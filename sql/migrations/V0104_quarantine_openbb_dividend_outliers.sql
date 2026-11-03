-- V0104: Park the absurd OPENBB per-share dividend tail.
--
-- MAX_PER_SHARE_DIVIDEND ($1,000) applies only to the SEC XBRL path because an
-- aggregate-dollar tag can land in a per-share concept. OPENBB/yfinance history
-- is not fully split-restated, so a valid pre-split payment can be tens or
-- hundreds of thousands of dollars per unadjusted share (CMCT ~$205k, SUNE
-- $96k). The defect is the far tail: 65 OPENBB rows above $1M, from CETX at
-- $1.764M through TOPS at $226,799,993,000,000.
--
-- Keep the raw rows as evidence. The shared ceiling in
-- src/crispdm/dividend_limits.py excludes them from feature windows, and the
-- post-nightly check fails on any new unquarantined amount above it.
--
-- The key is (security_id|ex_date|provider), matching raw.dividend_data's
-- primary key. observed_value is the amount the feature build actually uses:
-- adjusted_amount when present, otherwise amount.

BEGIN;

INSERT INTO audit.quarantined_values (
    table_schema, table_name, column_name, row_key,
    cik, ticker, observed_value, reason, rule
)
SELECT
    'raw', 'dividend_data', 'amount',
    concat_ws('|', d.security_id, d.ex_dividend_date, d.provider),
    s.cik, s.ticker,
    COALESCE(d.adjusted_amount, d.amount)::text,
    'OpenBB per-share amount exceeds $1,000,000. A valid pre-split payment can be '
    'tens of thousands of dollars per unadjusted share, but this far tail is a '
    'provider/split artifact; feature annualization excludes it. The raw row is '
    'kept as evidence.',
    'OPENBB_DIVIDEND_AMOUNT_ABSURD'
FROM raw.dividend_data d
JOIN reference.securities s ON s.security_id = d.security_id
WHERE d.provider = 'OPENBB'
  AND COALESCE(d.adjusted_amount, d.amount) > 1000000
ON CONFLICT (table_schema, table_name, column_name, row_key, observed_value)
DO NOTHING;

COMMIT;
