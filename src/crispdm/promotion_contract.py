"""Draft promotion contract fields for evaluation artifacts.

These constructors record the required structure and version identity. They do
not apply costs, validate a holdout, or create a promotion-grade claim.
"""

from __future__ import annotations

from typing import Any, Mapping

COST_MODEL_CONTRACT_ID = "cost_model_contract_v1"
COST_MODEL_CONTRACT_VERSION = "0.1.0-draft"
BENCHMARK_CONTRACT_ID = "benchmark_contract_v1"
BENCHMARK_CONTRACT_VERSION = "0.1.0-draft"
HOLDOUT_CONTRACT_ID = "holdout_reference_contract_v1"
HOLDOUT_CONTRACT_VERSION = "0.1.0-draft"


def draft_cost_model_contract() -> dict[str, Any]:
    return {
        "id": COST_MODEL_CONTRACT_ID,
        "version": COST_MODEL_CONTRACT_VERSION,
        "status": "draft_pending_dec_004",
        "applied": False,
        "required_assumptions": [
            "commission_bps",
            "spread_bps",
            "slippage_bps",
            "financing_rate_ref",
            "cash_treatment",
        ],
        "assumptions": None,
    }


def draft_benchmark_contract() -> dict[str, Any]:
    return {
        "id": BENCHMARK_CONTRACT_ID,
        "version": BENCHMARK_CONTRACT_VERSION,
        "status": "draft_pending_dec_004",
        "applied": False,
        "required_alignment": [
            "universe_alignment",
            "exposure_alignment",
            "rebalance_alignment",
            "cash_treatment",
        ],
        "definition": None,
    }


def draft_holdout_contract(holdout: Mapping[str, Any] | None = None) -> dict[str, Any]:
    supplied = dict(holdout or {})
    return {
        "id": HOLDOUT_CONTRACT_ID,
        "version": HOLDOUT_CONTRACT_VERSION,
        "status": "draft_pending_dec_002",
        "applied": False,
        "declared": bool(supplied),
        "id_ref": supplied.get("id"),
        "snapshot_ref": supplied.get("snapshot_ref"),
        "freeze_date": supplied.get("freeze_date"),
        "owner": supplied.get("owner"),
        "access_policy_ref": supplied.get("access_policy_ref"),
        "untouched_evidence_ref": supplied.get("untouched_evidence_ref"),
    }
