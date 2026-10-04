"""Market-regime layer: economic and credit phase-space classification.

The design specification is ``economic_credit_cycle_dividend_regime.md``. This
module is the executable form of the classifier, the credit-vulnerability
score, the credit modifier and the dividend-safety override, so the
specification's tables are checked by ``tests/test_regime.py`` rather than
being prose that can drift from the arithmetic it describes.

The layer sits *downstream* of :func:`src.crispdm.scoring.score`. It never
computes a factor sub-score and never re-ranks; it only rescales a composite
that already cleared the coverage floor. Three invariants follow from that
position and are enforced here rather than documented and hoped for:

* A ``NaN`` composite stays ``NaN``. Applying a multiplier to a missing value
  yields a missing value, and the safety cap is a ``min`` against a ceiling
  rather than an assignment, so neither the modifier nor the override can
  manufacture a score for a row that failed ``MIN_PRESENT_WEIGHT``.
* The modifier is applied **before** the cap, never after. Both operations are
  non-expansive (``x * m`` with ``m <= 1`` and ``min(x, c)`` with ``c <= x``),
  so both orders are monotone, but they are not equal: at a raw 0.85, an Acute
  Crunch modifier of 0.90 and a cap of 0.20, modifier-first gives
  ``min(0.765, 0.20) == 0.20`` while cap-first gives
  ``0.20 * 0.90 == 0.18``. Modifier-first is the specified order because the
  cap encodes an absolute ceiling on the *final* score, and applying a
  relative haircut after the ceiling would push a capped row below the ceiling
  for a reason that has nothing to do with the breach.
* The regime vocabulary is closed. :data:`CANONICAL_REGIMES` is the only set of
  labels this layer can emit, so a diagram or a table that introduces a
  seventh name fails a test instead of quietly becoming unreachable.
"""

import math
from typing import NamedTuple

#: The closed six-state vocabulary from specification section 3.1. Every
#: regime, weight row, modifier row and override branch is keyed on these
#: strings, and ``tests/test_regime.py`` asserts that no other label can be
#: produced. An earlier revision of the specification carried a "CONTRACTION
#: DRAG" cell in its phase-space diagram that the classifier never emitted and
#: that no weight row was defined for -- exactly the disconnected-vocabulary
#: failure section 3.1 exists to prevent, reintroduced by the diagram.
CANONICAL_REGIMES = (
    "Expansion",
    "Late Cycle",
    "Slowdown",
    "Recession",
    "Recovery",
    "Transition",
)

#: Factor weights per regime (specification section 7.2), plus the production
#: baseline currently in :data:`src.crispdm.scoring.WEIGHTS`.
#:
#: ``legal_rights_score`` and ``valuation_score`` are constants imputed to 0.5
#: for every security (``scoring.py`` / ``features.py``), so the weight that is
#: not backed by evidence is the complement of :data:`MEASURABLE_REGIME_KEYS`.
#: Recovery carries 25% appreciation, 25% sustainability, 15% income, 15% risk,
#: 10% legal and 10% valuation: 80% measurable, 20% constant. The first
#: revision of this table listed Recovery as 75%/25%, which contradicted its
#: own columns; ``tests/test_regime.py`` recomputes both figures from the
#: weights rather than trusting the summary row.
REGIME_WEIGHTS = {
    "Baseline": {
        "income": 0.25,
        "sustainability": 0.20,
        "appreciation": 0.15,
        "risk": 0.10,
        "legal_rights": 0.25,
        "valuation": 0.05,
    },
    "Expansion": {
        "income": 0.15,
        "sustainability": 0.20,
        "appreciation": 0.25,
        "risk": 0.15,
        "legal_rights": 0.10,
        "valuation": 0.15,
    },
    "Late Cycle": {
        "income": 0.15,
        "sustainability": 0.25,
        "appreciation": 0.15,
        "risk": 0.25,
        "legal_rights": 0.10,
        "valuation": 0.10,
    },
    "Transition": {
        "income": 0.15,
        "sustainability": 0.25,
        "appreciation": 0.15,
        "risk": 0.20,
        "legal_rights": 0.10,
        "valuation": 0.15,
    },
    "Slowdown": {
        "income": 0.15,
        "sustainability": 0.30,
        "appreciation": 0.10,
        "risk": 0.25,
        "legal_rights": 0.10,
        "valuation": 0.10,
    },
    "Recession": {
        "income": 0.15,
        "sustainability": 0.35,
        "appreciation": 0.05,
        "risk": 0.30,
        "legal_rights": 0.10,
        "valuation": 0.05,
    },
    "Recovery": {
        "income": 0.15,
        "sustainability": 0.25,
        "appreciation": 0.25,
        "risk": 0.15,
        "legal_rights": 0.10,
        "valuation": 0.10,
    },
}

