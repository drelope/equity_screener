-- V0040 clamp_future_dividend_last_paid
--
-- Resolve the five quarantined dividend_last_paid values from V0038 by applying
-- the invariant now enforced in sec_client.classify_companyfacts(): a dividend
-- cannot have been *paid* after the run date, so dividend_last_paid is clamped
-- to today.
--
-- Why the invariant and not a narrower matcher. The concept list is
-- DIVIDEND_FACT_TERMS = ("dividend", "distributionstoowners"), matched as a
-- substring, so it admits balance-sheet and forward-looking tags whose period
-- end is in the future. The five anomalies were produced by:
--
--   MTEX      CommonStockDividendsPerShareDeclared                     2108-11-14
--   SQFT      DividendsPayableCurrentAndNoncurrent                     2026-12-31
--   SQFTP     DividendsPayableCurrentAndNoncurrent                     2026-12-31
--   SQFTW     DividendsPayableCurrentAndNoncurrent                     2026-12-31
--   UBSI      CashDividendsPaidToParentCompanyByConsid...Subsidiaries  2026-12-31
--
-- UBSI matters: even a tag whose name says "Paid" carries a future period end,
-- so no amount of concept narrowing removes the need for the date clamp.
--
-- The obvious narrowing -- dropping the payable/receivable/declared families --
-- was measured before being rejected: over the 8,105 cached CIKs carrying
-- dividend_facts it would clear the dividend flag entirely for 3,611 of them.
-- That is a universe change of roughly 45% of the payer population, so it needs
-- the reference-stage rebuild that is currently unsafe, not a migration. It is
-- recorded here so it is not silently forgotten.
--
-- Clamping instead leaves the dividend flag untouched for all eight thousand
-- CIKs and fixes only the five impossible dates. The future-dated evidence is
-- left in raw.company_classification.dividend_facts and in the quarantine
-- registry so a later matcher fix can be compared against what was corrected.

UPDATE reference.securities s
SET dividend_last_paid = current_date
WHERE s.dividend_last_paid > current_date;

-- The cached classification carries the same value in its own column (added in
-- V0035), so it is corrected with the securities row rather than left stale for
-- the cached branch of populate_securities to re-emit.
UPDATE raw.company_classification cc
SET dividend_last_paid = current_date
WHERE cc.dividend_last_paid > current_date;

-- And reference.securities.classification_evidence embeds the value too, which
-- is what populate_securities reads to rebuild the dict, so a stale future date
-- here would come straight back on the next cached write.
UPDATE reference.securities s
SET classification_evidence = jsonb_set(
        s.classification_evidence,
        '{dividend_last_paid}',
        to_jsonb(current_date::text)
    )
WHERE s.classification_evidence IS NOT NULL
  AND s.classification_evidence->>'dividend_last_paid' > current_date::text;

-- Close the quarantine entries. The registry is append-only, so resolution is
-- recorded by stamping resolved_at and describing the fix, never by deleting.
UPDATE audit.quarantined_values
SET resolved_at = now(),
    resolution_note =
        'Clamped to current_date by V0040. sec_client.classify_companyfacts() now '
        'applies the same ceiling to the running max, so a re-extraction cannot '
        'reintroduce the future date. The future-dated fact remains in '
        'raw.company_classification.dividend_facts as evidence. Narrowing '
        'DIVIDEND_FACT_TERMS to exclude payable/receivable/declared tags was '
        'measured and rejected: it would clear the dividend flag for 3,611 of '
        '8,105 cached CIKs, which requires a reference-stage rebuild.'
WHERE resolved_at IS NULL
  AND table_schema = 'reference'
  AND table_name = 'securities'
  AND column_name = 'dividend_last_paid';
