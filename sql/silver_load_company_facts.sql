-- =====================================================================
-- silver.load_company_facts()
-- Explodes bronze.sec_company_facts.raw_payload into the silver star schema:
--   facts -> {us-gaap|dei|...} -> {tag} -> units -> {unit} -> [datapoints]
--
-- Apply after silver_schema.sql, then call:  SELECT silver.load_company_facts();
-- Returns the number of fact rows inserted (0 on a re-load, which is the
-- correct answer for an idempotent loader, not a failure).
--
-- WHY A FUNCTION AND NOT A STATEMENT
-- The obvious way to write this is one statement with data-modifying CTEs:
--
--     WITH ins_company AS (INSERT INTO dim_company ... RETURNING ...),
--          ins_concept AS (INSERT INTO dim_concept ... RETURNING ...),
--          ins_period  AS (INSERT INTO dim_period  ... RETURNING ...)
--     INSERT INTO fact_datapoint SELECT ... FROM normalized n
--     JOIN dim_company c ON ... JOIN dim_concept co ON ... JOIN dim_period p ON ...
--
-- That inserts zero facts, always. Sub-statements in a WITH clause execute
-- concurrently with the main query and against the snapshot taken when the
-- statement began, so the dimension rows inserted by ins_company/ins_concept/
-- ins_period are invisible to the fact INSERT's joins. On a fresh warehouse
-- every join matches nothing. The RETURNING clauses cannot rescue it either:
-- they exist to pass data between the CTEs, and none of them were wired up.
--
-- Each statement inside a plpgsql function is its own command and takes a
-- fresh snapshot, so a later statement sees an earlier one's committed rows.
--
-- The dimension joins are NULL-safe on every nullable key, matching the
-- NULLS NOT DISTINCT constraint on dim_period. Plain equality against a NULL
-- yields NULL, which is not true, so an instant fact (no fy, no fp, no start
-- date) would match no period row at all.
--
-- This is not applied automatically: silver_load_company_facts.sql does not
-- match the V####_name.sql pattern scripts/migrate.py discovers, and the
-- bronze intake layer it reads does not exist in this repository.
-- =====================================================================

CREATE OR REPLACE FUNCTION silver.load_company_facts()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_facts BIGINT := 0;
BEGIN
    IF to_regclass('bronze.sec_company_facts') IS NULL THEN
        RAISE EXCEPTION
            'bronze.sec_company_facts does not exist. The silver loader reads '
            'exploded SEC companyfacts from the bronze intake layer, which this '
            'repository does not create; the produced warehouse is '
            'raw/reference/fundamentals/model. Stage the payload into a '
            'bronze.sec_company_facts(cik, raw_payload jsonb, source_record_id, '
            'ingested_at) table first, or use scripts/populate_companyfacts.py, '
            'which writes raw.companyfacts.';
    END IF;

    -- Flatten the payload once; every statement below reads this instead of
    -- re-parsing the same JSON. The DROP is not redundant: ON COMMIT DROP only
    -- fires at commit, so a second call inside the same transaction -- a batch
    -- loading several files, say -- would collide with the table still there.
    DROP TABLE IF EXISTS _silver_company_facts;
    CREATE TEMP TABLE _silver_company_facts ON COMMIT DROP AS
    WITH exploded AS (
        SELECT
            b.cik,
            b.raw_payload ->> 'entityName'                       AS entity_name,
            b.source_record_id,
            taxonomy.key                                          AS taxonomy,
            tag.key                                                AS tag,
            unit.key                                               AS unit,
            dp.value                                               AS datapoint,
            b.ingested_at
        FROM bronze.sec_company_facts b
        CROSS JOIN LATERAL jsonb_each(b.raw_payload -> 'facts') AS taxonomy(key, value)
        CROSS JOIN LATERAL jsonb_each(taxonomy.value)            AS tag(key, value)
        CROSS JOIN LATERAL jsonb_each(tag.value -> 'units')      AS unit(key, value)
        CROSS JOIN LATERAL jsonb_array_elements(unit.value)      AS dp(value)
    )
    SELECT
        LPAD(TRIM(cik), 10, '0')                              AS cik,
        TRIM(entity_name)                                      AS entity_name,
        source_record_id,
        taxonomy,
        tag,
        unit,
        NULLIF(datapoint ->> 'fy', '')::SMALLINT              AS fiscal_year,
        NULLIF(datapoint ->> 'fp', '')                        AS fiscal_period,
        NULLIF(datapoint ->> 'start', '')::DATE               AS start_date,
        NULLIF(datapoint ->> 'end', '')::DATE                 AS end_date,
        NULLIF(datapoint ->> 'val', '')::NUMERIC               AS value,
        NULLIF(datapoint ->> 'form', '')                       AS form,
        NULLIF(datapoint ->> 'accn', '')                       AS accn,
        NULLIF(datapoint ->> 'filed', '')::DATE                AS filed_date,
        NULLIF(datapoint ->> 'frame', '')                      AS frame,
        ingested_at
    FROM exploded;

    -- entity_name is a type-1 attribute: newest payload wins for a CIK.
    INSERT INTO silver.dim_company (cik, entity_name, source_record_id, ingested_at)
    SELECT DISTINCT ON (cik) cik, entity_name, source_record_id, ingested_at
    FROM _silver_company_facts
    ORDER BY cik, ingested_at DESC
    ON CONFLICT (cik) DO UPDATE SET entity_name = EXCLUDED.entity_name;

    INSERT INTO silver.dim_concept (taxonomy, tag)
    SELECT DISTINCT taxonomy, tag
    FROM _silver_company_facts
    ON CONFLICT (taxonomy, tag) DO NOTHING;

    INSERT INTO silver.dim_period (fiscal_year, fiscal_period, start_date, end_date)
    SELECT DISTINCT fiscal_year, fiscal_period, start_date, end_date
    FROM _silver_company_facts
    ON CONFLICT (fiscal_year, fiscal_period, start_date, end_date) DO NOTHING;

    INSERT INTO silver.fact_datapoint
        (company_id, concept_id, period_id, unit, value, form, accn,
         filed_date, frame, source_record_id, ingested_at)
    SELECT
        c.company_id,
        co.concept_id,
        p.period_id,
        n.unit,
        n.value,
        n.form,
        n.accn,
        n.filed_date,
        n.frame,
        n.source_record_id,
        n.ingested_at
    FROM _silver_company_facts n
    JOIN silver.dim_company c ON c.cik = n.cik
    JOIN silver.dim_concept co ON co.taxonomy = n.taxonomy AND co.tag = n.tag
    JOIN silver.dim_period p
        ON p.fiscal_year IS NOT DISTINCT FROM n.fiscal_year
       AND p.fiscal_period IS NOT DISTINCT FROM n.fiscal_period
       AND p.start_date IS NOT DISTINCT FROM n.start_date
       AND p.end_date = n.end_date
    WHERE n.accn IS NOT NULL
    ON CONFLICT ON CONSTRAINT uq_fact_business_key DO NOTHING;

    GET DIAGNOSTICS v_facts = ROW_COUNT;
    RETURN v_facts;
END;
$$;

COMMENT ON FUNCTION silver.load_company_facts() IS
  'Load bronze.sec_company_facts into the silver star schema. Idempotent; '
  'returns the number of fact rows inserted, so 0 means already loaded.';
