"""Tests for the market-regime layer.

The specification (``economic_credit_cycle_dividend_regime.md``) is the
design record; ``src/crispdm/regime.py`` is the arithmetic. These tests exist
so the two cannot drift: every table in the specification that describes
behaviour rather than intent is asserted here against the code that implements
it.

The first revision of the specification carried a worked verification table
whose tenth row claimed ``Expansion`` where the documented algorithm returned
``Recovery``, a weight summary row that contradicted the weights above it, and
a tier gate described in prose with no implementation. All three were
invisible because nothing executed the document.
"""

import math

import pytest

from src.crispdm.regime import (
    CANONICAL_REGIMES,
    CREDIT_ENVIRONMENTS,
    CREDIT_MODIFIER_TABLE,
    CVS_CORE_LEVERAGE,
    CVS_STRONG_MAX_SCORE,
    CVS_WEIGHTS,
    MEASURABLE_REGIME_KEYS,
    REGIME_WEIGHTS,
    apply_credit_modifier,
    apply_safety_cap,
    bracket_score,
    compute_cvs,
    credit_environment,
    credit_modifier,
    determine_market_regime,
    evaluate_dividend_safety_override,
    final_score,
)

#: Coarse grid spanning every threshold the classifier branches on, including
#: the breakpoints the specification names explicitly (0.25 level, -0.25
#: depression, -0.5 stressed credit, -0.75 velocity, +0.75 recovery).
GRID = (-2.0, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 2.0)


def test_regime_weights_sum_to_one():
    for regime, weights in REGIME_WEIGHTS.items():
        assert sum(weights.values()) == pytest.approx(1.0), regime


def test_regime_weight_rows_match_the_specification_summary():
    """The measurable/constant split in specification section 7.2.

    Recovery was listed as 75% measurable against weights that sum to 80%. The
    summary is recomputed from the weights rather than read, so the two cannot
    disagree -- the one unrated leg (``legal_rights``) carries 10% of the weight
    in every non-baseline regime, which also puts a floor under CVS, and both
    facts are calibration, not rounding.
    """
    expected = {
        "Baseline": (0.75, 0.25),
        "Expansion": (0.90, 0.10),
        "Late Cycle": (0.90, 0.10),
        "Transition": (0.90, 0.10),
        "Slowdown": (0.90, 0.10),
        "Recession": (0.90, 0.10),
        "Recovery": (0.90, 0.10),
    }
    for regime, weights in REGIME_WEIGHTS.items():
        measurable = sum(weights[k] for k in MEASURABLE_REGIME_KEYS)
        constant = sum(weights.values()) - measurable
        want_measurable, want_constant = expected[regime]
        assert measurable == pytest.approx(want_measurable), regime
        assert constant == pytest.approx(want_constant), regime


def test_every_canonical_regime_has_a_weight_row():
    for regime in CANONICAL_REGIMES:
        assert regime in REGIME_WEIGHTS


def test_classifier_reproduces_the_verification_table():
    """Section 3.7's worked table, with row 10 corrected to the code's answer.

    Row 10 (``e_level=0.0, c_level=0.0, c_delta=+1.5``) was documented as
    Expansion under a "concordant" label. The documented algorithm returned
    Recovery, because its ``Recovery`` gate admitted ``c_level <= 0.0`` and
    the neutral baseline satisfies that. Either the gate or the row was wrong;
    the gate was, since the row is a routine credit-tightening expansion and
    calling it a trough inverts the argument of section 2.1.
    """
    cases = [
        # e_level, e_delta, c_level, c_delta, expected
        (1.5, 1.0, 1.0, 1.0, "Expansion"),
        (1.0, 0.0, 0.0, -1.5, "Late Cycle"),
        (1.0, -1.0, 0.0, -1.0, "Late Cycle"),
        (0.5, -1.5, 0.0, 0.0, "Slowdown"),
        (0.0, 0.0, 0.0, 0.0, "Transition"),
        (-1.5, -1.0, -1.5, -1.0, "Recession"),
        (-1.5, 0.0, -1.0, 1.8, "Recovery"),
        (-1.0, 1.5, -0.5, 1.0, "Recovery"),
        (0.0, 1.5, 0.0, 1.5, "Expansion"),
        (-0.5, -0.5, -1.0, 0.0, "Recession"),
    ]
    for e_level, e_delta, c_level, c_delta, expected in cases:
        got = determine_market_regime(e_level, e_delta, c_level, c_delta)
        assert got == expected, f"({e_level}, {e_delta}, {c_level}, {c_delta})"


