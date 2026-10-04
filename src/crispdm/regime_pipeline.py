"""Connect the regime layer to a scoring run.

:mod:`src.crispdm.regime` is deliberately pure -- scalars in, scalars out, no
database and no pandas -- so the arithmetic in the design specification can be
tested against the tables that describe it. This module is the other half: it
maps a warehouse feature frame onto the layer's inputs, calls the scalar
functions, and writes the result back.

Two things this module decides, and they are the only two decisions it makes.

**Which columns are inputs.** :data:`CVS_SOURCE_COLUMNS` names the mapping from
``model.features`` to CVS metrics. Three of the five CVS legs have no column in
the warehouse today -- ``refinancing_wall``, ``quick_liquidity`` and
``credit_rating`` -- and they are absent rather than filled with zero or a
plausible default, because the layer's entire premise is that an unreported
metric is not a good one.

**Whether the layer is allowed to move a score.** It is not, by default. See
:func:`apply_regime_layer` for the measurement behind that default. The layer
publishes its full output either way, so the state of the world is visible in
the database rather than inferred from a column that never changed.
"""

import pandas as pd

from .regime import (
    CREDIT_MODIFIER_TABLE,
    CVS_BRACKETS,
    CVS_CORE_LEVERAGE,
    CVS_IMPUTED_SCORE,
    CVS_MODERATE_MAX_SCORE,
    CVS_RATING_BRACKETS,
    CVS_STRONG_MAX_SCORE,
    CVS_STRONG_REQUIRED_METRICS,
    CVS_WEIGHTS,
    OVERRIDE_CAPS,
    UNSCORABLE_CVS_MODIFIER,
    MacroState,
    credit_environment,
    determine_market_regime,
    evaluate_dividend_safety_override,
    final_score,
)

#: ``model.features`` column -> CVS metric name. A leg not listed here has no
#: stored source and is treated as absent, which the CVS then imputes at
#: :data:`~src.crispdm.regime.CVS_IMPUTED_SCORE`.
#:
#: ``refinancing_wall`` needs a maturity schedule that XBRL does not expose as
#: a fact; ``quick_liquidity`` needs current-basis cash and current-basis
#: liabilities, and the stored ``liabilities`` column mixes ``Liabilities`` with
#: ``LiabilitiesCurrent`` because both are fallback tags for one slot, so a
#: quick ratio computed from it would be wrong for whichever basis lost;
#: ``credit_rating`` has no feed at all. Deriving the first two is a real
#: project and is not attempted here.
CVS_SOURCE_COLUMNS = {
    # Raw observations, not bracket points -- compute_cvs and compute_cvs_frame
    # both bracket them against the section 4.3 tables first.
    "net_debt_to_ebitda": "debt_to_ebitda",
    "interest_coverage": "interest_coverage",
    # V0016. Was NULL for every row until that migration added
    # fundamentals.periodic_financials.current_liabilities and the features
    # rebuild derived this from it. Until the ETL runs it back, the column is
    # still NULL everywhere and the CVS is unscorable for the whole universe --
    # which is the correct reading of "we have not measured this", and the
    # reason the layer stays gated rather than scoring on an imputed leg.
    "quick_liquidity": "quick_liquidity",
    "refinancing_wall": "refinancing_wall",
    "credit_rating": "credit_rating",
}

#: Threshold for each evaluable circuit breaker. ``C4``/``C5`` have no stored
#: source yet; their thresholds are stated here so the mapping is complete when
#: the feeds land, and so an absent column is visibly unsourced rather than
#: quietly unevaluated.
CIRCUIT_BREAKER_THRESHOLDS = {
    "C1": ("fcf_payout", lambda v: v < 0.0),  # FCF drain
    "C2": ("debt_to_ebitda", lambda v: v > 5.0),  # net debt / EBITDA
    "C3": ("interest_coverage", lambda v: v < 1.5),  # interest coverage
    # C4 reads the derived maturity cliff, not a raw maturity bucket. The first
    # implementation pointed it at a column named refinancing_wall_2y that has
    # never existed and set the threshold at 0.5, which is the midpoint of the
    # CVS bracket table for this metric rather than the condition itself: the
    # specification breaches C4 when maturities *exceed* reserves, which is a
    # ratio above 1.0. At 0.5 the breaker fired on a company that could cover
    # half its 18-month maturities twice over.
    "C4": ("refinancing_wall", lambda v: v > 1.0),  # maturities exceed cash
    "C5": ("credit_rating", lambda v: v >= 3),  # junk-scale rating indicator
}

