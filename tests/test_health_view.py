"""The Health page's stage-timing helpers: pure, no database needed."""

import pytest

pytest.importorskip("streamlit")
from app.views.health import _slowest_stage, _stage_rows  # noqa: E402


def test_stage_rows_lists_outcomes_with_seconds_and_hides_the_reserved_key():
    stages = {"a": "ok", "b": "failed", "_seconds": {"a": 1.5, "b": 20.0}}

    assert _stage_rows(stages) == [
        {"stage": "a", "result": "ok", "seconds": 1.5},
        {"stage": "b", "result": "failed", "seconds": 20.0},
    ]


def test_stage_rows_handles_a_run_recorded_without_timings():
    assert _stage_rows({"a": "ok"}) == [{"stage": "a", "result": "ok", "seconds": None}]
    assert _stage_rows(None) == []


def test_slowest_stage_names_the_longest_one():
    assert _slowest_stage({"a": "ok", "_seconds": {"a": 1.5, "b": 20.0}}) == "b (20s)"
    assert _slowest_stage({"a": "ok"}) == "-"
    assert _slowest_stage(None) == "-"
