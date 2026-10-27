"""The financial-scoring skill must implement policy, not own it."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "financial-scoring" / "SKILL.md"
REFERENCES = ROOT / "skills" / "financial-scoring" / "references"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_skill_is_write_and_has_no_runner_entrypoint():
    text = _text()

    assert "name: financial-scoring" in text
    assert "risk: write" in text
    assert "entrypoint: none" in text
    assert "lifecycle" in text


def test_skill_has_the_standard_sections():
    text = _text()

    for section in (
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
        "## References",
    ):
        assert section in text


def test_policy_ownership_is_explicit_and_does_not_self_route():
    text = _text()

    assert "business-understanding` decides the universe rule, weights" in text.lower() or (
        "policy is decided by `business-understanding`" in text.lower()
    )
    assert "scoring policy" not in text.lower()
    assert "route to `financial-scoring`" not in text


def test_replay_and_pruning_rules_are_present():
    text = _text()

    assert "--prune-superseded" in text
    assert "only the scored date" in text
    assert "historical" in text.lower()
    assert "rank diff" in text.lower()


def test_references_are_linked_and_have_load_triggers():
    text = _text()

    for name in ("scoring-model.md", "change-and-replay.md"):
        assert f"(references/{name})" in text

    for path in REFERENCES.glob("*.md"):
        content = path.read_text(encoding="utf-8")
        assert content.startswith("# ")
        assert "Load when:" in content
