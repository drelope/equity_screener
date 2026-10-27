# SDLC Review — Dividend Equity Screener

Review date: 2026-09-23
Scope: key SDLC roles and responsibilities, assessed against the **current
(as-is)** state of the repository.
Basis of review: repository contents at
`dividend_equity_crispdm_implementation/dividend_equity_crispdm` (README,
`src/`, `scripts/`, `tests/`, `sql/`, `api/`, `app/`, `Dockerfile`,
`docker-compose.yml`, `azure/`).

**Update 2026-09-23:** the notable absences identified below (no VCS, no CI,
no lint config, unpinned stack) were addressed the same day. A follow-up pass
same-day closed the remaining open items: branch/PR flow (`CONTRIBUTING.md`),
walk-forward evaluation checkpoint (`scripts/evaluate_walk_forward`, persisted
to `audit.model_runs`), the offline labeling plan, the requirements artifact,
postgres digest pinning + a deployment/rollback runbook, and security/ops
hygiene (SEC-UA enforcement, key rotation guidance, Airflow/systemd schedulers).
Each affected section below marks what changed and what remains.

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
| Deployment | Local Docker Compose: `postgres`, `migrate`, `streamlit`, `api`, `worker`; **dependencies pinned** | `docker-compose.yml`, `requirements.txt` |
| CI/CD | **GitHub Actions**: ruff check + format gate, pytest matrix (3.10 / 3.12) | `.github/workflows/ci.yml` |
| Version control | **Git** (`main`, baseline commit, `.gitignore`) | `git log` |
| Lint | **ruff** configured (`ruff.toml`, E/F/W/I, line-length 100); check + format clean | `ruff.toml`, `ruff check .` |
| Tests | 84 passing pytest cases (12 modules, mock-based); enforced by CI | `tests/`, `pytest -q` |
| Cloud readiness | Azure pilot *mapped*, explicitly deferred | `azure/README.md:12` |
| ML evaluation | `scripts/evaluate_walk_forward` records the walk-forward checkpoint in `audit.model_runs` + JSON; gates on `MIN_RECALL` | `scripts/evaluate_walk_forward.py`, `docs/model-labeling-plan.md` |
| Requirements | Light requirements artifact (universe, weights, acceptance) | `docs/requirements.md` |
| Scheduling | Nightly ETL: Airflow DAG + systemd timer templates | `airflow/dags/dividend_etl_dag.py`, `ops/systemd/` |
| Operations | Local Docker Compose: `postgres`, `migrate`, `streamlit`, `api`, `worker`; **dependencies pinned** | `docker-compose.yml`, `requirements.txt` |

## 3. Phase-by-phase assessment (as-is)

### 3.1 Requirements / Business Understanding

**Responsibility:** convert the business problem ("which equities pay income,
sustainably, with strong legal/economic rights") into measurable screening
rules, weights, and acceptance criteria.

**Current state:**

- Business framing is well captured by the CRISP-DM descriptions and the
  scoring weights surfaced in the Streamlit caption: Income 33.3% |
  Sustainability 26.7% | Appreciation 20.0% | Risk 13.3% | Valuation 6.7%
  (`app/column_docs.py`, `SCORING_CAPTION`).
- The dividend-universe definition is explicit and enforced: `dividend = TRUE`
   in `reference.securities`, backed by a partial index that gates every
   downstream ETL stage (`README.md:364-367`). Since 2026-10-07 the flag means
   a positive *per-share* dividend fact inside the 548-day recency window, or a
   payment observed in `raw.dividend_data` in the same window
   (`src/crispdm/sec_client.py::classify_companyfacts`,
   `src/crispdm/dividend_universe.py`); aggregate and dividends-received tags no
   longer flag.
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
  column-level comments (`sql/schema.sql`, `README.md:661-864`).
- Single-source-of-truth XBRL tag registry (`src/crispdm/xbrl_tags.py`) that
  keeps schema comments, extractors, classifiers, and taxonomy loaders in sync
  (`README.md:812-851`).
- Explicit data-flow diagram and end-to-end pipeline
  (`SEC + OpenBB → raw → features → rules+ML → walk-forward → rankings →
  Streamlit`, `README.md:866-907`).
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
  0-9 plus optional stage 10 labels, dependency-ordered, runnable as Python
  modules).
