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

# The anchor the window pivots on: the run date, bounded by the newest
# observation in the table. The default is that newest observation -- the
# nightly's behaviour -- but a re-scoring run (a scoring-policy change recomputes
# every historical date, not just the latest) binds ``:as_of`` to pivot the whole
# window on a chosen past date instead. Both are read from the bound parameter so
# no caller can interpolate a different date in; it reads MAX(as_of_date) twice,
# which is an index probe thanks to idx_features_as_of (V0037).
_ANCHOR = "COALESCE(CAST(:as_of AS date), (SELECT MAX(as_of_date) FROM model.features))"
_WINDOW = f"""
      g.as_of_date <= {_ANCHOR}
      AND g.as_of_date >= {_ANCHOR}
                           - make_interval(days => :carry_days)
"""


def carry_forward_days() -> int:
    """Tolerance in days; ``0`` restores the strict common-date behaviour."""
    from .config import settings

    return settings.feature_carry_forward_days


def feature_window_pit_metadata(
    as_of=None, *, include_historical: bool = False, carry_days: int | None = None
):
    """Draft PIT metadata for consumers of this window (RM-01/RM-02 integration)."""
    from .pit import feature_window_pit_context

    resolved_carry = carry_forward_days() if carry_days is None else int(carry_days)
    return feature_window_pit_context(
        as_of=as_of,
        carry_days=resolved_carry,
        include_historical=include_historical,
    )


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


def scoring_features_sql(include_historical: bool = False) -> str:
    """One feature row per active security, newest first within the window.

    Driven off reference.securities with a LATERAL join on purpose. The obvious
    alternative -- DISTINCT ON over model.features with a correlated MAX -- makes
    the planner evaluate the subquery once per feature row, and model.features
    holds 8.5M rows: 28s and 42.7M buffer hits, against ~10.7k index probes at
    0.1ms each here. The window is a per-security lookup, so drive it from the
    security list and let features_pkey (security_id, as_of_date) serve each
    probe.

    Callers bind two parameters: ``carry_days`` and ``as_of``. Bind ``as_of`` to
    ``None`` for the nightly (the window pivots on the newest feature date); bind
    a date to re-score that historical date point-in-time. The bound date can only
    move the window *earlier* than the newest row, never later, so it cannot read
    a future-dated feature.

    ``include_historical`` also reads securities recovered from EDGAR after they
    left the current snapshot (``historical = TRUE``). Off by default so the
    nightly never scores a delisted name against carried-forward features; the
    backfill stages turn it on for a chosen past date.
    """
    universe = (
        "(s.active = TRUE OR s.historical = TRUE)" if include_historical else "s.active = TRUE"
    )
    return f"""
    SELECT f.*, s.ticker, s.security_type
    FROM reference.securities s
    JOIN LATERAL (
        {_latest_row("s")}
    ) f ON TRUE
    WHERE {universe}
    """


def dashboard_features_sql(columns: str) -> str:
    """Same row selection for the dashboard, plus the score and preferred terms.

    The preferred terms (liquidation preference, first call date and the most
    recent dividend event) come from ``preferred.v_security_terms``, the same
    1:1 view the Security detail page reads. Resolving them here as well is what
    let the two pages disagree: this query took issuer-level par/aggregate as a
    liquidation preference while the detail page did not, and this query's
    dividend pick ignored the XBRL concept, so a preferred series often showed
    its issuer's common dividend. One view, one answer.

    The view is keyed by ``security_id`` (primary key), so a plain join holds
    exactly one row per security and cannot fan the dashboard out.
    """
    return f"""
SELECT s.ticker,s.security_type,s.currency,f.as_of_date,{columns},
       sc.composite_score,sc.score_coverage,
       v.ex_date AS ex_date,
       v.dividend_amount AS dividend_amount,
       v.liquidation_preference AS liquidation_preference,
       v.first_call_date AS first_call_date
FROM reference.securities s
JOIN LATERAL (
    {_latest_row("s")}
) f ON TRUE
LEFT JOIN model.scores sc ON sc.security_id=f.security_id AND sc.as_of_date=f.as_of_date
LEFT JOIN preferred.v_security_terms v ON v.security_id=s.security_id
WHERE s.active = TRUE
ORDER BY sc.composite_score DESC NULLS LAST
"""
