-- V0035 classification_cache_dividend_last_paid
--
-- Add dividend_last_paid to the raw.company_classification cache.
--
-- classify_companyfacts() has always returned dividend_last_paid (the latest
-- period end among positive in-window dividend facts, sec_client.py), and
-- populate_securities writes it to reference.securities. But the cache table
-- that stage reads from had no such column, so the cache branch of
-- populate_securities rebuilt the classification dict without the key and
-- classification.get("dividend_last_paid") returned None for every cached CIK.
-- The value was therefore written as NULL for all 6,012 active dividend payers
-- and could not be recovered by re-running the stage: the companyfacts
-- recompute path is guarded by `if row["cik"] not in cached_ciks`, so cached
-- issuers never reached it. A plain stage re-run would have left the column
-- NULL for every payer.
--
-- This column closes that path so the cached branch carries the same key the
-- fresh path already produced. It is a DATE because the source is an XBRL
-- period-end string, not a timestamp.
--
-- Backfill of both this column and reference.securities.dividend_last_paid is
-- derived from the already-persisted dividend_facts JSONB, which retains the
-- same positive records classify_companyfacts() used, so the backfill agrees
-- with the dividend flag rather than introducing a second source of truth.

ALTER TABLE raw.company_classification
    ADD COLUMN IF NOT EXISTS dividend_last_paid DATE;

COMMENT ON COLUMN raw.company_classification.dividend_last_paid IS
  'Latest XBRL period end among positive dividend facts, from '
  'classify_companyfacts(). Carried so the cached branch of '
  'populate_securities can populate reference.securities.dividend_last_paid.';
