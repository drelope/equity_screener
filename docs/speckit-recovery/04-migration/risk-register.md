# Stage 4 Risk Register

| Field | Value |
|---|---|
| Stage | 4 — Synthesis and migration |
| Date | 2026-11-15 |
| Method | Merged and de-duplicated findings from Stage 0–3 (`PA/BI/TG/DA`, `FR/NFR`, `PE`, constitution rules); read-only synthesis, no source changes |
| Basis | 84 requirements (18 Implemented, 53 Partial, 12 Missing, 1 Unknown), 30 PE rows, 95 constitution rules, prior audit registers |

Risks are merged themes (not 1:1 audit findings). Severity reflects likelihood × impact on research validity, reproducibility, governance, and safe adoption.

| ID | Risk | Likelihood | Impact | Severity | Owner role | Mitigation | Evidence refs |
|---|---|---|---|---|---|---|---|
| RK-01 | Survivorship-biased universe: current-state active/dividend/security_type used for historical membership; no PIT membership table | High | High | Critical | Data/Quant Lead | Build PIT membership (valid_from/valid_to) from dividend/listing/delisting evidence; require as-of eligibility in features/labels/backtest; report survivor-vs-PIT delta | BI-01,FR-UNI-01,NFR-PIT-02,PE-02,DG-08 |
| RK-02 | Dividend payer universe and total-return eligibility can leak future/current knowledge (today defaults, 14-day post-formation cleaning, SEC period-end/filing gaps) | High | High | Critical | Quant/Data Engineering | Remove today defaults; gate SEC dividends/features on filed<=as_of; restrict eligibility/cleaning to formation-available data; add PIT tests | BI-02,BI-03,FR-DIV-03,FR-DIV-07,NFR-PIT-01,NFR-PIT-03..04,PE-02,PE-14 |
| RK-03 | Decision evidence is mutable/overwritten: scores upserted, labels rebuilt destructively, canonical checkpoint overwritten, no artifact/run manifests | High | High | Critical | ML Platform/Engineering | Adopt append-only run-keyed stores for scores/labels/checkpoints/artifacts; add immutable run manifests with code/data/env/policy identity | BI-04,DA-02,DA-16,DA-18,FR-SIG-03,FR-LABEL-03,FR-EVAL-04,FR-BT-05,PE-04,PE-08,PE-12 |
| RK-04 | Backtest/evaluation evidence not reproducible or decision-grade: no costs, unmatched benchmark, reused holdout, demoted/changed policy, stale rule-set artifacts served | High | High | Critical | Quant Research Lead | Freeze acceptance policy and untouched holdout; add costs and exposure-matched benchmark; require artifact manifest/rule-set compatibility checks | BI-05,BI-06,BI-08,BI-21,FR-BT-03,FR-BT-04,FR-EVAL-03,PE-15,DC-02,DC-10 |
| RK-05 | Price/corporate-action adjustment correctness uncertain: adjusted_close 100% NULL, split handling/tolerance gaps, dividend basis ambiguity, raw closes basis unknown | Medium | High | High | Data Engineering/Quant | Verify raw close basis and provider split/dividend bases; implement/validate canonical adjustment layer; add boundary/golden tests for splits/dividends/returns | PA-P01,PA-P02,PA-F05,FA-U01,FA-U03,FR-ADJ-01..04,FR-DIV-08,FR-TR-01..03,TG-08..10 |
| RK-06 | Environment and runtime not reproducible: worktree unpinned freeze (0 ==), no lock, installed drift, image installs mutable deps | High | High | High | Platform/DevOps | Restore exact pins, add hashed lock, install same lock in CI/Docker/local; record dependency/image identity in run manifests | DA-17,PE-06,NFR-REPRO-01..02,ES-09,RP-01..02 |
| RK-07 | Insufficient run/input lineage: raw SEC latest-only, destructive 5-field lineage, scores lack feature hash, nightly/backtest lack code/env/input identity | High | High | High | Data/ML Platform | Append-only raw payload snapshots; extend lineage to all model inputs; propagate feature/run identity to scores and artifacts; stamp nightly runs | DA-03,DA-11,DA-13,PE-07,PE-08,NFR-AUD-01..03,AU-01..05 |
| RK-08 | Test and verification gaps allow silent defects: no coverage gate, 96 CLIs un-smoke-tested, broken dry-run, PIT/determinism SQL-contract gaps, source-text assertions | High | High | High | QA/Engineering | Add coverage threshold, CLI smoke and artifact-contract tests, frozen-clock/PIT/boundary tests, execute SQL constants against migrated schema | TG-01,TG-04,TG-06,TG-14..16,NFR-TEST-01..04,TR-04..11,QG-07..10 |
| RK-09 | Macro and report timing can be non-PIT: risk-free uses latest revision not ALFRED as-of; reports/autofill/calendar views rely on current date/latest rows without stamped as-of | Medium | High | High | Data/App Engineering | Route risk-free and macro reads through as-of vintage readers; require/stamp resolved as-of on reports/worksheets/autofill; parameterize date-sensitive queries/views | BI-14,BI-34,BI-35,DA-04,DA-20,FR-MACRO-02,FR-REP-02,FR-AI-02,NFR-PIT-05,AU-09 |
| RK-10 | Dividend data integrity defects: PK omits feed, NULL date overwrite on upsert, silent absurd-row drops/one-time quarantine, SEC amount/timing/merge limitations | High | Medium | High | Data Engineering | Redesign dividend key/evidence storage, COALESCE date preservation, runtime quarantine rules, preserve filing/retrieval metadata, validate amount bases | DA-05,DA-06,DA-21,FR-DIV-01,FR-DIV-04,FR-DIV-05,PA-D03..08,PA-D12..17,DG-02,DG-05..07 |
| RK-11 | Operational reliability risk: 4 recent nightly failures, no resume/stage checkpoints/timeouts, audit rows lack root cause | Medium | High | High | SRE/Ops | Add stage checkpoints/resume semantics and timeouts; capture error excerpts/root cause; add alerting and contention/replay tests | DA-11,PE-17,NFR-REL-01..02,CM-03 |
| RK-12 | Documentation/traceability drift: README/tech docs claim absent architecture; artifacts lack identity; migration ledger/files inconsistent | Medium | Medium | Medium | Tech Lead/Docs | Label implemented vs aspirational architecture; reconcile migration ledger; require doc/RTM updates with behavior changes and manifest-backed artifacts | PE-13,PE-23,FR-BT-05,ES-06,CM-05..06 |
| RK-13 | Provider/data governance unknowns: no provider terms/licensing inventory, external scheduler/object-store/backup state unverified | Medium | Medium | Medium | Product/Data Governance | Create provider terms inventory and distribution decision; document external orchestration/storage/backup dependencies and retention | NFR-GOV-03,PE-30,DG-11,DC-04,OQ-05 |
| RK-14 | Performance and scale unvalidated: large tables (9.8M prices, 9.76M features) with no load/capacity budget or tests | Low | Medium | Low | Platform/Engineering | Define representative performance budgets; add load/capacity tests and monitor query/resource behavior | NFR-SCALE-02,PE-18,PE-19,QG-12 |
| RK-15 | Security governance incomplete despite strong controls: no secret rotation/inventory policy; Streamlit direct DB reads blur boundary | Low | Medium | Low | Security/Platform | Add secret inventory/rotation policy and boundary decision; keep negative tests for auth/allowlist/read-only controls | NFR-SEC-02..03,PE-25,PE-28,CM-05 |

## Cross-cutting critical path
- **PIT integrity first (RK-01, RK-02, RK-09, RK-10):** without as-of correctness, downstream evaluation/replay evidence is untrustworthy.
- **Append-only decision evidence second (RK-03, RK-04, RK-07):** promotion claims require immutable, addressable scores/labels/checkpoints/artifacts/manifests.
- **Runtime reproducibility and test gates third (RK-05, RK-06, RK-08):** fixes must be pinned, verified and regression-protected before spec-driven adoption.

## De-duplication notes
- `BI-01/FR-UNI-01/NFR-PIT-02/PE-02` consolidated into RK-01.
- `DA-02/DA-16/DA-18/FR-SIG-03/FR-LABEL-03/FR-EVAL-04/FR-BT-05` consolidated into RK-03.
- `BI-05/BI-06/BI-08/BI-21/FR-EVAL-03/FR-BT-03..04` consolidated into RK-04.
- `DA-17/NFR-REPRO-01..02/TS-F02..03` consolidated into RK-06; test/determinism gaps consolidated into RK-08.