#: The four factors with a real per-security measurement. Mirrors
#: :data:`src.crispdm.scoring.MEASURABLE`; the two remaining keys are the
#: imputed constants.
MEASURABLE_REGIME_KEYS = ("income", "sustainability", "appreciation", "risk")

#: Credit modifier by environment and vulnerability tier (specification
#: section 5.2). Calibrated as an *incremental* haircut because the composite
#: already carries cross-sectional percentiles for weak coverage and high
#: leverage; without that restraint the same fact would be penalised twice.
CREDIT_MODIFIER_TABLE = {
    "Accommodative": {"strong": 1.00, "moderate": 0.95, "high": 0.85},
    "Normal": {"strong": 1.00, "moderate": 0.90, "high": 0.80},
    "Recovery": {"strong": 0.98, "moderate": 0.88, "high": 0.75},
    "Velocity Squeeze": {"strong": 0.95, "moderate": 0.80, "high": 0.65},
    "Acute Crunch": {"strong": 0.90, "moderate": 0.70, "high": 0.50},
}

#: Environment names in penalty order, mildest first. Used to pick the single
#: governing environment when several conditions match at once.
CREDIT_ENVIRONMENTS = (
    "Accommodative",
    "Normal",
    "Recovery",
    "Velocity Squeeze",
    "Acute Crunch",
)

#: Score cap and flag for each override outcome (specification section 6.2).
OVERRIDE_CAPS = {
    "RED": 0.20,
    "SYSTEMIC_RED": 0.25,
    "YELLOW": 0.45,
    "GREEN": 1.00,
}

#: Modifier for a row whose CVS could not be computed (section 5.3). Never
#: 1.00: an unmeasured balance sheet is not a clean one, and the most common
#: cause of an uncomputable CVS is a filer that does not disclose the inputs.
UNSCORABLE_CVS_MODIFIER = {"benign": 0.85, "stressed": 0.65}


class CVSScore(NamedTuple):
    """Company Credit Vulnerability result, with the evidence behind it."""

    #: 0 (prudent) to 100 (distressed), or ``None`` when the core evidence
    #: floor is not met.
    cvs: float | None
    #: Share of CVS weight backed by an actual measurement, 0.0 to 1.0.
    coverage: float
    #: One of :data:`CVS_TIERS`.
    tier: str
    #: Core leverage metrics absent. The Strong tier requires both.
    missing_core: tuple[str, ...]


CVS_TIERS = ("strong", "moderate", "high", "unscorable")


class MacroState(NamedTuple):
    """A point-in-time macro observation, or an explicit statement of absence.

    ``c_level`` and ``c_delta`` are present together or absent together. There
    is no partial state, because half an observation is a level with no
    velocity, which is exactly the reading section 2.1 exists to prevent: the
    whole framework distinguishes a credit market that is stressed from one
    that is closing fast, and a level alone cannot tell them apart.

    ``vintage`` is the as-of date the observation was valid at. Section 9
    forbids scoring against the current vintage, so a row that carries a value
    but no vintage is treated as absent by
    :func:`src.crispdm.regime_pipeline.macro_state_from_row` -- using it would
    be a look-ahead that nothing downstream could detect.
    """

    c_level: float | None
    c_delta: float | None
    vintage: object = None

    @property
    def present(self) -> bool:
        """Whether this observation may move a score."""
        return self.c_level is not None and self.c_delta is not None and self.vintage is not None


