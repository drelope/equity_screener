-- ROLLBACK CANDIDATE: NOT APPLIED — V0107 (RM-01 PIT membership)
-- DESTRUCTIVE: for disposable/approved rollback only. Never run on shared/production
-- data without an export of reference.security_membership_history,
-- reference.security_eligibility_asof, and reference.securities.delisted_date.
--
-- Preconditions before running:
--   1. Confirm no consumer reads reference.security_membership_history,
--      reference.security_eligibility_asof, or reference.securities.delisted_date.
--   2. Export the three objects (schema + data) if any row is present.
--   3. Confirm the migration is recorded as applied and this rollback is approved.
--
-- Post-rollback ledger action (manual, outside this file):
--   DELETE FROM public.schema_migrations WHERE version = 107;
--   (Do this only after the DDL rollback commits; otherwise the migrator will skip
--    the version on the next run and leave a partial schema.)

BEGIN;

DROP INDEX IF EXISTS reference.idx_securities_delisted_date;
ALTER TABLE reference.securities DROP COLUMN IF EXISTS delisted_date;
DROP TABLE IF EXISTS reference.security_eligibility_asof;
DROP INDEX IF EXISTS reference.idx_security_membership_history_security_dates;
DROP TABLE IF EXISTS reference.security_membership_history;

COMMIT;
