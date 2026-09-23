select cf.* 
from raw.companyfacts as cf
where cf.cik = '0000948320';

/**/
SELECT 
    c.security_id,
    c.cik,
    c.company_name,
    concept.key AS concept_key,
    concept.value->>'label' AS concept_label,
    unit.key AS unit,
    fact.value->>'fy' AS fiscal_year,
    fact.value->>'fp' AS fiscal_period,
    fact.value->>'form' AS form_type,
    fact.value->>'filed' AS filing_date,
    fact.value->>'start' AS period_start_date,
    fact.value->>'end' AS period_end_date,
    (fact.value->>'val')::numeric AS amount
FROM raw.companyfacts as c,
-- Iterate through all us-gaap concept keys inside raw_payload
LATERAL jsonb_each(c.raw_payload->'facts'->'us-gaap') AS concept,
-- Iterate through units array (e.g., "USD", "USD/shares")
LATERAL jsonb_each(concept.value->'units') AS unit,
-- Unnest the individual fact entries in the unit array
LATERAL jsonb_array_elements(unit.value) AS fact
WHERE concept.key IN (
    'CommonStockDividendsPerShareDeclared',
    'CommonStockDividendsPerShareCashPaid',
    'PaymentsOfDividends',
    'PaymentsOfDividendsCommonStock',
    'DividendsCommonStockCash',
    'PreferredStockDividendsIncomeStatementImpact',
    'Dividends'
)
ORDER BY filing_date DESC, concept_key;

/**/
SELECT 
    c.security_id,
    c.cik,
    c.company_name,
    f_form.val AS form_type,
    f_date.val AS filing_date,
    f_items.val AS items
FROM raw.companyfacts c
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'form') WITH ORDINALITY AS f_form(val, idx) ON true
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'filingDate') WITH ORDINALITY AS f_date(val, idx) ON f_form.idx = f_date.idx
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'items') WITH ORDINALITY AS f_items(val, idx) ON f_form.idx = f_items.idx
WHERE f_form.val IN ('10-Q', '10-K', '8-K')
  -- Item 8.01 (Other Events) often contains dividend announcements
  -- AND (f_items.val LIKE '%8.01%' OR f_form.val IN ('10-Q', '10-K'))
  ;

/**/
SELECT 
    c.security_id,
    c.cik,
    c.company_name,
    c.raw_payload->>'ein' AS ein,
    c.raw_payload->>'sic' AS sic,
    f_form.val AS form_type,
    f_date.val AS filing_date,
    f_size.val::bigint AS file_size_bytes,
    (f_xbrl.val::int = 1) AS is_xbrl,
    f_num.val AS file_number,
    f_act.val AS act,
    f_core.val AS core_type
FROM raw.companyfacts c
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'form') WITH ORDINALITY AS f_form(val, idx) ON true
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'filingDate') WITH ORDINALITY AS f_date(val, idx) ON f_form.idx = f_date.idx
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'size') WITH ORDINALITY AS f_size(val, idx) ON f_form.idx = f_size.idx
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'isXBRL') WITH ORDINALITY AS f_xbrl(val, idx) ON f_form.idx = f_xbrl.idx
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'fileNumber') WITH ORDINALITY AS f_num(val, idx) ON f_form.idx = f_num.idx
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'act') WITH ORDINALITY AS f_act(val, idx) ON f_form.idx = f_act.idx
LEFT JOIN LATERAL jsonb_array_elements_text(c.raw_payload->'filings'->'recent'->'core_type') WITH ORDINALITY AS f_core(val, idx) ON f_form.idx = f_core.idx
WHERE c.cik = '0000948320';

/**/

SELECT 
    security_id,
    cik,
    company_name,
    cg.key AS group_category,
    group_item.value AS concept_item
FROM raw.companyfacts AS cf,
LATERAL jsonb_each(cf.concept_groups) AS cg,
LATERAL jsonb_array_elements_text(cg.value) AS group_item;


/*expand only values that are valid JSON
This prevents the error you hit:
“Unexpected character '2' at position 0”  
(because some values begin with numbers, not { or [)
*/
/*
Flattening nested SEC‑style JSON in SQL Server means turning deeply nested objects/arrays (like the facts → dei → units → shares → array of objects structure in your attached document) into a relational rowset.

The key is to use OPENJSON + CROSS APPLY at each level, validating JSON before expanding it.

Below is the cleanest, production‑ready pattern for flattening any nested JSON column in SQL Server.
*/

SELECT
    top.[key]       AS level1_key,
    top.[type]      AS level1_type,
    mid.[key]       AS level2_key,
    mid.[type]      AS level2_type,
    leaf.[key]      AS level3_key,
    leaf.[type]     AS level3_type,
    leaf.[value]    AS level3_value
FROM raw.sec_company_facts_raw r
CROSS APPLY OPENJSON(r.Facts) top
OUTER APPLY (
    SELECT *
    FROM OPENJSON(top.[value])
    WHERE ISJSON(top.[value]) = 1
) mid
OUTER APPLY (
    SELECT *
    FROM OPENJSON(mid.[value])
    WHERE ISJSON(mid.[value]) = 1
) leaf;
/**/
SELECT
    j1.[key]       AS level1_key,
    j1.[type]      AS level1_type,
    j2.[key]       AS level2_key,
    j2.[type]      AS level2_type,
    j3.[key]      AS level3_key,
    j3.[type]     AS level3_type,
    j3.[value]    AS level3_value
FROM raw.sec_company_facts_raw s
CROSS APPLY OPENJSON(s.Facts) j1
OUTER APPLY (
    SELECT *
    FROM OPENJSON(j1.[value])
    --WHERE ISJSON(top.[value]) = 1
) j2
OUTER APPLY (
    SELECT *
    FROM OPENJSON(j2.[value])
    --WHERE ISJSON(mid.[value]) = 1
) j3
where j1.[key] = 'dei';

/*
SELECT top 100
    c.CIK,
    c.Ticker,
    JSON_VALUE(c.Facts, '$.entityName') AS EntityName,
    c.FetchedAt,

    -- Namespace (dei, us-gaap, ifrs-full, etc.)
    j1.[key] AS FactNamespace,

    -- Fact name
    j2.[key] AS FactName,

    -- Unit (USD, shares, pure, etc.)
    j3.[key] AS Unit,

    -- Period-level attributes
    JSON_VALUE(j4.[value], '$.end') AS EndDate,
    JSON_VALUE(j4.[value], '$.start') AS StartDate,
    JSON_VALUE(j4.[value], '$.val') AS Value,
    JSON_VALUE(j4.[value], '$.accn') AS AccessionNumber,
    JSON_VALUE(j4.[value], '$.form') AS Form,
    JSON_VALUE(j4.[value], '$.fy') AS FiscalYear,
    JSON_VALUE(j4.[value], '$.fp') AS FiscalPeriod,
    JSON_VALUE(j4.[value], '$.frame') AS Frame

FROM raw.sec_company_facts_raw AS c

-- facts object
CROSS APPLY OPENJSON(c.Facts, '$.facts') AS j1

-- individual fact inside namespace
CROSS APPLY OPENJSON(j1.[value]) AS j2

-- units inside fact
CROSS APPLY OPENJSON(j2.[value], '$.units') AS j3

-- array of period entries
CROSS APPLY OPENJSON(j3.[value]) AS j4

ORDER BY c.CIK, FactNamespace, FactName, EndDate;

*/