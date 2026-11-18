# Repository Map

| Field | Value |
|---|---|
| Stage | 0 — Discovery |
| Scope | Directory structure and file-role map |
| Method | `ls`/glob and read of key files; HEAD `d748cea` |
| Legend | V = Verified, I = Inferred, A = Assumption, U = Unknown |
| Row format | ID \| Finding \| Evidence \| File path \| Function/Class \| Requirement ID \| CRISP-DM phase \| Risk \| Recommended action \| Confidence \| Type |

## 1. Top-Level Tree

```text
dividend_equity_crispdm/
├── README.md                     # System overview, setup, pipeline, UI/API docs
├── TECHNICAL_SPEC.md             # Target technical design (partly aspirational)
├── CRISP_DM_Workflow.md          # CRISP-DM objectives, data, modeling, evaluation
├── SYSTEM.md                     # Agent/skill workflow contract
├── CONTRIBUTING.md               # Branch model, gates, PR checklist
├── Dockerfile                    # Python 3.12-slim image, non-root UID 10001
├── docker-compose.yml            # postgres/migrate/streamlit/api/worker
├── requirements.txt              # Runtime deps (pinned at HEAD; unpinned in worktree)
├── requirements-dev.txt          # pytest/ruff/pip-audit pins
├── ruff.toml                     # Lint/format config
├── .env.example                  # Environment contract sample
├── .github/
│   ├── workflows/ci.yml          # lint/test/security jobs
│   └── dependabot.yml            # Weekly pip/actions/docker updates
├── airflow/dags/
│   └── dividend_etl_dag.py       # Optional nightly DAG
├── api/
│   └── main.py                   # FastAPI app, routes, auth, rate limiting
├── app/
│   ├── streamlit_app.py          # Streamlit entry, page registry
│   ├── nav.py, ui.py             # Navigation and shared UI/operator auth
│   ├── analysis_schema.py        # 18-section worksheet schema
│   ├── analysis_autofill.py      # Deterministic autofill
│   ├── llm_client.py             # Optional local LLM draft client
│   └── views/                    # screener, security, dashboard, explorer, ops...
├── artifacts/                    # Runtime outputs (SEC bulk, backtests, agent runs)
├── data/                         # Local data incl. backups, checkpoints
├── docs/                         # Design, runbooks, audits, ADRs
│   └── speckit-recovery/         # This recovery documentation set
├── ops/systemd/                  # Nightly ETL service/timer/install/wait scripts
├── skills/                       # 22 SKILL.md contracts + _template
├── sql/
│   ├── schema.sql                # Canonical DDL (9 schemas)
│   ├── silver_schema.sql         # Unused alternate star schema
│   └── migrations/V0001..V0106   # 104 forward-only migration files
├── src/
│   ├── crispdm/                  # Core domain/application package
│   ├── agent/                    # Skill loader, schemas, tool registry/executor
│   └── math_engine.py            # Deterministic portfolio math
├── scripts/                      # 56 CLI stage/loader/verification entrypoints
└── tests/                        # 107 pytest modules (~1,929 tests)
```

## 2. Directory Roles

| Path | Role | Representative files | Conf/Type |
|---|---|---|---|
| `src/crispdm/` | Domain/application logic: clients, features, scoring, model, portfolio, backtest, regime, analytics, ops | `sec_client.py`, `openbb_client.py`, `features.py`, `scoring.py`, `model.py`, `portfolio.py`, `backtest.py`, `returns.py`, `ops/` | 0.98 V |
| `src/agent/` | Agent framework: skill loading/validation, tool registry, executor, CLI | `core/loader.py`, `schemas/skill.py`, `tools/{base,registry,library,executor}.py`, `cli/main.py` | 0.97 V |
| `src/math_engine.py` | Deterministic portfolio math | `RiskParityCalculator` | 0.98 V |
| `scripts/` | ~56 CLI entrypoints: ETL stages, loaders, scoring, backtest, migrations, verification, ops worker, agent runner | `run_full_etl.py`, `populate_*.py`, `load_*.py`, `score_rank.py`, `verify_nightly_run.py` | 0.98 V |
| `api/` | FastAPI read API | `main.py` | 0.98 V |
| `app/` | Streamlit analyst UI and worksheet | `streamlit_app.py`, `views/*.py`, `analysis_*.py`, `llm_client.py` | 0.98 V |
| `sql/` | Canonical schema and forward-only migrations | `schema.sql`, `migrations/V*.sql` | 0.98 V |
| `tests/` | Pytest suite with DB-gated integration tests | `conftest.py`, `test_*.py` | 0.98 V |
| `docs/` | Runbooks, data acquisition, verification, architecture, audits | `deployment-runbook.md`, `nightly-verification.md`, `data-acquisition.md`, `adr/` | 0.95 V |
| `ops/systemd/` | Host scheduling and DB readiness | `dividend-etl.service`, `.timer`, `install.sh`, `wait_for_db.py` | 0.98 V |
| `airflow/dags/` | Optional scheduler | `dividend_etl_dag.py` | 0.97 V |
| `skills/` | Operational/analytical skill contracts | `skills/*/SKILL.md` | 0.97 V |
| `artifacts/` | Runtime outputs | `sec_bulk/`, `runs/`, `backtests/`, `event_study/` | 0.90 V |
| `data/` | Local data and checkpoints | `backups/backup_20261028.dump`, `walk_forward_checkpoint.json` | 0.90 V |
| `azure/` | Azure pilot mapping doc only | `README.md` | 0.90 V |

