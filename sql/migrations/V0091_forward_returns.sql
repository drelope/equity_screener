-- V0091 forward_returns
--
-- What a holder earned over the window that FOLLOWED a date: the forward 12M total
-- return of every security, for every observation date whose window has closed.
--
-- The investment-analysis worksheet needs this to answer "how did setups like this
-- one turn out?" with a cross-sectional base rate instead of a lookback at one
-- security's own history. The calculation is in src/crispdm/returns.py and mirrors
-- the trailing total return in src/crispdm/features.py, so a forward return and a
-- trailing momentum are measured over comparable spans.
--
-- A forward return is knowable only once its window has closed, so the materialised
-- range ends 252 trading days before the last stored price. That lag is the point:
-- a base rate built from returns that had not happened yet would be a forecast
-- dressed as history.
--
-- The window must be COMPLETE. A partial sum over fewer observations is a valid
-- number that means something else (a 29-day return reported as a year), so
-- window_days records how many daily returns were actually summed, and only full
-- windows are stored.

CREATE TABLE IF NOT EXISTS model.forward_returns (
  security_id      UUID             NOT NULL REFERENCES reference.securities (security_id),
  as_of_date       DATE             NOT NULL,
  forward_date     DATE             NOT NULL,
  window_days      INTEGER          NOT NULL,
  total_return     DOUBLE PRECISION NOT NULL,
  price_return     DOUBLE PRECISION NOT NULL,
  dividend_return  DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (security_id, as_of_date)
);

CREATE INDEX IF NOT EXISTS ix_forward_returns_as_of
  ON model.forward_returns (as_of_date);

COMMENT ON TABLE model.forward_returns IS
  'Forward 12-month returns per security per observation date: what a holder '
  'earned in the 252 trading days after that date, dividends reinvested at the '
  'close of their ex-date. Only complete windows are stored, so the range ends '
  '252 trading days before the last stored price. Built by '
  'scripts.build_forward_returns; read by src/crispdm/analogs.py.';
COMMENT ON COLUMN model.forward_returns.security_id IS
  'Security the forward return belongs to';
COMMENT ON COLUMN model.forward_returns.as_of_date IS
  'First observation date of the forward window; the date the setup is judged from';
COMMENT ON COLUMN model.forward_returns.forward_date IS
  'Last observation date inside the window: the date the forward return is '
  'measured to, which is a trading date rather than a calendar anniversary';
COMMENT ON COLUMN model.forward_returns.window_days IS
  'Number of daily returns actually summed. Always 252 for a stored row, because '
  'a partial sum is a valid number that means something else; recorded so a short '
  'window is visible rather than implied.';
COMMENT ON COLUMN model.forward_returns.total_return IS
  'Forward price return plus dividends, compounded: what a holder earned';
COMMENT ON COLUMN model.forward_returns.price_return IS
  'Forward price return alone, over the same window, so the income and price '
  'contributions can be told apart';
COMMENT ON COLUMN model.forward_returns.dividend_return IS
  'total_return minus price_return: the contribution of dividends over the window';
