-- Dividend source policy for preferred.v_security_terms (supersedes the dividend
-- ranking of V0066; columns, order and liquidation/call logic are unchanged).
--
-- Provider evaluation (live warehouse, 2026-10-16):
--   * OPENBB rows are Yahoo Finance listing-level events (the OpenBB default, now
--     pinned in openbb_client.dividends). They carry the true ex-date of the symbol.
--     Freshness: 96.6% of 2,702 securities have a last ex-date within 1.5x their own
--     cadence (mean age 62 days). Accuracy: annual sums match SEC 10-K declared
--     per-share totals within 1% for 83.4% of 897 issuer-years (90.4% within 5%);
--     preferred events match coupon x liquidation / cadence within 1% for 84.2%.
--   * SEC_XBRL rows are filing facts dated to the fiscal PERIOD END, not the
--     ex-date, and lag by a filing cycle: 83.9% fresh (mean age 136 days).
--     PreferredStockDividendsPerShareDeclared is reported per issuer, so when an
--     issuer has several active preferred series it cannot be attributed to one.
--
-- V0066 ranked the SEC common declared concept ahead of OPENBB for non-preferred
-- securities, so 1,593 active dividend common stocks showed a fiscal period-end
-- as their "last ex-date" although a true ex-date was stored. The ranking is now:
--   1. OPENBB (true ex-date) for every security type;
--   2. SEC fallback: CommonStockDividendsPerShareDeclared for non-preferred types;
--      PreferredStockDividendsPerShareDeclared for a preferred series only when its
--      issuer has exactly one active preferred series (otherwise N/A);
--   3. any other stored row for non-preferred types (e.g. the CashPaid aggregate,
--      whose amount stays NULL).
-- The <= 1000 per-share guard and the refusal of common concepts for preferred
-- series are unchanged.

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
    SELECT count(*) AS active_series
    FROM reference.securities o
    WHERE s.security_type = 'preferred stock'
      AND o.cik = s.cik
      AND o.active
      AND o.security_type = 'preferred stock'
) ps ON TRUE
LEFT JOIN LATERAL (
    SELECT d.ex_dividend_date, d.amount, d.provider, d.concept
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
  '(Yahoo Finance) true ex-date first for every type, then the SEC XBRL declared '
  'per-share fallback (preferred only when the issuer has one active series). '
  'Shared by the Screener, Security page and feature window so they cannot disagree.';

COMMENT ON COLUMN preferred.v_security_terms.ex_date IS
  'Date of the selected dividend event. OPENBB (Yahoo Finance) rows are true '
  'ex-dates and always win; SEC XBRL fallback rows are fiscal period-ends (see '
  'ex_date_is_period_end).';
COMMENT ON COLUMN preferred.v_security_terms.dividend_provider IS
  'Provider of the selected dividend event: OPENBB (Yahoo Finance via OpenBB, the '
  'preferred source) or SEC_XBRL (fallback when no OPENBB event is stored).';
COMMENT ON COLUMN preferred.v_security_terms.dividend_concept IS
  'XBRL concept of the selected dividend event; empty for OPENBB rows. A preferred '
  'series accepts only PreferredStockDividendsPerShareDeclared, and only when its '
  'issuer has exactly one active preferred series.';