#: Weight of each CVS metric (section 4.2). ``credit_rating`` carries 15% with
#: no source in the warehouse, so it is imputed at the conservative 50-point
#: baseline for every security. That is a deliberate cost, not an oversight:
#: it puts a permanent +7.5 point floor under the score, so the achievable
#: range is [7.5, 92.5] rather than [0, 100] and the tiers are calibrated to
#: that compressed scale. The alternative -- dropping the leg -- would let an
#: unrated company collect a 0 on a metric nobody can report.
CVS_WEIGHTS = {
    "net_debt_to_ebitda": 0.25,
    "interest_coverage": 0.20,
    "refinancing_wall": 0.25,
    "quick_liquidity": 0.15,
    "credit_rating": 0.15,
}

#: The two metrics the core evidence floor and the Strong-tier gate both treat
#: as the leverage pair. Absence of the pair is what makes a company
#: unscoreable rather than merely thin.
CVS_CORE_LEVERAGE = ("net_debt_to_ebitda", "interest_coverage")

#: Conservative value for an absent metric. Mid-scale, never 0: a company with
#: no reported maturity schedule is not prudent, it is unknown, and 0 is the
#: best possible score on the metric.
CVS_IMPUTED_SCORE = 50.0

#: Metrics that must carry a real measurement before a row may be Strong.
#:
#: Section 4.5 stated this as "coverage >= 0.60 and zero missing core leverage
#: metrics". That threshold is satisfiable while a quarter of the weight is
#: imputed: with net debt, interest coverage and liquidity all measuring 0
#: and both ``refinancing_wall`` and ``credit_rating`` absent, the coverage
#: lands on exactly 0.60 and the score on 20.0, which is Strong by the stated
#: rule. It should not be. The maturity schedule is the input to circuit
#: breaker C4, so a company that does not report one is precisely the company
#: whose unmeasured risk is the risk the override exists to catch, and
#: ``credit_rating`` is absent for the entire universe, so a rule that admits
#: its absence admits nothing at all.
#:
#: Requiring these three measured implies coverage of at least 0.70, which
#: subsumes the 0.60 floor rather than contradicting it.
CVS_STRONG_REQUIRED_METRICS = (
    "net_debt_to_ebitda",
    "interest_coverage",
    "refinancing_wall",
)

#: Evidence floors. The Strong tier needs both because a Strong label drives
#: a 1.00 modifier -- the single cheapest place in the layer for missing data
#: to buy a free pass. The first revision of the specification described this
#: gate in prose without implementing it, and the consequence was that a
#: company whose EBITDA is uncomputable (no D&A line, ~36% of stored filings)
#: but whose other legs are pristine scored CVS 20.0 and was labelled Strong.
CVS_STRONG_MAX_SCORE = 30.0
CVS_STRONG_MIN_COVERAGE = 0.60
CVS_MODERATE_MAX_SCORE = 60.0