#: Circuit-breaker inputs mapped to the columns that supply them. Built from
#: :data:`CIRCUIT_BREAKER_THRESHOLDS`, so a lever cannot have a threshold
#: without a column and vice versa.
#:
#: ``C4`` draws on the contractual maturity ladder, which 2,680 of 7,079 stored
#: companyfacts disclose (V0018) -- the specification had recorded it as
#: unavailable. ``C5`` needs an agency rating feed, which the warehouse does not
#: carry and which no XBRL concept supplies. C5 is therefore still an absent
#: *source* rather than a missing value, and the distinction is load-bearing --
#: see :func:`evaluate_breakers`.
CIRCUIT_BREAKER_SOURCES = {
    name: (CIRCUIT_BREAKER_THRESHOLDS[name][0],) for name in CIRCUIT_BREAKER_THRESHOLDS
}

#: ``regime_gate_reason`` values, so a reader can tell an inert layer from a
#: broken one.
GATE_MACRO_ABSENT = "macro_feed_absent"
GATE_CVS_INCOMPLETE = "cvs_inputs_incomplete"
GATE_BREAKERS_UNEVALUABLE = "circuit_breakers_unevaluable"


def macro_state_from_row(row) -> MacroState:
    """Build a :class:`MacroState` from a macro observation row.

    A row with a value but no vintage is treated as **absent**, not as present.
    Section 9 of the design specification forbids scoring against the current
    vintage, so an observation that cannot be placed in time cannot be used to
    move a score; using it anyway would be a look-ahead with no way to detect
    it later.
    """
    if row is None:
        return MacroState(None, None, None)
    level = row.get("c_level")
    delta = row.get("c_delta")
    vintage = row.get("vintage")
    if level is None or delta is None or vintage is None:
        return MacroState(None, None, None)
    return MacroState(float(level), float(delta), vintage)