- Consistent house style across modules; now enforced by a checked-in
  `ruff.toml` (E/F/W/I rules, line-length 100) with `ruff format` applied to
  the tree and both gates wired into CI.
- **Addressed 2026-09-23:** the "reproducibility trinity" is now in place —
  Git history, pinned `requirements.txt`, and enforced `ruff` config. This
  clears the reproducibility precondition of the Azure gate
  (`azure/README.md:12`).
- **Remaining gap:** no `pyproject.toml`/`setup.cfg`, so packaging, version
  metadata, and a peer-reviewed PR flow (branch + review) are still absent —
  history is linear on one branch.

- **Addressed 2026-09-23:** version control initialised (Git, `main`,
  baseline commit + `.gitignore`), `requirements.txt` pinned to the same
  versions as `scripts/requirements.txt` (+ `ruff`), `ruff.toml` added, and a
  GitHub Actions workflow enforces `ruff check`, `ruff format --check`, and
  `pytest` on push/PR.
- **Remaining gaps:** no `pyproject.toml`/`setup.cfg` (packaging/entry points
  still absent), and a `pyproject.toml` absent also means no lockfile — pins
  are version-only. Two latent defects found during lint remediation and fixed:
  unparseable indentation in `src/crispdm/etl.py` (INSERT/`return` outside the
  `with` block) and an undefined `get_sec_data()` reference in
  `scripts/IdentifyingDividend-PayingTickers.py` (rewired to the maintained
  `sec_dividend_analysis` pipeline).

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
  threshold (`src/crispdm/config.py:11`).
- **Addressed 2026-09-23:** CI now runs `pytest` (currently 84 passing cases)
  and the ruff gates automatically on every push/PR, so regressions are caught
  without a manual run.
- **Remaining gaps:** no integration/e2e harness (ETL is verified manually
  against the live Dockerized Postgres); no evidence checkpoint that walk
  forward evaluation is **passing** — which the Azure pilot explicitly requires
  before migration.

### 3.5 Deployment / Release

**Responsibility:** package and run the app; release safely.

**Current state:**

- `Dockerfile` (python:3.12-slim, uvicorn default) and `docker-compose.yml`
  with five services: `postgres` (17.11 pinned by digest, tuned for the
  warehouse, memory-capped, `pg_stat_statements` enabled, health-checked),
  `migrate`, `streamlit` (8501), `api` (8000, requires `API_KEY` via env) and
  `worker` (runs tasks queued from the Operations page). Every published port
  is bound to `127.0.0.1`.
- API authentication: `/health` public; every other route requires
  `X-API-Key`; missing config returns 503 (`api/main.py:18-34`).
- **Addressed 2026-09-23:** the CI/CD pipeline now exists
  (`.github/workflows/ci.yml`) — the lint and test gates run on every push/PR,
  closing the previous absence of any pipeline.
- **Remaining gaps:** no staging environment. Image pinning is done for
  `postgres` (`@sha256:` digest) and the release/rollback procedure lives in
  [deployment-runbook.md](deployment-runbook.md). Deployments today are still
  manual `docker compose up` runs on the developer machine.

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
- SEC compliance honored via `SEC_USER_AGENT` (`src/crispdm/config.py:8`).
- **Gaps:** no scheduler *outside* this host: the nightly runs from the
  systemd timer installed here (`ops/systemd/dividend-etl.{service,timer}`,
  active and firing at 03:00 ET); Airflow is still an untested alternative
  (`airflow/dags/dividend_etl_dag.py`) and no cloud scheduler (Azure Functions
  job) is deployed. No monitoring/alerting (Azure Application Insights is only
  mapped, not implemented). Secrets are managed in `.env`/`.env.example`, not a
  vault.

## 4. Key SDLC roles and responsibilities (as-is)

Today **one person fills every role**. Coverage is labeled:

