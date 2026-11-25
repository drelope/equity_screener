# Principles Evidence Register

| Field | Value |
|---|---|
| Stage | 3 — Constitution reconstruction |
| Scope | Fourteen engineering and governance principles checked against Stage 0–2 evidence |
| Method | Read-only code, schema, tests, artifacts and prior registers; no source, test or config changes |
| Snapshot | 2026-11-15; repository revision `d748cea` |
| Row format | `ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type` |

A principle is **Practised** when the code, tests or controls consistently demonstrate it. **Partial** means a real control exists but a material gap remains. **Absent** means no evidence was found. **Unknown** means the evidence is outside the inspected scope. This register does not treat documentation claims as evidence.

## 1. Principle Summary

| Principle | Status | What is practised | What is missing | Evidence rows |
|---|---|---|---|---|
| **Determinism** | Partial | Explicit as-of parameters, fixed random seed and sorted fold labels make replay possible. | Wall-clock defaults, latent provider order and no frozen-clock replay test. | PE-01, PE-02 |
| **Auditability** | Partial | Audit tables, nightly checks and per-prediction run versions record real evidence. | Nightly, score and backtest records lack code, environment and input identity. | PE-03, PE-04 |
| **Reproducibility** | Partial | Docker and CI pin Python 3.12 and Postgres 17.11; HEAD pins 20 direct dependencies. | The worktree is an unpinned 238-line freeze with no lock; installed packages drift. | PE-05, PE-06 |
| **Lineage** | Partial | Feature rows carry version/hash; predictions carry run, model, feature and data versions. | Scores carry no feature hash; source lineage covers five fields and is rebuilt destructively. | PE-07, PE-08 |
| **Testability** | Partial | The suite collects 1,929 tests; a targeted 16-module gap run passed 302. | No coverage threshold, most entry points untested, advertised dry-run fails. | PE-09, PE-10 |
| **Traceability** | Partial | The 84-requirement RTM and 40-row crosswalk preserve audit IDs end to end. | Artifacts lack run identity; documentation describes absent architecture. | PE-11, PE-12, PE-13 |
| **Risk controls** | Partial | The acceptance gate fails closed, folds are purged and nightly runs take an advisory lock. | No costs, unmatched benchmark and a reused holdout weaken promotion evidence. | PE-14, PE-15 |
| **Reliability** | Partial | Advisory lock, migration preflight and explicit stage exit codes are implemented. | Four recent nightly runs failed; no stage checkpoint or resume contract exists. | PE-16, PE-17 |
| **Performance** | Partial | Query bounds, indexes, autovacuum and indexed LATERAL probes are in place. | No load or capacity test; the large price and feature tables remain untested at scale. | PE-18, PE-19 |
| **Modularity** | Practised | Twenty components separate config, clients, loaders, features, scoring, portfolio, API, UI, ops and audit. | Some modules remain broad; an unused alternate silver schema is still present. | PE-20, PE-21 |
| **Maintainability** | Partial | Ruff, docstrings, 107 test modules and forward-only migrations are present. | No packaging metadata or lock; docs drift; 104 migration files versus applied version 106. | PE-22, PE-23 |
| **Separation of concerns** | Practised | Domain logic, API, UI, ops and schema occupy distinct layers. | Streamlit reads Postgres directly and portfolio modules mix selection, risk and backtest. | PE-24, PE-25 |
| **Security** | Practised | API key and rate limits, catalog allowlist, read-only explorer and non-root containers. | No secret-rotation policy or provider-terms inventory; least privilege is strong but not fully governed. | PE-26, PE-27, PE-28 |
| **Data governance** | Partial | Quality, quarantine, freshness, schema-drift and migration-ledger controls are real. | Provider licensing is Unknown, lineage is narrow and quarantine rules are one-time. | PE-29, PE-30 |

Counts: 3 Practised, 11 Partial, 0 Absent, 0 Unknown. No principle is wholly absent; the partial ratings are concentrated in evidence retention, point-in-time enforcement and runtime reproducibility.

## 2. Detailed Evidence

| ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| `PE-01` | Explicit dates, a fixed seed and sorted folds make replay possible. | as_of arguments; random_state=42; labels sorted before cutting | src/crispdm/model.py; src/crispdm/features.py; scripts/evaluate_walk_forward.py | walk_forward; label_targets; build_features | NFR-DET-01, NFR-DET-03 | Modeling | High | Keep explicit dates and seed; require callers to bind them | 0.95 | Verified |
| `PE-02` | Wall-clock defaults and latent provider order remain. | date.today defaults; Timestamp.now; no frozen-clock replay test | src/crispdm/identity.py; src/crispdm/dividend_universe.py; app/analysis_autofill.py; tests/ | resolve_security_ids; observed_payer_keys; fetch_company | NFR-DET-02, NFR-DET-04 | Data Preparation | High | Require explicit as_of and add a two-date replay test | 0.95 | Verified |
| `PE-03` | Audit tables and nightly checks record quality, quarantine, freshness and run rows. | data_quality 343,627; quarantined 2,698; freshness 72 | scripts/populate_audit.py; scripts/verify_nightly_run.py; sql/schema.sql | populate_audit; main | NFR-AUD-01, NFR-GOV-02 | Data Governance | High | Preserve and extend audit coverage to model inputs | 0.95 | Verified |
| `PE-04` | Nightly, score and backtest records lack code, environment and input identity. | nightly_runs has no SHA; artifacts have no run_id | sql/schema.sql; scripts/run_full_etl.py; scripts/backtest.py | record_nightly_run; main | NFR-AUD-03, NFR-REPRO-03 | Deployment | High | Add a run manifest with code, environment and input snapshot | 0.95 | Verified |
| `PE-05` | Docker and CI pin Python 3.12 and Postgres 17.11; HEAD pins 20 direct dependencies. | python:3.12-slim; postgres:17.11; 20 pins at HEAD | Dockerfile; .github/workflows/ci.yml; docker-compose.yml; requirements.txt | — | NFR-REPRO-01, NFR-REPRO-02 | Deployment | High | Make the HEAD pin set enforceable and adopt a lock | 0.95 | Verified |
| `PE-06` | The worktree replaces pins with an unpinned freeze and has no lock. | 0 double-equals in worktree; pytest 9.1.1 vs 8.4.2 | requirements.txt; requirements-dev.txt | — | NFR-REPRO-01, NFR-REPRO-02 | Deployment | High | Restore exact pins and add a hashed lock | 1.00 | Verified |
| `PE-07` | Feature rows carry version/hash; predictions carry run and data versions. | 9,756,631 features stamped features_v5; 216 prediction run ids | src/crispdm/features.py; sql/migrations/V0095_feature_model_versioning.sql; model.predictions | build_features; predictions | FR-FEAT-02, FR-SIG-04, NFR-AUD-01 | Data Preparation | Medium | Extend the same provenance to scores and labels | 0.95 | Verified |
| `PE-08` | Source lineage is narrow and destructive; scores carry no feature hash. | 26,297 rows for five fields; delete then reinsert | scripts/populate_audit.py; model.scores; model.features | populate_audit; score | NFR-AUD-01, FR-SIG-03 | Data Governance | High | Make lineage append-only over all model inputs | 0.95 | Verified |
| `PE-09` | The suite is large and a targeted gap-area run passed. | 1,929 collected; 302 passed in 16 modules | tests/; requirements-dev.txt; .github/workflows/ci.yml | — | NFR-TEST-02 | Evaluation | Medium | Keep the gate and add contract tests | 0.98 | Verified |
| `PE-10` | There is no coverage threshold, most entry points are untested and the dry-run fails. | 11 of 107 call main; dry-run raises TypeError | tests/; scripts/dry_run_walk_forward.py; .github/workflows/ci.yml | main | NFR-TEST-01, NFR-TEST-04, FR-EVAL-05 | Evaluation | High | Add a coverage gate and a main() smoke test per CLI | 0.98 | Verified |
| `PE-11` | The requirement register and RTM preserve audit IDs and map every requirement. | 84 requirements; 40-row audit crosswalk | docs/speckit-recovery/02-requirements/requirements.md; rtm.md | — | NFR-AUD-01 | Data Governance | Medium | Keep IDs stable across later stages | 0.98 | Verified |
| `PE-12` | Backtest artifacts and nightly rows cannot be tied to code or data. | Seven metrics files; no run_id or SHA | artifacts/backtests/; audit.nightly_runs | — | FR-BT-05, NFR-REPRO-03 | Evaluation | High | Give every artifact an immutable run identity and manifest | 0.98 | Verified |
| `PE-13` | Documentation describes dbt, Bayesian and multi-agent designs that are absent. | README target design vs Python-only implementation | README.md; TECHNICAL_SPEC.md; docs/UiWorkflowArchitecture.md | — | NFR-REPRO-02 | Business Understanding | Medium | Label implemented and aspirational architecture separately | 0.90 | Verified |
| `PE-14` | The gate fails closed, folds are purged and nightly runs serialize with an advisory lock. | all_folds_passed; PIPELINE_LOCK_KEY; exit code 2 | src/crispdm/model.py; scripts/run_full_etl.py | evaluate_gate; main | FR-EVAL-01, FR-EVAL-02, NFR-REL-02 | Evaluation | High | Keep the controls and add contention/replay tests | 0.95 | Verified |
| `PE-15` | No costs, unmatched benchmark and a reused holdout weaken promotion evidence. | 150/50 book vs 100% net benchmark; no cost inputs | src/crispdm/backtest.py; docs/data-health-workstreams.md | run_walk_forward; evaluate_gate | FR-BT-03, FR-BT-04, FR-EVAL-03 | Evaluation | High | Add costs, an exposure-matched benchmark and a fresh holdout | 0.90 | Verified |
| `PE-16` | Nightly runs use an advisory lock, migration preflight and fail-closed stages. | PipelineAlreadyRunning; migration check; explicit exit codes | scripts/run_full_etl.py; scripts/migrate.py | main; run_module | NFR-REL-02 | Deployment | High | Document the lock and exit contract; test contention | 0.95 | Verified |
| `PE-17` | Recent nightly runs failed and there is no stage checkpoint or resume contract. | Four failed runs; no resume checkpoint | audit.nightly_runs; scripts/run_full_etl.py | main; run_module | NFR-REL-01, NFR-REL-02 | Deployment | High | Add stage checkpoints, resume semantics and alerting | 0.90 | Verified |
| `PE-18` | Query bounds, indexes, autovacuum and indexed LATERAL probes are in place. | MAX_ROWS 5,000; features_pkey probes; autovacuum settings | src/crispdm/explorer.py; src/crispdm/feature_window.py; sql/schema.sql | run_query; feature_window | NFR-SCALE-01 | Deployment | Low | Preserve the bounds and add a load test | 0.90 | Verified |
| `PE-19` | There is no load or capacity test for the large price and feature tables. | No load test; 9.8M prices and 9.76M features | tests/; src/crispdm/features.py; raw.market_data | build_features | NFR-SCALE-02 | Evaluation | Medium | Set a performance budget and test representative volumes | 0.90 | Verified |
| `PE-20` | Twenty components separate config, clients, loaders, features, scoring, portfolio, API, UI, ops and audit. | CMP-01..CMP-20; src/app/api/scripts/sql layers | docs/speckit-recovery/00-discovery/component-catalog.md; src/ | — | NFR-REPRO-02 | Business Understanding | Low | Keep component boundaries and document interfaces | 0.90 | Inferred |
| `PE-21` | Some modules remain broad and an unused alternate silver schema is present. | portfolio and backtest are broad; silver_schema unused | src/crispdm/portfolio.py; src/crispdm/backtest.py; sql/silver_schema.sql | select_portfolio; run_walk_forward | NFR-REPRO-02 | Modeling | Medium | Split by responsibility and archive the alternate schema | 0.85 | Inferred |
| `PE-22` | Ruff, docstrings, 107 test modules and forward-only migrations are present. | ruff check; forward-only migrations; 107 test modules | ruff.toml; .github/workflows/ci.yml; sql/migrations/; tests/ | — | NFR-REPRO-02, NFR-TEST-02 | Deployment | Medium | Keep the lint and test gates | 0.95 | Verified |
| `PE-23` | There is no packaging metadata or lock; docs drift and migration numbering is inconsistent. | No pyproject; 104 files vs applied version 106 | repo root; requirements.txt; sql/migrations/ | — | NFR-REPRO-01, NFR-TEST-04 | Deployment | High | Add packaging and a lock; reconcile the migration ledger | 0.95 | Verified |
| `PE-24` | Domain logic, API, UI, ops and schema occupy distinct layers. | src vs api vs app vs ops vs sql | src/crispdm/; api/; app/; ops/; sql/ | — | NFR-SEC-02, NFR-REPRO-02 | Business Understanding | Low | Keep UI reads behind API or client boundaries | 0.85 | Inferred |
| `PE-25` | Streamlit reads Postgres directly and portfolio mixes selection, risk and backtest concerns. | app views query the warehouse; portfolio.py is broad | app/views/; src/crispdm/portfolio.py | load_warehouse; risk_metrics; select_portfolio | NFR-SCALE-02, NFR-SEC-02 | Deployment | Medium | Document direct-read exceptions and split domain services | 0.85 | Inferred |
| `PE-26` | Public API data routes require an API key and a rate limit. | require_api_key; _SlidingWindowLimiter | api/main.py; tests/test_api.py | require_api_key; _SlidingWindowLimiter | NFR-SEC-01 | Deployment | Medium | Keep auth tests and add key rotation | 0.95 | Verified |
| `PE-27` | Ops is catalog-allowlisted, the explorer is read-only and containers run non-root. | CATALOG; READ ONLY; cap_drop ALL | src/crispdm/ops/catalog.py; src/crispdm/explorer.py; Dockerfile; docker-compose.yml | get_task; run_query | NFR-SEC-02, NFR-SEC-03 | Deployment | High | Preserve least privilege and add negative tests | 0.95 | Verified |
| `PE-28` | Secrets are gitignored and gitleaks runs, but there is no rotation policy. | .gitignore; gitleaks action; no rotation document | .gitignore; .github/workflows/ci.yml; docs/ | — | NFR-SEC-03 | Deployment | Medium | Add a secret inventory and rotation policy | 0.90 | Verified |
| `PE-29` | Quality, quarantine, freshness, schema drift and the migration ledger are real controls. | 343,627 quality rows; 2,698 quarantine; 72 freshness | scripts/populate_audit.py; scripts/check_schema_drift.py; scripts/verify_nightly_run.py | populate_audit; main | NFR-GOV-02 | Data Governance | Low | Keep and extend coverage to research inputs | 0.97 | Verified |
| `PE-30` | Provider terms are Unknown, lineage is narrow and quarantine rules are one-time. | No license inventory; five lineage fields; V0104 only | docs/; audit.source_lineage; sql/migrations/V0104 | populate_audit | NFR-GOV-03, NFR-AUD-01, FR-DIV-05 | Data Governance | High | Add terms inventory, append-only lineage and runtime quarantine rules | 0.90 | Verified |

