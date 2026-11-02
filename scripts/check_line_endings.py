"""Fail when a changed file's line endings differ from the endings it was committed with.

The repository mixes LF and CRLF files. Editing a CRLF file through Python's text mode
(``open(p).read()`` then ``open(p, "w").write(...)``) silently rewrites it as LF, which turns a
two-line edit into a whole-file diff (lessons L007). ``ruff format`` is not the cause: it
preserves a file's endings. Edit with ``newline=""`` or a tool that preserves them.

    python -m scripts.check_line_endings            # changed files vs the index
    python -m scripts.check_line_endings --all      # every tracked file
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT = "git"


def parse_eol(output: str) -> list[tuple[str, str, str]]:
    """``(index_eol, worktree_eol, path)`` from ``git ls-files --eol`` output."""
    rows = []
    for line in output.splitlines():
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) >= 2 and fields[0].startswith("i/") and fields[1].startswith("w/"):
            rows.append((fields[0][2:], fields[1][2:], path))
    return rows


def flipped(rows) -> list[tuple[str, str, str]]:
    """Rows whose working endings differ from the committed ones, ignoring files with none."""
    return [
        (i, w, p)
        for i, w, p in rows
        if i != w and i in ("lf", "crlf") and w in ("lf", "crlf", "mixed")
    ]


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed argument list, never a shell
        [GIT, *args], capture_output=True, text=True, cwd=ROOT, check=True
    ).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Check every tracked file.")
    args = parser.parse_args()
    if args.all:
        rows = parse_eol(_git("ls-files", "--eol"))
    else:
        changed = sorted(set(_git("diff", "--name-only", "HEAD").split()))
        rows = parse_eol(_git("ls-files", "--eol", "--", *changed)) if changed else []
    bad = flipped(rows)
    for index, work, path in bad:
        print(f"FAIL {path}: committed as {index}, working copy is {work}")
    print(f"{'PASS' if not bad else 'FAIL'}: {len(bad)} file(s) with changed line endings")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
