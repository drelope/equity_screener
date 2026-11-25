"""
Populate ``raw.market_data`` with daily OHLCV prices from OpenBB.

``scripts.build_features`` derives the momentum (63d/252d) and volatility
(252d) factors from this table, and ``scripts.label_targets`` needs feature rows
whose 365-day outcome window has already elapsed, so the default window opens
three years back: 252 trading days of lookback for the factors, plus a year of
labelable observations in front of them. Override with ``--start-date`` or the
``PRICE_LOOKBACK_START`` env var.

The target list is ``reference.securities`` (dividend payers only unless
``--all``), joined by ``security_id`` so no phantom security rows are created.
Prices are upserted per ticker, so a re-run resumes cheaply and a mid-run
failure never leaves a half-written ticker.

Usage:
    python -m scripts.populate_market_data
    python -m scripts.populate_market_data --limit 50
    python -m scripts.populate_market_data --tickers AAPL,MSFT
    python -m scripts.populate_market_data --start-date 2024-01-02 --end-date 2026-09-25
    python -m scripts.populate_market_data --all

Options:
    --limit N              Limit to the first N securities (testing)
    --tickers SYMBOL,...   Populate only selected tickers
    --all                  Include non-dividend securities
    --start-date YYYY-MM-DD
        Earliest price date (default: settings.price_lookback_start)
    --end-date YYYY-MM-DD
        Latest price date (default: now)
"""

import argparse
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

# Allow direct execution from the repository root as well as `python -m`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.config import settings
from src.crispdm.db import engine
from src.crispdm.openbb_client import historical_prices
from src.crispdm.pit import pit_manifest_metadata
from src.crispdm.run_manifest import build_run_manifest, get_git_state, write_manifest_file
from src.crispdm.stage import stage_exit_code

PROVIDER = "OPENBB"

INSERT_PRICE = """
INSERT INTO raw.market_data
    (security_id, observation_date, open, high, low, close, adjusted_close,
     volume, provider, retrieved_at)
VALUES (:security_id, :observation_date, :open, :high, :low, :close,
        :adjusted_close, :volume, :provider, now())
ON CONFLICT (security_id, observation_date, provider) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    adjusted_close = EXCLUDED.adjusted_close,
    volume = EXCLUDED.volume,
    retrieved_at = now()
"""


