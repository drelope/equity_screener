from datetime import date

import pytest

from src.crispdm.pit import (
    FEATURE_BUILD_TIMING_MODE_DRAFT,
    FORWARD_RETURN_TIMING_MODE_DRAFT,
    WALK_FORWARD_TIMING_MODE_DRAFT,
    feature_window_pit_context,
    filing_period_availability_proxy,
    is_available_as_of,
    merge_pit_parameters,
    normalize_as_of,
    pit_manifest_metadata,
    require_as_of,
)


def test_normalize_as_of():
    assert normalize_as_of(None) is None
    assert normalize_as_of(date(2026, 11, 15)) == "2026-11-15"
    assert normalize_as_of("2026-11-15") == "2026-11-15"
    assert normalize_as_of(" 2026-11-15T12:00:00Z ") == "2026-11-15"


def test_require_as_of():
    assert require_as_of("2026-11-15", context="score") == "2026-11-15"
    with pytest.raises(ValueError):
        require_as_of(None, context="score")


def test_is_available_as_of():
    assert is_available_as_of("2026-01-01", "2026-01-01") is True
    assert is_available_as_of("2026-01-02", "2026-01-01") is False
    assert is_available_as_of(None, "2026-01-01") is None
    assert is_available_as_of("2026-01-01", None) is None


def test_filing_period_availability_proxy():
    assert filing_period_availability_proxy("2026-02-01", "2025-12-31") == "2026-02-01"
    assert filing_period_availability_proxy("2025-12-01", "2025-12-31") == "2025-12-31"
    assert filing_period_availability_proxy(None, "2025-12-31") is None


def test_pit_manifest_metadata_is_explicitly_unverified():
    meta = pit_manifest_metadata(as_of="2026-11-15")
    assert meta["pit_policy"] == "pit_draft_v0"
    assert meta["resolved_as_of"] == "2026-11-15"
    assert meta["verified_pit_compliant"] is False
    assert "universe_eligibility_mode" in meta


def test_merge_pit_parameters():
    out = merge_pit_parameters({"carry_days": 7}, as_of="2026-11-15", foo=None, bar=1)
    assert out["carry_days"] == 7
    assert out["as_of"] == "2026-11-15"
    assert out["bar"] == 1
    assert "foo" not in out


def test_feature_window_pit_context_modes():
    active = feature_window_pit_context(as_of="2026-11-15", carry_days=5)
    hist = feature_window_pit_context(as_of="2026-11-15", carry_days=5, include_historical=True)
    assert active["verified_pit_compliant"] is False
    assert active["carry_days"] == 5
    assert active["include_historical"] is False
    assert (
        "active_securities_feature_carry_forward_window_draft"
        in active["universe_eligibility_mode"]
    )
    assert hist["include_historical"] is True
    assert "active_or_historical" in hist["universe_eligibility_mode"]


def test_consumer_timing_mode_constants_are_explicit_drafts():
    assert FEATURE_BUILD_TIMING_MODE_DRAFT.endswith("_draft")
    assert FORWARD_RETURN_TIMING_MODE_DRAFT.endswith("_draft")
    assert WALK_FORWARD_TIMING_MODE_DRAFT.endswith("_draft")