def determine_market_regime(e_level: float, e_delta: float, c_level: float, c_delta: float) -> str:
    """Classify the market regime from economic and credit phase coordinates.

    Precedence is strict: kinetic turning points (Tier 1) override static
    composite levels (Tier 2), because a turning point is a change in sign of
    the first derivative and the level has not caught up yet.

    ``Recovery`` requires the levels to be *genuinely depressed* --
    ``e_level <= 0.0`` and ``c_level <= -0.5``. The looser gate the first
    revision used (``e_level <= 0.25 and c_level <= 0.0``) admitted the
    neutral baseline, so an ordinary credit-tightening expansion
    (``e_level = 0.0, c_level = 0.0, c_delta = +1.5``) was labelled Recovery
    and inherited its 25% appreciation tilt. That is the routine state of a
    normal easing cycle, and treating it as a trough is the same blindness in
    the opposite direction from the one section 2.1 was written to fix.
    """
    s_level = 0.60 * e_level + 0.40 * c_level
    s_delta = 0.60 * e_delta + 0.40 * c_delta

    # Tier 1a: Recovery. Depressed levels with credit turning hard, or a
    # double-sided momentum inflection.
    if (
        e_level <= 0.0
        and c_level <= -0.5
        and (c_delta >= 0.75 or (e_delta >= 1.0 and c_delta >= 0.25))
    ):
        return "Recovery"

    # Tier 1b: Late Cycle. Activity still at or above trend while credit
    # velocity deteriorates. This is the state section 2.1 calls the regime's
    # reason for existing: spreads at the median but widening fast.
    if e_level >= 0.0 and c_delta <= -0.75:
        return "Late Cycle"

    # Tier 2a: Expansion. Either the level is healthy and momentum has not
    # turned down, or momentum is leading decisively out of a merely
    # depressed level. The second disjunct is what makes the diagram's
    # "Neutral x Accelerating" cell reachable as Expansion rather than
    # falling through to the residual.
    if (s_level >= 0.25 and s_delta >= -0.25) or (s_level >= -0.25 and s_delta >= 1.0):
        return "Expansion"

    # Tier 2b: Slowdown. Still at or above trend, momentum gone.
    if s_level >= -0.25 and s_delta < -0.25:
        return "Slowdown"

    # Tier 2c: Recession. Depressed level, momentum not leading.
    if s_level < -0.25 and s_delta <= 0.25:
        return "Recession"

    # Residual. Deeply depressed with momentum above the Recession ceiling but
    # without the credit confirmation Tier 1a requires: a recovery that has
    # not yet reopened the credit market. The specification previously
    # described Transition as the box ``|s_level| <= 0.25 and
    # |s_delta| <= 0.25``, which is not what this branch is -- over half of a
    # coarse grid landed in Transition outside that box. Transition is the
    # residual by construction; the numeric box describes the common case,
    # not the domain.
    return "Transition"


def credit_environment(c_level: float, c_delta: float) -> str:
    """Single governing credit environment from the level/velocity pair.

    Several of the section 5.2 rows match at once, so they are resolved by an
    explicit precedence rather than by the order they happen to be written in.

    The precedence is decided on the same principle as the regime classifier:
    a decisive turn outranks a still-elevated level. ``c_level = -1.0`` with
    ``c_delta = +1.5`` is spreads at a distress level that are closing fast --
    the reopening a recovery is made of -- and testing the level first gave it
    the harshest row in the table. That is the level/change conflation section
    2.1 was written to eliminate, reintroduced in the modifier. An
    environment is therefore Acute Crunch when the level is stressed *and has
    not turned*, not when the level is stressed.
    """
    if c_level <= -0.5 and c_delta >= 0.75:
        return "Recovery"
    if c_level <= -1.0 and c_delta < 0.75:
        return "Acute Crunch"
    if c_delta <= -0.75:
        return "Velocity Squeeze"
    # Strictly positive, not non-negative. The section 5.4 macro-absent default
    # is the neutral baseline (0.0, 0.0), and that baseline was resolving to
    # Accommodative -- the mildest row in the table, worth a 1.00 modifier for a
    # Strong company. So the state the framework falls back to when it knows
    # nothing was also the state it gives the best credit for, which is the
    # missing-data-is-a-signal rule of section 4.1 running backwards: absence of
    # a feed became a bonus. Section 5.4 explicitly prohibits defaulting to
    # Accommodative, and this was the default doing exactly that.
    if c_level >= 0.0 and c_delta >= 0.0 and (c_level > 0.0 or c_delta > 0.0):
        return "Accommodative"
    return "Normal"


