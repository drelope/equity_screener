"""Per-share dividend sanity ceilings shared by ingestion, features and checks.

The two caps are deliberately different. SEC XBRL occasionally tags the period's
aggregate dollars as a per-share concept, so a real per-share dividend there is
far below ``$1,000``. OpenBB/yfinance history is not split-restated all the way
back: a valid pre-split payment can legitimately be tens or hundreds of thousands
of dollars per (unadjusted) share. A blanket OpenBB ``$1,000`` cap would throw
that history away, so the OpenBB ceiling only removes the absurd tail.
"""

MAX_PER_SHARE_DIVIDEND = 1000.0

#: Above this, an OpenBB per-share amount is not a usable pre-split value. The
#: largest observed valid-looking pre-split payments are around ``$205,000``
#: (CMCT); the known defect rows start at ``$1,764,000`` (CETX) and reach
#: ``$226,799,993,000,000`` (TOPS). The gap is two orders of magnitude.
MAX_OPENBB_PER_SHARE_DIVIDEND = 1_000_000.0
