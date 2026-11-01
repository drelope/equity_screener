"""Backfill model.features provenance columns in committed batches.

V0095 added ``feature_version`` with the stale default ``v1`` and
``feature_set_hash`` with no default, so the 9.7M existing rows carry a version
the pipeline never used and a NULL hash. V0096 fixes the defaults; this script
repairs the history.

It is deliberately not part of the migration: a single ``UPDATE`` over 9.7M
rows rewrites the whole table in one transaction, holding locks and leaving
millions of dead tuples. Batching keeps each transaction short and lets an
interrupted run resume, because a repaired row no longer matches the predicate.

    python -m scripts.backfill_feature_provenance
    python -m scripts.backfill_feature_provenance --batch-size 25000
    python -m scripts.backfill_feature_provenance --dry-run
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import text

from src.crispdm.db import engine, read_df
from src.crispdm.versioning import FEATURE_SET_V1, FEATURE_VERSION, compute_feature_set_hash

FEATURE_SET_HASH = compute_feature_set_hash(FEATURE_SET_V1)

NEEDS_BACKFILL = "feature_version = 'v1' OR feature_set_hash IS NULL"

BATCH_UPDATE = text(f"""
WITH batch AS (
    SELECT ctid
    FROM model.features
    WHERE {NEEDS_BACKFILL}
    LIMIT :batch_size
    FOR UPDATE SKIP LOCKED
)
UPDATE model.features AS f
SET feature_version = :feature_version,
    feature_set_hash = :feature_set_hash
FROM batch
WHERE f.ctid = batch.ctid
""")


def remaining() -> int:
    return int(
        read_df(f"SELECT count(*) AS n FROM model.features WHERE {NEEDS_BACKFILL}").iloc[0, 0]
    )


def backfill(batch_size: int, sleep_seconds: float, dry_run: bool) -> int:
    total = remaining()
    print(f"rows needing backfill: {total}", flush=True)
    if dry_run or total == 0:
        return 0

    done = 0
    while True:
        with engine.begin() as conn:
            result = conn.execute(
                BATCH_UPDATE,
                {
                    "batch_size": batch_size,
                    "feature_version": FEATURE_VERSION,
                    "feature_set_hash": FEATURE_SET_HASH,
                },
            )
            updated = result.rowcount
        if not updated:
            break
        done += updated
        print(f"  updated {done}/{total}", flush=True)
        if sleep_seconds:
            time.sleep(sleep_seconds)

    left = remaining()
    print(
        f"done: {done} rows updated to {FEATURE_VERSION} / {FEATURE_SET_HASH}; {left} remaining",
        flush=True,
    )
    return 0 if left == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to pause between batches, to let autovacuum keep up.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report the row count only.")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    return backfill(args.batch_size, args.sleep, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
