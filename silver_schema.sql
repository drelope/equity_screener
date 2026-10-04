-- =====================================================================
-- Silver layer schema: SEC XBRL company facts
-- PostgreSQL 15+ (UNIQUE NULLS NOT DISTINCT; the compose stack pins 17.11)
-- Star schema: dim_company, dim_concept, dim_period  +  fact_datapoint
--
-- Canonical definition. A duplicate file (silver_sec_company_facts.sql)
-- previously drifted from this one; it was consolidated here so the table
-- DDLs, comments and indexes live in a single source of truth.
--
-- This file is DDL only. The loader lives in silver_load_company_facts.sql,
-- which is a function rather than a bare statement because a data-modifying
-- CTE cannot see the rows it inserts: every sub-statement in a WITH clause
-- runs against the snapshot taken at the start of the enclosing statement,
-- so the fact INSERT could not join to the dimension rows inserted alongside
-- it and inserted zero rows on an empty warehouse.
--
-- NOT APPLIED BY ANYTHING IN THIS REPOSITORY. The loader reads
-- bronze.sec_company_facts (cik, raw_payload jsonb, source_record_id text,
-- ingested_at), an intake layer this repo does not create; the produced
-- warehouse is raw/reference/fundamentals/model instead. This schema is kept
-- as the target shape for that layer and is applied by hand.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS silver;

-- ---------------------------------------------------------------------
-- DIM: company
-- One row per CIK. Type-1 (overwrite) on entity_name, so there is no
-- history to select from and no is_current flag to maintain: the single
-- row for a CIK is by construction the current one.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.dim_company (
    company_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cik                CHAR(10)     NOT NULL UNIQUE,      -- zero-padded, e.g. '0000320193'
    entity_name        TEXT         NOT NULL,
    source_record_id   TEXT,                               -- bronze row id, for lineage
    ingested_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE silver.dim_company IS 'One row per SEC filer (CIK), overwritten in place.';

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
-- One row per distinct reporting period shape, shared across companies.
-- start_date IS NULL for instantaneous facts (e.g. balance sheet items).
--
-- fy and fp are nullable as well as start_date, and a plain UNIQUE treats
-- every NULL as distinct, so an instant fact with no fy/fp/start would
-- insert a fresh duplicate period on every load and then fan out into
-- duplicate facts -- the fact join matches on NULL-safe equality. The
-- constraint has to be NULLS NOT DISTINCT or the dimension does not dedupe
-- the rows it exists to dedupe.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.dim_period (
    period_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fiscal_year      SMALLINT,          -- fy, NULL when the fact carries none
    fiscal_period     TEXT,              -- fp: 'Q1','Q2','Q3','FY', NULL when absent
    start_date        DATE,              -- NULL for instant facts
    end_date           DATE     NOT NULL,
    UNIQUE NULLS NOT DISTINCT (fiscal_year, fiscal_period, start_date, end_date)
);

COMMENT ON TABLE silver.dim_period IS 'One row per distinct reporting period (shared across companies).';

-- ---------------------------------------------------------------------
-- FACT: datapoint
-- Grain: company x concept x unit x period x accession number.
-- accn is part of the grain because SEC restates/repeats periods
-- across multiple filings (e.g. comparative prior-year figures).
--
-- There is deliberately no is_current flag. The loader never supersedes a
-- row -- it leaves conflicts alone -- so nothing could ever clear the flag,
-- and a column that is always TRUE is read as if it means something. A
-- restatement policy needs the old and new filing side by side, which is a
-- decision about the grain rather than a boolean.
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

    CONSTRAINT uq_fact_business_key UNIQUE (company_id, concept_id, unit, period_id, accn)
);

COMMENT ON TABLE silver.fact_datapoint IS 'One row per reported XBRL value, at company x concept x unit x period x filing grain.';

-- No (company_id, concept_id) index: uq_fact_business_key already leads with
-- those two columns, so this one could never be chosen ahead of it.

CREATE INDEX IF NOT EXISTS ix_fact_period
    ON silver.fact_datapoint (period_id);

CREATE INDEX IF NOT EXISTS ix_fact_concept_period
    ON silver.fact_datapoint (concept_id, period_id);
