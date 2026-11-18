# M2 Spec Kit Draft — P0 Foundations (Plan)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation / M2 draft input |
| Date | 2026-11-15 |
| Status | **Draft for stakeholder review; not approved** |
| Scope | `RM-01..RM-07` implementation planning for M3 foundation + M4 validation entry |

## 1. Architecture and design changes (planned)
| Area | Current gap | Planned change | Traceability |
|---|---|---|---|
| Membership/identity | Current-state flags, no PIT intervals | Add membership/identity interval model and as-of resolver; delisting handling policy | `RM-01`, `FR-UNI-01..03`, `NFR-PIT-02` |
| Availability semantics | Period-end/filing leakage, wall-clock defaults | Filed-date persistence, `filed<=as_of` gates, explicit `as_of` parameters/clock injection | `RM-02`, `FR-DIV-03`, `FR-FEAT-01`, `NFR-PIT-03/04`, `NFR-DET-02` |
| Backtest/evaluation | 14-day leakage, no costs/matched benchmark, policy drift risk | Formation-available windows, cost/benchmark manifest fields, frozen policy/holdout references | `RM-03`, `FR-BT-02..04`, `FR-EVAL-03/04` |
| Evidence stores | Mutable scores/labels/checkpoints/artifacts | Run-keyed append-only tables/paths, manifest schema, canonical pointer (not overwrite) | `RM-04`, `FR-SIG-03`, `FR-LABEL-03`, `FR-BT-05`, `NFR-REPRO-03/04` |
| Lineage/payloads | Latest-only/destructive/narrow lineage | Versioned payload snapshots, append-only lineage covering model inputs, propagated provenance IDs | `RM-05`, `NFR-AUD-01..04`, `FR-SIG-04` |
| Runtime | Unpinned/no lock/drift | Hashed lock, aligned install path in CI/Docker/local, env identity capture | `RM-06`, `NFR-REPRO-01/02`, `ES-09` |
| Verification | Missing blocking gates | Coverage, CLI smoke, PIT/frozen-clock, SQL/manifest contract gates | `RM-07`, `NFR-TEST-01..04`, `QG-07..10` |

## 2. Work packages and sequencing
| WP | Description | Depends on | Outputs | Milestone |
|---|---|---|---|---|
| WP-01 Contracts/specs | Finalize P0 schemas/contracts: as_of rules, manifest schema, run-keyed store design, migration/backfill approach | DEC-002/003/004/008 draft | Approved design specs, migration plan, test matrix | M2 |
| WP-02 Reproducible runtime | Implement lock/pins and CI/Docker/local alignment; capture env identity | WP-01 | Locked builds/install parity, CI update | M3 |
| WP-03 Evidence foundation | Implement manifest + run-keyed append-only stores/paths and lineage expansion | WP-01, WP-02 | Manifest validator, append-only storage, provenance propagation | M3 |
| WP-04 PIT data semantics | Implement membership/identity intervals, delisting, filed/as_of gating, explicit as_of controls | WP-01, WP-03 (where identity/run links needed) | PIT-correct readers/writers for covered paths | M3/M4 |
| WP-05 Backtest/eval integrity | Correct formation windows, add costs/benchmark/holdout/policy references in artifacts | WP-03, WP-04 | Decision-grade artifact records | M4 |
| WP-06 Verification gates | Implement PIT/determinism/CLI/coverage/contract tests and CI enforcement | WP-02..05 incremental | Blocking CI/release gates, regression suites | M3/M4 |
| WP-07 Replay & readiness | Controlled replay/backfill, evidence collection, exception/risk updates | WP-03..06 | Manifest-backed replay evidence, readiness review pack | M4 |

## 3. Data migration and compatibility plan (draft)
| Step | Action | Risk control |
|---|---|---|
| MIG-01 | Additive schema migrations for manifests, run IDs, interval tables, versioned payload/lineage structures | Forward-only migrations, preflight checks, rollback-by-compensation plan (no destructive rollback assumed) |
| MIG-02 | Dual-write/backfill where needed (legacy + run-keyed) with compatibility readers | Feature flags/config toggles; parity checks; no deletion of legacy evidence until validated |
| MIG-03 | Backfill/recompute scoped historical outputs with manifests (pilot slice first) | Record run/input snapshots; compare deltas (esp. survivor-vs-PIT); document expected changes |
| MIG-04 | Cutover consumers to run-keyed/manifest-validated sources | Compatibility window, consumer contract tests, reject unlabeled legacy artifacts for promotion use |

## 4. Verification plan
| Gate | Checks | Traceability |
|---|---|---|
| GATE-ENV | Hashed lock, clean install parity CI/Docker/local, env identity emitted | `NFR-REPRO-01/02`, `RM-06` |
| GATE-PIT | Explicit as_of, future-row isolation, filed<=as_of, membership/delisting correctness | `NFR-PIT-01..04`, `FR-UNI-01..03`, `FR-DIV-03`, `RM-01/02` |
| GATE-DET | Frozen-clock replay equality, deterministic ordering/tie-breaks | `NFR-DET-01..04`, `RM-02/07` |
| GATE-EVID | Manifest completeness, append-only/run-keyed retrieval, no overwrite, lineage coverage | `NFR-AUD-*`, `NFR-REPRO-03/04`, `RM-04/05` |
| GATE-EVAL | Formation-available windows, costs, exposure-matched benchmark, policy/holdout refs present | `FR-BT-02..04`, `FR-EVAL-03/04`, `RM-03/04` |
| GATE-CI | Coverage threshold, CLI smoke, SQL/contract tests, artifact compatibility checks | `NFR-TEST-01..04`, `RM-07` |

## 5. Dependencies, assumptions, and resource needs
- **Dependencies:** stakeholder decisions `DEC-001..005,008`; validation outputs `UNK-001/002/004/005/006`.
- **Assumptions (flagged):** additive migrations feasible in current Postgres environment; pilot recompute acceptable; dual-read/write period manageable.
- **Resources (proposed):** Data Engineering, Quant Research, ML Platform, Platform/DevOps, QA, App/UI, Governance/Legal support.

## 6. Milestone alignment
- **M2:** WP-01 complete, decisions/exceptions reviewed, P0 specs/tasks approved.
- **M3:** WP-02/03 and initial WP-06 gates operational in controlled environment.
- **M4:** WP-04/05/07 complete for P0 scope with evidence; blocking conditions cleared or explicitly excepted.
