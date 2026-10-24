---
name: data-archiving
description: "Use when applying retention, pruning superseded predictions, or releasing a ticker/CIK conflict that deletes rows. Do not use for backups or for pruning point-in-time features and score history."
version: 1
risk: heavy
owner: operations
entrypoint: none  # none|fixed|list
tags: []
---

# Data Archiving and Retention

Apply the repository's narrow, explicit retention actions. There is **no general
retention job**: most tables are append-only or point-in-time history and must
not be pruned. New retention is a policy decision, not a cleanup task.

## When to use / when not to use

Use when:

- pruning superseded predictions for the date just scored;
- releasing a ticker/CIK conflict, which archives before deleting;
- reviewing the existing archive under `data/`;
- proposing a retention policy.

Do not use when:

- the task is a pre-change backup (`data-backup-recovery`);
- the tables are `model.features`, `model.forward_returns` or older
  `model.scores`/`model.rankings` dates (point-in-time history);
- the request is a blanket `DELETE` or `TRUNCATE`.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Command | `python -m scripts.score_rank --prune-superseded` | no | Prunes only the scored date. |
| Command | `python -m scripts.resolve_ticker_conflict review` | yes for conflicts | Read-only classification. |
| Command | `python -m scripts.resolve_ticker_conflict release` | yes for conflicts | Archives, then deletes, in one transaction. |
| Dir | `data/ticker_conflict_archive/` | output | Gitignored JSON archive. |
| Doc | `docs/nightly-verification.md` | yes | Conflict decision rules. |
| Doc | `docs/database-audit-report.md` | yes | Retention history and hazards. |

## Procedure

1. Run the preflight from `SYSTEM.md`. For a destructive action, take a backup
   first (`data-backup-recovery`).
2. State the exact rows in scope and why they are not point-in-time history.
3. For superseded predictions, let the scorer prune only its own date:

   ```bash
   python -m scripts.score_rank --as-of YYYY-MM-DD --prune-superseded
   ```

   A replay prunes by default; use `--keep-superseded` only when the old rows
   are deliberately wanted.
4. For a ticker/CIK conflict, review first:

   ```bash
   python -m scripts.resolve_ticker_conflict review --json
   ```

   Release only a `STALE` conflict, and only with the explicit confirmation:

   ```bash
   python -m scripts.resolve_ticker_conflict release --ticker T \
     --reviewed-by NAME --execute --confirm T
   ```

5. Verify the archive exists and its row counts match the plan before the
   transaction commits.
6. Never prune `model.features` or `model.forward_returns`: they are the
   backtest record.
7. Never touch `market.*` in this skill; those tables are reserved and empty.

## Outputs

- Deletions limited to the stated scope.
- `data/ticker_conflict_archive/<ticker>_<cik>_<utc>.json` for a conflict
  release, plus the registry note.
- `audit.source_lineage` retained for every surviving raw row.
- No archive table for deleted audit snapshots by design.

## Verification

Pass when:

- the archive file exists and its per-table counts equal the deleted counts;
- the release plan is `STALE` (not `AMBIGUOUS` or `INCOMING_WRONG`);
- only the intended date/security rows were removed;
- point-in-time history is untouched;
- the operation is recorded (registry note or scored-date output).

## Failure handling

- No archive, or a count mismatch: abort; the command rolls back the
  transaction.
- Conflict is `AMBIGUOUS` or `INCOMING_WRONG`: stop; do not release.
- A requested prune reaches an older date: stop; only the scored date may be
  pruned.
- Someone asks to prune features to save space: stop; that destroys the
  backtest. Escalate as a policy decision.
- Restoring an archived conflict is manual; report the file path and the rows.

## Source of truth

- `scripts/resolve_ticker_conflict.py`
- `scripts/score_rank.py`
- `docs/nightly-verification.md`
- `docs/database-audit-report.md`
- `docs/data-health-workstreams.md` (prediction retention)

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
