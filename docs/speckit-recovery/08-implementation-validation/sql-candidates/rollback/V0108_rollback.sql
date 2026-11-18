-- ROLLBACK CANDIDATE: NOT APPLIED — V0108 (RM-02 PIT timing)
-- DESTRUCTIVE: for disposable/approved rollback only. Never run on shared/production
-- data without exporting raw.dividend_data timing columns. If any consumer has been
-- switched to available_at/ex_known_at, revert that consumer before dropping these.
--
-- Post-rollback ledger action (manual):
--   DELETE FROM public.schema_migrations WHERE version = 108;

BEGIN;

DROP INDEX IF EXISTS raw.idx_dividend_data_ex_known_at;
DROP INDEX IF EXISTS raw.idx_dividend_data_available_at;
ALTER TABLE raw.dividend_data
    DROP COLUMN IF EXISTS timing_confidence,
    DROP COLUMN IF EXISTS timing_evidence_source,
    DROP COLUMN IF EXISTS available_at,
    DROP COLUMN IF EXISTS ex_known_at,
    DROP COLUMN IF EXISTS payment_known_at,
    DROP COLUMN IF EXISTS record_known_at,
    DROP COLUMN IF EXISTS declared_known_at;

COMMIT;
