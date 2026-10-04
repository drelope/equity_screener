"""Build the feature table one observation-date window at a time.

The query's peak memory is set by the quarterly TTM join rather than by the
output, so building the whole 2019-2026 history in one statement exhausted a
15 GB host. Chunking by date bounds that intermediate; the trailing price
features still see full history because their window functions sit upstream of
the bound.

Writes are upserts, so a rerun over any window is idempotent, and the windows
together cover every observation date exactly once.
"""

import argparse
import sys
import time
from datetime import timedelta

from sqlalchemy import text

from src.crispdm.db import engine
from src.crispdm.features import build_features, persist_features
from src.crispdm.model import FEATURES, feature_completeness


def observation_date_range():
    with engine.connect() as c:
        row = c.execute(
            text(
                "SELECT min(observation_date), max(observation_date) "
                "FROM raw.market_data WHERE close IS NOT NULL"
            )
        ).fetchone()
    return row


def windows(first, last, size_days):
    start = first
    while start <= last:
        end = min(start + timedelta(days=size_days), last + timedelta(days=1))
        yield start, end
        start = end


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--window-days",
        type=int,
        default=365,
        help="observation dates per build window (default: 365)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Rebuild only the last N days of observations (default: all history). "
        "Rows are keyed (security_id, as_of_date) and the insert is an upsert, so a "
        "nightly run needs only the recent tail; a full rebuild of 2019-present takes "
        "~50 minutes against ~7 for the last window.",
    )
    args = parser.parse_args()

    first, last = observation_date_range()
    if first is None:
        print("No priced observations to build features from.")
        return 1
    if args.days is not None:
        # Never skip a date that is already priced: a rerun after a partial run has
        # to converge, so the floor is the earlier of the two.
        cutoff = last - timedelta(days=args.days)
        first = max(first, cutoff)
        print(f"Incremental build: {first} .. {last} ({args.days} days)")

    total = 0
    # Row counts alone hide a build that ran clean but produced an empty
    # feature: sum non-null counts per window so the printed coverage is
    # exact even though windows vary in size.
    non_null = {f: 0 for f in FEATURES}
    for start, end in windows(first, last, args.window_days):
        began = time.monotonic()
        df = build_features(date_from=start, date_to=end)
        persist_features(df)
        total += len(df)
        for f in FEATURES:
            non_null[f] += int(df[f].notna().sum()) if f in df.columns else 0
        coverage = feature_completeness(df)
        summary = ", ".join(f"{f}={c:.0%}" for f, c in coverage.items())
        print(
            f"  {start} .. {end - timedelta(days=1)}: {len(df):,} rows "
            f"({time.monotonic() - began:.0f}s) coverage: {summary}",
            flush=True,
        )
    print("Feature rows:", total)
    if total:
        print("Cumulative feature coverage:")
        for f in FEATURES:
            print(f"  {f}: {non_null[f] / total:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
