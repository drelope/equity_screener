"""
Populate fundamentals.periodic_financials from stored SEC XBRL companyfacts.

DB-only: reads the normalized us-gaap facts already stored in raw.companyfacts
(one payload per issuer CIK) and upserts one row per fiscal period into
fundamentals.periodic_financials. No SEC / Yahoo / OpenBB calls are made, so
this is runnable offline and is idempotent.

Because the stored payloads are large, only the canonical periodic-financial
us-gaap concepts are shipped across the wire; ``extract_periodic_financials``
reads exactly those tags, so the resulting rows are unchanged.

The universe is processed in keyset-paginated batches (see ``BATCH_SIZE``),
so at most one batch of payloads is in memory at a time. Materializing all
~6,000 issuer slices at once takes gigabytes, which pinned the stage against
the unit's MemoryMax and left it thrashing in reclaim for hours.

Usage:
    python -m scripts.populate_fundamentals
    python -m scripts.populate_fundamentals --tickers ACR-PD,ACR-PC
    python -m scripts.populate_fundamentals --limit 25
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine
from src.crispdm.fundamentals import extract_periodic_financials
from src.crispdm.xbrl_tags import PERIODIC_FINANCIAL_CONCEPTS

# Issuer payloads per batch. The full universe at once is gigabytes of jsonb
# slices; a batch keeps the stage well under the unit's MemoryHigh while still
# committing progress every couple hundred issuers instead of once at the end.
BATCH_SIZE = 250


@dataclass(frozen=True)
class FundamentalsResult:
    """What the stage actually did, so main() can fail on a stage that did nothing."""

    candidates: int
    securities: int
    periods: int
    errors: int


def _candidate_filters(tickers=None):
    """Shared WHERE clauses so count and load agree on the universe."""
    clauses = ["cf.cik IS NOT NULL", "s.active = TRUE", "s.dividend = TRUE"]
    params = {}
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [ticker.upper() for ticker in tickers]
    return " AND ".join(clauses), params


def count_candidates(conn, tickers=None, limit=None):
    """How many securities the stage will process; caps ``limit`` if given."""
    where, params = _candidate_filters(tickers)
    count = conn.execute(
        text(f"""
        SELECT count(*)
        FROM raw.companyfacts cf
        JOIN reference.securities s ON s.cik = cf.cik
        WHERE {where}
    """),
        params,
    ).scalar_one()
    return min(count, limit) if limit is not None else count


def load_candidates(conn, tickers=None, limit=None, after_security_id=None):
    """One batch of securities with a stored companyfacts payload.

    The companyfacts payload is per-issuer CIK but periodic financials are
    stored per security_id, so each CIK's fact slice is extracted once and
    fanned out to every active, dividend-flagged security sharing that CIK.

    ``after_security_id`` advances the keyset cursor: pass the last row's
    ``security_id`` from the previous batch to get the next page in the same
    ``ORDER BY s.security_id`` order.
    """
    where, params = _candidate_filters(tickers)
    params["concepts"] = list(PERIODIC_FINANCIAL_CONCEPTS)

    if after_security_id is not None:
        where += " AND s.security_id > :after_security_id"
        params["after_security_id"] = after_security_id

    limit_sql = " LIMIT :limit" if limit is not None else ""
    if limit is not None:
        params["limit"] = limit

    return (
        conn.execute(
            text(f"""
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
    """),
            params,
        )
        .mappings()
        .all()
    )


def upsert_periodic_financials(conn, security_id, rows):
    """Upsert one fundamentals.periodic_financials row per (period, vintage).

    ``filed`` is part of the conflict key because a period legitimately appears
    more than once: the original filing and each later restatement are distinct
    observations, and collapsing them would destroy the ability to resolve an
    as-of date correctly.
    """
    inserted = 0
    for row in rows:
        result = conn.execute(
            text("""
            INSERT INTO fundamentals.periodic_financials
                (security_id, period_end, fiscal_year, fiscal_period, filed,
                 revenue, gross_profit, cost_of_revenue, operating_income, net_income, eps, cash,
                 assets, liabilities, debt, equity, operating_cash_flow,
                 capital_expenditures, free_cash_flow, share_repurchases,
                 depreciation_amortization, interest_expense, shares_outstanding,
                 current_assets, current_liabilities,
                 debt_maturing_12m, debt_maturing_year_2,
                 committed_undrawn_facility,
                 source, retrieved_at)
            VALUES (:security_id, :period_end, :fiscal_year, :fiscal_period, :filed,
                    :revenue, :gross_profit, :cost_of_revenue, :operating_income, :net_income, :eps,
                    :cash, :assets, :liabilities, :debt, :equity,
                    :operating_cash_flow, :capital_expenditures,
                    :free_cash_flow, :share_repurchases,
                    :depreciation_amortization,
                    :interest_expense, :shares_outstanding,
                    :current_assets, :current_liabilities,
                    :debt_maturing_12m, :debt_maturing_year_2,
                    :committed_undrawn_facility,
                    :source, now())
            ON CONFLICT (security_id, period_end, fiscal_period, filed) DO UPDATE SET
                fiscal_year = EXCLUDED.fiscal_year,
                revenue = EXCLUDED.revenue,
                gross_profit = EXCLUDED.gross_profit,
                cost_of_revenue = EXCLUDED.cost_of_revenue,
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
                share_repurchases = EXCLUDED.share_repurchases,
                depreciation_amortization = EXCLUDED.depreciation_amortization,
                interest_expense = EXCLUDED.interest_expense,
                shares_outstanding = EXCLUDED.shares_outstanding,
                current_assets = EXCLUDED.current_assets,
                current_liabilities = EXCLUDED.current_liabilities,
                debt_maturing_12m = EXCLUDED.debt_maturing_12m,
                committed_undrawn_facility = EXCLUDED.committed_undrawn_facility,
                debt_maturing_year_2 = EXCLUDED.debt_maturing_year_2,
                source = EXCLUDED.source,
                retrieved_at = now()
        """),
            {
                "security_id": security_id,
                "period_end": row.get("period_end"),
                "fiscal_year": row.get("fiscal_year"),
                "fiscal_period": row.get("fiscal_period") or "FY",
                "filed": row.get("filed"),
                "revenue": row.get("revenue"),
                "gross_profit": row.get("gross_profit"),
                "cost_of_revenue": row.get("cost_of_revenue"),
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
                "share_repurchases": row.get("share_repurchases"),
                "depreciation_amortization": row.get("depreciation_amortization"),
                "interest_expense": row.get("interest_expense"),
                "shares_outstanding": row.get("shares_outstanding"),
                "current_assets": row.get("current_assets"),
                "current_liabilities": row.get("current_liabilities"),
                "debt_maturing_12m": row.get("debt_maturing_12m"),
                "committed_undrawn_facility": row.get("committed_undrawn_facility"),
                "debt_maturing_year_2": row.get("debt_maturing_year_2"),
                "source": row.get("source") or "SEC_XBRL",
            },
        )
        inserted += max(result.rowcount, 0)
    return inserted


def populate_fundamentals(tickers=None, limit=None, batch_size=BATCH_SIZE):
    """Build fundamentals.periodic_financials from stored XBRL payloads."""
    periods = securities = errors = 0
    processed = 0
    # The run date is the ceiling for a period_end: a period that has not ended
    # cannot have been reported. Passed to the extractor so a forward-dated XBRL
    # context never reaches the stored table.
    run_date = date.today()

    with engine.connect() as conn:
        total = count_candidates(conn, tickers=tickers, limit=limit)

    last_id = None
    remaining = total
    while remaining > 0:
        take = min(batch_size, remaining)
        # One transaction per batch: short enough that the AccessShareLocks the
        # load takes on reference.securities / raw.companyfacts are released
        # between batches instead of being held for the whole stage, and a
        # crash loses at most one batch of upserts instead of everything.
        with engine.begin() as conn:
            batch = load_candidates(conn, tickers=tickers, limit=take, after_security_id=last_id)
            if not batch:
                break
            for candidate in batch:
                # A savepoint per issuer. One bad statement aborts it and every
                # later statement then fails with InFailedSqlTransaction. That
                # turns one root cause into one error per remaining candidate,
                # and the resulting error text points at the wrong issuer.
                try:
                    with conn.begin_nested():
                        payload = {"full_facts": {"facts": {"us-gaap": candidate["us_gaap"]}}}
                        rows = extract_periodic_financials(payload, as_of=run_date)
                        if rows:
                            periods += upsert_periodic_financials(
                                conn, candidate["security_id"], rows
                            )
                            securities += 1
                except Exception as exc:
                    errors += 1
                    if errors <= 5:
                        print(f"  Error extracting {candidate['ticker']}: {exc}")
            last_id = batch[-1]["security_id"]
        remaining -= len(batch)
        processed += len(batch)
        print(f"  {processed}/{total} candidates processed ({periods} period rows)", flush=True)

    result = FundamentalsResult(
        candidates=total, securities=securities, periods=periods, errors=errors
    )
    # The checkmark is conditional because it used to print over a stage that had
    # written nothing at all: 8,350 errors, 0 rows, and a success tick in the
    # nightly log, which run_full_etl and populate_audit both recorded as ok.
    failed = result.candidates > 0 and result.periods == 0
    print(f"\n{'✗' if failed else '✓'} Fundamentals.periodic_financials from stored XBRL:")
    print(f"  Candidates: {result.candidates}")
    print(f"  Securities: {result.securities}")
    print(f"  Fiscal-period rows upserted: {result.periods}")
    print(f"  Errors: {result.errors}")
    if result.candidates:
        print(f"  Error rate: {result.errors}/{result.candidates}")
    if failed:
        print(
            "  No rows were written. The stored data is unchanged, but the stage "
            "did not do its job -- most often a migration is missing.",
            file=sys.stderr,
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated tickers, e.g. 'AAPL,MSFT'")
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit to the first N securities (for testing)"
    )
    args = parser.parse_args()

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()] if args.tickers else None
    )

    try:
        result = populate_fundamentals(tickers=tickers, limit=args.limit)
    except Exception as exc:
        print(f"✗ Error populating fundamentals: {exc}", file=sys.stderr)
        return 1

    # A stage that processed candidates and wrote nothing has failed, whatever
    # its internal error count says. main() used to discard the return value and
    # return 0 unconditionally, so a wholly broken stage exited 0 and the nightly
    # was audited as successful.
    if result.candidates > 0 and result.periods == 0:
        print(
            f"✗ populate_fundamentals wrote 0 of {result.candidates} candidates "
            f"({result.errors} errors); treating the stage as failed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
