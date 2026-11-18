-- CANDIDATE: NOT APPLIED — RM-02 PIT timing/availability candidate (V0108)
-- Promotion source: ../sql-drafts/rm02_pit_timing_additive.sql
-- APPROVAL-GATES: M1, EX-003, UNK-001, UNK-002
-- ROLLBACK: rollback/V0108_rollback.sql
-- REHEARSAL: ../sql-drafts/rehearsal-full-apply-2026-11-16.json (draft DDL rehearsal)
--
-- Purpose: additive timing columns that distinguish reporting period, filing/acceptance,
--          and point-in-time availability for fundamentals and dividend known-as-of
--          semantics (NFR-PIT-01, FR-DIV-03/04, FR-FEAT-01/02).
--
-- Numbering: V0108 follows the current on-disk maximum V0106 (V0107 reserved for RM-01).
-- This file is NOT discovered by scripts/migrate.py while it lives under sql-candidates/.
--
-- Additive-only: adds nullable columns/indexes. It does NOT backfill timestamps, does NOT
-- rewrite feature/label queries, and does NOT by itself make any consumer PIT-compliant.
-- Consumer cutover (using available_at <= as_of or an approved conservative proxy) is a
-- separate, approved change after UNK-001/002 canonical-basis decisions.

BEGIN;

-- Fundamentals/filing availability. The canonical fundamentals table is still being
-- reconciled (DEC-007), so these ALTERs remain disabled until the target is confirmed:
-- ALTER TABLE <fundamentals_fact_table>
--     ADD COLUMN IF NOT EXISTS period_end_date DATE,
--     ADD COLUMN IF NOT EXISTS filed_at TIMESTAMPTZ,
--     ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ,
--     ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ,
--     ADD COLUMN IF NOT EXISTS source_filing_id TEXT,
--     ADD COLUMN IF NOT EXISTS amendment_flag BOOLEAN,
--     ADD COLUMN IF NOT EXISTS timing_source TEXT;

-- Dividend known-as-of support. raw.dividend_data currently stores event dates but no
-- explicit knowledge/availability timestamps; these columns let ingestion record when
-- each fact became known without changing the existing key or overwriting raw dates.
ALTER TABLE raw.dividend_data
    ADD COLUMN IF NOT EXISTS declared_known_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS record_known_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS payment_known_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ex_known_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS timing_evidence_source TEXT,
    ADD COLUMN IF NOT EXISTS timing_confidence TEXT;

-- Consumer filtering is expected to use available_at (or an approved proxy) <= as_of.
-- The index supports that read pattern once the contract is approved.
CREATE INDEX IF NOT EXISTS idx_dividend_data_available_at
    ON raw.dividend_data (security_id, available_at);

CREATE INDEX IF NOT EXISTS idx_dividend_data_ex_known_at
    ON raw.dividend_data (security_id, ex_known_at)
    WHERE ex_known_at IS NOT NULL;

COMMIT;
