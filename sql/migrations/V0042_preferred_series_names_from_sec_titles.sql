-- V0042 preferred_series_names_from_sec_titles
--
-- All 1,327 active preferreds carried a security_name with no "Series X" in it,
-- e.g. "ZIONS BANCORPORATION, NATIONAL ASS" or "Public Storage" -- an issuer
-- name, not an instrument name. series_pattern_from_security() keys off
-- "Series <x>", so the series was undetectable for every one of them.
--
-- Most of this population cannot be fixed from what is in the warehouse. The
-- obvious source, preferred.security_terms.preferred_series, turns out to be
-- populated with issuer names as well: 916 distinct values, of which 0 match a
-- bare series letter like "A" or "PS" and which read "FEDERAL HOME LOAN
-- MORTGAGE CORP", "Public Storage", "BANK OF AMERICA CORP /DE/". The column
-- name says series and the contents say issuer, which is the real blocker here
-- rather than a missing join. Fixing the population would mean parsing series
-- out of filings for 1,323 securities.
--
-- What is evidenced is fixed. raw.sec_instrument_titles holds the instrument
-- title exactly as the filer wrote it, and four active preferreds without a
-- series have one naming a series. Their security_name is set to the filed
-- title, which both introduces the series and matches the convention the table
-- already uses for common_stock ("Class A ordinary shares, par value ...").
--
-- security_name is a display label: no model.* table has the column and neither
-- scoring.py, features.py nor score_rank.py reads it, so no score, prediction or
-- ranking can move. The issuer is still carried by ticker.

UPDATE reference.securities s
SET security_name = src.title
FROM (
    SELECT DISTINCT ON (upper(t.ticker))
           upper(t.ticker) AS ticker_key,
           t.title
    FROM raw.sec_instrument_titles t
    WHERE t.title ~* 'series\s+[A-Za-z0-9]'
    ORDER BY upper(t.ticker), length(t.title)
) src
WHERE upper(s.ticker) = src.ticker_key
  AND s.active
  AND s.security_type LIKE '%preferred%'
  AND (s.security_name IS NULL OR s.security_name !~* 'series\s+[A-Za-z0-9]');