## 3. Principle-by-Principle Reading

### Determinism

The code can be replay-deterministic: every audited clock site accepts an explicit date, the model fixes `random_state=42`, and walk-forward labels are sorted before cutting. It is not enforced. The default in identity, dividend-universe, label and calendar paths is the wall clock, and no test replays a fixed input on two dates. Provider ordering is latent in joins and duplicate handling. (`PE-01`, `PE-02`, `DA-01`, `DA-08`, `DA-19`.)

### Auditability

The audit plane is real: `audit.data_quality`, `audit.quarantined_values`, `audit.source_freshness`, `audit.nightly_runs`, `audit.model_runs` and nightly verification all exist. The gap is identity. A nightly row records stage status but not code, image, arguments or an error excerpt. A score row has no run id. A backtest artifact has no run id or code SHA. (`PE-03`, `PE-04`, `DA-02`, `DA-09`, `DA-11`.)

### Reproducibility

Container and CI definitions pin Python and Postgres, and HEAD pins 20 direct dependencies. The worktree replaces those pins with a 238-line freeze, has no lock file, and the installed pytest and streamlit versions already differ from the pins. The image installs the mutable worktree file. (`PE-05`, `PE-06`, `DA-17`, `TS-F02`, `TS-F03`.)

### Lineage

Feature rows carry `feature_version` and `feature_set_hash`; predictions carry `run_id`, model, feature and data versions plus a config hash and training run id. Those are genuine controls. Scores carry none of them, labels have no run identity, and `audit.source_lineage` covers five decision fields and is deleted and rebuilt on each run. (`PE-07`, `PE-08`, `DA-12`, `DA-13`.)

