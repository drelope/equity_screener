"""Persist one run-keyed output artifact (RM-05 draft scaffolding).

Dry-run is the default. Writing requires both ``--write`` and
``--i-understand-run-output-write``. Existing output files are never overwritten:
an identical payload is an idempotent no-op; a different payload for the same
run/output pair fails. This does not write to a database or wire any pipeline.

Exit codes: 0 = dry-run/write succeeded; 1 = validation/conflict failure;
2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crispdm.output_store import store_output  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True, help="JSON object or list to store")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-kind", required=True)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / "artifacts/run_outputs")
    parser.add_argument("--entity-type")
    parser.add_argument("--entity-id")
    parser.add_argument("--write", action="store_true", help="write the file (default: dry-run)")
    parser.add_argument("--i-understand-run-output-write", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.write and not args.i_understand_run_output_write:
        print("error: --write requires --i-understand-run-output-write", file=sys.stderr)
        return 2

    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        result = store_output(
            payload,
            root=args.root,
            run_id=args.run_id,
            output_kind=args.output_kind,
            entity_type=args.entity_type,
            entity_id=args.entity_id,
            write=args.write,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    result["promotion_claim"] = False
    result["enforcement_claim"] = False
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        mode = "WRITE" if args.write else "DRY-RUN"
        print(
            f"{mode} run_id={result['run_id']} output_kind={result['output_kind']} "
            f"content_hash={result['content_hash'][:12]}… storage_ref={result['storage_ref']}"
        )
        print("run-keyed output scaffolding only; not promotion evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
