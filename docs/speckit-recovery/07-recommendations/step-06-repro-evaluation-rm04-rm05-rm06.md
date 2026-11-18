# Step 6 — Reproducibility and Decision-Grade Evaluation (RM-04/05/06) Spec (Prepared)

| Field | Value |
|---|---|
| Recommendation | Immutable run manifests, frozen holdout/policy versioning, explicit costs/benchmark, reproducible locks |
| Status | **Prepared; decisions and implementation pending** |
| Traceability | `RM-04`, `RM-05`, `RM-06`, `FR-EVAL-03`, `FR-BT-03/04/05`, `NFR-REPRO-01/02/03/04/05`, `NFR-GOV-01/02`, `RK-03`, `RK-04`, `RK-06`, `DEC-002/003/004/005/008`, `TSK-003/008/018/026` |

## 1. Current gaps
- Manifests/provenance incomplete (`FR-BT-05`/`RM-04`); mutable/replaceable evidence risks (`FR-AI-02`, `FR-REP-02`, `RM-05`).
- No decision-grade eval baseline: `FR-EVAL-03` Missing; `FR-BT-03/04` Missing/Partial; `FR-EVAL-02` Partial; policy versioning partial (`NFR-GOV-01`).
- Reproducibility limited: runtime lock (`NFR-REPRO-01` Partial), CI/container parity (`NFR-REPRO-02` Partial), environment manifests for runs partial.

## 2. Recommended solution
### 2.1 Immutable run manifests (all material runs)
Required fields (minimum): `run_id` (immutable), `run_type`, `code_sha` + dirty flag, `config_hash`, `parameter_hash`, `acceptance_policy_id/version/hash` (`DEC-003`), input data snapshot ids/hashes/manifests, `resolved_as_of`/time bounds, environment/runtime/lock ref, dependency versions, random seeds (if any), output artifact IDs/locations/hashes, status/timestamps/actor.

### 2.2 Mutable output control (`RM-05`)
- Scores/reports/AI outputs must be run-keyed and non-overwriting for decision/audit contexts; retain prior versions with compatibility metadata.
- Reports must include provenance and as-of/fetch-time (Step 7).

### 2.3 Evaluation/promotion governance
- `DEC-002`: frozen, access-controlled holdout with defined protocol and ledger.
- `DEC-003`: versioned acceptance policy; include version/hash in manifests and promotion evidence.
- `DEC-004`: explicit trading/financing/cash costs and exposure-matched benchmark; report gross and net with comparable assumptions.
- `DEC-005`: `rule_scoring_v1` remains production default unless promotion gate evidence approved.
- No "decision-grade"/promotion claim without required evidence package.

### 2.4 Reproducible runtime (`DEC-008`)
- Select and enforce lock mechanism (e.g. pinned requirements/lockfile/hash mode) consistently for local, CI, and Docker builds.
- Record lock hash/version in manifests; CI should verify reproducible install/build.

## 3. Verification plan
- Re-run from manifest reproduces identical outputs (or documented deterministic-equivalence) for fixed inputs.
- Promotion/evaluation artifacts rejected if manifest, policy version, holdout protocol, or cost/benchmark fields missing.
- RTM and `AC-P0-07/08/09/10` style checks satisfied with evidence.

## 4. Dependencies
- Human decisions `DEC-002/003/004/005/008`.
- Storage/artifact retention and access controls (Step 8 / `UNK-007`).