### Testability

The suite is broad: 107 modules, 1,929 collected tests, 1,602 non-integration, and a targeted 16-module gap run passed 302 tests. The suite is not contract-complete: only 11 modules call a CLI `main()`, the advertised dry-run raises `TypeError`, there is no coverage tool or threshold, and many SQL paths are asserted as strings rather than executed. (`PE-09`, `PE-10`, `TG-01`, `TG-14`, `TG-15`, `TG-16`.)

### Traceability

The Stage 2 register maps 84 requirements to audit IDs, files, functions, tests, phases and risks, with a 40-row crosswalk. That is the strongest traceability artifact in the repository. The implementation trails it: backtest artifacts and nightly rows cannot be tied to code or data, and the README describes an architecture the code does not contain. (`PE-11`, `PE-12`, `PE-13`.)

### Risk controls

The evaluation gate requires all eligible folds, fails closed on skipped folds, and purges labels before cutting. The nightly pipeline takes an advisory lock and exits 2 on contention. These are real controls. They do not cover costs, the benchmark is 100 percent net against a 150/50 book, and the acceptance policy has been revised on the same folds it judges. (`PE-14`, `PE-15`, `BI-05`, `BI-08`.)

### Reliability

The nightly pipeline has migration preflight, explicit stage exit codes, an advisory lock and a verification script. It lacks a stage checkpoint, a resume contract and a per-stage timeout. Four recent nightly runs failed, and the audit row records no root cause. (`PE-16`, `PE-17`, `DA-11`.)

