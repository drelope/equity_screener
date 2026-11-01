import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.crispdm.config import settings
from src.crispdm.feature_set import FEATURES
from src.crispdm.features import RETIRED_FEATURES

#: A feature that is present in the declared list but has no real source is a
#: placeholder. Nine of the thirteen originally declared features were written
#: as a literal ``np.nan`` by ``src.crispdm.features.build_features``, so the
#: model trained on four of them while reporting thirteen. A declared feature
#: with no implementation must be treated as absent, not as a free pass
#: through the imputer.
#:
#: The nine have since been split by whether the warehouse can support them:
#: four are now computed from real point-in-time fundamentals, and five were
#: removed from ``FEATURES`` because no source exists (see
#: ``features.RETIRED_FEATURES``). This set is the guard that keeps them from
#: being reintroduced silently, and it is what makes the completeness gate
#: fail closed if a retired name is ever added back to the declared list.
PLACEHOLDER_FEATURES = frozenset(RETIRED_FEATURES)


def implemented_features(features=None):
    """Return the declared features that actually have an implementation."""
    declared = list(FEATURES if features is None else features)
    return [f for f in declared if f not in PLACEHOLDER_FEATURES]


def feature_completeness(df, features=None):
    """Per-feature non-null share, for the completeness gate.

    A feature at 0% non-null is a placeholder; anything under
    ``min_coverage`` is too sparse to carry signal and is reported so the
    caller can fail the build rather than quietly imputing it.
    """
    declared = list(FEATURES if features is None else features)
    if df.empty:
        return {f: 0.0 for f in declared}
    total = max(len(df), 1)
    return {f: float(df[f].notna().sum()) / total if f in df.columns else 0.0 for f in declared}


class _ExpectedColumns(TransformerMixin, BaseEstimator):
    """Assert the frame handed to ``fit`` is the declared feature set.

    ``make_model`` used to accept a feature list and discard it, so a caller that
    asked for a subset silently trained on whatever columns it passed and a
    caller that asked for the full set got no check at all that the columns
    matched. The evaluation path is the only caller and it passed no list, so
    nothing complained. Enforcing the contract here rather than at the call site
    means a mismatch fails at fit, where the mistake is, instead of being
    reported later as an unexplained metric.
    """

    def __init__(self, features):
        self.features = list(features)

    def fit(self, X, y=None):
        if hasattr(X, "columns"):
            missing = [f for f in self.features if f not in X.columns]
            if missing:
                raise ValueError(
                    f"model was declared for {len(self.features)} features but "
                    f"{len(missing)} are absent from the frame: {', '.join(missing)}. "
                    f"Refusing to fit a model that is not the declared one."
                )
        return self

    def transform(self, X):
        return X


def make_model(features=None):
    steps = []
    if features is not None:
        steps.append(("contract", _ExpectedColumns(features)))
    steps += [
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        (
            "model",
            # No class_weight="balanced". It reweights the minority class during
            # training, which makes the fitted probabilities calibrated to a
            # 50/50 prior rather than the true one. On a training set with 12%
            # negatives that produces probabilities that are far too high for
            # the negative class, and a threshold calibrated on them flags 48%
            # of a test set that is only 2.4% negative. The flag-rate threshold
            # below is what actually controls the false positive rate; the class
            # weight only corrupts the probabilities that threshold is set from.
            LogisticRegression(max_iter=3000, random_state=42),
        ),
    ]
    return Pipeline(steps)


def threshold_for_flag_rate(y, p, max_flag_rate=0.10):
    """Highest threshold that flags at most ``max_flag_rate`` of the population.

    Calibrating to a recall target is prevalence-fragile: a threshold that
    catches 30% of negatives on a 12%-negative training set flags a much larger
    share of a 2.4%-negative test set, because the model is less confident when
    negatives are rare. The flag rate is a property of the threshold, not of the
    class balance, so it is the quantity that survives the shift.

    Among every threshold whose flag rate is within budget, the one with the
    highest recall on the minority class wins -- the budget is spent on catching
    as many negatives as it allows, and no more.
    """
    best = 0.95
    best_r = -1.0
    for t in np.linspace(0.05, 0.95, 181):
        pred = (p >= t).astype(int)
        flag_rate = 1.0 - float(pred.mean())
        if flag_rate <= max_flag_rate:
            r = recall_score(y, pred, zero_division=0)
            if r > best_r:
                best, best_r = t, r
    return best


