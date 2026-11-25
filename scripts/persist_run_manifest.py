"""Persist a run manifest to the candidate append-only ledger (opt-in).

The ledger tables come from ``V0110_rm04_run_manifest_ledger.sql``, which is **not
approved/applied** by default. This CLI is dry-run unless ``--persist`` and
``--i-understand-ledger-write`` are both supplied, and it refuses shared-like or
non-local targets unless explicitly allowed. It never creates tables and never
updates rows: existing ``run_id`` rows must match the manifest hash.

Exit codes: 0 = dry-run/write succeeded; 1 = conflict/validation failure;
2 = usage, safety refusal, missing ledger, or database error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rehearse_p0_full import safety_check_dsn  # noqa: E402
from src.crispdm.manifest_store import (  # noqa: E402
    ManifestConflictError,
    ManifestLedgerError,
    ManifestLedgerUnavailable,
    persist_manifest,
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_outputs(path: Path | None) -> list[dict]:
    if path is None:
        return []
    payload = load_json(path)
    if isinstance(payload, dict):
        payload = payload.get("outputs")
    if not isinstance(payload, list):
        raise ValueError("outputs file must be a JSON list or an object with an 'outputs' list")
    return payload


def sanitized_target(dsn: str) -> dict:
    url = make_url(dsn)
    return {"host": url.host, "database": url.database, "driver": url.drivername}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, help="optional JSON list of output refs")
    parser.add_argument("--dsn", help="target DSN; required for --persist")
    parser.add_argument(
        "--persist", action="store_true", help="write to the ledger (default: dry-run)"
    )
    parser.add_argument("--dry-run", action="store_true", help="explicitly avoid all DB access")
    parser.add_argument(
        "--i-understand-ledger-write",
        action="store_true",
        help="required acknowledgement that this writes to an approved candidate ledger",
    )
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--allow-shared-name", action="store_true")
    parser.add_argument("--recorded-by", default=None)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--json", action="store_true", help="print machine-readable result")
    args = parser.parse_args(argv)

    if args.persist and args.dry_run:
        print("error: --persist and --dry-run are mutually exclusive", file=sys.stderr)
        return 2
    if args.persist and not args.dsn:
        print("error: --persist requires --dsn", file=sys.stderr)
        return 2
    if args.persist and not args.i_understand_ledger_write:
        print(
            "error: --persist requires --i-understand-ledger-write (candidate ledger, not approved)",
            file=sys.stderr,
        )
        return 2

    try:
        manifest = load_json(args.manifest)
        outputs = load_outputs(args.outputs)
    except Exception as exc:  # noqa: BLE001
        print(f"error: cannot read manifest/outputs: {exc}", file=sys.stderr)
        return 2
    if not isinstance(manifest, dict):
        print("error: manifest must be a JSON object", file=sys.stderr)
        return 2

    dry_run = not args.persist
    if dry_run:
        try:
            result = persist_manifest(None, manifest, outputs=outputs, dry_run=True)
        except ManifestLedgerError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        result.update({"mode": "dry_run", "target": None})
    else:
        issues = safety_check_dsn(args.dsn, args.allow_nonlocal, args.allow_shared_name)
        if issues:
            print("error: safety refusal:", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
            return 2
        engine = create_engine(args.dsn)
        try:
            with engine.begin() as conn:
                result = persist_manifest(
                    conn,
                    manifest,
                    outputs=outputs,
                    recorded_by=args.recorded_by,
                    dry_run=False,
                )
        except ManifestConflictError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except ManifestLedgerUnavailable as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except ManifestLedgerError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"error: database failure: {exc}", file=sys.stderr)
            return 2
        finally:
            engine.dispose()
        result.update({"mode": "persist", "target": sanitized_target(args.dsn)})

    result["read_only"] = dry_run
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"mode={result['mode']} run_id={result['run_id']} "
            f"manifest_hash={result['manifest_hash'][:12]}…"
        )
        if dry_run:
            print(f"dry-run: {len(result['output_rows'])} output row(s) validated; no DB access")
        else:
            print(
                f"manifest_inserted={result['manifest_inserted']} "
                f"outputs_inserted={result['outputs_inserted']}/{result['outputs_requested']}"
            )
            print("candidate ledger write only; not promotion evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
