# Project Constitution — Ratification Draft

| Field | Value |
|---|---|
| Stage | 6 — M1 preparation |
| Prepared | 2026-11-18 |
| Status | **Prepared for external approval; no approval evidence supplied** |
| Source | `../03-constitution/constitution-draft.md`, `../03-constitution/principles-evidence.md`, `constitution-disposition-and-exceptions.md` |
| Approval rule | Effective for governed P0 implementation from 2026-11-18; named individual substitution remains an audit-hygiene follow-up |

## Preamble

This constitution preserves existing controls and defines enforced targets for the recovered equity/dividend research platform. Descriptive rules protect behavior already observed in code, tests, and CI. Aspirational rules define required target behavior; they are not treated as Descriptive until verification evidence exists.

The draft does not incorporate AI-IOS as a normative source. That document remains a non-normative future-vision reference under `../09-future-vision/`.

## 1. Guiding principles

| ID | Principle | Current status | Rule basis |
|---|---|---|---|
| PE-DET | Determinism | Partial | Explicit dates/seed exist; frozen-clock replay and total ordering missing |
| PE-AUD | Auditability | Partial | Audit plane exists; run/code/environment identity incomplete |
| PE-REPRO | Reproducibility | Partial | Python/Postgres pinned in CI/container; lock strategy not ratified |
| PE-LIN | Lineage | Partial | Feature/prediction versions exist; source lineage narrow and destructive |
| PE-TEST | Testability | Partial | Large suite and CI exist; coverage/CLI smoke/determinism gates incomplete |
| PE-TRACE | Traceability | Partial | Requirement register strong; artifacts lack run identity |
| PE-RISK | Risk controls | Partial | Gate fails closed; costs/holdout/benchmark evidence incomplete |
| PE-REL | Reliability | Partial | Lock/preflight/exit codes exist; resume and root-cause capture incomplete |
| PE-PERF | Performance | Partial | Bounds/indexes exist; representative-volume budget missing |
| PE-MOD | Modularity | Practised | Layer/component boundaries are real |
| PE-MAINT | Maintainability | Partial | Ruff/migrations/tests exist; lock and documentation drift remain |
| PE-SEP | Separation of concerns | Practised | Domain/API/UI/ops/schema layers separated |
| PE-SEC | Security | Practised | API auth, ops allowlist, read-only explorer, non-root containers |
| PE-GOV | Data governance | Partial | Quality/quarantine/freshness controls real; provider/lineage governance incomplete |

## 2. Descriptive rule groups — proposed to ratify as non-regression controls

| Group | Rule IDs | Control |
|---|---|---|
| GP | GP-02, GP-04, GP-07, GP-08 | Rule-scored production path; fail-closed stages; provenance/quarantine preservation; least privilege |
| ES | ES-01, ES-02, ES-05, ES-08, ES-10 | Lint/format; forward-only migrations; env config/no secrets; catalog-only ops; version/hash bumps |
| DG | DG-01, DG-03, DG-04, DG-10 | Dividend provenance; macro vintages; append-only quarantine; freshness/schema/quality checks |
| TR | TR-01, TR-02, TR-03 | Non-integration suite, migrated Postgres integration suite, and lint gate in CI |
| AU | AU-06, AU-07, AU-10 | Prediction/feature version identity and append-only history tables |
| RP | RP-03 | Runtime Python pin in container and CI |
| CM | CM-03, CM-07 | Forward-only migrations and version bumps for feature/model changes |
| QG | QG-01..QG-06 | Lint, tests, fresh migrated DB, dependency/secret scan, schema drift, nightly verification |
| DC | DC-01, DC-08 | Rule score remains production default; remote LLM opt-in and no warehouse writes |

A Descriptive rule may be reclassified only if its cited verification remains present in CI or runtime.

## 3. Aspirational rule groups — proposed to adopt as enforced targets

| Group | Rule IDs | Target |
|---|---|---|
| GP | GP-01, GP-03, GP-05, GP-06 | PIT precedence; reproducible promotion decisions; append-only run-addressable evidence; implemented vs aspirational docs |
| ES | ES-03, ES-04, ES-06, ES-07, ES-09 | Explicit as-of; total ordering; canonical schema; CLI smoke tests; hashed lock parity |
| DG | DG-02, DG-05, DG-06, DG-07, DG-08, DG-09, DG-11, DG-12, DG-13 | Feed-safe evidence; runtime quarantine; date preservation; filing-time gating; membership intervals; delisting handling; provider terms; identity archives; versioned payloads |
| TR | TR-04..TR-11 | Coverage, CLI smoke, PIT, determinism, boundary, SQL execution, artifact contract, and behavior tests |
| AU | AU-01..AU-05, AU-08, AU-09, AU-11 | Immutable run IDs, append-only scores/labels/evidence, complete manifests, stored as-of reports, run-addressed checkpoints |
| RP | RP-01, RP-02, RP-04..RP-10 | Hashed locks, environment parity, clean replay, code/env/input identity in manifests, immutable artifacts, retained payloads |
| CM | CM-01, CM-02, CM-04..CM-09 | Versioned policy/holdout, post-hoc invalidation, archive on destructive change, same-change docs, control-change review, non-overwritten checkpoint |
| QG | QG-07..QG-12 | Coverage threshold, PIT/determinism suites, manifest completeness, artifact compatibility, performance budget |
| DC | DC-02..DC-04, DC-05..DC-07, DC-09..DC-11 | Promotion gates, factor/provider admission, append-only preference, stale-artifact rejection, explicit as-of, identity archive, costs/benchmark, report as-of |

## 4. Governance rules

1. Descriptive and Aspirational classifications remain separate until verification evidence supports reclassification.
2. Every Critical requirement must be closed or carried as a time-bounded exception with owner, compensating control, and review date.
3. Promotion-grade claims require frozen policy, untouched holdout, cost model, exposure-matched benchmark, complete manifests, and named approval.
4. Ordinary runs must not overwrite canonical evidence or checkpoints.
5. Raw provider evidence, quarantine records, and macro vintages are append-only.
6. Historical paths require an explicit as-of; an ambiguous as-of is a defect.
7. Schema changes are forward-only and ledger-recorded.
8. Secrets are never committed; operational surfaces retain least privilege.
9. Documentation must distinguish implemented behavior from target behavior.
10. Any change to a risk control requires review, versioning, and a regression test.

## 5. Amendment process

- Amendments require a named authority, date, rationale, affected rule IDs, and migration plan.
- A rule cannot be downgraded solely because implementation is difficult.
- Rejection or deferral of a MUST rule requires an explicit compensating control and expiry.
- Approval records belong in `m1-decision-log-template.md`; this draft is not sufficient.

## 6. Recorded outcome and residual non-claims

- Prepared as a recommendation in `m1-decision-log-template.md`; no approval evidence supplied.
- M1 approval is pending; merge, release, promotion, and cutover remain blocked.
- Aspirational rules remain targets until verification evidence exists.
- EX-001..EX-005 and DEC-001..DEC-008 are dispositioned with owners/dates; their evidence remains pending.
