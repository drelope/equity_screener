-- =====================================================================
-- V0029 dividend_recency
-- Bound the dividend flag on the recency of its evidence.
--
-- classify_companyfacts() previously set reference.securities.dividend from
-- the mere presence of a positive us-gaap dividend fact. SEC XBRL Company
-- Facts retain every fact an issuer has ever filed, including comparative
-- columns from long-past periods, so a single stale positive fact kept a
-- long-defunct or acquired issuer inside the dividend universe indefinitely.
--
-- The classifier now ignores dividend facts whose period end falls outside a
-- 548-day window (DIVIDEND_RECENCY_DAYS, the same horizon the preferred
-- dividend snapshot uses) and records the qualifying period end so the flag is
-- auditable rather than a bare boolean.
--
-- No backfill: the qualifying fact period end has to be recomputed from
-- raw.companyfacts by re-running populate_reference_tables --stage reference,
-- because XBRL evidence does not survive a SQL-only projection of the payload.
-- Existing rows keep their current dividend value until that stage runs, so
-- this migration is additive and safe to apply on its own.
-- =====================================================================

ALTER TABLE reference.securities
  ADD COLUMN IF NOT EXISTS dividend_last_paid DATE;

COMMENT ON COLUMN reference.securities.dividend IS
  'Whether SEC evidence indicates that the security pays a dividend. '
  'Requires a positive dividend fact whose period ends within the recency '
  'window (DIVIDEND_RECENCY_DAYS, 548 days) before the classification date; '
  'XBRL retains stale comparative facts that would otherwise keep defunct '
  'issuers in the universe';

COMMENT ON COLUMN reference.securities.dividend_last_paid IS
  'Period end (end date) of the most recent positive dividend fact that '
  'qualified reference.securities.dividend, or NULL when not a current payer';