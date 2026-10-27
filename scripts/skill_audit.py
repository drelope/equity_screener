"""Deterministic quality, security and token gate for ``skills/``.

The audit is read-only. It validates the skill contract, links, source paths,
token budgets, secret hygiene and lifecycle design records. It never reads
``.env`` values, connects to the database or executes a skill.

Usage:
    python -m scripts.skill_audit --all
    python -m scripts.skill_audit --skill financial-analysis
    python -m scripts.skill_audit --all --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from src.agent.core.loader import SKILL_NAME, SkillLoadError, load_skill_validated
from src.agent.schemas.skill import SkillFrontmatter
from src.agent.tools import ToolResolutionError, build_registry, resolve_tools

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
DESIGNS_DIR = ROOT / "docs" / "skill-designs"
SYSTEM = ROOT / "SYSTEM.md"
WORKFLOW = ROOT / "docs" / "file-based-agentic-workflow.md"
LIFECYCLE_DOC = ROOT / "docs" / "skill-lifecycle.md"

MAX_SKILL_CHARS = 8_000
MAX_SKILL_LINES = 160
MAX_REFERENCE_CHARS = 12_000
MAX_REFERENCE_LINES = 260
MAX_DESIGN_CHARS = 12_000
MAX_DESIGN_LINES = 220
LIFECYCLE_TAG = "lifecycle"
PHASES = ("clarify", "design", "plan", "code", "verify")

HANDOFF = re.compile(r"(?:route to|→)\s*`([a-z0-9-]+)`", re.I)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BACKTICK_PATH = re.compile(r"`([^`\n]+)`")
UNRESOLVED = re.compile(r"\b(?:TODO|FIXME|TBD:)\b")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|database_url|sec_user_agent)\b"
    r"\s*[:=]\s*[\"']?"
    r"(?!\$|\{|`|<|\.\.\.|none\b|required\b|yes\b|no\b|value\b|name\b|present\b)"
    r"[^\s\"'`]{8,}"
)
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
ABSOLUTE_PATH = re.compile(r"(?<![\w.])/(?:mnt|home|Users)/|[A-Za-z]:\\\\Users\\\\")
OPEN_QUESTIONS_NONE = re.compile(r"open questions\s*:\s*none\b", re.I)
GATE_ROW = re.compile(r"^\|\s*([a-z]+)\s*\|\s*([a-z]+)\s*\|", re.I)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _skill_names(skills_dir: Path) -> set[str]:
    return {
        path.parent.name
        for path in skills_dir.glob("*/SKILL.md")
        if not path.parent.name.startswith("_")
    }


def _check_budget(
    path: Path, text: str, max_chars: int, max_lines: int, root: Path
) -> list[Finding]:
    findings = []
    lines = len(text.splitlines())
    if len(text) > max_chars:
        findings.append(
            Finding("budget", _relative(path, root), f"{len(text)} chars exceeds {max_chars}")
        )
    if lines > max_lines:
        findings.append(
            Finding("budget", _relative(path, root), f"{lines} lines exceeds {max_lines}")
        )
    return findings


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    nxt = text.find("\n## ", start)
    return text[start : nxt if nxt >= 0 else len(text)]


def _check_security(path: Path, text: str, root: Path) -> list[Finding]:
    findings = []
    rel = _relative(path, root)
    if SECRET_ASSIGNMENT.search(text):
        findings.append(Finding("secret", rel, "assignment looks like a secret value"))
    if PRIVATE_KEY.search(text):
        findings.append(Finding("secret", rel, "contains a private-key block"))
    if ABSOLUTE_PATH.search(text):
        findings.append(Finding("absolute-path", rel, "contains an absolute host path"))
    return findings


def _check_links(skill_path: Path, text: str, root: Path) -> list[Finding]:
    findings = []
    for target in MARKDOWN_LINK.findall(text):
        clean = target.split("#", 1)[0].strip()
        if not clean or clean.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (skill_path.parent / clean).resolve()
        if not resolved.is_relative_to(root.resolve()):
            findings.append(
                Finding("link", _relative(skill_path, root), f"link leaves the repo: {target}")
            )
        elif not resolved.exists():
            findings.append(
                Finding("link", _relative(skill_path, root), f"missing link target: {target}")
            )
    return findings


def _check_source_paths(skill_path: Path, text: str, root: Path) -> list[Finding]:
    findings = []
    section = _section(text, "Source of truth")
    for raw in BACKTICK_PATH.findall(section):
        candidate = raw.strip()
        if not candidate or any(ch in candidate for ch in " <>|"):
            continue
        if "/" not in candidate and "." not in candidate:
            continue
        if candidate.startswith(("http://", "https://")):
            continue
        is_glob = any(ch in candidate for ch in "*?[")
        matches = root.glob(candidate) if is_glob else (root / candidate,)
        if not any(match.exists() for match in matches):
            findings.append(
                Finding(
                    "source-path",
                    _relative(skill_path, root),
                    f"source of truth path does not exist: {candidate}",
                )
            )
    return findings


def _check_description(path: Path, frontmatter: SkillFrontmatter, root: Path) -> list[Finding]:
    findings = []
    description = frontmatter.description
    if "use when" not in description.lower():
        findings.append(
            Finding("description", _relative(path, root), "description lacks a 'Use when' trigger")
        )
    if "do not use" not in description.lower():
        findings.append(
            Finding(
                "description", _relative(path, root), "description lacks a 'Do not use' boundary"
            )
        )
    return findings


def _check_handoffs(text: str, name: str, known: set[str], path: Path, root: Path) -> list[Finding]:
    findings = []
    for target in sorted(set(HANDOFF.findall(text))):
        if target not in known:
            findings.append(
                Finding(
                    "handoff",
                    _relative(path, root),
                    f"{name}: unknown handoff target {target!r}",
                )
            )
    return findings


def _check_tools(frontmatter: SkillFrontmatter, path: Path, root: Path) -> list[Finding]:
    findings = []
    try:
        tools = resolve_tools(build_registry(), frontmatter.name, frontmatter.tools)
    except ToolResolutionError as exc:
        findings.append(Finding("tool", _relative(path, root), str(exc)))
        return findings

    if frontmatter.risk == "read":
        for tool in tools:
            if tool.risk != "read" or tool.side_effects:
                findings.append(
                    Finding(
                        "tool",
                        _relative(path, root),
                        f"read skill declares a mutating tool: {tool.name}",
                    )
                )
    return findings


def _check_references(skill_dir: Path, text: str, root: Path) -> list[Finding]:
    findings = []
    ref_dir = skill_dir / "references"
    if not ref_dir.is_dir():
        return findings
    for path in sorted(ref_dir.glob("*.md")):
        rel = _relative(path, root)
        ref_text = _read(path)
        findings.extend(
            _check_budget(path, ref_text, MAX_REFERENCE_CHARS, MAX_REFERENCE_LINES, root)
        )
        findings.extend(_check_security(path, ref_text, root))
        if "Load when:" not in ref_text:
            findings.append(Finding("reference", rel, "reference lacks a 'Load when:' trigger"))
        if path.name not in text:
            findings.append(Finding("reference", rel, "reference is not linked from SKILL.md"))
    return findings


def _check_design(
    name: str, designs_dir: Path, root: Path, through: str = "verify"
) -> list[Finding]:
    if through not in PHASES:
        return [Finding("design-gate", name, f"unknown phase {through!r}")]
    path = designs_dir / f"{name}.md"
    if not path.is_file():
        return [
            Finding("design", _relative(path, root), f"missing lifecycle design record for {name}")
        ]
    text = _read(path)
    rel = _relative(path, root)
    findings = _check_budget(path, text, MAX_DESIGN_CHARS, MAX_DESIGN_LINES, root)
    findings.extend(_check_security(path, text, root))

    for phase in PHASES:
        if not re.search(rf"^##\s+{phase}\s*$", text, re.M | re.I):
            findings.append(Finding("design", rel, f"missing '## {phase}' section"))
    if not OPEN_QUESTIONS_NONE.search(text):
        findings.append(Finding("design", rel, "'Open questions: none' is required"))
    if UNRESOLVED.search(text):
        findings.append(Finding("design", rel, "contains an unresolved marker"))

    gate: dict[str, str] = {}
    for line in text.splitlines():
        match = GATE_ROW.match(line)
        if match:
            gate[match.group(1).lower()] = match.group(2).lower()
    required = PHASES[: PHASES.index(through) + 1]
    for phase in PHASES:
        result = gate.get(phase)
        if phase in required and result is None:
            findings.append(Finding("design-gate", rel, f"gate log is missing {phase}"))
        elif phase in required and result != "pass":
            findings.append(Finding("design-gate", rel, f"gate {phase} is {result!r}, not 'pass'"))
    return findings


def audit_skill(
    name: str,
    *,
    root: Path = ROOT,
    skills_dir: Path | None = None,
    designs_dir: Path | None = None,
    through: str = "verify",
) -> list[Finding]:
    """Audit one skill by directory name."""
    root = root.resolve()
    skills_dir = (skills_dir or root / "skills").resolve()
    designs_dir = (designs_dir or root / "docs" / "skill-designs").resolve()
    path = skills_dir / name / "SKILL.md"
    try:
        frontmatter, text, path = load_skill_validated(name, skills_dir)
    except SkillLoadError as exc:
        return [Finding("contract", _relative(path, root), str(exc))]

    findings = []
    findings.extend(_check_budget(path, text, MAX_SKILL_CHARS, MAX_SKILL_LINES, root))
    findings.extend(_check_security(path, text, root))
    findings.extend(_check_description(path, frontmatter, root))
    findings.extend(_check_links(path, text, root))
    findings.extend(_check_source_paths(path, text, root))
    findings.extend(_check_handoffs(text, name, _skill_names(skills_dir), path, root))
    findings.extend(_check_tools(frontmatter, path, root))
    findings.extend(_check_references(path.parent, text, root))

    if LIFECYCLE_TAG in frontmatter.tags:
        findings.extend(_check_design(name, designs_dir, root, through))
    return findings


def _routing_names(text: str) -> set[str]:
    section = text.split("## 8. Routing table", 1)[1].split("## 9.", 1)[0]
    names: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        match = re.fullmatch(r"`([a-z0-9-]+)`", cells[1])
        if match:
            names.add(match.group(1))
    return names


def _system_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        match = re.fullmatch(r"`([a-z0-9-]+)`", cells[0])
        if match and cells[1] in ("read", "write", "heavy"):
            names.add(match.group(1))
    return names


def audit_repository(*, root: Path = ROOT) -> list[Finding]:
    """Audit every routed skill plus the routing and inventory maps."""
    root = root.resolve()
    skills_dir = root / "skills"
    designs_dir = root / "docs" / "skill-designs"
    findings: list[Finding] = []
    names = _skill_names(skills_dir)

    for name in sorted(names):
        findings.extend(
            audit_skill(name, root=root, skills_dir=skills_dir, designs_dir=designs_dir)
        )

    workflow_path = root / "docs" / "file-based-agentic-workflow.md"
    system_path = root / "SYSTEM.md"
    if not workflow_path.is_file():
        findings.append(
            Finding("routing", _relative(workflow_path, root), "missing workflow document")
        )
    else:
        routed = _routing_names(_read(workflow_path))
        if routed != names:
            findings.append(
                Finding(
                    "routing",
                    _relative(workflow_path, root),
                    f"routing {sorted(routed)} does not match skills {sorted(names)}",
                )
            )

    if not system_path.is_file():
        findings.append(Finding("system", _relative(system_path, root), "missing SYSTEM.md"))
    else:
        listed = _system_names(_read(system_path))
        if listed != names:
            findings.append(
                Finding(
                    "system",
                    _relative(system_path, root),
                    f"SYSTEM.md {sorted(listed)} does not match skills {sorted(names)}",
                )
            )

    if not (root / "docs" / "skill-lifecycle.md").is_file():
        findings.append(
            Finding("lifecycle", "docs/skill-lifecycle.md", "missing shared lifecycle contract")
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Audit every routed skill")
    group.add_argument("--skill", help="Audit one skill directory")
    parser.add_argument("--phase", choices=PHASES, default="verify", help="Gate through this phase")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    if args.skill:
        if not SKILL_NAME.match(args.skill):
            print(f"invalid skill name: {args.skill}", file=sys.stderr)
            return 2
        findings = audit_skill(args.skill, through=args.phase)
    else:
        if args.phase != "verify":
            print("--phase requires --skill", file=sys.stderr)
            return 2
        findings = audit_repository()

    if args.json:
        print(
            json.dumps(
                {"passed": not findings, "findings": [f.as_dict() for f in findings]}, indent=2
            )
        )
    else:
        for finding in findings:
            print(f"{finding.path}: [{finding.code}] {finding.message}")
        print(f"{'PASS' if not findings else 'FAIL'}: {len(findings)} finding(s)")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
