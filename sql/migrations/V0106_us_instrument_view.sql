-- V0106: United States instrument rule, as a view.
--
-- Owner rule: keep a payer when dividend = TRUE and it is a United States instrument,
-- where a US instrument is one that is (1) listed on a US exchange and priced in USD, or,
-- for the OTC venues (PINK/OTC), (2) priced in USD with a US business address in the SEC
-- submissions payload (addresses.business.stateOrCountry).
--
-- It is a view, not a change to reference.securities.dividend: the flag is rewritten by
-- every reference run and is part of the security_id hash, so editing it would not hold.
-- Nothing reads the view yet; it records the rule once, reproducibly, and the audit uses it.
-- 'unknown' (no address on file) is reported separately and never counted as US or non-US.
BEGIN;

CREATE OR REPLACE VIEW reference.v_us_instruments AS
WITH base AS (
  SELECT s.security_id, s.ticker, s.cik, s.security_type, s.dividend, s.active, s.currency,
         e.exchange_code,
         ss.raw_payload->'addresses'->'business'->>'stateOrCountry' AS business_state_or_country
  FROM reference.securities s
  LEFT JOIN reference.exchanges e ON e.exchange_id = s.exchange_id
  LEFT JOIN raw.sec_submissions ss ON ss.cik = s.cik
)
SELECT security_id, ticker, cik, security_type, dividend, active, currency, exchange_code,
       business_state_or_country,
       CASE
         WHEN currency = 'USD' AND exchange_code IN ('NYSE', 'NASDAQ', 'AMEX', 'ARCA', 'BATS')
           THEN 'us_exchange_usd'
         WHEN currency = 'USD' AND business_state_or_country IN (
              'AL','AK','AZ','AR','CA','CO','CT','DE','DC','FL','GA','HI','ID','IL','IN','IA',
              'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM',
              'NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA',
              'WV','WI','WY','PR','GU','VI','AS','MP','X1')
           THEN 'us_business_address'
         WHEN business_state_or_country IS NULL THEN 'unknown'
         ELSE 'non_us'
       END AS us_basis,
       (currency = 'USD' AND (
          exchange_code IN ('NYSE', 'NASDAQ', 'AMEX', 'ARCA', 'BATS')
          OR business_state_or_country IN (
              'AL','AK','AZ','AR','CA','CO','CT','DE','DC','FL','GA','HI','ID','IL','IN','IA',
              'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM',
              'NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA',
              'WV','WI','WY','PR','GU','VI','AS','MP','X1'))) AS is_us_instrument
FROM base;

COMMENT ON VIEW reference.v_us_instruments IS
  'Owner rule: a US instrument is USD-priced and listed on a US exchange (NYSE, NASDAQ, AMEX, ARCA, BATS), or on an OTC venue with a US SEC business address (state code, X1 = United States). us_basis = unknown when no address is on file.';

COMMIT;
