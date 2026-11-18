# Existing Trading Platform Modernization — Specify Draft

| Field | Value |
|---|---|
| Stage | 5 — Spec Kit artifacts |
| Date | 2026-11-15 |
| Status | Draft (recovered, not stakeholder-approved) |
| Inputs | `docs/speckit-recovery/00-discovery/` through `04-migration/` |
| Traceability | References `FR-*`, `NFR-*`, `PE-*`, `RK-*`, `RM-*`, `PA/BI/TG/DA`, `CMP/SVC/EP/DF/CAP` IDs; no untraceable requirements introduced |

## Problem Statement
The recovered equity/dividend research platform has substantial implemented capability (84 recovered requirements: 18 Implemented, 53 Partial, 12 Missing, 1 Unknown) but is not yet decision-grade for reproducible historical research or promotion. Critical gaps remain in point-in-time integrity (`FR-UNI-01`, `FR-DIV-03/07`, `NFR-PIT-01..05`, `RK-01/02/09`), immutable decision evidence and lineage (`FR-SIG-03`, `FR-LABEL-03`, `FR-EVAL-04`, `FR-BT-05`, `NFR-AUD-*`, `NFR-REPRO-03`, `RK-03/07`), evaluation rigor (`FR-EVAL-03`, `FR-BT-03/04`, `RK-04`), runtime reproducibility (`NFR-REPRO-01..02`, `RK-06`), and verification gates (`NFR-TEST-01..04`, `RK-08`). Existing strengths (security/least privilege, audit/quarantine/freshness controls, modular layering, rule-based scoring and gated ML path) must be preserved (`NFR-SEC-01..03`, `NFR-GOV-02`, `PE-26/27/29`, `CMP-*`).

## Business Objectives
| ID | Objective | Traceability |
|---|---|---|
| BO-01 | Produce trustworthy, PIT-correct income/total-return signals and historical evaluations | `BG-01,BG-02`, `FR-UNI-01..03,FR-DIV-03/07,FR-FEAT-01,FR-TR-*`, `NFR-PIT-01..05`, `RK-01/02/05/09` |
| BO-02 | Make scores, labels, evaluations and backtests reproducible, immutable and run-addressable | `BG-04`, `FR-SIG-03/04,FR-LABEL-03,FR-EVAL-04,FR-BT-05`, `NFR-AUD-*`, `NFR-REPRO-03/04`, `RK-03/04/07` |
| BO-03 | Restore reliable, diagnosable daily operations and decision-grade promotion evidence | `BG-03,BG-05`, `FR-EVAL-01..03,FR-BT-02..04`, `NFR-REL-*`, `RK-04/11` |
| BO-04 | Institutionalize verification and governance gates before spec-driven adoption | `BG-07`, `NFR-TEST-*`, `NFR-GOV-*`, `NFR-REPRO-01..02`, `RK-06/08/12/13`, `PE-09/10` |
| BO-05 | Preserve controlled AI/reporting and security boundaries while making outputs as-of stamped and auditable | `BG-06,BG-08`, `FR-AI-01..03,FR-REP-02`, `NFR-SEC-*`, `RK-09/15` |

## Goals
- Close P0 foundations first (`RM-01..RM-07`): PIT integrity, immutable run-keyed evidence/manifests, reproducible runtime, and blocking verification gates.
- Resolve Critical requirements `FR-UNI-01`, `FR-DIV-07`, `NFR-PIT-01`, `NFR-PIT-02` or document owned, time-bounded exceptions (constitution adoption note).
- Achieve manifest-backed, replayable evaluation/backtest artifacts with costs and exposure-matched benchmarks before promotion claims (`FR-BT-03..05`, `FR-EVAL-03/04`, `RK-04`).
- Raise compliance targets post-Phase 4: CRISP-DM >=3.5, research governance >=3.5, reproducibility >=3.5, production readiness >=3.5 (Stage 4 scorecard conditions).
- Maintain existing strengths: rule-based production scoring until explicit ML promotion (`FR-SIG-01`, `FR-EVAL-02`), API/ops/explorer security controls, and audit/quarantine/freshness primitives.

