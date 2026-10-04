-- V0003 documented debt_to_ebitda, interest_coverage, liquidation_discount,
-- legal_rights_score and data_quality_score as "NULL until populated", which
-- implied a future build would fill them in. src.crispdm.features.RETIRED_FEATURES
-- since recorded that no source data exists for any of the five, so the
-- comments are corrected here to say so instead of promising work that will
-- not happen.
COMMENT ON COLUMN model.features.debt_to_ebitda IS
  'Total debt divided by EBITDA; retired, permanently NULL -- no D&A/EBITDA in schema';
COMMENT ON COLUMN model.features.interest_coverage IS
  'Operating income divided by interest expense; retired, permanently NULL -- no interest expense line in schema';
COMMENT ON COLUMN model.features.liquidation_discount IS
  'Discount of market price to the preferred liquidation preference; retired, permanently NULL -- no shares outstanding, market cap not derivable';
COMMENT ON COLUMN model.features.legal_rights_score IS
  'Legal and protective-rights strength score on 0-1; retired, permanently NULL -- preferred.contract_terms has 2 of 10992 securities';
COMMENT ON COLUMN model.features.data_quality_score IS
  'Data-quality score of the underlying sources on 0-1; retired, permanently NULL -- audit.data_quality is a 2-date snapshot, not a series';
