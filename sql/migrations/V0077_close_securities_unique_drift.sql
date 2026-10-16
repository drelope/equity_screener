-- =====================================================================
-- V0077: close the last accepted schema drift -- the redundant
--        reference.securities UNIQUE(security_id).
--
-- reference.securities has both `security_id UUID PRIMARY KEY` and, on the
-- live database only, a second `UNIQUE(security_id)`. The two are identical:
-- 2.3 MB of index duplicating what the primary key already enforces. The
-- repository has only ever declared the primary key, so this is the one entry
-- in check_schema_drift.ACCEPTED_DIFFERENCES.
--
-- It was left in place because it cannot just be dropped: every foreign key to
-- reference.securities was resolved against this index rather than the primary
-- key, and PostgreSQL refuses to drop an index an FK depends on. (The
-- accepted-difference note mentions only market_data's FK as the expensive one;
-- in fact all twenty FKs to this table resolve to it.) The reason it is the
-- non-PK index at all is historical -- the UNIQUE predates the FKs, and an FK
-- binds to the unique index it finds first.
--
-- The fix is to drop all twenty FKs, drop the redundant constraint, and add the
-- FKs back; with the duplicate gone, the only unique index left is the primary
-- key, so each FK re-binds to it. The ~21M child rows across the tables are
-- re-validated by the ADD, which is the real cost and why this belongs in a
-- maintenance window rather than a random migration.
--
-- The guard matters: a fresh build (sql/schema.sql) never creates the redundant
-- constraint, so on a fresh database this is a no-op and the FKs already point
-- at the primary key. It only does work on the live database that carries the
-- historical duplicate.
-- =====================================================================

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'securities_security_id_key'
      AND conrelid = 'reference.securities'::regclass
  ) THEN
    RAISE NOTICE 'securities_security_id_key absent; V0077 is a no-op here';
    RETURN;
  END IF;

  -- 1. Drop every FK bound to the redundant unique index. Partitioned parents
  --    (market.trade/quote/bar) cascade to their partitions.
  ALTER TABLE raw.market_data             DROP CONSTRAINT market_data_security_id_fkey;
  ALTER TABLE raw.dividend_data           DROP CONSTRAINT dividend_data_security_id_fkey;
  ALTER TABLE raw.contract_documents      DROP CONSTRAINT contract_documents_security_id_fkey;
  ALTER TABLE raw.sec_documents           DROP CONSTRAINT sec_documents_security_id_fkey;
  ALTER TABLE raw.ticker_profile          DROP CONSTRAINT ticker_profile_security_id_fkey;
  ALTER TABLE clean.company_profile       DROP CONSTRAINT company_profile_reference_security_id_fkey;
  ALTER TABLE clean.ticker_profile        DROP CONSTRAINT ticker_profile_security_id_fkey;
  ALTER TABLE fundamentals.periodic_financials DROP CONSTRAINT periodic_financials_security_id_fkey;
  ALTER TABLE model.features              DROP CONSTRAINT features_security_id_fkey;
  ALTER TABLE model.predictions           DROP CONSTRAINT predictions_security_id_fkey;
  ALTER TABLE model.rankings              DROP CONSTRAINT rankings_security_id_fkey;
  ALTER TABLE model.scores                DROP CONSTRAINT scores_security_id_fkey;
  ALTER TABLE preferred.contract_terms    DROP CONSTRAINT contract_terms_security_id_fkey;
  ALTER TABLE preferred.dividend_snapshot DROP CONSTRAINT dividend_snapshot_security_id_fkey;
  ALTER TABLE preferred.security_terms    DROP CONSTRAINT security_terms_security_id_fkey;
  ALTER TABLE audit.data_quality          DROP CONSTRAINT data_quality_security_id_fkey;
  ALTER TABLE audit.source_lineage        DROP CONSTRAINT source_lineage_security_id_fkey;
  ALTER TABLE market.trade                DROP CONSTRAINT trade_security_id_fkey;
  ALTER TABLE market.quote                DROP CONSTRAINT quote_security_id_fkey;
  ALTER TABLE market.bar                  DROP CONSTRAINT bar_security_id_fkey;

  -- 2. Drop the duplicate. This also drops its backing index.
  ALTER TABLE reference.securities DROP CONSTRAINT securities_security_id_key;

  -- 3. Re-add the FKs. Only securities_pkey remains, so each binds to it.
  ALTER TABLE raw.market_data             ADD CONSTRAINT market_data_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE raw.dividend_data           ADD CONSTRAINT dividend_data_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE raw.contract_documents      ADD CONSTRAINT contract_documents_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE raw.sec_documents           ADD CONSTRAINT sec_documents_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE raw.ticker_profile          ADD CONSTRAINT ticker_profile_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE clean.company_profile       ADD CONSTRAINT company_profile_reference_security_id_fkey FOREIGN KEY (reference_security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE clean.ticker_profile        ADD CONSTRAINT ticker_profile_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE fundamentals.periodic_financials ADD CONSTRAINT periodic_financials_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE model.features              ADD CONSTRAINT features_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE model.predictions           ADD CONSTRAINT predictions_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE model.rankings              ADD CONSTRAINT rankings_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE model.scores                ADD CONSTRAINT scores_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE preferred.contract_terms    ADD CONSTRAINT contract_terms_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE preferred.dividend_snapshot ADD CONSTRAINT dividend_snapshot_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE preferred.security_terms    ADD CONSTRAINT security_terms_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE audit.data_quality          ADD CONSTRAINT data_quality_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE audit.source_lineage        ADD CONSTRAINT source_lineage_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE market.trade                ADD CONSTRAINT trade_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE market.quote                ADD CONSTRAINT quote_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
  ALTER TABLE market.bar                  ADD CONSTRAINT bar_security_id_fkey FOREIGN KEY (security_id) REFERENCES reference.securities(security_id);
END $$;
