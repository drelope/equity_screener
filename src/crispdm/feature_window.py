"""Choosing which feature rows a scoring run should read.

``model.features`` holds one row per real observation date, so a security that
did not trade on the run date simply has no row for that date. Both consumers
used to read ``WHERE as_of_date = (SELECT MAX(as_of_date) ...)``, which silently
dropped every security that did not trade on the single latest date: 155 active
dividend payers on the 2026-10-02 run, 78 of them only one trading day stale.

They now read each security's most recent row within a tolerance window instead.
The window is defined once here so the scoring query and the dashboard query
cannot drift apart -- a consumer that quietly reverted to the common-date rule
would understate coverage while still returning rows.

Both consumers drive off ``reference.securities`` with a ``LATERAL`` join, so
the per-security lookup hits ``features_pkey`` once per active security instead
of scanning every feature row.

Note that carrying a row forward makes a security *eligible*; it does not make
it scoreable. Every carried row on 2026-10-02 still produced a NULL composite
because its present inputs fell below ``MIN_PRESENT_WEIGHT``, so this widened
the read window without changing any score.
"""

# The date window, relative to the latest observation in the table. Written out
# rather than passed in so the SQL stays self-contained and no caller can drift
# onto a different run date; it reads MAX(as_of_date) twice, which is an index
# probe thanks to idx_features_as_of (V0037).
_WINDOW = """
      g.as_of_date <= (SELECT MAX(as_of_date) FROM model.features)
      AND g.as_of_date >= (SELECT MAX(as_of_date) FROM model.features)
                           - make_interval(days => :carry_days)
"""


def carry_forward_days() -> int:
    """Tolerance in days; ``0`` restores the strict common-date behaviour."""
    from .config import settings

    return settings.feature_carry_forward_days


def _latest_row(sec_alias: str) -> str:
    """The per-security row lookup: newest feature row inside the window.

    ORDER BY ... LIMIT 1 rather than a correlated MAX because the correlated
    form gets de-correlated into a join over every feature row, while this stays
    a single index probe on features_pkey (security_id, as_of_date) that stops at
    the first hit.
    """
    return f"""
    SELECT g.* FROM model.features g
    WHERE g.security_id={sec_alias}.security_id
      AND {_WINDOW}    ORDER BY g.as_of_date DESC
    LIMIT 1
"""


def scoring_features_sql() -> str:
    """One feature row per active security, newest first within the window.

    Driven off reference.securities with a LATERAL join on purpose. The obvious
    alternative -- DISTINCT ON over model.features with a correlated MAX -- makes
    the planner evaluate the subquery once per feature row, and model.features
    holds 8.5M rows: 28s and 42.7M buffer hits, against ~10.7k index probes at
    0.1ms each here. The window is a per-security lookup, so drive it from the
    security list and let features_pkey (security_id, as_of_date) serve each
    probe.
    """
    return f"""
    SELECT f.*, s.ticker, s.security_type
    FROM reference.securities s
    JOIN LATERAL (
        {_latest_row("s")}
    ) f ON TRUE
    WHERE s.active = TRUE
    """


def dashboard_features_sql(columns: str) -> str:
    """Same row selection for the dashboard, plus the score join."""
    return f"""
SELECT s.ticker,s.security_type,f.as_of_date,{columns},
       sc.composite_score,sc.score_coverage
FROM reference.securities s
JOIN LATERAL (
    {_latest_row("s")}
) f ON TRUE
LEFT JOIN model.scores sc ON sc.security_id=f.security_id AND sc.as_of_date=f.as_of_date
WHERE s.active = TRUE
ORDER BY sc.composite_score DESC NULLS LAST
"""
