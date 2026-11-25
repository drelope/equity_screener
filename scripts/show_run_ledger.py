"""Read one run-keyed manifest/output bundle from the candidate ledger.

Read-only. Requires the V0110 candidate tables on an explicit target; refuses
shared-like/non-local targets unless overridden. Never creates or mutates rows.

Exit codes: 0 = found; 1 = run_id not found; 2 = safety refusal, missing ledger,
database error, or usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rehearse_p0_full import safety_check_dsn  # noqa: E402
from src.crispdm.manifest_store import (  # noqa: E402
    ManifestLedgerError,
    ManifestLedgerUnavailable,
    get_run_bundle,
)


def sanitized_target(dsn: str) -> dict:
    url = make_url(dsn)
    return {"host": url.host, "database": url.database, "driver": url.drivername}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--allow-shared-name", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    issues = safety_check_dsn(args.dsn, args.allow_nonlocal, args.allow_shared_name)
    if issues:
        print("error: safety refusal:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 2

    engine = create_engine(args.dsn)
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = '60s'"))
            bundle = get_run_bundle(conn, args.run_id)
    except ManifestLedgerUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ManifestLedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: database failure: {exc}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()

    if bundle is None:
        print(f"not found: run_id={args.run_id}", file=sys.stderr)
        return 1

    result = {
        **bundle,
        "target": sanitized_target(args.dsn),
        "read_only": True,
    }
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        manifest = bundle["manifest"]
        print(
            f"run_id={bundle['run_id']} run_type={manifest.get('run_type')} "
            f"status={manifest.get('status')} outputs={bundle['output_count']}"
        )
        print(f"manifest_hash={manifest.get('manifest_hash')}")
        for output in bundle["outputs"]:
            print(f"  - {output.get('output_kind')} {output.get('storage_ref')}")
        print("read-only candidate ledger lookup; not promotion evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
