-- CANDIDATE: NOT APPLIED — RM-04/RM-05 run manifest/output ledger candidate (V0110)
-- Promotion source: ../sql-drafts/rm04_run_manifest_ledger.sql
-- APPROVAL-GATES: M1, DEC-002, DEC-003, DEC-005
-- ROLLBACK: rollback/V0110_rollback.sql
-- REHEARSAL: ../sql-drafts/rehearsal-full-apply-2026-11-16.json (draft DDL rehearsal)
--
-- Purpose: immutable run-manifest ledger and run-keyed output references complementing
--          file manifests under artifacts/runs/ (FR-BT-05, FR-AI-02, FR-REP-02,
--          NFR-REPRO-03, NFR-PIT-05).
--
-- Numbering: V0110 follows V0109. This file is NOT discovered by scripts/migrate.py
-- while it lives under sql-candidates/.
--
-- Additive-only: creates new audit tables/indexes. It does NOT wire scripts to persist
-- manifests, does NOT enforce immutability, and does NOT make any output run-keyed.
-- The mutation-prevention function/trigger and role model are deliberately deferred to a
-- follow-up candidate after DEC-002/003/005 approval.

BEGIN;

CREATE TABLE IF NOT EXISTS audit.run_manifests (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    resolved_as_of TEXT,
    code_sha TEXT,
    code_dirty BOOLEAN,
    git_branch TEXT,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    environment JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    manifest_json JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_run_manifests_type_created
    ON audit.run_manifests (run_type, created_at_utc);

-- Immutability guard is intentionally deferred: enabling a trigger before the approved
-- role/retention model could block legitimate incident response. Follow-up candidate:
-- CREATE OR REPLACE FUNCTION audit.prevent_run_manifest_mutation() ...

CREATE TABLE IF NOT EXISTS audit.run_outputs (
    output_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES audit.run_manifests(run_id),
    output_kind TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    storage_ref TEXT,
    content_hash TEXT,
    created_at_utc TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, output_kind, storage_ref)
);

CREATE INDEX IF NOT EXISTS idx_run_outputs_kind_entity
    ON audit.run_outputs (output_kind, entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_run_outputs_run_id
    ON audit.run_outputs (run_id);

COMMIT;