def compute_cvs_frame(frame):
    """Vectorised :func:`~src.crispdm.regime.compute_cvs` over a feature frame.

    One call per nightly run rather than 5,443 scalar calls, and the imputation
    arithmetic stays in exactly one place. Returns a DataFrame of
    ``cvs_score``/``cvs_coverage``/``cvs_tier``/``cvs_missing_core`` indexed
    like ``frame``.

    The scalar version remains the reference; ``tests/test_regime_pipeline.py``
    asserts the two agree row for row, including the unscorable path, so this
    cannot drift into a second set of rules.
    """
    metrics = {}
    for metric, column in CVS_SOURCE_COLUMNS.items():
        if column in frame.columns:
            metrics[metric] = pd.to_numeric(frame[column], errors="coerce")

    if not metrics:
        empty = pd.Series([None] * len(frame), index=frame.index, dtype=object)
        return pd.DataFrame(
            {
                "cvs_score": pd.Series([None] * len(frame), index=frame.index, dtype="float64"),
                "cvs_coverage": pd.Series(0.0, index=frame.index, dtype="float64"),
                "cvs_tier": empty,
                "cvs_missing_core": pd.Series([""] * len(frame), index=frame.index, dtype=object),
            }
        )

    # Every weight carries its contribution, and every leg is bracketed first.
    # A leg with no column contributes the imputed 50 points; a leg with a
    # column contributes its section 4.3 bracket, or 50 where the value is
    # absent. This is the section 4.4 rule: missing is imputed conservatively,
    # never dropped and never zeroed.
    #
    # Bracketing happens here rather than being assumed of the caller because
    # the inputs are raw ratios. Summing them directly adds a leverage multiple
    # of 2.0 and an agency rating of 2.0 to the same total as though they were
    # both 0-100 scores -- which is what the first version did, and it made
    # every company's CVS a fraction of a point below any tier boundary.
    total = pd.Series(0.0, index=frame.index, dtype="float64")
    measured = pd.Series(0.0, index=frame.index, dtype="float64")
    for metric, weight in CVS_WEIGHTS.items():
        if metric in metrics:
            raw = metrics[metric]
            present = raw.notna()
            points = _bracket_series(metric, raw)
            total = total + points.where(present, CVS_IMPUTED_SCORE) * weight
            measured = measured + present.astype(float) * weight
        else:
            total = total + CVS_IMPUTED_SCORE * weight

    def present(metric):
        if metric in metrics:
            return metrics[metric].notna()
        return pd.Series(False, index=frame.index, dtype=bool)

    # Core evidence floor: one leverage leg and a liquidity measure. Absent
    # quick_liquidity means the floor is never met, which is why every row
    # lands on 'unscorable' today.
    has_leverage = present(CVS_CORE_LEVERAGE[0]) | present(CVS_CORE_LEVERAGE[1])
    has_liquidity = present("quick_liquidity")
    scoreable = has_leverage & has_liquidity

    # Reported exactly as the scalar reference reports it: an unscorable row
    # lists both core leverage metrics, because the floor was not met and the
    # row is short of evidence as a whole rather than on one leg. Building it
    # by string concatenation over a mask produced an empty string for fully
    # present rows and the wrong single name for a half-present unscorable row,
    # so it is derived from the two boolean masks instead.
    missing_core = pd.Series([""] * len(frame), index=frame.index, dtype=object)
    for metric in CVS_CORE_LEVERAGE:
        missing_core = missing_core.mask(~present(metric), metric)
    missing_core = missing_core.mask(
        ~present(CVS_CORE_LEVERAGE[0]) & ~present(CVS_CORE_LEVERAGE[1]),
        ",".join(CVS_CORE_LEVERAGE),
    )
    missing_core = missing_core.mask(~scoreable, ",".join(CVS_CORE_LEVERAGE))

    has_required = (
        present(CVS_STRONG_REQUIRED_METRICS[0])
        & present(CVS_STRONG_REQUIRED_METRICS[1])
        & present(CVS_STRONG_REQUIRED_METRICS[2])
    )

    tier = pd.Series("high", index=frame.index, dtype=object)
    tier = tier.mask(total < CVS_MODERATE_MAX_SCORE, "moderate")
    tier = tier.mask((total < CVS_STRONG_MAX_SCORE) & has_required, "strong")
    tier = tier.mask(~scoreable, "unscorable")

    return pd.DataFrame(
        {
            "cvs_score": total.where(scoreable),
            "cvs_coverage": measured.where(scoreable, 0.0),
            "cvs_tier": tier,
            "cvs_missing_core": missing_core,
        }
    )


#: Section 4.3 thresholds per metric, in ascending order for a low-is-good leg
#: and descending for a high-is-good one. Read straight off the scalar tables so
#: the two implementations cannot disagree about where a bracket starts; only
#: the evaluation is expressed as a comparison because that vectorises.
_BRACKET_STEPS = {
    metric: (
        tuple(threshold for threshold, _ in table),
        tuple(points for _, points in table),
        table[0][0] > table[-1][0],
    )
    for metric, table in {**CVS_BRACKETS, "credit_rating": CVS_RATING_BRACKETS}.items()
}


