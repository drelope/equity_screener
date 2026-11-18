# Technology Stack

| Field | Value |
|---|---|
| Stage | 0 — Discovery |
| Scope | Languages, frameworks, datastores, infrastructure, tooling |
| Method | Read `Dockerfile`, `docker-compose.yml`, `requirements*.txt`, `ruff.toml`, `.github/workflows/ci.yml`, source imports |
| Legend | V = Verified, I = Inferred, A = Assumption, U = Unknown |
| Row format | ID \| Finding \| Evidence \| File path \| Function/Class \| Requirement ID \| CRISP-DM phase \| Risk \| Recommended action \| Confidence \| Type |

## 1. Stack Summary

| Layer | Technology | Version | Evidence | Conf/Type |
|---|---|---|---|---|
| Language | Python | 3.12 in Docker/CI; 3.11.0rc1 local; README claims 3.10-3.14 | `Dockerfile`; `.github/workflows/ci.yml`; `.venv` | 1.0 V |
| Database | PostgreSQL | `17.11` digest-pinned | `docker-compose.yml` | 0.99 V |
| DB access | SQLAlchemy + psycopg | 2.0.54 / 3.3.6 | `src/crispdm/db.py` | 0.98 V |
| Config | pydantic-settings + python-dotenv | 2.15.0 / 1.2.3 | `src/crispdm/config.py` | 0.98 V |
| Data processing | pandas + numpy | 2.3.3 / 2.2.6 | Repo-wide | 0.99 V |
| Market/provider SDK | OpenBB + yfinance | 4.7.2 / 1.7.0 | `src/crispdm/openbb_client.py` | 0.97 V |
| ML | scikit-learn + joblib | 1.7.2 / 1.6.0 | `src/crispdm/model.py` | 0.97 V |
| HTTP | requests | 2.34.2 | `sec_client.py`, `http_retry.py`, `llm_client.py` | 0.98 V |
| Parsing | beautifulsoup4 / lxml / defusedxml | 4.15.0 / 6.1.3 / 0.7.1 | SEC parsing | 0.95 V |
| UI | Streamlit | 1.64.0 (HEAD) | `app/streamlit_app.py` | 0.99 V |
| Charts | Plotly | 7.1.0 | `app/views/*` | 0.97 V |
| API | FastAPI + uvicorn | 0.136.3 / 0.40.0 | `api/main.py`; `Dockerfile` | 0.99 V |
| Templating | Jinja2 | 3.1.6 | HEAD requirements | 0.90 V |
| Migration | Custom forward-only SQL + Python runner | max applied 106 | `sql/migrations/`; `scripts/migrate.py` | 0.98 V |
| Orchestration | Python stage runner | — | `scripts/run_full_etl.py` | 0.98 V |
| Scheduling | systemd timer (primary) / Airflow (optional) / DB schedules | — | `ops/systemd/`; `airflow/`; `src/crispdm/ops/` | 0.98 V |
| Container | Docker + Docker Compose | Python 3.12 slim; 5 services | `Dockerfile`; `docker-compose.yml` | 0.99 V |
| CI | GitHub Actions | 3 jobs | `.github/workflows/ci.yml` | 0.98 V |
| Lint | ruff | 0.15.22 | `ruff.toml`; `requirements-dev.txt` | 0.99 V |
| Test | pytest | 8.4.2 pinned; 9.1.1 local | `requirements-dev.txt`; `.venv` | 1.0 V |
| Security | pip-audit + gitleaks | 2.10.1 / action v2 | `.github/workflows/ci.yml` | 0.98 V |
| Agent tooling | opencode + Ollama | — | `opencode.json`; `Modelfile` | 0.90 V |
| Cloud | Azure (mapping only) | — | `azure/README.md` | 0.90 I |

## 2. Key Technology Decisions (observed)