def compute_cvs(metrics: dict) -> CVSScore:
    """Company Credit Vulnerability score, tier and evidence coverage.

    Follows the repository's missing-data standard from ``scoring.py``: an
    absent metric is imputed at the conservative 50-point baseline rather
    than dropped, because dropping it would hand a company with no leverage
    disclosure the best possible score on leverage.

    The Strong-tier gate is enforced here, not merely described. ``CVS < 30``
    on its own is reachable by a company that discloses no net debt at all,
    because the three pristine legs outweigh the imputed one. That company is
    Moderate, not Strong, and the gate is what keeps it there.
    """
    # Bracketed here rather than trusted from the caller: the function is
    # documented as taking 0-100 bracket scores, and every test that pins the
    # tier boundaries passes bracket values. A caller handing it raw ratios is
    # then silently scored on the wrong scale, which is what the pipeline did
    # before this. Bracketing is idempotent on an input that is already a
    # bracket only by accident -- 0 and 100 land where they should, but 25 maps
    # to 25 on the interest_coverage table and 50 on the leverage one, so the
    # function takes raw observations and is documented as doing so.
    metrics = {key: bracket_score(key, value) for key, value in metrics.items()}

    has_leverage = any(metrics.get(m) is not None for m in CVS_CORE_LEVERAGE)
    has_liquidity = metrics.get("quick_liquidity") is not None
    if not (has_leverage and has_liquidity):
        return CVSScore(None, 0.0, "unscorable", CVS_CORE_LEVERAGE)

    missing_core = tuple(m for m in CVS_CORE_LEVERAGE if metrics.get(m) is None)
    total = 0.0
    measured_weight = 0.0
    for key, weight in CVS_WEIGHTS.items():
        value = metrics.get(key)
        if value is None:
            total += CVS_IMPUTED_SCORE * weight
        else:
            total += value * weight
            measured_weight += weight

    cvs = total
    strong = cvs < CVS_STRONG_MAX_SCORE and all(
        metrics.get(m) is not None for m in CVS_STRONG_REQUIRED_METRICS
    )
    if strong:
        tier = "strong"
    elif cvs < CVS_MODERATE_MAX_SCORE:
        tier = "moderate"
    else:
        tier = "high"
    return CVSScore(cvs, measured_weight, tier, missing_core)


#: Section 4.3 brackets: metric -> ascending ``(threshold, points)`` pairs.
#: Each leg is scored 0 / 25 / 50 / 75 / 100, so the CVS is a weighted sum of
#: bracket scores rather than of raw ratios.
#:
#: These live here rather than in the pipeline because the tier boundaries in
#: CVS_TIER_MAX_SCORE are only meaningful against bracketed input. A raw
#: ``debt_to_ebitda`` of 2.0 is a perfectly ordinary ratio, and adding it as
#: though it were a 0-100 score contributes 0.5 points -- while a
#: ``credit_rating`` of 2.0 on the same footing contributes 0.3. Two legs on
#: incompatible scales, summed, with the tiers calibrated for neither.
CVS_BRACKETS = {
    # Low is good. Thresholds ascending: <= 1.75x is 0 points, above 5.5x is 100.
    "net_debt_to_ebitda": ((1.75, 0.0), (2.75, 25.0), (4.00, 50.0), (5.50, 75.0)),
    "refinancing_wall": ((0.25, 0.0), (0.50, 25.0), (1.00, 50.0), (1.50, 75.0)),
    # High is good, so these run the other way. A quick ratio of 1.5 covers
    # near-term obligations several times over; 0.2 does not.
    "interest_coverage": ((6.00, 0.0), (4.00, 25.0), (2.50, 50.0), (1.50, 75.0)),
    "quick_liquidity": ((1.20, 0.0), (0.90, 25.0), (0.65, 50.0), (0.45, 75.0)),
}

