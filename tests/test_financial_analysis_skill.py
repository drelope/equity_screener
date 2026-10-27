"""The financial-analysis skill and its dashboard methodology must stay aligned."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "financial-analysis" / "SKILL.md"
DASHBOARD_DOC = ROOT / "docs" / "AnalystDashboard.md"
REFERENCES = ROOT / "skills" / "financial-analysis" / "references"

TAB_NAMES = (
    "Portfolio Dashboard",
    "Performance Analytics",
    "Risk Monitor",
    "Position Book",
    "Factor Attribution",
    "Research Pipeline",
    "Reports Center",
)


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _all_text() -> str:
    paths = [SKILL, *sorted(REFERENCES.glob("*.md"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_skill_is_read_only_and_has_no_runner_entrypoint():
    text = _text()

    assert "name: financial-analysis" in text
    assert "risk: read" in text
    assert "entrypoint: none" in text


def test_skill_has_the_required_sections():
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


def test_skill_uses_all_three_on_demand_references():
    text = _text()

    for name in ("kpi-library.md", "validation-and-risk.md", "reports-and-dashboard.md"):
        assert f"(references/{name})" in text

    for path in REFERENCES.glob("*.md"):
        assert path.read_text(encoding="utf-8").startswith("# ")
        assert "Load when:" in path.read_text(encoding="utf-8")


def test_skill_names_all_seven_dashboard_tabs():
    text = _text()

    for name in TAB_NAMES:
        assert name in text


def test_skill_states_the_current_composite_weights_and_floor():
    text = _text()

    assert "1/3 (33.33%)" in text
    assert "4/15 (26.67%)" in text
    assert "1/5 (20.00%)" in text
    assert "2/15 (13.33%)" in text
    assert "1/15 (6.67%)" in text
    assert "MIN_PRESENT_WEIGHT` is 0.50" in text


def test_references_preserve_kpi_validation_and_report_detail():
    text = _all_text()

    for phrase in (
        "dividend_coverage",
        "cash_conversion",
        "Investment validation checklist",
        "component VaR",
        "survivorship bias",
        "An IC memo is generated only from a saved **Final** worksheet",
        "not a Fama-French regression",
    ):
        assert phrase in text


def test_dashboard_methodology_document_covers_construction_and_limits():
    text = DASHBOARD_DOC.read_text(encoding="utf-8")

    for phrase in (
        "simulated",
        "completed",
        "score_coverage >= 0.50",
        "top 15",
        "bottom 8",
        "$100M",
        "Gross exposure is therefore 150%",
        "borrow, financing, slippage",
        "not a Fama-French regression",
        "Known limitations",
    ):
        assert phrase in text
