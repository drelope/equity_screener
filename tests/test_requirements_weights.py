"""The requirements table and UI caption must match the scorer's weights."""

from __future__ import annotations

from pathlib import Path

from app import column_docs
from src.crispdm.scoring import WEIGHTS

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "docs" / "requirements.md"


def _weight_section() -> str:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    return text.split("## 3. Scoring weights", 1)[1].split("## 4.", 1)[0]


def test_requirements_weight_table_matches_scoring():
    section = _weight_section()
    for name, weight in WEIGHTS.items():
        row = next(line for line in section.splitlines() if line.startswith(f"| {name} "))
        assert f"{weight:.1%}" in row, row


def test_retired_legal_rights_factor_is_not_in_the_weight_table():
    assert not any(
        line.startswith("| legal_rights_score ") for line in _weight_section().splitlines()
    )


def test_ui_caption_is_derived_from_the_scoring_weights():
    expected = " | ".join(
        f"{column_docs._WEIGHT_LABELS[name]} {weight:.1%}" for name, weight in WEIGHTS.items()
    )
    assert column_docs.SCORING_CAPTION == expected


def test_both_weight_displays_use_the_shared_caption():
    for relative in ("app/views/screener.py", "app/streamlit_app.py"):
        assert "SCORING_CAPTION" in (ROOT / relative).read_text(encoding="utf-8")