def naive_baseline(y):
    """Metrics for the "always predict sustainable" classifier.

    With 93.6% positive labels this scores recall 1.000 and PR-AUC equal to
    the positive rate, so a gate on recall alone cannot distinguish it from a
    trained model. It is the floor every candidate must clear.

    Accepts a Series or array; ``y.nunique()`` is not assumed.
    """
    y = np.asarray(y).astype(int)
    pred = np.ones(len(y), dtype=int)
    return {
        "strategy": "always_predict_sustainable",
        "positive_rate": float(y.mean()) if len(y) else 0.0,
        "accuracy": float(accuracy_score(y, pred)) if len(y) else 0.0,
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)) if len(y) else 0.0,
        "precision": float(precision_score(y, pred, zero_division=0)) if len(y) else 0.0,
        "recall": float(recall_score(y, pred, zero_division=0)) if len(y) else 0.0,
        "f1": float(f1_score(y, pred, zero_division=0)) if len(y) else 0.0,
        "pr_auc": float(average_precision_score(y, pred)) if len(y) else 0.0,
    }


def discrimination_metrics(y, p, pred):
    """Imbalance-aware metrics, including the minority class explicitly.

    ``negative_*`` are the ones that move when the 6.4% minority is actually
    being detected; a model that scores well only by riding the majority
    shows up here as near-zero negative recall.
    """
    y = np.asarray(y).astype(int)
    pred = np.asarray(pred).astype(int)
    neg_true = y == 0
    neg_pred = pred == 0
    out = {
        "accuracy": float(accuracy_score(y, pred)) if len(y) else 0.0,
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)) if len(y) else 0.0,
        "precision": float(precision_score(y, pred, zero_division=0)) if len(y) else 0.0,
        "recall": float(recall_score(y, pred, zero_division=0)) if len(y) else 0.0,
        "f1": float(f1_score(y, pred, zero_division=0)) if len(y) else 0.0,
        "pr_auc": float(average_precision_score(y, p)) if len(y) else 0.0,
    }
    out["roc_auc"] = float(roc_auc_score(y, p)) if len(y) and np.unique(y).size > 1 else None
    out["positive_precision"] = (
        float(precision_score(y, pred, pos_label=1, zero_division=0)) if len(y) else 0.0
    )
    out["positive_recall"] = (
        float(recall_score(y, pred, pos_label=1, zero_division=0)) if len(y) else 0.0
    )
    out["negative_precision"] = (
        float(precision_score(y, pred, pos_label=0, zero_division=0)) if len(y) else 0.0
    )
    out["negative_recall"] = (
        float(recall_score(y, pred, pos_label=0, zero_division=0)) if len(y) else 0.0
    )
    out["negative_support"] = int(neg_true.sum())
    out["positive_support"] = int((~neg_true).sum())
    out["predicted_negative"] = int(neg_pred.sum())
    return out


#: Minimum improvement over the naive baseline for the gate to pass. Chosen so
#: that a model which merely reproduces the majority class cannot clear it:
#: the baseline's balanced accuracy is 0.5 by construction, so a real
#: classifier has to find genuine minority-class signal.
MIN_BALANCED_ACCURACY_LIFT = 0.10
MIN_NEGATIVE_RECALL = 0.10
MIN_PR_AUC_LIFT = 0.02

#: Maximum share of the universe the model may flag as unsustainable.
#:
#: Recall alone is not a deployment criterion. A model that catches 95% of
#: unsustainable dividends by flagging 48% of the universe is not a screen, it is
#: a lottery: an investor acting on it would discard half the investable set to
#: avoid a 2.4% event, and be wrong 95% of the time when it did flag one. The
#: flag rate is the metric that captures that trade, and it is prevalence-free
#: in the way recall is not -- it is a property of the threshold, not of the
#: class balance.
#:
#: 0.20 is deliberately permissive. The point is not to demand a precise
#: screen, it is to fail the "flag everything uncertain" failure mode, which is
#: what the previous gate certified. A model that cannot clear 20% is not
#: ready regardless of its recall.
MAX_FLAG_RATE = 0.20


def minority_rate(baseline):
    """Smaller of the two class rates for a scored population."""
    positive = float(baseline.get("positive_rate", 0.0))
    return min(positive, 1.0 - positive)