def test_recovery_does_not_fire_at_the_neutral_baseline():
    """A tightening credit cycle from trend is Expansion, not a trough.

    This is the single behavioural change from the first revision. The looser
    ``Recovery`` gate reached ``c_level = 0.0`` and ``e_level = 0.0``, so the
    ordinary state of an easing cycle inherited Recovery's 25% appreciation
    tilt and its reduced risk weight.
    """
    assert determine_market_regime(0.0, 1.5, 0.0, 1.5) == "Expansion"
    assert determine_market_regime(0.0, 1.0, 0.0, 2.0) == "Expansion"
    assert determine_market_regime(0.25, 1.0, 0.0, 1.0) == "Expansion"
    # And symmetrically: credit at a stress level that is closing fast is a
    # Recovery, not an Acute Crunch, despite the level breach.
    assert determine_market_regime(-1.0, 0.5, -1.0, 1.5) == "Recovery"


def test_recovery_still_requires_depressed_levels():
    """Both Tier 1a entry paths keep working, which is what the gate protects."""
    # Level-depressed, credit turning hard.
    assert determine_market_regime(-1.5, 0.0, -1.0, 1.8) == "Recovery"
    # Double-sided momentum inflection.
    assert determine_market_regime(-1.0, 1.5, -0.5, 1.0) == "Recovery"
    # Credit still wide, so the recovery is unconfirmed even as growth improves.
    assert determine_market_regime(-1.0, 1.0, -0.5, 0.0) != "Recovery"


def test_late_cycle_still_fires_ahead_of_gdp():
    """The state the framework exists to catch, unchanged."""
    assert determine_market_regime(1.0, 0.0, 0.0, -1.5) == "Late Cycle"
    assert determine_market_regime(1.2, 0.0, 0.0, -1.5) == "Late Cycle"
    assert determine_market_regime(1.0, -1.0, 0.0, -1.0) == "Late Cycle"


def test_classifier_emits_only_canonical_labels_and_reaches_all_of_them():
    """The vocabulary is closed.

    A phase-space diagram in the first revision carried "CONTRACTION DRAG",
    a label no weight row was defined for and the classifier never produced.
    Asserting the output set is exactly the canonical set makes an
    unreachable or extra label a test failure instead of a discrepancy
    between a diagram and a table.
    """
    seen = set()
    for e_level in GRID:
        for e_delta in GRID:
            for c_level in GRID:
                for c_delta in GRID:
                    seen.add(determine_market_regime(e_level, e_delta, c_level, c_delta))
    assert seen == set(CANONICAL_REGIMES)


def test_transition_is_the_residual_not_the_neutral_box():
    """Section 3.1 described Transition as a box; it is a fallback.

    The residual is a real state -- depressed levels with momentum improving
    but credit not yet reopened -- and it is deliberately allowed to sit
    outside ``|s_level| <= 0.25``. What must not happen is the reverse: a
    state that a named regime claims silently defaulting to Transition.
    """
    for e_level in GRID:
        for e_delta in GRID:
            for c_level in GRID:
                for c_delta in GRID:
                    regime = determine_market_regime(e_level, e_delta, c_level, c_delta)
                    s_level = 0.60 * e_level + 0.40 * c_level
                    s_delta = 0.60 * e_delta + 0.40 * c_delta
                    if regime == "Transition":
                        assert not (s_level >= 0.25 and s_delta >= -0.25)
                        assert not (s_level >= -0.25 and s_delta >= 1.0)
                        assert not (s_level >= -0.25 and s_delta < -0.25)
                        assert not (s_level < -0.25 and s_delta <= 0.25)


