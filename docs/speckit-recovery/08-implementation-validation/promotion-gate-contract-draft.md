# Promotion / Evaluation Gate Contract Draft (RM-07, DEC-002..005)

| Field | Value |
|---|---|
| Date | 2026-11-16 |
| Status | **Draft/scaffolding only** — `DEC-002/003/004/005` pending approval |
| Scope | `FR-EVAL-02/03/04/05`, `FR-BT-03/04/05`, `AC-P0-10`, `TSK-002/003`, `P0-TSK-007/010` |

## Objective
Define evidence required before any promotion-grade or decision-grade performance/model claim. Current production default remains **rule-based scoring** unless a promotion gate explicitly passes with recorded evidence and approvals.

## Required evidence (all mandatory for promotion-grade claim)

| Area | Requirement | Draft fields/artifacts | DEC/owner |
|---|---|---|---|
| Frozen holdout | Untouched holdout dataset/snapshot/version frozen before tuning/evaluation; access/control recorded | `holdout.id`, `holdout.snapshot_hash`, `holdout.freeze_date`, `holdout.owner`, `holdout.access_policy_ref` | DEC-002 |
| Acceptance policy | Versioned policy with effective date, criteria, blocking/diagnostic checks, change-control record | `acceptance_policy.id`, `version`, `effective_date`, `criteria`, `blocking_checks`, `diagnostics`, `change_record_ref` | DEC-003 |
| Cost model | Explicit trading/financing/slippage/spread/cash assumptions; gross and net reported | `cost_model.id/version`, assumptions, `gross_*`, `net_*` metrics | DEC-004 |
| Benchmark | Exposure-matched benchmark definition and alignment with strategy universe/holding/cash treatment | `benchmark.id/version`, construction, exposure_match, comparison metrics | DEC-004 |
| Manifests/provenance | Immutable run manifests linking code/config/policy/inputs/outputs/env/lock hashes | `run_id`, `manifest_path/hash`, `code_sha`, `data_version`, `feature_version`, `config_hash`, `dependency_lock_hashes` | RM-04/06 |
| Reproducibility | Same inputs/policy/config produce reproducible or deterministic-equivalent outputs (within approved tolerance) | replay run IDs, diff/hash evidence, environment refs | RM-04/06/07 |
| Approval | Named promotion decision with evidence package and residual risks/exceptions | `promotion_decision`, approver, date, exceptions/compensating controls | DEC-005 |

## Current repo observations (non-exhaustive)
- `scripts/evaluate_walk_forward.py` emits contract/versioned acceptance-policy fields and `data/walk_forward_checkpoint.json`; latest observed checkpoint is `readiness=no_go`, `gate_passed=false`.
- `scripts/backtest.py` emits daily/periods/metrics and file manifest (`artifacts/backtests/*`); `src.crispdm/backtest.py` computes returns/benchmark but does **not** implement explicit trading cost model or DEC-004 exposure-matched benchmark contract as promotion evidence.
- Run manifests are file artifacts only (no immutable DB ledger/enforcement).

## Draft gate decision rule
- **FAIL** if any required evidence category is missing, unversioned, non-immutable/unlinked, or produced under stale/superseded contract.
- **FAIL** if holdout is not demonstrably frozen/untouched for the evaluated policy/model run.
- **FAIL** if net/cost/exposure-matched benchmark evidence is absent for performance claims.
- **PASS (draft)** only when all required fields/artifacts are present and verifiable; final pass requires recorded human approvals and CI/controlled evidence.

## CI closeout gate

The `evidence-closeout` CI job runs `scripts/check_evidence_closeout.py` against
`evidence-closeout-index.json`. It proves only that the curated draft evidence
bundle is internally consistent and still marked non-promotion. It does not
evaluate holdout freeze, cost/benchmark economics, statistical validity, or
human approval; `--require-promotion-grade` is deliberately unsupported.

## Non-claims
No promotion-grade gate is implemented or passed by this draft. Existing checkpoints/backtests are **not** promoted evidence.
