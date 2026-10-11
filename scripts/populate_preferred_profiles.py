"""
Populate raw.ticker_profile for the preferred dividend universe from local DB data.

DB-only: does not call SEC, Yahoo, or OpenBB. The preferred list is the
active dividend-payer universe in reference.securities (the same gating set
used by the downstream ETL stages). SEC Company Facts are issuer-level and do
not identify which preferred series a numeric fact belongs to, so extracted
terms are retained as evidence but not assigned to an individual security.

Populating this durable handoff is the prerequisite for
``python -m scripts.populate_companyfacts --preferred-facts``, which reads
the preferred rows in raw.ticker_profile and downloads SEC submissions +
company facts for each.

Usage:
    python -m scripts.populate_preferred_profiles
    python -m scripts.populate_preferred_profiles --tickers ACR-PD,ACR-PC
    python -m scripts.populate_preferred_profiles --limit 100
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.populate_dividend_data import extract_security_series
from src.crispdm.db import engine
from src.crispdm.sec_client import (
    PREFERRED_COUPON_CONCEPTS,
    PREFERRED_LIQUIDATION_CONCEPTS,
    PREFERRED_PAR_VALUE_CONCEPTS,
    extract_preferred_terms_from_companyfacts,
)
from src.crispdm.stage import stage_exit_code
from src.crispdm.ticker_profile_store import SEC_XBRL_SCOPE, upsert_ticker_profile

DEFAULT_PROVIDER = "SEC_XBRL"

PREFERRED_CONCEPTS = (
    PREFERRED_COUPON_CONCEPTS + PREFERRED_LIQUIDATION_CONCEPTS + PREFERRED_PAR_VALUE_CONCEPTS
)


def _extract_sec_terms(raw_payload):
    """Best-effort coupon_rate/liquidation_preference from a stored payload."""
    if not isinstance(raw_payload, dict):
        return {}
    try:
        return extract_preferred_terms_from_companyfacts(raw_payload)
    except Exception:
        return {}


def load_preferred_candidates(conn, tickers=None, limit=None):
    """Active dividend securities (one row per ticker) with any stored facts.

    The stored SEC companyfacts payload can be very large, so instead of
    shipping the whole JSONB across the wire only the preferred-stock XBRL
    concepts (coupon + liquidation/par-value tags) are extracted in SQL and
    rebuilt into a slim payload. ``extract_preferred_terms_from_companyfacts``
    reads exactly these tags, so the resulting terms are unchanged.
    """
    clauses = ["s.active = TRUE", "s.dividend = TRUE"]
    params = {"preferred_concepts": list(PREFERRED_CONCEPTS)}
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [ticker.upper() for ticker in tickers]
    where = " AND ".join(clauses)

    limit_sql = " LIMIT :limit" if limit is not None else ""
    if limit is not None:
        params["limit"] = limit

    return (
        conn.execute(
            text(f"""
        SELECT DISTINCT ON (s.ticker)
               s.security_id, s.ticker, s.cik, s.security_name, s.security_type,
               slim.raw_payload
        FROM reference.securities s
        LEFT JOIN LATERAL (
            SELECT CASE WHEN EXISTS (
                       SELECT 1 FROM raw.companyfacts cf
                       WHERE cf.cik = s.cik
                   ) THEN jsonb_build_object(
                       'full_facts',
                       jsonb_build_object(
                           'facts',
                           jsonb_build_object(
                               'us-gaap',
                               COALESCE(
                                   (SELECT jsonb_object_agg(e.k, e.v)
                                    FROM raw.companyfacts cf,
                                         jsonb_each(jsonb_extract_path(cf.raw_payload, 'facts', 'us-gaap')) AS e(k, v)
                                    WHERE cf.cik = s.cik
                                      AND e.k = ANY(:preferred_concepts)),
                                   '{{}}'::jsonb
                               )
                           )
                       )
                   ) ELSE NULL END AS raw_payload
        ) slim ON TRUE
        WHERE {where}
        ORDER BY s.ticker, s.updated_at DESC NULLS LAST, s.security_id
        {limit_sql}
    """),
            params,
        )
        .mappings()
        .all()
    )


def upsert_preferred_profile(conn, candidate):
    """Build and upsert one raw.ticker_profile row from local reference data."""
    security_name = candidate.get("security_name")
    security_type = candidate.get("security_type") or "preferred stock"
    series_type = extract_security_series(security_name)
    if not series_type or "preferred" not in series_type.lower():
        series_type = security_type

    sec_terms = _extract_sec_terms(candidate.get("raw_payload"))

    raw_payload = {"sec_xbrl_scope": SEC_XBRL_SCOPE}
    if any(value is not None for value in sec_terms.values()):
        raw_payload["sec_xbrl"] = sec_terms

    row = {
        "security_id": candidate["security_id"],
        "ticker": candidate["ticker"],
        "provider": DEFAULT_PROVIDER,
        "sector": None,
        "industry": None,
        "security_type": series_type,
        "coupon_type": None,
        "coupon_rate": None,
        "fixed_period_end": None,
        "floating_spread": None,
        "tax_status": None,
        "call_date": None,
        "liquidation_preference": None,
        "raw_payload": json.dumps(raw_payload),
    }
    # Owns no typed column: per-series terms are not derivable from issuer-level
    # SEC facts, and security_type is owned by the name-parse writers. Typed
    # values here only seed a brand-new row; the SEC evidence is refreshed.
    return upsert_ticker_profile(
        conn, row, loader="populate_preferred_profiles", owned_columns=()
    )


def populate_preferred_profiles(tickers=None, limit=None):
    """Persist raw.ticker_profile rows for the preferred dividend universe."""
    inserted = errors = 0
    missing_facts = []

    with engine.begin() as conn:
        candidates = load_preferred_candidates(conn, tickers=tickers, limit=limit)
        for candidate in candidates:
            try:
                insert = upsert_preferred_profile(conn, candidate)
                inserted += insert
                if candidate.get("raw_payload") is None:
                    missing_facts.append(candidate["ticker"])
            except Exception as exc:
                errors += 1
                if errors <= 5:
                    print(f"  Error populating profile for {candidate['ticker']}: {exc}")

    print("\n✓ Populated raw.ticker_profile from reference.securities:")
    print(f"  Candidates: {len(candidates)}")
    print(f"  Inserted/refreshed: {inserted}")
    print(f"  Errors: {errors}")
    print(f"  Missing SEC companyfacts (coupon/liq will be NULL): {len(missing_facts)}")
    if missing_facts:
        print("  Sample missing:", ", ".join(missing_facts[:10]))
    return len(candidates), inserted, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated tickers, e.g. 'ACR-PD,ACR-PC'")
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit to the first N securities (for testing)"
    )
    args = parser.parse_args()

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()] if args.tickers else None
    )

    try:
        candidates, inserted, errors = populate_preferred_profiles(
            tickers=tickers, limit=args.limit
        )
        return stage_exit_code("populate_preferred_profiles", candidates, inserted, errors=errors)
    except Exception as exc:
        print(f"✗ Error populating preferred profiles: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