def test_credit_environment_prefers_the_turn_over_the_stale_level():
    """A level breach does not outrank a decisive reversal in the same variable.

    Spreads at -1.0 that are closing at +1.5bp of velocity are the reopening a
    recovery consists of, and the first implementation tested the level first
    and handed that state the harshest row in section 5.2. That is the
    level/change conflation section 2.1 exists to remove, reintroduced in the
    modifier rather than the classifier.
    """
    assert credit_environment(-1.0, 1.5) == "Recovery"
    assert credit_environment(-1.5, 1.0) == "Recovery"
    # Still stressed and not yet turning: the harsh row is correct here.
    assert credit_environment(-1.0, 0.0) == "Acute Crunch"
    assert credit_environment(-1.5, -1.0) == "Acute Crunch"
    # Widening from a perfectly normal level is a squeeze, not a crunch.
    assert credit_environment(0.0, -1.0) == "Velocity Squeeze"
    assert credit_environment(1.0, 1.0) == "Accommodative"
    assert credit_environment(0.5, -0.25) == "Normal"
    # Genuine easing on one leg is enough: the table's Accommodative row is
    # "level >= 0 AND delta >= 0", and 0.5/-0.25 fails the second half.
    assert credit_environment(0.5, 0.25) == "Accommodative"


def test_macro_absent_baseline_is_normal_not_accommodative():
    """Section 5.4's fallback must not be the best credit in the table.

    With no macro feed the layer defaults to the neutral baseline (0.0, 0.0).
    A non-negative test on both legs resolved that to Accommodative, the
    mildest row, so the state the framework falls into when it knows nothing
    was also the state it pays best for -- a 1.00 modifier for a Strong
    company with no macro observation behind it. Section 5.4 explicitly
    prohibits defaulting to Accommodative, and the default was doing exactly
    that. Absence of a feed has to read as Normal.
    """
    assert credit_environment(0.0, 0.0) == "Normal"
    # And the regime classifier agrees: the baseline is the residual bucket.
    assert determine_market_regime(0.0, 0.0, 0.0, 0.0) == "Transition"


def test_credit_modifier_table_is_monotone_in_tier_and_environment():
    """More vulnerable and worse macro must never pay a smaller penalty.

    ``CREDIT_ENVIRONMENTS`` is ordered mildest-first, so the pairwise sweep
    over every (milder, harsher) combination asserts the table gets stricter
    as credit deteriorates, in every tier.
    """
    for env, row in CREDIT_MODIFIER_TABLE.items():
        assert row["strong"] >= row["moderate"] >= row["high"], env
    for i, milder in enumerate(CREDIT_ENVIRONMENTS):
        for harsher in CREDIT_ENVIRONMENTS[i + 1 :]:
            for tier in ("strong", "moderate", "high"):
                assert (
                    CREDIT_MODIFIER_TABLE[harsher][tier] <= CREDIT_MODIFIER_TABLE[milder][tier]
                ), f"{harsher}/{tier} vs {milder}/{tier}"


def test_unscorable_cvs_never_receives_a_clean_modifier():
    """Section 5.3: an unmeasured balance sheet is not a strong one."""
    for stressed in (False, True):
        value = credit_modifier("Normal", "unscorable", unscorable_is_stressed=stressed)
        assert value < 1.0
        assert value == (0.65 if stressed else 0.85)


#: A company with a pristine balance sheet: every leg lands in the 0-point
#: column of the section 4.3 bracket tables. These are RAW observations, not
#: bracket scores -- ``compute_cvs`` brackets them itself.
PRISTINE = {
    "net_debt_to_ebitda": 1.0,
    "interest_coverage": 10.0,
    "refinancing_wall": 0.1,
    "quick_liquidity": 2.0,
    "credit_rating": 1.0,
}

#: A company in the 100-point (Distressed) column on every leg.
DISTRESSED = {
    "net_debt_to_ebitda": 100.0,
    "interest_coverage": 0.1,
    "refinancing_wall": 5.0,
    "quick_liquidity": 0.1,
    "credit_rating": 4.5,
}


def _cvs(**overrides):
    base = dict(PRISTINE)
    base.update(overrides)
    return compute_cvs(base)


