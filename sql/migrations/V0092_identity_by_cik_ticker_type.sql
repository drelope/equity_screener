-- V0092 identity_by_cik_ticker_type
--
-- A security's identity is (cik, ticker, security_type). `dividend` is an
-- attribute of the instrument, not part of its identity.
--
-- Why: security_id was minted from (ticker, cik, security_type, dividend), and
-- the unique index carried `dividend` in its key. When raw.company_classification
-- flipped an issuer's dividend flag, the reseed minted a second row with a new
-- security_id and deactivated the first. The history (prices, fundamentals,
-- audit lineage) stayed under the old id, and the active twin had none. Measured
-- on 2026-10-24: 2,787 (cik, ticker, security_type) groups were split this way,
-- 268 groups had no active row, and the backtest could not see about 39% of the
-- companies priced in January 2019.
--
-- What this migration does, in one transaction:
--   1. Picks one winner per (cik, ticker, security_type) group: the row with the
--      most price rows, then the active row, then the latest update.
--   2. Moves each loser's child rows to the winner. Where the winner already has
--      a row with the same key, the loser's copy is deleted, because it is the
--      same SEC fact re-extracted under the other id.
--   3. Deletes the losers, which then have no child rows.
--   4. Sets the winner's dividend flag from raw.company_classification (the
--      issuer-level source, as in V0047), and sets active when the group had an
--      active row, or the winner traded within 14 days of the newest price.
--   5. Replaces ux_security_cik_ticker_type_dividend with
--      ux_security_cik_ticker_type on (cik, ticker, security_type).
--
-- Guards: the migration raises, and rolls back, if a table with a security_id
-- key that is not handled explicitly holds rows for a loser.

CREATE TEMP TABLE identity_winner ON COMMIT DROP AS
WITH px AS (
    SELECT security_id, count(*) AS px_rows
    FROM raw.market_data
    GROUP BY security_id
),
newest AS (
    SELECT max(observation_date) AS d FROM raw.market_data
),
ranked AS (
    SELECT s.security_id, s.cik, s.ticker, s.security_type, s.dividend, s.active,
           s.updated_at,
           COALESCE(px.px_rows, 0) AS px_rows,
           row_number() OVER (
               PARTITION BY s.cik, s.ticker, s.security_type
               ORDER BY COALESCE(px.px_rows, 0) DESC, s.active DESC,
                        s.updated_at DESC, s.security_id
           ) AS rn,
           bool_or(s.active) OVER (PARTITION BY s.cik, s.ticker, s.security_type)
               AS group_active,
           count(*) OVER (PARTITION BY s.cik, s.ticker, s.security_type) AS group_size
    FROM reference.securities s
    LEFT JOIN px USING (security_id)
    WHERE s.cik IS NOT NULL
)
SELECT r.cik, r.ticker, r.security_type,
       r.security_id AS winner_id,
       COALESCE(c.dividend, r.dividend) AS new_dividend,
       (r.group_active
        OR EXISTS (
            SELECT 1 FROM raw.market_data m, newest n
            WHERE m.security_id = r.security_id
              AND m.observation_date >= n.d - 14
        )) AS new_active
FROM ranked r
LEFT JOIN raw.company_classification c ON c.cik = r.cik
WHERE r.rn = 1 AND r.group_size > 1;

CREATE TEMP TABLE identity_loser ON COMMIT DROP AS
SELECT s.security_id AS loser_id, w.winner_id
FROM reference.securities s
JOIN identity_winner w
  ON w.cik = s.cik AND w.ticker = s.ticker AND w.security_type = s.security_type
WHERE s.security_id <> w.winner_id;

-- 2a. Tables whose key includes a natural column: a loser row is dropped when
--     the winner already has the same key, and re-pointed otherwise.
DELETE FROM audit.data_quality d
USING identity_loser l
WHERE d.security_id = l.loser_id
  AND EXISTS (SELECT 1 FROM audit.data_quality w
              WHERE w.security_id = l.winner_id AND w.as_of_date = d.as_of_date);
