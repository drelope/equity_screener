# SDLC Review — Dividend Equity Screener

Review date: 2026-09-23
Scope: key SDLC roles and responsibilities, assessed against the **current
(as-is)** state of the repository.
Basis of review: repository contents at
`dividend_equity_crispdm_implementation/dividend_equity_crispdm` (README,
`src/`, `scripts/`, `tests/`, `sql/`, `api/`, `app/`, `Dockerfile`,
`docker-compose.yml`, `azure/`).

## 1. Purpose and scope

This document reviews the Software Development Life Cycle (SDLC) of the
Dividend Equity Screener and defines the key SDLC roles and responsibilities
that apply to it today. It is written for the current reality of the project:
a **local-first MVP** delivered by a **single owner** who currently wears every
SDLC hat. The review therefore assesses each phase as-is, names the roles that
phase activates, states whether the role is covered today (by the single
owner), and highlights what is missing or at risk before the project moves to
Azure (see `azure/README.md` — "Move to Azure only after the local MVP is
reproducible and walk-forward evaluation is passing").

Reference methodology: the project explicitly follows CRISP-DM
(`README.md:1-3`), so the SDLC phases below are aligned to the standard
waterfall-style phases that map cleanly onto CRISP-DM's
Business Understanding → Data Understanding → Data Preparation → Modeling →
Evaluation → Deployment stage order.

## 2. Current-state snapshot

| Dimension | Observed state | Evidence |
|---|---|---|
| Product type | Dividend-equity data pipeline + screening/ranking + web UI | `README.md:1-33` |
| Methodology | CRISP-DM (business → data → model → evaluate → deploy) | `README.md:1-3` |
| Stack | Python, PostgreSQL (Dockerized, v17.11), SEC EDGAR/XBRL, OpenBB, scikit-learn, Streamlit, FastAPI | `README.md:13-20` |
| Deployment | Local Docker Compose: `postgres`, `migrate`, `streamlit`, `api` | `docker-compose.yml` |
| CI/CD | **None** (no `.github/`, no lint/pre-commit config, no package manifest) | repo listing |
| Version control | **None** (no `.git` at repo, parent, or `/mnt` level) | `git log`/`git status` fail |
| Tests | 12 pytest modules (mock-based unit tests); `.pytest_cache` shows no last-failed | `tests/` |
| Cloud readiness | Azure pilot *mapped*, explicitly deferred | `azure/README.md:12` |
| Operations | Nightly ETL aspiration; staged orchestration via `scripts.run_full_etl`; Airflow *optional* | `README.md:24`, `scripts/run_full_etl.py` |

## 3. Phase-by-phase assessment (as-is)

### 3.1 Requirements / Business Understanding

**Responsibility:** convert the business problem ("which equities pay income,
sustainably, with strong legal/economic rights") into measurable screening
rules, weights, and acceptance criteria.

**Current state:**

- Business framing is well captured by the CRISP-DM descriptions and the
  scoring weights surfaced in the Streamlit caption: Income 25% | Sustainability
  20% | Legal/Economic Rights 25% | Appreciation 15% | Risk 10% | Valuation 5%
  (`app/streamlit_app.py:7`).
- The dividend-universe definition is explicit and enforced: `dividend = TRUE`
  in `reference.securities`, backed by a partial index that gates every
  downstream ETL stage (`README.md:404-407`).
- **Gap:** there is no formal requirements artifact (PRD / user stories /
  acceptance criteria). `README.md` is the de-facto spec. Weights live in code
  and UI captions only. No documented record of *who decided* the weights or
  *how they are validated* against a backtest/benchmark.

### 3.2 Architecture / Design / Data Understanding & Preparation

**Responsibility:** design the schema, data flow, and transformation mapping so
that raw SEC/OpenBB payloads become auditable, normalized facts.

**Current state — strong:**

- Eight-schema PostgreSQL model (`raw`, `reference`, `fundamentals`,
  `dividends`, `preferred`, `market`, `model`, `audit`) documented with
  column-level comments (`sql/schema.sql`, `README.md:343-488`).
- Single-source-of-truth XBRL tag registry (`src/crispdm/xbrl_tags.py`) that
  keeps schema comments, extractors, classifiers, and taxonomy loaders in sync
  (`README.md:437-475`).
- Explicit data-flow diagram and end-to-end pipeline
  (`SEC + OpenBB → raw → features → rules+ML → walk-forward → rankings →
  Streamlit`, `README.md:490-529`).
- Field-level provenance design (`audit.source_lineage`), quality scores
  (`audit.data_quality`), and model-run metadata (`audit.model_runs`).

**Gap:** no architecture decision records (ADRs); design rationale is
concentrated in `README.md` prose and schema comments. Staging this as separate
design documents would reduce knowledge-isolation risk for the single owner.

### 3.3 Development

**Responsibility:** implement the pipeline stages, library code, API, and UI.

**Current state:**

- Modular library (`src/crispdm/`) + one script per pipeline stage
  (`scripts/populate_*.py`), orchestrated by `scripts/run_full_etl` (stages
  0-6, dependency-ordered, runnable as Python modules).
- Consistent house style across modules; `ruff` has been run ad hoc (a
  `.ruff_cache` exists) but **no lint configuration is checked in** and no
  formatting/linting gate exists.
- **Gaps:** no version control (no `.git` anywhere in the tree), no
  `pyproject.toml`/`setup.cfg`, and `requirements.txt` pins no versions
  (`README.md` and `.env.example` drive configuration instead). Unpinned
  dependencies and the absence of VCS make the MVP non-reproducible — the
  explicit precondition for Azure is "local MVP is reproducible"
  (`azure/README.md:12`).

### 3.4 Testing / QA / Model Evaluation

**Responsibility:** verify ingestion, normalization, classification,
scoring, and API behavior; evaluate model quality.

**Current state:**

- 12 pytest modules covering: scoring weights and composite score
  (`test_scoring.py`), SEC security-type/dividend classification auditability,
  companyfacts ingestion, dividend-data population, preferred-profile
  population, doc-clause parsing, instrument titles, security-type vocabulary,
  fundamentals + predictions, archive index, and API
  (`tests/`, `tests/test_api.py`).
- Tests are mock-based unit tests suited to a local-first single-owner repo.
- `MIN_RECALL=0.30` exists in `.env.example` as a measurable acceptance
  threshold (`src/crispdm/config.py:8`).
- **Gaps:** no CI to run `pytest`/`ruff` automatically; no integration/e2e
  harness (ETL is verified manually against the live Dockerized Postgres); no
  evidence checkpoint that walk-forward evaluation is **passing** — which the
  Azure pilot explicitly requires before migration.

### 3.5 Deployment / Release

**Responsibility:** package and run the app; release safely.

**Current state:**

- `Dockerfile` (python:3.12-slim, uvicorn default) and `docker-compose.yml`
  with four services: `postgres` (17.11, `pg_stat_statements` enabled,
  health-checked), `migrate`, `streamlit` (8501), `api` (8000, requires
  `API_KEY` via env).
- API authentication: `/health` public; every other route requires
  `X-API-Key`; missing config returns 503 (`api/main.py:18-34`).
- **Gaps:** no release/rollback procedure, no image tag pinning (compose notes
  a `@sha256:` digest as a recommended improvement), no staging environment,
  no CI/CD pipeline. Deployments today are manual `docker compose up` runs on
  the developer machine.

### 3.6 Maintenance / Operations

**Responsibility:** keep the nightly pipeline running, apply schema changes
safely, and keep data provenance auditable.

**Current state:**

- Structured migration setup: Flyway-style `sql/migrations/V0002-V0004` plus
  `init_db`'s compatibility migrations and a `scripts.migrate` compose step
  (`scripts/init_db.py`, `docker-compose.yml:33-41`).
- Staged ETL with skip flags and limits for testing/partial runs
  (`scripts/run_full_etl.py`).
- Auditability designed in (`audit.*` schemas, content hashes, provider tags,
  timestamps in every raw table).
- SEC compliance honored via `SEC_USER_AGENT` (`src/crispdm/config.py:5`).
- **Gaps:** a nightly schedule is *aspirational* — Airflow is "optional" and no
  scheduler/runtime (Cron, Airflow DAG, Azure Functions job) is defined or
  deployed. No monitoring/alerting (Azure Application Insights is only mapped,
  not implemented). Secrets are managed in `.env`/`.env.example`, not a vault.

## 4. Key SDLC roles and responsibilities (as-is)

Today **one person fills every role**. Coverage is labeled:

- ✓ **Filled today** — the single owner actively performs the role's duties
  (with quality noted per role).
- ◐ **Partial** — function exists but is incomplete, unenforced, or guarded by
  manual steps.
- ✗ **Gap** — the role's responsibilities are not meaningfully discharged.

| Role | Primary responsibilities | Phase(s) | Coverage |
|---|---|---|---|
| **Product Owner / Business Analyst** | Own screening objectives, the weighting scheme (Income 25 / Sustainability 20 / Legal-Rights 25 / Appreciation 15 / Risk 10 / Valuation 5), the dividend-universe definition, and priority order of stages | Requirements | ◐ Weighted rules and universe defined; no formal PRD or acceptance criteria recorded |
| **Data Scientist / ML Engineer** | Feature engineering, rule+ML composite scoring (`src/crispdm/scoring.py`, `WEIGHTS` sum to 1), walk-forward evaluation, offline target labeling for future dividend outcomes | Requirements, Design, Testing | ◐ Scoring implemented and unit-tested; **walk-forward not shown passing**; labels deliberately not fabricated — target population is open work (`README.md:666`) |
| **Data Engineer** | SEC EDGAR/XBRL + OpenBB ingestion, normalization against the XBRL tag registry, `raw→reference` classification, per-CIK de-duplication, audit lineage | Design, Development, Ops | ✓ Strong: staged scripts, CIK-keyed payloads, dividend gating, `raw_payload` retention |
| **DBA / Data Modeler** | 8-schema data model, `reference.securities` hub, indexes (`ix_securities_dividend_active`), Flyway-style migrations + `init_db` compat, Compose-hosted Postgres with `pg_stat_statements` | Design, Deployment, Ops | ✓ Strong: schema documented with per-column `COMMENT`, migration discipline present |
| **Backend / API Developer** | FastAPI service, `X-API-Key` auth, query serialization, expected `404`/error-code behavior for missing SEC datasets | Development, Deployment | ✓ Filled; API-key handling and ticker validation present |
| **Frontend / Analytics Developer** | Streamlit dashboard over `model.features`/`model.scores`, Plotly visualizations, screening sliders/type filters | Development, Ops | ✓ Filled (thin view over the ranked model) |
| **QA / Test Engineer** | Mock-based pytest suites, ETL verification against live Postgres, `MIN_RECALL` acceptance hygiene | Testing | ◐ 12 suites exist but are run manually; no CI gate, no integration harness |
| **DevOps / SRE / Release Engineer** | Docker Compose services, container health/heartbeat, image reproducibility, CI/CD, Azure migration (Container Apps, Azure DB for Postgres, Blob, Functions jobs, Key Vault, App Insights) | Deployment, Ops | ◐ Compose is functional; **no VCS, no CI, no rollback, cloud deferred** |
| **Security / Compliance** | API-key auth, SEC User-Agent policy, secrets management, auditability (`audit.*`) | Requirements, Deployment, Ops | ◐ Auth + lineage sound; secrets live in `.env`; SEC rate-limit/UA policy not codified as enforced checks |
| **Release / Change Management** | Version control, code review, changelog, tagged releases, rollback | Development, Deployment | ✗ No `.git`, no review process, no releases |
| **Project Manager / Coordinator** | Backlog, sprint/phase tracking, Go/No-Go decision for Azure gate ("walk-forward passing") | All | ✗ Absent; tasks driven ad hoc |
| **Technical Writer** | README (666 lines, thorough), Azure mapping, schema comments | All | ✓ README/documentation is a strength of the project |

## 5. Phase × role coverage matrix

Legend: ✓ covered today · ◐ partial · ✗ gap · — not applicable.

| Phase | PO/BA | DS/ML | Data Eng | DBA/Model | Backend | Frontend | QA | DevOps/SRE | Security | Change Mgmt | PM |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Requirements | ◐ | ◐ | — | — | — | — | — | — | ◐ | ✗ | ✗ |
| Design | ◐ | ◐ | ✓ | ✓ | ✓ | ✓ | — | ◐ | ◐ | ✗ | ✗ |
| Development | — | ✓ | ✓ | ✓ | ✓ | ✓ | ◐ | ◐ | ◐ | ✗ | ✗ |
| Testing | — | ◐ | ◐ | ◐ | ◐ | — | ◐ | ✗ | — | ✗ | ✗ |
| Deployment | — | — | — | ◐ | ◐ | — | — | ◐ | ◐ | ✗ | ✗ |
| Ops/Maintenance | — | ◐ | ✓ | ✓ | — | ✓ | — | ◐ | ◐ | ✗ | ✗ |

Reading: the **library/data disciplines (Data Engineering, DBA, Backend,
Frontend, docs) are genuinely covered today**. The **process roles — Change
Management, PM, CI-backed QA, reproducible releases — are the structural
gaps**, and they are precisely the preconditions the project itself set before
Azure.

## 6. Prioritized gaps and recommended next actions

1. **Initialise version control** (highest impact). No `.git` exists; the
   Azure requirement of a *reproducible* MVP is unmet without it. Create a
   repo, baseline the tree, adopt a conventional commit + branch-and-PR flow so
   the Release/Change-Management role becomes real and every change is
   attributable.
2. **Add CI sanity gates** (pytest + ruff). All 12 suites currently pass
   locally (`lastfailed` empty); wiring them into CI converts manual QA into an
   enforced regression net and lifts the Testing and DevOps roles from ◐/✗.
3. **Pin dependencies.** `requirements.txt` is fully unpinned; add a lockfile
   or pinned constraints so `best-effort install` cannot drift the build. This
   is a second reproducibility gap blocking the Azure gate.
4. **Checkpoint walk-forward evaluation.** The Scoring/ML role is ◐: formalize
   the snapshot that proves walk-forward passes, tie it to `MIN_RECALL=0.30`,
   and record the decision — this is the explicit Go/No-Go for the Azure pilot.
5. **Define the offline labeling plan.** The ML target must be populated from
   future dividend events/coverage rather than fabricated (`README.md:666`);
   document the labeling owner and cadence so the Data Scientist/ML role is
   complete before modeling.
6. **Author a light requirements artifact.** Record the screening weights, the
   `dividend = TRUE` universe rule, and acceptance criteria in one page so the
   Product-Owner role survives knowledge loss (e.g., a `docs/requirements.md`
   or an ADR-style note).
7. **Codify security/ops hygiene** as the PM/coordinator evolves into a
   release procedure: key rotation for `API_KEY`, enforcing `SEC_USER_AGENT`
   in config, moving secrets toward a vault at Azure time, and defining a
   nightly scheduler (Airflow DAG or Azure Functions job) for the current
   manual `run_full_etl` invocation.

## 7. End-state role definition (reference)

The roles defined in section 4 remain the target responsibility map as the
project scales from a single owner to a team; the only change is that each role
moves from "worn by the single owner" to an explicit named owner. **Nothing in
this review requires an org change today** — it only marks which hats are
already being worn well, which are worn partially, and which must be put on
before the dividend-end Azure migration proceeds.