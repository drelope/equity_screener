"""
Populate fundamentals.periodic_financials from stored SEC XBRL companyfacts.

DB-only: reads the normalized us-gaap facts already stored in raw.companyfacts
(one payload per issuer CIK) and upserts one row per fiscal period into
fundamentals.periodic_financials. No SEC / Yahoo / OpenBB calls are made, so
this is runnable offline and is idempotent.

Because the stored payloads are large, only the canonical periodic-financial
us-gaap concepts are shipped across the wire; ``extract_periodic_financials``
reads exactly those tags, so the resulting rows are unchanged.

Usage:
    python -m scripts.populate_fundamentals
    python -m scripts.populate_fundamentals --tickers ACR-PD,ACR-PC
    python -m scripts.populate_fundamentals --limit 25
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine
from src.crispdm.fundamentals import extract_periodic_financials
from src.crispdm.xbrl_tags import PERIODIC_FINANCIAL_CONCEPTS


def load_candidates(conn, tickers=None, limit=None):
    """Securities with a stored companyfacts payload, slimmed to the facts used.

    The companyfacts payload is per-issuer CIK but periodic financials are
    stored per security_id, so each CIK's fact slice is extracted once and
    fanned out to every security sharing that CIK.
    """
    clauses = ["cf.cik IS NOT NULL"]
    params = {"concepts": list(PERIODIC_FINANCIAL_CONCEPTS)}
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [ticker.upper() for ticker in tickers]
    where = " AND ".join(clauses)

    limit_sql = " LIMIT :limit" if limit is not None else ""
    if limit is not None:
        params["limit"] = limit

    return conn.execute(text(f"""
        SELECT s.security_id, s.ticker, s.cik,
               facts.us_gaap AS us_gaap
        FROM raw.companyfacts cf
        JOIN LATERAL (
            SELECT COALESCE(
                (SELECT jsonb_object_agg(e.k, e.v)
                 FROM jsonb_each(jsonb_extract_path(cf.raw_payload, 'facts', 'us-gaap')) AS e(k, v)
                 WHERE e.k = ANY(:concepts)),
                '{{}}'::jsonb) AS us_gaap
        ) facts ON TRUE
        JOIN reference.securities s ON s.cik = cf.cik
        WHERE {where}
        ORDER BY s.security_id
        {limit_sql}
    """), params).mappings().all()


def upsert_periodic_financials(conn, security_id, rows):
    """Upsert one fundamentals.periodic_financials row per fiscal period."""
    inserted = 0
    for row in rows:
        result = conn.execute(text("""
            INSERT INTO fundamentals.periodic_financials
                (security_id, period_end, fiscal_year, fiscal_period,
                 revenue, operating_income, net_income, eps, cash, assets,
                 liabilities, debt, equity, operating_cash_flow,
                 capital_expenditures, free_cash_flow, source, retrieved_at)
            VALUES (:security_id, :period_end, :fiscal_year, :fiscal_period,
                    :revenue, :operating_income, :net_income, :eps, :cash,
                    :assets, :liabilities, :debt, :equity,
                    :operating_cash_flow, :capital_expenditures,
                    :free_cash_flow, :source, now())
            ON CONFLICT (security_id, period_end, fiscal_period) DO UPDATE SET
                fiscal_year = EXCLUDED.fiscal_year,
                revenue = EXCLUDED.revenue,
                operating_income = EXCLUDED.operating_income,
                net_income = EXCLUDED.net_income,
                eps = EXCLUDED.eps,
                cash = EXCLUDED.cash,
                assets = EXCLUDED.assets,
                liabilities = EXCLUDED.liabilities,
                debt = EXCLUDED.debt,
                equity = EXCLUDED.equity,
                operating_cash_flow = EXCLUDED.operating_cash_flow,
                capital_expenditures = EXCLUDED.capital_expenditures,
                free_cash_flow = EXCLUDED.free_cash_flow,
                source = EXCLUDED.source,
                retrieved_at = now()
        """), {
            "security_id": security_id,
            "period_end": row.get("period_end"),
            "fiscal_year": row.get("fiscal_year"),
            "fiscal_period": row.get("fiscal_period") or "FY",
            "revenue": row.get("revenue"),
            "operating_income": row.get("operating_income"),
            "net_income": row.get("net_income"),
            "eps": row.get("eps"),
            "cash": row.get("cash"),
            "assets": row.get("assets"),
            "liabilities": row.get("liabilities"),
            "debt": row.get("debt"),
            "equity": row.get("equity"),
            "operating_cash_flow": row.get("operating_cash_flow"),
            "capital_expenditures": row.get("capital_expenditures"),
            "free_cash_flow": row.get("free_cash_flow"),
            "source": row.get("source") or "SEC_XBRL",
        })
        inserted += max(result.rowcount, 0)
    return inserted


def populate_fundamentals(tickers=None, limit=None):
    """Build fundamentals.periodic_financials from stored XBRL payloads."""
    periods = securities = errors = 0

    with engine.begin() as conn:
        candidates = load_candidates(conn, tickers=tickers, limit=limit)
        for candidate in candidates:
            try:
                payload = {"full_facts": {"facts": {"us-gaap": candidate["us_gaap"]}}}
                rows = extract_periodic_financials(payload)
                if rows:
                    periods += upsert_periodic_financials(conn, candidate["security_id"], rows)
                    securities += 1
            except Exception as exc:
                errors += 1
                if errors <= 5:
                    print(f"  Error extracting {candidate['ticker']}: {exc}")

    print("\n✓ Populated fundamentals.periodic_financials from stored XBRL:")
    print(f"  Securities: {securities}")
    print(f"  Fiscal-period rows upserted: {periods}")
    print(f"  Errors: {errors}")
    return periods


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated tickers, e.g. 'AAPL,MSFT'")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit to the first N securities (for testing)")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] if args.tickers else None

    try:
        populate_fundamentals(tickers=tickers, limit=args.limit)
        return 0
    except Exception as exc:
        print(f"✗ Error populating fundamentals: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())