UPDATE audit.data_quality d SET security_id = l.winner_id
FROM identity_loser l WHERE d.security_id = l.loser_id;

DELETE FROM fundamentals.periodic_financials f
USING identity_loser l
WHERE f.security_id = l.loser_id
  AND EXISTS (SELECT 1 FROM fundamentals.periodic_financials w
              WHERE w.security_id = l.winner_id
                AND w.period_end = f.period_end
                AND w.fiscal_period = f.fiscal_period
                AND w.filed = f.filed);
UPDATE fundamentals.periodic_financials f SET security_id = l.winner_id
FROM identity_loser l WHERE f.security_id = l.loser_id;

DELETE FROM raw.dividend_data d
USING identity_loser l
WHERE d.security_id = l.loser_id
  AND EXISTS (SELECT 1 FROM raw.dividend_data w
              WHERE w.security_id = l.winner_id
                AND w.ex_dividend_date = d.ex_dividend_date
                AND w.provider = d.provider);
UPDATE raw.dividend_data d SET security_id = l.winner_id
FROM identity_loser l WHERE d.security_id = l.loser_id;

-- 2b. Tables keyed by security_id alone: the winner's row is kept. The foreign key
--     clean.company_profile -> raw.ticker_profile is checked at the end of this
--     step, not per statement, because the winner's profile row may not exist
--     until the move below. The constraint is restored to immediate afterwards.
ALTER TABLE clean.company_profile
    ALTER CONSTRAINT company_profile_source_profile_security_id_fkey
    DEFERRABLE INITIALLY DEFERRED;
-- Only this constraint is deferrable, so ALL affects nothing else.
SET CONSTRAINTS ALL DEFERRED;

UPDATE clean.company_profile t SET source_profile_security_id = l.winner_id
FROM identity_loser l WHERE t.source_profile_security_id = l.loser_id;

-- Where both rows exist, the winner keeps its own raw_payload, provider and
-- retrieved_at, but a business field that is NULL on the winner is filled from
-- the loser. Ten pairs differ in sector, industry or coupon values this way
-- (SLNHP, PCG-PC, PCG-PI, RILYL, RILYP, NHPAP); deleting the loser would lose them.
UPDATE raw.ticker_profile w SET
    sector = COALESCE(w.sector, lp.sector),
    industry = COALESCE(w.industry, lp.industry),
    coupon_type = COALESCE(w.coupon_type, lp.coupon_type),
    coupon_rate = COALESCE(w.coupon_rate, lp.coupon_rate),
    fixed_period_end = COALESCE(w.fixed_period_end, lp.fixed_period_end),
    floating_spread = COALESCE(w.floating_spread, lp.floating_spread),
    tax_status = COALESCE(w.tax_status, lp.tax_status),
    call_date = COALESCE(w.call_date, lp.call_date),
    liquidation_preference = COALESCE(w.liquidation_preference, lp.liquidation_preference)
FROM identity_loser l
JOIN raw.ticker_profile lp ON lp.security_id = l.loser_id
WHERE w.security_id = l.winner_id;

DELETE FROM raw.ticker_profile t
USING identity_loser l
WHERE t.security_id = l.loser_id
  AND EXISTS (SELECT 1 FROM raw.ticker_profile w WHERE w.security_id = l.winner_id);
UPDATE raw.ticker_profile t SET security_id = l.winner_id
FROM identity_loser l WHERE t.security_id = l.loser_id;

-- Check the deferred foreign key now, then restore the constraint to immediate.
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE clean.company_profile
    ALTER CONSTRAINT company_profile_source_profile_security_id_fkey
    NOT DEFERRABLE;

DELETE FROM preferred.contract_terms t
USING identity_loser l
WHERE t.security_id = l.loser_id
  AND EXISTS (SELECT 1 FROM preferred.contract_terms w WHERE w.security_id = l.winner_id);
