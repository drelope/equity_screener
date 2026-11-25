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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from src.crispdm.db import engine
from src.crispdm.features import build_features, build_features_pit_metadata, persist_features
from src.crispdm.model import FEATURES, feature_completeness
from src.crispdm.run_manifest import build_run_manifest, get_git_state, write_manifest_file


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
    parser.add_argument(
        "--date-from",
        type=date.fromisoformat,
        default=None,
        help="Rebuild observation dates on or after this ISO date (targeted repair).",
    )
    parser.add_argument(
        "--date-to",
        type=date.fromisoformat,
        default=None,
        help="Rebuild observation dates on or before this ISO date.",
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

    if args.date_from is not None:
        first = max(first, args.date_from)
    if args.date_to is not None:
        last = min(last, args.date_to)
    if first is not None and last is not None and first > last:
        print(f"Empty range: {first} .. {last}")
        return 1
    if args.date_from is not None or args.date_to is not None:
        print(f"Targeted build: {first} .. {last}")

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

    try:
        git_state = get_git_state(Path(__file__).resolve().parents[1])
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest = build_run_manifest(
            run_type="build_features",
            code_sha=git_state.get("sha"),
            code_dirty=git_state.get("dirty"),
            parameters={
                "window_days": args.window_days,
                "days": args.days,
                "date_from": str(first) if first else None,
                "date_to": str(last) if last else None,
            },
            inputs={
                "market_data_table": "raw.market_data",
                "pit": build_features_pit_metadata(
                    as_of=str(last) if last else None,
                    date_from=str(first) if first else None,
                    date_to=str(last) if last else None,
                ),
            },
            outputs={"feature_rows_written": total, "resolved_range": [str(first), str(last)]},
            resolved_as_of=str(last) if last else None,
            environment={"script": "scripts.build_features"},
            status="completed",
        )
        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "artifacts"
            / "runs"
            / f"build_features_{stamp}"
            / "manifest.json"
        )
        write_manifest_file(manifest, manifest_path)
        print(f"Manifest: {manifest_path}")
    except Exception as exc:
        print(f"Manifest write failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