- ✓ **Filled today** — the single owner actively performs the role's duties
  (with quality noted per role).
- ◐ **Partial** — function exists but is incomplete, unenforced, or guarded by
  manual steps.
- ✗ **Gap** — the role's responsibilities are not meaningfully discharged.

| Role | Primary responsibilities | Phase(s) | Coverage |
|---|---|---|---|
| **Product Owner / Business Analyst** | Own screening objectives, the weighting scheme (Income 33.3 / Sustainability 26.7 / Appreciation 20.0 / Risk 13.3 / Valuation 6.7), the dividend-universe definition, and priority order of stages | Requirements | ◐ Weighted rules and universe recorded in a light requirements artifact; acceptance criteria now codified (`docs/requirements.md`); still no PRD-level user stories |
| **Data Scientist / ML Engineer** | Feature engineering, rule+ML composite scoring (`src/crispdm/scoring.py`, `WEIGHTS` sum to 1), walk-forward evaluation, offline target labeling for future dividend outcomes | Requirements, Design, Testing | ◐ Scoring implemented + tested; checkpoint mechanism, labeler, **and a dry-run Go/No-Go demonstration** (`scripts.dry_run_walk_forward`, PASS) all wired and unit-tested; lookback (2025-01-01) + total-history provisions in place; the DB now carries 315k+ `raw.dividend_data` rows back to 1970 and 3.4M labeled `model.features` rows — **the real-data gate has been run and recorded `no_go` in `audit.model_runs` (2026-10-06), an accepted decision (the composite rules score ships, not the model)** |
| **Data Engineer** | SEC EDGAR/XBRL + OpenBB ingestion, normalization against the XBRL tag registry, `raw→reference` classification, per-CIK de-duplication, audit lineage | Design, Development, Ops | ✓ Strong: staged scripts, CIK-keyed payloads, dividend gating, `raw_payload` retention |
| **DBA / Data Modeler** | 8-schema data model, `reference.securities` hub, indexes (`ix_securities_dividend_active`), Flyway-style migrations + `init_db` compat, Compose-hosted Postgres with `pg_stat_statements` | Design, Deployment, Ops | ✓ Strong: schema documented with per-column `COMMENT`, migration discipline present |
| **Backend / API Developer** | FastAPI service, `X-API-Key` auth, query serialization, expected `404`/error-code behavior for missing SEC datasets | Development, Deployment | ✓ Filled; API-key handling and ticker validation present |
| **Frontend / Analytics Developer** | Streamlit dashboard over `model.features`/`model.scores`, Plotly visualizations, screening sliders/type filters | Development, Ops | ✓ Filled (thin view over the ranked model) |
| **QA / Test Engineer** | Mock-based pytest suites, ETL verification against live Postgres, `MIN_RECALL` acceptance hygiene | Testing | ◐ 13 suites, all cases enforced by CI (incl. walk-forward gate + SEC-UA tests); still no integration harness; walk-forward gate runs on real data end-to-end (labels + `MIN_RECALL`), latest verdict `no_go` — accepted, ML not adopted |
| **DevOps / SRE / Release Engineer** | Docker Compose services, container health/heartbeat, image reproducibility, CI/CD, Azure migration (Container Apps, Azure DB for Postgres, Blob, Functions jobs, Key Vault, App Insights) | Deployment, Ops | ◐ Compose + CI functional; **postgres image digest-pinned**, rollback runbook written, nightly scheduler installed and enabled here (systemd timer firing 03:00 ET); cloud migration still deferred |
| **Security / Compliance** | API-key auth, SEC User-Agent policy, secrets management, auditability (`audit.*`) | Requirements, Deployment, Ops | ◐ **SEC_USER_AGENT now enforced** before any SEC request; key-rotation + vault guidance in runbook; secrets still live in `.env` locally |
| **Release / Change Management** | Version control, code review, changelog, tagged releases, rollback | Development, Deployment | ◐ Git history + **documented branch/PR flow** (`CONTRIBUTING.md`), tag/release + rollback procedure defined; **no PRs merged yet, no tags cut** (linear history on `main` so far) |
| **Project Manager / Coordinator** | Backlog, sprint/phase tracking, Go/No-Go decision for Azure gate ("walk-forward passing") | All | ◐ The single-owner **operating ritual now exists and is auditable**: nightly run + data-module verification (`scripts.verify_nightly_run`, records into `audit.nightly_runs` + `audit.nightly_checks`) with a defined process doc; the Go/No-Go record pipeline (`audit.model_runs`) is in place — no dedicated coordinator beyond the owner, and the real-data gate has produced its `no_go` record (2026-10-06), accepted |
| **Technical Writer** | README, Azure mapping, schema comments, docs index | All | ✓ README + new docs (`requirements`, `model-labeling-plan`, `deployment-runbook`, `CONTRIBUTING`) |

