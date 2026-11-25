"""Read-only integrity checks for the candidate run manifest ledger.

Verifies, without writes:
- each stored manifest_json still hashes to manifest_hash;
- denormalized columns agree with manifest_json;
- manifest_json.run_id agrees with the row key;
- every output references an existing manifest.

Exit codes: 0 = pass; 1 = integrity issues; 2 = safety refusal/DB/ledger error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rehearse_p0_full import safety_check_dsn  # noqa: E402
from src.crispdm.manifest_store import ManifestLedgerUnavailable, ledger_available  # noqa: E402
from src.crispdm.run_manifest import canonical_json, sha256_hex  # noqa: E402


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _same_json(left: Any, right: Any) -> bool:
    return canonical_json(left) == canonical_json(right)


def inspect_ledger(conn) -> dict[str, Any]:
    issues: list[str] = []
    if not ledger_available(conn):
        raise ManifestLedgerUnavailable(
            "candidate ledger missing; apply V0110/V0111 on an isolated target first"
        )

    manifest_rows = (
        conn.execute(
            text(
                """
            SELECT run_id, status, manifest_hash, manifest_json,
                   parameters, input_refs, output_refs, environment
            FROM audit.run_manifests
            ORDER BY run_id
            """
            )
        )
        .mappings()
        .all()
    )
    output_rows = (
        conn.execute(
            text(
                """
            SELECT output_id, run_id, output_kind, storage_ref
            FROM audit.run_outputs
            ORDER BY output_id
            """
            )
        )
        .mappings()
        .all()
    )

    run_ids = set()
    runs = []
    for row in manifest_rows:
        run_id = row["run_id"]
        run_ids.add(run_id)
        manifest = _json(row["manifest_json"])
        if not isinstance(manifest, Mapping):
            issues.append(f"{run_id}: manifest_json is not a JSON object")
            manifest = {}
        if manifest.get("run_id") != run_id:
            issues.append(f"{run_id}: manifest_json.run_id does not match row key")
        recomputed = sha256_hex(manifest)
        if recomputed != row["manifest_hash"]:
            issues.append(
                f"{run_id}: manifest_hash mismatch (stored={row['manifest_hash']}, recomputed={recomputed})"
            )
        checks = (
            ("parameters", "parameters"),
            ("inputs", "input_refs"),
            ("outputs", "output_refs"),
            ("environment", "environment"),
        )
        for manifest_key, column in checks:
            if not _same_json(manifest.get(manifest_key), _json(row[column])):
                issues.append(f"{run_id}: {column} does not match manifest_json.{manifest_key}")
        if manifest.get("status") != row["status"]:
            issues.append(f"{run_id}: status does not match manifest_json.status")
        runs.append(
            {
                "run_id": run_id,
                "manifest_hash": row["manifest_hash"],
                "hash_ok": recomputed == row["manifest_hash"],
            }
        )

    for row in output_rows:
        if row["run_id"] not in run_ids:
            issues.append(f"output_id={row['output_id']}: missing parent manifest {row['run_id']}")
        if not str(row["output_kind"] or "").strip():
            issues.append(f"output_id={row['output_id']}: empty output_kind")
        if not str(row["storage_ref"] or "").strip():
            issues.append(f"output_id={row['output_id']}: empty storage_ref")

    return {
        "run_count": len(manifest_rows),
        "output_count": len(output_rows),
        "runs": runs,
        "issues": issues,
        "passed": not issues,
    }


def sanitized_target(dsn: str) -> dict:
    url = make_url(dsn)
    return {"host": url.host, "database": url.database, "driver": url.drivername}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
            result = inspect_ledger(conn)
    except ManifestLedgerUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: database failure: {exc}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()

    result = {
        **result,
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
        print(
            f"runs={result['run_count']} outputs={result['output_count']} "
            f"issues={len(result['issues'])}"
        )
        for issue in result["issues"]:
            print(f"  - {issue}")
        print("read-only integrity check; not promotion evidence")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
