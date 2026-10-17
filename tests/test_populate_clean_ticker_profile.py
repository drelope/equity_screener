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


def test_contract_preference_fills_only_absent_profile_values_with_lineage():
    sql = _normalized()
    assert "LEFT JOIN preferred.contract_terms AS ct ON ct.security_id = s.security_id" in sql
    assert "CASE WHEN grouped.liquidation_preference_count = 0" in sql
    assert "AND representative.security_type = 'preferred stock'" in sql
    assert "THEN representative.contract_liquidation_preference" in sql
    assert "ELSE grouped.liquidation_preference END" in sql
    assert "'contract_source_document_id', contract_source_document_id" in sql
    assert "grouped.liquidation_preference_count > 1" in sql


def test_contract_call_date_fills_only_absent_profile_values_with_lineage():
    sql = _normalized()
    assert "ct.first_call_date AS contract_first_call_date" in sql
    assert "CASE WHEN grouped.call_date_count = 0" in sql
    assert "THEN representative.contract_first_call_date" in sql
    assert "ELSE grouped.call_date END" in sql
    assert "'contract_first_call_date', contract_first_call_date" in sql


def test_contract_floating_terms_fill_only_absent_profile_values_with_lineage():
    sql = _normalized()
    assert "ct.fixed_period_end AS contract_fixed_period_end" in sql
    assert "ct.floating_spread AS contract_floating_spread" in sql
    assert "THEN representative.contract_fixed_period_end" in sql
    assert "ELSE grouped.fixed_period_end END" in sql
    assert "THEN representative.contract_floating_spread" in sql
    assert "ELSE grouped.floating_spread END" in sql
    assert "'contract_floating_spread', contract_floating_spread" in sql
