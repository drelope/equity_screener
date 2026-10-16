-- =====================================================================
-- V0074: reserve in-page space on the update-heavy tables (fillfactor).
--
-- The 2026-10-15 efficiency audit found these tables ~50% free space with
-- negligible dead tuples. The cause is not dead rows left by autovacuum:
-- it is that these tables are upserted heavily (raw.market_data has seen 34M
-- updates over 9.7M rows) and were created at the default fillfactor of 100,
-- so every HOT update that did not fit on its page spilled to a new one. Over
-- time the old pages were drained of their live tuples and never refilled:
-- raw.market_data measured 46.3% free before a one-time VACUUM FULL.
--
-- fillfactor is the percentage of a page a rewrite (VACUUM FULL / CLUSTER) or
-- insert-split fills before leaving the rest free. Setting it to 85 leaves
-- roughly 15% of each page for HOT updates to land in, so they reuse the page
-- instead of growing the heap. The one-time reclaim already happened; this
-- makes it durable rather than something to repeat.
--
-- The value takes effect the next time each table is rewritten; it does not
-- rewrite anything now. If a table is not HOT-updated (an indexed column
-- changes on every write) the reserved space is simply unused, which is why
-- 85 and not something more aggressive.
--
-- reloptions are not part of the drift fingerprint, so this needs no
-- ACCEPTED_DIFFERENCES entry; the same WITH (fillfactor = 85) clauses are
-- declared in sql/schema.sql so a fresh build matches the live tables.
-- =====================================================================

ALTER TABLE raw.market_data SET (fillfactor = 85);
ALTER TABLE fundamentals.periodic_financials SET (fillfactor = 85);
ALTER TABLE raw.dividend_data SET (fillfactor = 85);
ALTER TABLE reference.securities SET (fillfactor = 85);
