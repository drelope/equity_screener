-- ROLLBACK CANDIDATE: NOT APPLIED — V0109 (RM-03 dividend evidence/quarantine)
-- DESTRUCTIVE: for disposable/approved rollback only. Never run on shared/production
-- data without exporting all three tables. Evidence and quarantine history are the
-- audit trail; deleting them is a last resort, not routine cleanup.
--
-- Preconditions: no loader writes evidence-first, no consumer reads the evidence,
-- quarantine, or correction tables, and exports are verified.
--
-- Post-rollback ledger action (manual):
--   DELETE FROM public.schema_migrations WHERE version = 109;

BEGIN;

DROP TABLE IF EXISTS audit.dividend_corrections;
DROP TABLE IF EXISTS audit.dividend_quarantine;
DROP TABLE IF EXISTS raw.dividend_data_evidence;

COMMIT;
