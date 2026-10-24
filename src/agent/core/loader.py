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
MODULE = re.compile(r"^scripts\.[a-z][a-z0-9_]*$")
RISKS = ("read", "write", "heavy")


class SkillLoadError(ValueError):
    pass


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


def _parse_tools(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        parts = []
        for p in inner.split(","):
            p = p.strip().strip('"').strip("'")
            if p:
                parts.append(p)
        return parts
    # comma separated
    parts = []
    for p in raw.split(","):
        p = p.strip().strip('"').strip("'")
        if p:
            parts.append(p)
    return parts


def load_skill_validated(name: str, skills_dir: Path | None = None):
    if not SKILL_NAME.match(name):
        raise SkillLoadError(f"invalid skill name {name!r}; use kebab-case")
    path = (skills_dir or SKILLS_DIR) / name / "SKILL.md"
    if not path.is_file():
        raise SkillLoadError(f"unknown skill {name!r}: {path} does not exist")

    text = path.read_text(encoding="utf-8")
    raw_fm = _frontmatter_raw(text, path)
    # inject parsed tools/tags if list form
    if "tools" in raw_fm:
        tools = _parse_tools(raw_fm["tools"])
        raw_fm["tools"] = ",".join(tools) if tools else ""
    if "tags" in raw_fm:
        tags = _parse_tools(raw_fm["tags"])
        raw_fm["tags"] = ",".join(tags) if tags else ""

    # pydantic expects lists for tools/tags; coerce
    fm_dict = dict(raw_fm)
    fm_dict["tools"] = _parse_tools(raw_fm.get("tools"))
    fm_dict["tags"] = _parse_tools(raw_fm.get("tags"))
    if "owner" in fm_dict and fm_dict["owner"] == "":
        fm_dict["owner"] = None
    if "entrypoint" in fm_dict and fm_dict["entrypoint"] == "":
        fm_dict["entrypoint"] = None

    try:
        fm = SkillFrontmatter.model_validate(fm_dict)
    except ValidationError as exc:
        raise SkillLoadError(f"{path}: frontmatter validation failed: {exc}") from exc

    if fm.name != name:
        raise SkillLoadError(f"{path}: frontmatter name {fm.name!r} does not match {name!r}")
    if fm.risk not in RISKS:
        raise SkillLoadError(f"{path}: risk must be one of {RISKS}, got {fm.risk!r}")
    if len(fm.description) < 30:
        raise SkillLoadError(f"{path}: description is missing or too short")
    missing = [section for section in REQUIRED_SECTIONS if section not in text]
    if missing:
        raise SkillLoadError(f"{path}: missing sections: {', '.join(missing)}")
    return fm, text, path