def _bracket_series(metric: str, raw):
    """Vectorised :func:`~src.crispdm.regime.bracket_score`.

    The scalar version is the reference; ``tests/test_regime_pipeline.py``
    asserts they agree row for row. The reduction here is "first bracket the
    value satisfies", which is the same rule, and expressing it as a comparison
    rather than a Python loop is the whole reason this module exists.
    """
    thresholds, points, descending = _BRACKET_STEPS[metric]
    out = pd.Series(100.0, index=raw.index, dtype="float64")
    # Best bracket first, so the first satisfaction wins and later ones cannot
    # overwrite it.
    for threshold, points_at in zip(reversed(thresholds), reversed(points)):
        satisfied = raw >= threshold if descending else raw <= threshold
        out = out.where(~satisfied, points_at)
    return out


def evaluate_breakers(frame, cvs_score, macro: MacroState, breaker_sources=None):
    """Circuit-breaker flags per row, distinguishing two kinds of absence.

    Returns ``(flags, caps, unavailable)``.

    The layer treats an unknown breaker as breached -- that is
    :func:`~src.crispdm.regime.evaluate_dividend_safety_override`'s rule and it
    is right for a *company*: an unevaluated lever on one firm means that
    firm's solvency is unknown, and unknown is not safe.

    It is wrong for a *source*. ``C4`` and ``C5`` are unsourced for all 5,443
    securities because the warehouse has no maturity schedule and no rating
    feed, and that is a statement about our ingestion, not about any company.
    Failing closed on it would put every security at two breaches, hence RED
    and a 0.20 cap, on the grounds that we have not built an integration --
    publishing 5,443 insolvency verdicts as though we had.

    So a breaker with no source is **excluded** from the count and named in
    ``unavailable``. A breaker with a source that is missing for one row still
    fails closed for that row, because that is the per-company case the rule
    was written for.
    """
    sources = CIRCUIT_BREAKER_SOURCES if breaker_sources is None else breaker_sources
    columns = {
        name: sources[name][0]
        for name in sources
        if sources.get(name) and sources[name][0] in frame.columns
    }
    missing_sources = [name for name in sorted(sources) if name not in columns]

    flags, caps, warnings, exemptions = [], [], [], []
    for position in range(len(frame)):

        def value_of(name):
            column = columns.get(name)
            if column is None:
                return None
            raw = pd.to_numeric(frame[column], errors="coerce").iloc[position]
            # Missing for this row -> None, which the scalar rule reads as a
            # breach. That is the per-company fail-closed path.
            return None if pd.isna(raw) else raw

        # The C4 fallback needs two columns that no breaker reads directly, so
        # the row view is not just the breaker columns -- it is those plus the
        # fallback inputs. Building it from ``columns`` alone silently dropped
        # ``quick_liquidity`` (nothing reads it as a breaker), which made every
        # missing ladder look unevaluable and warned on rows the proxies
        # actually cleared.
        row = {column: value_of(name) for name, column in columns.items()}
        for extra in (*C4_FALLBACK_COLUMNS, DEBT_PRESENCE_COLUMN):
            if extra in frame.columns and extra not in row:
                raw = pd.to_numeric(frame[extra], errors="coerce").iloc[position]
                row[extra] = None if pd.isna(raw) else raw

        # An unsourced breaker is passed as a definite pass so it does not count
        # against the row, and is named in ``missing_sources`` so the reader
        # knows the verdict did not rest on it.
        cvs_value = cvs_score.iloc[position]
        conditions = {
            name: (_evaluate_breaker(name, value_of(name), row) if name in columns else False)
            for name in sources
        }

        # Section 5.5's audit warning for C4, recorded per row so the count of
        # unverifiable maturity cliffs is visible in the database rather than
        # only in this function's return value.
        if "C4" in columns and value_of("C4") is None:
            _, evaluable = _c4_fallback_verdict(row)
            if not evaluable:
                warnings.append(position)

        # The EXEMPT notation. Recorded per row because a pass and an exemption
        # are different claims: one says the lever was evaluated and cleared,
        # the other says the lever did not apply. Collapsing them would make an
        # unlevered company look as though its leverage had been tested.
        if not _has_reportable_debt(row):
            exemptions.append(position)

        flag, cap = _override_with_exclusions(conditions, cvs_value, macro, len(missing_sources))
        flags.append(flag)
        caps.append(cap)
    return (
        flags,
        caps,
        ",".join(missing_sources) if missing_sources else None,
        len(warnings),
        len(exemptions),
    )