UPDATE preferred.contract_terms t SET security_id = l.winner_id
FROM identity_loser l WHERE t.security_id = l.loser_id;

DELETE FROM preferred.security_terms t
USING identity_loser l
WHERE t.security_id = l.loser_id
  AND EXISTS (SELECT 1 FROM preferred.security_terms w WHERE w.security_id = l.winner_id);
UPDATE preferred.security_terms t SET security_id = l.winner_id
FROM identity_loser l WHERE t.security_id = l.loser_id;

DELETE FROM preferred.dividend_snapshot t
USING identity_loser l
WHERE t.security_id = l.loser_id
  AND EXISTS (SELECT 1 FROM preferred.dividend_snapshot w WHERE w.security_id = l.winner_id);
UPDATE preferred.dividend_snapshot t SET security_id = l.winner_id
FROM identity_loser l WHERE t.security_id = l.loser_id;

-- 2c. Tables whose primary key does not include security_id: plain re-pointing.
UPDATE audit.source_lineage t SET security_id = l.winner_id
FROM identity_loser l WHERE t.security_id = l.loser_id;
UPDATE clean.company_profile t SET reference_security_id = l.winner_id
FROM identity_loser l WHERE t.reference_security_id = l.loser_id;
UPDATE clean.ticker_profile t SET security_id = l.winner_id
FROM identity_loser l WHERE t.security_id = l.loser_id;
UPDATE raw.contract_documents t SET security_id = l.winner_id
FROM identity_loser l WHERE t.security_id = l.loser_id;
UPDATE raw.sec_documents t SET security_id = l.winner_id
FROM identity_loser l WHERE t.security_id = l.loser_id;
UPDATE analysis.investment_analyses t SET security_id = l.winner_id
FROM identity_loser l WHERE t.security_id = l.loser_id;

-- 2d. Guard: every other child table must hold no loser rows. Their primary keys
--     include security_id, so a re-point could collide silently. Stop if any do.
DO $$
DECLARE
    tbl text;
    n bigint;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'market.bar', 'market.bar_default', 'market.quote', 'market.quote_default',
        'market.trade', 'market.trade_default', 'model.features',
        'model.forward_returns', 'model.predictions', 'model.rankings', 'model.scores',
        'raw.market_data', 'raw.fmp_dcf', 'raw.fmp_filings', 'raw.fmp_statements'
    ] LOOP
        EXECUTE format(
            'SELECT count(*) FROM %s t JOIN identity_loser l ON t.security_id = l.loser_id',
            tbl) INTO n;
        IF n > 0 THEN
            RAISE EXCEPTION 'V0092: % loser rows in % need an explicit merge rule', n, tbl;
        END IF;
    END LOOP;
END $$;

-- 3. Losers now have no child rows; remove them.
DELETE FROM reference.securities s
USING identity_loser l
WHERE s.security_id = l.loser_id;

-- 4. Winner attributes. Done after the loser delete so the old unique key cannot
--    collide with the winner's new dividend value.
UPDATE reference.securities s
SET dividend = w.new_dividend,
    active = w.new_active,
    updated_at = now()
FROM identity_winner w
WHERE s.security_id = w.winner_id
  AND (s.dividend IS DISTINCT FROM w.new_dividend OR s.active IS DISTINCT FROM w.new_active);

-- 5. Identity index.
DROP INDEX IF EXISTS reference.ux_security_cik_ticker_type_dividend;
CREATE UNIQUE INDEX IF NOT EXISTS ux_security_cik_ticker_type
    ON reference.securities (cik, ticker, security_type);

-- Post-condition: no duplicate identities remain.
DO $$
DECLARE
    n bigint;
BEGIN
    SELECT count(*) INTO n FROM (
        SELECT 1 FROM reference.securities
        WHERE cik IS NOT NULL
        GROUP BY cik, ticker, security_type
        HAVING count(*) > 1
    ) d;
    IF n > 0 THEN
        RAISE EXCEPTION 'V0092: % identity groups still have more than one row', n;
    END IF;
END $$;
