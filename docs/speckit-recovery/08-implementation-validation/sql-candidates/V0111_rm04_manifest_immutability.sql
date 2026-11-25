-- CANDIDATE: NOT APPLIED — RM-04 manifest ledger immutability candidate (V0111)
-- Promotion source: follow-up to V0110; see dependency-and-rollback-notes.md#v0111
-- APPROVAL-GATES: M1, DEC-002, DEC-003, DEC-005
-- ROLLBACK: rollback/V0111_rollback.sql
-- REHEARSAL: rehearsal-apply-rollback-v0111-2026-11-16.json (DDL + behavior rehearsal)
--
-- Purpose: database-enforced append-only behavior for the V0110 run manifest/output
--          ledger (FR-BT-05, FR-AI-02, NFR-REPRO-03, NFR-PIT-05).
--
-- Numbering: V0111 follows V0110. This file is NOT discovered by scripts/migrate.py
-- while it lives under sql-candidates/.
--
-- Additive-only: creates one trigger function and two triggers. It does NOT add
-- roles/grants, retention policy, or an incident-response bypass. Those depend on
-- DEC-002/003/005 and remain unimplemented.
--
-- Dependency: requires audit.run_manifests and audit.run_outputs from V0110.

BEGIN;

CREATE OR REPLACE FUNCTION audit.prevent_run_manifest_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'append-only ledger: % is not allowed on %.% (run_id=%)',
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME, OLD.run_id
        USING ERRCODE = '23000';
END;
$$;

CREATE TRIGGER run_manifests_append_only
BEFORE UPDATE OR DELETE ON audit.run_manifests
FOR EACH ROW EXECUTE FUNCTION audit.prevent_run_manifest_mutation();

CREATE TRIGGER run_outputs_append_only
BEFORE UPDATE OR DELETE ON audit.run_outputs
FOR EACH ROW EXECUTE FUNCTION audit.prevent_run_manifest_mutation();

COMMIT;
