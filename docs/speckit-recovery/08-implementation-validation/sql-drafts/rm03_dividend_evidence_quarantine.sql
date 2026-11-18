-- RM-03 dividend evidence/quarantine/correction additive draft (NOT APPLIED / DEC/UNK approvals pending)
-- Purpose: retain provider/feed evidence, deterministic batch identity, append-only quarantine/corrections,
-- preserve date integrity and adjustment-basis provenance without destructive overwrite of raw history.
-- Current table raw.dividend_data remains in place for compatibility during dual-read/write/cutover.

BEGIN;

-- Append-only raw dividend evidence (one row per observed provider/feed/event payload identity)
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
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_dividend_evidence_security_ex_provider_feed
    ON raw.dividend_data_evidence (security_id, ex_dividend_date, provider, feed);

CREATE INDEX IF NOT EXISTS idx_dividend_evidence_retrieved_at
    ON raw.dividend_data_evidence (retrieved_at);

-- Append-only quarantine/audit records for implausible or conflicting rows
CREATE TABLE IF NOT EXISTS audit.dividend_quarantine (
    quarantine_id BIGSERIAL PRIMARY KEY,
    evidence_id BIGINT REFERENCES raw.dividend_data_evidence(evidence_id),
    security_id UUID REFERENCES reference.securities(security_id),
    provider TEXT,
    feed TEXT,
    reason_code TEXT NOT NULL, -- e.g. implausible_amount, key_collision, basis_mismatch, missing_dates
    reason_detail TEXT,
    row_snapshot JSONB,
    status TEXT NOT NULL DEFAULT 'open', -- open/reviewed/accepted/rejected/corrected
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    detected_by_run_id TEXT,
    resolved_at TIMESTAMPTZ,
    resolution_note TEXT
);

-- Append-only correction/version history (no destructive overwrite of prior evidence)
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

-- Curated projection view/table TBD after contract approval (feed-aware key/precedence).
-- Loader changes required: deterministic in-batch dedupe by approved conflict key, COALESCE date preservation
-- for non-audited updates, and evidence-first writes.

COMMIT;