### Performance

The explorer caps results at 5,000 rows and runs in a read-only transaction; the feature window deliberately uses indexed LATERAL probes instead of a 42-million-buffer-hit DISTINCT ON; the schema uses aggressive autovacuum on large tables. There is no load test, no query budget and no capacity documentation. (`PE-18`, `PE-19`, `NFR-SCALE-01..02`.)

### Modularity

Twenty components separate configuration, clients, loaders, features, scoring, portfolio, API, UI, ops, audit and the worksheet. The boundaries are readable and mostly stable. Some modules remain broad, and `sql/silver_schema.sql` is an unused alternate schema. (`PE-20`, `PE-21`, `CMP-F14`.)

### Maintainability

Ruff, docstrings, 107 test modules and forward-only migrations are present. There is no `pyproject.toml`, no lock file and no Makefile; documentation drifts from implementation; 104 migration files coexist with an applied ledger at version 106. (`PE-22`, `PE-23`, `CMP-F13`.)

### Separation of concerns

Domain logic lives in `src/crispdm`, serving in `api/`, UI in `app/`, operations in `ops/`, and schema in `sql/`. The separation is real but not pure: Streamlit views read Postgres directly, and `portfolio.py` mixes selection, risk, attribution and backtest helpers. (`PE-24`, `PE-25`.)

### Security

Data routes require `X-API-Key` and a sliding-window limit; the ops plane is catalog-allowlisted; the explorer is read-only and capped; containers drop capabilities and run non-root; secrets are gitignored and gitleaks runs. The missing piece is governance: no secret inventory or rotation policy, and provider licensing is Unknown. (`PE-26`, `PE-27`, `PE-28`, `NFR-SEC-01..03`.)

### Data governance

Technical governance is strong: quality, quarantine, freshness, schema drift and a migration ledger are implemented, and quarantined values are append-only. It is incomplete as a governance system: provider terms are not inventoried, source lineage is five fields and destructive, and the quarantine rule is written only by a one-time migration. (`PE-29`, `PE-30`, `NFR-GOV-02..03`.)

## 4. Search Coverage

- Re-read all Stage 0 discovery files, all four Stage 1 audit summaries and registers, and all six Stage 2 files.
- Re-opened source for clock inputs, mutable stores, lineage writers, score/checkpoint writers, API/auth, ops catalog, explorer, containers and CI.
- Probed schema and live row counts only where the prior register already established the query; no writes and no pipeline runs in Stage 3.
- Searched for `TODO`, `FIXME`, `CURRENT_DATE`, `date.today`, `Timestamp.now`, `random_state`, `run_id`, `feature_set_hash`, `delisted_date`, `adjusted_close`, `coverage`, `lock`, and `secret` across source, tests, SQL and docs.
- Two consecutive passes after the first read found no new principle or control class; the register was closed at 30 evidence rows.

## 5. Limits

- Principle status is a judgment over observed controls, not a certification. A Practised rating does not mean every edge case is covered.
- No new execution was performed in Stage 3; runtime claims rest on Stage 1C executions and Stage 1D probes.
- The evidence register is intentionally narrower than the 84-requirement register; the constitution cites the requirements, not every finding.
- External scheduler state, object-store archives and provider audit logs remain outside the inspected scope.
