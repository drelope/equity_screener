import numpy as np
import pandas as pd

WEIGHTS = {
    "dividend_income_score": 0.25,
    "sustainability_score": 0.20,
    "legal_rights_score": 0.25,
    "appreciation_score": 0.15,
    "risk_score": 0.10,
    "valuation_score": 0.05,
}

#: Components computed from data. One component is still a constant:
#: ``legal_rights_score`` is imputed to a flat 0.5 for every security and is
#: 0.25 of the weight. It is excluded from the coverage denominator because
#: coverage is meant to answer "how much of this score is evidence", and an
#: imputation is never evidence. Counting it would put a floor of 0.25 under
#: every row, so a security with nothing measured would still report 25%
#: covered and the published number would say almost nothing.
#:
#: ``valuation_score`` used to be the second constant -- a hardcoded 0.5,
#: excluded for the same reason. It is now a real cross-sectional percentile
#: blend of the point-in-time valuation ratios (see :data:`VALUATION_PARTS`), so
#: it counts as evidence; a row with no valuation input simply loses that 0.05
#: rather than carrying a free placeholder reading.
MEASURABLE = (
    "dividend_income_score",
    "sustainability_score",
    "appreciation_score",
    "risk_score",
    "valuation_score",
)

#: Share of the total composite weight that must be present before a composite
#: is published at all. Below this the score is mostly a rescaled fragment of a
#: few percentiles, and a rank against a 5,443-name universe is a statement
#: about the peers who happened to report, not about the company.
#:
#: Measured against the *total* weight, not the measurable subtotal, and the
#: distinction is a policy choice rather than a rounding one. The one constant
#: component (``legal_rights_score``, 0.25) is always present, so this bar sits
#: at 0.50 - 0.25 = 0.25 of the 0.75 measurable weight, i.e. 33.3% coverage.
#: Requiring 0.50 of the *measurable* weight instead would be a stricter rule
#: wearing the same label and would drop names that clear the total-weight bar.
#: The stated threshold therefore stays on the total, where the round number
#: means what a reader expects it to mean.
MIN_PRESENT_WEIGHT = 0.50

#: Section 7.2 regime weight matrix, keyed by the stored column names rather
#: than the factor concepts the specification writes in. Keeping the translation
#: local means the matrix can stay transcribed verbatim from the spec, which is
#: the point -- it is a published table, and re-expressing it in a second set of
#: names is how the two drift apart unnoticed.
from .regime import REGIME_WEIGHTS  # noqa: E402  (needs WEIGHTS to exist first)

TRANSLATE = {
    "income": "dividend_income_score",
    "sustainability": "sustainability_score",
    "appreciation": "appreciation_score",
    "risk": "risk_score",
    "legal_rights": "legal_rights_score",
    "valuation": "valuation_score",
}

#: Inner blends. Lower payout is better for both fcf_payout and dividend_coverage,
#: hence the per-part direction; growth is higher-is-better.
SUSTAINABILITY_PARTS = {
    "dividend_coverage": (0.5, True),
    "dividend_growth": (0.2, True),
    "fcf_payout": (0.3, False),
}
APPRECIATION_PARTS = {
    "momentum_252d": (0.6, True),
    "momentum_63d": (0.4, True),
}
#: Valuation: cheaper is better, blended over whichever ratios a filer reports.
#: Earnings yield and FCF yield are higher-is-better cash-flow signals;
#: price-to-book is lower-is-better. P/E is deliberately not a fourth part --
#: it is the reciprocal of earnings yield, so including both would weight the
#: same earnings fact twice. Each ratio is NULL upstream when its denominator is
#: absent or non-positive, so the blend renormalises over what exists and
#: returns NaN when none of the three is present.
VALUATION_PARTS = {
    "earnings_yield": (0.4, True),
    "fcf_yield": (0.4, True),
    "price_to_book": (0.2, False),
}


def pct(s, high=True):
    r = pd.to_numeric(s, errors="coerce").rank(pct=True)
    return r if high else 1 - r


def _blend(x, parts):
    """Weighted blend renormalised over the parts that are present.

    Returns ``(value, present_weight)``. A plain weighted sum across a part that
    is missing for one row silently rescales that row's remaining parts and
    reports it as a full-strength number, which is how a security with two
    percentiles and one with all four used to share a column. Returning the
    shortfall separately lets the caller decide whether enough of the blend is
    there to publish, instead of the blend deciding on its own.

    An inner part is renormalised the same way as the composite: a filer
    reporting no dividend growth still has a dividend coverage ratio, and
    dropping the whole sub-score for one missing leg throws away a measurement
    that was actually taken.
    """
    value = pd.Series(0.0, index=x.index, dtype=float)
    present = pd.Series(0.0, index=x.index, dtype=float)
    for column, (weight, high) in parts.items():
        # A column the caller did not carry at all is treated the same as one
        # that is present-but-null: the part simply does not count. This lets a
        # frame built before a part existed keep scoring on the parts it has,
        # rather than raising on the new column name.
        if column not in x:
            continue
        series = pct(x[column], high)
        available = series.notna()
        value = value + series.where(available, 0.0) * weight
        present = present + available.astype(float) * weight
    return value / present.where(present > 0), present


