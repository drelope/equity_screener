# Synthetic Backfill / Cutover Dry-Run (2026-11-16)

Status: **rehearsal only; not approved, not applied, not promotion evidence.**

## Purpose

This dry run proves that the read-only readiness gate can be driven from
`checks_passed` to `checks_passed` with synthetic data after V0107–V0110 DDL is
applied. It does **not** establish source mappings, status taxonomy, feed
precedence, adjustment basis, or cutover approval.

## Fixture

`sql-candidates/backfill/synthetic-backfill-2026-11-16.sql` inserts:

- three invented securities (two active, one delisted with a `delisted_date`);
- non-overlapping membership intervals and an as-of eligibility snapshot;
- dividend timing rows whose `available_at` is after both the known-at timestamp
  and the ex-date, with an explicit `timing_evidence_source`;
- one evidence row per source event, one quarantined secondary-feed row with a
  reason, and one correction linked to source evidence;
- one run manifest and output reference for the synthetic backfill run.

The fixture is idempotent by natural key and is only safe on a disposable target.

## Rehearsal

Commands (isolated `postgres:17-alpine`, 127.0.0.1:55448, created/destroyed):

```bash
# baseline + V0107–V0113, with prerequisite NOLOGIN NOINHERIT roles for V0112
python3 scripts/rehearse_p0_full.py \
  --dsn 'postgresql+psycopg://postgres:test@127.0.0.1:55448/rehearsal' \
  --drafts-dir docs/speckit-recovery/08-implementation-validation/sql-candidates \
  --apply --verify --i-understand-disposable-target

# load fixture and run the read-only readiness checker
python3 scripts/rehearse_backfill_synthetic.py \
  --dsn 'postgresql+psycopg://postgres:test@127.0.0.1:55448/rehearsal' \
  --out docs/speckit-recovery/08-implementation-validation/sql-candidates/backfill/synthetic-backfill-2026-11-16.json \
  --i-understand-disposable-target
```

Result: every V0107–V0110 candidate reported `schema=present data=checks_passed`;
readiness exit 0; evidence at `synthetic-backfill-2026-11-16.json` and
`readiness-after-synthetic-synthetic-backfill-2026-11-16.json`.

## Cutover Dry-Run Sequence (to repeat with approved data)

1. Apply V0107–V0109 to an isolated copy of the canonical baseline.
2. Load approved source mappings and status taxonomy into the new tables; never
   overwrite `raw.dividend_data` or `reference.securities` historical evidence.
3. Reconcile row counts, NULL rates, interval overlaps, quarantine reasons,
   correction linkage, and feed/source precedence against the approved contract.
4. Run `check_candidate_backfill_readiness.py --dsn ...` in a read-only
   transaction and require `checks_passed`.
5. Run dual-read comparisons between current and candidate consumers; record
   deltas and M1/EX/UNK sign-off before any consumer cutover.
6. Keep rollback scripts and an export of all new tables available until the
   stabilization window ends.

Nothing in this dry run authorizes a shared/production apply or a cutover.
