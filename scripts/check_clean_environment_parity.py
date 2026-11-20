"""Verify that both exact-pin lock files produce stable, matching identity metadata."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_reproducibility_locks import parse_lock  # noqa: E402
from src.crispdm.run_manifest import (  # noqa: E402
    LOCK_STRATEGY,
    LOCK_STRATEGY_VERSION,
    get_dependency_lock_hashes,
)


def check_parity(root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "root": str(root),
        "status": "failed",
        "strategy": LOCK_STRATEGY,
        "strategy_version": LOCK_STRATEGY_VERSION,
        "identity": get_dependency_lock_hashes(root),
        "issues": [],
    }
    if report["identity"].get("lock_strategy") != LOCK_STRATEGY:
        report["issues"].append("manifest lock strategy mismatch")
    if report["identity"].get("lock_strategy_version") != LOCK_STRATEGY_VERSION:
        report["issues"].append("manifest lock strategy version mismatch")

    pins: dict[str, set[str]] = {}
    for name in ("requirements.lock.txt", "requirements-dev.lock.txt"):
        path = root / name
        if not path.is_file():
            report["issues"].append(f"missing {name}")
            continue
        entries, invalid = parse_lock(path)
        if invalid:
            report["issues"].append(f"{name}: {len(invalid)} invalid entries")
        pins[name] = set(entries)

    if len(pins) == 2 and pins["requirements.lock.txt"] != pins["requirements-dev.lock.txt"]:
        report["issues"].append("runtime and development lock pin sets differ")
    report["runtime_pins"] = len(pins.get("requirements.lock.txt", ()))
    report["dev_pins"] = len(pins.get("requirements-dev.lock.txt", ()))
    report["status"] = "pass_local_parity" if not report["issues"] else "fail"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    report = check_parity(args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass_local_parity" else 1


if __name__ == "__main__":
    raise SystemExit(main())
