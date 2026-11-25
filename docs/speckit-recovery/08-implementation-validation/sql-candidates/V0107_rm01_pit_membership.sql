-- CANDIDATE: NOT APPLIED — RM-01 PIT membership candidate (V0107)
-- Promotion source: ../sql-drafts/rm01_pit_membership_additive.sql
-- APPROVAL-GATES: M1, EX-001, EX-004, UNK-003 (post-implementation validation)
-- ROLLBACK: rollback/V0107_rollback.sql
-- REHEARSAL: ../sql-drafts/rehearsal-full-apply-2026-11-16.json (draft DDL rehearsal)
--
-- Purpose: additive PIT membership/status history, as-of eligibility scaffold, and
--          delisted-date capture on reference.securities so the eligible universe can
--          be reconstructed as of a historical date (FR-UNI-01/FR-UNI-03, NFR-PIT-02/04).
--
-- Numbering: V0107 follows the current on-disk maximum V0106. The historical V0045
--            numbering gap is intentionally NOT reused (UNK-006 rationale remains
--            undocumented; see decision-unknown-tracker.md).
--
-- This file is NOT discovered by scripts/migrate.py while it lives under
-- sql-candidates/. Promotion to sql/migrations/ requires approval gates, dependency
-- review, isolated apply evidence, and backfill/cutover sign-off.
--
-- Additive-only: creates new tables/columns/indexes. It does NOT backfill membership,
-- derive delisted dates, enforce eligibility, or change consumer reads.

BEGIN;

-- Historical membership/status intervals. The status taxonomy is deliberately not
-- constrained here: M1/DEC approval is pending, and a premature CHECK would block
-- legitimate statuses discovered during the membership backfill.
CREATE TABLE IF NOT EXISTS reference.security_membership_history (
    membership_id BIGSERIAL PRIMARY KEY,
    security_id UUID NOT NULL REFERENCES reference.securities(security_id),
    status TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    listed_date DATE,
    delisted_date DATE,
    source TEXT,
    source_ref TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id TEXT,
    notes TEXT,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX IF NOT EXISTS idx_security_membership_history_security_dates
    ON reference.security_membership_history (security_id, effective_from, effective_to);

-- Optional PIT eligibility cache/materialization. Populated only after the membership
-- backfill is reconciled against reference.securities; it is not authoritative until
-- UNK-003 magnitude validation and M1 sign-off.
CREATE TABLE IF NOT EXISTS reference.security_eligibility_asof (
    as_of_date DATE NOT NULL,
    security_id UUID NOT NULL REFERENCES reference.securities(security_id),
    is_eligible BOOLEAN NOT NULL,
    eligibility_reason TEXT,
    source_run_id TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of_date, security_id)
);

-- Additive delisted-date capture. Existing rows stay NULL until the approved backfill
-- populates them from membership evidence; NULL is not evidence of "still listed".
ALTER TABLE reference.securities
    ADD COLUMN IF NOT EXISTS delisted_date DATE;

CREATE INDEX IF NOT EXISTS idx_securities_delisted_date
    ON reference.securities (delisted_date)
    WHERE delisted_date IS NOT NULL;

-- Final as-of eligibility view is intentionally deferred: its status/evidence rules
-- depend on the approved taxonomy and membership backfill contract.
-- CREATE OR REPLACE VIEW reference.v_security_eligible_asof AS ...

COMMIT;