#: Section 5.5's fallback for C4, used only when a filer discloses no maturity
#: ladder at all. The specification's own wording matters here: with schedules
#: absent, C4 is called *Safe* when Quick Liquidity >= 1.20x and Net Debt /
#: EBITDA <= 2.0x, and otherwise "flags an audit warning".
#:
#: An audit warning is not a breach, and treating it as one is the single
#: largest source of wrong overrides in this module. 3,915 of 4,907 securities
#: disclose no maturity ladder; failing them closed on missing footnote data
#: pushed every one of them to C4-true, and two breaches with it, so 90% of the
#: universe printed RED. That is the module docstring's exact failure mode --
#: publishing insolvency verdicts on the grounds that an integration was never
#: built. Disclosure of a footnote schedule is not evidence of a maturity cliff.
C4_FALLBACK_QUICK_LIQUIDITY_MIN = 1.20
C4_FALLBACK_NET_DEBT_TO_EBITDA_MAX = 2.0

#: Columns the C4 fallback reads when the maturity ladder is absent. Both are
#: derived in ``model.features``: ``quick_liquidity`` by V0016 (current-basis
#: cash over current-basis liabilities) and ``debt_to_ebitda`` as the CVS
#: leverage leg. Either one missing leaves the fallback unevaluable, which is
#: reported as an audit warning rather than quietly resolving to Safe.
C4_FALLBACK_COLUMNS = ("quick_liquidity", "debt_to_ebitda")


#: Breakers that only exist for a firm carrying debt. Net Debt / EBITDA and
#: Interest Coverage are undefined for a firm with no interest-bearing
#: instruments: there is no ratio to compute, and forcing one produces either
#: a divide-by-zero artefact or an infinite ratio that reads as the worst
#: possible score.
#:
#: For those firms the correct verdict is EXEMPT -- a pass with a notation, not
#: a penalty. Treating "no debt" as "debt disclosure withheld" conflates a
#: clean balance sheet with an incomplete data pull and puts a firm with
#: nothing to repay into the same bucket as one hiding its obligations.
#:
#: Fail-closed is untouched where it belongs: if ``debt`` is present and
#: positive, the firm has debt instruments, so a missing ratio is a real
#: disclosure gap and still fails closed.
DEBT_EXEMPT_BREAKERS = ("C2", "C3")

#: ``model.features`` column establishing that a firm has reportable debt
#: instruments. Absent or zero means none. This is a precondition, not a
#: threshold, and it is why ``debt`` is carried as a feature column: without it
#: "no debt" and "debt never extracted" are the same NULL.
DEBT_PRESENCE_COLUMN = "debt"


def _has_reportable_debt(row):
    """Whether the filer reports any interest-bearing obligation.

    Zero is treated as "none": a filer that tags its debt balance at zero has
    answered the question affirmatively, which is different from never tagging
    debt at all. Both mean EXEMPT for C2 and C3; they differ only in how much we
    trust the absence.
    """
    debt = row.get(DEBT_PRESENCE_COLUMN)
    if debt is None:
        return False
    try:
        return float(debt) > 0.0
    except (TypeError, ValueError):
        return False


def _c4_fallback_verdict(row):
    """C4 for a filer with no maturity ladder.

    Returns ``(breached, evaluable)``. ``breached`` is always ``False``: the
    specification's response to an absent schedule is an audit warning, and an
    audit warning is a data-quality statement, not a dividend-safety verdict.
    ``evaluable`` is False when the proxies are missing, so the caller can tell
    "checked and clear" from "could not check".
    """
    quick = row.get("quick_liquidity")
    leverage = row.get("debt_to_ebitda")
    if quick is None or leverage is None:
        return False, False
    return False, bool(
        quick >= C4_FALLBACK_QUICK_LIQUIDITY_MIN and leverage <= C4_FALLBACK_NET_DEBT_TO_EBITDA_MAX
    )


