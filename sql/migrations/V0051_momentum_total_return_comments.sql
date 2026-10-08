-- V0051 momentum columns are total return as of features_v4
--
-- model.features.momentum_252d and momentum_63d were documented, and computed, as
-- price change: close / close-n minus 1. They are meant to be total return, so a
-- dividend payer is not scored as if its income did not exist. features_v4
-- computes them as the compounded daily total return, crediting each per-payment
-- dividend on its ex-date.
--
-- Comment-only: the columns and their types are unchanged. Rows built before the
-- features_v4 rebuild still hold price momentum, so a stale row is distinguishable
-- only by the build, not by this comment.

BEGIN;

COMMENT ON COLUMN model.features.momentum_252d IS
  'Total return over the trailing 252 trading days: price change plus dividends credited on their ex-dates, compounded; decimal fraction (e.g. 0.10 = 10%). A security with no stored per-payment dividends reads as price return. features_v4; earlier builds hold price change only';

COMMENT ON COLUMN model.features.momentum_63d IS
  'Total return over the trailing 63 trading days: price change plus dividends credited on their ex-dates, compounded; decimal fraction. A security with no stored per-payment dividends reads as price return. features_v4; earlier builds hold price change only';

COMMIT;
