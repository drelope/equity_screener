"""clean.ticker_profile must not emit groups whose only rows are deactivated.

The rebuild groups raw profiles by (cik, ticker). A ticker that flipped
security_id leaves an inactive stale row behind, and the old query emitted it
as the representative when no active row remained -- polluting the curated
snapshot with deactivated instruments. Inactive payloads must still be
preserved in source_profiles for audit.
"""

from scripts.populate_clean_ticker_profile import REBUILD_SQL


def _normalized():
    return " ".join(REBUILD_SQL.split())


def test_rebuild_requires_an_active_representative():
    assert "WHERE representative.active = TRUE" in _normalized()


def test_rebuild_still_ranks_active_rows_first():
    # The active bonus keeps selection deterministic while the filter above
    # guarantees a group is dropped only when it has no active member at all.
    assert "CASE WHEN s.active THEN 1000 ELSE 0 END" in _normalized()


def test_rebuild_keeps_all_contributing_payloads_for_audit():
    assert "source_profiles" in _normalized()
    assert "JSONB_AGG(" in REBUILD_SQL


def test_source_profiles_carry_lineage_not_full_payloads():
    sql = _normalized()
    assert "'payload_hash'" in sql
    assert "'field_sources'" in sql
    assert "'raw_payload'" not in sql
