"""
Backfill audit.source_lineage and audit.data_quality from existing data.

DB-only: reconstructs provenance (audit.source_lineage) and per-security data
quality scores (audit.data_quality) from what the pipeline has already stored
(raw.ticker_profile, raw.companyfacts, reference.securities). No SEC, Yahoo,
or OpenBB calls, so it is runnable offline and idempotent:

- ``audit.source_lineage`` records where each decision field (security type,
  issuer name, coupon, liquidation preference, dividend flag) came from,
  including the provider and confidence score.
- ``audit.data_quality`` scores every active security on source reliability,
  completeness, recency, and consistency for the current run date. Every
  component is bounded to [0, 1]; recency needs the explicit upper clamp
  because ``as_of`` is midnight while a row retrieved later the same day would
  otherwise score above 1.

Only active securities are audited, so deactivated tickers do not dilute the
coverage and quality metrics.

Usage:
    python -m scripts.populate_audit
    python -m scripts.populate_audit --securities "0001090872"
    python -m scripts.populate_audit --as-of 2026-09-21
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine
from src.crispdm.versioning import FEATURE_SET_V1, MODEL_VERSION, compute_feature_set_hash

#: Provider -> sourcing reliability used by the confidence/heuristic scores.
PROVIDER_RELIABILITY = {
    "SEC_XBRL": 1.0,
    "SEC_SUBMISSIONS": 1.0,
    "YFINANCE": 0.8,
    "OPENBB": 0.9,
}


def source_lineage(conn, as_of):
    """Insert provenance rows for fields derivable from stored data.

    Re-runs replace the prior provenance view for the backfilled fields rather
    than appending duplicate rows.
    """
    conn.execute(
        text("""
        DELETE FROM audit.source_lineage
        WHERE field_name IN ('security_type', 'coupon_rate',
                             'liquidation_preference', 'issuer_name', 'dividend')
    """)
    )
    sql = """
        INSERT INTO audit.source_lineage
            (security_id, field_name, field_value, source, source_document,
             period, retrieval_date, provider, confidence_score,
             model_version, feature_set_hash)
        SELECT x.*, :model_version, :feature_set_hash FROM (
            SELECT tp.security_id, 'security_type' AS field_name,
                   tp.security_type AS field_value,
                   'raw.ticker_profile' AS source,
                   'raw.ticker_profile' AS source_document,
                   NULL::date AS period,
                   tp.retrieved_at AS retrieval_date,
                   tp.provider AS provider,
                   COALESCE(:reliability, 0.7) AS confidence_score
            FROM raw.ticker_profile tp
            JOIN reference.securities s ON s.security_id = tp.security_id AND s.active = TRUE
            WHERE tp.security_type IS NOT NULL

            UNION ALL

            SELECT tp.security_id, 'coupon_rate', tp.coupon_rate::text,
                   'raw.ticker_profile', 'raw.ticker_profile', NULL::date,
                   tp.retrieved_at, tp.provider, COALESCE(:reliability, 0.7)
            FROM raw.ticker_profile tp
            JOIN reference.securities s ON s.security_id = tp.security_id AND s.active = TRUE
            WHERE tp.coupon_rate IS NOT NULL

            UNION ALL

            SELECT tp.security_id, 'liquidation_preference',
                   tp.liquidation_preference::text,
                   'raw.ticker_profile', 'raw.ticker_profile', NULL::date,
                   tp.retrieved_at, tp.provider, COALESCE(:reliability, 0.7)
            FROM raw.ticker_profile tp
            JOIN reference.securities s ON s.security_id = tp.security_id AND s.active = TRUE
            WHERE tp.liquidation_preference IS NOT NULL

            UNION ALL

            SELECT s.security_id, 'issuer_name', cf.company_name,
                   'raw.companyfacts', 'raw.companyfacts', NULL::date,
                   cf.retrieved_at, 'SEC_XBRL', 1.0
            FROM raw.companyfacts cf
            JOIN reference.securities s ON s.cik = cf.cik AND s.active = TRUE
            WHERE cf.company_name IS NOT NULL

            UNION ALL

            SELECT s.security_id, 'dividend', s.dividend::text,
                   'reference.securities', 'reference.securities',
                   s.updated_at::date, s.updated_at, 'SEC_CLASSIFICATION', 0.9
            FROM reference.securities s
            WHERE s.active = TRUE
        ) x
        WHERE :as_of IS NOT NULL
        ORDER BY security_id, field_name
    """
    result = conn.execute(
        text(sql),
        {
            "as_of": as_of,
            "reliability": PROVIDER_RELIABILITY.get("SEC_XBRL", 0.7),
            "model_version": MODEL_VERSION,
            "feature_set_hash": compute_feature_set_hash(FEATURE_SET_V1),
        },
    )
    return result.rowcount


def lineage_provenance_gaps(conn):
    """Count lineage rows that do not name their source, model version and feature set.

    Every row written by ``source_lineage`` carries all three, so a nonzero count
    means a row came from a writer that predates the stamp (or bypassed it).
    """
    return int(
        conn.execute(
            text("""
        SELECT count(*) FROM audit.source_lineage
        WHERE source IS NULL OR model_version IS NULL OR feature_set_hash IS NULL
    """)
        ).scalar()
    )


def data_quality(conn, as_of):
    """Score every active security on data quality for the as-of date.

    Re-derived 2026-10-09 (WS4 step 5, data-health-workstreams.md) over the
    sources the pipeline actually populates for the whole active universe.
    ``raw.companyfacts`` covers the fundamental side of almost every active
    security, so a security is only ``no data`` when *neither* companyfacts nor
    a ticker profile exists -- not merely because it is not a dividend payer and
    therefore unprofiled. The components are:

    - ``source_reliability``: the strongest contributing source -- the profile
      provider for ``raw.ticker_profile`` rows (WS4 item 9: an OpenBB-sourced
      profile must not read as SEC_XBRL), or SEC XBRL when the issuer has
      ``raw.companyfacts``.
    - ``completeness``: full market metadata (profile) 1.0, fundamentals only
      (companyfacts) 0.5, nothing 0.0.
    - ``recency``: newest retrieval in either source, decaying over a year,
      clamped to [0, 1].
    - ``consistency``: ``security_type`` compared after normalising the OpenBB
      spelling to the reference class (WS4 item 8: ``"Common Stock, par value
      $0.01 per share"`` must agree with ``common_stock``, not be penalised for
      the wording).

    The ``no data`` band is reserved for securities with no source at all.
    """
    sql = """
        INSERT INTO audit.data_quality
            (security_id, as_of_date, source_reliability, completeness,
             recency, consistency, quality_score, status)
        SELECT
            s.security_id,
            :as_of AS as_of_date,
            q.source_reliability,
            q.completeness,
            q.recency,
            q.consistency,
            COALESCE(
                0.4 * q.source_reliability
                + 0.3 * q.completeness
                + 0.2 * q.recency
                + 0.1 * q.consistency,
                0.0) AS quality_score,
            CASE
                WHEN COALESCE(q.source_reliability, 0) = 0 THEN 'no data'
                WHEN COALESCE(0.4 * q.source_reliability + 0.3 * q.completeness
                              + 0.2 * q.recency + 0.1 * q.consistency, 0) >= 0.8 THEN 'good'
                WHEN COALESCE(0.4 * q.source_reliability + 0.3 * q.completeness
                              + 0.2 * q.recency + 0.1 * q.consistency, 0) >= 0.5 THEN 'fair'
                ELSE 'poor'
            END AS status
        FROM reference.securities s
        CROSS JOIN LATERAL (
            SELECT
                GREATEST(
                    CASE
                        WHEN tp.security_id IS NOT NULL
                             AND LOWER(COALESCE(tp.provider, '')) LIKE '%openbb%'
                             THEN COALESCE(:openbb_reliability, 0.9)
                        WHEN tp.security_id IS NOT NULL
                             AND LOWER(COALESCE(tp.provider, '')) LIKE '%yfinance%'
                             THEN COALESCE(:yfinance_reliability, 0.8)
                        WHEN tp.security_id IS NOT NULL THEN COALESCE(:sec_reliability, 1.0)
                        ELSE 0.0
                    END,
                    CASE WHEN cf.cik IS NOT NULL THEN COALESCE(:sec_reliability, 1.0) ELSE 0.0 END
                ) AS source_reliability,
                CASE
                    WHEN tp.security_id IS NOT NULL THEN 1.0
                    WHEN cf.cik IS NOT NULL THEN 0.5
                    ELSE 0.0
                END AS completeness,
                CASE
                    WHEN tp.retrieved_at IS NOT NULL
                    THEN LEAST(1.0, GREATEST(0.0, 1.0 - EXTRACT(EPOCH FROM (:as_of)::timestamp
                        - tp.retrieved_at::timestamp) / 31536000.0))
                    WHEN cf.retrieved_at IS NOT NULL
                    THEN LEAST(1.0, GREATEST(0.0, 1.0 - EXTRACT(EPOCH FROM (:as_of)::timestamp
                        - cf.retrieved_at::timestamp) / 31536000.0))
                    ELSE 0.0
                END AS recency,
                CASE
                    WHEN tp.security_id IS NOT NULL AND tp.security_type IS NOT NULL
                         AND s.security_type IS NOT NULL
                         AND ((LOWER(tp.security_type) LIKE '%common%'
                               AND LOWER(s.security_type) LIKE '%common%')
                              OR (LOWER(tp.security_type) LIKE '%preferred%'
                                  AND LOWER(s.security_type) LIKE '%preferred%')
                              OR (LOWER(tp.security_type) NOT LIKE '%common%'
                                  AND LOWER(tp.security_type) NOT LIKE '%preferred%'
                                  AND LOWER(s.security_type) NOT LIKE '%common%'
                                  AND LOWER(s.security_type) NOT LIKE '%preferred%'))
                    THEN 1.0
                    WHEN tp.security_id IS NOT NULL AND tp.security_type IS NOT NULL
                         AND s.security_type IS NOT NULL THEN 0.5
                    ELSE 0.0
                END AS consistency
            FROM (SELECT 1 AS one) _z
            LEFT JOIN raw.ticker_profile tp ON tp.security_id = s.security_id
            LEFT JOIN raw.companyfacts cf ON cf.cik = s.cik
        ) q
        WHERE s.active = TRUE
        ORDER BY s.security_id
        ON CONFLICT (security_id, as_of_date) DO UPDATE SET
            source_reliability = EXCLUDED.source_reliability,
            completeness = EXCLUDED.completeness,
            recency = EXCLUDED.recency,
            consistency = EXCLUDED.consistency,
            quality_score = EXCLUDED.quality_score,
            status = EXCLUDED.status
    """
    result = conn.execute(
        text(sql),
        {
            "as_of": as_of,
            "sec_reliability": PROVIDER_RELIABILITY.get("SEC_XBRL", 1.0),
            "openbb_reliability": PROVIDER_RELIABILITY.get("OPENBB", 0.9),
            "yfinance_reliability": PROVIDER_RELIABILITY.get("YFINANCE", 0.8),
        },
    )
    return result.rowcount


def populate_audit(as_of=None):
    as_of = as_of or date.today()
    with engine.begin() as conn:
        lineage = source_lineage(conn, as_of)
        quality = data_quality(conn, as_of)
        gaps = lineage_provenance_gaps(conn)
    print("\n✓ Populated audit tables:")
    print(f"  as_of: {as_of}")
    print(f"  audit.source_lineage rows: {lineage}")
    print(f"  audit.data_quality rows:   {quality}")
    print(f"  lineage rows missing source/model/feature stamp: {gaps}")
    return quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="Scoring date (default: today)"
    )
    args = parser.parse_args()

    try:
        populate_audit(as_of=args.as_of)
        return 0
    except Exception as exc:
        print(f"✗ Error populating audit: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
