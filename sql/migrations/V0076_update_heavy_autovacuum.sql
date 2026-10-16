-- =====================================================================
-- V0076: let autovacuum keep up with the upsert-heavy tables.
--
-- V0074 reserved ~15% of every page on the tables that are rewritten in
-- place, so a HOT update lands on its own page instead of spilling to a new
-- one. Reserving the space is only half the job: the dead tuple versions the
-- updates leave behind still have to be collected, and the fraction left free
-- is only reusable once autovacuum has run and marked the space dead.
--
-- Autovacuum's default trigger is 20% of the table plus 50 rows. On a 9.7M-row
-- table that means it does not start until ~1.94M rows are dead, and a table
-- that is updated a little every night sits well under that line for weeks,
-- quietly filling the 15% reserve until HOT updates spill again. The defaults
-- are sized for small tables; for these they are far too relaxed.
--
-- Scale factor 0.02 makes the two 9.7M-row tables vacuum after ~194k dead
-- tuples instead of ~1.94M -- frequently enough that the reserve is recycled
-- long before it fills, and still far above the point where the scan cost
-- matters. The two smaller tables (1.28M and 0.32M rows) use 0.05: the same
-- concern at a smaller absolute trigger, without making a small table vacuum
-- constantly. ANALYZE follows the same cadence so the planner's row estimates
-- track the updates.
--
-- model.features is tuned for autovacuum here but deliberately not given a
-- fillfactor: the carry-forward guard means unchanged rows are not rewritten,
-- and each run mostly appends new (security_id, as_of_date) rows that are never
-- updated in place, so a write-time reserve would only waste space.
--
-- reloptions are not part of the drift fingerprint; the same settings are
-- declared in sql/schema.sql so a fresh build matches the live tables.
-- =====================================================================

ALTER TABLE raw.market_data SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.02
);

ALTER TABLE model.features SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.02
);

ALTER TABLE fundamentals.periodic_financials SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.05
);

ALTER TABLE raw.dividend_data SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.05
);
