# File-Based Agentic Workflow

Status: phase 4 complete. `SYSTEM.md`, `skills/_template/`, all 21 skills,
the deterministic executor (`scripts/agent_runner.py`), the skill lifecycle
(`docs/skill-lifecycle.md`), the audit (`scripts/skill_audit.py`), gitignored
run artifacts and the drift test exist. The pipeline they wrap is real and
authoritative: `scripts.run_full_etl` and the stage scripts listed in
[README](../README.md#data-workflow).

This document defines how a file-based agent layer sits **above** the existing
CRISP-DM pipeline. It does not replace the pipeline, add stages, or change
scoring.

## 1. Purpose and scope

The workflow gives an agent a small, stable contract for doing project work:

- one capability per skill directory, loaded on demand;
- one deterministic executor that reads the routing rules and runs an approved
  command;
- one run record per invocation, written outside version control.

**In scope:** routing a request to a skill, describing inputs and outputs,
running the existing commands, verifying the result, and recording what
happened.

**Out of scope:** new ETL stages, autonomous schema changes, live trading,
secrets handling, and any behavior that bypasses `src/crispdm/ops/catalog.py` for
queued operations.

## 2. Why the layout differs from the original sketch

The first sketch put `system.py`, `SYSTEM.md` and `skills/` at the repository
root and used ad-hoc skill names. This design keeps the intent but aligns with
the repository:

| Original | Change | Reason |
|---|---|---|
| `system.py` at root | `scripts/agent_runner.py` | The repo keeps executables under `scripts/`; a root module collides with ruff/import expectations. |
| `skills/` at root | Keep at root, tracked | `.claude/` and `.agents/` are gitignored, so skills stored there cannot be shared. |
| `investor_support` | `investment-analysis` | The real feature is `app/views/investment_analysis.py` plus `docs/InvestmentAnalysisWorkflow.md`. |
| `data_analysis` | `financial-scoring` | The project has a concrete rule-based scorer, not generic analysis. |
| `investor_reporting` | `financial-analysis` | The analyst layer validates, risks and reports the score; it is separate from score mechanics. |
| `data_dependency_optimization` | Retired | No matching stage or documented capability; keep the tree honest. |
| Underscored names | kebab-case | Matches the existing `.claude/skills/developing-with-streamlit` convention. |

## 3. Design principles

1. **Code wins.** When this document and the code disagree, the code is
   correct and this document is fixed. The same rule already governs
   `docs/InvestmentAnalysisWorkflow.md`.
2. **The pipeline is the product.** The agent coordinates existing scripts; it
   never reimplements a stage.
3. **Read-only by default.** Write actions require an explicit skill, a
   preflight, and a verification step.
4. **One primary skill per request.** Multiple skills may be consulted, but one
   owns the run and its exit criteria.
5. **Deterministic execution.** The executor builds argv from a fixed catalog,
   never from free-form shell text.
6. **Idempotency.** Every write stage is safe to re-run; upserts and
   `ON CONFLICT` are preferred over deletes.
7. **Auditability.** Every run records its intent, commands, exit codes and
   verification. Pipeline writes land in `audit.*`, not in a private log.
8. **Evidence over assertion.** A skill is done when its verifier passes, not
   when the command returns.

## 4. Directory layout

```text
dividend_equity_crispdm/
├── SYSTEM.md                              # Existing: global rules + routing pointer
├── docs/
│   ├── skill-lifecycle.md                 # Existing: five-gate authoring contract
│   └── skill-designs/                     # Existing: per-skill gate evidence
├── scripts/
│   ├── run_full_etl.py                    # Existing: stage orchestrator
│   ├── agent_runner.py                    # Existing: thin workflow executor
│   └── skill_audit.py                     # Existing: deterministic skill gate
├── skills/                                # Existing: one capability per directory
│   ├── _template/                         # Existing (copy source)
│   │   └── SKILL.md
│   ├── skill-clarify/                     # Existing (write)
│   │   └── SKILL.md
│   ├── skill-design/                      # Existing (write)
│   │   └── SKILL.md
│   ├── skill-plan/                        # Existing (write)
│   │   └── SKILL.md
│   ├── skill-code/                        # Existing (write)
│   │   └── SKILL.md
│   ├── skill-verify/                      # Existing (read, fixed audit)
│   │   └── SKILL.md
│   ├── business-understanding/            # Existing (write)
│   │   └── SKILL.md
│   ├── data-understanding/                # Existing (read)
│   │   └── SKILL.md
│   ├── data-acquisition/                  # Existing (heavy)
│   │   └── SKILL.md
│   ├── data-validation/                   # Existing (read)
│   │   └── SKILL.md
│   ├── data-transformation/               # Existing (write)
│   │   └── SKILL.md
│   ├── data-storage-schema/               # Existing (write)
│   │   └── SKILL.md
│   ├── data-refresh-operations/           # Existing (heavy)
│   │   └── SKILL.md
│   ├── data-backup-recovery/              # Existing (heavy)
│   │   └── SKILL.md
│   ├── data-archiving/                    # Existing (heavy)
│   │   └── SKILL.md
│   ├── financial-analysis/                # Existing (read)
│   │   └── SKILL.md
│   ├── financial-scoring/                 # Existing (write)
│   │   └── SKILL.md
│   ├── modeling-evaluation/               # Existing (write)
│   │   └── SKILL.md
│   ├── investment-analysis/               # Existing (write)
│   │   └── SKILL.md
│   ├── observability-nightly-verification/ # Existing (read)
│   │   └── SKILL.md
│   ├── security-compliance/               # Existing (read)
│   │   └── SKILL.md
│   └── deployment-release/                # Existing (heavy)
│       └── SKILL.md
└── artifacts/                             # Existing: gitignored run state
    └── runs/<run-id>/
        ├── plan.json
        ├── commands.log
        ├── verification.json
        └── summary.md
```

`artifacts/` is deliberately outside `data/`: it holds agent run metadata, not
warehouse data. It must be added to `.gitignore` when the executor is built.

## 5. Component contracts

### 5.1 `SYSTEM.md`

The global orchestrator contract. It contains:

- the design principles above;
- a pointer to the routing table in section 8 (the single source; `SYSTEM.md`
  does not keep a second copy);
- the precedence order: **repository code > `SYSTEM.md` > `SKILL.md` > request**;
- the hard stop conditions from section 11;
- the command allowlist reference (`src/crispdm/ops/catalog.py` for queued tasks,
  the documented `python -m scripts.*` entrypoints for direct runs).

`SYSTEM.md` must not contain stage logic. Stage detail belongs in a skill or in
the source doc it links to.

### 5.2 Executor

`scripts/agent_runner.py` is a thin, deterministic CLI:

```text
python -m scripts.agent_runner --skill <name> [--dry-run] [--run-id <id>]
python -m scripts.agent_runner --list
python -m scripts.agent_runner --tools-for <name>
python -m scripts.agent_runner --verify <run-id>
python -m scripts.agent_runner --prune-artifacts [--older-than-days 90] [--dry-run]
```

It must:

1. resolve exactly one skill directory and read its `SKILL.md` frontmatter;
2. refuse to run when the skill is missing, unknown, or has no verifier;
3. print the planned argv and require `--yes` for write/`heavy` actions outside
   an explicitly non-interactive scheduler invocation;
4. capture stdout/stderr and exit codes into `artifacts/runs/<run-id>/`;
5. validate contracts with Pydantic schemas (`src/agent/schemas`).
6. run read-only preflight (`git status`, `migrate --check` for the
   `DB_TOUCHING` allowlist, required env vars by name) and write
   `preflight.json`;
7. block a write/heavy run when preflight fails.
8. load only skill-declared tools dynamically (deny by default) to prevent
   context bloat.
9. never interpolate request text into a shell string;
10. never read or print `.env` values.

A read-only fixed entrypoint does not imply database access. `skill-verify`
runs only `python -m scripts.skill_audit --all`, so it is not in
`DB_TOUCHING` and does not require the migration check. The allowlist currently
contains `data-validation` and `observability-nightly-verification`.

`--tools-for` prints the tools a skill resolves, including each input schema.
`--dry-run` records them in `plan.json` and prints them alongside the argv. A
skill that declares no `tools` resolves none; a declared name that is unknown or
out of scope stops the run before any artifact is executed.

The executor is **not** an LLM. Model choice, if any, belongs to the client
invoking the workflow. This keeps the run reproducible.

### 5.3 `SKILL.md`

Every skill uses YAML frontmatter followed by fixed sections:

```markdown
---
name: data-acquisition
description: "Use when fetching SEC/OpenBB/FMP/FRED data or adding a source."
version: 1
risk: read | write | heavy
owner: data-engineering
entrypoint: none | fixed | list
tools: []  # optional; pass Python tools only when skill demands them
tags: []
---

# Data Acquisition

## When to use / when not to use

## Runner

## Preflight

## Inputs

## Procedure

## Outputs

## Verification

## Failure handling

## Handoffs

## Stop conditions

## Evidence required

## Source of truth
```

Rules:

- `name` must match the directory name.
- `description` states the trigger and the boundary, like the existing
  Streamlit skill.
- `risk` drives the executor's confirmation policy.
- `entrypoint` is `fixed` only when `scripts.agent_runner.py` declares the
  skill's commands; otherwise it is `none` or `list`.
- `tools` (optional) lists Python tool names made available only when this skill
  is selected (dynamic tooling to prevent context bloat). Empty by default.
- `Runner` states whether the deterministic executor may run the skill and
  repeats the confirmation rule.
- `Preflight` mirrors the orchestrator preflight for this skill.
- `Inputs` names tables, files, env vars and flags; never secret values.
- `Procedure` lists exact commands in dependency order.
- `Outputs` names tables and artifacts, including audit rows.
- `Verification` names a command, its pass condition, and the evidence to keep.
- `Handoffs` names the owning skill for out-of-scope findings.
- `Stop conditions` repeats the hard stops that apply to this skill.
- `Evidence required` lists the commands, state and findings to record.
- `Source of truth` links to code and docs instead of duplicating them.

### 5.4 Run artifacts

Each run writes a small, machine-readable record:

| File | Content |
|---|---|
| `plan.json` | request summary, selected skill, intended argv, resolved tools |
| `preflight.json` | git status, migration check, env-var presence by name |
| `commands.log` | argv, start/end time, exit code, truncated output |
| `verification.json` | verifier command, exit code, pass/fail, evidence paths |
| `summary.md` | human-readable outcome and next action |

Run IDs are UTC timestamps plus a short random suffix. Artifacts are never
committed. Retention is 90 days: `--prune-artifacts` deletes run directories
whose run-id timestamp is older than the window (dry-run first); the audit of
record stays in `audit.*`, so pruning loses no authoritative history.

## 6. Orchestrator loop

```text
intake
  -> classify (one primary skill + CRISP-DM phase)
  -> load (SYSTEM.md + SKILL.md; fail if missing)
  -> preflight (git status, env presence, migrate --check when DB-touching)
  -> execute (one stage or command at a time)
  -> verify (skill verifier + targeted tests)
  -> record (artifacts + audit rows)
  -> escalate (stop, report, name the next safe action)
```

Preflight is mandatory for write/heavy skills and every `DB_TOUCHING` skill,
without printing values:

- `git status --short` (no unexpected edits);
- `python -m scripts.migrate --check` (no pending migrations);
- required env vars are present (`DATABASE_URL`, `SEC_USER_AGENT`, and
  `API_KEY`/`OPS_ADMIN_TOKEN` only where documented);
- no other `run_full_etl` holds the pipeline lock.

A read-only skill with a fixed entrypoint still gets `git status`; it gets the
migration check only when it is in `DB_TOUCHING`. If preflight fails, the run
stops before any write.

Skill authoring does not use this CRISP-DM execution loop. It follows the five
gates in [`docs/skill-lifecycle.md`](skill-lifecycle.md): Clarify, Design, Plan,
Code, Verify. `skill-verify` runs the deterministic repository audit through the
same executor.

## 7. CRISP-DM phase map

| CRISP-DM phase | Primary skills |
|---|---|
| Business Understanding | `business-understanding` |
| Data Understanding | `data-understanding`, `data-acquisition`, `data-validation` |
| Data Preparation | `data-transformation`, `data-storage-schema`, `data-refresh-operations`, `data-backup-recovery`, `data-archiving` |
| Modeling | `financial-scoring`, `modeling-evaluation` |
| Evaluation | `financial-analysis`, `modeling-evaluation`, `observability-nightly-verification` |
| Deployment | `deployment-release`, `security-compliance`, `investment-analysis` |

Skill authoring is a separate five-gate flow, not a CRISP-DM phase:

| Gate | Primary skill | Evidence |
|---|---|---|
| Clarify | `skill-clarify` | `docs/skill-designs/<name>.md`, `clarify` gate row |
| Design | `skill-design` | contract, tool scope, reference and token plan |
| Plan | `skill-plan` | exact files, tests, verifiers and rollback |
| Code | `skill-code` | scoped diff, targeted tests, `code` gate row |
| Verify | `skill-verify` | `python -m scripts.skill_audit --all`, ruff, tests |

The ML model is **not adopted** (see `docs/requirements.md`, section 4). The
`modeling-evaluation` skill covers diagnostics and the walk-forward gate; it
does not promote a model to production.

## 8. Routing table

| Intake | Primary skill | Entrypoint | Verifier |
|---|---|---|---|
| Clarify a new skill or a material skill change | `skill-clarify` | `docs/skill-lifecycle.md`, `docs/skill-designs/_template.md` | `python -m scripts.skill_audit --skill <name> --phase clarify` |
| Design a skill's contract, tools and references | `skill-design` | `docs/skill-lifecycle.md`, `docs/skill-designs/<name>.md` | `python -m scripts.skill_audit --skill <name> --phase design` |
| Plan a skill change to exact files and tests | `skill-plan` | `docs/skill-designs/<name>.md` | `python -m scripts.skill_audit --skill <name> --phase plan` |
| Implement an approved skill plan | `skill-code` | `docs/skill-designs/<name>.md`, `skills/<name>/SKILL.md` | `python -m scripts.skill_audit --skill <name> --phase code` |
| Run the final skill gates | `skill-verify` | `python -m scripts.skill_audit --all` | exit 0 + targeted tests + ruff |
| Change screening rules, weights or acceptance criteria | `business-understanding` | `docs/requirements.md`, `src/crispdm/scoring.py` | `tests/test_scoring.py` |
| Add or assess a data source or field | `data-understanding` | `docs/data-acquisition.md`, `src/crispdm/sec_client.py`, `src/crispdm/openbb_client.py` | relevant `tests/test_populate_*` |
| Fetch raw SEC/OpenBB/FMP/FRED data | `data-acquisition` | `python -m scripts.populate_raw_tables`, `populate_reference_tables`, `populate_market_data`, `populate_dividend_data`, `populate_companyfacts`, `populate_sec_documents`, `populate_fmp_fundamentals`, `populate_macro_inputs` | stage exit 0 + population tests |
| Detect schema or payload drift | `data-validation` | `python -m scripts.check_schema_drift`, `python -m scripts.verify_nightly_run` | exit 0; findings in `audit.nightly_checks` |
| Build derived tables | `data-transformation` | `python -m scripts.populate_fundamentals`, `build_features`, `build_forward_returns`, `populate_clean_ticker_profile`, `populate_clean_company_profile`, `populate_contract_terms` | `tests/test_features.py`, `test_fundamentals_and_predictions.py` |
| Add or change schema | `data-storage-schema` | `sql/migrations/`, `python -m scripts.init_db`, `python -m scripts.migrate` | `migrate --check`, `check_schema_drift`, `tests/test_migrate.py` |
| Run the nightly or a partial pipeline | `data-refresh-operations` | `python -m scripts.run_full_etl`, `python -m scripts.run_etl` | `python -m scripts.verify_nightly_run`, `audit.nightly_runs` |
| Back up or restore the warehouse | `data-backup-recovery` | `docs/deployment-runbook.md` sections 3-4 | documented restore drill |
| Archive or apply retention | `data-archiving` | `docs/deployment-runbook.md` | lineage and `audit.source_lineage` preserved |
| Produce scores and rankings | `financial-scoring` | `python -m scripts.score_rank --prune-superseded` | `tests/test_scoring.py`, `tests/test_score_pruning.py` |
| Validate an investment, interpret KPIs/risk, or prepare the analyst dashboard/reports | `financial-analysis` | `app/views/dashboard.py`, `docs/AnalystDashboard.md`, `docs/InvestmentAnalysisWorkflow.md` | `tests/test_portfolio.py`, `tests/test_dashboard_view.py`, `tests/test_financial_analysis_skill.py` |
| Revisit the ML model | `modeling-evaluation` | `python -m scripts.evaluate_walk_forward`, `python -m scripts.dry_run_walk_forward` | `MIN_RECALL`, `audit.model_runs` |
| Work an investment-analysis worksheet | `investment-analysis` | `app/views/investment_analysis.py`, `docs/InvestmentAnalysisWorkflow.md` | `tests/test_workflow_doc.py`, `tests/test_analysis_schema.py` |
| Morning health check | `observability-nightly-verification` | `python -m scripts.verify_nightly_run` | exit 0; exit 1 is a recorded finding, not a crash |
| Handle secrets, API auth or SEC access | `security-compliance` | `src/crispdm/sec_client.py`, `api/main.py`, `.env.example` | `tests/test_api.py`, CI secret scan |
| Release or deploy | `deployment-release` | `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `docs/deployment-runbook.md` | ruff, pytest, pip-audit, secret scan |

## 9. Skill inventory

All 21 skills exist; `_template` is excluded. The five lifecycle skills form
the authoring flow in [`docs/skill-lifecycle.md`](skill-lifecycle.md). The
"Existing anchors" column is the code and documentation each skill must link to
rather than restate.

| Skill | Purpose | Existing anchors |
|---|---|---|
| `skill-clarify` | Record the problem, scope, assumptions and success criteria | `docs/skill-lifecycle.md`, `docs/skill-designs/_template.md` |
| `skill-design` | Define the skill contract, boundaries, tools and references | `docs/skill-lifecycle.md`, `docs/skill-designs/<name>.md` |
| `skill-plan` | Map the design to files, tests, verifiers and rollback | `docs/skill-lifecycle.md`, `docs/skill-designs/<name>.md` |
| `skill-code` | Implement only the approved skill plan | `docs/skill-lifecycle.md`, `docs/skill-designs/<name>.md` |
| `skill-verify` | Run the audit, tests and style gates; record evidence | `scripts/skill_audit.py`, `scripts/agent_runner.py` |
| `business-understanding` | Translate objectives into universe rules, weights and acceptance criteria | `docs/requirements.md`, `docs/GlobalMacroStrategy.md`, `src/crispdm/scoring.py` |
| `data-understanding` | Profile sources, coverage and known gaps before fetching | `docs/data-acquisition.md`, `docs/data-health-workstreams.md` |
| `data-acquisition` | Fetch and upsert raw SEC/OpenBB/FMP/FRED payloads | `scripts/populate_*.py`, `src/crispdm/sec_client.py`, `src/crispdm/openbb_client.py` |
| `data-validation` | Check schema drift, freshness, coverage and quality thresholds | `scripts/check_schema_drift.py`, `scripts/verify_nightly_run.py` |
| `data-transformation` | Build clean, fundamental and feature tables from stored payloads | `src/crispdm/features.py`, `fundamentals.py`, `doc_clauses.py`, `scripts/populate_clean_*.py` |
| `data-storage-schema` | Own schema, migrations and schema comments | `sql/schema.sql`, `sql/migrations/`, `scripts/migrate.py`, `scripts/init_db.py` |
| `data-refresh-operations` | Run nightly/partial ETL safely | `scripts/run_full_etl.py`, `scripts/run_etl.py`, `ops/systemd/`, `airflow/dags/` |
| `data-backup-recovery` | Back up and restore the warehouse | `docs/deployment-runbook.md` sections 3-4 |
| `data-archiving` | Apply retention without losing lineage | `docs/deployment-runbook.md`, `audit.source_lineage` |
| `financial-analysis` | Validate investments, interpret KPIs/risk and run the 7-tab analyst dashboard | `src/crispdm/portfolio.py`, `app/views/dashboard.py`, `docs/AnalystDashboard.md` |
| `financial-scoring` | Build and explain the rule-based composite | `src/crispdm/scoring.py`, `scripts/score_rank.py`, `docs/requirements.md` |
| `modeling-evaluation` | Keep walk-forward diagnostics reproducible; do not promote a failed model | `src/crispdm/model.py`, `scripts/evaluate_walk_forward.py`, `docs/model-labeling-plan.md` |
| `investment-analysis` | Drive the 18-step worksheet and recommendation gate | `app/analysis_schema.py`, `app/views/investment_analysis.py`, `docs/InvestmentAnalysisWorkflow.md` |
| `observability-nightly-verification` | Verify the nightly run and data-module SLAs | `scripts/verify_nightly_run.py`, `docs/nightly-verification.md` |
| `security-compliance` | Enforce SEC user agent, API key, rate limits and secret hygiene | `src/crispdm/sec_client.py`, `api/main.py`, `.env.example` |
| `deployment-release` | Release, roll back and schedule safely | `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `docs/deployment-runbook.md` |

## 10. Repository and schema map

| Schema | Contents | Produced by |
|---|---|---|
| `raw` | Source payloads, lineage, classifications | Stages 0-5f |
| `reference` | Exchanges, issuers, securities, dividend flag | Stage 1 (+1a/1b repairs) |
| `preferred` | Preferred security terms and contract clauses | Stages 3, 5b |
| `clean` | Normalized ticker/company profiles and corporate actions | Stages 5c-5d |
| `fundamentals` | Periodic financials derived from stored XBRL | Stage 6 |
| `model` | Features, forward returns, scores, predictions, rankings, labels | Stages 7-8, 10 |
| `audit` | Source lineage, data quality, nightly runs/checks, model runs | Stage 9, verifier |
| `market` | Reserved intraday tables; intentionally empty | none |

The authoritative stage list is the module docstring in
`scripts/run_full_etl.py` and the "Data Workflow" section of the README. Skills
link to those; they do not fork the numbering.

## 11. Guardrails and verification gates

### Non-negotiable stops

Stop and report instead of proceeding when:

- `git status` shows unexpected edits in a scoped change;
- `python -m scripts.migrate --check` reports pending migrations before a write;
- a stage exits non-zero;
- a verifier fails;
- a requested action would write to `market.*`, delete reference rows, or
  release a ticker conflict without its dedicated confirmed command;
- a partial run would write immutable labels (`--run-labels` with `--limit` or
  `--tickers`);
- a secret value would be printed, logged or committed;
- a skill change skips a lifecycle gate or its design record has an open
  question;
- `python -m scripts.skill_audit --all` fails.

### Repository gates

```bash
ruff check .
ruff format --check .
python -m pytest -q
python -m pytest -m "not integration" -q   # fast lane
python -m scripts.skill_audit --all
```

SQL/schema changes also require a migration under `sql/migrations/`, a
`COMMENT ON COLUMN` entry, and `python -m scripts.check_schema_drift`.
Skill changes also require the targeted tests and the lifecycle audit through
the phase being claimed.

### Data and security gates

- `SEC_USER_AGENT` must be a real contact string before any SEC request.
- The API keeps `/health` public; every other route requires `X-API-Key` and
  returns 503 when the key is unconfigured.
- Interactive API docs stay disabled unless explicitly enabled.
- Queued operations only run entries in `src/crispdm/ops/catalog.py`.
- One pipeline lock; no concurrent write stages.
- Raw rows retain `raw_payload`, `content_hash` and `provider`.
- The rule-based composite is the product; `model.predictions` is a relative
  rank, not a calibrated probability.

## 12. Drift control and rollout

### Drift control

This document must not duplicate stage logic. It links to the README, schema
and code. When a stage or command changes, update the link and the routing
table in the same change, mirroring the discipline enforced by
`tests/test_workflow_doc.py`.

`tests/test_agentic_workflow.py` enforces the contract:

1. parses the routing table and every `skills/*/SKILL.md`;
2. asserts each routed skill directory exists and `SYSTEM.md` lists it;
3. asserts frontmatter `name` matches the directory and the risk is valid;
4. asserts every skill has the required sections, including `## Verification`;
5. asserts no skill references a script that is absent from the repo;
6. asserts every executable entrypoint is a `scripts.*` module with a verifier;
7. asserts every skill declares a runner policy and its tools resolve;
8. runs `python -m scripts.skill_audit --all` for links, budgets, design gates
   and routing/`SYSTEM.md` sync.

### Rollout

| Phase | Work | Gate | Status |
|---|---|---|---|
| 0 | This document; delete the root sketch | `git diff --check` | Done |
| 1 | `SYSTEM.md`, `skills/_template/`, read-only skills (`observability-nightly-verification`, `security-compliance`, `data-understanding`) | manual review | Implemented; pending review |
| 2 | Write skills and their verifiers, starting with `data-storage-schema` and `data-refresh-operations` | each skill's verifier proves it on a scratch database | Done (evidence below) |
| 3 | `scripts/agent_runner.py`, `artifacts/`, `.gitignore` entry, drift test | `ruff`, `pytest`, one dry run | Done |
| 4 | Five lifecycle skills, `docs/skill-lifecycle.md`, `scripts/skill_audit.py`, design records | `skill_audit --all`, lifecycle and runner tests | Done |

Phase 2 scratch-database evidence (2026-10-28, scratch database
`skill_verify_scratch`, dropped after the runs):

- `data-storage-schema`: `init_db` + `migrate` (92 versioned migrations
  applied on top of the baseline), `migrate --check` exit 0,
  `check_schema_drift --quiet` exit 0 (live 1218 = reference 1218 objects),
  `tests/test_migrate.py` + `tests/test_schema_drift.py` 26 passed.
- `data-refresh-operations`: `run_full_etl --limit 500 --trigger manual`
  exit 0 (24 stages, none failed); `audit.nightly_runs` row for 2026-10-28
  with `status=success, exit_code=0`; `verify_nightly_run` exit 0 with every
  check OK; the limited run touched only the requested scope (500-ticker
  snapshot, 273 dividend payers downstream).
- The scratch run caught three stage-crashing defects from the
  `historical_only` refactor in commit `a78bb42` before the nightly hit them:
  `populate_market_data.get_target_securities` and
  `populate_dividend_data.load_security_ids` were called with a
  `historical_only` keyword they did not accept, and
  `populate_companyfacts.main` read `args.include_historical` /
  `args.historical_only` without defining the options. Fixed with regression
  tests in `tests/test_populate_market_data.py`,
  `tests/test_populate_dividend_data.py` and
  `tests/test_populate_companyfacts.py`.
- Remaining write-skill verifiers are their targeted suites:
  `test_scoring.py` + `test_score_pruning.py` (44), `test_features.py` (78),
  `test_fundamentals_and_predictions.py` (37),
  `test_workflow_doc.py` + `test_analysis_schema.py` (50),
  `test_portfolio.py` + `test_dashboard_view.py` +
  `test_financial_analysis_skill.py` (57), `test_dry_run_walk_forward.py` +
  `test_run_full_etl_stages.py` + `test_stage_exit_codes.py` (23) — all pass.
- Scope note recorded from the runs: on a cold database,
  `run_full_etl --tickers` does not bound stage 0 (`populate_raw_tables`
  accepts only `--limit`), so a ticker-scoped refresh of an empty warehouse
  sweeps the full SEC ticker file. `--limit` is the working narrow scope for a
  scratch proof.

Heavy-skill drill evidence (2026-10-28, against the live warehouse):

- `data-backup-recovery`: full §3 dump (`backup_20261028.dump`, custom format,
  2.6 GB, 1100 TOC entries) verified readable with `pg_restore --list`, copied
  out of the volume to `data/backups/`, and restored into a scratch database
  (`restore_drill`, 10 GB, zero restore errors). Verification clauses all
  passed: six checked tables matched live row counts exactly
  (`reference.securities` 12,495; `raw.market_data` 9,852,886;
  `raw.dividend_data` 320,527; `model.features` 9,745,254; `model.scores`
  440,138; `audit.nightly_runs` 36), `migrate --check` exited 0 at V0094, and
  `verify_nightly_run` reported the expected state (a faithful copy of live,
  including the 2026-10-27 stage-2 failure fixed in `daa5a70`). Scratch
  dropped after the drill.
- `data-archiving`: `resolve_ticker_conflict review --json` runs clean and
  classifies the one open conflict (`SATS`) as `STALE` -- release-eligible but
  deferred, since the release path is the dedicated confirmed command.
  `audit.source_lineage` retained 25,976 rows, byte-identical after the
  restore drill; `data/ticker_conflict_archive/` holds three prior release
  archives; no point-in-time history was pruned. The superseded-prediction
  prune path (`score_rank --prune-superseded`) ran as stage 8 of the phase-2
  scratch ETL and is covered by `tests/test_score_pruning.py`.

The executor stays deterministic. `skill-verify` is the only read-only fixed
entrypoint; all write/heavy execution still requires explicit confirmation.

### Open decisions

- Resolved: `scripts/agent_runner.py` and the loader discover root `skills/`.
  External clients should use the runner or follow the same root.
- Resolved: the executor stays strictly deterministic; model choice belongs to
  the client invoking the workflow.
- Resolved: run artifacts are pruned by age, 90 days, via
  `python -m scripts.agent_runner --prune-artifacts`. The audit of record is
  `audit.*`; the run directory is operational convenience, and 90 days covers
  a quarter of runs for failure diagnosis.