## 3. Key Module Map

| Module | Purpose | Conf/Type |
|---|---|---|
| `src/crispdm/config.py` | `Settings` from env/.env; DB URL, provider keys, LLM flags | 0.98 V |
| `src/crispdm/db.py` | SQLAlchemy engine, `execute`, `read_df`, retry helpers | 0.99 V |
| `src/crispdm/http_retry.py` | `Throttle`, `request_with_backoff` with jitter | 0.98 V |
| `src/crispdm/sec_client.py` | SEC API/archives, caching, concept classification | 0.98 V |
| `src/crispdm/openbb_client.py` | OpenBB/yfinance/FMP/Polygon access and reconciliation | 0.98 V |
| `src/crispdm/fundamentals.py` | XBRL → periodic financials | 0.98 V |
| `src/crispdm/features.py` / `feature_set.py` / `feature_window.py` | Point-in-time features and dashboard SQL | 0.95 V |
| `src/crispdm/scoring.py` | Rule-based composite scoring/ranking | 0.98 V |
| `src/crispdm/model.py` / `validation.py` | ML classifier and walk-forward validation | 0.95 V |
| `src/crispdm/portfolio.py` / `backtest.py` / `baselines.py` | Portfolio construction, backtest, baselines | 0.95 V |
| `src/crispdm/returns.py` | Forward total returns | 0.95 V |
| `src/crispdm/dividend_universe.py` / `dividend_limits.py` | Dividend classification and sanity limits | 0.95 V |
| `src/crispdm/regime.py` / `regime_pipeline.py` | Regime/CVS diagnostic layer | 0.95 V |
| `src/crispdm/analogs.py` / `event_study.py` | Peer base rates, event studies | 0.95 V |
| `src/crispdm/explorer.py` | Allowlisted read-only query builder | 0.93 V |
| `src/crispdm/ops/*` | Catalog, queue, schedules, auth, worker logic | 0.98 V |
| `src/crispdm/analysis/store.py` | Worksheet persistence/revisions | 0.95 V |
| `app/streamlit_app.py` | 8-page UI registry | 0.98 V |
| `api/main.py` | FastAPI app and routes | 0.98 V |

## 4. Findings Register

| ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| RM-F01 | Repo is a modular monolith with clear layer directories | `src/`, `scripts/`, `api/`, `app/`, `sql/` | — | — | TBD | Business Understanding | Low | Use as basis for spec boundaries | 0.98 | Verified |
| RM-F02 | `scripts/` is very large (56 executables) and mixes production stages with maintenance/one-offs | legacy scripts not in nightly stage list | `scripts/` | — | TBD | Data Preparation | Med | Classify production vs maintenance; document | 1.0 | Verified |
| RM-F03 | Docs directory mixes current runbooks with aspirational architecture | `UiWorkflowArchitecture.md` vs implemented code | `docs/` | — | TBD | Business Understanding | Med | Tag docs current/target | 0.90 | Verified |
| RM-F04 | Recovery artifacts are isolated under `docs/speckit-recovery/` and untracked | `git status` shows untracked dir | `docs/speckit-recovery/` | — | TBD | Deployment | Low | Decide whether to commit recovery set | 1.0 | Verified |
| RM-F05 | `sql/silver_schema.sql` is non-canonical and unused | no runtime references | `sql/silver_schema.sql` | — | TBD | Data Preparation | Low | Archive/remove | 0.90 | Inferred |
| RM-F06 | `artifacts/` and `data/` contain local runtime state that affects reproducibility | SEC bulk, backups, checkpoints | `artifacts/`; `data/` | — | NFR reproducibility | Deployment | Med | Document required artifacts; add manifests | 0.90 | Verified |
| RM-F07 | 22 skills + `_template` under `skills/` (23 directories) | `ls -d skills/*/ \| wc -l` → 23 | `skills/` | — | TBD | Deployment | Low | Keep template separate in counts | 1.0 | Verified |
| RM-F08 | 104 migration files but max applied version 106 and 105 ledger rows | `schema_migrations` | `sql/migrations/` | — | TBD | Data Preparation | Med | Reconcile numbering and document gaps | 1.0 | Verified |
