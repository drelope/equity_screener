-- V0055: Map OpenBB corporate_actions to a typed child table and record the
-- flattener's unmapped source keys.
--
-- corporate_actions (DELISTING, TICKER_CHANGE, NAME_CHANGE, SPLIT, DIVIDEND
-- announcements) previously only lived inside raw.ticker_profile.raw_payload,
-- so lifecycle events never reached reference data. They are now flattened
-- into clean.corporate_action by scripts.populate_clean_company_profile in
-- the same transaction as the profile/officer rebuild.
--
-- clean.v_corporate_action_reference_exceptions lists past-effective
-- delistings/ticker changes whose reference security is still active. It is a
-- review queue only; reference data is never deactivated automatically.

CREATE TABLE IF NOT EXISTS clean.corporate_action (
  profile_id BIGINT NOT NULL
    REFERENCES clean.company_profile(profile_id) ON DELETE CASCADE,
  action_no SMALLINT NOT NULL,
  symbol TEXT NOT NULL,
  security_id UUID,
  event_type TEXT NOT NULL,
  effective_date DATE,
  amount NUMERIC,
  split_ratio TEXT,
  new_ticker TEXT,
  old_name TEXT,
  new_name TEXT,
  header TEXT,
  message TEXT,
  source_retrieved_at TIMESTAMPTZ,
  source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (profile_id, action_no),
  CONSTRAINT chk_clean_corporate_action_event_type CHECK (BTRIM(event_type) <> '')
);

CREATE INDEX IF NOT EXISTS ix_clean_corporate_action_security_event
  ON clean.corporate_action (security_id, event_type, effective_date);

COMMENT ON TABLE clean.corporate_action IS
  'OpenBB/yfinance corporate-action announcements flattened from raw.ticker_profile raw_payload openbb.corporate_actions; one row per array element';
COMMENT ON COLUMN clean.corporate_action.profile_id IS
  'Parent clean.company_profile row; rows are rebuilt with the profile and cascade on delete';
COMMENT ON COLUMN clean.corporate_action.action_no IS
  'One-based ordinal from the source corporate_actions array';
COMMENT ON COLUMN clean.corporate_action.symbol IS
  'Profile symbol the announcement was published under';
COMMENT ON COLUMN clean.corporate_action.security_id IS
  'Raw ticker-profile security ID that supplied the announcement (reference.securities key)';
COMMENT ON COLUMN clean.corporate_action.event_type IS
  'Provider meta.eventType: DIVIDEND, DELISTING, TICKER_CHANGE, NAME_CHANGE or SPLIT';
COMMENT ON COLUMN clean.corporate_action.effective_date IS
  'Effective/ex date converted from meta.dateEpochMs (Unix epoch milliseconds) to a UTC calendar date';
COMMENT ON COLUMN clean.corporate_action.amount IS
  'Announced cash amount per share for DIVIDEND events (meta.amount)';
COMMENT ON COLUMN clean.corporate_action.split_ratio IS
  'Provider split ratio text for SPLIT events, e.g. 1:16 (meta.splitRatio)';
COMMENT ON COLUMN clean.corporate_action.new_ticker IS
  'Replacement symbol for TICKER_CHANGE events (meta.newTicker)';
COMMENT ON COLUMN clean.corporate_action.old_name IS
  'Former issuer name for NAME_CHANGE events (meta.oldName)';
COMMENT ON COLUMN clean.corporate_action.new_name IS
  'New issuer name for NAME_CHANGE events (meta.newName)';
COMMENT ON COLUMN clean.corporate_action.header IS
  'Provider display header for the announcement';
COMMENT ON COLUMN clean.corporate_action.message IS
  'Provider announcement text';
COMMENT ON COLUMN clean.corporate_action.source_retrieved_at IS
  'Retrieval timestamp of the raw profile that carried the announcement';
COMMENT ON COLUMN clean.corporate_action.source_payload IS
  'Original corporate_actions array element as received';
COMMENT ON COLUMN clean.corporate_action.loaded_at IS
  'Timestamp when the clean corporate-action row was loaded';

ALTER TABLE clean.company_profile
  ADD COLUMN IF NOT EXISTS unmapped_source_keys TEXT[] NOT NULL DEFAULT '{}'::text[];

COMMENT ON COLUMN clean.company_profile.unmapped_source_keys IS
  'Scalar OpenBB source keys with no clean column; their values are preserved under source_payload.unmapped';
COMMENT ON COLUMN clean.company_profile.source_payload IS
  'JSONB snapshot of the selected source profile: mapped scalars under openbb, unmapped scalars under unmapped, plus SEC evidence; officer and corporate-action arrays are stored in child tables';

CREATE OR REPLACE VIEW clean.v_corporate_action_reference_exceptions AS
SELECT
  ca.event_type,
  ca.effective_date,
  ca.symbol,
  ca.new_ticker,
  ca.message,
  s.security_id,
  s.ticker AS reference_ticker,
  s.active AS reference_active,
  ca.source_retrieved_at
FROM clean.corporate_action ca
JOIN reference.securities s ON s.security_id = ca.security_id
WHERE ca.event_type IN ('DELISTING', 'TICKER_CHANGE')
  AND ca.effective_date <= CURRENT_DATE
  AND s.active IS TRUE;

COMMENT ON VIEW clean.v_corporate_action_reference_exceptions IS
  'Review queue: past-effective DELISTING/TICKER_CHANGE announcements whose reference.securities row is still active; never applied automatically';
