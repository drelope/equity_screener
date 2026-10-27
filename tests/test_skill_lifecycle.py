"""The five lifecycle skills and their shared contract must not drift."""

from __future__ import annotations

from pathlib import Path

from scripts import agent_runner as runner

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "docs" / "skill-lifecycle.md"
DESIGNS = ROOT / "docs" / "skill-designs"

PHASES = ("clarify", "design", "plan", "code", "verify")
NAMES = tuple(f"skill-{phase}" for phase in PHASES)


def _text(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_all_five_lifecycle_skills_exist_and_are_routed():
    names = {skill.name for skill in runner.list_skills()}
    assert set(NAMES) <= names

    system = (ROOT / "SYSTEM.md").read_text(encoding="utf-8")
    workflow = (ROOT / "docs" / "file-based-agentic-workflow.md").read_text(encoding="utf-8")
    for name in NAMES:
        assert f"`{name}`" in system
        assert f"`{name}`" in workflow


def test_lifecycle_risk_and_entrypoint_modes_are_explicit():
    expected = {
        "skill-clarify": ("write", "none"),
        "skill-design": ("write", "none"),
        "skill-plan": ("write", "none"),
        "skill-code": ("write", "none"),
        "skill-verify": ("read", "fixed"),
    }
    for name, (risk, entrypoint) in expected.items():
        skill = runner.load_skill(name)
        assert skill.risk == risk, name
        assert skill.entrypoint_mode == entrypoint, name


def test_skill_verify_is_the_only_fixed_lifecycle_entrypoint():
    assert runner.ENTRYPOINTS["skill-verify"] == (("scripts.skill_audit", "--all"),)
    assert runner.VERIFIERS["skill-verify"] == (("scripts.skill_audit", "--all"),)
    for name in NAMES[:-1]:
        assert name not in runner.ENTRYPOINTS


def test_each_phase_hands_off_to_the_next_gate():
    for phase, next_phase in zip(PHASES, PHASES[1:]):
        text = _text(f"skill-{phase}")
        assert f"`skill-{next_phase}`" in text, f"skill-{phase} does not hand off"


def test_lifecycle_doc_defines_every_gate_and_the_audit():
    text = LIFECYCLE.read_text(encoding="utf-8")

    assert "docs/skill-designs" in text
    assert "python -m scripts.skill_audit --all" in text
    for phase in PHASES:
        assert phase in text.lower()


def test_lifecycle_template_has_every_gate_row():
    text = (DESIGNS / "_template.md").read_text(encoding="utf-8")

    assert "Open questions: none" in text
    for phase in PHASES:
        assert f"| {phase} |" in text


def test_financial_skills_are_lifecycle_tagged_with_design_records():
    for name in ("financial-analysis", "financial-scoring"):
        assert (DESIGNS / f"{name}.md").is_file()
        assert "lifecycle" in _text(name).split("---", 2)[1]
