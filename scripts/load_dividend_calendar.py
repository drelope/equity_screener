"""Load FMP's dividend calendar into raw.dividend_calendar.

One market-wide call per window (FMP caps a window at 90 days) returns every
declared or scheduled dividend, so this is a handful of requests, not one per
ticker. Rows for tickers that are not an active security are skipped. Re-running
updates a row in place by (security, ex-date, provider).

    python -m scripts.load_dividend_calendar               # 7 days back, 90 ahead
    python -m scripts.load_dividend_calendar --back 30 --ahead 180
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
from sqlalchemy import text

from src.crispdm import openbb_client as oc
from src.crispdm.db import engine, read_df

URL = "https://financialmodelingprep.com/stable/dividends-calendar"
PROVIDER = "FMP_CALENDAR"
WINDOW_DAYS = 90

UPSERT = text(
    """
    INSERT INTO raw.dividend_calendar
      (security_id, ex_dividend_date, declaration_date, record_date, payment_date,
       amount, adjusted_amount, dividend_yield, frequency, is_special, provider)
    VALUES
      (CAST(:security_id AS uuid), :ex_dividend_date, :declaration_date, :record_date,
       :payment_date, :amount, :adjusted_amount, :dividend_yield, :frequency,
       :is_special, :provider)
    ON CONFLICT (security_id, ex_dividend_date, provider) DO UPDATE SET
      declaration_date = EXCLUDED.declaration_date,
      record_date = EXCLUDED.record_date,
      payment_date = EXCLUDED.payment_date,
      amount = EXCLUDED.amount,
      adjusted_amount = EXCLUDED.adjusted_amount,
      dividend_yield = EXCLUDED.dividend_yield,
      frequency = EXCLUDED.frequency,
      is_special = EXCLUDED.is_special,
      retrieved_at = now()
    """
)


def windows(start: date, end: date, days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Consecutive, non-overlapping windows covering ``start``..``end`` inclusive."""
    out = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=days - 1), end)
        out.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return out


def fetch_window(start: date, end: date, key: str, opener=urlopen, url: str = URL) -> list[dict]:
    """One FMP calendar window; ``url`` selects the calendar (dividends by default)."""
    url = f"{url}?{urlencode({'from': start, 'to': end, 'apikey': key})}"
    for attempt in range(oc.FMP_RATE_LIMIT_RETRIES + 1):
        oc._fmp_throttle()
        try:
            with opener(url, timeout=60) as response:
                payload = json.load(response)
            return payload if isinstance(payload, list) else []
        except HTTPError as exc:
            if exc.code != 429 or attempt == oc.FMP_RATE_LIMIT_RETRIES:
                raise RuntimeError(f"FMP dividends-calendar HTTP {exc.code}") from None
            import time

            time.sleep(60)
    return []


def _date(value):
    parsed = pd.to_datetime(value or None, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def _number(value):
    parsed = pd.to_numeric(value if value != "" else None, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def calendar_rows(events: list[dict], tickers: dict[str, str]) -> list[dict]:
    """Insert parameters for events on active tickers with a usable ex-date."""
    rows = {}
    for event in events:
        security_id = tickers.get(str(event.get("symbol", "")).upper())
        ex_date = _date(event.get("date"))
        if security_id is None or ex_date is None:
            continue
        frequency = event.get("frequency") or None
        rows[(security_id, ex_date)] = {
            "security_id": security_id,
            "ex_dividend_date": ex_date,
            "declaration_date": _date(event.get("declarationDate")),
            "record_date": _date(event.get("recordDate")),
            "payment_date": _date(event.get("paymentDate")),
            "amount": _number(event.get("dividend")),
            "adjusted_amount": _number(event.get("adjDividend")),
            "dividend_yield": _number(event.get("yield")),
            "frequency": frequency,
            "is_special": str(frequency or "").lower() == "special",
            "provider": PROVIDER,
        }
    return list(rows.values())


def active_tickers() -> dict[str, str]:
    frame = read_df(
        "SELECT security_id::text AS security_id, upper(ticker) AS ticker "
        "FROM reference.securities WHERE active = TRUE"
    )
    return dict(zip(frame["ticker"], frame["security_id"], strict=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--back", type=int, default=7, help="Days before today to include.")
    parser.add_argument("--ahead", type=int, default=90, help="Days after today to include.")
    parser.add_argument(
        "--skip-if-no-key",
        action="store_true",
        help="Exit 0 instead of 1 when the API key is not configured (nightly use).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    key = oc._fmp_key()
    if not key:
        print("no FMP API key configured; cannot fetch the dividend calendar")
        return 0 if args.skip_if_no_key else 1
    today = date.today()
    tickers = active_tickers()
    total = 0
    for start, end in windows(
        today - timedelta(days=args.back), today + timedelta(days=args.ahead)
    ):
        rows = calendar_rows(fetch_window(start, end, key), tickers)
        total += len(rows)
        print(f"{start}..{end}: {len(rows)} dividends on active securities", flush=True)
        if rows and not args.dry_run:
            with engine.begin() as conn:
                conn.execute(UPSERT, rows)
    print(f"done: {total} rows{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
