"""Apply a synthetic RM-01/02/03/05 backfill on an explicit disposable target.

Safety: requires --i-understand-disposable-target; refuses shared-like/non-local
targets unless explicitly allowed. Loads only the synthetic fixture under
sql-candidates/backfill/ and runs the read-only readiness checker afterward.
This is a rehearsal tool, not approval or promotion evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_candidate_backfill_readiness import main as readiness_main  # noqa: E402
from scripts.check_migration_candidates import DEFAULT_CANDIDATES_DIR  # noqa: E402
from scripts.rehearse_p0_full import safety_check_dsn  # noqa: E402

FIXTURE = DEFAULT_CANDIDATES_DIR / "backfill" / "synthetic-backfill-2026-11-16.sql"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--allow-shared-name", action="store_true")
    parser.add_argument("--i-understand-disposable-target", action="store_true")
    args = parser.parse_args(argv)

    issues = safety_check_dsn(args.dsn, args.allow_nonlocal, args.allow_shared_name)
    if issues:
        print("safety refusal:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 2
    if not args.i_understand_disposable_target:
        print("ERROR: --i-understand-disposable-target is required", file=sys.stderr)
        return 2
    if not args.fixture.exists():
        print(f"ERROR: fixture not found: {args.fixture}", file=sys.stderr)
        return 2

    engine = create_engine(args.dsn)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "failed",
        "fixture": args.fixture.name,
        "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        "errors": [],
    }
    readiness_out = args.out.with_name("readiness-after-synthetic-" + args.out.name)

    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(args.fixture.read_text(encoding="utf-8"))
        rc = readiness_main(["--dsn", args.dsn, "--json-out", str(readiness_out)])
        report["readiness_exit"] = rc
        report["readiness_report"] = str(readiness_out)
        if rc != 0:
            report["status"] = "readiness_failed"
            report["errors"].append(f"readiness checker exited {rc}")
        else:
            report["status"] = "synthetic_backfill_readiness_passed"
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(str(exc))
    finally:
        engine.dispose()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status={report['status']} errors={len(report['errors'])}")
    for err in report["errors"]:
        print(f"FAIL: {err}", file=sys.stderr)
    return 0 if report["status"] == "synthetic_backfill_readiness_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
