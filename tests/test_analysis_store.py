"""``analysis.investment_analyses`` against the real warehouse, rolled back.

Every test runs inside a transaction that is never committed, so the live tables are
untouched. The readiness probe doubles as the ``integration`` marker (see conftest).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app import analysis_schema as schema
from src.crispdm.analysis import store


def _live_engine():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1 FROM analysis.investment_analyses LIMIT 1")
        return engine
    except Exception:  # pragma: no cover - no database, or V0086 not applied
        return None


pytestmark = pytest.mark.skipif(
    _live_engine() is None, reason="no live database with the analysis schema"
)

BY = "pytest"


@pytest.fixture
def security(db_conn):
    row = db_conn.execute(
        text(
            "SELECT security_id::text, ticker FROM reference.securities "
            "WHERE active ORDER BY ticker LIMIT 1"
        )
    ).first()
    if row is None:
        pytest.skip("no active securities in the warehouse")
    return row[0], row[1]


def payload_with(thesis: str = "One. Two. Three.") -> dict:
    payload = schema.empty_payload()
    payload["sections"]["final"]["thesis"] = thesis
    return payload


def create(conn, security, **overrides):
    security_id, ticker = security
    args = {
        "security_id": security_id,
        "ticker": ticker,
        "payload": payload_with(),
        "thesis": "One. Two. Three.",
        "recommendation": "Hold",
        "confidence": "Medium",
        "overall_risk_score": 5,
        "status": "draft",
        "created_by": BY,
    }
    args.update(overrides)
    return store.create(conn, **args)


# --- create / read ----------------------------------------------------------------


def test_a_worksheet_round_trips_through_the_warehouse(db_conn, security):
    analysis_id = create(db_conn, security)

    row = store.get(db_conn, analysis_id)
    assert row["ticker"] == security[1]
    assert row["status"] == "draft"
    assert row["recommendation"] == "Hold" and row["confidence"] == "Medium"
    assert row["overall_risk_score"] == 5
    assert row["created_by"] == BY and row["updated_by"] is None
    assert row["schema_version"] == schema.SCHEMA_VERSION
    assert row["payload"] == payload_with()


def test_list_for_security_returns_the_newest_worksheet_first(db_conn, security):
    first = create(db_conn, security, thesis="First. Second. Third.")
    second = create(db_conn, security, thesis="Fourth. Fifth. Sixth.")

    rows = store.list_for_security(db_conn, security[0])
    ours = [row for row in rows if row["analysis_id"] in (first, second)]
    assert [row["analysis_id"] for row in ours] == [second, first]
    assert ours[0]["thesis"] == "Fourth. Fifth. Sixth."


def test_a_payload_without_sections_is_refused(db_conn, security):
    with pytest.raises(ValueError, match="no sections"):
        create(db_conn, security, payload={"version": schema.SCHEMA_VERSION})


# --- update / delete --------------------------------------------------------------


def test_update_overwrites_the_content_and_records_the_editor(db_conn, security):
    analysis_id = create(db_conn, security)
    before = store.get(db_conn, analysis_id)["updated_at"]

    changed = payload_with("Revised. Thesis. Here.")
    ok = store.update(
        db_conn,
        analysis_id,
        payload=changed,
        thesis="Revised. Thesis. Here.",
        recommendation="Add",
        confidence="High",
        overall_risk_score=3,
        status="final",
        updated_by="pytest-editor",
    )

    row = store.get(db_conn, analysis_id)
    assert ok and row["payload"] == changed
    assert row["status"] == "final" and row["recommendation"] == "Add"
    assert row["overall_risk_score"] == 3
    assert row["updated_by"] == "pytest-editor"
    assert row["updated_at"] >= before


def test_update_of_an_unknown_row_returns_false(db_conn):
    ok = store.update(
        db_conn,
        -1,
        payload=payload_with(),
        thesis="",
        recommendation=None,
        confidence=None,
        overall_risk_score=None,
        status="draft",
        updated_by="pytest-editor",
    )
    assert ok is False


def test_delete_removes_only_the_named_worksheet(db_conn, security):
    keep = create(db_conn, security)
    drop = create(db_conn, security)

    assert store.delete(db_conn, drop) is True
    assert store.delete(db_conn, drop) is False
    assert store.get(db_conn, drop) is None
    assert store.get(db_conn, keep) is not None


def test_the_status_column_refuses_values_outside_the_check_constraint(db_conn, security):
    analysis_id = create(db_conn, security)
    with pytest.raises(Exception):
        store.update(
            db_conn,
            analysis_id,
            payload=payload_with(),
            thesis="",
            recommendation=None,
            confidence=None,
            overall_risk_score=None,
            status="published",
            updated_by="pytest-editor",
        )


def test_list_for_security_carries_both_audit_labels(db_conn, security):
    analysis_id = create(db_conn, security)
    store.update(
        db_conn,
        analysis_id,
        payload=payload_with(),
        thesis="One. Two. Three.",
        recommendation=None,
        confidence=None,
        overall_risk_score=None,
        status="draft",
        updated_by="pytest-editor",
    )

    rows = [
        r for r in store.list_for_security(db_conn, security[0]) if r["analysis_id"] == analysis_id
    ]
    assert rows and rows[0]["created_by"] == BY and rows[0]["updated_by"] == "pytest-editor"


# --- status transitions -----------------------------------------------------------


def _demote(db_conn, analysis_id, **kwargs):
    return store.update(
        db_conn,
        analysis_id,
        payload=payload_with(),
        thesis="",
        recommendation=None,
        confidence=None,
        overall_risk_score=None,
        status="draft",
        updated_by="pytest-editor",
        **kwargs,
    )


def test_a_final_worksheet_cannot_be_demoted_without_an_explicit_reopen(db_conn, security):
    analysis_id = create(db_conn, security, status="final")

    with pytest.raises(store.StatusTransitionError):
        _demote(db_conn, analysis_id)

    assert store.get(db_conn, analysis_id)["status"] == "final"


def test_a_final_worksheet_can_be_reopened_as_a_draft_deliberately(db_conn, security):
    analysis_id = create(db_conn, security, status="final")

    assert _demote(db_conn, analysis_id, reopen=True) is True
    assert store.get(db_conn, analysis_id)["status"] == "draft"


def test_draft_to_final_needs_no_reopen_flag(db_conn, security):
    analysis_id = create(db_conn, security)  # draft

    ok = store.update(
        db_conn,
        analysis_id,
        payload=payload_with(),
        thesis="One. Two. Three.",
        recommendation="Hold",
        confidence="Medium",
        overall_risk_score=5,
        status="final",
        updated_by="pytest-editor",
    )

    assert ok and store.get(db_conn, analysis_id)["status"] == "final"


def test_the_transition_guard_does_not_misfire_on_an_unknown_row(db_conn):
    assert _demote(db_conn, -1) is False


# --- revisions --------------------------------------------------------------------


def test_the_first_save_is_kept_as_a_revision(db_conn, security):
    analysis_id = create(db_conn, security)

    revisions = store.revisions(db_conn, analysis_id)
    assert len(revisions) == 1
    assert revisions[0]["status"] == "draft"
    assert revisions[0]["saved_by"] == BY
    assert revisions[0]["payload"] == payload_with()


def test_each_later_save_appends_a_revision_newest_first(db_conn, security):
    analysis_id = create(db_conn, security)
    store.update(
        db_conn,
        analysis_id,
        payload=payload_with("Second. Save. Here."),
        thesis="Second. Save. Here.",
        recommendation="Add",
        confidence="High",
        overall_risk_score=3,
        status="final",
        updated_by="pytest-editor",
    )

    revisions = store.revisions(db_conn, analysis_id)
    assert [r["saved_by"] for r in revisions] == ["pytest-editor", BY]
    assert [r["status"] for r in revisions] == ["final", "draft"]
    assert revisions[0]["thesis"] == "Second. Save. Here."
    assert [r["revision_id"] for r in revisions] == sorted(
        (r["revision_id"] for r in revisions), reverse=True
    )


def test_revisions_are_deleted_with_their_worksheet(db_conn, security):
    analysis_id = create(db_conn, security)
    assert store.revisions(db_conn, analysis_id)

    store.delete(db_conn, analysis_id)

    assert store.revisions(db_conn, analysis_id) == []


# --- recommendation history -------------------------------------------------------


def _set_call(db_conn, analysis_id, recommendation, status="draft"):
    return store.update(
        db_conn,
        analysis_id,
        payload=payload_with(),
        thesis="One. Two. Three.",
        recommendation=recommendation,
        confidence="Medium",
        overall_risk_score=5,
        status=status,
        updated_by="pytest-editor",
    )


def _our_history(db_conn, security, analysis_ids):
    rows = store.recommendation_history(db_conn, security[0])
    return [row for row in rows if row["analysis_id"] in analysis_ids]


def test_recommendation_history_keeps_only_changes_newest_first(db_conn, security):
    analysis_id = create(db_conn, security)  # Hold
    _set_call(db_conn, analysis_id, "Hold")  # unchanged, collapsed
    _set_call(db_conn, analysis_id, "Add")
    _set_call(db_conn, analysis_id, "Add")  # unchanged again
    _set_call(db_conn, analysis_id, "Trim")

    history = _our_history(db_conn, security, {analysis_id})

    assert [row["recommendation"] for row in history] == ["Trim", "Add", "Hold"]
    assert [row["previous"] for row in history] == ["Add", "Hold", None]
    assert [row["status"] for row in history] == ["draft", "draft", "draft"]


def test_recommendation_history_skips_a_withdrawn_call(db_conn, security):
    analysis_id = create(db_conn, security)  # Hold
    _set_call(db_conn, analysis_id, None)  # withdrawn
    _set_call(db_conn, analysis_id, "Buy")

    history = _our_history(db_conn, security, {analysis_id})

    assert [row["recommendation"] for row in history] == ["Buy", "Hold"]
    assert [row["previous"] for row in history] == ["Hold", None]


def test_recommendation_history_spans_worksheets_newest_first(db_conn, security):
    first = create(db_conn, security, recommendation="Buy")
    second = create(db_conn, security, recommendation="Sell")

    history = _our_history(db_conn, security, {first, second})

    assert [row["recommendation"] for row in history] == ["Sell", "Buy"]
    assert all(row["previous"] is None for row in history)
    assert all(row["saved_by"] == BY for row in history)


def test_recommendation_history_ignores_worksheets_with_no_call(db_conn, security):
    analysis_id = create(db_conn, security, recommendation=None)

    assert _our_history(db_conn, security, {analysis_id}) == []
