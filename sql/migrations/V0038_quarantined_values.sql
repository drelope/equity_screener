-- V0038 quarantined_values
--
-- Append-only registry of data values that are known-wrong and deliberately left
-- in place. Quarantine here means "keep it visible and queryable, stop trusting
-- it", not "delete it" and not "block the run".
--
-- Why this exists: V0036 restored reference.securities.dividend_last_paid by
-- taking the max period end out of dividend_facts, which is faithful to what the
-- extractor saw. For five securities that max is in the future, because the
-- dividend-concept match is broad enough to admit dividend-payable and
-- forward-dated facts (MTEX 2108-11-14; SQFT, SQFTP, SQFTW, UBSI 2026-12-31).
--
-- The correct fix is to narrow the matcher, which changes the dividend universe
-- and so needs its own reviewed run. Meanwhile the values stay where they are --
-- deleting or NULLing them would hide a real defect and lose the evidence that
-- the matcher produced them -- and they are recorded here so the next run can
-- find them without re-deriving the whole population.
--
-- These rows do not reach the composite. build_features() reads raw.market_data
-- and raw.dividend_data; nothing reads reference.securities.dividend_last_paid,
-- so the five securities score on the same inputs as any other and their
-- published scores are unaffected. The registry records that judgement rather
-- than asserting it, and the values remain correct-by-construction here so a
-- future matcher fix can be compared against what was quarantined.
--
-- No constraint blocks ingestion: a CHECK that rejected future dates would fail
-- the classification write for the whole issuer, which is the coupling this
-- registry exists to avoid.

CREATE TABLE IF NOT EXISTS audit.quarantined_values (
    quarantine_id BIGSERIAL PRIMARY KEY,
    table_schema   VARCHAR(64) NOT NULL,
    table_name     VARCHAR(64) NOT NULL,
    column_name    VARCHAR(64) NOT NULL,
    row_key        TEXT        NOT NULL,   -- PK of the offending row, as text
    cik            VARCHAR(10),
    ticker         VARCHAR(16),
    observed_value TEXT        NOT NULL,   -- the quarantined value, verbatim
    reason         TEXT        NOT NULL,   -- why it cannot be trusted
    rule           TEXT        NOT NULL,   -- the predicate that detected it
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at    TIMESTAMPTZ,            -- NULL while still quarantined
    resolution_note TEXT,                   -- what fixed it, once it does
    UNIQUE (table_schema, table_name, column_name, row_key, observed_value)
);

COMMENT ON TABLE audit.quarantined_values IS
    'Known-wrong values left in place and excluded from downstream use. '
    'Append-only: resolution is recorded by setting resolved_at, never by '
    'deleting the row, so the defect stays auditable after it is fixed.';

-- Seed the population V0036 produced. ON CONFLICT DO NOTHING so re-running is
-- a no-op rather than a duplicate; detected_at then records first sighting.
INSERT INTO audit.quarantined_values (
    table_schema, table_name, column_name, row_key,
    cik, ticker, observed_value, reason, rule
)
SELECT
    'reference', 'securities', 'dividend_last_paid', s.security_id::text,
    s.cik, s.ticker, s.dividend_last_paid::text,
    'dividend_last_paid is in the future, so the dividend-concept match admitted '
    'a dividend-payable or forward-dated fact and the max period end is not a '
    'payment date. Re-extract after the matcher is narrowed.',
    'dividend_last_paid > now()::date'
FROM reference.securities s
WHERE s.dividend_last_paid > now()::date
ON CONFLICT (table_schema, table_name, column_name, row_key, observed_value)
DO NOTHING;