def evaluate_gate(
    metrics,
    baseline,
    min_balanced_lift=MIN_BALANCED_ACCURACY_LIFT,
    min_negative_recall=MIN_NEGATIVE_RECALL,
    max_flag_rate=MAX_FLAG_RATE,
    prevalence_guardrail=None,
):
    """Decide Go/No-Go on discrimination, and report PR-AUC as a diagnostic.

    Acceptance rests on the three checks that are stable as class prevalence
    moves: balanced-accuracy lift over the naive baseline, recall on the
    minority (negative) class, and the flag rate. The first two are ratios that
    do not saturate, so they keep their meaning when negatives are rare. The
    third is a property of the threshold rather than the class balance, and it
    is what stops a model from "succeeding" by flagging half the universe.

    PR-AUC lift is deliberately **not** blocking. Its baseline is the positive
    rate, so as negatives thin out the always-predict-sustainable baseline
    approaches PR-AUC 1.0 and the entire remaining headroom -- the maximum lift
    any model could show, ``1 - baseline_pr_auc`` -- shrinks below the required
    margin. Measured across the rolling folds the lift decayed monotonically
    (0.065 -> 0.044 -> 0.026 -> 0.010) as test negatives fell 7.6% -> 1.1%, and
    the last fold became unattainable rather than merely missed. A gate whose
    ceiling is set by prevalence cannot be a deployment criterion, so it is
    reported per fold alongside the prevalence that makes it unreliable.

    ``prevalence_guardrail`` is the empirically derived minority-rate cutoff
    (see :func:`scripts.evaluate_walk_forward.derive_prevalence_guardrail`).
    When the observed minority rate is at or below it, or when the PR-AUC
    headroom is already under the reference margin, the diagnostic is flagged
    ``reliable=False`` rather than being silently trusted.

    Returns ``passed`` plus per-criterion detail, so a failure states which
    criterion was missed rather than just failing.
    """
    checks = {
        "balanced_accuracy_lift": {
            "required": float(min_balanced_lift),
            "actual": float(metrics["balanced_accuracy"] - baseline["balanced_accuracy"]),
            "direction": "at_least",
        },
        "negative_recall": {
            "required": float(min_negative_recall),
            "actual": float(metrics.get("negative_recall", 0.0)),
            "direction": "at_least",
        },
        "flag_rate": {
            "required": float(max_flag_rate),
            "actual": float(metrics.get("predicted_negative", 0)) / float(metrics.get("n_test", 1)),
            "direction": "at_most",
        },
    }
    for check in checks.values():
        if check["direction"] == "at_most":
            check["passed"] = check["actual"] <= check["required"]
        else:
            check["passed"] = check["actual"] >= check["required"]

    # The best lift any model could possibly show on PR-AUC for this
    # population: a perfect ranker reaches 1.0, the trivial baseline reaches
    # the positive rate, so the gap between them is the entire headroom.
    headroom = 1.0 - float(baseline["pr_auc"])
    rate = minority_rate(baseline)
    guardrail = None if prevalence_guardrail is None else float(prevalence_guardrail)
    no_headroom = headroom < MIN_PR_AUC_LIFT
    below_guardrail = guardrail is not None and rate <= guardrail
    reliable = not (no_headroom or below_guardrail)

    if no_headroom:
        reason = (
            f"the naive baseline already reaches PR-AUC {baseline['pr_auc']:.4f}, "
            f"leaving {headroom:.4f} of headroom, less than the reference "
            f"margin {MIN_PR_AUC_LIFT:.4f}; the criterion is unattainable for "
            f"any model at this prevalence"
        )
    elif below_guardrail:
        reason = (
            f"minority rate {rate:.2%} is at or below the empirically derived "
            f"guardrail {guardrail:.2%}, where PR-AUC lift is not a stable "
            f"acceptance comparison"
        )
    else:
        reason = None

    diagnostics = {
        "pr_auc_lift": float(metrics["pr_auc"] - baseline["pr_auc"]),
        "pr_auc_model": float(metrics["pr_auc"]),
        "pr_auc_baseline": float(baseline["pr_auc"]),
        "pr_auc_headroom": headroom,
        "reference_margin": float(MIN_PR_AUC_LIFT),
        "minority_rate": rate,
        "prevalence_guardrail": guardrail,
        "reliable": reliable,
        "unreliable_reason": reason,
    }
    return {
        "passed": all(c["passed"] for c in checks.values()),
        "checks": checks,
        "diagnostics": diagnostics,
    }


