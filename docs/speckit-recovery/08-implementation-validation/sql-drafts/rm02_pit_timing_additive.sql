-- RM-02 PIT timing/availability additive draft (NOT APPLIED / DEC approvals pending)
-- Purpose: prevent leakage by distinguishing reporting period, filing/acceptance, and point-in-time availability
-- for fundamentals and dividend known-as-of semantics.

BEGIN;

-- Fundamentals/filing availability (target table(s) TBD based on canonical fundamentals storage)
-- Example additive columns if fundamentals are stored in existing tables; adjust names/types after schema review.
-- ALTER TABLE <fundamentals_fact_table>
--     ADD COLUMN IF NOT EXISTS period_end_date DATE,
--     ADD COLUMN IF NOT EXISTS filed_at TIMESTAMPTZ,
--     ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ,
--     ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ, -- PIT-safe availability timestamp
--     ADD COLUMN IF NOT EXISTS source_filing_id TEXT,
--     ADD COLUMN IF NOT EXISTS amendment_flag BOOLEAN,
--     ADD COLUMN IF NOT EXISTS timing_source TEXT;

-- Dividend known-as-of/support fields (additive support; preserve raw evidence semantics)
-- raw.dividend_data currently stores declared/record/payment/ex dates but not explicit known/available timestamps.
ALTER TABLE raw.dividend_data
    ADD COLUMN IF NOT EXISTS declared_known_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS record_known_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS payment_known_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ex_known_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS timing_evidence_source TEXT,
    ADD COLUMN IF NOT EXISTS timing_confidence TEXT;

-- PIT feature/signal consumers must filter on available_at/known-at (or approved conservative proxy) <= as_of.
-- Indexes/views to be added after contract and query-pattern confirmation.
CREATE INDEX IF NOT EXISTS idx_dividend_data_available_at
    ON raw.dividend_data (security_id, available_at);

COMMIT;
