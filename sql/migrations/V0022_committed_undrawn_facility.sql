-- Committed undrawn credit facilities (specification section 5.5, C4).
--
-- C4 compares debt maturing within 18 months against "total available liquid
-- reserves (Cash + Committed Undrawn Facilities)". V0018 measured cash alone
-- because committed capacity had not been extracted. It is a reported XBRL
-- balance -- LineOfCreditFacilityRemainingBorrowingCapacity -- disclosed by 888
-- stored filers, so cash-only overstated the maturity cliff on precisely the
-- firms holding a revolver alongside a near-term maturity.
--
-- Coverage is partial by nature and no attempt is made to fill the gap. A
-- filer that does not tag this has an unknown capacity, not a zero one; the
-- figure simply stays NULL and the C4 numerator omits it, keeping the measure
-- conservative in the direction a gate needs.
BEGIN;

ALTER TABLE fundamentals.periodic_financials
  ADD COLUMN IF NOT EXISTS committed_undrawn_facility NUMERIC;

COMMENT ON COLUMN fundamentals.periodic_financials.committed_undrawn_facility IS
  'Remaining borrowing capacity under committed credit facilities at the FY '
  'vintage. Added to cash in the C4 reserves denominator (section 5.5). NULL '
  'where the filer discloses no facility capacity -- absence of a tag is not a '
  'zero balance, and is never coalesced to one.';

INSERT INTO public.schema_migrations(version, name)
VALUES (22, 'committed_undrawn_facility')
ON CONFLICT (version) DO NOTHING;

COMMIT;