# P0 Draft Rehearsal Notes (Disposable DB only)

## Tool
- `scripts/rehearse_p0_drafts.py` validates draft files and can apply/verify them against an **explicit disposable** Postgres target.
- Safety: requires `--dsn`; refuses non-local/obvious shared DB names unless `--allow-nonlocal`; `--apply` requires `--i-understand-disposable-target`.

## Examples (do not run against shared DB)
```bash
# file checks only
python3 scripts/rehearse_p0_drafts.py --check-only

# disposable docker example
docker run --rm -d --name p0-rehearsal -e POSTGRES_PASSWORD=test -e POSTGRES_DB=rehearsal -p 55432:5432 postgres:17-alpine
python3 scripts/rehearse_p0_drafts.py \
  --dsn 'postgresql+psycopg://postgres:test@localhost:55432/rehearsal' \
  --apply --verify --i-understand-disposable-target \
  --out /tmp/p0-rehearsal-summary.json
docker rm -f p0-rehearsal
```

## Caveats
- Drafts assume schemas/tables like `reference.securities`, `raw.dividend_data` exist for FK/ALTER targets in a full project schema; rehearsal on a bare database may fail until canonical baseline schema/migrations are applied first.
- No shared DB rehearsal was executed in this pass. `rm02`/`rm03` drafts include `ALTER TABLE ... raw.dividend_data` and FK references; `rm04` uses `audit` schema — apply after baseline schemas/tables exist or split/adapt during promotion.
- Promotion to `sql/migrations/V0107+...` requires numbering reconciliation, DEC/UNK approvals, isolated validation evidence, and backfill/cutover review.


## Bare-DB rehearsal result (2026-11-16)
- Disposable `postgres:17-alpine` on `localhost:55434/rehearsal`, created and destroyed by agent.
- `scripts/rehearse_p0_drafts.py --apply --verify --i-understand-disposable-target` failed at RM-01: `schema "reference" does not exist` (drafts assume baseline schemas/tables for FK/ALTER targets).
- Evidence: `sql-drafts/rehearsal-apply-bare-db-2026-11-16.json` (status failed, no shared DB touched).


## Baseline-aware full rehearsal result (2026-11-16)
- Disposable `postgres:17-alpine` on `localhost:55435/rehearsal` (created and destroyed).
- `scripts/rehearse_p0_full.py --apply --verify --i-understand-disposable-target` on a clean disposable DB:
  - applied `sql/schema.sql` (273 statements), init_db inline migrations (35), versioned migrations (104 applied, ledger tracked), and all 4 P0 drafts.
  - post-apply verification: all target objects/columns present (`reference.security_membership_history`, `reference.security_eligibility_asof`, `reference.securities.delisted_date`, `raw.dividend_data_evidence`, `audit.dividend_quarantine`, `audit.dividend_corrections`, `audit.run_manifests`, `audit.run_outputs`, `public.schema_migrations`).
- Evidence: `sql-drafts/rehearsal-full-apply-2026-11-16.json` (status applied). No shared/project DB touched.
- Caveats: DDL rehearsal only (no data backfill, no consumer cutover, no performance/load, no promotion to `sql/migrations/` numbering). Drafts remain non-authoritative until DEC/UNK approvals, numbering reconciliation, backfill/rollback validation, and controlled cutover evidence.


## Numbered candidate apply + rollback rehearsal (2026-11-16)
- Derived numbered candidates V0107–V0110 live in `../sql-candidates/`; all four were applied and rolled back on a fresh isolated `postgres:17-alpine` (`127.0.0.1:55439/rehearsal`, created/destroyed; no shared DB touched).
- Result: `status=applied_and_rolled_back`; nine target objects/columns verified present after apply; eight candidate objects/columns absent after rollback; `public.schema_migrations` intact.
- Evidence: `../sql-candidates/rehearsal-apply-rollback-2026-11-16.json`; notes in `../sql-candidates/README.md` and `../sql-candidates/dependency-and-rollback-notes.md`.
- Caveats: DDL-only; rollback ledger deletions were not performed on the disposable baseline; backfill/cutover/approval still required.
