# Entry Points

| Field | Value |
|---|---|
| Stage | 0 — Discovery |
| Scope | CLIs, APIs, jobs, schedulers, UI workflows (EP-) |
| Method | Read `scripts/`, `api/main.py`, `app/`, `ops/`, `airflow/`, `docker-compose.yml` |
| Legend | V = Verified, I = Inferred, A = Assumption, U = Unknown |
| Row format | ID \| Finding \| Evidence \| File path \| Function/Class \| Requirement ID \| CRISP-DM phase \| Risk \| Recommended action \| Confidence \| Type |

## 1. UI Workflows (Streamlit)

| ID | Entry point | Evidence | Notes | Conf/Type |
|---|---|---|---|---|
| EP-01 | Screener (default page) | `app/views/screener.py` | 16 financial metrics, filters, CSV, three Plotly charts; uses `feature_window.dashboard_features_sql` | 0.95 V |
| EP-02 | Security detail | `app/views/security.py` | Profile, score history, features, financials, FMP, dividends, recommendation, issuer | 0.90 V |
| EP-03 | Investment analysis worksheet | `app/views/investment_analysis.py` | 18 steps; deterministic autofill; optional LLM draft; Draft/Final validation; Markdown/JSON export; revisions | 0.95 V |
| EP-04 | Analyst dashboard + Reports Center | `app/views/dashboard.py` | 7 tabs; 5 deterministic report types; CSV/Markdown downloads | 0.95 V |
| EP-05 | Data explorer | `app/views/data_explorer.py`; `src/crispdm/explorer.py` | Allowlisted, read-only, max 5,000 rows | 0.90 V |
| EP-06 | Health / Operations / Integrations | `app/views/{health,operations,integrations}.py` | Ops controls require `OPS_ADMIN_TOKEN`; read-only otherwise | 0.85 V |

## 2. API Endpoints (FastAPI)

| ID | Entry point | Evidence | Notes | Conf/Type |
|---|---|---|---|---|
| EP-07 | Core SEC-backed API | `api/main.py` | `GET /health` public; `/companies/`, `/companies/{ticker}`, `/filings/{ticker}`, `/facts/{ticker}`, `/financials/{ticker}` | 0.98 V |
| EP-08 | OpenBB-backed API | `api/main.py` | `/openbb/ratios|valuation|profile|analysts|fundamentals|statements|dcf|filings/{ticker}`, `/openbb/macro/inputs` | 0.98 V |
| EP-09 | Enriched metrics API | `api/main.py` | `GET /metrics/enriched/{ticker}` | 0.98 V |
| EP-16 | API docs | `api/main.py` | OpenAPI/docs disabled unless `API_ENABLE_DOCS` | 0.95 V |

- All routes except `/health` require `X-API-Key`. Rate limit defaults to 120 requests/minute. API returns 503 if unconfigured. `[V 0.95]`

## 3. Batch / CLI Entry Points

| ID | Entry point | Command / evidence | Notes | Conf/Type |
|---|---|---|---|---|
| EP-10 | Full ETL | `python -m scripts.run_full_etl` | Stages 0–9 + optional stage 10; `--trigger systemd/airflow`; `--limit`, `--tickers`, `--skip-*` | 0.95 V |
| EP-11 | Scoring/ranking | `python -m scripts.score_rank` | Writes `model.scores/predictions/rankings`; `--as-of`; regime weights gated | 0.95 V |
| EP-12 | Portfolio backtest | `python -m scripts.backtest` | Writes `artifacts/backtests/*` | 0.95 V |
| EP-13 | Research/evaluation CLIs | `build_features`, `build_forward_returns`, `label_targets`, `event_study`, `liquidity_floor_study`, `evaluate_walk_forward`, `dry_run_walk_forward` | Batch research/validation | 0.95 V |
| EP-14 | Ops worker | Compose `worker` service; `python -m scripts.ops_worker` | Queue/schedule/cancel via allowlist | 0.85 V |
| EP-18 | Quality gate | `python -m scripts.crispdm_validate` | `migrate --check`, ruff check/format, skill audit, pytest | 0.95 V |
| EP-19 | Agent/skill runner | `python -m scripts.agent_runner --skill …` | `--list`, `--tools-for`, `--verify`, `--dry-run`, `--prune-artifacts`; artifacts in `artifacts/runs/` | 0.95 V |
| EP-20 | Nightly verification | `python -m scripts.verify_nightly_run` | Exit 1 = attention needed | 0.95 V |
| EP-21 | Schema bootstrap / migrate | `python -m scripts.init_db`; `python -m scripts.migrate` | CI and Compose use both | 0.98 V |
| EP-22 | Bulk EDGAR load | `python -m scripts.load_sec_bulk` | Weekly bulk refresh before stage 4a | 0.95 V |

