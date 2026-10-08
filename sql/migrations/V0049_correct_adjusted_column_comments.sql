-- V0049 correct the comments on the never-populated adjusted columns
--
-- raw.market_data.adjusted_close was documented as "used for return
-- calculations". It is NULL in all 9,274,415 rows and nothing reads it:
-- src/crispdm/features.py and scripts/build_features.py compute returns and
-- volatility from raw.market_data.close. The writers look for an adjusted_close
-- or adj_close field, but the OpenBB yfinance price frame carries neither (it
-- only takes an `adjustment` setting, default "splits_only"), so the column can
-- not fill through the current provider path.
--
-- raw.dividend_data.adjusted_amount is likewise NULL in every row and unread.
--
-- Comment-only change: the columns stay, so a provider that does return an
-- adjusted series can populate them without a schema change.

BEGIN;

COMMENT ON COLUMN raw.market_data.adjusted_close IS
  'Provider adjusted close; currently always NULL (the OpenBB yfinance frame has no such field) and not read by any consumer. Returns are computed from close, which the provider splits-adjusts by default; provider data, not an XBRL fact';

COMMENT ON COLUMN raw.dividend_data.adjusted_amount IS
  'Provider split-adjusted per-share dividend; currently always NULL and not read by any consumer. Use amount';

COMMIT;
