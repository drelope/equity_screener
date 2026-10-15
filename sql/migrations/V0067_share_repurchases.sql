-- Share buybacks: cash paid by the issuer to repurchase its own shares.
--
-- The pipeline identified dividends but not the other half of capital return.
-- XBRL records repurchases in the financing section as a cash-flow (duration)
-- fact: PaymentsForRepurchaseOfCommonStock (3,392 stored filers) and
-- PaymentsForRepurchaseOfEquity (480, which also covers repurchases of
-- preferred stock). Stored per fiscal period and vintage in
-- fundamentals.periodic_financials, exactly like the other periodic metrics.
--
-- A filer that does not tag a repurchase has an unknown buyback, not a zero
-- one, so the column stays NULL and is never coalesced to zero.
BEGIN;

ALTER TABLE fundamentals.periodic_financials
  ADD COLUMN IF NOT EXISTS share_repurchases NUMERIC;

COMMENT ON COLUMN fundamentals.periodic_financials.share_repurchases IS
  'Cash paid to repurchase the issuer''s own shares over the fiscal period '
  '(us-gaap PaymentsForRepurchaseOfCommonStock, then PaymentsForRepurchaseOfEquity). '
  'Duration fact, reported in the financing section. NULL where the filer '
  'discloses no repurchase -- absence of a tag is not a zero buyback.';

COMMIT;
