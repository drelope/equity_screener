-- RM-01 PIT membership additive draft (NOT APPLIED / DEC approvals pending)
-- Purpose: support as-of eligible universe, delisted/inactive PIT validity, reproducible PIT recomputes.
-- Safety: additive-first; no destructive changes to reference.securities in this draft.

BEGIN;

-- Historical membership/status intervals (authoritative where available)
CREATE TABLE IF NOT EXISTS reference.security_membership_history (
    membership_id BIGSERIAL PRIMARY KEY,
    security_id UUID NOT NULL REFERENCES reference.securities(security_id),
    status TEXT NOT NULL, -- e.g. active/inactive/listed/delisted/suspended (taxonomy TBD DEC/M1)
    effective_from DATE NOT NULL,
    effective_to DATE,    -- NULL = open/current interval as known at load time
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

-- Optional PIT eligibility cache/materialization for audited recomputes (populate after backfill)
CREATE TABLE IF NOT EXISTS reference.security_eligibility_asof (
    as_of_date DATE NOT NULL,
    security_id UUID NOT NULL REFERENCES reference.securities(security_id),
    is_eligible BOOLEAN NOT NULL,
    eligibility_reason TEXT,
    source_run_id TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of_date, security_id)
);

-- Delisted date capture on canonical security row (additive; backfill policy TBD)
ALTER TABLE reference.securities
    ADD COLUMN IF NOT EXISTS delisted_date DATE;

-- Example as-of eligibility view (draft; final logic depends on approved status taxonomy/evidence)
-- CREATE OR REPLACE VIEW reference.v_security_eligible_asof AS ...

COMMIT;
