"""Check that dependency lock artifacts exist and are consistent with policy drafts.

RM-06 / DEC-008 scaffolding only: this does not claim a ratified lock strategy.
It verifies that lock files are present, non-empty, and parseable as pinned
requirements (``name==version`` lines, ignoring comments/blanks/options).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+(\[[A-Za-z0-9_,.-]+\])?==[^\s;]+")
REQ_OPT_RE = re.compile(r"^-(r|c|e)\s+|^--")


def parse_lock(path: Path) -> tuple[list[str], list[str]]:
    pins: list[str] = []
    invalid: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if REQ_OPT_RE.match(line):
            continue
        if "==" in line and PIN_RE.match(line):
            pins.append(line)
        else:
            invalid.append(f"{path}:{lineno}: {raw}")
    return pins, invalid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock",
        action="append",
        default=[],
        help="Lock file to check (repeatable). Defaults to repo lock files.",
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    locks = [Path(p) for p in args.lock] or [
        root / "requirements.lock.txt",
        root / "requirements-dev.lock.txt",
    ]

    errors: list[str] = []
    for lock in locks:
        if not lock.exists():
            errors.append(f"missing lock file: {lock}")
            continue
        pins, invalid = parse_lock(lock)
        if not pins:
            errors.append(f"no pinned entries found in {lock}")
        errors.extend(invalid)
        print(f"{lock}: {len(pins)} pinned entries")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print("Reproducibility lock check: PASS (scaffolding)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