@pytest.mark.parametrize(
    ("metric", "value", "points"),
    [
        # Low-is-good legs: higher value, worse bracket.
        ("net_debt_to_ebitda", 1.75, 0.0),
        ("net_debt_to_ebitda", 2.75, 25.0),
        ("net_debt_to_ebitda", 4.00, 50.0),
        ("net_debt_to_ebitda", 5.50, 75.0),
        ("net_debt_to_ebitda", 6.00, 100.0),
        ("quick_liquidity", 1.20, 0.0),
        ("quick_liquidity", 0.90, 25.0),
        ("quick_liquidity", 0.65, 50.0),
        ("quick_liquidity", 0.45, 75.0),
        ("quick_liquidity", 0.10, 100.0),
        # High-is-good legs: lower value, worse bracket. Same table shape, and
        # getting the direction wrong here would score every covered company
        # distressed.
        ("interest_coverage", 6.00, 0.0),
        ("interest_coverage", 5.99, 25.0),
        ("interest_coverage", 2.50, 50.0),
        ("interest_coverage", 1.50, 75.0),
        ("interest_coverage", 1.00, 100.0),
        ("refinancing_wall", 0.25, 0.0),
        ("refinancing_wall", 0.26, 25.0),
        ("refinancing_wall", 1.00, 50.0),
        ("refinancing_wall", 1.50, 75.0),
        ("refinancing_wall", 2.00, 100.0),
        # Agency scale, 1 best-rated (AAA/AA) through 5 junk. Low is good.
        ("credit_rating", 1.0, 0.0),
        ("credit_rating", 1.5, 0.0),
        ("credit_rating", 2.5, 25.0),
        ("credit_rating", 3.0, 50.0),
        ("credit_rating", 3.5, 75.0),
        ("credit_rating", 4.5, 100.0),
    ],
)
def test_bracket_tables_follow_section_4_3(metric, value, points):
    """Every boundary in the spec, including the direction of each table."""
    assert bracket_score(metric, value) == points


def test_bracket_score_treats_absence_as_absence():
    """A bracket is a statement about evidence, so NULL stays NULL."""
    assert bracket_score("net_debt_to_ebitda", None) is None
    assert bracket_score("net_debt_to_ebitda", float("nan")) is None


def test_bracketing_is_what_stops_incommensurable_scales_being_summed():
    """The defect this exists to close.

    Summing raw observations puts a leverage ratio of 2.0 (0.25 weight) on the
    same footing as a rating of 2.0 (0.15 weight), and both contribute a
    fraction of a point against a tier boundary calibrated for 0-100. A
    pristine company scored 0.5 of 100 and could not be distinguished from one
    with no data at all.
    """
    assert compute_cvs(PRISTINE).cvs == pytest.approx(0.0)
    assert compute_cvs(DISTRESSED).cvs == pytest.approx(100.0)


def test_cvs_requires_a_leverage_metric_and_liquidity():
    """The core evidence floor, or the score is NULL rather than guessed."""
    assert _cvs(net_debt_to_ebitda=None, interest_coverage=None).cvs is None
    assert _cvs(quick_liquidity=None).cvs is None
    # One of the pair is enough.
    assert _cvs(net_debt_to_ebitda=None).cvs is not None


def test_missing_leverage_cannot_buy_the_strong_tier():
    """The gate the first revision described but never implemented.

    EBITDA is uncomputable for roughly a third of stored filings because no
    D&A line is reported. A company in that position, with its other four
    legs pristine, sums to 12.5 on the arithmetic alone -- below the Strong
    boundary of 30 and a 1.00 modifier, which is the cheapest place in the
    layer for missing data to earn a free pass.
    """
    result = _cvs(net_debt_to_ebitda=None)
    assert result.cvs < CVS_STRONG_MAX_SCORE
    assert result.tier == "moderate"
    assert result.missing_core == ("net_debt_to_ebitda",)
    assert credit_modifier("Normal", result.tier) < 1.0


def test_strong_tier_requires_the_metrics_behind_the_circuit_breakers():
    """Strong is a 1.00 modifier, so it needs its evidence actually present.

    A missing maturity schedule is not a neutral gap: it is the input to
    circuit breaker C4, so the company that omits it is the company whose
    unmeasured risk the override exists to catch. A missing rating is weaker
    evidence than that -- it is absent for the whole universe -- so it is
    priced by imputation rather than used to bar the Strong tier.
    """
    assert _cvs().tier == "strong"
    assert _cvs(credit_rating=None).tier == "strong"
    assert _cvs(interest_coverage=None).tier == "moderate"
    assert _cvs(net_debt_to_ebitda=None).tier == "moderate"
    assert _cvs(refinancing_wall=None).tier == "moderate"


