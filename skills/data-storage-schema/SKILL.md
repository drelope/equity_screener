---
name: data-storage-schema
description: "Use when adding or changing a table, column, index, constraint or schema comment, creating a migration, or resolving schema drift. Do not use for data backfills, feature logic, or editing an already-applied migration."
version: 1
risk: write
owner: data-engineering
entrypoint: fixed
tags: []
---

# Data Storage and Schema

Own the PostgreSQL schema, its forward-only migrations, and its comments. The
schema is the contract every stage, view, API route and Streamlit page reads.

## When to use / when not to use

Use when:

- adding or changing a table, column, index, constraint or enum;
- backfilling a column's `COMMENT ON COLUMN` entry;
- creating `sql/migrations/V####_name.sql`;
- investigating a schema-drift report.

Do not use when:

- the change is a data repair (`data-acquisition` or `data-transformation`);
- the change is a feature or score formula (`financial-scoring`);
- a migration is already applied and needs correction: add a new migration
  instead of editing the old one.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| File | `sql/schema.sql` | yes | Baseline, idempotent schema plus comments. |
| File | `sql/migrations/` | yes | Forward-only, ordered by `V####`. |
| File | `scripts/migrate.py` | yes | Ledger, pending check, apply. |
| File | `scripts/init_db.py` | yes | Creates the database and applies the baseline. |
| File | `scripts/check_schema_drift.py` | yes | Compares repository DDL to the live catalog. |
| Doc | `CONTRIBUTING.md` | yes | The SQL/schema PR checklist. |

## Procedure

1. Run the preflight from `SYSTEM.md`: clean `git status` for the scoped change,
   and `python -m scripts.migrate --check`. A pending migration is expected
   only when the change adds one; otherwise stop.
2. Back up before a destructive or risky migration:

   ```bash
   docker compose exec -T postgres pg_dump --username=dividend --dbname=dividend \
     --format=custom --file=/var/lib/postgresql/data/backup_$(date +%Y%m%d).dump
   ```

3. Read `sql/schema.sql` and the highest existing migration version. Never
   reuse or edit an applied version.
4. Add `sql/migrations/V####_snake_case_name.sql` with the next number. The
   file must be forward-only and idempotent where practical (`IF NOT EXISTS`,
   guarded `DO` blocks).
5. Add a `COMMENT ON COLUMN` entry for every new or changed column, and update
   the schema reference in `README.md` when a table or user-facing column
   changes.
6. Apply to a fresh or migrated database:

   ```bash
   python -m scripts.migrate --plan
   python -m scripts.migrate
   ```

   Use `python -m scripts.init_db` only when creating a new database; it
   applies the baseline plus compatibility migrations.
7. Verify the ledger and the live catalog:

   ```bash
   python -m scripts.migrate --check
   python -m scripts.check_schema_drift --quiet
   python -m pytest -q tests/test_migrate.py tests/test_schema_drift.py
   ```

8. If the change affects a view used by the API or UI, run the relevant tests
   (`tests/test_api.py`, `tests/test_current_predictions_view.py`, and the
   view-specific module).

## Outputs

- A new versioned migration under `sql/migrations/`.
- A row in `schema_migrations`.
- Updated column comments and, when needed, the README schema reference.
- No application data backfill unless the migration explicitly performs it and
  the change has been reviewed for locking and runtime.

## Verification

Pass when:

- `python -m scripts.migrate --check` exits 0;
- `python -m scripts.check_schema_drift --quiet` exits 0;
- `tests/test_migrate.py` and `tests/test_schema_drift.py` pass;
- every new column has a comment;
- the migration is present in `schema_migrations` and the expected catalog
  objects exist.

## Failure handling

- Version conflict or duplicate number: stop and resolve the version; do not
  renumber an applied migration.
- Failed migration that is already recorded: do not re-run it. Fix forward with
  a new corrective migration, or restore the pre-migration dump and re-apply.
- Migration is long-running or locking: stop and report; schedule it rather
  than holding the pipeline lock.
- Schema drift reports an object you did not add: treat it as a finding and
  reconcile the baseline versus migration path; do not edit the live catalog by
  hand.
- Destructive change without a backup: stop and take the dump first.

## Source of truth

- `sql/schema.sql`
- `sql/migrations/`
- `scripts/migrate.py`
- `scripts/init_db.py`
- `scripts/check_schema_drift.py`
- `README.md` (PostgreSQL schema section)
- `CONTRIBUTING.md`

## Runner

- **Mode:** Fixed entrypoint. The deterministic runner executes only `python -m scripts.migrate` (apply pending migrations).
- **Confirmation:** `risk: write`, so `--yes` is required. The runner's preflight also runs `python -m scripts.migrate --check` and blocks on a non-zero result. Never edit an already-applied migration.

## Preflight

- [ ] Read `SYSTEM.md` and confirm this skill owns the task.
- [ ] `git status --short` reviewed (note exceptions if any).
- [ ] `python -m scripts.migrate --check` exits 0 if the task touches the database or schema.
- [ ] Required environment variables present by name only (never print values). Check `SEC_USER_AGENT` if calling SEC.
- [ ] No pipeline lock held / no conflicting run in progress if executing `run_full_etl`.

## Handoffs

- **Apply or replay the pipeline:** route to `data-refresh-operations` with the migration plan.
- **Drift or freshness finding:** route to `observability-nightly-verification` with `check_schema_drift` output.
- **Security/secret risk:** route to `security-compliance` (do not share secret values).

## Stop conditions

- [ ] Task is outside this skill's scope (see "Do not use when").
- [ ] `python -m scripts.migrate --check` reports pending migrations before a write operation.
- [ ] `--run-labels` requested with `--limit` or `--tickers` (partial runs must not be labeled).
- [ ] Action would delete reference rows, prune historical features/returns outside the allowed command, or release a ticker conflict without its dedicated confirmed command.
- [ ] Secret would be printed, logged or committed, or a required command fails without documented "finding" handling.
- [ ] Unexpected `git status` changes in the scoped area.

## Evidence required

- **Commands:** argv list, cwd, exit codes, timestamps.
- **State:** affected tables/rows, `audit.nightly_runs`/`audit.nightly_checks`, migration ledger state, or files written.
- **Findings:** relation/filter/as-of for quantitative claims; diffs for schema/config changes.
- **Handoffs:** target skill + reason + evidence attached.
