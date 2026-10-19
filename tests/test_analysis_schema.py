"""The worksheet schema without a database: order, validation, export.

The schema is the contract between the app, the stored payload and
``docs/InvestmentAnalysisWorkflow.md``, so these tests pin the workflow order, every
validation rule and both export formats.
"""

from __future__ import annotations

import json

from app import analysis_schema as schema

WORKFLOW_ORDER = [
    "universe",
    "macro",
    "industry",
    "capital_cycle",
    "supply",
    "demand",
    "consensus",
    "variant",
    "company",
    "earnings_quality",
    "moat",
    "management",
    "valuation",
    "scenarios",
    "analog",
    "risk",
    "portfolio",
    "final",
]


def filled_payload() -> dict:
    """A payload that passes every validation rule."""
    payload = schema.empty_payload()
    for section in schema.SECTIONS:
        values = payload["sections"][section.id]
        for field in section.all_fields:
            if field.kind == "select":
                values[field.id] = field.options[0]
            elif field.kind == "score":
                values[field.id] = 5
            else:
                values[field.id] = "A detailed answer for the worksheet."
    payload["sections"]["variant"]["key_evidence"] = (
        "First piece of evidence.\nSecond piece.\nThird piece."
    )
    payload["sections"]["final"]["thesis"] = "One sentence. Two sentences. Three sentences."
    return payload


# --- structure --------------------------------------------------------------------


def test_the_workflow_follows_the_documented_step_order():
    assert [section.id for section in schema.SECTIONS] == WORKFLOW_ORDER


def test_every_section_declares_well_formed_fields():
    for section in schema.SECTIONS:
        ids = [field.id for field in section.all_fields]
        assert len(ids) == len(set(ids)), f"duplicate field id in {section.id}"
        for field in section.all_fields:
            assert field.kind in schema.KINDS
            if field.kind == "select":
                assert field.options, f"{section.id}.{field.id} has no options"
                assert schema.PLACEHOLDER not in field.options


def test_analytical_sections_carry_a_confidence_block():
    for section in schema.SECTIONS:
        has_level = section.field("confidence") is not None
        assert has_level == section.has_confidence, section.id


# --- validation -------------------------------------------------------------------


def test_an_empty_worksheet_lists_every_required_field():
    errors = schema.validate(schema.empty_payload())
    required = [
        f"{section.title} / {field.label}"
        for section in schema.SECTIONS
        for field in section.all_fields
        if field.required
    ]
    assert len(errors) == len(required), errors
    for where in required:
        assert any(error.startswith(f"{where}:") for error in errors), where


def test_a_completed_worksheet_validates_cleanly():
    assert schema.validate(filled_payload()) == []


def test_a_placeholder_select_is_rejected_on_a_required_field():
    payload = filled_payload()
    payload["sections"]["macro"]["credit_verdict"] = schema.PLACEHOLDER
    errors = schema.validate(payload)
    assert any("Credit market verdict" in error for error in errors)


def test_an_unknown_select_option_is_rejected():
    payload = filled_payload()
    payload["sections"]["risk"]["business_risk"] = "Catastrophic"
    errors = schema.validate(payload)
    assert any("Catastrophic" in error for error in errors)


def test_a_score_must_be_a_whole_number_from_one_to_ten():
    payload = filled_payload()
    payload["sections"]["risk"]["overall_risk_score"] = 11
    assert any("1 to 10" in error for error in schema.validate(payload))
    payload["sections"]["risk"]["overall_risk_score"] = None
    assert any("required" in error for error in schema.validate(payload))


def test_low_confidence_requires_a_note_but_high_does_not():
    payload = filled_payload()
    payload["sections"]["macro"]["confidence"] = "Low"
    payload["sections"]["macro"]["confidence_note"] = ""
    assert any("confidence note" in error for error in schema.validate(payload))
    payload["sections"]["macro"]["confidence_note"] = "Thin credit data this cycle."
    assert schema.validate(payload) == []


def test_variant_evidence_needs_at_least_three_lines():
    payload = filled_payload()
    payload["sections"]["variant"]["key_evidence"] = "Only one line."
    errors = schema.validate(payload)
    assert any("three lines" in error for error in errors)


def test_the_thesis_must_be_three_sentences_or_fewer():
    payload = filled_payload()
    payload["sections"]["final"]["thesis"] = "One. Two. Three. Four."
    errors = schema.validate(payload)
    assert any("three sentences" in error for error in errors)


def test_a_missing_section_is_reported():
    payload = filled_payload()
    del payload["sections"]["risk"]
    assert any("Risk decomposition: section is missing" in e for e in schema.validate(payload))


# --- completion and summary -------------------------------------------------------


def test_completion_counts_only_required_fields():
    filled, total = schema.completion(filled_payload())
    assert filled == total > 0
    assert schema.completion(schema.empty_payload()) == (0, total)


def test_final_summary_reads_the_denormalised_columns():
    payload = filled_payload()
    payload["sections"]["risk"]["overall_risk_score"] = 4
    payload["sections"]["final"]["recommendation"] = "Add"
    payload["sections"]["final"]["confidence_overall"] = "Medium"
    summary = schema.final_summary(payload)
    assert summary["recommendation"] == "Add"
    assert summary["confidence"] == "Medium"
    assert summary["overall_risk_score"] == 4
    assert summary["thesis"].startswith("One sentence.")


def test_final_summary_of_an_empty_worksheet_is_empty_not_broken():
    summary = schema.final_summary(schema.empty_payload())
    assert summary["thesis"] == ""
    assert summary["recommendation"] is None
    assert summary["confidence"] is None
    assert summary["overall_risk_score"] is None


# --- export -----------------------------------------------------------------------


def test_json_export_round_trips():
    payload = filled_payload()
    assert json.loads(schema.to_json(payload)) == payload


def test_markdown_export_renders_every_step_in_order():
    markdown = schema.to_markdown(filled_payload(), "ABC")
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert len(headings) == len(schema.SECTIONS)
    for step, section in enumerate(schema.SECTIONS, start=1):
        assert headings[step - 1] == f"## {step}. {section.title}"
    assert markdown.startswith("# Investment analysis — ABC")


def test_markdown_export_ends_analytical_sections_with_a_confidence_block():
    markdown = schema.to_markdown(filled_payload(), "ABC")
    assert (
        markdown.count("Confidence Level:")
        == sum(1 for section in schema.SECTIONS if section.has_confidence) + 1
    )  # the final section renders the full block with its own level field
    assert "- Data quality:" in markdown
    assert "- Variant perception conviction:" in markdown


def test_markdown_export_skips_unset_fields():
    markdown = schema.to_markdown(schema.empty_payload(), "ABC")
    assert "**Credit market verdict:**" not in markdown
    assert "(unset)" in markdown  # the confidence block still shows its level line