#: ``interest_coverage``, ``quick_liquidity`` and ``credit_rating`` read
#: high-is-good while the ratio legs read low-is-good. That is not a hand-kept
#: list here: the direction is derived from the bracket table's own shape, which
#: removes an opportunity to add a metric and get its direction silently wrong.
#: A table listing descending thresholds (6.0, 4.0, 2.5, 1.5 for interest
#: coverage) is satisfied by ``value >= threshold``; an ascending one
#: (1.75, 2.75, 4.0, 5.5 for leverage) by ``value <= threshold``. In both cases
#: the best bracket is the one the value reaches first, and the worst is the
#: fall-through.
CVS_INVERTED_METRICS = frozenset({"interest_coverage", "credit_rating"})

#: Bracket for ``credit_rating`` on a 1-5 agency scale where 1 is best-rated
#: (1 = AAA/AA, 5 = below B+). Low-is-good like the other two ratio legs, so the
#: table ascends and :func:`bracket_score` resolves the direction from that
#: shape rather than from a metric name.
#:
#: It is written out rather than folded into CVS_BRACKETS because it is a
#: bounded ordinal scale rather than a ratio: 5 is not "twice as bad" as 2.5, and
#: a filer's rating is a standing opinion rather than a measured quantity.
CVS_RATING_BRACKETS = ((1.50, 0.0), (2.50, 25.0), (3.00, 50.0), (3.50, 75.0))


def bracket_score(metric: str, value):
    """Map a raw observation onto its section 4.3 bracket, 0 to 100.

    Returns ``None`` for an absent input, because a bracket is a statement
    about evidence and absence is not evidence. Callers impute.

    ``interest_coverage`` and ``credit_rating`` are compared from the good end
    downward; every other leg is compared from the bad end upward. Both
    directions fall through to 100 past the last threshold, which is the
    "Distressed" column and has no upper bound.
    """
    value = _measured(value)
    if value is None:
        return None
    if metric == "credit_rating":
        table = CVS_RATING_BRACKETS
    else:
        table = CVS_BRACKETS.get(metric)
    if table is None:
        raise KeyError(f"no bracket defined for CVS metric {metric!r}")

    # Direction is read off the table rather than looked up. An ascending table
    # is a low-is-good leg and is satisfied by value <= threshold; a descending
    # one is high-is-good and satisfied by value >= threshold. Deriving it means
    # a new metric cannot be added with its direction wrong, which is the failure
    # that scored every covered company distressed when the two directions were
    # swapped on interest_coverage.
    descending = table[0][0] > table[-1][0]

    # The tables list brackets best-to-worst, so the answer is the points of
    # the FIRST entry the value satisfies -- which reads the same way for both
    # directions once `inside` accounts for it. A high-is-good leg satisfies
    # `value >= threshold` at its best bracket; a low-is-good leg satisfies
    # `value <= threshold`. Breaking on the first satisfaction is what makes a
    # value exactly on a boundary take that boundary's points.
    #
    # The obvious alternative -- keep walking and let the last satisfied entry
    # win -- is wrong in both directions, and wrong in a way that looks
    # plausible: it reports the WORST bracket every value satisfies, so a
    # pristine 1.75x-levered company lands at 75 points and an unrated 3.5
    # lands at 100. Both look like real numbers.
    points = 100.0
    for threshold, points_at in table:
        if (value >= threshold) if descending else (value <= threshold):
            return points_at
    return points