def test_credit_rating_absence_does_not_bar_everyone_from_strong():
    """It is absent for the entire universe, so it cannot gate the tier.

    A gate that admits nothing is not a gate; since ``credit_rating`` resolves
    for 0% of securities, requiring it would make Strong unreachable and hand
    every row the 0.90 modifier regardless of its balance sheet.
    """
    assert _cvs(credit_rating=None).cvs < CVS_STRONG_MAX_SCORE
    assert _cvs(credit_rating=None).tier == "strong"


def test_credit_rating_is_imputed_conservatively_and_floors_the_score():
    """The 15% leg nobody can report is a cost, and it is calibrated for.

    Dropping it would give an unrated company a 0 on a metric no filer in the
    warehouse can supply. Imputing at 50 keeps the score honest about that
    gap and puts a floor under the achievable range.
    """
    result = _cvs(credit_rating=None)
    assert result.cvs == pytest.approx(50.0 * CVS_WEIGHTS["credit_rating"])
    assert result.coverage == pytest.approx(1.0 - CVS_WEIGHTS["credit_rating"])


def test_cvs_tier_boundaries():
    """Boundaries land at the weights' arithmetic, not at the label.

    The inputs here are RAW observations that land in a named bracket, not
    bracket points -- ``compute_cvs`` brackets them, so passing 100.0 for
    interest coverage would mean 100x interest coverage, the most pristine
    reading on the table. The DISTRESSED/PRISTINE pairs state the intent.
    """
    # Distressed on every leg: 25% + 20% + 25% + 15% + 15% = 100.
    assert compute_cvs(DISTRESSED).cvs == pytest.approx(100.0)
    assert compute_cvs(DISTRESSED).tier == "high"
    # Dropping the rating leg imputes it at 50, so 85% at 100 + 15% at 50.
    assert compute_cvs({**DISTRESSED, "credit_rating": None}).cvs == pytest.approx(92.5)
    assert compute_cvs({**DISTRESSED, "credit_rating": None}).tier == "high"
    # Distressed on leverage and coverage only: 45% at 100, the other 55% at 0.
    # That is 45, under the High boundary of 60, so the tier is set by the
    # arithmetic rather than by the two alarming legs -- imputation of the
    # structural legs is what pulls it back, not a discount for them.
    partially = {
        **PRISTINE,
        "net_debt_to_ebitda": 100.0,
        "interest_coverage": 0.1,
    }
    assert compute_cvs(partially).cvs == pytest.approx(45.0)
    assert compute_cvs(partially).tier == "moderate"
    # All five legs impaired but only into the 50-point column: 50 everywhere.
    strained = {metric: 3.0 for metric in PRISTINE}
    strained["net_debt_to_ebitda"] = 3.5  # 50-point column
    strained["refinancing_wall"] = 0.75  # 50-point column
    strained["quick_liquidity"] = 0.75  # 50-point column
    strained["credit_rating"] = 3.0  # 50-point column
    assert compute_cvs(strained).cvs == pytest.approx(50.0)
    assert compute_cvs(strained).tier == "moderate"


def test_modifier_preserves_nan():
    """A row the base scorer refused must not acquire a score here."""
    nan = float("nan")
    assert math.isnan(apply_credit_modifier(nan, 0.55))
    assert math.isnan(apply_safety_cap(nan, 0.20))
    assert math.isnan(final_score(nan, 0.55, 0.20))


def test_cap_preserves_nan_regardless_of_argument_order():
    """``min`` is not a ``NaN`` guard; it just happens to work in one order.

    ``min(nan, cap)`` is ``nan``, but ``min(cap, nan)`` returns ``cap`` -- a
    cap that would *invent* a score for an unrankable row if anyone ever
    swapped the arguments. The invariant is stated in the spec, so it is
    asserted rather than left to argument order.
    """
    nan = float("nan")
    assert min(cap_value := 0.20, nan) == cap_value  # the footgun
    assert math.isnan(apply_safety_cap(nan, 0.20))  # what the layer actually does


def test_cap_cannot_raise_a_score():
    assert apply_safety_cap(0.85, 0.20) == pytest.approx(0.20)
    assert apply_safety_cap(0.10, 0.20) == pytest.approx(0.10)


