-- CANDIDATE: NOT APPLIED — RM-04/RM-05 ledger role/grant candidate (V0112)
-- Promotion source: ../manifest-ledger-governance-policy-draft.md
-- APPROVAL-GATES: M1, DEC-002, DEC-003, DEC-005
-- ROLLBACK: rollback/V0112_rollback.sql
-- REHEARSAL: ledger-role-grants-rehearsal-2026-11-16.json (DDL + privilege checks)
--
-- Purpose: speculative least-privilege grants for the V0110/V0111 ledger after M1,
--          DEC-002, DEC-003, and DEC-005 approve the role model and retention policy.
--
-- Prerequisite: DBA-provisioned group roles named manifest_writer, manifest_reader,
--               and ledger_auditor, each NOLOGIN NOINHERIT. This candidate does NOT
--               create, alter, or drop roles; it asserts the prerequisites so a
--               missing/misconfigured role fails closed. Deployment role mapping and
--               security review remain external approval actions.
--
-- Additive-only: revokes PUBLIC/current grants and grants least privilege. It does
-- NOT create roles, retention jobs, purge paths, or incident-response tables.
--
-- Dependency: V0110 tables and V0111 triggers.

BEGIN;

DO $$
DECLARE
    missing_roles TEXT;
BEGIN
    SELECT string_agg(required.name, ', ')
      INTO missing_roles
      FROM (VALUES ('manifest_writer'), ('manifest_reader'), ('ledger_auditor'))
           AS required(name)
     WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = required.name);

    IF missing_roles IS NOT NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = 'V0112 prerequisite roles missing: ' || missing_roles;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM pg_roles
         WHERE rolname IN ('manifest_writer', 'manifest_reader', 'ledger_auditor')
           AND (rolcanlogin OR rolinherit)
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'V0112 prerequisite roles must be NOLOGIN NOINHERIT group roles';
    END IF;
END;
$$;

REVOKE ALL ON audit.run_manifests, audit.run_outputs FROM PUBLIC;
REVOKE ALL ON SEQUENCE audit.run_outputs_output_id_seq FROM PUBLIC;

REVOKE ALL ON audit.run_manifests, audit.run_outputs
    FROM manifest_writer, manifest_reader, ledger_auditor;
REVOKE ALL ON SEQUENCE audit.run_outputs_output_id_seq
    FROM manifest_writer, manifest_reader, ledger_auditor;
REVOKE ALL ON public.schema_migrations
    FROM manifest_reader, ledger_auditor;

GRANT USAGE ON SCHEMA audit
    TO manifest_writer, manifest_reader, ledger_auditor;
GRANT INSERT ON audit.run_manifests, audit.run_outputs TO manifest_writer;
GRANT USAGE ON SEQUENCE audit.run_outputs_output_id_seq TO manifest_writer;
GRANT SELECT ON audit.run_manifests, audit.run_outputs
    TO manifest_reader, ledger_auditor;
GRANT SELECT ON public.schema_migrations TO ledger_auditor;

COMMIT;
