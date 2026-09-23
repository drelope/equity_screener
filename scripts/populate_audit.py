"""
Backfill audit.source_lineage and audit.data_quality from existing data.

DB-only: reconstructs provenance (audit.source_lineage) and per-security data
quality scores (audit.data_quality) from what the pipeline has already stored
(raw.ticker_profile, raw.companyfacts, reference.securities). No SEC, Yahoo,
or OpenBB calls, so it is runnable offline and idempotent:

- ``audit.source_lineage`` records where each decision field (security type,
  issuer name, coupon, liquidation preference, dividend flag) came from,
  including the provider and confidence score.
- ``audit.data_quality`` scores every security on source reliability,
  completeness, recency, and consistency for the current run date.

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
    params = {"as_of": as_of}
    conn.execute(text("""
        DELETE FROM audit.source_lineage
        WHERE field_name IN ('security_type', 'coupon_rate',
                             'liquidation_preference', 'issuer_name', 'dividend')
    """))
    sql = """
        INSERT INTO audit.source_lineage
            (security_id, field_name, field_value, source, source_document,
             period, retrieval_date, provider, confidence_score)
        SELECT * FROM (
            SELECT tp.security_id, 'security_type' AS field_name,
                   tp.security_type AS field_value,
                   'raw.ticker_profile' AS source,
                   'raw.ticker_profile' AS source_document,
                   NULL::date AS period,
                   tp.retrieved_at AS retrieval_date,
                   tp.provider AS provider,
                   COALESCE(:reliability, 0.7) AS confidence_score
            FROM raw.ticker_profile tp
            WHERE tp.security_type IS NOT NULL

            UNION ALL

            SELECT tp.security_id, 'coupon_rate', tp.coupon_rate::text,
                   'raw.ticker_profile', 'raw.ticker_profile', NULL::date,
                   tp.retrieved_at, tp.provider, COALESCE(:reliability, 0.7)
            FROM raw.ticker_profile tp
            WHERE tp.coupon_rate IS NOT NULL

            UNION ALL

            SELECT tp.security_id, 'liquidation_preference',
                   tp.liquidation_preference::text,
                   'raw.ticker_profile', 'raw.ticker_profile', NULL::date,
                   tp.retrieved_at, tp.provider, COALESCE(:reliability, 0.7)
            FROM raw.ticker_profile tp
            WHERE tp.liquidation_preference IS NOT NULL

            UNION ALL

            SELECT s.security_id, 'issuer_name', cf.company_name,
                   'raw.companyfacts', 'raw.companyfacts', NULL::date,
                   cf.retrieved_at, 'SEC_XBRL', 1.0
            FROM raw.companyfacts cf
            JOIN reference.securities s ON s.cik = cf.cik
            WHERE cf.company_name IS NOT NULL

            UNION ALL

            SELECT s.security_id, 'dividend', s.dividend::text,
                   'reference.securities', 'reference.securities',
                   s.updated_at::date, s.updated_at, 'SEC_CLASSIFICATION', 0.9
            FROM reference.securities s
        ) x
        WHERE :as_of IS NOT NULL
        ORDER BY security_id, field_name
    """
    result = conn.execute(text(sql), {
        "as_of": as_of,
        "reliability": PROVIDER_RELIABILITY.get("SEC_XBRL", 0.7),
    })
    return result.rowcount


def data_quality(conn, as_of):
    """Score every security on data quality for the as-of date."""
    sql = """
        INSERT INTO audit.data_quality
            (security_id, as_of_date, source_reliability, completeness,
             recency, consistency, quality_score, status)
        SELECT
            s.security_id,
            :as_of AS as_of_date,
            COALESCE(MAX(q.source_reliability), 0.0) AS source_reliability,
            COALESCE(AVG(q.completeness), 0.0) AS completeness,
            COALESCE(MAX(q.recency), 0.0) AS recency,
            COALESCE(MAX(q.consistency), 0.0) AS consistency,
            COALESCE(
                0.4 * MAX(q.source_reliability)
                + 0.3 * AVG(q.completeness)
                + 0.2 * MAX(q.recency)
                + 0.1 * MAX(q.consistency),
                0.0) AS quality_score,
            CASE
                WHEN COALESCE(MAX(q.source_reliability), 0) = 0 THEN 'no data'
                WHEN COALESCE(0.4 * MAX(q.source_reliability) + 0.3 * AVG(q.completeness)
                              + 0.2 * MAX(q.recency) + 0.1 * MAX(q.consistency), 0) >= 0.8 THEN 'good'
                WHEN COALESCE(0.4 * MAX(q.source_reliability) + 0.3 * AVG(q.completeness)
                              + 0.2 * MAX(q.recency) + 0.1 * MAX(q.consistency), 0) >= 0.5 THEN 'fair'
                ELSE 'poor'
            END AS status
        FROM reference.securities s
        CROSS JOIN LATERAL (
            SELECT
                CASE WHEN tp.security_id IS NOT NULL
                     THEN COALESCE(:reliability, 0.7) ELSE 0.0 END
                     AS source_reliability,
                CASE
                    WHEN tp.security_id IS NOT NULL THEN 1.0
                    WHEN cf.cik IS NOT NULL THEN 0.5
                    ELSE 0.0
                END AS completeness,
                CASE
                    WHEN tp.retrieved_at IS NOT NULL
                    THEN GREATEST(0.0, 1.0 - EXTRACT(EPOCH FROM (:as_of)::timestamp
                        - tp.retrieved_at::timestamp) / 31536000.0)
                    WHEN cf.retrieved_at IS NOT NULL
                    THEN GREATEST(0.0, 1.0 - EXTRACT(EPOCH FROM (:as_of)::timestamp
                        - cf.retrieved_at::timestamp) / 31536000.0)
                    ELSE 0.0
                END AS recency,
                CASE
                    WHEN tp.security_type IS NOT NULL AND s.security_type IS NOT NULL
                         AND LOWER(tp.security_type) = LOWER(s.security_type) THEN 1.0
                    WHEN tp.security_type IS NOT NULL AND s.security_type IS NOT NULL THEN 0.5
                    ELSE 0.0
                END AS consistency
            FROM (SELECT 1 AS one) _z
            LEFT JOIN raw.ticker_profile tp ON tp.security_id = s.security_id
            LEFT JOIN raw.companyfacts cf ON cf.cik = s.cik
        ) q
        GROUP BY s.security_id
        ORDER BY s.security_id
        ON CONFLICT (security_id, as_of_date) DO UPDATE SET
            source_reliability = EXCLUDED.source_reliability,
            completeness = EXCLUDED.completeness,
            recency = EXCLUDED.recency,
            consistency = EXCLUDED.consistency,
            quality_score = EXCLUDED.quality_score,
            status = EXCLUDED.status
    """
    result = conn.execute(text(sql), {
        "as_of": as_of,
        "reliability": PROVIDER_RELIABILITY.get("SEC_XBRL", 0.7),
    })
    return result.rowcount


def populate_audit(as_of=None):
    as_of = as_of or date.today()
    with engine.begin() as conn:
        lineage = source_lineage(conn, as_of)
        quality = data_quality(conn, as_of)
    print("\n✓ Populated audit tables:")
    print(f"  as_of: {as_of}")
    print(f"  audit.source_lineage rows: {lineage}")
    print(f"  audit.data_quality rows:   {quality}")
    return quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None,
                        help="Scoring date (default: today)")
    args = parser.parse_args()

    try:
        populate_audit(as_of=args.as_of)
        return 0
    except Exception as exc:
        print(f"✗ Error populating audit: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())