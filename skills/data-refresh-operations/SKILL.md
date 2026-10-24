---
name: data-refresh-operations
description: "Use when running the nightly ETL, a partial or ticker-scoped refresh, a source-specific load, or re-running the pipeline after a fix. Do not use to diagnose a failed stage, change scoring, or verify a completed run without running one."
version: 1
risk: heavy
owner: operations
entrypoint: fixed
tags: []
---

# Data Refresh Operations

Run the existing pipeline safely. This skill chooses the scope, runs
`scripts.run_full_etl` (or the explicit stage scripts), respects the pipeline
lock, and leaves the run recorded in `audit.nightly_runs`.

## When to use / when not to use

Use when:

- running the nightly ETL;
- refreshing a limited ticker set or source;
- re-running after an upstream fix;
- exercising a stage subset with `--skip-*`.

Do not use when:

- the run already happened and only verification is needed
  (`observability-nightly-verification`);
- a stage failed and needs a code or data repair;
- the task is to change weights or features (`financial-scoring`);
- the task is to add schema (`data-storage-schema`).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Env | `SEC_USER_AGENT` | yes for SEC stages | Must be a real contact string. |
| Env | `OPENBB_PROVIDER`, `ObbCredentials.json` | conditional | Required only for keyed OpenBB providers. |
| Command | `python -m scripts.run_full_etl` | yes | The orchestrator; takes the advisory lock. |
| Command | `python -m scripts.run_etl` | no | Ad hoc symbol/date load, not the nightly. |
| Doc | `scripts/run_full_etl.py` module docstring | yes | Authoritative stage order and flags. |
| Table | `audit.nightly_runs` | output | Per-stage status and exit code. |

Relevant environment knobs: `DIVIDEND_LOOKBACK_START`,
`ENFORCE_DIVIDEND_RECENCY`, `DIVIDEND_RECENCY_DAYS`. Relevant flags include
`--feature-days`, `--companyfacts-refresh-after-days` and
`--preferred-companyfacts-refresh-after-days`. Read defaults from
`src/crispdm/config.py` and the script's `--help`; do not guess.

## Procedure

1. Run the preflight from `SYSTEM.md`. Confirm:
   - `git status` shows only intended edits;
   - `python -m scripts.migrate --check` exits 0 (the orchestrator also runs it
     as its first stage and refuses to start otherwise);
   - `SEC_USER_AGENT` is set for any stage that calls SEC;
   - no other run holds the pipeline lock.
2. Choose the narrowest scope that proves the change:
   - full nightly: `python -m scripts.run_full_etl --trigger manual`;
   - limited universe: `--limit 50` or `--tickers ACR-PC,ACR-PD`;
   - source subset: `--sources sec`, `--sources openbb`, or `--sources all`;
   - offline derived stages only: keep stored data and use `--skip-*` flags;
   - derived stages skipped: `--skip-derived`.
3. Never run two write runs concurrently. `run_full_etl` holds a PostgreSQL
   advisory lock and refuses a second run; do not bypass it by launching the
   stage scripts in parallel.
4. Run one command and watch the per-stage output. The orchestrator stops at
   the first failed stage (`all_ok` gate).
5. Do not label on a partial run. `--run-labels` is refused with `--limit` or
   `--tickers` because labels are immutable once written.
6. Confirm the run was recorded, then hand off to the verification skill:

   ```bash
   python -m scripts.verify_nightly_run
   ```

7. Report the trigger, scope, every stage status and the exit code.

## Outputs

- Table writes for the selected stages, including `raw.*`, `reference.*`,
  `preferred.*`, `clean.*`, `fundamentals.*`, `model.*` and `audit.*`.
- One `audit.nightly_runs` row with per-stage results and exit code.
- Stage output in the terminal (or the scheduler log).

## Verification

Pass when:

- `python -m scripts.run_full_etl` exits 0;
- `audit.nightly_runs` has a row for the run date with status `success` and no
  failed stages;
- `python -m scripts.verify_nightly_run` exits 0, or its findings are reported
  and routed;
- a limited run touched only the requested tickers/sources.

Never validate a run from process exit alone; the audit row and the verifier are
the evidence.

## Failure handling

- Pipeline lock held: report the other run; wait for it. Do not kill it or
  delete the advisory lock by hand.
- Pending migration: stop. Route to `data-storage-schema`; do not auto-apply.
- Stage failure: stop the chain; identify the owning skill (`data-acquisition`,
  `data-transformation`, `financial-scoring`) and report the stage, exit code and
  first error.
- Upstream unavailable (SEC/OpenBB/FMP/FRED): report the source and skip scope;
  do not fabricate data or silently widen a timeout.
- Partial run requested without a stable frame: never add `--run-labels`.
- A second run would overlap the nightly: stop and schedule it instead.

## Source of truth

- `scripts/run_full_etl.py`
- `scripts/run_etl.py`
- `src/crispdm/config.py`
- `docs/data-acquisition.md`
- `docs/nightly-verification.md`
- `ops/systemd/`, `airflow/dags/`

## Runner

- **Mode:** Fixed entrypoint. The deterministic runner executes only `python -m scripts.run_full_etl`; partial refresh, ticker-scoped loads and individual stages remain manual.
- **Confirmation:** `risk: heavy`, so `--yes` is required. The runner records `preflight.json`; confirm the pipeline lock is free before using it.

## Preflight

- [ ] Read `SYSTEM.md` and confirm this skill owns the task.
- [ ] `git status --short` reviewed (note exceptions if any).
- [ ] `python -m scripts.migrate --check` exits 0 if the task touches the database or schema.
- [ ] Required environment variables present by name only (never print values). Check `SEC_USER_AGENT` if calling SEC.
- [ ] No pipeline lock held / no conflicting run in progress if executing `run_full_etl`.
- [ ] Scope narrowed to the smallest change that satisfies the request.

## Handoffs

- **DB/schema drift:** route to `data-storage-schema` with `migrate --check` output and affected tables.
- **Missing/dirty source data:** route to `data-acquisition` with coverage gaps and tables.
- **Freshness/health check:** route to `observability-nightly-verification` with `audit.nightly_runs`/`audit.nightly_checks`.
- **Security/secret risk:** route to `security-compliance` (do not share secret values).
- **Investment validation, KPI/risk interpretation or a report:** route to `financial-analysis`.
- **Scoring/labeling policy:** route to `financial-scoring` or `modeling-evaluation` per boundaries above.

## Stop conditions

- [ ] Task is outside this skill's scope (see "Do not use when").
- [ ] `python -m scripts.migrate --check` reports pending migrations before a write operation.
- [ ] `--run-labels` requested with `--limit` or `--tickers` (partial runs must not be labeled).
- [ ] Action would delete reference rows, prune historical features/returns outside the allowed command, or release a ticker conflict without its dedicated confirmed command.
- [ ] Secret would be printed, logged, or committed.
- [ ] Non-zero exit from a required command with no documented "finding" handling.
- [ ] Unexpected `git status` changes in the scoped area.

## Evidence required

- **Commands:** argv list, cwd, exit codes, timestamps.
- **State:** affected tables/rows, `audit.nightly_runs`/`audit.nightly_checks`, migration ledger state, or files written.
- **Findings:** relation/filter/as-of for quantitative claims; diffs for schema/config changes.
- **Handoffs:** target skill + reason + evidence attached.
