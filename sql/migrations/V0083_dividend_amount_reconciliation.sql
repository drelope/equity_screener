-- Record which feed's amount an OPENBB dividend row carries, and keep the
-- verdicts that settled FMP/Yahoo amount disagreements.
--
-- FMP is the primary dividend feed (V0081), but its amount is not always the right
-- one. A universe audit (2026-10-16, events since 2025-01-01) found 629 of 16,976
-- shared FMP/Yahoo events more than 1% apart. With Polygon.io as a third source,
-- FMP was confirmed on 114 of the disputed events (TSM, IHG, UL, Canadian OTC
-- listings Yahoo converts at a stale FX rate) and Yahoo on 22 (CHA: the issuer 6-K
-- of 2025-11-28 declares US$0.92 per ADS, FMP has 0.87; SAN, EQNR, HTGC). FMP was
-- far off and Yahoo within a few percent of Polygon on ORANY, ABBNY, FORTY, IMOS.
-- The loader now keeps FMP's figure unless Polygon confirms Yahoo's
-- (openbb_client.reconcile_amounts), and caches each verdict here so Polygon's
-- free 5-calls-per-minute budget is spent only on new disagreements.

ALTER TABLE raw.dividend_data ADD COLUMN IF NOT EXISTS amount_feed text;

UPDATE raw.dividend_data SET amount_feed = feed
WHERE provider = 'OPENBB' AND amount_feed IS NULL;

COMMENT ON COLUMN raw.dividend_data.amount_feed IS
  'Feed whose per-share amount an OPENBB row carries: normally the same as feed; '
  'yfinance on an fmp row when FMP and Yahoo disagreed and Polygon confirmed Yahoo '
  '(see raw.dividend_amount_check). NULL for SEC_XBRL rows.';
COMMENT ON COLUMN raw.dividend_data.feed IS
  'Underlying OpenBB provider of an OPENBB row: fmp (as-declared amount, '
  'declaration/record/payment dates) or yfinance (split-adjusted amount only). '
  'NULL for SEC_XBRL rows.';
COMMENT ON COLUMN raw.dividend_data.adjusted_amount IS
  'fmp rows: the declared amount restated by the Yahoo split factors the stored '
  'closes carry (FMP''s own adjDividend misses splits). yfinance rows leave it NULL '
  'because their amount is already restated; consumers that compare dividends with '
  'prices read COALESCE(adjusted_amount, amount).';

CREATE TABLE IF NOT EXISTS raw.dividend_amount_check (
    ticker           text        NOT NULL,
    ex_dividend_date date        NOT NULL,
    fmp_amount       numeric     NOT NULL,
    yahoo_amount     numeric     NOT NULL,
    polygon_amount   numeric,
    polygon_currency text,
    chosen           text        NOT NULL CHECK (chosen IN ('fmp', 'yfinance', 'unresolved')),
    checked_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, ex_dividend_date)
);

COMMENT ON TABLE raw.dividend_amount_check IS
  'One row per FMP dividend event whose amount Yahoo contradicted (beyond 1% or '
  'Yahoo''s 3-decimal rounding, on the declared basis): both figures, Polygon''s '
  'figure and currency, and the feed chosen. unresolved (Polygon had no USD event, '
  'or neither feed was close) keeps FMP; it is re-checked after 7 days unless '
  'Polygon only had a local-currency figure, which a re-check cannot settle.';
