"""Keep raw.corporate_actions current from FMP's market-wide splits calendar.

``scripts.fetch_fmp_splits`` is a full history pull (one request per ticker, about
4,100 calls) and stays a manual backfill. This is the nightly-sized counterpart: one
call per 90-day window returns every split announced or recently effective, so a
nightly costs a couple of requests.

Rows use the same ``source_hash`` scheme as ``scripts.load_corporate_actions``, so a
split the full load already stored is recognised, not duplicated. A row seen again
has ``retrieved_at`` refreshed: that column means "last confirmed against the
provider", which is what the freshness check ages, and with insert-only semantics it
would only move when a brand-new split appeared. Tickers that match no tracked
security are skipped (the feed covers the whole market).

    python -m scripts.load_split_calendar                  # 30 days back, 90 ahead
    python -m scripts.load_split_calendar --back 365 --ahead 180
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text

from scripts.load_corporate_actions import split_rows
from scripts.load_dividend_calendar import fetch_window, windows
from src.crispdm import openbb_client as oc
from src.crispdm.db import engine, read_df

URL = "https://financialmodelingprep.com/stable/splits-calendar"

UPSERT = text(
    """
    INSERT INTO raw.corporate_actions
      (security_id, ticker, action_type, effective_date, numerator, denominator,
       ratio, source, source_hash)
    VALUES
      (CAST(:security_id AS uuid), :ticker, 'split', :effective_date, :numerator,
       :denominator, :ratio, :source, :source_hash)
    ON CONFLICT (source_hash) DO UPDATE SET retrieved_at = now()
    """
)


def calendar_split_rows(events: list[dict], securities: pd.DataFrame) -> list[dict]:
    """Insert parameters for calendar events on tracked securities only."""
    raw = pd.DataFrame(
        [
            {
                "ticker": e.get("symbol"),
                "date": e.get("date"),
                "numerator": e.get("numerator"),
                "denominator": e.get("denominator"),
            }
            for e in events
        ],
        columns=["ticker", "date", "numerator", "denominator"],
    )
    return [r for r in split_rows(raw, securities) if r["security_id"] is not None]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--back", type=int, default=30, help="Days before today to include.")
    parser.add_argument("--ahead", type=int, default=90, help="Days after today to include.")
    parser.add_argument(
        "--skip-if-no-key",
        action="store_true",
        help="Exit 0 instead of 1 when the FMP key is not configured (nightly use).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    key = oc._fmp_key()
    if not key:
        print("no FMP API key configured; cannot fetch the splits calendar")
        return 0 if args.skip_if_no_key else 1
    securities = read_df(
        "SELECT security_id::text AS security_id, ticker FROM reference.securities "
        "WHERE security_type = 'common_stock'"
    )
    today = date.today()
    total = 0
    for start, end in windows(
        today - timedelta(days=args.back), today + timedelta(days=args.ahead)
    ):
        rows = calendar_split_rows(fetch_window(start, end, key, url=URL), securities)
        total += len(rows)
        print(f"{start}..{end}: {len(rows)} splits on tracked securities", flush=True)
        if rows and not args.dry_run:
            with engine.begin() as conn:
                conn.execute(UPSERT, rows)
    print(f"done: {total} rows{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
