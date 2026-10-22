"""Build the forward-return table one observation-date window at a time.

A forward 12M return is knowable only once its window has closed, so the table
covers every observation date whose 252nd following price is also stored. The
materialised range therefore ends 252 trading days before the last stored price,
and the tail of the price history has no forward row at all. That is the lag in the
data, not a missing build: a base rate built from returns that had not happened yet
would be a forecast dressed as history.

The window exists because the query's peak memory is set by the per-security window
functions over the whole price history, not by the output. Bounding the output dates
does not bound that, so the windows here bound the OUTPUT and the price scan behind
it is repeated per window; the trade is a slower full build in exchange for a build
that does not exhaust the host.

The width of a window is therefore set by how much output it may hold rather than by
a fixed number of days, because every window costs the same price scan whatever it
covers: a window of one day and a window of a year both read the whole history. The
nightly's tail fits in a single pass, and a fixed day-count would instead split it
across two and pay for the scan twice.

Writes are upserts, so a rerun over any window is idempotent, and the windows
together cover every observation date exactly once.
"""

import argparse
import sys
import time
from datetime import timedelta

from src.crispdm.returns import (
    build_forward_returns,
    observation_date_range,
    observation_density,
    persist_forward_returns,
)

#: The most output rows one window may hold. The frame is a handful of columns
#: per row, so this is a few hundred megabytes at most: enough to keep the build
#: off the edge of the host's memory, and wide enough that a full rebuild takes
#: a handful of scans rather than dozens.
MAX_WINDOW_ROWS = 2_000_000

#: The narrowest window worth running. A window narrower than this is not
#: bounding anything, it is just paying another scan.
MIN_WINDOW_DAYS = 30


def plan_windows(first, last, max_rows=MAX_WINDOW_ROWS):
    """Split the output range into windows that each hold at most ``max_rows`` rows.

    The forward table holds at most one row per priced observation, so the count
    of priced observations in the range is an upper bound on what it can
    produce, and the density that implies is what sizes the windows. The bound
    is an over-estimate for recent ranges, where the newest securities have no
    complete forward window yet, which makes the plan conservative in the right
    direction: a wider window than strictly needed, never a narrower one.
    """
    span_days = (last - first).days + 1
    priced = observation_density(first, last + timedelta(days=1))
    if priced <= 0 or span_days <= 0:
        return [(first, last + timedelta(days=1))]
    rows_per_day = priced / span_days
    # The width is clamped to the span: a sparse price history implies a window
    # wider than the range itself, and adding that many days to a date overflows.
    window_days = min(span_days, max(MIN_WINDOW_DAYS, int(max_rows / rows_per_day)))
    windows = []
    start = first
    end = last + timedelta(days=1)
    while start < end:
        stop = min(start + timedelta(days=window_days), end)
        windows.append((start, stop))
        start = stop
    return windows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--window-days",
        type=int,
        default=None,
        help="Maximum observation dates per build window (default: chosen from "
        "the output density, so each window holds at most "
        f"{MAX_WINDOW_ROWS:,} rows).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Rebuild only the last N days of observations (default: all history). "
        "Rows are keyed (security_id, as_of_date) and the insert is an upsert, so a "
        "nightly run needs only the recent tail.",
    )
    args = parser.parse_args()

    first, last = observation_date_range()
    if first is None:
        print("No priced observations to build forward returns from.")
        return 1
    if args.days is not None:
        # Never skip a date that is already priced: a rerun after a partial run has
        # to converge, so the floor is the earlier of the two.
        cutoff = last - timedelta(days=args.days)
        first = max(first, cutoff)
        print(f"Incremental build: {first} .. {last} ({args.days} days)")

    windows = plan_windows(first, last)
    if args.window_days is not None:
        windows = _fixed_windows(first, last, args.window_days)
    print(f"Build windows: {len(windows)}")

    total = 0
    for start, end in windows:
        began = time.monotonic()
        df = build_forward_returns(date_from=start, date_to=end)
        written = persist_forward_returns(df)
        total += written
        print(
            f"  {start} .. {end - timedelta(days=1)}: {written:,} rows "
            f"({time.monotonic() - began:.0f}s)",
            flush=True,
        )
    print("Forward return rows:", total)
    return 0


def _fixed_windows(first, last, size_days):
    """Windows of a fixed width, for a caller that asks for one explicitly."""
    windows = []
    start = first
    end = last + timedelta(days=1)
    while start < end:
        stop = min(start + timedelta(days=size_days), end)
        windows.append((start, stop))
        start = stop
    return windows


if __name__ == "__main__":
    sys.exit(main())
