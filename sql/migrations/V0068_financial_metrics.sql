-- =====================================================================
-- V0068 financial_metrics
-- Point-in-time margins, cash-flow quality, balance-sheet and valuation
-- ratios, plus the GrossProfit subtotal they need.
--
-- Why this migration exists
-- ------------------------
-- The feature table answered "can this dividend be paid?" (payout, coverage,
-- leverage) but not "what kind of business is paying it?". Two issuers on the
-- same 5% yield and the same 60% payout look identical to the current model
-- whether one turns 40% of revenue into gross profit and the other turns 8%,
-- or whether one collects its earnings in cash and the other books them as
-- receivables. Those are the distinctions a dividend analyst reaches for
-- first, and none of them were materialised.
--
-- The valuation side had the mirror problem: scoring.py hardcodes
-- valuation_score = 0.5 as a placeholder (docs/requirements.md section 3), so
-- the 5-15% valuation weight in every regime is a constant. Nothing here fixes
-- that in this migration -- scoring is Phase 2 -- but the inputs a real
-- valuation score needs (a point-in-time P/E, earnings yield, FCF yield,
-- price-to-book) are what this migration makes available.
--
-- Why these come from vintage fundamentals, not the provider snapshot
-- ------------------------------------------------------------------
-- clean.company_profile already carries trailing_p_e, price_to_book,
-- profit_margins and the rest at 40-99% coverage. It is deliberately NOT used.
-- It is a single current snapshot (source_retrieved_at fixed at the run date),
-- so joining it to a 2018 as_of_date would put today's P/E into a past row --
-- the exact look-ahead that retired data_quality_score
-- (features.py:76-79). Every value below is derived from
-- fundamentals.periodic_financials rows selected by `filed <= as_of_date`, the
-- same point-in-time discipline as eps_ttm and fcf_ttm. The provider snapshot
-- remains the display-only source in the UI, where "today" is the correct date.
--
-- Why a migration and not only schema.sql
-- ---------------------------------------
-- V0001 is a baseline marker, not replayed DDL: schema.sql only reaches a
-- brand-new database. An established warehouse gets columns from migrations
-- alone (V0012, V0016). Both are updated here, but this file is what the live
-- database actually receives.
--
-- Guarding
-- --------
-- Every ratio is NULL when its denominator is absent or non-positive, and no
-- leg is coalesced to zero. A filer that reports no revenue has no margin, not
-- a zero one; a loss-making issuer has no P/E, not a negative one. The rules
-- are implemented once in features.py financial_metrics() and documented per
-- column below. `net_debt` is the one member that is a level rather than a
-- ratio; it needs both legs reported, because treating a missing cash balance
-- as zero would inflate net debt and treating a missing debt balance as zero
-- would fabricate net cash.
-- =====================================================================

-- The GrossProfit subtotal. Read only from the direct GrossProfit tag: a filer
-- reporting CostOfRevenue but not the gross subtotal keeps a NULL gross profit
-- rather than a derived one, because subtracting a separately tagged cost line
-- across mixed period lengths (a quarterly cost against a YTD revenue) would
-- manufacture a figure the filer never stated.
ALTER TABLE fundamentals.periodic_financials
  ADD COLUMN IF NOT EXISTS gross_profit NUMERIC;

COMMENT ON COLUMN fundamentals.periodic_financials.gross_profit IS
  'Gross profit over the fiscal period (us-gaap GrossProfit). Stored because it '
  'is reported; the gross_margin ratio is derived at feature time. NULL where '
  'the filer does not tag the gross subtotal -- absence of a tag is not a zero '
  'margin.';

-- The materialised ratios on model.features. All sixteen are nullable; a NULL
-- is the honest answer for an undefined ratio and doubles as the coverage
-- signal the score_rank report reads.
ALTER TABLE model.features
  ADD COLUMN IF NOT EXISTS gross_margin NUMERIC,
  ADD COLUMN IF NOT EXISTS operating_margin NUMERIC,
  ADD COLUMN IF NOT EXISTS net_margin NUMERIC,
  ADD COLUMN IF NOT EXISTS fcf_margin NUMERIC,
  ADD COLUMN IF NOT EXISTS ocf_margin NUMERIC,
  ADD COLUMN IF NOT EXISTS cash_conversion NUMERIC,
  ADD COLUMN IF NOT EXISTS capex_intensity NUMERIC,
  ADD COLUMN IF NOT EXISTS fcf_growth NUMERIC,
  ADD COLUMN IF NOT EXISTS net_debt NUMERIC,
  ADD COLUMN IF NOT EXISTS net_debt_to_ebitda NUMERIC,
  ADD COLUMN IF NOT EXISTS current_ratio NUMERIC,
  ADD COLUMN IF NOT EXISTS debt_to_equity NUMERIC,
  ADD COLUMN IF NOT EXISTS pe_ratio NUMERIC,
  ADD COLUMN IF NOT EXISTS earnings_yield NUMERIC,
  ADD COLUMN IF NOT EXISTS fcf_yield NUMERIC,
  ADD COLUMN IF NOT EXISTS price_to_book NUMERIC;

