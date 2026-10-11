-- V0056: Record provider fields whose numeric value was non-finite.
--
-- OpenBB/yfinance emits Infinity/NaN (as JSON strings) for ratios such as
-- trailing_p_e and price_to_sales. PostgreSQL NUMERIC accepts 'Infinity' and
-- 'NaN', which silently poisons aggregates. The flattener now stores NULL in
-- the typed column and lists the field here; the original value stays in
-- source_payload.

ALTER TABLE clean.company_profile
  ADD COLUMN IF NOT EXISTS non_finite_fields TEXT[] NOT NULL DEFAULT '{}'::text[];

COMMENT ON COLUMN clean.company_profile.non_finite_fields IS
  'Typed numeric columns whose provider value was Infinity/-Infinity/NaN and was loaded as NULL; raw value kept in source_payload';
