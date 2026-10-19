"""The workflow document and the schema must not drift apart.

``docs/InvestmentAnalysisWorkflow.md`` is written to mirror ``app/analysis_schema.py``:
the document is the analyst-facing contract, the module is the executable one. When a
step or field is added to one and not the other, the analyst reads a document that lies.
These tests parse the document and compare it to the schema, so drift fails CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import analysis_schema as schema

DOC = Path(__file__).resolve().parents[1] / "docs" / "InvestmentAnalysisWorkflow.md"


def _document() -> str:
    return DOC.read_text(encoding="utf-8")


def test_the_document_exists():
    assert DOC.is_file()


def test_the_documented_steps_match_the_schema_in_order():
    headings = re.findall(r"^### \d+\.\s+.+?\s+—\s+`([a-z_]+)`", _document(), re.M)
    assert headings == [section.id for section in schema.SECTIONS]


def test_every_field_id_matches_in_both_directions():
    text = _document()
    # Field ids sit in the first cell of each table row, either alone or as several
    # ids separated by "/" (the auto-added confidence/sources block). Collect them all.
    documented: set[str] = set()
    for cell in re.findall(r"^\|\s*(`[^|]+`)\s*\|", text, re.M):
        documented.update(re.findall(r"`([a-z0-9_]+)`", cell))
    declared = {field.id for section in schema.SECTIONS for field in section.all_fields}
    assert documented == declared, {
        "only_in_document": sorted(documented - declared),
        "only_in_schema": sorted(declared - documented),
    }