## 5. Phase × role coverage matrix

Legend: ✓ covered today · ◐ partial · ✗ gap · — not applicable.

| Phase | PO/BA | DS/ML | Data Eng | DBA/Model | Backend | Frontend | QA | DevOps/SRE | Security | Change Mgmt | PM |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Requirements | ◐ | ◐ | — | — | — | — | — | — | ◐ | ✗ | ✗ |
| Design | ◐ | ◐ | ✓ | ✓ | ✓ | ✓ | — | ◐ | ◐ | ✗ | ✗ |
| Development | — | ✓ | ✓ | ✓ | ✓ | ✓ | ◐ | ◐ | ◐ | ◐ | ✗ |
| Testing | — | ◐ | ◐ | ◐ | ◐ | — | ◐ | ✓ | — | ◐ | ✗ |
| Deployment | — | — | — | ◐ | ◐ | — | — | ◐ | ◐ | ◐ | ✗ |
| Ops/Maintenance | — | ◐ | ✓ | ✓ | — | ✓ | — | ◐ | ◐ | ◐ | ✗ |

Reading: the **library/data disciplines (Data Engineering, DBA, Backend,
Frontend, docs) are genuinely covered today**. The 2026-09-23 hardening moved
**CI-backed QA, lint enforcement, and change tracking from gap to partial**;
the 2026-09-23 follow-up finished **walk-forward checkpointing, the labeling
plan, the requirements artifact, the branch/PR flow, deployment reproducibility
(digests + rollback + scheduler), and SEC-UA enforcement**. Roles that remain
open gaps: **PM/coordinator** and the *result* of walk-forward evaluation — the
mechanism exists but there are still no labels, so "walk-forward passing" is
not yet demonstrated (the Azure Go/No-Go cannot be recorded as met).

## 6. Prioritized gaps and recommended next actions

**Completed 2026-09-23** (original actions 1-3):

1. ✅ **Version control initialised.** Git repo on `main` with a baseline
   commit, `.gitignore` (`.env`, venv, caches, scratch artifacts excluded), and
   local commit identity configured.
2. ✅ **CI sanity gates added.** `.github/workflows/ci.yml` runs ruff lint +
   format on every push/PR and pytest across Python 3.10/3.12; the full suite
   passes locally.
3. ✅ **Dependencies pinned.** Root `requirements.txt` now matches the pinned
   `scripts/requirements.txt` (plus `ruff==0.15.22`) so installs cannot drift.

**Completed 2026-09-23 (follow-up — original actions 4-9):**

4. ✅ **Branch-and-PR flow defined.** `CONTRIBUTING.md` documents the branch
   model (`feat/`, `fix/`, `docs/`, ...), Conventional-Commit style, the PR
   checklist, and the branch-protection settings to enable once the repo is
   hosted. Merge-to-`main` via review is now the written process; no PR has
   actually been merged yet (single-owner, linear history).
5. ✅ **Walk-forward evaluation checkpoint.** `scripts/evaluate_walk_forward`
   runs `walk_forward` over labeled `model.features`, persists metrics to
   `audit.model_runs`, writes a reviewable JSON checkpoint, and exits non-zero
   when `recall < MIN_RECALL`. The checkpoint *is* the Go/No-Go record for
   Azure. **Status 2026-10-06:** labels (item 6) landed and the gate has been
   run on real data — verdict `no_go`, accepted (see item 10).