def safe_float(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    number = safe_float(value)
    return None if number is None else int(number)


def parse_date(value):
    if value is None or value == "":
        return None
    # NaT is a datetime instance, so it has to be rejected before the type checks
    # below or parse_date would hand a NaT straight to a NOT NULL date column.
    if not isinstance(value, str) and pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


def get_target_securities(
    conn,
    tickers=None,
    dividend_only=True,
    limit=None,
    include_historical=False,
    historical_only=False,
):
    """Return ``(security_id, ticker)`` for the price-ingestion universe."""
    params = {}
    if historical_only:
        clauses = ["s.historical = TRUE"]
    elif include_historical:
        clauses = ["(s.active = TRUE OR s.historical = TRUE)"]
    else:
        clauses = ["s.active = TRUE"]
    if dividend_only:
        clauses.append("s.dividend = TRUE")
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [ticker.upper() for ticker in tickers]
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT :limit"
        params["limit"] = limit

    rows = conn.execute(
        text(f"""
        SELECT s.security_id, s.ticker
        FROM reference.securities s
        WHERE {" AND ".join(clauses)}
        ORDER BY s.ticker
        {limit_clause}
    """),
        params,
    ).all()
    return [(row[0], row[1]) for row in rows]


def normalize_price_rows(security_id, ticker, data_frame):
    """Map an OpenBB price frame onto raw.market_data columns."""
    if data_frame is None or data_frame.empty:
        return []

    df = data_frame.copy()
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    if "date" not in df.columns and "datetime" not in df.columns:
        # OpenBB returns the observation date as the frame index, not a column.
        df = df.reset_index()
        df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    for candidate in ("date", "datetime"):
        if candidate in df.columns:
            date_col = candidate
            break
    else:
        date_col = df.columns[0]

    rows = []
    for _, record in df.iterrows():
        observation_date = parse_date(record.get(date_col))
        if observation_date is None:
            continue
        rows.append(
            {
                "security_id": security_id,
                "observation_date": observation_date,
                "open": safe_float(record.get("open")),
                "high": safe_float(record.get("high")),
                "low": safe_float(record.get("low")),
                "close": safe_float(record.get("close")),
                "adjusted_close": safe_float(record.get("adjusted_close", record.get("adj_close"))),
                "volume": safe_int(record.get("volume")),
                "provider": PROVIDER,
            }
        )
    return rows


#: yfinance raises rather than returning an empty frame for a symbol it does not
#: carry, so "this provider has no series" arrives as an exception. The strings
#: below are what it and OpenBB use for that condition. They mean the instrument
#: is not priceable from this source -- a warrant, right, unit or preferred line
#: that Yahoo does not list, or a delisted symbol -- which is an expected outcome
#: for part of a dividend universe, not a pipeline fault.
NO_DATA_MARKERS = (
    "no data found",
    "no price data found",
    "quote not found",
    "no timezone found",
    "possibly delisted",
    "delisted",
    "no quotes found",
    "no results found",
)


def is_no_data_error(exc):
    """True when an exception means "no series for this symbol", not "fetch broke".

    Getting this wrong in the other direction would be worse than the current
    behaviour: a transient network failure is a real fault and must stay
    counted, otherwise a broken fetch reports as a clean run.
    """
    message = str(exc).lower()
    if any(marker in message for marker in NO_DATA_MARKERS):
        return True
    # OpenBB has a dedicated type for this, and it is the reliable signal: its
    # message is a generic "no results found" that a real query mistake could
    # also produce, whereas the class only means the provider had nothing.
    if type(exc).__name__ == "EmptyDataError":
        return True
    return type(exc).__name__ in {"YFNoPriceDataError", "YFTzNoDataError"}


def _fetch_with_retry(ticker, start, end, attempts=3):
    """Fetch one ticker's prices, retrying only genuine transient failures.

    No-data is not retried: the provider has already said the symbol is unknown,
    and asking again just repeats the 404 against a rate-limited endpoint.
    """
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return historical_prices(ticker, start, end), None
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            last = exc
            if is_no_data_error(exc) or attempt == attempts:
                break
            # Transient: a provider 5xx, a timeout, a rate limit.
            time.sleep(2 * attempt)
    return None, last


def populate_market_data(
    tickers=None,
    dividend_only=True,
    limit=None,
    start_date=None,
    end_date=None,
    include_historical=False,
    historical_only=False,
):
    """Upsert daily prices for the target universe.

    Returns ``(written, empty, errors, no_data)``. ``errors`` counts genuine
    fetch or write failures; ``no_data`` counts securities the provider simply
    does not carry, which is a coverage gap rather than a fault. These were the
    same counter until they were split, so a run in which nothing had actually
    failed reported 235 errors for instruments that were never tradeable there.
    """
    start = start_date or settings.price_lookback_start
    end = end_date or date.today()

    written = 0
    empty = 0
    errors = 0
    no_data = 0
    unpriced = []
    with engine.connect() as conn:
        targets = get_target_securities(
            conn,
            tickers=tickers,
            dividend_only=dividend_only,
            limit=limit,
            include_historical=include_historical,
            historical_only=historical_only,
        )

    print(f"Fetching prices from: openbb ({start} -> {end or 'now'}) for {len(targets)} securities")

    for position, (security_id, ticker) in enumerate(targets, start=1):
        data_frame, exc = _fetch_with_retry(ticker, start.isoformat(), end.isoformat())
        if data_frame is None:
            if is_no_data_error(exc):
                # The provider does not carry this instrument. Expected for
                # warrants, rights, units and some preferred lines, and it says
                # nothing about pipeline health -- but it is a real coverage gap,
                # so it is counted and listed rather than silently skipped.
                no_data += 1
                unpriced.append(ticker)
                if len(unpriced) <= 5:
                    print(f"  No price series for {ticker} (not carried by provider)")
            else:
                errors += 1
                print(f"  Price fetch failed for {ticker}: {exc}")
            continue

        rows = normalize_price_rows(security_id, ticker, data_frame)
        if not rows:
            empty += 1
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(INSERT_PRICE), rows)
            written += len(rows)
        except Exception as exc:
            errors += 1
            print(f"  Error writing prices for {ticker}: {exc}")
            continue

        if position % 100 == 0:
            print(
                f"  {position}/{len(targets)} securities, rows={written}, "
                f"no_data={no_data}, errors={errors}"
            )

    print("\nPopulated raw.market_data:")
    print(f"  Securities: {len(targets)}")
    print(f"  Rows: {written}")
    print(f"  No price data: {empty}")
    print(f"  Not carried by provider: {no_data}")
    print(f"  Errors: {errors}")
    if unpriced:
        # Listed in full: a silent gap in preferred-line pricing is exactly the
        # kind of thing that should be queryable after the fact rather than
        # scrolled past in a 5,700-line log.
        # Deduped: a ticker can appear once per security_id, and the raw list
        # double-counted several of them.
        print(
            f"  Unpriced tickers ({len(set(unpriced))} of {len(unpriced)} securities): "
            f"{','.join(sorted(set(unpriced)))}"
        )
    return written, empty, errors, no_data, len(targets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Limit to the first N securities")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include non-dividend securities (default: dividend payers only)",
    )
    parser.add_argument("--start-date", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--include-historical",
        action="store_true",
        help="Also fetch prices for securities recovered from EDGAR after delisting",
    )
    parser.add_argument(
        "--historical-only",
        action="store_true",
        help="Fetch only the recovered delisted securities",
    )
    parser.add_argument("--end-date", type=date.fromisoformat, default=None)
    args = parser.parse_args()

    tickers = (
        [value.strip().upper() for value in args.tickers.split(",") if value.strip()]
        if args.tickers
        else None
    )
    try:
        written, empty, errors, no_data, targets = populate_market_data(
            tickers=tickers,
            dividend_only=not args.all,
            limit=args.limit,
            start_date=args.start_date,
            end_date=args.end_date,
            include_historical=args.include_historical,
            historical_only=args.historical_only,
        )
        # empty and no_data count as skipped: a security the provider does not
        # carry is a coverage gap, and a weekend on which nothing traded is not
        # a broken stage. Only a run that tried every target and wrote none
        # fails, which is the case where the provider changed shape or the
        # universe filter is wrong -- neither of which is a successful night.
        code = stage_exit_code(
            "populate_market_data", targets, written, skipped=empty + no_data, errors=errors
        )
    except Exception as exc:
        print(f"\n✗ Error populating market data: {exc}", file=sys.stderr)
        return 1
    if code:
        return code
    try:
        git_state = get_git_state(Path(__file__).resolve().parents[1])
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest = build_run_manifest(
            run_type="populate_market_data",
            code_sha=git_state.get("sha"),
            code_dirty=git_state.get("dirty"),
            parameters={
                "tickers": tickers,
                "dividend_only": not args.all,
                "limit": args.limit,
                "start_date": str(args.start_date) if args.start_date else None,
                "end_date": str(args.end_date) if args.end_date else None,
                "include_historical": args.include_historical,
                "historical_only": args.historical_only,
            },
            inputs={
                "source": "openbb_historical_prices",
                "table": "raw.market_data",
                "pit": pit_manifest_metadata(
                    as_of=str(args.end_date) if args.end_date else None,
                    universe_mode="reference_securities_active_or_historical_selection_draft",
                    feature_timing_mode="market_observation_dates_draft",
                    notes="Draft PIT metadata: market data ingested by observation date; adjustment/basis and PIT universe eligibility not fully implemented/verified.",
                ),
            },
            outputs={
                "rows_written": written,
                "no_price_data": empty,
                "errors": errors,
                "not_carried_by_provider": no_data,
                "targets": targets,
            },
            environment={"script": "scripts.populate_market_data"},
            status="completed",
        )
        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "artifacts"
            / "runs"
            / f"populate_market_data_{stamp}"
            / "manifest.json"
        )
        write_manifest_file(manifest, manifest_path)
        print(f"Manifest: {manifest_path}")
    except Exception as exc:
        print(f"Manifest write failed: {exc}")
    print("\nMarket data population complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
