-- ROLLBACK CANDIDATE: NOT APPLIED — V0112 ledger role/grant rollback
-- Revokes only privileges granted by V0112. It does NOT drop the prerequisite
-- group roles (they are DBA-provisioned and may have other grants). Export the
-- current ACLs before running this on an isolated target.
BEGIN;

REVOKE ALL ON audit.run_manifests, audit.run_outputs
    FROM manifest_writer, manifest_reader, ledger_auditor;
REVOKE ALL ON SEQUENCE audit.run_outputs_output_id_seq
    FROM manifest_writer, manifest_reader, ledger_auditor;
REVOKE ALL ON public.schema_migrations FROM ledger_auditor;
REVOKE USAGE ON SCHEMA audit
    FROM manifest_writer, manifest_reader, ledger_auditor;

COMMIT;
