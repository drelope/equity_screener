"""Fetch FMP split history for every common-stock ticker that has prices.

Read from the warehouse, written to ``artifacts/corporate_actions/fmp_splits.csv``
(gitignored). One FMP call per ticker, through the repo's rate limiter. The file is
rewritten after each ticker, so an interrupted run resumes where it stopped.

The split history is used only where the warehouse price also shows the jump (see
``src/crispdm/portfolio.py``, ``clean_prices``). It is not used to adjust prices on
its own.

    python -m scripts.fetch_fmp_splits
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from src.crispdm import openbb_client as oc
from src.crispdm.db import read_df

OUTPUT = Path(__file__).resolve().parents[1] / "artifacts" / "corporate_actions" / "fmp_splits.csv"
URL = "https://financialmodelingprep.com/stable/splits"
FIELDS = ["ticker", "date", "numerator", "denominator", "split_type"]
RATE_LIMIT_RETRIES = 3


def common_stock_tickers() -> list[str]:
    frame = read_df(
        """
        SELECT DISTINCT s.ticker
        FROM reference.securities s
        JOIN raw.market_data m USING (security_id)
        WHERE s.security_type = 'common_stock'
        ORDER BY s.ticker
        """
    )
    return list(frame["ticker"])


def fetch_splits(ticker: str, key: str) -> list[dict]:
    url = f"{URL}?{urlencode({'symbol': ticker, 'apikey': key})}"
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        oc._fmp_throttle()
        try:
            # Fixed https endpoint; the URL is not user input.
            with urlopen(url, timeout=30) as response:  # noqa: S310
                payload = json.load(response)
            break
        except HTTPError as exc:
            if exc.code != 429 or attempt == RATE_LIMIT_RETRIES:
                raise RuntimeError(f"FMP splits HTTP {exc.code} for {ticker}") from None
            time.sleep(60)
    if not isinstance(payload, list):
        return []
    return [
        {
            "ticker": ticker,
            "date": row.get("date"),
            "numerator": row.get("numerator"),
            "denominator": row.get("denominator"),
            "split_type": row.get("splitType"),
        }
        for row in payload
        if row.get("date") and row.get("numerator") and row.get("denominator")
    ]


def load_done() -> tuple[None, set[str]]:
    """Tickers already fetched, read from the output so a restart skips them."""
    if not OUTPUT.exists():
        return None, set()
    with OUTPUT.open(encoding="utf-8", newline="") as handle:
        return None, {row["ticker"] for row in csv.DictReader(handle)}


def main() -> int:
    key = oc._fmp_key()
    if not key:
        raise SystemExit("No FMP key is configured.")
    tickers = common_stock_tickers()
    _, done = load_done()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(tickers)} tickers; {len(done)} already fetched", flush=True)
    failed: list[str] = []
    total_rows = 0
    for index, ticker in enumerate(tickers, start=1):
        if ticker in done:
            continue
        try:
            events = fetch_splits(ticker, key)
        except RuntimeError as exc:
            failed.append(ticker)
            print(f"  {exc}", flush=True)
            continue
        is_new = not OUTPUT.exists()
        with OUTPUT.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerows(events)
        done.add(ticker)
        total_rows += len(events)
        if index % 250 == 0:
            print(f"  {index}/{len(tickers)} tickers, {total_rows} new split rows", flush=True)
    print(f"done: {len(done)} tickers fetched, {len(failed)} failed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
