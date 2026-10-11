-- =====================================================================
-- V0054 ticker_profile_load_history
--
-- raw.ticker_profile was a mutable "latest" row maintained by three writers
-- with COALESCE(new, old) per column and a shallow `old || new` JSON merge:
--   * nothing that was ever written could be cleared, so a mis-derived value
--     (e.g. an issuer-level SEC par value stamped into liquidation_preference)
--     survived every later correction;
--   * the payload accumulated legacy top-level keys beside the nested
--     provider objects, and the clean flattener read the stale ones;
--   * there was no history, so no load could be replayed or audited.
--
-- This migration:
--   1. adds raw.ticker_profile_load, an append-only landing history that every
--      writer inserts into (src/crispdm/ticker_profile_store.py) before merging
--      into the latest table with explicit column ownership;
--   2. adds raw.ticker_profile.field_sources (column -> loader lineage);
--   3. seeds the history with a baseline snapshot of every current row, taken
--      BEFORE normalization so the legacy payload keys are preserved;
--   4. normalizes raw.ticker_profile.raw_payload to the provider envelope
--      {openbb, sec_xbrl, sec_xbrl_scope}: legacy flat keys are dropped where a
--      nested openbb object exists, and flat-only payloads are wrapped as openbb.
-- Idempotent: safe on a fresh database built from schema.sql.
-- =====================================================================

