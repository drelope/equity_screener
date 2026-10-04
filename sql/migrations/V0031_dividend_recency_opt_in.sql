-- Document that dividend-recency enforcement is opt-in.
--
-- V0029 bounded reference.securities.dividend to recent positive facts and
-- V0030 re-commented the column. Enforcement is now controlled by
-- settings.enforce_dividend_recency (env ENFORCE_DIVIDEND_RECENCY, default
-- False) so an unattended nightly ETL cannot silently change the dividend
-- universe; the 548-day bound applies only when an operator opts in.
--
-- Comment-only: no column, data, or flag value changes. Safe to apply on its
-- own at any time.
COMMENT ON COLUMN reference.securities.dividend IS
  'Whether SEC evidence indicates that the security pays a dividend. When '
  'ENFORCE_DIVIDEND_RECENCY is enabled, requires a positive dividend fact '
  'whose period ends within DIVIDEND_RECENCY_DAYS (548) of the classification '
  'date; off by default to preserve the historical any-positive-fact rule.';
COMMENT ON COLUMN reference.securities.dividend_last_paid IS
  'Period end of the most recent positive dividend fact that qualified '
  'reference.securities.dividend, or NULL when the security is not a '
  'flagged payer';
