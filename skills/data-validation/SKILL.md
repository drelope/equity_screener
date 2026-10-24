---
name: data-validation
description: "Use when checking schema drift, data freshness, coverage, quality thresholds or lineage completeness, or when a stage fails a data-integrity check. Do not use to repair the data or to run the nightly."
version: 1
risk: read
owner: data-engineering
entrypoint: fixed
tags: []
---

# Data Validation

Check that stored data matches the schema and the declared quality rules, and
produce evidence for a decision. Validation reports; it does not repair.

## When to use / when not to use

Use when:

- a schema or view change may have drifted from the live catalog;
- a freshness, coverage or completeness threshold may have been breached;
- a stage failed an integrity assertion;
- confirming `audit.source_lineage` and `audit.data_quality` are current.

Do not use when:

- the nightly has not run and must be started (`data-refresh-operations`);
- a failure needs a code or data repair;
- the task is the morning health summary only
  (`observability-nightly-verification`).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Command | `python -m scripts.migrate --check` | yes | No pending migration. |
| Command | `python -m scripts.check_schema_drift` | yes | Repository DDL versus live catalog. |
| Command | `python -m scripts.verify_nightly_run` | yes | Freshness, coverage, quality. |
| Table | `audit.data_quality` | yes | Completeness and rating snapshots. |
| Table | `audit.source_lineage` | yes | Provenance. |
| Doc | `docs/nightly-verification.md` | yes | Threshold meanings and escalation. |

## Procedure

1. Run the preflight from `SYSTEM.md`.
2. Check migrations first:

   ```bash
   python -m scripts.migrate --check
   ```

   A pending migration is a stop condition; route it to `data-storage-schema`.
3. Check schema drift:

   ```bash
   python -m scripts.check_schema_drift --quiet
   ```

   The script builds a scratch database from `sql/schema.sql`, the inline
   migrations and every versioned migration, then diffs it against the live
   catalog. It creates and drops the scratch database; it does not touch data.
4. Check freshness, coverage and quality:

   ```bash
   python -m scripts.verify_nightly_run --json
   ```

   Treat exit `0` as all checks passing and exit `1` as attention needed with
   findings; neither is a crash.
5. Run the integrity tests relevant to the change:

   ```bash
   python -m pytest -q tests/test_schema_drift.py tests/test_health_view.py tests/test_verify_nightly_run.py
   ```

6. Report each finding with the measured value, threshold, relation and as-of
   time. Route repairs to the owning skill.

## Outputs

- No data writes, except the `audit.nightly_checks` row written by
  `verify_nightly_run`.
- A findings report with pass/fail per check and the evidence command.

## Verification

Pass when:

- `migrate --check` exits 0;
- `check_schema_drift --quiet` exits 0;
- `verify_nightly_run` exits 0, or its exit-1 findings are reported with
  evidence;
- the targeted tests pass;
- every finding is reproducible from the stated command and threshold.

## Failure handling

- Missing run-tracking tables: stop; the fix is `python -m scripts.migrate`.
- Schema drift: report the object and the path that should define it; do not
  alter the live catalog by hand.
- Threshold breach: report it; never widen the threshold to clear the finding.
- Database unreachable: stop; do not infer health from a container status.
- Conflicting quality snapshots: use the latest snapshot and say which one;
  do not average across dates with different denominators.

## Source of truth

- `scripts/check_schema_drift.py`
- `scripts/verify_nightly_run.py`
- `scripts/migrate.py`
- `docs/nightly-verification.md`
- `docs/database-audit-report.md`

## Runner

- **Mode:** Fixed entrypoints. The deterministic runner executes only:
  - `python -m scripts.migrate --check`
  - `python -m scripts.check_schema_drift --quiet`
- **Confirmation:** `risk: read`, so no `--yes` is required. A non-zero exit is a finding to report, not a crash; route the owning repair to the matching skill.

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
