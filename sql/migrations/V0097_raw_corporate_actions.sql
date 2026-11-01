-- V0097: Persist corporate actions in the warehouse.
--
-- Split history used to be a gitignored CSV artifact read by
-- portfolio.load_split_events, so a fresh checkout or another host had no split
-- data and nothing recorded where a ratio came from. The table holds splits now
-- and has room for symbol changes, mergers and spinoffs.
--
-- security_id is nullable: a provider reports by ticker, and a ticker that does
-- not resolve to a security is kept (and visible) rather than dropped.
BEGIN;

CREATE TABLE IF NOT EXISTS raw.corporate_actions (
  action_id BIGSERIAL PRIMARY KEY,
  security_id UUID REFERENCES reference.securities(security_id),
  ticker VARCHAR(32) NOT NULL,
  action_type VARCHAR(16) NOT NULL
    CHECK (action_type IN ('split', 'symbol_change', 'merger', 'spinoff')),
  effective_date DATE NOT NULL,
  numerator NUMERIC,
  denominator NUMERIC,
  ratio NUMERIC CHECK (ratio IS NULL OR ratio > 0),
  from_symbol VARCHAR(32),
  to_symbol VARCHAR(32),
  source VARCHAR(64) NOT NULL,
  source_hash VARCHAR(64) NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT corporate_actions_source_hash_key UNIQUE (source_hash)
);

CREATE INDEX IF NOT EXISTS corporate_actions_security_date_idx
  ON raw.corporate_actions (security_id, effective_date);
CREATE INDEX IF NOT EXISTS corporate_actions_ticker_idx
  ON raw.corporate_actions (ticker, action_type);

COMMENT ON TABLE raw.corporate_actions IS
  'Splits, symbol changes, mergers and spinoffs as reported by a provider; one row per source_hash';
COMMENT ON COLUMN raw.corporate_actions.ratio IS
  'Price multiplier for pre-event prints: denominator / numerator for a split (2-for-1 = 0.5)';
COMMENT ON COLUMN raw.corporate_actions.source_hash IS
  'SHA-256 of source|ticker|action_type|effective_date|numerator|denominator|from|to; makes loads idempotent';

COMMIT;
