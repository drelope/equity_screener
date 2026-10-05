-- V0037 features_as_of_index
--
-- Index model.features(as_of_date DESC) so MAX(as_of_date) is an index probe.
--
-- Every consumer that picks "the latest feature date" -- the scoring run, the
-- dashboard, the verifier -- reads MAX(as_of_date) FROM model.features, and with
-- no index on that column each one pays a parallel sequential scan of the whole
-- table. model.features holds 8.5M rows, so that is ~500ms per lookup and
-- ~1.07M buffers read, repeated for every query that needs the bound twice.
--
-- This surfaced while adding the carry-forward window: expressing the window as
-- a correlated MAX over the feature table was 28s and 42.7M buffer hits, and
-- even after rewriting it as a per-security LATERAL ... ORDER BY as_of_date DESC
-- LIMIT 1 the two MAX lookups were the remaining cost. Descending because the
-- only query shape is MAX, which the planner can satisfy from the leading edge.
--
-- Index only, no data change: this is a read-path optimisation and must not
-- alter which rows any query returns.

CREATE INDEX IF NOT EXISTS idx_features_as_of
    ON model.features (as_of_date DESC);