def regime_weights(regime):
    """Map a regime name to the factor weights it blends with.

    Returns ``WEIGHTS`` for anything not in :data:`~src.crispdm.regime.REGIME_WEIGHTS`,
    which includes ``None``. That fallback is the safe direction: an unrecognised
    regime falls back to the published baseline rather than to a blend that
    nobody approved, and ``None`` in particular is what arrives while the macro
    feed is absent.

    The keys differ from :data:`WEIGHTS` -- ``income`` versus
    ``dividend_income_score``, ``legal_rights`` versus ``legal_rights_score`` --
    because the regime matrix is written against the factor concepts while the
    scorer's weights are written against the stored columns. TRANSLATE is the
    only place that knows both.
    """
    table = REGIME_WEIGHTS.get(regime)
    if table is None:
        return WEIGHTS
    return {TRANSLATE[k]: w for k, w in table.items()}


def score(df, regime=None):
    """Score each security, publishing how much of the result is evidence.

    The composite is renormalised over whichever components are present, so it
    stays on the same 0-1 scale as a fully measured row and the percentile
    ranks remain comparable across the universe.

    Two thresholds, deliberately on different denominators. The composite is
    published when ``MIN_PRESENT_WEIGHT`` of the *total* weight is present,
    which is the floor the policy was set with. ``score_coverage`` reports the
    share of the *measurable* weight, so it answers "how much of this is a
    measurement" and bottoms out at 0 for a security with nothing measured --
    which a total-weight figure cannot do, because the one constant component
    (``legal_rights_score``) guarantees every row a reading of at least 0.25.

    That trade is deliberate. The previous plain sum left 4,127 of 5,443
    securities unscored -- 75.8% -- so the score was unusable for the portfolio,
    while a few percentiles of a mostly-missing row would have been published as
    if they were a full reading. Renormalising plus a floor keeps the column
    mostly populated and makes the gaps visible in a second column instead of
    silently scoring them as zero.

    ``regime`` selects the section 7.2 weight matrix for the composite blend.
    Three things stay on the baseline regardless, which is section 7.1's
    requirement rather than an implementation convenience:

    * ``score_coverage`` is computed against :data:`WEIGHTS`. Coverage is a
      statement about what a filer disclosed. Letting it move with the business
      cycle would mean a security could lose coverage by nothing other than the
      economy turning, and two runs of the same data would report different
      coverage for the same row.
    * The ``MIN_PRESENT_WEIGHT`` floor is evaluated against :data:`WEIGHTS`, so
      no security is excluded or resurrected by shifting emphasis.
    * ``Baseline`` in the matrix is :data:`WEIGHTS`, so ``regime=None`` and
      ``regime="Baseline"`` are the same computation.

    Only the blend moves. That is what makes the tilt safe to apply while the
    macro feed is still absent: with no regime, every row blends on baseline
    weights and the output is byte-identical to the previous implementation.
    """
    x = df.copy()
    x["dividend_income_score"] = pct(x.dividend_yield)
    x["sustainability_score"] = _blend(x, SUSTAINABILITY_PARTS)[0]
    x["legal_rights_score"] = x.legal_rights_score.fillna(0.5)
    x["appreciation_score"] = _blend(x, APPRECIATION_PARTS)[0]
    x["risk_score"] = pct(x.volatility_252d, False)
    x["valuation_score"] = _blend(x, VALUATION_PARTS)[0]

    # Baseline weights decide who gets published and how much of it was
    # measured; regime weights decide only how the published number is composed.
    baseline_present = pd.Series(0.0, index=x.index, dtype=float)
    measured_present = pd.Series(0.0, index=x.index, dtype=float)
    available = {}
    for name, weight in WEIGHTS.items():
        series = x[name]
        present = series.notna()
        available[name] = present
        baseline_present = baseline_present + present.astype(float) * weight
        if name in MEASURABLE:
            measured_present = measured_present + present.astype(float) * weight

    weights = regime_weights(regime)
    value = pd.Series(0.0, index=x.index, dtype=float)
    total_present = pd.Series(0.0, index=x.index, dtype=float)
    for name, weight in weights.items():
        series = x[name]
        value = value + series.where(available[name], 0.0) * weight
        total_present = total_present + available[name].astype(float) * weight

    measurable = sum(WEIGHTS[name] for name in MEASURABLE)
    x["score_coverage"] = measured_present / measurable
    # The floor is checked on baseline_present, not total_present. Renormalising
    # on regime weights would let a tilt move the bar: a regime that shifts
    # weight onto an absent factor would drop rows that clear the baseline floor,
    # which section 7.1 forbids.
    x["composite_score"] = (value / total_present.where(total_present > 0)).where(
        baseline_present >= MIN_PRESENT_WEIGHT
    )
    return x


