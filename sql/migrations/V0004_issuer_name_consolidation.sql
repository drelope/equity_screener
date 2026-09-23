-- =====================================================================
-- V0004 issuer_name_consolidation
-- Consolidate the issuer-name attribute onto reference.issuers.
--
--  1. reference.issuers.legal_name  -> reference.issuers.issuer_name
--     (rename: one canonical issuer-name column, dei:EntityRegistrantName).
--  2. reference.securities.issuer_name -> dropped
--     (denormalized per-security copy; the issuer name now lives on
--     reference.issuers and is reached by joining reference.securities via
--     issuer_id / cik).
--
-- Wrapped in a single DO block so scripts/migrate.py applies the file as one
-- statement (see scripts/migrate.py apply_migration). Every step is guarded so
-- the migration is idempotent: fresh installs that already carry the canonical
-- names (schema.sql) and databases converged by V0003 / init_db.py are skipped.
-- =====================================================================

DO $migration$
BEGIN

-- 1) Rename reference.issuers.legal_name to the canonical issuer_name.
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'reference' AND table_name = 'issuers'
      AND column_name = 'legal_name'
) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'reference' AND table_name = 'issuers'
      AND column_name = 'issuer_name'
) THEN
    ALTER TABLE reference.issuers RENAME COLUMN legal_name TO issuer_name;
END IF;

-- 2) Drop the denormalized issuer_name copy on reference.securities.
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'reference' AND table_name = 'securities'
      AND column_name = 'issuer_name'
) THEN
    ALTER TABLE reference.securities DROP COLUMN issuer_name;
END IF;

END
$migration$;