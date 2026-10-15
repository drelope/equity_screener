-- =====================================================================
-- V0071: index raw.market_data by observation_date for date-window scans.
--
-- raw.market_data is keyed (security_id, observation_date, provider). A
-- predicate on observation_date alone therefore cannot be served by the
-- primary-key btree: PostgreSQL does not skip-scan a non-leading column
-- (that arrives in 18), so the planner falls back to reading the whole
-- 836 MB primary-key index, or to a sequential scan of the 3 GB table.
--
-- Every access that keys on the date rather than on a security does that:
--
--   * the feature build runs, once per window and four times per build,
--       SELECT DISTINCT security_id, observation_date FROM raw.market_data
--       WHERE close IS NOT NULL
--         AND observation_date >= <window start>
--         AND observation_date <  <window end>      (src/crispdm/features.py);
--   * scripts/build_features.py sizes each build window with
--       SELECT min(observation_date), max(observation_date)
--       FROM raw.market_data WHERE close IS NOT NULL
--
-- The index is partial on close IS NOT NULL and includes security_id, so the
-- DISTINCT probe is answered by an index-only scan and min/max become index
-- endpoints. Measured against the live table (2026-10-15):
--
--   window      before                              after
--   1 day       423 ms, 109,275 buffers            2.6 ms, 43 buffers
--   365 days    2301 ms, 287,370 buffers (seq)     1618 ms, 9,676 buffers
--
-- Plain CREATE INDEX, not CONCURRENTLY: migrations run one transaction per
-- file so CONCURRENTLY is unavailable, and this is a single ACCESS EXCLUSIVE
-- pass over the largest raw table. Idempotent; the same statement is declared
-- in sql/schema.sql so a fresh build and this migration converge.
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_market_data_observation_date
  ON raw.market_data (observation_date)
  INCLUDE (security_id)
  WHERE close IS NOT NULL;
