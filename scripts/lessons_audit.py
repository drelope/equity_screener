"""Deterministic integrity check for the ETL lessons ledger (docs/etl-lessons/).

A lesson that is written down but not enforced is a note, not learning. This fails when a
lesson claims to be ``guarded`` without naming a guard that exists, when two lessons share an
id, when a required field is missing, or when the index and the files disagree.

    python -m scripts.lessons_audit
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LESSONS_DIR = ROOT / "docs" / "etl-lessons"
STATUSES = ("guarded", "monitored", "open")
FIELDS = ("Status", "Area", "Symptom", "Root cause", "Detection", "Guard", "Recurrence check")
ID = re.compile(r"^L(\d{3})-[a-z0-9-]+\.md$")


@dataclass(frozen=True)
class Finding:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


def parse(text: str) -> dict[str, str]:
    """``- **Field:** value`` bullets; a value may continue on indented lines."""
    out: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"^- \*\*([^*]+):\*\*\s*(.*)$", line)
        if match:
            current = match.group(1).strip()
            out[current] = match.group(2).strip()
        elif current and line.startswith("  ") and line.strip():
            out[current] += " " + line.strip()
    return out


def guard_paths(value: str) -> list[str]:
    return re.findall(r"`([^`]+)`", value)


def audit(lessons_dir: Path = LESSONS_DIR, root: Path = ROOT) -> list[Finding]:
    findings: list[Finding] = []
    files = sorted(p for p in lessons_dir.glob("L*.md"))
    ids: dict[str, Path] = {}
    for path in files:
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name
        match = ID.match(path.name)
        if not match:
            findings.append(Finding(rel, "file name must look like L001-short-name.md"))
            continue
        if match.group(1) in ids:
            findings.append(Finding(rel, f"duplicate lesson id L{match.group(1)}"))
        ids[match.group(1)] = path
        fields = parse(path.read_text(encoding="utf-8"))
        for field in FIELDS:
            if not fields.get(field):
                findings.append(Finding(rel, f"missing field '{field}'"))
        status = fields.get("Status", "")
        if status and status not in STATUSES:
            findings.append(Finding(rel, f"Status must be one of {STATUSES}, got {status!r}"))
        paths = guard_paths(fields.get("Guard", ""))
        if status == "guarded":
            if not paths:
                findings.append(Finding(rel, "a guarded lesson must name its guard in backticks"))
            for guard in paths:
                if not (root / guard).exists():
                    findings.append(Finding(rel, f"guard does not exist: {guard}"))
        if re.search(r"\b(TODO|FIXME|TBD:)", path.read_text(encoding="utf-8")):
            findings.append(Finding(rel, "unresolved marker"))
    index = lessons_dir / "INDEX.md"
    if not index.exists():
        findings.append(Finding("docs/etl-lessons/INDEX.md", "missing index"))
    else:
        listed = set(
            re.findall(r"\]\((L\d{3}-[a-z0-9-]+\.md)\)", index.read_text(encoding="utf-8"))
        )
        actual = {p.name for p in files}
        for name in sorted(actual - listed):
            findings.append(Finding("docs/etl-lessons/INDEX.md", f"does not list {name}"))
        for name in sorted(listed - actual):
            findings.append(Finding("docs/etl-lessons/INDEX.md", f"lists missing file {name}"))
    return findings


def main() -> int:
    findings = audit()
    for finding in findings:
        print(f"FAIL {finding}")
    print(f"{'PASS' if not findings else 'FAIL'}: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
