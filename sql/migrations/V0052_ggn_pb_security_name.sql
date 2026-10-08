-- V0052 GGN-PB security_name from the fund's own filings
--
-- reference.securities.security_name for GGN-PB was the issuer name ("GAMCO Global
-- Gold, Natural Resources & Income Trust"), because the pipeline has no source for a
-- closed-end fund's class titles: raw.sec_instrument_titles reads the dei cover page
-- of 10-K / 10-Q / 20-F / S-1 / 424B forms, and GGN files N-CSR, N-CSRS, N-2 and 497.
-- Tested 2026-10-06: the XBRL on the N-CSR and N-CSRS of GGN and four peer funds
-- (GAB, GDV, GLU, GNT) carries no security-title or trading-symbol tag, so adding those
-- forms to the extractor would extract nothing. The name cannot come from the pipeline.
--
-- It is evidenced by the filings themselves. GGN's N-CSR (2026-03-09) lists
-- "5.00% Series B Cumulative Preferred Shares", and its N-2/A (2024-04-15) states they
-- "are listed on the NYSE American under the symbol 'GGN PrB'", i.e. GGN-PB.
--
-- The value is the issuer name followed by the filed title. V0042 set the bare filed
-- title for the preferreds that had one; the issuer prefix is kept here by request, and
-- the issuer is still carried by cik.
--
-- security_name is a display label. No model.* table has the column and neither
-- scoring.py, features.py nor score_rank.py reads it, and GGN-PB is not a dividend
-- payer, so it has no prices, features, scores or predictions to move.
--
-- Durable: populate_reference_tables keeps an existing name when there is no title
-- evidence ("retained_existing_unverified"), and populate_raw_tables only rewrites
-- names for dividend payers. If filed-title evidence ever appears it takes precedence,
-- which is the intended order. The guard below leaves any name that already carries a
-- series untouched, so re-applying never clobbers a better one.

UPDATE reference.securities
SET security_name = 'GAMCO Global Gold, Natural Resources & Income Trust 5.00% Series B Cumulative Preferred Shares',
    updated_at = now()
WHERE ticker = 'GGN-PB'
  AND cik = '0001313510'
  AND security_type = 'preferred stock'
  AND (security_name IS NULL OR security_name !~* 'series\s+[A-Za-z0-9]');
