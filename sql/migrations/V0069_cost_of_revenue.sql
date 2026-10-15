-- =====================================================================
-- V0069 cost_of_revenue
-- The total cost-of-revenue line, and the derived gross profit it enables.
--
-- Why this migration exists
-- ------------------------
-- V0068 added gross_profit, read only from the direct us-gaap:GrossProfit tag.
-- That left gross_margin with the thinnest coverage of the new block: 692 of
-- 2,635 rows on the latest date (26%), because only 839 of 2,926 candidate
-- filers tag the gross subtotal at all.
--
-- The gap is recoverable. Measured over the stored companyfacts payloads of the
-- active dividend universe:
--   * 1,177 filers tag a *total* cost-of-revenue concept
--     (CostOfRevenue or CostOfGoodsAndServicesSold);
--   * 403 of them report revenue and that cost line but no GrossProfit subtotal;
--   * a further 904 filers report revenue but no cost line at all, and stay
--     unrecoverable on this path.
--
-- V0068 declined to derive gross profit because a quarterly cost against a YTD
-- revenue would manufacture a figure the filer never stated. That concern was
-- measured and does not hold: within one (period_end, fp, filed) key the SEC
-- payload lists the shorter duration last, and the extractor's per-metric
-- overwrite keeps the last. Across the stored payloads the shorter duration was
-- last in 100% of 51,675 ambiguous cost keys and 125,412 ambiguous revenue keys,
-- so the revenue and cost stored on one row are both the quarterly figure. The
-- derivation is therefore the same operation free_cash_flow = ocf - capex has
-- always been.
--
-- Only the two total cost concepts are read. CostOfGoodsSold omits services cost
-- and CostOfServices omits goods cost; subtracting either from total revenue
-- would overstate gross profit, so a filer tagging only those keeps a NULL gross
-- profit. Coverage is recorded, never paid for with a partial cost line.
-- =====================================================================

-- The total cost of revenue. Stored because it is reported, and because the
-- derived gross_profit is only auditable if the line it was derived from is
-- visible.
ALTER TABLE fundamentals.periodic_financials
  ADD COLUMN IF NOT EXISTS cost_of_revenue NUMERIC;

COMMENT ON COLUMN fundamentals.periodic_financials.cost_of_revenue IS
  'Total cost of revenue over the fiscal period, from us-gaap CostOfRevenue or '
  'CostOfGoodsAndServicesSold. Narrow concepts (CostOfGoodsSold, CostOfServices) '
  'are deliberately not read: subtracting a partial cost from total revenue '
  'would overstate gross profit. NULL where the filer tags no total cost line.';

-- Re-state gross_profit: it is now the direct subtotal when tagged, else derived
-- as revenue - cost_of_revenue.
COMMENT ON COLUMN fundamentals.periodic_financials.gross_profit IS
  'Gross profit over the fiscal period. The direct us-gaap GrossProfit subtotal '
  'when the filer states it, otherwise revenue - cost_of_revenue from the total '
  'cost concepts only. NULL where neither the subtotal nor a total cost line is '
  'tagged -- absence of disclosure is not a zero margin.';
