-- V0046 validate the securities company_ticker foreign key
--
-- init_db.py adds fk_securities_company_ticker as NOT VALID so that
-- initialization cannot fail on a database whose ticker/cik pairs do not all
-- resolve -- the point of NOT VALID is that existing rows are not checked.
--
-- The live database has since had it validated, which is the desired end state,
-- but nothing in the repository said so: init_db re-adds it NOT VALID and no
-- migration ever validated it, so a rebuild produced a structurally different
-- database that happened to be weaker. Found by diffing a reference build
-- against the live catalog (scripts/check_schema_drift.py).
--
-- VALIDATE CONSTRAINT on an already-validated constraint is a no-op, so this is
-- safe to apply to live: it verifies rather than rebuilds, and it takes a
-- SHARE UPDATE EXCLUSIVE lock rather than ACCESS EXCLUSIVE.

BEGIN;

ALTER TABLE reference.securities
    VALIDATE CONSTRAINT fk_securities_company_ticker;

COMMIT;
