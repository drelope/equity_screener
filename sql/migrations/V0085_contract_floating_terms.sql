-- Floating-rate terms mined from the governing documents.
--
-- On 2026-10-17 fixed_period_end and floating_spread were NULL for all 30 active
-- fixed-to-floating preferreds in clean.ticker_profile, because those fields came
-- only from parsing names, and names never state them. The offering supplement
-- states both in one dividend sentence ("... to, but excluding, October 30, 2026
-- at a fixed rate ... Three-Month Term SOFR plus a spread of 5.442%").
-- scripts.populate_contract_terms mines them with doc_clauses.extract_floating_terms
-- (only for securities whose name or coupon type marks a floating or reset
-- structure), and populate_clean_ticker_profile uses them when no profile source
-- supplies a value.

ALTER TABLE preferred.contract_terms
    ADD COLUMN IF NOT EXISTS fixed_period_end   date,
    ADD COLUMN IF NOT EXISTS floating_spread    numeric(8, 4),
    ADD COLUMN IF NOT EXISTS floating_benchmark text;

COMMENT ON COLUMN preferred.contract_terms.fixed_period_end IS
  'Last day (exclusive) of the fixed-rate dividend period, from the dividend clause';
COMMENT ON COLUMN preferred.contract_terms.floating_spread IS
  'Spread over the benchmark in percent (5.442 = 5.442%) for the floating/reset period';
COMMENT ON COLUMN preferred.contract_terms.floating_benchmark IS
  'Benchmark named in the dividend clause (SOFR, LIBOR, Treasury Rate, benchmark rate)';
