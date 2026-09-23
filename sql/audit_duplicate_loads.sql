-- Audit queries for duplicate SEC filing loads (ETL performance / storage).
--
-- Before the CIK re-keying, the issuer-level payloads in raw.companyfacts,
-- raw.sec_submissions and raw.company_taxonomy were copied once per listed
-- security. Run these to (a) confirm the dedupe migration is stable and
-- (b) spot any future regression that would reload the same issuer payload
-- multiple times.

-- 1. Payload tables must hold exactly one row per distinct CIK.
SELECT 'raw.companyfacts'        AS table_name, count(*) AS rows, count(DISTINCT cik) AS distinct_ciks,
       pg_size_pretty(SUM(pg_column_size(raw_payload))) AS payload_bytes
FROM raw.companyfacts
UNION ALL
SELECT 'raw.sec_submissions', count(*), count(DISTINCT cik), pg_size_pretty(SUM(pg_column_size(raw_payload)))
FROM raw.sec_submissions
UNION ALL
SELECT 'raw.company_taxonomy', count(*), count(DISTINCT cik), pg_size_pretty(SUM(pg_column_size(raw_payload)))
FROM raw.company_taxonomy;

-- 2. Rows that STILL duplicate another row with the same CIK + content hash
--    (regression check: any hit means a per-security copy was written again).
SELECT 'raw.companyfacts' AS table_name, count(*) AS leftover_duplicates
FROM raw.companyfacts a
JOIN raw.companyfacts b
  ON a.cik = b.cik AND a.ctid <> b.ctid
WHERE a.content_hash = b.content_hash
UNION ALL
SELECT 'raw.sec_submissions', count(*)
FROM raw.sec_submissions a
JOIN raw.sec_submissions b
  ON a.cik = b.cik AND a.ctid <> b.ctid
WHERE a.content_hash = b.content_hash
UNION ALL
SELECT 'raw.company_taxonomy', count(*)
FROM raw.company_taxonomy a
JOIN raw.company_taxonomy b
  ON a.cik = b.cik AND a.ctid <> b.ctid
WHERE a.content_hash = b.content_hash;

-- 3. Issuers with the most formerly-reduplicated copies still in references:
--    how many listed securities today point at the SAME one row per CIK.
SELECT s.cik,
       count(DISTINCT s.security_id) AS linked_securities,
       count(DISTINCT cf.content_hash) AS distinct_facts,
       cf.content_hash IS NOT NULL AS facts_loaded_once
FROM reference.securities s
LEFT JOIN raw.companyfacts cf ON cf.cik = s.cik
GROUP BY s.cik, cf.content_hash
HAVING count(DISTINCT s.security_id) > 1 AND count(DISTINCT cf.content_hash) <= 1
ORDER BY linked_securities DESC
LIMIT 20;

-- 4. Storage saved by the dedupe (rounded to MB, before/after snapshot).
SELECT 'companyfacts_before' AS metric,
       pg_size_pretty(2001.8 * 1024 * 1024) AS bytes
UNION ALL
SELECT 'companyfacts_after',
       pg_size_pretty(COALESCE(SUM(pg_column_size(raw_payload)), 0))
FROM raw.companyfacts;