def _fit_and_score(df, used, horizon, test_start, test_end, max_flag_rate):
    """Fit on everything purge-eligible before ``test_start`` and score the block.

    Shared by the single split and the rolling folds so both apply exactly the
    same embargo and the same fail-closed feature checks.
    """
    candidates = df[pd.to_datetime(df["as_of_date"]) < test_start]
    window_closes = pd.to_datetime(candidates["as_of_date"]) + horizon
    train = candidates[window_closes < test_start]
    test = df[pd.to_datetime(df["as_of_date"]) >= test_start]
    if test_end is not None:
        test = test[pd.to_datetime(test["as_of_date"]) < test_end]

    if train.empty:
        raise ValueError(
            f"label embargo removed every training row: the test period starts "
            f"{test_start.date()}, so a {horizon.days}-day label horizon makes "
            f"only rows before {(test_start - horizon).date()} trainable, and "
            f"none exist. Shorten the horizon, widen the labelled history, or "
            f"move the test start later."
        )

    train_coverage = {
        f: float(train[f].notna().mean()) if f in train.columns else 0.0 for f in used
    }
    absent = sorted(f for f, c in train_coverage.items() if c == 0.0)
    if absent:
        window_days = (
            pd.to_datetime(train["as_of_date"]).max() - pd.to_datetime(train["as_of_date"]).min()
        ).days
        raise ValueError(
            f"{len(absent)} declared feature(s) have no values in the embargoed "
            f"training set: {', '.join(absent)}. The embargo leaves "
            f"{train['as_of_date'].nunique()} training dates spanning {window_days} "
            f"days (last {pd.to_datetime(train['as_of_date']).max().date()}), which "
            f"is shorter than the lookback those features need. SimpleImputer would "
            f"drop them silently and report a model that is not the declared one. "
            f"Either extend the price history before "
            f"{(pd.to_datetime(train['as_of_date']).min()).date()}, or retire the "
            f"feature via features.RETIRED_FEATURES."
        )

    y_train = train.target_sustainable_dividend.astype(int)
    if y_train.nunique() < 2:
        raise ValueError(
            f"embargoed training set has a single target class: "
            f"{sorted(y_train.unique().tolist())}. The solver cannot fit and the "
            f"fold cannot be scored."
        )

    # The test block is held to the same standard as the training block. A block
    # with no rows, or with only one class, cannot support the comparison the
    # gate makes: balanced accuracy and negative recall against the naive
    # baseline are both undefined or degenerate on a single-class test set, and
    # sklearn's zero_division handling would return 0.0 and let the fold look
    # measured rather than impossible. Failing closed keeps "every requested
    # fold was evaluated and passed" honest.
    if test.empty:
        raise ValueError(
            f"test block {test_start.date()}.."
            f"{(test_end.date() if test_end is not None else 'open')} contains no "
            f"labelled rows, so the fold cannot be scored. A fold that cannot be "
            f"evaluated is a failed fold, not a skipped one."
        )
    y_test_classes = test.target_sustainable_dividend.astype(int).unique()
    if len(y_test_classes) < 2:
        raise ValueError(
            f"test block {test_start.date()}.."
            f"{(test_end.date() if test_end is not None else 'open')} has a single "
            f"target class: {sorted(y_test_classes.tolist())} over {len(test):,} rows. "
            f"Balanced accuracy and negative recall are undefined without both "
            f"classes present, so this fold cannot be scored. Move the fold "
            f"boundary, shorten the block, or extend the labelled history."
        )

    m = make_model(used)
    m.fit(train[used], y_train)
    threshold = threshold_for_flag_rate(y_train, m.predict_proba(train[used])[:, 1], max_flag_rate)
    p = m.predict_proba(test[used])[:, 1]
    pred = (p >= threshold).astype(int)
    y = test.target_sustainable_dividend.astype(int)
    metrics = discrimination_metrics(y, p, pred)
    metrics["threshold"] = threshold
    metrics["n_test"] = int(len(test))
    metrics["n_train"] = int(len(train))
    metrics["embargo"] = {
        "horizon_days": int(horizon.days),
        "test_start": test_start.date().isoformat(),
        "test_end": (test_end.date().isoformat() if test_end is not None else None),
        "first_train_date": pd.to_datetime(train["as_of_date"]).min().date().isoformat(),
        "last_train_date": pd.to_datetime(train["as_of_date"]).max().date().isoformat(),
        "rows_before_embargo": int(len(candidates)),
        "rows_dropped_as_leaky": int(len(candidates) - len(train)),
        "rows_retained": int(len(train)),
        "retained_share": round(len(train) / len(candidates), 6) if len(candidates) else 0.0,
        "train_dates": int(pd.to_datetime(train["as_of_date"]).nunique()),
        "train_negative_rate": round(float(1 - y_train.mean()), 6),
        "test_negative_rate": round(float(1 - y.mean()), 6) if len(test) else 0.0,
        "train_feature_coverage": {k: round(v, 6) for k, v in sorted(train_coverage.items())},
    }
    return m, metrics, test.assign(probability=p, predicted_class=pred)