def _measured(value):
    """Normalise a metric input to ``None`` when it is not a real observation.

    A caller reading a warehouse row gets ``NaN``, not ``None``, for a metric
    the filer did not report. Treating that as a measurement multiplies ``NaN``
    into the weighted total, and the comparisons below then all fail, so the row
    falls through to the ``high`` tier -- the worst label in the table, reached
    by an arithmetic accident rather than by evidence. Reading a
    :class:`~pandas.Series` is the ordinary way this data arrives, so ``NaN`` is
    normalised to the same absent state as ``None``.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def credit_modifier(environment: str, tier: str, *, unscorable_is_stressed: bool = False) -> float:
    """Credit modifier for a scored row, or the conservative unscorable default."""
    if tier == "unscorable":
        key = "stressed" if unscorable_is_stressed else "benign"
        return UNSCORABLE_CVS_MODIFIER[key]
    return CREDIT_MODIFIER_TABLE[environment][tier]


def _breached(condition: bool | None) -> bool:
    """Return whether a circuit-breaker condition counts as breached.

    ``None`` is an unevaluated breaker and counts as breached; see
    :func:`evaluate_dividend_safety_override` for why.
    """
    return True if condition is None else bool(condition)


def evaluate_dividend_safety_override(
    c1: bool,
    c2: bool,
    c3: bool,
    c4: bool,
    c5: bool,
    cvs_score: float | None,
    macro_c_level: float,
    macro_c_delta: float,
) -> tuple[str, float]:
    """Return ``(flag, score_cap)`` for the solvency circuit breakers.

    Unconditional on macro state for the hard case: a broken capital structure
    is excluded whether or not credit is open. The systemic tier escalates a
    single breach only when capital markets are actually shut.
    """
    conditions = (c1, c2, c3, c4, c5)

    # ``None`` means "this breaker could not be evaluated", which is not a
    # pass. Counting it as a breach is the fail-closed direction: a circuit
    # breaker exists to stop the model from advancing a company whose
    # solvency it does not know, and an unevaluated breaker is exactly that
    # case. The alternative, treating ``None`` as unbreached, awards the clean
    # pass to precisely the rows the section 4.1 house standard forbids
    # rewarding for missing data -- and it does so silently, whereas the
    # original ``sum(conditions)`` formulation raised ``TypeError`` and took
    # the whole screening run down instead of deciding anything.
    breach_count = sum(1 for c in conditions if c is None or c)

    if breach_count >= 2 or (_breached(c1) and _breached(c4)):
        return "RED", OVERRIDE_CAPS["RED"]

    macro_stressed = macro_c_delta <= -0.75 or macro_c_level <= -1.0
    if breach_count == 1 and macro_stressed:
        return "SYSTEMIC_RED", OVERRIDE_CAPS["SYSTEMIC_RED"]

    if breach_count == 1 or (cvs_score is not None and cvs_score >= CVS_MODERATE_MAX_SCORE):
        return "YELLOW", OVERRIDE_CAPS["YELLOW"]

    return "GREEN", OVERRIDE_CAPS["GREEN"]


def apply_credit_modifier(composite_score: float, modifier: float) -> float:
    """Scale a composite by the credit modifier, preserving ``NaN``.

    ``float('nan') * 0.8`` is still ``NaN``, so the coverage-floor rejection
    survives the modifier without a branch. Stated explicitly because the
    whole layer depends on it: a row the base scorer refused to publish must
    not acquire a score here.
    """
    return composite_score * modifier


def apply_safety_cap(composite_score: float, cap: float) -> float:
    """Cap a composite at the override ceiling, preserving ``NaN``.

    The ``NaN`` check is explicit rather than left to ``min``. ``min(nan, cap)``
    does happen to be ``nan``, but that is an accident of argument order:
    ``min(cap, nan)`` returns ``cap``, because Python's ``min`` compares the
    second argument against the first and every comparison with ``nan`` is
    false. Relying on it would make the ``NULL``-preservation invariant
    (§6.2) depend on which way round two arguments were written.
    """
    if math.isnan(composite_score):
        return composite_score
    return min(composite_score, cap)


def final_score(composite_score: float, modifier: float, cap: float) -> float:
    """Apply the credit modifier and then the safety cap, in that order.

    Both steps are non-expansive, so a capped row stays capped, but the order
    is still observable: modifier-first is the specified sequence and keeps a
    capped row at exactly the ceiling rather than pushing it below for a
    breach the modifier has nothing to do with.
    """
    return apply_safety_cap(apply_credit_modifier(composite_score, modifier), cap)