COMMENT ON COLUMN model.features.gross_margin IS
  'TTM gross profit over TTM revenue. The cost structure at the top of the '
  'P&L. NULL when revenue is absent or non-positive, or gross profit is not '
  'tagged.';
COMMENT ON COLUMN model.features.operating_margin IS
  'TTM operating income over TTM revenue. The operating cost structure, before '
  'interest and tax. NULL when revenue is absent or non-positive.';
COMMENT ON COLUMN model.features.net_margin IS
  'TTM net income over TTM revenue. The bottom line as a share of sales. NULL '
  'when revenue is absent or non-positive; a negative margin is reported as '
  'the filer''s actual loss rather than suppressed.';
COMMENT ON COLUMN model.features.fcf_margin IS
  'TTM free cash flow over TTM revenue. How much of each sales dollar survives '
  'to fund the dividend. NULL when revenue is absent or non-positive.';
COMMENT ON COLUMN model.features.ocf_margin IS
  'TTM operating cash flow over TTM revenue. The cash margin before capital '
  'spending. NULL when revenue is absent or non-positive.';
COMMENT ON COLUMN model.features.cash_conversion IS
  'TTM operating cash flow over TTM net income: how fully accounting profit is '
  'collected in cash. NULL unless net income is positive -- a loss gives a '
  'meaningless or sign-flipped quotient.';
COMMENT ON COLUMN model.features.capex_intensity IS
  'TTM capital expenditures over TTM revenue. Capital-hungry issuers have less '
  'cash free for the dividend at a given margin. NULL when revenue is absent or '
  'non-positive.';
COMMENT ON COLUMN model.features.fcf_growth IS
  'TTM free cash flow over the prior TTM free cash flow, minus one. NULL unless '
  'the prior base is positive, the same guard eps_ttm_growth uses; a negative '
  'base has no meaningful growth rate.';
COMMENT ON COLUMN model.features.net_debt IS
  'Total debt less cash and short-term investments, a level not a ratio. '
  'Negative for a net-cash issuer. NULL unless both debt and cash are reported; '
  'neither a missing balance is filled with zero.';
COMMENT ON COLUMN model.features.net_debt_to_ebitda IS
  'Net debt over TTM EBITDA (operating income plus depreciation and '
  'amortisation). NULL unless EBITDA is positive. Complements the gross '
  'debt_to_ebitda already in the table.';
COMMENT ON COLUMN model.features.current_ratio IS
  'Current assets over current liabilities: short-term solvency. Both legs are '
  'the current-basis subtotals V0016 added. NULL unless current liabilities are '
  'positive.';
COMMENT ON COLUMN model.features.debt_to_equity IS
  'Total debt over total equity. NULL unless equity is positive; a '
  'negative-equity issuer has no meaningful debt-to-equity.';
COMMENT ON COLUMN model.features.pe_ratio IS
  'Price over TTM earnings per share. The price the market pays per dollar of '
  'trailing earnings. NULL unless EPS is positive -- a loss has no P/E.';
COMMENT ON COLUMN model.features.earnings_yield IS
  'TTM earnings per share over price, the reciprocal of pe_ratio kept as its '
  'own column because a screen sorts on either and the inverse of a ratio is '
  'not the ratio. NULL unless price and EPS are positive.';
COMMENT ON COLUMN model.features.fcf_yield IS
  'TTM free cash flow over market capitalisation (price times shares '
  'outstanding). The cash return on the whole company, from the point-in-time '
  'share count. NULL unless market capitalisation is positive.';
COMMENT ON COLUMN model.features.price_to_book IS
  'Price over book value per share, i.e. market capitalisation over total '
  'equity. NULL unless equity is positive.';

-- No backfill. Every ratio would have to come from a full fundamentals rebuild
-- (gross_profit is NULL until the next ETL pass populates it), and a
-- backfilled column cannot be told apart from a measured one. The columns and
-- their guards ship together; the next build_features window fills them.
