-- =====================================================================
-- V0011 fundamentals_leverage_inputs
-- Add the three inputs the leverage ratios need, so the ratios can be
-- computed from evidence instead of retired on the assumption that the
-- data was absent.
--
-- model.features.debt_to_ebitda and interest_coverage were retired with the
-- stated reasons "no D&A/EBITDA in schema" and "no interest expense line in
-- any table" (src/crispdm/features.py RETIRED_FEATURES). Those reasons were
-- accurate about the *materialised columns* and wrong about the *data*:
-- raw.companyfacts.raw_payload retains the complete XBRL payload, and the
-- concepts are present far more often than "no line in any table" implies.
-- Measured over all 9,730 candidates this stage processes, counting every
-- ordered fallback in PERIODIC_FINANCIAL_CONCEPT_TAGS (a security counts as a
-- hit if it reports any one of them):
--
--   D&A                 resolves in 5,999 / 9,730 = 61.7%
--   interest expense    resolves in 6,226 / 9,730 = 64.0%
--   shares outstanding  resolves in 7,633 / 9,730 = 78.4%
--
-- The shares figure is us-gaap only, which is all this extractor reads. A
-- dei-inclusive count is higher (91% on an earlier 1,500-row sample) because
-- dei:EntityCommonStockSharesOutstanding is widely reported, but dei is a
-- separate taxonomy that PERIODIC_FINANCIAL_CONCEPT_TAGS does not read, so
-- quoting that number here would overstate what this migration delivers.
--
-- So the columns are added here and populated from those concepts. They stay
-- NULL where the filer does not report them, which is the honest outcome: the
-- ratio features become computable for a real majority of the universe, and
-- the residual sparsity is reported as a coverage number rather than filled in.
--
-- Deliberately NOT added:
--   * An EBITDA column. EBITDA is a derived measure (operating income + D&A),
--     not a reported fact, and storing a derived value alongside its inputs
--     invites the two to disagree. debt_to_ebitda is computed at feature time
--     from the two inputs.
--   * A market-cap column, for the same reason: it is derived from price and
--     shares outstanding, both of which already exist elsewhere.
--
-- V0003 documented debt_to_ebitda as a feature the schema could not support;
-- V0010 recorded its retirement. V0011 supplies the missing inputs; V0012
-- re-documents the two restored features. The earlier migrations are left in
-- place rather than rewritten, because the retirement was a correct decision
-- about the data that existed at the time and the record of it should stay
-- readable.
--
-- Re-run:  python scripts/populate_fundamentals.py   (DB-only, no network)
--          python scripts/build_features.py
-- =====================================================================

ALTER TABLE fundamentals.periodic_financials
  ADD COLUMN IF NOT EXISTS depreciation_amortization NUMERIC,
  ADD COLUMN IF NOT EXISTS interest_expense NUMERIC,
  ADD COLUMN IF NOT EXISTS shares_outstanding NUMERIC;

COMMENT ON COLUMN fundamentals.periodic_financials.depreciation_amortization IS
  'Depreciation and amortisation for the fiscal period, from us-gaap '
  'DepreciationDepletionAndAmortization with the reported variants as ordered '
  'fallbacks. A flow (duration) amount, not a balance. Together with '
  'operating_income this forms EBITDA; it is stored because it is reported, not '
  'because EBITDA is. NULL when the filer does not disclose it -- roughly a '
  'third of filings -- and never imputed, so a company that reports D&A as one '
  'combined line and one that reports it split are not silently conflated.';

COMMENT ON COLUMN fundamentals.periodic_financials.interest_expense IS
  'Interest expense for the fiscal period, from us-gaap InterestExpense with '
  'InterestExpenseNonoperating and the combined interest-and-debt lines as '
  'ordered fallbacks, because filers present it as either. A flow amount. NULL '
  'when not disclosed. A filer that folds interest into another line is not '
  'recorded as zero interest: the ratio that consumes this reports NULL rather '
  'than an implausibly strong coverage figure.';

COMMENT ON COLUMN fundamentals.periodic_financials.shares_outstanding IS
  'Shares outstanding, from the us-gaap share-count concepts. dei:EntityCommon'
  'StockSharesOutstanding has wider coverage but lives in the dei taxonomy, '
  'which this extractor does not read, so it is not used here. Instant for the '
  'balance-sheet concepts and duration for the weighted-average ones, so it is '
  'resolved per fiscal period on the same vintage basis as every other column. '
  'Stored so equity value becomes derivable from price; no market-cap or '
  'liquidation-discount feature is enabled by it in this migration.';