6. ✅ **Offline labeling plan authored and implemented.** The plan
    (ownership, cadence, sources, cohort acceptance, version binding) and its
    implementation, `scripts.label_targets`, both landed: the script labels
    every eligible feature row from future dividend events (1 = ≥ one positive
    payment in the 365-day window; 0 = monitored through the window end with
    none; NULL = insufficient evidence), is available as ETL stage 10 via
    `run_full_etl --run-labels`, and refuses partial `--limit`/`--tickers`
    runs so labels stay immutable.
7. ✅ **Requirements artifact.** `docs/requirements.md` records objectives, the
   dividend-universe rule, the weight scheme, acceptance criteria, out-of-scope,
   and priorities.
8. ✅ **Deployment reproducibility.** `postgres` image pinned to an immutable
   digest (`sha256:f4c6…e91232`); `docs/deployment-runbook.md` covers release
   steps, pg_dump backups, forward-only-migration-aware rollback, and
   digest-based image rollback.
9. ✅ **Security/ops hygiene codified.** `SEC_USER_AGENT` is enforced before
   any SEC request; key rotation + Key Vault guidance is in the runbook; the
   nightly schedule runs from the installed systemd timer
   `ops/systemd/dividend-etl.{service,timer}` (enabled, daily 03:00 ET); an
   equivalent Airflow DAG sits alongside it at
   `airflow/dags/dividend_etl_dag.py`, untested.

**Remaining, in priority order:**

10. **✅ Done (2026-10-06) — accrual complete, gate run, verdict accepted.**
    `raw.dividend_data` accrued (315k+ rows, back to 1970; the lookback bound
    still applies to OpenBB-derived rows), `scripts.label_targets` labeled 3.4M
    `model.features` rows (stage 10 / `--run-labels`), and
    `python -m scripts.evaluate_walk_forward` recorded the real verdict in
    `audit.model_runs`: **`no_go`**, `recall < MIN_RECALL`. The owner accepted
    it — the shipped product is the rule-based composite score, and the ML
    model is deliberately not adopted ([data-health-workstreams.md](data-health-workstreams.md),
    WS12). **Consequence to settle:** the Azure release criterion still reads
    "walk-forward evaluation is passing" (`azure/README.md:12`,
    `docs/deployment-runbook.md` §2.1); it needs restating as a
    product-owner decision (e.g. gate = rules-composite acceptance) before any
    move to Azure.
11. **Merge the first real PR and cut a release tag** to exercise the
    documented flow end-to-end, then enable branch protection when the repo is
    hosted.
12. **Perform the nightly verification ritual (and log it).** The PM tracking
    artifact now exists: `python -m scripts.verify_nightly_run` records the
    daily clean/Azure-gate check into `audit.nightly_checks`
    (see [docs/nightly-verification.md](nightly-verification.md)). Doing it
    daily — and re-verifying after any fix with a note — converts the ◐ PM role
    into a performed process; a dedicated coordinator remains optional.

## 7. End-state role definition (reference)

The roles defined in section 4 remain the target responsibility map as the
project scales from a single owner to a team; the only change is that each role
moves from "worn by the single owner" to an explicit named owner. **Nothing in
this review requires an org change today** — it only marks which hats are
already being worn well, which are worn partially, and which must be put on
before the dividend-end Azure migration proceeds.
## 8. Skill-authoring lifecycle addendum

Skill changes now follow the same gate discipline as the product pipeline:
Clarify, Design, Plan, Code, Verify ([skill-lifecycle.md](skill-lifecycle.md)).
Each phase has a named role owner, a done condition, evidence, and a stop
condition; `skill-verify` runs `python -m scripts.skill_audit --all`.

This closes the earlier gap where `SKILL.md` files were reviewed only by
inspection. The audit enforces routing/`SYSTEM.md` sync, link and source-path
validity, required sections, least-privilege tool scope, secret hygiene,
progressive-disclosure budgets, and durable design records for lifecycle-tagged
skills. The five lifecycle skills are the authoring path; they do not replace
the CRISP-DM execution skills.
