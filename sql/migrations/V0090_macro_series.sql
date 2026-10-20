-- V0090 macro_series
--
-- Economic inputs for docs/GlobalMacroStrategy.md, gathered by
-- scripts.populate_macro_inputs from two OpenBB providers: FMP for the UST
-- curve, VIX, spot metals, ETF closes and ETF sector weights, and FRED for
-- the series FMP does not carry (SOFR, RRP, ICE BofA OAS, breakevens, TIPS
-- real yields, daily WTI/Brent/Henry Hub). `source` records which provider
-- delivered each observation so provenance stays auditable.
--
-- Rate-like values are stored in percent (SOFR 3.89, IG OAS 0.83), prices in
-- the quote currency, VIX in index points; `unit` states which per series.
-- These rows are SUPPORTING context for the macro strategy worksheet only:
-- they never feed the model feature build.

CREATE TABLE IF NOT EXISTS raw.macro_series (
  series_id VARCHAR(64) NOT NULL,
  observation_date DATE NOT NULL,
  value NUMERIC NOT NULL,
  unit VARCHAR(32) NOT NULL,
  source VARCHAR(16) NOT NULL,
  provider VARCHAR(64) NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (series_id, observation_date)
);

COMMENT ON TABLE raw.macro_series IS
  'One scalar economic observation per series per date (UST tenors, VIX, spot '
  'metals, ETF closes, SOFR, OAS, breakevens, energy prices) for '
  'docs/GlobalMacroStrategy.md. Supporting data only; not read by the model '
  'feature build.';
COMMENT ON COLUMN raw.macro_series.series_id IS
  'Stable series key from src/crispdm/macro_inputs.py (UST_2Y, VIX, GOLD_SPOT, '
  'SOFR, HY_OAS, PFF, ...).';
COMMENT ON COLUMN raw.macro_series.unit IS
  'percent for rates/spreads/breakevens, USD (or USD per unit) for prices, '
  'index points for VIX, billions USD for the RRP balance.';
COMMENT ON COLUMN raw.macro_series.source IS
  'FMP or FRED, whichever provider delivered the observation.';

CREATE TABLE IF NOT EXISTS raw.macro_etf_sectors (
  symbol VARCHAR(16) NOT NULL,
  sector VARCHAR(64) NOT NULL,
  weight NUMERIC NOT NULL,
  source VARCHAR(16) NOT NULL DEFAULT 'FMP',
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, sector)
);

COMMENT ON TABLE raw.macro_etf_sectors IS
  'Sector weights of the preferred/dividend benchmark ETFs (PFF, PGX, SDY) so '
  'a proxy can state its concentration - especially financials - before use, '
  'as docs/GlobalMacroStrategy.md requires. Sector totals are per provider '
  'snapshot, not point-in-time historical.';
COMMENT ON COLUMN raw.macro_etf_sectors.weight IS
  'Fraction of fund assets in the sector (0.62 = 62%).';