def _evaluate_breaker(name: str, value, row=None):
    """Evaluate one lever, returning ``None`` when its input is unknown.

    ``row`` supplies the extra columns that C4's fallback and the C2/C3
    precondition need. It is only consulted when the primary input is missing,
    so a disclosed maturity ladder always wins over its proxies.
    """
    if name == "C4" and value is None:
        breached, _evaluable = _c4_fallback_verdict(row or {})
        return breached
    # The debt precondition is checked before the missing-value rule, and that
    # ordering is the whole point. A firm with no debt instruments is not a
    # firm whose disclosure failed -- there is no ratio to disclose, so its
    # absence carries no information. Checking fail-closed first would read
    # every unlevered company as an unevaluated lever.
    if name in DEBT_EXEMPT_BREAKERS and not _has_reportable_debt(row or {}):
        return False
    if value is None:
        return None
    if name not in CIRCUIT_BREAKER_THRESHOLDS:
        raise KeyError(f"no evaluator for circuit breaker {name!r}")
    return bool(CIRCUIT_BREAKER_THRESHOLDS[name][1](value))


def _debt_exempt_mask(frame, exemption_count):
    """Per-row boolean: C2 and C3 did not apply because there is no debt.

    Returns False for every row when ``debt`` is not available, because then the
    precondition could not be evaluated at all and reporting an exemption would
    be an unearned pass. Without that guard a build that forgot to carry the
    column would exempt the entire universe.
    """
    if DEBT_PRESENCE_COLUMN not in frame.columns or exemption_count == 0:
        return pd.Series(False, index=frame.index, dtype=bool)
    debt = pd.to_numeric(frame[DEBT_PRESENCE_COLUMN], errors="coerce")
    return debt.isna() | (debt <= 0)


def _c4_audit_warning_mask(frame, breaker_sources, warning_count):
    """Per-row boolean: this row's C4 could not be evaluated at all.

    A scalar count would answer "how many" but not "which", and the rows that
    matter are the ones an operator has to go and fix. Returns False for every
    row when C4 has no source at all, since an unsourced lever is a different
    condition entirely and is reported through ``breakers_unavailable``.
    """
    sources = CIRCUIT_BREAKER_SOURCES if breaker_sources is None else breaker_sources
    column = sources.get("C4", (None,))[0]
    if column is None or column not in frame.columns or warning_count == 0:
        return pd.Series(False, index=frame.index, dtype=bool)
    maturity = pd.to_numeric(frame[column], errors="coerce")
    quick = (
        pd.to_numeric(frame["quick_liquidity"], errors="coerce")
        if "quick_liquidity" in frame.columns
        else pd.Series(float("nan"), index=frame.index)
    )
    leverage = (
        pd.to_numeric(frame["debt_to_ebitda"], errors="coerce")
        if "debt_to_ebitda" in frame.columns
        else pd.Series(float("nan"), index=frame.index)
    )
    absent = maturity.isna()
    unverifiable = absent & (quick.isna() | leverage.isna())
    return unverifiable.fillna(False)


def _override_with_exclusions(conditions, cvs_value, macro, excluded_count):
    """Evaluate the override, discounting excluded breakers.

    Delegates to the scalar reference when nothing was excluded, so the
    authoritative case cannot drift. Otherwise the levers are evaluated from
    the surviving ones, with an unsourced lever contributing a pass rather than
    a breach.
    """
    if excluded_count == 0:
        return evaluate_dividend_safety_override(
            conditions["C1"],
            conditions["C2"],
            conditions["C3"],
            conditions["C4"],
            conditions["C5"],
            cvs_value,
            _c_level(macro),
            _c_delta(macro),
        )

    breaches = sum(1 for condition in conditions.values() if condition is None or condition)
    if breaches >= 2:
        return "RED", OVERRIDE_CAPS["RED"]
    if breaches == 1 and _macro_stressed(macro):
        return "SYSTEMIC_RED", OVERRIDE_CAPS["SYSTEMIC_RED"]
    if breaches == 1:
        return "YELLOW", OVERRIDE_CAPS["YELLOW"]
    if cvs_value is not None and cvs_value >= CVS_MODERATE_MAX_SCORE:
        return "YELLOW", OVERRIDE_CAPS["YELLOW"]
    # GREEN asserts nothing is wrong, from the levers that exist. Defensible
    # but a weaker claim than the real thing, which ``breakers_unavailable``
    # lets the reader see.
    return "GREEN", OVERRIDE_CAPS["GREEN"]


