import numpy as np
import pandas as pd

#: Section 7.1 factor weights, renormalised to 1.0.
#:
#: ``legal_rights_score`` is retired from the composite. It was a flat 0.5
#: imputation over a column that is NULL for every row (``preferred.contract_terms``
#: holds 212 terms against 612 active preferreds and no score is defined over
#: them), carrying 0.25 of the weight -- so every security received the same
#: 0.125 of composite regardless of evidence. That is not measurement, and a
#: constant leg also put a 0.25 floor under ``score_coverage``, so a security
#: with nothing measured still reported 25% covered. Retiring the weight makes
#: the composite 100% evidence-backed and lets coverage bottom out at 0.
#:
#: The five remaining weights renormalise over the 0.75 they now share
#: (0.25/0.20/0.15/0.10/0.05 divided by 0.75), so the composite is a weighted
#: mean of measured components and a complete row's score is unchanged relative
#: to its peers -- the removal of the constant is an affine rescaling that
#: preserves the ranking among fully measured names.
WEIGHTS = {
    "dividend_income_score": 0.25 / 0.75,
    "sustainability_score": 0.20 / 0.75,
    "appreciation_score": 0.15 / 0.75,
    "risk_score": 0.10 / 0.75,
    "valuation_score": 0.05 / 0.75,
}

#: Components computed from data. Every component is now measured: the one
#: constant, ``legal_rights_score`` (an imputed 0.5 worth 0.25 of the weight),
#: has been retired from :data:`WEIGHTS`. Coverage is therefore the share of the
#: total weight a filer actually disclosed, and it can reach 0 -- which a
#: constant leg made impossible, since it guaranteed every row a 0.25 floor.
#:
#: ``valuation_score`` used to be a second constant (a hardcoded 0.5) before it
#: became a real cross-sectional percentile blend (:data:`VALUATION_PARTS`).
MEASURABLE = tuple(WEIGHTS)

#: Share of the total composite weight that must be present before a composite
#: is published at all. Below this the score is mostly a rescaled fragment of a
#: few percentiles, and a rank against a 5,443-name universe is a statement
#: about the peers who happened to report, not about the company.
#:
#: Measured against the *total* weight. With every component measurable, the
#: total and the measurable weight are the same 1.0, so the floor is 0.50 of
#: both. Before ``legal_rights_score`` was retired, 0.25 of the total was a
#: constant, so the same 0.50 bar sat at only 0.333 of measurement -- and the
#: change is stricter by that amount, which was measured at 52 of 2,779 scored
#: names at the latest date (a 1.9% cohort reduction) before being kept.
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

    Each matrix row is renormalised over its own sum. The specification still
    writes the rows as they were transcribed -- the retired ``legal_rights`` leg
    removed, leaving the remaining five summing to 0.75 (baseline) or 0.90
    (elsewhere). Renormalising here rather than editing the table keeps the
    published numbers readable as the spec's, while guaranteeing every blend is
    a weighted mean over 1.0 and ``regime="Baseline"`` reproduces :data:`WEIGHTS`
    exactly (the baseline row divided by its own 0.75 is the same arithmetic as
    the renormalised :data:`WEIGHTS`).

    The keys differ from :data:`WEIGHTS` -- ``income`` versus
    ``dividend_income_score`` -- because the regime matrix is written against the
    factor concepts while the scorer's weights are written against the stored
    columns. TRANSLATE is the only place that knows both.
    """
    table = REGIME_WEIGHTS.get(regime)
    if table is None:
        return WEIGHTS
    weights = {TRANSLATE[k]: w for k, w in table.items()}
    total = sum(weights.values())
    if not total:
        return weights
    return {name: w / total for name, w in weights.items()}


def score(df, regime=None):
    """Score each security, publishing how much of the result is evidence.

    The composite is renormalised over whichever components are present, so it
    stays on the same 0-1 scale as a fully measured row and the percentile
    ranks remain comparable across the universe.

    Two thresholds, deliberately on different denominators. The composite is
    published when ``MIN_PRESENT_WEIGHT`` of the *total* weight is present,
    which is the floor the policy was set with. ``score_coverage`` reports the
    share of the *measurable* weight, so it answers "how much of this is a
    measurement". The two now coincide -- every component is measured, so the
    measurable weight equals the total weight of 1.0 -- but they are kept as
    separate concepts because they answer different questions and the coverage
    denominator must stay fixed even if a constant leg ever returns.

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
    weights, and ``regime=None`` is byte-identical to ``regime="Baseline"``.
    """
    x = df.copy()
    x["dividend_income_score"] = pct(x.dividend_yield)
    x["sustainability_score"] = _blend(x, SUSTAINABILITY_PARTS)[0]
    # ``legal_rights_score`` is deliberately not computed: it is retired from
    # the composite (see WEIGHTS). score_rank still carries the raw column
    # through to model.scores, where it stays NULL for every row -- the honest
    # value for a metric with no defined measurement.
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