| Decision | Observation | Evidence | Conf/Type |
|---|---|---|---|
| Postgres as single system of record | No alternate DB/warehouse | `src/crispdm/db.py`; storage search | 0.95 V |
| Batch ELT, not streaming | No broker/event bus; sequential stages | `scripts/run_full_etl.py` | 0.90 V |
| Rule-based production scoring | Percentile blends; ML gated | `src/crispdm/scoring.py`; `model.py` | 0.98 V |
| Deterministic reports | Reports Center states no LLM used | `app/views/dashboard.py` | 0.95 V |
| Local-first compute | Host ETL + local Postgres + loopback ports | `docker-compose.yml`; `ops/systemd/` | 0.98 V |
| Allowlist-based ops execution | Fixed catalog, no shell strings | `src/crispdm/ops/catalog.py` | 0.98 V |
| Optional local LLM | OpenAI-compatible endpoint, disabled by default | `app/llm_client.py`; `config.py` | 0.97 V |
| Forward-only migrations | No rollback migrations | `scripts/migrate.py` | 0.98 V |

## 3. Not Present

- dbt, Airflow runtime dependency, Prefect, APScheduler, cron installer. `[V 0.95]`
- Kafka/RabbitMQ/Redis/celery or any event bus. `[V 0.85]`
- Parquet/DuckDB/SQLite/S3/Azure Blob/GCS/Snowflake/BigQuery/Redshift storage. `[V 0.85]`
- Broker/order execution, email/Slack/webhook alerts. `[V 0.85]`
- `pyproject.toml`, lockfile, Makefile, pre-commit config. `[V 1.0]`
- PDF generation and automated report distribution. `[V 0.85]`

## 4. Findings Register

| ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| TS-F01 | Python version is inconsistent across README, Docker/CI, and local venv | 3.10-3.14 claim vs 3.12 vs 3.11.0rc1 | `README.md`; `Dockerfile`; `.venv` | — | NFR reproducibility | Deployment | High | Pin one version and enforce it | 1.0 | Verified |
| TS-F02 | Direct dependencies are pinned at HEAD but the worktree is unpinned | 0 `==` in working tree; 20 at HEAD | `requirements.txt` | — | NFR reproducibility | Deployment | Critical | Resolve uncommitted change; add lockfile | 1.0 | Verified |
| TS-F03 | No packaging metadata or lockfile | repo-wide search | — | — | NFR reproducibility | Deployment | High | Adopt `pyproject.toml` + lock | 1.0 | Verified |
| TS-F04 | OpenBB provider surface is large and version-sensitive | `openbb==4.7.2` + 30 provider packages | `requirements.txt` | — | NFR reliability | Deployment | High | Pin provider set; stage upgrades | 0.95 | Verified |
| TS-F05 | Local tooling drift (pytest, streamlit, pip-audit) | `.venv/bin/pip list` vs pins | `requirements-dev.txt` | — | NFR reproducibility | Deployment | Med | Rebuild venv; make CI authoritative | 1.0 | Verified |
| TS-F06 | CI and Docker use different Postgres pinning styles (tag vs digest) | `postgres:17.11` vs digest | `.github/workflows/ci.yml`; `docker-compose.yml` | — | NFR reproducibility | Deployment | Med | Use digest in both | 1.0 | Verified |
| TS-F07 | Azure is documentation-only despite appearing in tech discussions | mapping doc; no IaC/SDK | `azure/README.md` | — | NFR maintainability | Deployment | Low | Mark Azure as deferred | 0.90 | Verified |
| TS-F08 | No coverage tooling or threshold in CI | bare `pytest -q`; no pytest-cov | `.github/workflows/ci.yml`; `requirements-dev.txt` | — | NFR testability | Evaluation | High | Add coverage reporting and gate | 1.0 | Verified |
| TS-F09 | pandas/numpy pinned; downstream inputs can still drift via provider APIs | provider calls unpinned by contract | `src/crispdm/openbb_client.py` | — | NFR determinism | Deployment | High | Snapshot raw payloads for reproducibility | 0.90 | Inferred |