def predictions(
    scores,
    run_id,
    threshold=0.5,
    model_version="rule_scoring_v1",
    # feature_version and data_version must equal the constants in
    # scripts.evaluate_walk_forward and the versions in the live checkpoint.
    # Those two describe the world the rows were computed from, not the
    # algorithm -- which is why model_version stays rule_scoring_v1, since the
    # rule scorer genuinely is a different model from the walk-forward
    # logistic regression. Binding the other two is what makes the next input
    # change self-invalidating here too.
    #
    # Both defaults had drifted, and the drift was invisible because
    # model.predictions was empty: nothing had ever been written to contradict
    # them, so the first score_rank run would have stamped new rows with a
    # feature version the checkpoint had retired (v2, period-end alignment, fed
    # the model a quarter's earnings before it was filed) and a data version
    # that no longer described the stored inputs (v2, the unversioned relation,
    # superseded by V0009 filing-vintaged fundamentals). Worse, the two counters
    # had diverged into unrelated series: this module's v2 had meant "per-share
    # dividend amounts under V0006" while evaluate_walk_forward's v2 meant
    # "period-end alignment", so the shared string named two different things.
    # tests/test_scoring.py now pins all three sources together.
    #
    # features_v5 nulls a negative debt balance and computes dividend growth from the
    # per-payment series only where its prior-year window is observed. features_v4 is
    # total-return momentum plus a fundamentals availability date
    # that cannot precede the period it reports. The per-metric quarterly vintage
    # chain from v3 is unchanged, and the leverage inputs added in V0011 join
    # that same chain without changing what any declared column means.
    feature_version="features_v5",
    data_version="sec_xbrl_v3",
):
    """Derive model.predictions rows from model.scores.

    The rule-based scorer produces a percentile composite score, so the
    sustainable-dividend probability is the composite itself and the predicted
    class is the composite against ``threshold``. It is a relative rank, not a
    calibrated probability: the ML model was evaluated and rejected (NO-GO,
    2026-10-06), and this scorer is the product. ``run_id`` is generated once
    per campaign so all rows share one immutable model run.
    """
    x = scores.copy()
    x["run_id"] = run_id
    x["probability"] = x["composite_score"].clip(0, 1)
    # NULL stays NULL rather than becoming 0. `NaN >= threshold` is False, so
    # astype(int) filed every unscorable security as a confident "not
    # sustainable" call -- a false negative awarded for missing data, and the
    # exact mirror of reading an undisclosed interest line as zero interest.
    # A row below the coverage floor is not a prediction against the threshold.
    x["predicted_class"] = (x["composite_score"] >= threshold).astype("Int64")
    x["precision_threshold"] = threshold
    x["model_version"] = model_version
    x["feature_version"] = feature_version
    x["data_version"] = data_version
    x["as_of_date"] = x["as_of_date"] if "as_of_date" in x.columns else None
    return x


def rankings(scores, predictions_df=None):
    """Derive model.rankings rows from model.scores (rank by composite score).

    A composite that is NaN or infinite is left unranked (NULL) rather than
    ranked. The composite is a plain weighted sum, so a single missing input
    propagates and the whole row becomes NaN; casting that to the integer rank
    column raised IntCastingNaNError, which is how the first run of this script
    died. Unranked is also the honest outcome: there is no position for a
    security with no score.

    Whether those rows *should* be scoreable is a scoring-policy question and
    is deliberately not decided here -- see the coverage report in
    scripts/score_rank.py.
    """
    x = scores.copy()
    finite = pd.to_numeric(x["composite_score"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    # float ranks, so NaN survives; the writer maps NaN to NULL.
    x["rank"] = finite.rank(ascending=False, method="first")
    if predictions_df is not None and "probability" in predictions_df.columns:
        probs = predictions_df[["security_id", "as_of_date", "probability"]]
        x = x.merge(probs, on=["security_id", "as_of_date"], how="left")
    else:
        x["probability"] = x["composite_score"].clip(0, 1)
    return x
