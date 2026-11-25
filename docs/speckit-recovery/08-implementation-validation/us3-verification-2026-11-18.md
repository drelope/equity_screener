# US3 Verification: Evaluation Contract Inputs

**Feature**: `specs/001-p0-recovery/spec.md`

**Scope**: T023–T029 (P2)

**Status**: Draft contract scaffolding; promotion-grade evaluation evidence remains blocked

## T023 / T027 — Versioned policy fields

`promotion-policy-template.json` now records:

- `version`: `0.1.0-draft-contract`
- `acceptance_policy.id`: `DRAFT-acceptance-policy`
- `acceptance_policy.version`: `0.1.0-draft-contract`
- `acceptance_policy.change_control_ref`: M1 decision log
- `cost_model.id/version/status`: `cost_model_contract_v1`, `0.1.0-draft`, `draft_pending_dec_004`
- `benchmark.id/version/status`: `benchmark_contract_v1`, `0.1.0-draft`, `draft_pending_dec_004`
- `holdout.contract_id/contract_version/status`: draft contract identity, `draft_pending_dec_002`
- `promotion_decision.acceptance_policy_ref`: dated draft policy reference

These are structure and lineage fields. They do not approve a policy or apply economics.

## T024 / T025 — Cost model and exposure-matched benchmark contracts

- `src/crispdm/promotion_contract.py` provides `draft_cost_model_contract()` and `draft_benchmark_contract()`.
- `src/crispdm/backtest.py` records `cost_model_contract` and `exposure_matched_benchmark_contract` in metrics.
- `scripts/backtest.py` replaces the old inline placeholders with the shared versioned draft contracts.
- All contracts have `applied=False`; no costs, financing, slippage, exposure alignment, or net-return computation is applied.

## T026 — Frozen holdout references

- `scripts/evaluate_walk_forward.py` accepts explicit `--holdout-id`, `--holdout-snapshot-ref`, `--holdout-freeze-date`, `--holdout-owner`, `--holdout-access-policy-ref`, and `--holdout-untouched-evidence-ref`.
- The manifest records `draft_holdout_contract()` under inputs.
- Absent values leave the holdout declared-but-unconfigured; no holdout is validated or treated as frozen.

## T028 — Named promotion gaps

- `scripts/check_promotion_evidence.py` adds `check_draft_contract()` and `DRAFT_CONTRACT_PATHS`.
- Policy structure is checked separately from promotion-grade gaps.
- `--require-promotion-grade` still fails with named null/approval gaps.

## T029 — Dated evaluation evidence

This file is the dated evidence artifact. Acceptance-policy reference: `DRAFT-acceptance-policy@0.1.0-draft-contract` (2026-11-18).

## US3 checkpoint

Versioned evaluation contract fields and named gaps are present. Promotion-grade evaluation inputs are **not** complete: holdout freeze, cost values, net returns, exposure alignment, and statistical validity remain external/DEC-002..005-gated.
