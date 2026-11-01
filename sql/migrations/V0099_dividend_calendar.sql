-- V0099: Dividend calendar and special / return-of-capital flags.
--
-- raw.dividend_data holds dividends once they exist as history. A dividend that
-- is declared but not yet paid, or whose ex-date is still ahead, was invisible to
-- the forward-yield path. raw.dividend_calendar holds the provider's calendar of
-- those, and raw.upcoming_dividends exposes the ones with no history row yet.
--
-- is_special is derived from an explicit 'Special' frequency only ('Irregular' is
-- a cadence, not a one-off). is_return_of_capital is NULL = unknown: no provider
-- feed in use reports it, and FALSE would assert something nobody checked.
BEGIN;

ALTER TABLE raw.dividend_data
  ADD COLUMN IF NOT EXISTS is_special BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS is_return_of_capital BOOLEAN;

COMMENT ON COLUMN raw.dividend_data.is_special IS
  'TRUE when the provider labels the payment Special (a one-off, not part of the regular cadence)';
COMMENT ON COLUMN raw.dividend_data.is_return_of_capital IS
  'TRUE/FALSE when a source states it; NULL when unknown (no feed in use reports it)';

UPDATE raw.dividend_data SET is_special = TRUE
WHERE lower(frequency) = 'special' AND is_special = FALSE;

CREATE TABLE IF NOT EXISTS raw.dividend_calendar (
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  ex_dividend_date DATE NOT NULL,
  declaration_date DATE,
  record_date DATE,
  payment_date DATE,
  amount NUMERIC,
  adjusted_amount NUMERIC,
  dividend_yield NUMERIC,
  frequency VARCHAR(32),
  is_special BOOLEAN NOT NULL DEFAULT FALSE,
  provider VARCHAR(64) NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, ex_dividend_date, provider)
);

CREATE INDEX IF NOT EXISTS dividend_calendar_ex_date_idx
  ON raw.dividend_calendar (ex_dividend_date);

COMMENT ON TABLE raw.dividend_calendar IS
  'Provider dividend calendar: declared and upcoming dividends, including ones not yet in raw.dividend_data';

CREATE OR REPLACE VIEW raw.upcoming_dividends AS
SELECT c.*
FROM raw.dividend_calendar c
WHERE (c.ex_dividend_date >= CURRENT_DATE OR c.payment_date >= CURRENT_DATE)
  AND NOT EXISTS (
    SELECT 1 FROM raw.dividend_data d
    WHERE d.security_id = c.security_id AND d.ex_dividend_date = c.ex_dividend_date
  );

COMMENT ON VIEW raw.upcoming_dividends IS
  'Calendar dividends whose ex-date or payment is still ahead and that have no raw.dividend_data row yet';

COMMIT;
