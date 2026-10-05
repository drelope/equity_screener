-- V0036 backfill_dividend_last_paid
--
-- Restore reference.securities.dividend_last_paid, which has been NULL for every
-- dividend payer, and populate the raw.company_classification cache column added
-- in V0035.
--
-- Root cause (V0035): classify_companyfacts() always returned dividend_last_paid,
-- but the cache table had no column for it, so the cached branch of
-- populate_securities rebuilt the classification dict without the key and
-- wrote NULL. Because the column was never populated, re-running the stage could
-- not recover it.
--
-- The value is reconstructed from dividend_facts, which is already persisted and
-- holds the same positive records classify_companyfacts() used to set both the
-- dividend flag and dividend_last_paid (it stores the 5 most recent positive
-- records per concept). Reconstructing from those records therefore agrees with
-- the existing dividend flag instead of introducing a second source of truth, and
-- needs no network access.
--
-- Only XBRL period-end strings are stored in dividend_facts, so the max is the
-- latest period end, matching sec_client.py's own ordering logic.
--
-- The classification_evidence payload is updated alongside, because it embeds
-- the same two keys (dividend_last_paid, and dividend_lookback_start) and both
-- were written as null by the same defect. dividend_lookback_start is
-- deliberately left null: it is derived from the recency cutoff, which is
-- correctly absent while ENFORCE_DIVIDEND_RECENCY is false, so null is the
-- accurate value there rather than a gap.

-- Step 1: cache column, from the persisted positive dividend records.
UPDATE raw.company_classification cc
SET dividend_last_paid = sub.last_paid::date
FROM (
    SELECT src.cik, MAX(r.value->>'end') AS last_paid
    FROM raw.company_classification src
    CROSS JOIN LATERAL jsonb_array_elements(src.dividend_facts) AS c(value)
    CROSS JOIN LATERAL jsonb_array_elements(c.value->'records') AS r(value)
    WHERE r.value->>'end' IS NOT NULL
    GROUP BY src.cik
) AS sub
WHERE cc.cik = sub.cik
  AND cc.dividend_last_paid IS DISTINCT FROM sub.last_paid::date;

-- Step 2: reference.securities, from the cache, for every security whose CIK
-- has a cached value -- matching populate_securities, which binds
-- classification.get("dividend_last_paid") regardless of the dividend flag.
UPDATE reference.securities s
SET dividend_last_paid = cc.dividend_last_paid,
    updated_at = now()
FROM raw.company_classification cc
WHERE cc.cik = s.cik
  AND cc.dividend_last_paid IS NOT NULL
  AND s.dividend_last_paid IS DISTINCT FROM cc.dividend_last_paid;

-- Step 3: mirror the restored value into the evidence payload.
UPDATE reference.securities s
SET classification_evidence = jsonb_set(
        s.classification_evidence,
        '{dividend_last_paid}',
        to_jsonb(s.dividend_last_paid::text),
        true
    )
WHERE s.classification_evidence IS NOT NULL
  AND s.dividend_last_paid IS NOT NULL
  AND s.classification_evidence->>'dividend_last_paid'
      IS DISTINCT FROM s.dividend_last_paid::text;
