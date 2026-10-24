---
name: data-backup-recovery
description: "Use when taking a pre-change database snapshot, testing a restore, or recovering from a bad migration or release. Do not use for routine nightly operation or for deleting the data volume."
version: 1
risk: heavy
owner: operations
entrypoint: none  # none|fixed|list
tags: []
---

# Data Backup and Recovery

Snapshot the warehouse before a risky change, prove the snapshot is readable,
and restore deliberately. The `pgdata` volume is the system of record; the
repository only contains schema and code.

## When to use / when not to use

Use when:

- before a destructive or long migration;
- before a high-volume repair or debug sweep;
- testing disaster recovery;
- recovering from a failed migration or bad release.

Do not use when:

- the task is a normal nightly (`data-refresh-operations`);
- the task is archiving specific rows (`data-archiving`);
- the request is to run `docker compose down -v` as a first resort.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `POSTGRES_PASSWORD` | yes for Compose | Never print the value. |
| File | `docs/deployment-runbook.md` sections 3-4 | yes | Backup and rollback procedure. |
| File | `docker-compose.yml` | yes | Service and volume names. |
| Volume | `pgdata` | yes | Persists the warehouse. |
| Command | `docker compose exec -T postgres pg_dump` | yes | Custom-format snapshot. |
| Command | `pg_restore --list` | yes | Readability check. |

## Procedure

1. Run the preflight from `SYSTEM.md`. Confirm the target database and the
   release/tag you are protecting.
2. Take a custom-format dump inside the container:

   ```bash
   docker compose exec -T postgres pg_dump --username=dividend --dbname=dividend \
     --format=custom --file=/var/lib/postgresql/data/backup_$(date +%Y%m%d).dump
   ```

3. Verify the dump is readable before relying on it:

   ```bash
   docker compose exec -T postgres pg_restore --list \
     /var/lib/postgresql/data/backup_YYYYMMDD.dump | head
   ```

4. Copy the dump out of the volume when it must survive a volume rebuild.
5. For a restore drill or recovery, restore into a scratch database first.
   Never restore over the live database without an explicit stop-and-confirm.
6. For a release rollback, follow `docs/deployment-runbook.md` section 4:
   previous tag, `postgres`, `migrate`, then application services.
7. After any restore, run migrations only to the target version, then
   `python -m scripts.verify_nightly_run`.

## Outputs

- A dump file under the PostgreSQL data directory (and a copy outside it when
  required).
- A restored scratch or live database, with the restore command recorded.

## Verification

Pass when:

- `pg_restore --list` reads the dump without error;
- the restore target has the expected schemas and row counts for the tables you
  checked;
- `python -m scripts.migrate --check` exits 0 for the target version;
- `python -m scripts.verify_nightly_run` reports the expected state.

## Failure handling

- Dump missing or zero-length: stop; do not proceed with the risky change.
- Restore fails: keep the live database untouched and report the error.
- Migration already applied and failing: do not re-run it; apply a corrective
  migration or restore the pre-migration dump.
- `docker compose down -v` would be needed: treat it as a last resort, take a
  dump first, and get explicit confirmation.
- Never delete a dump during the same change that might need it.

## Source of truth

- `docs/deployment-runbook.md` sections 3-4
- `docker-compose.yml`
- `scripts/migrate.py`
- `scripts/verify_nightly_run.py`

## Runner

- **Mode:** Follow this skill's procedure. The deterministic runner only executes allowlisted fixed entrypoints; most work here is manual unless stated otherwise.
- **Confirmation:** Skills with `risk: write` or `risk: heavy` require `--yes` when executed via the runner. Never parse commands from Markdown.

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