def _macro_stressed(macro: MacroState) -> bool:
    return _c_delta(macro) <= -0.75 or _c_level(macro) <= -1.0


def _c_level(macro: MacroState) -> float:
    return float(macro.c_level) if macro.present else 0.0


def _c_delta(macro: MacroState) -> float:
    return float(macro.c_delta) if macro.present else 0.0


def layer_readiness(frame, macro: MacroState) -> list[str]:
    """Why the layer cannot move scores yet. Empty means it can.

    A single row-specific readiness is not meaningful -- a run is gated by
    whether its *inputs* exist, which is a property of the pipeline, not of any
    one security.
    """
    reasons = []
    if not macro.present:
        reasons.append(GATE_MACRO_ABSENT)
    if "cvs_tier" in frame.columns and bool((frame["cvs_tier"] == "unscorable").all()):
        reasons.append(GATE_CVS_INCOMPLETE)
    if "breakers_unavailable" in frame.columns and any(frame["breakers_unavailable"]):
        reasons.append(GATE_BREAKERS_UNEVALUABLE)
    return reasons


def apply_regime_layer(
    scores,
    macro: MacroState = MacroState(None, None, None),
    *,
    apply_scores=False,
    breaker_sources=None,
):
    """Attach regime, CVS, modifier and override columns to a scored frame.

    Adds the ten V0015 columns. ``composite_score`` is returned unchanged
    unless ``apply_scores=True``.

    The default is off, and the reason is measured rather than cautious. On the
    warehouse as it stands, ``quick_liquidity`` and ``refinancing_wall`` have no
    stored source, so every row's CVS is unscorable and every row draws the same
    0.85 provisional modifier. A uniform multiplier cannot reorder anything, so
    applying the layer today would move the whole distribution down by 15% and
    publish a number that looks adjusted while carrying no cross-sectional
    information. It would also assert a credit verdict from three of five
    circuit breakers, which is why ``breakers_unavailable`` is published
    alongside ``override_flag``.

    So the layer runs, computes, and publishes; it just does not rescale. The
    gate reason is written to ``regime_gate_reason`` so the next run can tell
    "nothing to apply" from "nothing wrong found".

    Passing ``apply_scores=True`` with the inputs still absent is allowed. It is
    a deliberate escape hatch for evaluating the layer end to end, not a
    supported configuration.
    """
    x = scores.copy()
    frame_index = x.index

    cvs = compute_cvs_frame(x)
    x["cvs_score"] = cvs["cvs_score"]
    x["cvs_coverage"] = cvs["cvs_coverage"]
    x["cvs_tier"] = cvs["cvs_tier"]
    x["cvs_missing_core"] = cvs["cvs_missing_core"]

    # Macro absent -> the section 5.4 neutral baseline, which reads Normal after
    # the Accommodative-boundary fix, not the mildest environment.
    c_level = float(macro.c_level) if macro.present else 0.0
    c_delta = float(macro.c_delta) if macro.present else 0.0
    environment = credit_environment(c_level, c_delta)
    # No economic leg is stored, so the phase-space reading is credit-only.
    # Passing 0.0 for the economic leg is the neutral baseline, and the
    # classifier's Tier 1a Recovery gate cannot fire without a negative credit
    # level, so the result is a credit-driven regime rather than a full
    # two-coordinate classification. Recorded as such by macro_vintage.
    regime = determine_market_regime(0.0, 0.0, c_level, c_delta)

    modifiers = []
    for tier in x["cvs_tier"]:
        if tier == "unscorable":
            modifiers.append(UNSCORABLE_CVS_MODIFIER["benign"])
        else:
            modifiers.append(CREDIT_MODIFIER_TABLE[environment][tier])

    flags, caps, unavailable, c4_audit_warnings, debt_exemptions = evaluate_breakers(
        x, x["cvs_score"], macro, breaker_sources
    )

    x["market_regime"] = regime
    x["credit_environment"] = environment
    x["credit_modifier"] = modifiers
    x["override_flag"] = flags
    x["score_cap"] = caps
    x["macro_vintage"] = macro.vintage if macro.present else None
    # Which levers the verdict did not rest on. A GREEN from three of five
    # breakers is a weaker claim than one from five, and a reader cannot tell
    # the difference from the flag alone.
    x["breakers_unavailable"] = unavailable
    # Section 5.5's audit warning, per row: this filer discloses no maturity
    # ladder and the Quick Liquidity / Net Debt proxies were missing too, so
    # C4 is unverifiable rather than clear. Recorded as a flag so the number of
    # such rows is queryable and cannot be mistaken for a pass.
    x["c4_audit_warning"] = _c4_audit_warning_mask(x, breaker_sources, c4_audit_warnings)
    x["debt_exempt"] = _debt_exempt_mask(x, debt_exemptions)

    reasons = layer_readiness(x, macro)
    x["regime_gate_reason"] = ",".join(reasons) if reasons else None

    if apply_scores:
        adjusted = [
            final_score(cs, m, cap) if pd.notna(cs) else cs
            for cs, m, cap in zip(x["composite_score"], modifiers, x["score_cap"])
        ]
        x["composite_score"] = adjusted
        x["composite_score_unadjusted"] = scores.loc[frame_index, "composite_score"]

    return x