## Scope
### In scope
- Recovery-driven modernization of data integrity, lineage, reproducibility, testing, evaluation, operations, documentation and governance for the existing platform (`CMP-01..20`, `SVC-01..11`, `EP-*`, `DF-*`).
- PIT membership/identity/delisting and filing/availability semantics; dividend, price-adjustment and total-return correctness; macro/report as-of stamping (`FR-UNI/ID/DIV/ADJ/CA/TR/FEAT/LABEL/MACRO/REP`).
- Append-only run-keyed stores, manifests and lineage for scores/labels/checkpoints/artifacts/runs/inputs (`FR-SIG-03/04,FR-LABEL-03,FR-EVAL-04,FR-BT-05`, `NFR-AUD-*`, `NFR-REPRO-*`).
- Environment pinning/locking, CI/Docker alignment, CLI smoke/PIT/determinism/contract/perf test gates, nightly reliability hardening (`NFR-TEST-*`, `NFR-REL-*`, `NFR-SCALE-*`).
- Governance/documentation reconciliation (RTM, constitution, provider terms, secrets inventory, migration ledger) (`NFR-GOV-*`, `NFR-SEC-03`, `CM-*`).

### Out of scope (current draft)
- New trading strategy alpha, model redesign, or automatic ML promotion beyond existing gated research path (`FR-EVAL-02`, `GP-02`).
- New external text/transcript/news/sentiment ingestion (`FR-AI-03` Missing; `BI-36` verified absence).
- Untraceable architecture rewrites (dbt/Bayesian/multi-agent/Azure) except where explicitly specified and traced; target claims must remain labeled aspirational (`PE-13`, `CM-06`).
- Legal determination of provider redistribution rights; requires external decision artifact (`NFR-GOV-03` Unknown, `RK-13`).

## Functional Requirements (traceable summary)
| Group | Requirement IDs | Required behavior (target) | Current status signal |
|---|---|---|---|
| Price/corporate actions/returns | `FR-ADJ-01..04, FR-CA-01..02, FR-TR-01..04` | Canonical adjusted series/factors, consistent split conventions, total-return decomposition, exposure-matched benchmarks and documented cash/financing assumptions | Mostly Partial; adjustment correctness uncertain (`RK-05`, `PA-*`) |
| Dividend integrity & universe | `FR-DIV-01..08, FR-UNI-01..03, FR-ID-01` | Feed-safe dividend evidence, COALESCE date preservation, runtime quarantine, PIT payer/membership eligibility, delisting treatment, resolvable identity intervals | Mixed Partial/Missing; Critical `FR-UNI-01`, `FR-DIV-07` |
| Features, labels, macro | `FR-FEAT-01..04, FR-LABEL-01..03, FR-MACRO-01..02` | Filed/as-of feature availability, version/hash/data provenance, append-only label runs, PIT/vintage macro and risk-free reads | Mostly Partial/Missing; `FR-MACRO-01` Implemented |
| Signals, evaluation, backtest, portfolio | `FR-SIG-01..04, FR-EVAL-01..05, FR-BT-01..05, FR-PORT-01..02` | Rule-score production path, immutable/versioned scores and predictions, frozen policy/holdout and run-keyed checkpoints, formation-correct backtests with costs/benchmarks/manifests, explicit constraints/risk | Mix of Implemented anchors and critical Partial/Missing evidence gaps |
| Reporting & AI | `FR-REP-01..02, FR-AI-01..03` | Deterministic as-of-stamped reports and worksheets; optional local/allow-remote drafting with no warehouse writes and bounded scope | `FR-REP-01`, `FR-AI-01` Implemented; as-of/scope gaps remain |

