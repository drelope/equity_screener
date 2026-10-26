from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from src.agent.schemas.skill import SkillFrontmatter

ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = ROOT / "skills"

SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_SECTIONS = (
    "## When to use / when not to use",
    "## Runner",
    "## Preflight",
    "## Inputs",
    "## Procedure",
    "## Outputs",
    "## Verification",
    "## Failure handling",
    "## Handoffs",
    "## Stop conditions",
    "## Evidence required",
    "## Source of truth",
)
RISKS = ("read", "write", "heavy")


class SkillLoadError(ValueError):
    """The skill file is missing or violates the SKILL.md contract."""


def _frontmatter_raw(text: str, path: Path) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise SkillLoadError(f"{path}: missing YAML frontmatter")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise SkillLoadError(f"{path}: malformed frontmatter line {line!r}")
        raw = value.strip()
        if raw[:1] in ("'", '"'):
            raw = raw.strip('"').strip("'")
        else:
            raw = raw.split(" #", 1)[0].strip()
        fields[key.strip()] = raw
    return fields


def _parse_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [part.strip().strip('"').strip("'") for part in raw.split(",") if part.strip()]


def load_skill_validated(
    name: str, skills_dir: Path | None = None
) -> tuple[SkillFrontmatter, str, Path]:
    """Parse and validate a skill, raising ``SkillLoadError`` on any violation."""
    if not SKILL_NAME.match(name):
        raise SkillLoadError(f"invalid skill name {name!r}; use kebab-case")
    path = (skills_dir or SKILLS_DIR) / name / "SKILL.md"
    if not path.is_file():
        raise SkillLoadError(f"unknown skill {name!r}: {path} does not exist")

    text = path.read_text(encoding="utf-8")
    raw = _frontmatter_raw(text, path)
    data: dict[str, object] = dict(raw)
    data["tools"] = _parse_list(raw.get("tools"))
    data["tags"] = _parse_list(raw.get("tags"))
    if not data.get("owner"):
        data["owner"] = None
    if not data.get("entrypoint"):
        data["entrypoint"] = None

    try:
        frontmatter = SkillFrontmatter.model_validate(data)
    except ValidationError as exc:
        raise SkillLoadError(f"{path}: frontmatter validation failed: {exc}") from exc

    if frontmatter.name != name:
        raise SkillLoadError(
            f"{path}: frontmatter name {frontmatter.name!r} does not match {name!r}"
        )
    missing = [section for section in REQUIRED_SECTIONS if section not in text]
    if missing:
        raise SkillLoadError(f"{path}: missing sections: {', '.join(missing)}")
    return frontmatter, text, path