def summarize(frame):
    """Human-readable state of the layer for a run's console output."""
    reasons = layer_readiness(
        frame,
        MacroState(None, None, None) if frame["macro_vintage"].isna().all() else _any_macro(frame),
    )
    lines = [
        f"  Regime layer: {frame['market_regime'].iloc[0]} / {frame['credit_environment'].iloc[0]}",
        f"  CVS: median {frame['cvs_score'].median():.1f}"
        if frame["cvs_score"].notna().any()
        else "  CVS: uncomputable for every row",
    ]
    if "cvs_tier" in frame.columns:
        for tier, n in frame["cvs_tier"].value_counts().items():
            lines.append(f"    {tier:12} {n:5d}")
    if "override_flag" in frame.columns:
        counts = ", ".join(f"{k} {v}" for k, v in frame["override_flag"].value_counts().items())
        lines.append(f"  Override: {counts}")
    if reasons:
        lines.append(f"  GATED OFF: {', '.join(reasons)}")
        lines.append(
            "  Scores were not modified. Enabling the layer while its inputs are absent\n"
            "  applies a uniform cap to most of the universe and flattens the ranking."
        )
    return "\n".join(lines)


def _any_macro(frame):
    vintage = frame["macro_vintage"].dropna()
    if vintage.empty:
        return MacroState(None, None, None)
    return MacroState(0.0, 0.0, vintage.iloc[0])


__all__ = [
    "CVS_SOURCE_COLUMNS",
    "CIRCUIT_BREAKER_SOURCES",
    "CIRCUIT_BREAKER_THRESHOLDS",
    "evaluate_breakers",
    "GATE_MACRO_ABSENT",
    "GATE_CVS_INCOMPLETE",
    "GATE_BREAKERS_UNEVALUABLE",
    "apply_regime_layer",
    "compute_cvs_frame",
    "layer_readiness",
    "macro_state_from_row",
    "summarize",
]
