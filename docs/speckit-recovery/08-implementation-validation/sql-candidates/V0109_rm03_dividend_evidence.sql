-- CANDIDATE: NOT APPLIED — RM-03 dividend evidence/quarantine candidate (V0109)
-- Promotion source: ../sql-drafts/rm03_dividend_evidence_quarantine.sql
-- APPROVAL-GATES: M1, EX-002, UNK-002, UNK-005
-- ROLLBACK: rollback/V0109_rollback.sql
-- REHEARSAL: ../sql-drafts/rehearsal-full-apply-2026-11-16.json (draft DDL rehearsal)
--
-- Purpose: append-only provider/feed evidence, quarantine, and correction history for
--          dividends; deterministic batch identity and adjustment-basis provenance without
--          destructive overwrite of raw history (FR-DIV-01/04/05/08, UNK-005).
--
-- Numbering: V0109 follows V0108. This file is NOT discovered by scripts/migrate.py
-- while it lives under sql-candidates/.
--
-- Additive-only: creates new tables/indexes. raw.dividend_data remains authoritative for
-- current readers until the evidence-first loader, curated projection, dual-read/cutover,
-- and approved conflict-key/precedence contract are implemented and validated.

BEGIN;

-- One row per observed provider/feed/event payload identity. Append-only by convention;
-- no UPDATE/DELETE policy is enforced here (role/immutability model pending UNK-005).
CREATE TABLE IF NOT EXISTS raw.dividend_data_evidence (
    evidence_id BIGSERIAL PRIMARY KEY,
    security_id UUID NOT NULL REFERENCES reference.securities(security_id),
    provider TEXT NOT NULL,
    feed TEXT,
    ex_dividend_date DATE,
    declaration_date DATE,
    record_date DATE,
    payment_date DATE,
    amount NUMERIC,
    adjusted_amount NUMERIC,
    amount_feed TEXT,
    currency TEXT,
    frequency TEXT,
    source_event_key TEXT,
    source_payload_hash TEXT,
    source_payload JSONB,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingest_run_id TEXT,
    is_quarantined BOOLEAN NOT NULL DEFAULT FALSE,
    quarantine_reason TEXT,
    correction_of_evidence_id BIGINT REFERENCES raw.dividend_data_evidence(evidence_id),
    notes TEXT,
    CHECK (NOT is_quarantined OR quarantine_reason IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_dividend_evidence_security_ex_provider_feed
    ON raw.dividend_data_evidence (security_id, ex_dividend_date, provider, feed);

CREATE INDEX IF NOT EXISTS idx_dividend_evidence_retrieved_at
    ON raw.dividend_data_evidence (retrieved_at);

CREATE INDEX IF NOT EXISTS idx_dividend_evidence_source_event_key
    ON raw.dividend_data_evidence (provider, source_event_key)
    WHERE source_event_key IS NOT NULL;

-- Append-only quarantine/audit records for implausible or conflicting rows.
CREATE TABLE IF NOT EXISTS audit.dividend_quarantine (
    quarantine_id BIGSERIAL PRIMARY KEY,
    evidence_id BIGINT REFERENCES raw.dividend_data_evidence(evidence_id),
    security_id UUID REFERENCES reference.securities(security_id),
    provider TEXT,
    feed TEXT,
    reason_code TEXT NOT NULL,
    reason_detail TEXT,
    row_snapshot JSONB,
    status TEXT NOT NULL DEFAULT 'open',
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    detected_by_run_id TEXT,
    resolved_at TIMESTAMPTZ,
    resolution_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_dividend_quarantine_status_detected
    ON audit.dividend_quarantine (status, detected_at);

-- Append-only correction/version history; prior evidence is never overwritten.
CREATE TABLE IF NOT EXISTS audit.dividend_corrections (
    correction_id BIGSERIAL PRIMARY KEY,
    security_id UUID NOT NULL REFERENCES reference.securities(security_id),
    provider TEXT,
    feed TEXT,
    target_event_key TEXT,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    correction_reason TEXT,
    source_evidence_id BIGINT REFERENCES raw.dividend_data_evidence(evidence_id),
    approved_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_dividend_corrections_target
    ON audit.dividend_corrections (security_id, target_event_key, field_name);

-- Curated projection (view/table) is intentionally deferred until the approved
-- conflict key/feed precedence and dual-read contract exist.

COMMIT;
