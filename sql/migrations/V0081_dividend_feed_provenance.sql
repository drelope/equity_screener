-- Record which OpenBB provider supplied each OPENBB dividend row, and expose it on
-- preferred.v_security_terms.
--
-- raw.dividend_data.provider stays 'OPENBB' for every listing-level event (features,
-- labels, cadence and the V0080 source policy all key on it). Since the FMP plan was
-- upgraded (2026-10-16) the loader asks FMP first and falls back to Yahoo Finance per
-- symbol, so the provider alone no longer says where a row came from. On a 120-
-- security sample FMP and Yahoo agreed on 738 of 749 ex-dates; FMP's amount is the
-- as-declared figure (WLFC 0.40, RUSHA 0.19 match the SEC 10-K) and its
-- adjusted_amount equals Yahoo's split-adjusted amount, and FMP adds declaration,
-- record and payment dates plus announced future ex-dates.
--
-- Every OPENBB row stored before this migration came from yfinance: no provider
-- credentials existed, and openbb_client pinned yfinance (V0080 evaluation).

ALTER TABLE raw.dividend_data ADD COLUMN IF NOT EXISTS feed text;

UPDATE raw.dividend_data SET feed = 'yfinance' WHERE provider = 'OPENBB' AND feed IS NULL;

COMMENT ON COLUMN raw.dividend_data.feed IS
  'Underlying OpenBB provider of an OPENBB row: fmp (as-declared amount, '
  'split-adjusted adjusted_amount, declaration/record/payment dates) or yfinance '
  '(split-adjusted amount only). NULL for SEC_XBRL rows.';
COMMENT ON COLUMN raw.dividend_data.adjusted_amount IS
  'Split-adjusted per-share amount when the feed supplies one (fmp). yfinance rows '
  'leave it NULL because their amount is already split-adjusted; consumers that '
  'compare dividends with split-adjusted prices read COALESCE(adjusted_amount, amount).';

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
    dd.concept AS dividend_concept,
    dd.feed AS dividend_feed
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
    SELECT count(*) AS active_series
    FROM reference.securities o
    WHERE s.security_type = 'preferred stock'
      AND o.cik = s.cik
      AND o.active
      AND o.security_type = 'preferred stock'
) ps ON TRUE
LEFT JOIN LATERAL (
    SELECT d.ex_dividend_date, d.amount, d.provider, d.concept, d.feed
    FROM raw.dividend_data d
    WHERE d.security_id = s.security_id
      AND (
            s.security_type <> 'preferred stock'
            OR d.provider = 'OPENBB'
            OR (
                d.concept = 'PreferredStockDividendsPerShareDeclared'
                AND ps.active_series = 1
            )
          )
      AND (d.amount IS NULL OR d.amount <= 1000)
    ORDER BY
        CASE
            WHEN d.provider = 'OPENBB' THEN 0
            WHEN d.concept IN (
                'CommonStockDividendsPerShareDeclared',
                'PreferredStockDividendsPerShareDeclared'
            ) THEN 1
            ELSE 2
        END,
        d.ex_dividend_date DESC NULLS LAST
    LIMIT 1
) dd ON TRUE;

COMMENT ON VIEW preferred.v_security_terms IS
  'Per-security preferred terms (liquidation preference, first call/call price) and '
  'the most-recent dividend event under the V0080 source policy: the OPENBB '
  'listing-level ex-date first for every type (FMP, Yahoo Finance fallback; see '
  'dividend_feed), then the SEC XBRL declared per-share fallback (preferred only when '
  'the issuer has one active series). An FMP event may be an announced future '
  'ex-date. Shared by the Screener, Security page and feature window.';
COMMENT ON COLUMN preferred.v_security_terms.dividend_amount IS
  'As-declared per-share amount of the selected dividend event (FMP rows; yfinance '
  'rows are split-adjusted). The CommonStockDividendsPerShareCashPaid annual '
  'aggregate is NULLed rather than shown as per-share.';
COMMENT ON COLUMN preferred.v_security_terms.dividend_feed IS
  'OpenBB provider behind an OPENBB dividend event (fmp or yfinance); NULL for '
  'SEC XBRL fallback rows.';