## Non-Functional Requirements (traceable summary)
| Group | Requirement IDs | Target contract | Current status signal |
|---|---|---|---|
| Point-in-time & determinism | `NFR-PIT-01..05`, `NFR-DET-01..04` | No future/current leakage; explicit as_of/clock injection; total ordering/tie-breaks; frozen replay tests | All Partial |
| Auditability & lineage | `NFR-AUD-01..04` | Append-only, complete input lineage; run-addressable decisions; no destructive provenance loss | 1 Partial/3 Partial (all gaps material) |
| Reproducibility & governance | `NFR-REPRO-01..04`, `NFR-GOV-01..03` | Hashed locked env, manifests, immutable artifacts/payload snapshots, versioned policy/holdout, provider terms inventory | Mostly Partial/Missing/Unknown (`NFR-GOV-03`) |
| Reliability, scale, security, testability | `NFR-REL-01..02`, `NFR-SCALE-01..02`, `NFR-SEC-01..03`, `NFR-TEST-01..04` | Resumable diagnosable runs; bounded/performance-tested queries; preserved least privilege; coverage, CLI, PIT and determinism gates | Security/scale bounds strongest; reliability/test gates incomplete |

## User Stories
| ID | Story | Primary requirements | Acceptance criteria (summary) |
|---|---|---|---|
| US-01 | As a quant researcher, I need historical universes, features, labels and dividends to reflect only information available at each as-of date so results are not survivorship/look-ahead biased. | `FR-UNI-01..03,FR-DIV-03/07,FR-FEAT-01,FR-LABEL-01`, `NFR-PIT-01..04` | PIT membership/delisting intervals applied; filed/as-of gates enforced; no today/current-state defaults in replay paths; PIT regression suite passes. |
| US-02 | As a model owner, I need every score, label, checkpoint and backtest artifact to be immutable and traceable to code, data, policy and environment so promotion decisions are defensible. | `FR-SIG-03/04,FR-LABEL-03,FR-EVAL-03/04,FR-BT-05`, `NFR-AUD-*`, `NFR-REPRO-03/04` | Run-keyed append-only stores; complete manifests; canonical checkpoint not overwritten; artifacts rejected/labeled on rule-set mismatch. |
| US-03 | As a backtest reviewer, I need formation-correct books, documented costs and exposure-matched benchmarks so performance claims are comparable and auditable. | `FR-BT-01..04`, `FR-TR-04`, `FR-PORT-01..02` | No post-formation eligibility leakage; cost/benchmark assumptions recorded; net/gross/exposure reported; matched benchmark comparison produced. |
| US-04 | As a platform engineer, I need reproducible environments and blocking CI/test gates so fixes do not regress silently. | `NFR-REPRO-01..02`, `NFR-TEST-01..04`, `FR-EVAL-05`, `NFR-REL-02` | Hashed lock aligned across CI/Docker/local; coverage/CLI/PIT/determinism/contract gates block merges/releases; dry-run and advertised CLIs pass. |
| US-05 | As an operator, I need nightly runs to be diagnosable and recoverable without corrupting prior evidence. | `NFR-REL-01..02`, `NFR-AUD-03`, `RK-11` | Stage checkpoints/resume/timeouts, root-cause capture, alerting, and contention/replay tests in place. |
| US-06 | As an analyst, I need reports and AI-assisted worksheets to be as-of stamped and bounded to approved data with no unreviewed writes. | `FR-REP-02`, `FR-AI-01..02`, `NFR-PIT-05`, `NFR-SEC-*` | Resolved as-of/fetch time stored and displayed; historical reads parameterized; AI remains optional/no-write and scope-controlled. |
| US-07 | As a governance/compliance owner, I need documentation, provider terms and inventories aligned to implemented behavior and controls. | `NFR-GOV-03`, `NFR-SEC-03`, `CM-05/06`, `PE-13/23/28/30` | Docs label implemented vs aspirational; provider terms and secret rotation inventories exist; migration ledger reconciled. |

