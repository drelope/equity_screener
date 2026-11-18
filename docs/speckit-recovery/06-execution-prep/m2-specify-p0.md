# M2 Spec Kit Draft — P0 Foundations (Specify)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation / M2 draft input |
| Date | 2026-11-15 |
| Status | **Draft for stakeholder review; not approved** |
| Scope | P0 remediation foundations `RM-01..RM-07` (mapped from `RK-01..04,06,07,08` and Critical PIT gaps) |
| Inputs | Stage 0–5 recovery artifacts, `decision-unknown-tracker.md`, `constitution-disposition-and-exceptions.md` |

## 1. Problem statement
The platform cannot produce trustworthy, reproducible, promotion-grade historical evidence until P0 gaps are addressed: PIT/survivorship and timing leakage (`FR-UNI-01`, `FR-DIV-03/07`, `FR-FEAT-01`, `NFR-PIT-01..05`), mutable/non-run-addressable decision evidence (`FR-SIG-03`, `FR-LABEL-03`, `FR-EVAL-04`, `FR-BT-05`, `NFR-AUD-*`, `NFR-REPRO-03/04`), non-decision-grade evaluation controls (`FR-EVAL-03`, `FR-BT-02..04`), unreproducible runtime (`NFR-REPRO-01/02`), and missing blocking verification gates (`NFR-TEST-01..04`, `FR-EVAL-05`).

## 2. Goals
| Goal | Traceability | Acceptance intent |
|---|---|---|
| G-P0-01 Enforce PIT-correct historical inputs | `RM-01, RM-02`, `FR-UNI-01..03, FR-DIV-03/07, FR-FEAT-01, NFR-PIT-01..04` | No current-state/wall-clock defaults in covered replay paths; filed/as-of eligibility enforced; survivor-vs-PIT delta measurable |
| G-P0-02 Make decision evidence immutable and run-addressable | `RM-04, RM-05`, `FR-SIG-03/04, FR-LABEL-03, FR-EVAL-04, FR-BT-05, NFR-AUD-01..04, NFR-REPRO-03/04` | Run-keyed append-only stores/manifests with code/env/input/policy identity |
| G-P0-03 Make evaluation inputs decision-grade at formation/publication | `RM-03, RM-04`, `FR-BT-02..04, FR-EVAL-03/04, FR-TR-04` | Formation-available eligibility/cleaning, costs and exposure-matched benchmark recorded, frozen policy/holdout referenced |
| G-P0-04 Make runtime reproducible | `RM-06`, `NFR-REPRO-01/02`, `ES-09` | Hashed lock and aligned CI/Docker/local installs with recorded env identity |
| G-P0-05 Block silent regressions | `RM-07`, `NFR-TEST-01..04`, `NFR-DET-02`, `TR-04..10`, `QG-07..10` | Coverage, CLI smoke, PIT/frozen-clock, SQL-contract and manifest/artifact checks enforced |

## 3. In scope (P0)
- `RM-01`: PIT membership/identity intervals, delisting handling, as-of eligibility in universe/features/labels/backtest.
- `RM-02`: SEC filed-date persistence/use, filed<=as_of gating, period-end substitution fix, explicit `as_of` in replay paths.
- `RM-03`: formation-available selection/cleaning, 14-day lookahead correction, costs and exposure-matched benchmark fields/reporting.
- `RM-04`: immutable run manifests and run-keyed append-only stores for scores/labels/checkpoints/backtests.
- `RM-05`: append-only/versioned payloads and complete lineage (beyond 5 fields), propagated feature/hash/run identity.
- `RM-06`: exact pins + hashed lock, CI/Docker/local alignment, env identity capture.
- `RM-07`: coverage threshold, CLI smoke tests (including dry-run contract), frozen-clock replay and PIT regression suite.

## 4. Out of scope (P0 draft)
- Full dividend/adjustment correctness closure beyond PIT-critical interfaces (`RM-08`, `RM-10` detailed implementation except required contracts) — tracked as P1.
- Provider legal terms resolution and external system inventories except templates/decision capture (`DEC-001`, `UNK-007`).
- ML model changes/promotion, new alpha features, or non-traceable architecture rewrites.
- Production cutover/recompute at scale; this draft specifies and plans controlled implementation/replay validation.

## 5. Functional requirements (P0 target slice)
| ID | Requirement | P0 deliverable | Verification |
|---|---|---|---|
| FR-P0-01 | As-of membership and delisting are enforced for historical reads/writes | Membership interval model + query contract; delisting truncation/return policy | PIT tests, survivor-vs-PIT comparison artifact |
| FR-P0-02 | Fundamental/dividend availability respects filing/acceptance timing | Persist/use filed dates; gate SEC-derived values; remove period-end substitution leakage | Future-row isolation and two-date replay tests |
| FR-P0-03 | Backtest selection/cleaning uses formation-available data and records economics/benchmark assumptions | Corrected windows; cost/benchmark fields and matched comparison output | Window assertions, artifact contract tests, benchmark report |
| FR-P0-04 | Scores, labels, checkpoints and backtest artifacts are immutable and run-keyed | Append-only schemas/stores and canonical checkpoint pointer strategy | No-overwrite tests, run-addressable retrieval |
| FR-P0-05 | Runs and artifacts carry complete manifests and lineage | Manifest schema, run IDs, code/env/input/policy/rule-set identity, expanded lineage | Manifest completeness validator, lineage coverage checks |
| FR-P0-06 | Reproducible runtime is installable from lock in all supported environments | Lock file, install workflow updates, env identity capture | Clean build/install parity checks in CI and container |
| FR-P0-07 | Regression gates block PIT, determinism, CLI and coverage regressions | PIT/frozen-clock suites, CLI smoke harness, SQL/manifest contract checks, coverage threshold | CI/release gate results |

## 6. Acceptance criteria
- **AC-P0-01:** Covered replay paths require explicit `as_of` and pass PIT/frozen-clock tests (`NFR-PIT-01..04`, `NFR-DET-02`).
- **AC-P0-02:** No covered historical output can be overwritten without new run identity; manifests validate required fields (`FR-SIG-03`, `FR-LABEL-03`, `FR-EVAL-04`, `FR-BT-05`, `NFR-REPRO-03`).
- **AC-P0-03:** Backtest artifacts record formation rule, costs, and exposure-matched benchmark assumptions (`FR-BT-02..04`, `FR-EVAL-03` design linkage).
- **AC-P0-04:** Locked clean installs succeed in CI and container builds; env identity recorded (`NFR-REPRO-01/02`).
- **AC-P0-05:** CI enforces coverage threshold and P0 regression suites; broken advertised CLIs are fixed or removed from contract (`NFR-TEST-01..04`, `FR-EVAL-05`).
- **AC-P0-06:** Critical requirement exceptions (`EX-001..005`) remain explicit until closure evidence exists.

## 7. Dependencies and open decisions
- Decisions: `DEC-002/003/004/008` required for full acceptance of RM-03/04/06 evidence fields.
- Unknowns: `UNK-001/002/004/005/006` inform implementation details but must not block P0 contract specification.
- Data migration/backfill strategy required for append-only/PIT schema changes (plan in `m2-plan-p0.md`).

## 8. Risks
- Historical recompute may materially change metrics (`RK-01/02/04`).
- Schema/storage growth and migration complexity (`RK-03/07`, `NFR-SCALE-02`).
- Temporary dual-read/write compatibility needed during cutover (assumption; must be specified).
