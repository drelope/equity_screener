-- ROLLBACK CANDIDATE: NOT APPLIED — V0111 manifest immutability rollback
-- Drops the append-only triggers and trigger function created by V0111.
-- V0110 tables/rows are NOT touched. Destructive only to the V0111 guard objects.
BEGIN;

DROP TRIGGER IF EXISTS run_outputs_append_only ON audit.run_outputs;
DROP TRIGGER IF EXISTS run_manifests_append_only ON audit.run_manifests;
DROP FUNCTION IF EXISTS audit.prevent_run_manifest_mutation();

COMMIT;
