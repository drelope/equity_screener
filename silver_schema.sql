-- =====================================================================
-- Silver layer schema: SEC XBRL company facts
-- PostgreSQL 13+
-- Star schema: dim_company, dim_concept, dim_period  +  fact_datapoint
--
-- Canonical definition. A duplicate file (silver_sec_company_facts.sql)
-- previously drifted from this one; it was consolidated here so the table
-- DDLs, comments and indexes live in a single source of truth.
--
-- The loader below expects a bronze.sec_company_facts table
-- (cik, raw_payload jsonb, source_record_id text, ingested_at) which is a
-- separate, aspirational intake layer; the produced/finished warehouse layer
-- in this repository is `raw`/`reference`/`fundamentals`/`model` instead.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS silver;

-- ---------------------------------------------------------------------
-- DIM: company
-- One row per CIK. Type-1 (overwrite) on entity_name.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.dim_company (
    company_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cik                CHAR(10)     NOT NULL UNIQUE,      -- zero-padded, e.g. '0000320193'
    entity_name        TEXT         NOT NULL,
    source_record_id   TEXT,                               -- bronze row id, for lineage
    ingested_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    is_current           BOOLEAN      NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE silver.dim_company IS 'One row per SEC filer (CIK).';

-- ---------------------------------------------------------------------
-- DIM: concept
-- One row per (taxonomy, tag), e.g. ('us-gaap','Assets'), ('dei','EntityCommonStockSharesOutstanding')
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.dim_concept (
    concept_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    taxonomy       TEXT NOT NULL,     -- 'us-gaap' | 'dei' | 'ifrs-full' | ...
    tag             TEXT NOT NULL,     -- 'Assets', 'Revenues', ...
    label           TEXT,               -- optional, if SEC metadata pulled
    description     TEXT,
    UNIQUE (taxonomy, tag)
);

COMMENT ON TABLE silver.dim_concept IS 'One row per distinct XBRL concept (taxonomy + tag).';

-- ---------------------------------------------------------------------
-- DIM: period
-- One row per distinct reporting period shape.
-- start_date IS NULL for instantaneous facts (e.g. balance sheet items).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.dim_period (
    period_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fiscal_year      SMALLINT,          -- fy
    fiscal_period     TEXT,               -- fp: 'Q1','Q2','Q3','FY'
    start_date        DATE,               -- NULL for instant facts
    end_date           DATE     NOT NULL,
    UNIQUE (fiscal_year, fiscal_period, start_date, end_date)
);

COMMENT ON TABLE silver.dim_period IS 'One row per distinct reporting period (shared across companies).';

-- ---------------------------------------------------------------------
-- FACT: datapoint
-- Grain: company x concept x unit x period x accession number.
-- accn is part of the grain because SEC restates/repeats periods
-- across multiple filings (e.g. comparative prior-year figures).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.fact_datapoint (
    fact_id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id           BIGINT NOT NULL REFERENCES silver.dim_company(company_id),
    concept_id            BIGINT NOT NULL REFERENCES silver.dim_concept(concept_id),
    period_id              BIGINT NOT NULL REFERENCES silver.dim_period(period_id),
    unit                    TEXT   NOT NULL,     -- 'USD','shares','USD/shares', ...
    value                    NUMERIC,
    form                     TEXT,               -- '10-K','10-Q','8-K', ...
    accn                      TEXT   NOT NULL,     -- accession number of reporting filing
    filed_date                DATE,
    frame                      TEXT,               -- e.g. 'CY2023Q4I', nullable
    source_record_id           TEXT,               -- bronze row id, for lineage
    ingested_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_current                    BOOLEAN     NOT NULL DEFAULT TRUE,

    CONSTRAINT uq_fact_business_key UNIQUE (company_id, concept_id, unit, period_id, accn)
);

COMMENT ON TABLE silver.fact_datapoint IS 'One row per reported XBRL value, at company x concept x unit x period x filing grain.';

CREATE INDEX IF NOT EXISTS ix_fact_company_concept
    ON silver.fact_datapoint (company_id, concept_id);

CREATE INDEX IF NOT EXISTS ix_fact_period
    ON silver.fact_datapoint (period_id);

CREATE INDEX IF NOT EXISTS ix_fact_concept_period
    ON silver.fact_datapoint (concept_id, period_id);


-- =====================================================================
-- LOAD: silver.load_company_facts
-- Explodes bronze.sec_company_facts.raw_payload:
--   facts -> {us-gaap|dei|...} -> {tag} -> units -> {unit} -> [datapoints]
-- =====================================================================

-- 1) Flatten to one row per datapoint (staging CTE, reused below)
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
),

-- 2) Normalize keys
normalized AS (
    SELECT
        LPAD(TRIM(cik), 10, '0')                              AS cik_padded,
        TRIM(entity_name)                                      AS entity_name,
        source_record_id,
        taxonomy,
        tag,
        unit,
        (datapoint ->> 'fy')::SMALLINT                         AS fiscal_year,
        datapoint ->> 'fp'                                     AS fiscal_period,
        NULLIF(datapoint ->> 'start', '')::DATE                AS start_date,
        (datapoint ->> 'end')::DATE                            AS end_date,
        (datapoint ->> 'val')::NUMERIC                          AS value,
        datapoint ->> 'form'                                    AS form,
        datapoint ->> 'accn'                                     AS accn,
        NULLIF(datapoint ->> 'filed', '')::DATE                  AS filed_date,
        datapoint ->> 'frame'                                     AS frame,
        ingested_at
    FROM exploded
),

-- 3) Upsert dimensions, capture surrogate keys
ins_company AS (
    INSERT INTO silver.dim_company (cik, entity_name, source_record_id, ingested_at)
    SELECT DISTINCT ON (cik_padded) cik_padded, entity_name, source_record_id, ingested_at
    FROM normalized
    ON CONFLICT (cik) DO UPDATE SET entity_name = EXCLUDED.entity_name
    RETURNING company_id, cik
),
ins_concept AS (
    INSERT INTO silver.dim_concept (taxonomy, tag)
    SELECT DISTINCT taxonomy, tag
    FROM normalized
    ON CONFLICT (taxonomy, tag) DO NOTHING
    RETURNING concept_id, taxonomy, tag
),
ins_period AS (
    INSERT INTO silver.dim_period (fiscal_year, fiscal_period, start_date, end_date)
    SELECT DISTINCT fiscal_year, fiscal_period, start_date, end_date
    FROM normalized
    ON CONFLICT (fiscal_year, fiscal_period, start_date, end_date) DO NOTHING
    RETURNING period_id, fiscal_year, fiscal_period, start_date, end_date
)

-- 4) Insert facts, deduped on the business key
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
FROM normalized n
JOIN silver.dim_company c  ON c.cik = n.cik_padded
JOIN silver.dim_concept co ON co.taxonomy = n.taxonomy AND co.tag = n.tag
JOIN silver.dim_period p
    ON p.fiscal_year = n.fiscal_year
   AND p.fiscal_period = n.fiscal_period
   AND p.start_date IS NOT DISTINCT FROM n.start_date
   AND p.end_date = n.end_date
ON CONFLICT ON CONSTRAINT uq_fact_business_key DO NOTHING;