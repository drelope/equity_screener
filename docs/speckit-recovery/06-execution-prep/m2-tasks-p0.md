# M2 Spec Kit Draft — P0 Foundations (Tasks)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation / M2 draft input |
| Date | 2026-11-15 |
| Status | **Draft for stakeholder review; not approved** |
| Scope | P0 tasks derived from `RM-01..RM-07` (traceable to `TSK-*`, `FR/NFR`, `RK/PE`) |

## Ordered P0 task list
| ID | Task | Source mapping | Priority | Depends on | Acceptance check | Deliverable |
|---|---|---|---|---|---|---|
| P0-TSK-001 | Finalize stakeholder review and capture dispositions/decisions | `TSK-001..003`, `DEC-001..008`, `EX-001..005` | P0 | — | Signed disposition/decision records or explicitly logged pending items with owners/dates | Review minutes + updated decision/exception logs |
| P0-TSK-002 | Approve P0 contract specs: as_of policy, manifest schema, run-keyed store model, migration/backfill strategy | `TSK-008,014`, `RM-01..05`, `FR-SIG-03`, `FR-BT-05`, `NFR-REPRO-03` | P0 | P0-TSK-001 (policy inputs) | Specs approved with field-level requirements and compatibility plan | Design spec package (M2) |
| P0-TSK-003 | Implement reproducible runtime baseline: exact pins, hashed lock, aligned CI/Docker/local installs, env identity capture | `TSK-026`, `RM-06`, `NFR-REPRO-01/02`, `RK-06` | P0 | P0-TSK-002 (lock/tooling decision) | Clean install parity in CI/container; env hash emitted for runs | Lockfile + workflow updates + env identity mechanism |
| P0-TSK-004 | Implement run manifest framework and append-only/run-keyed stores for scores, labels, checkpoints, artifacts | `TSK-022`, `RM-04`, `FR-SIG-03`, `FR-LABEL-03`, `FR-EVAL-04`, `FR-BT-05`, `RK-03/04` | P0 | P0-TSK-002,003 | Writes are run-addressable/append-only; canonical checkpoint not overwritten; manifests validate | Schema/migrations + writer/reader changes + validator |
| P0-TSK-005 | Implement append-only payload/versioned lineage expansion and provenance propagation (features/scores/predictions/runs) | `TSK-023`, `RM-05`, `NFR-AUD-01..04`, `FR-SIG-04`, `RK-07` | P0 | P0-TSK-004 | Lineage covers model inputs; no destructive rebuild for covered scope; provenance fields populated | Lineage/payload storage + propagation code |
| P0-TSK-006 | Implement PIT membership/identity intervals, delisting handling, and as-of eligibility enforcement in covered paths | `TSK-016`, `RM-01`, `FR-UNI-01..03`, `NFR-PIT-02`, `RK-01` | P0 | P0-TSK-002,004,005 | Historical reads use as-of intervals; delisting policy applied; survivor-vs-PIT delta computable | Interval model + resolver + reader/writer updates |
| P0-TSK-007 | Implement filed/as-of availability enforcement and remove wall-clock defaults in covered replay paths | `TSK-017,020`, `RM-02`, `FR-DIV-03`, `FR-FEAT-01`, `NFR-PIT-03/04`, `NFR-DET-02`, `RK-02` | P0 | P0-TSK-002,006 | `filed<=as_of` gates enforced; explicit `as_of` required; no period-end-before-filed leakage in covered outputs | Code/schema/query changes |
| P0-TSK-008 | Correct backtest formation/cleaning windows and add costs/exposure-matched benchmark/policy references to artifacts | `TSK-018`, `RM-03`, `FR-BT-02..04`, `FR-EVAL-03/04`, `RK-02/04` | P0 | P0-TSK-004,006,007; DEC-002/003/004 inputs | Formation-available eligibility only; artifacts include required economic/benchmark/policy fields | Backtest/eval logic + artifact schema updates |
| P0-TSK-009 | Add/enable blocking verification gates: coverage, CLI smoke (incl. dry-run), PIT/frozen-clock, SQL/manifest contracts | `TSK-009,010,011,013,020`, `RM-07`, `NFR-TEST-01..04`, `QG-07..10`, `RK-08` | P0 | P0-TSK-003..008 incremental | CI fails on gate violations; P0 suites pass on scoped implementation; advertised CLIs valid | Tests + CI/release gate configuration |
| P0-TSK-010 | Execute controlled pilot replay/backfill and produce M4 readiness evidence package | `TSK-028`, `RM-01..07`, `AC-P0-01..06` | P0 | P0-TSK-003..009 | Manifest-backed replay evidence, PIT delta, gate results, open exceptions/risks documented | Readiness report + artifacts + updated RTM/exception log |

## Cross-cutting requirements for every P0 task
- Link changes/specs/tests to `FR/NFR/PE/RK/RM/TSK` IDs and update RTM/docs (`TSK-014,015`, `CM-05`).
- Do not claim closure without verification evidence (tests, manifests, CI/gate output).
- Preserve existing security/audit controls (`NFR-SEC-01..03`, `NFR-GOV-02`, `PE-26/27/29`) as non-regression constraints.
- Keep exceptions explicit and time-bounded until resolved (`EX-001..005`).
