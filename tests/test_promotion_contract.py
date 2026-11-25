from scripts.check_promotion_evidence import check_draft_contract
from src.crispdm.promotion_contract import (
    draft_benchmark_contract,
    draft_cost_model_contract,
    draft_holdout_contract,
)


def test_cost_model_contract_is_versioned_and_unapplied():
    contract = draft_cost_model_contract()
    assert contract["id"] == "cost_model_contract_v1"
    assert contract["version"] == "0.1.0-draft"
    assert contract["applied"] is False
    assert "commission_bps" in contract["required_assumptions"]


def test_benchmark_contract_is_versioned_and_unapplied():
    contract = draft_benchmark_contract()
    assert contract["id"] == "benchmark_contract_v1"
    assert contract["version"] == "0.1.0-draft"
    assert contract["applied"] is False
    assert "exposure_alignment" in contract["required_alignment"]


def test_holdout_contract_declares_without_claiming_frozen():
    contract = draft_holdout_contract({"id": "H1", "freeze_date": "2026-01-01"})
    assert contract["status"] == "draft_pending_dec_002"
    assert contract["applied"] is False
    assert contract["declared"] is True
    assert contract["id_ref"] == "H1"


def test_default_policy_has_complete_draft_contract():
    from scripts.check_promotion_evidence import DEFAULT_POLICY

    assert check_draft_contract(DEFAULT_POLICY) == []
