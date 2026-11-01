-- V0103: Keep announcement history on raw.dividend_calendar.
--
-- The calendar loader upserted rows in place, so what was known on a past date
-- could not be reconstructed: a dividend announced on day D looked the same as one
-- seen on day D+30. first_seen_at records when a (security, ex-date) first appeared
-- and last_changed_at when its amount or dates last changed, so a forward-yield
-- feature can later be tested point-in-time ("only dividends first seen by D").
--
-- Rows that predate this column get the migration time as first_seen_at. That is an
-- upper bound on the true first sighting, never earlier, so using it cannot leak.
BEGIN;

ALTER TABLE raw.dividend_calendar
  ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS last_changed_at TIMESTAMPTZ NOT NULL DEFAULT now();

COMMENT ON COLUMN raw.dividend_calendar.first_seen_at IS
  'When this (security, ex-date) first appeared in the calendar; never updated. Rows loaded before V0103 carry the migration time (an upper bound)';
COMMENT ON COLUMN raw.dividend_calendar.last_changed_at IS
  'When amount, declaration, record or payment date last changed';

COMMIT;