- 56 root `scripts/*.py` files contain `if __name__ == "__main__"`; most are invoked as `python -m scripts.<name>` from repo root. `[V 1.0]`
- `scripts/run_etl.py` executes at module import (no `main()`/guard). `[V 1.0]`
- No Makefile and no `pyproject.toml` console scripts. `[V 1.0]`

## 4. Jobs, Schedulers, and Services

| ID | Entry point | Evidence | Notes | Conf/Type |
|---|---|---|---|---|
| EP-15 | systemd timer | `ops/systemd/dividend-etl.timer` | 03:00 America/New_York daily, `Persistent=true` | 0.98 V |
| EP-17 | Compose stack | `docker-compose.yml` | `postgres`, `migrate`, `streamlit`, `api`, `worker` | 0.95 V |
| EP-23 | Airflow DAG (optional) | `airflow/dags/dividend_etl_dag.py` | 03:00 America/New_York, 2 retries, no catchup | 0.95 V |
| EP-24 | Ops schedules | `src/crispdm/ops/schedule.py`; `ops/store.py` | `once`/`interval`/`daily`; worker enqueues due tasks | 0.98 V |

## 5. Findings Register

| ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| EP-F01 | No consolidated CLI reference; entry points are spread across 56 scripts plus API/UI/schedulers | 56 `__main__` scripts | `scripts/` | — | TBD | Deployment | Med | Generate CLI reference from argparse | 1.0 | Verified |
| EP-F02 | `scripts/run_etl.py` executes on import, which is unsafe for tooling/import | no `main()` or `__main__` guard | `scripts/run_etl.py` | module top-level | TBD | Deployment | Med | Add guard and `main()` | 1.0 | Verified |
| EP-F03 | ETL stage list is implicit in `run_full_etl.py` docstring and code, not data-driven | stage docstring + `run_module` calls | `scripts/run_full_etl.py` | `run_module` | TBD | Data Preparation | Med | Externalize stage manifest | 0.98 | Verified |
| EP-F04 | `--skip-*` flags allow partial ETL; no dependency check between skipped and required stages | argparse flags | `scripts/run_full_etl.py` | `main` | TBD | Data Preparation | High | Add stage dependency validation | 0.95 | Verified |
| EP-F05 | API docs disabled by default; consumers must read code or OpenAPI when enabled | `API_ENABLE_DOCS` gate | `api/main.py` | app setup | TBD | Deployment | Low | Document enabling docs in non-prod | 0.95 | Verified |
| EP-F06 | Streamlit is the only human UI; no desktop or mobile client | `app/streamlit_app.py` | `app/streamlit_app.py` | `PAGES` | TBD | Deployment | Low | Accept; document browser requirement | 0.95 | Verified |
| EP-F07 | Ops tasks are constrained to a fixed catalog, limiting remote execution surface | `TaskDef` allowlist | `src/crispdm/ops/catalog.py` | `CATALOG` | TBD | Deployment | High | Keep allowlist tests and review process | 0.98 | Verified |
| EP-F08 | Agent runner supports dry-run/verify but is not an autonomous agent loop | CLI flags; fixed scripts | `scripts/agent_runner.py` | `main` | TBD | Deployment | Low | Keep deterministic; document skill authoring | 0.95 | Verified |
| EP-F09 | Worksheet Draft/Final validation is the only formal analyst sign-off workflow | Draft/Final validation; revisions | `app/views/investment_analysis.py`; `analysis.*` | — | TBD | Business Understanding | Med | Define acceptance criteria for Final | 0.95 | Verified |
| EP-F10 | Health/Operations read-only mode is available without operator token | `controls_enabled()` gating | `app/ui.py`; `app/views/operations.py` | `operator_panel` | TBD | Deployment | Low | Document read-only vs operator capabilities | 0.90 | Verified |
