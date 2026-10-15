-- One per-security place for the "terms" the Screener and the Security detail page
-- both read: liquidation preference, first call date / call price, and the most
-- recent dividend event with its ex-date and per-share amount.
--
-- The two consumers used to resolve these independently, and disagreed:
--   * dashboard_features_sql took liquidation from preferred.issuer_terms FIRST
--     (issuer_liquidation_or_par_value), which mixes per-share preferences, nominal
--     par values (often < $10) and issuer-level AGGREGATE totals across all classes.
--     The Security page read only reference.securities.liquidation_preference.
--   * the dividend pick ignored the XBRL concept, so most preferred series resolved
--     to CommonStockDividendsPerShareDeclared (the ISSUER's common dividend) or to a
--     CashPaid annual aggregate.
--
-- This view resolves both once, per security, so the pages cannot drift again.
--
-- Liquidation preference: PER-SERIES evidence only -- the governing document
-- (preferred.contract_terms) then the per-series XBRL snapshot
-- (preferred.security_terms) -- guarded to a plausible per-share range
-- [1, 1000]. Issuer-level par/aggregate (preferred.issuer_terms) is deliberately
-- NOT a source: it is not attributable to one series. When no per-series value
-- exists the column is NULL, which the pages render as N/A rather than a wrongly
-- precise number (accuracy over coverage).
--
-- Dividend event: the stored concept and provider now decide the row.
--   * preferred stock: an OPENBB row (a true ex-date for that symbol) is preferred;
--     otherwise the per-share PreferredStockDividendsPerShareDeclared concept. The
--     issuer's common-stock concepts are refused, so a preferred with only common
--     evidence shows N/A instead of the issuer's common dividend.
--   * other types: the declared common per-share concept, then OPENBB, then the rest.
--   * CommonStockDividendsPerShareCashPaid is an annual aggregate, not a per-share
--     amount, so it is excluded from the amount (the ex-date may still be shown).
--
-- ex_date_is_period_end marks SEC XBRL dates: fact.end is the fiscal period-end,
-- not the ex-date; only OPENBB carries the true ex-date.

CREATE OR REPLACE VIEW preferred.v_security_terms AS
SELECT
    s.security_id,
    liq.liquidation_preference,
    liq.liquidation_source,
    COALESCE(ct.first_call_date, s.call_date) AS first_call_date,
    ct.call_price,
    CASE
        WHEN ct.first_call_date IS NOT NULL THEN 'preferred.contract_terms'
        WHEN s.call_date IS NOT NULL THEN 'reference.securities'
    END AS call_source,
    dd.ex_dividend_date AS ex_date,
    (dd.provider IS NOT NULL AND dd.provider <> 'OPENBB') AS ex_date_is_period_end,
    CASE
        WHEN dd.concept = 'CommonStockDividendsPerShareCashPaid' THEN NULL
        ELSE dd.amount
    END AS dividend_amount,
    dd.provider AS dividend_provider,
    dd.concept AS dividend_concept
FROM reference.securities s
LEFT JOIN preferred.contract_terms ct ON ct.security_id = s.security_id
LEFT JOIN preferred.security_terms st ON st.security_id = s.security_id
LEFT JOIN LATERAL (
    SELECT v.value AS liquidation_preference, v.source AS liquidation_source
    FROM (VALUES
        (ct.liquidation_preference, 'preferred.contract_terms'),
        (st.liquidation_preference, 'preferred.security_terms')
    ) AS v(value, source)
    WHERE s.security_type = 'preferred stock'
      AND v.value IS NOT NULL
      AND v.value >= 1
      AND v.value <= 1000
    ORDER BY v.source
    LIMIT 1
) liq ON TRUE
LEFT JOIN LATERAL (
    SELECT d.ex_dividend_date, d.amount, d.provider, d.concept
    FROM raw.dividend_data d
    WHERE d.security_id = s.security_id
      AND (
            s.security_type <> 'preferred stock'
            OR d.provider = 'OPENBB'
            OR d.concept = 'PreferredStockDividendsPerShareDeclared'
            OR COALESCE(d.concept, '') = ''
          )
      AND (d.amount IS NULL OR d.amount <= 1000)
    ORDER BY
        CASE
            WHEN s.security_type = 'preferred stock' AND d.provider = 'OPENBB' THEN 0
            WHEN s.security_type = 'preferred stock' THEN 1
            WHEN d.concept = 'CommonStockDividendsPerShareDeclared' THEN 0
            WHEN d.provider = 'OPENBB' THEN 1
            ELSE 2
        END,
        d.ex_dividend_date DESC NULLS LAST
    LIMIT 1
) dd ON TRUE;

COMMENT ON VIEW preferred.v_security_terms IS
  'Per-security preferred terms (liquidation preference, first call/call price) and '
  'the class-aware most-recent dividend event (ex-date, per-share amount, provider, '
  'concept). Resolves the joined lookups the Screener and Security detail page used '
  'to compute separately, so they cannot disagree. Liquidation is per-series only '
  'and range-guarded; issuer-level par/aggregate evidence is never used.';

COMMENT ON COLUMN preferred.v_security_terms.liquidation_preference IS
  'Per-share liquidation preference. Per-series evidence only: the governing '
  'document (preferred.contract_terms) then the XBRL snapshot '
  '(preferred.security_terms), guarded to [1, 1000]. NULL when no per-series value '
  'is known; render as N/A rather than substituting issuer-level par or aggregate.';
COMMENT ON COLUMN preferred.v_security_terms.liquidation_source IS
  'Which per-series table supplied liquidation_preference '
  '(preferred.contract_terms or preferred.security_terms).';
COMMENT ON COLUMN preferred.v_security_terms.first_call_date IS
  'Earliest date the issuer may redeem: the governing document first_call_date, '
  'falling back to reference.securities.call_date.';
COMMENT ON COLUMN preferred.v_security_terms.call_price IS
  'Optional redemption call price at the first call date, per share '
  '(preferred.contract_terms.call_price).';
COMMENT ON COLUMN preferred.v_security_terms.call_source IS
  'Which source supplied first_call_date (preferred.contract_terms or '
  'reference.securities).';
COMMENT ON COLUMN preferred.v_security_terms.ex_date IS
  'Date of the selected dividend event. OPENBB rows are true ex-dates; SEC XBRL '
  'rows are fiscal period-ends (see ex_date_is_period_end).';
COMMENT ON COLUMN preferred.v_security_terms.ex_date_is_period_end IS
  'True when ex_date is an SEC XBRL fiscal period-end rather than a true ex-date '
  '(only OPENBB rows carry true ex-dates).';
COMMENT ON COLUMN preferred.v_security_terms.dividend_amount IS
  'Per-share amount of the selected dividend event. CommonStockDividendsPerShareCashPaid '
  'is an annual aggregate, so its amount is NULLed rather than shown as per-share.';
COMMENT ON COLUMN preferred.v_security_terms.dividend_provider IS
  'Provider of the selected dividend event (OPENBB or SEC_XBRL).';
COMMENT ON COLUMN preferred.v_security_terms.dividend_concept IS
  'XBRL concept of the selected dividend event; empty for OPENBB rows. Used to keep '
  'preferred series off the issuer common-stock dividend concepts.';