def test_modifier_is_applied_before_the_cap():
    """Ordering is observable and is fixed.

    Both operations are non-expansive, so the sequence never changes *which*
    rows are capped -- but at a raw 0.85 with a 0.90 modifier and a 0.20 cap,
    modifier-first gives 0.20 and cap-first gives 0.18. Modifier-first keeps a
    capped row at exactly the ceiling instead of pushing it below for a breach
    the modifier has nothing to do with.
    """
    raw, modifier, cap = 0.85, 0.90, 0.20
    assert final_score(raw, modifier, cap) == pytest.approx(0.20)
    assert final_score(raw, modifier, cap) == pytest.approx(min(raw * modifier, cap))
    assert min(raw, cap) * modifier == pytest.approx(0.18)
    assert final_score(raw, modifier, cap) != pytest.approx(min(raw, cap) * modifier)


def test_override_flags():
    assert evaluate_dividend_safety_override(True, True, False, False, False, 10.0, 1.0, 1.0) == (
        "RED",
        0.20,
    )
    # FCF drain plus an uncovered maturity wall is RED on its own.
    assert evaluate_dividend_safety_override(True, False, False, True, False, 10.0, 1.0, 1.0) == (
        "RED",
        0.20,
    )
    # One breach is only escalated when credit is shut.
    assert evaluate_dividend_safety_override(True, False, False, False, False, 10.0, 0.0, 0.0) == (
        "YELLOW",
        0.45,
    )
    assert evaluate_dividend_safety_override(True, False, False, False, False, 10.0, 0.0, -1.0) == (
        "SYSTEMIC_RED",
        0.25,
    )
    assert evaluate_dividend_safety_override(False, False, False, False, False, 20.0, 0.0, 0.0) == (
        "GREEN",
        1.00,
    )
    # A high CVS alone is a watchlist, not an exclusion.
    assert evaluate_dividend_safety_override(False, False, False, False, False, 70.0, 0.0, 0.0) == (
        "YELLOW",
        0.45,
    )


def test_unevaluated_circuit_breakers_fail_closed():
    """``None`` is unknown, and unknown is not safe.

    The reference implementation in the first draft summed the five
    conditions directly, so a ``None`` raised ``TypeError`` and killed the
    screening run. The obvious repair -- treating ``None`` as unbreached --
    is the wrong one: it hands a clean pass to exactly the companies whose
    solvency the breakers cannot see.
    """
    # Five unevaluated breakers: two-or-more breached, so RED.
    flag, cap = evaluate_dividend_safety_override(None, None, None, None, None, 10.0, 1.0, 1.0)
    assert flag == "RED"
    assert cap == pytest.approx(0.20)

    # One unevaluated breaker among four clean ones is a single breach.
    flag, cap = evaluate_dividend_safety_override(None, False, False, False, False, 10.0, 0.0, 0.0)
    assert flag == "YELLOW"
    assert cap == pytest.approx(0.45)

    # An unevaluated C4 pairs with an unevaluated C1 as the FCF/maturity pair.
    flag, _ = evaluate_dividend_safety_override(None, False, False, None, False, 10.0, 0.0, 0.0)
    assert flag == "RED"

    # And it escalates on a single breach when credit is shut, like any other.
    flag, cap = evaluate_dividend_safety_override(False, False, False, None, False, 10.0, 0.0, -1.0)
    assert flag == "SYSTEMIC_RED"
    assert cap == pytest.approx(0.25)

    # A fully evaluated clean row is still GREEN: the fail-closed path keys on
    # None specifically, not on uncertainty in general.
    flag, cap = evaluate_dividend_safety_override(False, False, False, False, False, 20.0, 0.0, 0.0)
    assert flag == "GREEN"
    assert cap == pytest.approx(1.00)


def test_override_is_regime_independent_for_the_hard_flag():
    """Macro cannot grant a waiver to a broken balance sheet."""
    for c_level, c_delta in ((2.0, 2.0), (0.0, 0.0), (-2.0, -2.0)):
        flag, _ = evaluate_dividend_safety_override(
            True, True, False, False, False, 80.0, c_level, c_delta
        )
        assert flag == "RED"


def test_cvs_weights_sum_to_one():
    assert sum(CVS_WEIGHTS.values()) == pytest.approx(1.0)
    assert set(CVS_CORE_LEVERAGE) <= set(CVS_WEIGHTS)
