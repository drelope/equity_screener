"""The workflow document, SYSTEM.md and skills must not drift apart.

The routing table is the single source for which skill owns an intake. These
tests parse it and the skill files, so a rename, a missing directory or a broken
contract fails CI instead of leaving an agent with a route to nowhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts import agent_runner as runner

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "file-based-agentic-workflow.md"
SYSTEM = ROOT / "SYSTEM.md"


def _routing_skills() -> set[str]:
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## 8. Routing table", 1)[1].split("## 9.", 1)[0]
    skills: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        match = re.fullmatch(r"`([a-z0-9-]+)`", cells[1])
        if match:
            skills.add(match.group(1))
    return skills


def _system_skills() -> set[str]:
    skills: set[str] = set()
    for line in SYSTEM.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        match = re.fullmatch(r"`([a-z0-9-]+)`", cells[0])
        if match and cells[1] in runner.RISKS:
            skills.add(match.group(1))
    return skills


def test_every_routed_skill_directory_exists():
    routed = _routing_skills()
    assert len(routed) == 21
    on_disk = {skill.name for skill in runner.list_skills()}
    assert routed == on_disk


def test_system_md_lists_every_skill_with_its_risk():
    on_disk = {skill.name: skill.risk for skill in runner.list_skills()}
    assert _system_skills() == set(on_disk)
    for name, risk in on_disk.items():
        row = next(
            line
            for line in SYSTEM.read_text(encoding="utf-8").splitlines()
            if line.startswith(f"| `{name}`")
        )
        assert f"| {risk} |" in row


def test_every_skill_satisfies_the_contract():
    for skill in runner.list_skills():
        assert skill.description
        assert skill.path.name == "SKILL.md"
        text = skill.path.read_text(encoding="utf-8")
        for section in runner.REQUIRED_SECTIONS:
            assert section in text, f"{skill.name}: missing {section}"


def test_skill_handoffs_point_at_existing_skills():
    names = {skill.name for skill in runner.list_skills()}
    for skill in runner.list_skills():
        text = skill.path.read_text(encoding="utf-8")
        refs = set(re.findall(r"(?:route to|→)\s*`([a-z0-9-]+)`", text))
        missing = sorted(ref for ref in refs if ref not in names)
        assert not missing, f"{skill.name}: unknown handoff(s) {missing}"


def test_no_skill_references_a_missing_script():
    paths = [skill.path for skill in runner.list_skills()]
    paths.append(ROOT / "skills" / "_template" / "SKILL.md")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for module in set(re.findall(r"scripts\.([a-z_]+)", text)):
            assert (ROOT / "scripts" / f"{module}.py").is_file(), (
                f"{path.parent.name}: scripts/{module}.py does not exist"
            )


def test_skill_entrypoint_modes_match_the_runner():
    for skill in runner.list_skills():
        expected = "fixed" if skill.name in runner.ENTRYPOINTS else "none"
        assert skill.entrypoint_mode == expected, (
            f"{skill.name}: frontmatter entrypoint is {skill.entrypoint_mode!r}, "
            f"expected {expected!r}"
        )


def test_entrypoints_are_valid_and_verifiable():
    skills = {skill.name: skill for skill in runner.list_skills()}
    for name, commands in runner.ENTRYPOINTS.items():
        assert name in skills
        assert runner.VERIFIERS.get(name), f"{name}: entrypoint without verifier"
        for command in commands:
            assert runner.MODULE.match(command[0]), command
            assert (ROOT / f"{command[0].replace('.', '/')}.py").is_file(), command


def test_dry_run_writes_a_plan_and_executes_nothing(tmp_path, capsys):
    code = runner.run_skill(
        "observability-nightly-verification", dry_run=True, artifacts_dir=tmp_path
    )
    assert code == 0
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    plan = (runs[0] / "plan.json").read_text(encoding="utf-8")
    assert '"skill": "observability-nightly-verification"' in plan
    assert "python -m scripts.verify_nightly_run" in capsys.readouterr().out
    assert not (runs[0] / "commands.log").exists()


def test_a_skill_without_entrypoint_can_only_be_inspected(tmp_path):
    assert runner.run_skill("data-understanding", dry_run=True, artifacts_dir=tmp_path) == 0
    with pytest.raises(runner.SkillError, match="no executable entrypoint"):
        runner.run_skill("data-understanding", artifacts_dir=tmp_path)


def test_a_write_skill_requires_confirmation(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(runner, "_run", lambda *args, **kwargs: called.append(args))
    code = runner.run_skill(
        "data-storage-schema", yes=False, artifacts_dir=tmp_path, run_id="confirm"
    )
    assert code == 2
    assert called == []


def test_unknown_or_mismatched_skill_is_refused():
    with pytest.raises(runner.SkillError, match="unknown skill"):
        runner.load_skill("does-not-exist")
    with pytest.raises(runner.SkillError, match="kebab-case"):
        runner.load_skill("Bad_Name")


def test_verify_reads_the_recorded_result(tmp_path):
    run_dir = tmp_path / "runs" / "sample"
    run_dir.mkdir(parents=True)
    (run_dir / "verification.json").write_text(
        '{"skill": "data-validation", "passed": true, "entrypoint": [], "verifier": []}',
        encoding="utf-8",
    )
    assert runner.show_verification("sample", tmp_path) == 0
    assert runner.show_verification("missing", tmp_path) == 2