## Acceptance Criteria (program-level)
- **AC-01 (PIT):** `NFR-PIT-01..05`, `FR-UNI-01..03`, `FR-DIV-03/07`, `FR-FEAT-01` verified by automated PIT/future-row/frozen-clock tests and survivor-vs-PIT delta reporting.
- **AC-02 (Evidence):** `FR-SIG-03/04`, `FR-LABEL-03`, `FR-EVAL-04`, `FR-BT-05`, `NFR-AUD-*`, `NFR-REPRO-03/04` verified by manifest completeness, append-only lineage, and run-addressable replay of a scoped evaluation.
- **AC-03 (Evaluation):** `FR-EVAL-03`, `FR-BT-02..04` verified by frozen policy/untouched holdout record, cost inputs, and exposure-matched benchmark in published artifacts.
- **AC-04 (Runtime/tests):** `NFR-REPRO-01..02`, `NFR-TEST-01..04` verified by locked clean builds and CI gates (coverage, CLI smoke, PIT/determinism/SQL-contract/artifact compatibility).
- **AC-05 (Operations/security):** `NFR-REL-01..02`, `NFR-SEC-01..03` verified by failure diagnostics/resume behavior and preserved/extended negative security tests.

## Risks
| ID | Severity | Risk | Traceability |
|---|---|---|---|
| RK-01 | Critical | Survivorship-biased universe / no PIT membership | `BI-01, FR-UNI-01, NFR-PIT-02` |
| RK-02 | Critical | Future/current leakage in dividends/eligibility/timing defaults | `BI-02/03, FR-DIV-03/07, NFR-PIT-01/03/04` |
| RK-03 | Critical | Mutable/overwritten decision evidence, no manifests | `DA-02/16/18, FR-SIG-03, FR-LABEL-03, FR-EVAL-04, FR-BT-05` |
| RK-04 | Critical | Non-decision-grade backtests/evaluation evidence | `BI-05/06/08/21, FR-EVAL-03, FR-BT-03/04` |
| RK-05 | High | Price/corporate-action adjustment correctness uncertain | `PA-P01/02, FA-U01/U03, FR-ADJ-*` |
| RK-06 | High | Runtime not reproducible (unpinned/no lock/drift) | `DA-17, NFR-REPRO-01/02` |
| RK-07 | High | Incomplete/destructive lineage and missing run identity | `DA-03/11/13, NFR-AUD-*` |
| RK-08 | High | Test/verification gaps allow silent defects | `TG-01/04/06/14..16, NFR-TEST-*` |

(Full register: `RK-01..RK-15` in Stage 4.)

## Assumptions
- **A-REC-01 (Verified baseline):** recovery artifacts Stage 0–4 accurately reflect repository/DB state at snapshot `2026-11-15`, HEAD `d748cea` (read-only synthesis).
- **A-REC-02 (Assumption, flagged):** P0 remediation can be implemented incrementally without requiring a full strategy redesign; historical recompute will be required and may change reported results (`RK-04/05`, RM-03/04/10).
- **A-REC-03 (Assumption, flagged):** stakeholders will provide/approve external policy decisions needed for closure: provider terms, cost model, exposure-matched benchmark, holdout ownership, and boundary decisions (`NFR-GOV-03`, `FR-BT-03/04`, `FR-EVAL-03`, `PE-25`, `RK-13`).
- **A-REC-04 (Assumption, flagged):** existing security and audit primitives are preserved as non-regression controls during modernization (`NFR-SEC-01..03`, `NFR-GOV-02`, `PE-26/27/29`).
- **A-REC-05 (Unknown carried):** raw close/dividend/split bases (`FA-U01/U03`), BI-01 magnitude, BI-37, DA-21, and external scheduler/object-store/backup state remain unresolved until targeted validation.

## Constraints
- **C-01:** Recovery and this draft introduce no source/test/config changes; implementation occurs only in subsequent traced work items.
- **C-02:** No requirement may be treated as satisfied without verification evidence (test, CI gate, manifest, or runtime check) per constitution rules.
- **C-03:** Historical replay paths must not depend on wall-clock/current-state defaults once remediated (`NFR-DET-02`, `NFR-PIT-*`).
- **C-04:** Production ranking remains rule-based until explicit ML promotion criteria and evidence are met (`FR-SIG-01`, `FR-EVAL-02`, `DC-01/02`).
- **C-05:** Security/least-privilege boundaries and no-write AI behavior are mandatory constraints (`NFR-SEC-01..03`, `FR-AI-01`).
- **C-06:** External provider licensing/redistribution constraints may limit data use/distribution until resolved (`NFR-GOV-03`).
