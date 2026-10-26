"""Contract tests for the Pydantic schemas and dynamic tooling layer."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from scripts import agent_runner as runner
from src.agent.core.loader import SkillLoadError, load_skill_validated
from src.agent.schemas import RunPlan, SkillFrontmatter
from src.agent.tools import (
    Tool,
    ToolExecutionError,
    ToolExecutor,
    ToolRegistry,
    ToolResolutionError,
    build_registry,
    resolve_tools,
)
from src.agent.tools.builtins.repo import RepoTools

VALID_FRONTMATTER = {
    "name": "data-validation",
    "description": "Use when checking schema drift and quality thresholds.",
    "version": 1,
    "risk": "read",
    "owner": "data-engineering",
    "entrypoint": "fixed",
    "tools": [],
    "tags": [],
}


def _skill_text(name: str = "demo-skill", tools: str = "[]") -> str:
    sections = "\n\n".join(f"{section}\n\nPlaceholder." for section in runner.REQUIRED_SECTIONS)
    return f"""---
name: {name}
description: "Use when testing the loader contract. Do not use in production."
version: 1
risk: read
owner: test
entrypoint: none
tools: {tools}
tags: []
---

# Demo skill

{sections}
"""


def _write_skill(directory: Path, name: str = "demo-skill", tools: str = "[]") -> Path:
    skill_dir = directory / name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(_skill_text(name, tools), encoding="utf-8")
    return path


def test_skill_frontmatter_validates_and_forbids_extra_fields():
    frontmatter = SkillFrontmatter.model_validate(VALID_FRONTMATTER)
    assert frontmatter.name == "data-validation"
    assert frontmatter.tools == []

    with pytest.raises(ValidationError):
        SkillFrontmatter.model_validate({**VALID_FRONTMATTER, "unexpected": True})


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "Bad_Name"},
        {"description": "too short"},
        {"risk": "danger"},
        {"tools": ["Bad Tool"]},
    ],
)
def test_skill_frontmatter_rejects_invalid_values(overrides):
    with pytest.raises(ValidationError):
        SkillFrontmatter.model_validate({**VALID_FRONTMATTER, **overrides})


def test_loader_validates_real_skill_and_sections(tmp_path):
    frontmatter, text, path = load_skill_validated("data-validation")
    assert frontmatter.entrypoint == "fixed"
    assert path.name == "SKILL.md"
    assert "## Verification" in text

    bad = _write_skill(tmp_path, name="broken-skill")
    bad.write_text(
        bad.read_text(encoding="utf-8").replace("## Verification", "## Removed"),
        encoding="utf-8",
    )
    with pytest.raises(SkillLoadError, match="missing sections"):
        load_skill_validated("broken-skill", tmp_path)


def test_loader_reads_declared_tools(tmp_path):
    _write_skill(tmp_path, name="tool-skill", tools="[files.read]")
    frontmatter, _, _ = load_skill_validated("tool-skill", tmp_path)
    assert frontmatter.tools == ["files.read"]


def test_registry_denies_tools_by_default():
    registry = build_registry()
    assert registry.tools_for_skill("data-validation", []) == []
    assert [tool.name for tool in registry.tools_for_skill("data-validation")] == ["files.read"]
    assert [tool.name for tool in registry.tools_for_skill("data-validation", ["files.read"])] == [
        "files.read"
    ]


def test_registry_respects_explicit_scope():
    registry = ToolRegistry()
    tool = Tool(name="demo.read", description="Demo", func=lambda: None, scopes={"a"})
    registry.register(tool)
    assert registry.tools_for_skill("a", ["demo.read"]) == [tool]
    assert registry.tools_for_skill("b", ["demo.read"]) == []


def test_resolve_tools_rejects_unknown_and_out_of_scope():
    with pytest.raises(ToolResolutionError, match="unknown tool"):
        resolve_tools(build_registry(), "data-validation", ["missing.tool"])

    registry = ToolRegistry()
    tool = Tool(name="demo.read", description="Demo", func=lambda: None, scopes={"a"})
    registry.register(tool)
    with pytest.raises(ToolResolutionError, match="not allowed"):
        resolve_tools(registry, "b", ["demo.read"])


def test_executor_validates_inputs_and_requires_confirmation():
    class Args(BaseModel):
        value: int

    calls: list[int] = []

    def add_one(value: int) -> int:
        calls.append(value)
        return value + 1

    tool = Tool(
        name="demo.write",
        description="Add one",
        func=add_one,
        input_schema=Args,
        risk="write",
        scopes={"*"},
        requires_confirmation=True,
        side_effects=True,
    )
    log = io.StringIO()
    executor = ToolExecutor(audit_log=log)

    with pytest.raises(ToolExecutionError, match="confirmation"):
        executor.execute(tool, {"value": 1})

    assert executor.execute(tool, {"value": "2"}, confirm=True) == 3
    assert calls == [2]
    assert "demo.write ok" in log.getvalue()

    with pytest.raises(ToolExecutionError, match="invalid args"):
        executor.execute(tool, {"value": "not-an-int"}, confirm=True)


def test_files_read_is_repo_scoped_and_secret_safe():
    assert "Agent Orchestrator" in RepoTools.read_file("SYSTEM.md")["content"]

    with pytest.raises(ValueError, match="secret"):
        RepoTools.read_file(".env")
    with pytest.raises(ValueError, match="outside"):
        RepoTools.read_file("../outside.txt")


def test_run_plan_schema_accepts_recorded_tools():
    plan = RunPlan.model_validate(
        {
            "run_id": "test-run",
            "skill": "security-compliance",
            "description": "Audit secrets",
            "risk": "read",
            "entrypoint_mode": "none",
            "owner": "security",
            "skill_file": "skills/security-compliance/SKILL.md",
            "entrypoints": [],
            "verifiers": [],
            "tools": [
                {
                    "name": "files.read",
                    "description": "Read a repository file",
                    "risk": "read",
                }
            ],
        }
    )
    assert plan.tools[0].name == "files.read"


def test_runner_records_dynamic_tools(tmp_path, capsys):
    code = runner.run_skill("security-compliance", dry_run=True, artifacts_dir=tmp_path)
    assert code == 0

    run_dir = next((tmp_path / "runs").iterdir())
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    assert [tool["name"] for tool in plan["tools"]] == ["files.read"]
    assert "tool: files.read (read)" in capsys.readouterr().out


def test_runner_rejects_an_unknown_declared_tool(tmp_path):
    _write_skill(tmp_path, name="unknown-tool-skill", tools="[missing.tool]")
    with pytest.raises(runner.SkillError, match="unknown tool"):
        runner.run_skill(
            "unknown-tool-skill",
            dry_run=True,
            skills_dir=tmp_path,
            artifacts_dir=tmp_path / "artifacts",
        )
