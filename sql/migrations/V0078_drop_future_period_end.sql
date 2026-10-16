-- V0078 drop future period_end
--
-- WS4 step 6. V0050 quarantined the impossible `period_end` values in
-- fundamentals.periodic_financials (315 rows at the 2026-10-05 audit; 354 rows
-- at this writing) but left them in place, on the principle that recording a
-- defect is not the same as excluding it. The feature build was made safe
-- separately: features.py resolves a vintage's availability as
-- GREATEST(filed, period_end), so a forward-dated period waits until its own
-- date and never enters a trailing-four-quarter TTM (WS11). That closed the
-- look-ahead but left the shared table dirty, and two readers order by
-- period_end alone -- the /financials/{ticker} API and the Streamlit
-- Fundamentals tab -- so a 2039 period was served as the latest reported
-- vintage.
--
-- This migration removes the impossible rows outright and closes the registry
-- entries. A period that has not ended cannot have been reported, so the row is
-- unusable rather than merely early, and there is nothing to preserve: unlike a
-- look-ahead that needs a corrected date, a period_end after the run date has no
-- correct value to reconstruct. The extractor now applies the same ceiling
-- (extract_periodic_financials(as_of=...) via scripts/populate_fundamentals), so
-- a re-extraction cannot reintroduce them; the API and app queries are bounded
-- too, so even an unfixed writer could not surface one.
--
-- The 18 affected issuers at this writing: EVOH (2039-08-31), AAGH (2031-12-31),
-- NAII (2031-09-25), the PMT preferred complex (PMT, PMT-PA, PMT-PB, PMT-PC,
-- PMTU, PMTV, PMTW; 2030-09-30), QPRC (2029-06-30), and the HVII/HNOI/CLUS/ONEN
-- group (2026-12-31). No stored row has a `filed` date in the future, so the
-- period_end bound is the only writer-side anomaly of this class.
--
-- Only the period_end registry entries are resolved here. The `filed <
-- period_end` entries from V0050 stay open: features.py already clamps them with
-- GREATEST, and whether to repair or drop them is a separate decision.

DELETE FROM fundamentals.periodic_financials
WHERE period_end > CURRENT_DATE;

-- Close the quarantine entries. The registry is append-only, so resolution is
-- recorded by stamping resolved_at and describing the fix, never by deleting.
UPDATE audit.quarantined_values
SET resolved_at = now(),
    resolution_note =
        'Deleted by V0078: a period_end after the run date cannot have been '
        'reported, so the row is unusable rather than merely early. '
        'extract_periodic_financials() now takes an as_of ceiling and '
        'scripts/populate_fundamentals passes the run date, so a re-extraction '
        'cannot reintroduce a forward-dated period. The /financials/{ticker} API '
        'and the Streamlit Fundamentals tab are bounded by CURRENT_DATE too. The '
        'V0050 filed < period_end entries stay open; features.py clamps those '
        'with GREATEST(filed, period_end).'
WHERE resolved_at IS NULL
  AND table_schema = 'fundamentals'
  AND table_name = 'periodic_financials'
  AND column_name = 'period_end';