CREATE TABLE IF NOT EXISTS raw.ticker_profile_load (
    load_id BIGSERIAL PRIMARY KEY,
    -- No FK: history must survive retention deletes of reference.securities.
    security_id UUID NOT NULL,
    ticker VARCHAR(32) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    loader TEXT NOT NULL,
    owned_columns TEXT[] NOT NULL DEFAULT '{}',
    sector TEXT,
    industry TEXT,
    security_type TEXT,
    coupon_type VARCHAR(32),
    coupon_rate NUMERIC,
    fixed_period_end DATE,
    floating_spread NUMERIC,
    tax_status VARCHAR(32),
    call_date DATE,
    liquidation_preference NUMERIC,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_hash TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_raw_ticker_profile_load_security_retrieved
    ON raw.ticker_profile_load (security_id, retrieved_at DESC);

COMMENT ON TABLE raw.ticker_profile_load IS
    'Append-only landing history of every raw.ticker_profile observation, stored as '
    'received. raw.ticker_profile is the latest-per-security projection of this table';
COMMENT ON COLUMN raw.ticker_profile_load.load_id IS 'Surrogate key, monotonically increasing per load';
COMMENT ON COLUMN raw.ticker_profile_load.security_id IS
    'reference.securities.security_id the observation was written for (no FK so history survives deletes)';
COMMENT ON COLUMN raw.ticker_profile_load.ticker IS 'Ticker the observation was fetched for';
COMMENT ON COLUMN raw.ticker_profile_load.provider IS 'Provider label of this single observation';
COMMENT ON COLUMN raw.ticker_profile_load.loader IS
    'Writer that produced the observation (populate_raw_tables, populate_dividend_data, '
    'populate_preferred_profiles, repair_ticker_profile_sec_terms, baseline_v0054)';
COMMENT ON COLUMN raw.ticker_profile_load.owned_columns IS
    'Typed columns this loader is authoritative for; they overwrite raw.ticker_profile, NULL included';
COMMENT ON COLUMN raw.ticker_profile_load.sector IS 'Sector as observed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.industry IS 'Industry as observed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.security_type IS 'Series/security type label as observed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.coupon_type IS 'Coupon type parsed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.coupon_rate IS 'Per-series coupon rate (percent) parsed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.fixed_period_end IS 'Fixed-rate period end parsed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.floating_spread IS 'Floating spread parsed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.tax_status IS 'Dividend tax status parsed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.call_date IS 'Call date parsed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.liquidation_preference IS
    'Per-series liquidation preference parsed in this load';
COMMENT ON COLUMN raw.ticker_profile_load.raw_payload IS
    'Provider envelope exactly as received ({openbb, sec_xbrl, sec_xbrl_scope}); the baseline '
    'rows keep the pre-V0054 payload including legacy top-level keys';
COMMENT ON COLUMN raw.ticker_profile_load.payload_hash IS
    'SHA-256 (md5 for baseline rows) of the canonical payload, for change detection';
COMMENT ON COLUMN raw.ticker_profile_load.retrieved_at IS 'When the observation was written (UTC)';

ALTER TABLE raw.ticker_profile
    ADD COLUMN IF NOT EXISTS field_sources JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN raw.ticker_profile.field_sources IS
    'Column lineage: typed column name -> loader that last set it (see raw.ticker_profile_load.loader)';

-- Baseline snapshot, once, before the payload is normalized.
INSERT INTO raw.ticker_profile_load
    (security_id, ticker, provider, loader, owned_columns, sector, industry,
     security_type, coupon_type, coupon_rate, fixed_period_end, floating_spread,
     tax_status, call_date, liquidation_preference, raw_payload, payload_hash,
     retrieved_at)
SELECT tp.security_id, tp.ticker, tp.provider, 'baseline_v0054',
       ARRAY['sector', 'industry', 'security_type', 'coupon_type', 'coupon_rate',
             'fixed_period_end', 'floating_spread', 'tax_status', 'call_date',
             'liquidation_preference'],
       tp.sector, tp.industry, tp.security_type, tp.coupon_type, tp.coupon_rate,
       tp.fixed_period_end, tp.floating_spread, tp.tax_status, tp.call_date,
       tp.liquidation_preference, tp.raw_payload, md5(tp.raw_payload::text),
       tp.retrieved_at
FROM raw.ticker_profile AS tp
WHERE NOT EXISTS (
    SELECT 1 FROM raw.ticker_profile_load AS l WHERE l.loader = 'baseline_v0054'
);

-- Normalize payloads to the provider envelope.
WITH parts AS (
    SELECT tp.security_id,
           tp.raw_payload AS old_payload,
           COALESCE((
               SELECT jsonb_object_agg(e.key, e.value)
               FROM jsonb_each(tp.raw_payload) AS e(key, value)
               WHERE e.key IN ('sec_xbrl', 'sec_xbrl_scope')
           ), '{}'::jsonb) AS envelope,
           CASE WHEN jsonb_typeof(tp.raw_payload -> 'openbb') = 'object'
                 AND tp.raw_payload -> 'openbb' <> '{}'::jsonb
                THEN tp.raw_payload -> 'openbb' END AS nested_openbb,
           COALESCE((
               SELECT jsonb_object_agg(e.key, e.value)
               FROM jsonb_each(tp.raw_payload) AS e(key, value)
               WHERE e.key NOT IN ('openbb', 'sec_xbrl', 'sec_xbrl_scope')
           ), '{}'::jsonb) AS flat
    FROM raw.ticker_profile AS tp
    WHERE jsonb_typeof(tp.raw_payload) = 'object'
), normalized AS (
    SELECT security_id,
           old_payload,
           envelope || CASE
               WHEN nested_openbb IS NOT NULL THEN jsonb_build_object('openbb', nested_openbb)
               WHEN flat <> '{}'::jsonb THEN jsonb_build_object('openbb', flat)
               ELSE '{}'::jsonb
           END AS new_payload
    FROM parts
)
UPDATE raw.ticker_profile AS tp
SET raw_payload = n.new_payload
FROM normalized AS n
WHERE n.security_id = tp.security_id
  AND n.new_payload IS DISTINCT FROM n.old_payload;

COMMENT ON COLUMN raw.ticker_profile.raw_payload IS
    'Latest provider envelope: {"openbb": <OpenBB/yfinance profile>, "sec_xbrl": <issuer-level '
    'SEC XBRL terms>, "sec_xbrl_scope": "issuer_level_unallocated"}. Each provider object is '
    'replaced wholesale by its latest observation; full history is in raw.ticker_profile_load';
