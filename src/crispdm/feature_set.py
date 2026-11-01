"""The declared model feature set.

This module is deliberately dependency-free: ``model`` needs the list, and
``versioning`` needs it to hash the feature definition, while ``features``
imports ``versioning``. Defining the list here keeps a single source of truth
without an import cycle (``model`` -> ``feature_set``, ``versioning`` ->
``feature_set``, ``features`` -> ``versioning``).
"""

FEATURES = [
    "dividend_yield",
    "dividend_growth",
    "earnings_payout",
    "fcf_payout",
    "dividend_coverage",
    "volatility_252d",
    "momentum_252d",
    "momentum_63d",
    # The two leverage ratios restored in V0011/V0012. They were computed,
    # persisted, and shown on the dashboard but absent from this list, so the
    # model could not see them -- the first features that speak to balance-sheet
    # stress rather than price. Coverage is 32-37% (debt_to_ebitda) and 60-62%
    # (interest_coverage) across the training period, both above the 20%
    # completeness floor.
    "debt_to_ebitda",
    "interest_coverage",
]
