"""The deterministic skill audit must fail closed on unsafe or incomplete skills."""

from __future__ import annotations

from pathlib import Path

from scripts import agent_runner as runner
from scripts import skill_audit as audit
from src.agent.tools import Tool, ToolRegistry


def _skill_text(
    name: str = "demo-skill",
    *,
    risk: str = "read",
    tools: str = "[]",
    tags: str = "[]",
    extra: str = "",
) -> str:
    sections = "\n\n".join(f"{section}\n\nPlaceholder." for section in runner.REQUIRED_SECTIONS)
    return f"""---
name: {name}
description: "Use when testing the audit contract. Do not use for production work."
version: 1
risk: {risk}
owner: test
entrypoint: none
tools: {tools}
tags: {tags}
---

# Demo

{sections}

- `skills/{name}/SKILL.md`

{extra}
"""


def _write_skill(
    root: Path,
    name: str = "demo-skill",
    *,
    risk: str = "read",
    tools: str = "[]",
    tags: str = "[]",
    extra: str = "",
) -> Path:
    directory = root / "skills" / name
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(
        _skill_text(name, risk=risk, tools=tools, tags=tags, extra=extra), encoding="utf-8"
    )
    return path


def _design_text(
    *, verify: str = "pass", open_questions: str = "none", results: dict[str, str] | None = None
) -> str:
    results = results or {}
    gate = "\n".join(
        f"| {phase} | {results.get(phase, 'pass' if phase != 'verify' else verify)} | evidence |"
        for phase in audit.PHASES
    )
    return f"""# Skill Design: demo-skill

Open questions: {open_questions}

## Clarify

## Design

## Plan

## Code

## Verify

## Gate log

| Phase | Result | Evidence |
|---|---|---|
{gate}
"""


def _write_design(root: Path, name: str = "demo-skill", **kwargs) -> Path:
    path = root / "docs" / "skill-designs" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_design_text(**kwargs), encoding="utf-8")
    return path


def _codes(findings: list[audit.Finding]) -> set[str]:
    return {finding.code for finding in findings}


def test_a_clean_skill_passes(tmp_path):
    _write_skill(tmp_path)
    assert audit.audit_skill("demo-skill", root=tmp_path) == []


def test_a_missing_required_section_is_a_contract_failure(tmp_path):
    path = _write_skill(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8").replace("## Verification", "## Removed"),
        encoding="utf-8",
    )
    findings = audit.audit_skill("demo-skill", root=tmp_path)
    assert _codes(findings) == {"contract"}


def test_broken_links_and_source_paths_are_rejected(tmp_path):
    _write_skill(
        tmp_path,
        extra="- [missing](references/missing.md)\n- `no/such/file.py`",
    )
    findings = audit.audit_skill("demo-skill", root=tmp_path)
    assert "link" in _codes(findings)
    assert "source-path" in _codes(findings)


def test_secrets_and_absolute_paths_are_rejected(tmp_path):
    _write_skill(tmp_path, extra="API_KEY=supersecret123\n\nSee /mnt/c/private/data.")
    findings = audit.audit_skill("demo-skill", root=tmp_path)
    assert "secret" in _codes(findings)
    assert "absolute-path" in _codes(findings)


def test_an_oversized_skill_is_rejected(tmp_path):
    _write_skill(tmp_path, extra="x" * (audit.MAX_SKILL_CHARS + 1))
    findings = audit.audit_skill("demo-skill", root=tmp_path)
    assert "budget" in _codes(findings)


def test_references_need_a_load_trigger_and_a_link(tmp_path):
    _write_skill(tmp_path)
    ref = tmp_path / "skills" / "demo-skill" / "references" / "extra.md"
    ref.parent.mkdir()
    ref.write_text("# Extra\n\nNo trigger here.\n", encoding="utf-8")
    findings = audit.audit_skill("demo-skill", root=tmp_path)
    reference_findings = [f for f in findings if f.code == "reference"]
    assert len(reference_findings) == 2


