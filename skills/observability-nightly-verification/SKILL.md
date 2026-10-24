---
name: observability-nightly-verification
description: "Use when checking whether the nightly ETL ran, whether source tables are fresh, whether dividend coverage or data quality breached a threshold, or when investigating a failed nightly. Do not use to re-run or repair the pipeline."
version: 1
risk: read
owner: operations
entrypoint: fixed
tags: []
---

# Observability and Nightly Verification

Run the morning health check and interpret it. This skill inspects the recorded
nightly run and the data modules; it does not repair data or trigger the ETL.

## When to use / when not to use

Use when:

- running the morning check after the 03:00 ET nightly;
- replaying a historical date after a scoring-policy change;
- investigating a stale source, coverage drop or quality breach;
- confirming that `audit.nightly_runs` and `audit.nightly_checks` are current.

Do not use when:

- the pipeline has not run and must be started (`data-refresh-operations`);
- a failed stage needs a code or data fix;
- the task is a full schema audit (`data-validation`).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Table | `audit.nightly_runs` | yes | Per-stage status and exit code. |
| Table | `audit.nightly_checks` | yes | Recorded verification findings. |
| Command | `python -m scripts.verify_nightly_run` | yes | The check itself. |
| Doc | `docs/nightly-verification.md` | yes | Thresholds and escalation. |

## Procedure

1. Run the preflight from `SYSTEM.md`.
2. Confirm the run-tracking tables exist. If they are missing, stop and report
   `python -m scripts.migrate` (do not run it from this skill).
3. Run the check for the target date:

   ```bash
   python -m scripts.verify_nightly_run --json
   ```

   For a historical date:

   ```bash
   python -m scripts.verify_nightly_run --run-date YYYY-MM-DD --json
   ```

4. Read the JSON. Separate the critical checks from the informational
   walk-forward verdict. The ML model is not adopted; a `no_go` readiness is
   expected and is not an outage.
5. For each finding, name the source table, the measured age/coverage, the
   threshold and the observation time.
6. Record the outcome in `audit.nightly_checks` through the command itself; do
   not insert rows by hand.
7. Escalate per `docs/nightly-verification.md`: stale nightly, failed stage,
   coverage breach, or security-consistency failure.

## Outputs

- Console/JSON report.
- One row in `audit.nightly_checks` for the target date, written by the
  verifier.
- No other writes.

## Verification

Pass when:

- the verifier exits `0` and the `audit.nightly_checks` row for the date has
  the expected status;
- exit `1` is reported as a finding with its evidence, not treated as a crash;
- any critical failure names the failed check and the next safe action.

Use `--no-check-log` only when the caller must not write the check record; say
so explicitly in the report.

## Failure handling

- Missing run-tracking tables: stop; the fix is `python -m scripts.migrate`.
- No `audit.nightly_runs` row: report a missed nightly; do not backfill a
  success row.
- Database unreachable: stop; do not infer health from container status alone.
- Verifier exits `1`: report findings and route the repair; do not widen a
  threshold to clear it.

## Source of truth

- `scripts/verify_nightly_run.py`
- `docs/nightly-verification.md`
- `src/crispdm/ops/catalog.py` (`verify_nightly`)
- `scripts/run_full_etl.py` (stage recording)

## Runner

- **Mode:** Fixed entrypoint. The deterministic runner executes only `python -m scripts.verify_nightly_run`.
- **Confirmation:** `risk: read`, so no `--yes` is required. Never parse commands from Markdown; use the documented script for ad-hoc SQL.

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
- **Scoring/labeling policy:** route to `analysis-scoring` or `modeling-evaluation` per boundaries above.

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
