-- ROLLBACK CANDIDATE: NOT APPLIED — V0110 (RM-04/RM-05 run manifest/output ledger)
-- DESTRUCTIVE: for disposable/approved rollback only. Never run on shared/production
-- data without exporting audit.run_outputs and audit.run_manifests. The manifest ledger
-- is intended as immutable evidence; dropping it discards provenance.
--
-- Preconditions: scripts/consumers do not require the ledger for the current run, and a
-- verified export exists. File-based artifacts under artifacts/runs/ are unaffected.
--
-- Post-rollback ledger action (manual):
--   DELETE FROM public.schema_migrations WHERE version = 110;

BEGIN;

DROP TABLE IF EXISTS audit.run_outputs;
DROP TABLE IF EXISTS audit.run_manifests;

COMMIT;
