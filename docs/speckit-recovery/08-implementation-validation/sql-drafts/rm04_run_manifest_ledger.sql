-- RM-04/RM-05 run manifest and run-keyed output ledger draft (NOT APPLIED / DEC approvals pending)
-- Purpose: immutable run manifests, append-only run records, run-keyed score/report/output references.
-- Complements file artifacts currently written to artifacts/runs/* by scripts.

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

-- Immutability guard (example; policy/role model TBD)
-- CREATE OR REPLACE FUNCTION audit.prevent_run_manifest_mutation() ...

CREATE TABLE IF NOT EXISTS audit.run_outputs (
    output_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES audit.run_manifests(run_id),
    output_kind TEXT NOT NULL, -- score/report/feature/label/market_data/dividend_ingest/audit/etc.
    entity_type TEXT,
    entity_id TEXT,
    storage_ref TEXT,          -- table/key/path/object uri
    content_hash TEXT,
    created_at_utc TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, output_kind, storage_ref)
);

CREATE INDEX IF NOT EXISTS idx_run_outputs_kind_entity
    ON audit.run_outputs (output_kind, entity_type, entity_id);

COMMIT;