def test_a_linked_reference_with_a_trigger_passes(tmp_path):
    _write_skill(
        tmp_path,
        extra="- [extra](references/extra.md)",
    )
    ref = tmp_path / "skills" / "demo-skill" / "references" / "extra.md"
    ref.parent.mkdir()
    ref.write_text("# Extra\n\nLoad when: the extra detail is needed.\n", encoding="utf-8")
    assert audit.audit_skill("demo-skill", root=tmp_path) == []


def test_unknown_handoffs_are_rejected(tmp_path):
    _write_skill(tmp_path, extra="Route to `missing-skill` for the rest.")
    findings = audit.audit_skill("demo-skill", root=tmp_path)
    assert "handoff" in _codes(findings)


def test_a_read_skill_cannot_declare_a_write_tool(tmp_path, monkeypatch):
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="demo.write",
            description="Demo write",
            func=lambda: None,
            risk="write",
            scopes={"demo-skill"},
            side_effects=True,
        )
    )
    monkeypatch.setattr(audit, "build_registry", lambda: registry)
    _write_skill(tmp_path, tools="[demo.write]")
    findings = audit.audit_skill("demo-skill", root=tmp_path)
    assert "tool" in _codes(findings)


def test_lifecycle_skills_need_a_complete_passing_design_record(tmp_path):
    _write_skill(tmp_path, tags="[lifecycle]")
    assert "design" in _codes(audit.audit_skill("demo-skill", root=tmp_path))

    _write_design(tmp_path, verify="pending")
    assert "design-gate" in _codes(audit.audit_skill("demo-skill", root=tmp_path))

    _write_design(tmp_path)
    assert audit.audit_skill("demo-skill", root=tmp_path) == []


def test_a_phase_audit_only_requires_gates_through_that_phase(tmp_path):
    _write_skill(tmp_path, tags="[lifecycle]")
    _write_design(
        tmp_path,
        results={"clarify": "pass", "design": "pending", "plan": "pending", "code": "pending"},
        verify="pending",
    )
    assert audit.audit_skill("demo-skill", root=tmp_path, through="clarify") == []
    assert "design-gate" in _codes(audit.audit_skill("demo-skill", root=tmp_path))


def test_repository_audit_detects_routing_and_system_drift(tmp_path):
    _write_skill(tmp_path)
    _write_design(tmp_path)
    lifecycle = tmp_path / "docs" / "skill-lifecycle.md"
    lifecycle.parent.mkdir(parents=True, exist_ok=True)
    lifecycle.write_text("# Lifecycle\n", encoding="utf-8")
    workflow = tmp_path / "docs" / "file-based-agentic-workflow.md"
    workflow.write_text(
        "## 8. Routing table\n\n| Intake | Primary skill | Entrypoint | Verifier |\n"
        "|---|---|---|---|\n| Demo | `other-skill` | x | x |\n\n## 9. Skill inventory\n",
        encoding="utf-8",
    )
    (tmp_path / "SYSTEM.md").write_text(
        "| Skill | Risk | Phase |\n|---|---|---|\n| `other-skill` | read | 1 |\n",
        encoding="utf-8",
    )

    findings = audit.audit_repository(root=tmp_path)
    assert _codes(findings) == {"routing", "system"}

    workflow.write_text(
        "## 8. Routing table\n\n| Intake | Primary skill | Entrypoint | Verifier |\n"
        "|---|---|---|---|\n| Demo | `demo-skill` | x | x |\n\n## 9. Skill inventory\n",
        encoding="utf-8",
    )
    (tmp_path / "SYSTEM.md").write_text(
        "| Skill | Risk | Phase |\n|---|---|---|\n| `demo-skill` | read | 1 |\n",
        encoding="utf-8",
    )
    assert audit.audit_repository(root=tmp_path) == []