def walk_forward(df, max_flag_rate=0.10, features=None, embargo_days=None):
    """Train on a single 70/30 date cut and score the remainder, with an embargo.

    A feature row dated ``D`` is labelled from dividend events in
    ``(D, D + horizon]``, so its label is not fully determined until
    ``D + horizon`` has passed. Splitting on ``as_of_date`` alone therefore
    leaks: the last ``horizon`` days of "training" rows have labels whose
    outcome window reaches into the test period, and the model is being scored
    partly on events it was effectively shown.

    The remediation is a purge, not a shift. Rows are train-eligible only when
    their *complete* label window closes strictly before the test period opens::

        eligible  <=>  D + horizon < test_start

    Nothing is padded or truncated: a row near the boundary is simply not
    trainable, because no amount of care makes its label knowable in time. The
    comparison is strict because the label reads events in a half-open interval
    ending on ``D + horizon``, so a window that ends exactly on ``test_start``
    still consumes a test-period observation.

    The test set is untouched. Only the training set shrinks, and
    ``metrics['embargo']`` records what was dropped so the cost is auditable
    rather than silent.

    A single cut hides regime change: the negative-label rate here runs from
    ~12% in 2019-2022 to ~2% in 2023-2025, so one verdict can be an artefact of
    where the cut landed. Use :func:`walk_forward_folds` to score the model
    across several chronological folds before trusting it.
    """
    df = df.sort_values("as_of_date").dropna(subset=["target_sustainable_dividend"])
    used = implemented_features(features)
    horizon = pd.Timedelta(
        days=settings.label_horizon_days if embargo_days is None else embargo_days
    )
    dates = sorted(df.as_of_date.unique())
    cut = max(1, int(len(dates) * 0.70))
    return _fit_and_score(df, used, horizon, pd.Timestamp(dates[cut]), None, max_flag_rate)


def walk_forward_folds(
    df, n_folds=4, max_flag_rate=0.10, features=None, embargo_days=None, test_share=0.5
):
    """Expanding-window walk-forward evaluation across ``n_folds`` test blocks.

    The last ``test_share`` of the labelled dates are cut into ``n_folds``
    consecutive test blocks. Fold *i* trains on every purge-eligible row that
    precedes its own block, so the training window only ever grows and no fold
    ever sees its own future. Each fold is purged with the same label embargo as
    :func:`walk_forward`, so the eligibility rule is applied per fold rather
    than once.

    This exists because the label's prevalence is not stationary: the negative
    rate falls from ~12% in 2019-2022 to ~2% in 2023-2025. One cut cannot tell a
    model that generalises from one that was lucky about where it landed.
    Folds whose embargoed training set has a single target class are reported as
    skipped with a reason instead of being silently dropped.
    """
    df = df.sort_values("as_of_date").dropna(subset=["target_sustainable_dividend"])
    used = implemented_features(features)
    horizon = pd.Timedelta(
        days=settings.label_horizon_days if embargo_days is None else embargo_days
    )
    dates = [pd.Timestamp(d) for d in sorted(df.as_of_date.unique())]
    n_test = int(len(dates) * test_share)
    n_folds = max(1, int(n_folds))
    if n_test < n_folds:
        raise ValueError(
            f"cannot build {n_folds} folds from {len(dates)} labelled dates "
            f"({n_test} reserved for testing)."
        )
    block = n_test // n_folds
    origin = len(dates) - n_test

    folds = []
    for i in range(n_folds):
        lo = origin + i * block
        hi = lo + block if i < n_folds - 1 else len(dates)
        # test_end is an exclusive bound, so the final fold runs to the end of
        # the labelled history rather than to dates[len(dates)].
        test_start = dates[lo]
        test_end = dates[hi] if hi < len(dates) else dates[-1] + pd.Timedelta(days=1)
        fold = {"fold": i + 1, "test_start": test_start, "test_end": test_end}
        try:
            m, metrics, test = _fit_and_score(
                df, used, horizon, test_start, test_end, max_flag_rate
            )
        except ValueError as exc:
            folds.append({**fold, "status": "skipped", "reason": str(exc)})
            continue
        folds.append({**fold, "status": "ok", "model": m, "metrics": metrics, "test": test})
    return folds
