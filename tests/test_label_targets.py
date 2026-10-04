from datetime import date

import numpy as np
import pandas as pd
import pytest

from scripts import label_targets
from scripts.evaluate_walk_forward import split_dates
from scripts.label_targets import OUTCOME_WINDOW_DAYS, label_value
from src.crispdm.model import FEATURES, implemented_features, walk_forward


def test_label_value_positive_when_event_in_window():
    assert label_value(has_in_window=True, last_ex_date=None, as_of_date="2024-01-01") == 1


def test_label_value_positive_ignores_missing_monitoring():
    assert label_value(has_in_window=True, last_ex_date=None, as_of_date="2024-01-01") == 1


def test_label_value_zero_when_monitored_past_window_end():
    from datetime import date, timedelta

    as_of_date = date(2024, 1, 1)
    window_end = as_of_date + timedelta(days=OUTCOME_WINDOW_DAYS)
    assert label_value(has_in_window=False, last_ex_date=window_end, as_of_date=as_of_date) == 0
    assert (
        label_value(
            has_in_window=False, last_ex_date=window_end + timedelta(days=1), as_of_date=as_of_date
        )
        == 0
    )


def test_label_value_none_when_monitoring_stops_inside_window():
    from datetime import date, timedelta

    as_of_date = date(2024, 1, 1)
    mid_window = as_of_date + timedelta(days=100)
    assert label_value(has_in_window=False, last_ex_date=mid_window, as_of_date=as_of_date) is None


def _daily_frame(n_days, seed=0, per_day=8):
    """A labelled frame long enough to survive a 365-day label embargo.

    The embargo needs roughly 365/0.7 ~= 522 distinct dates before anything is
    trainable, so a short fixture would fail for the wrong reason. Both classes
    are present because the solver rejects a single-class target.
    """
    rng = np.random.RandomState(seed)
    rows = []
    for i in range(n_days):
        as_of = pd.Timestamp("2023-01-01") + pd.Timedelta(days=i)
        score = rng.rand(per_day)
        d = {k: rng.rand(per_day) * (1 + score) for k in FEATURES}
        d["dividend_coverage"] = score + rng.rand(per_day) * 0.1
        d["as_of_date"] = as_of
        d["target_sustainable_dividend"] = (score > 0.5).astype(int)
        d["security_id"] = [f"S{i}_{j}" for j in range(per_day)]
        rows.append(pd.DataFrame(d))
    return pd.concat(rows, ignore_index=True)


def test_walk_forward_smoke_returns_imbalance_aware_metrics():
    df = _daily_frame(540)

    model, metrics, test = walk_forward(df, max_flag_rate=0.10)
    # The metrics a 93.6%-positive label set needs: the minority class has to
    # be reported explicitly, not averaged away.
    assert {
        "balanced_accuracy",
        "negative_recall",
        "negative_precision",
        "positive_recall",
        "positive_precision",
        "negative_support",
        "positive_support",
    } <= set(metrics)
    assert metrics["negative_support"] + metrics["positive_support"] == len(test)
    assert metrics["recall"] >= 0.30

    # The test set is the plain date cut, unaffected by the embargo.
    dates, cut = split_dates(df["as_of_date"])
    assert len(test) == len(df) - (8 * cut)
    assert metrics["n_train"] < 8 * cut, "the embargo must actually remove training rows"


def test_naive_baseline_is_the_floor_a_real_model_must_clear():
    import numpy as np

    from src.crispdm.model import naive_baseline

    # 936 positive / 64 negative: the shape of the real label population.
    y = np.array([1] * 936 + [0] * 64)
    baseline = naive_baseline(y)
    assert baseline["positive_rate"] == pytest.approx(0.936, abs=1e-3)
    # This is why an absolute recall gate could never fail.
    assert baseline["recall"] == 1.0
    assert baseline["precision"] == pytest.approx(0.936, abs=1e-3)
    # Balanced accuracy is 0.5 for the majority-class answer, so it is the
    # metric with room to discriminate.
    assert baseline["balanced_accuracy"] == pytest.approx(0.5)


def test_evaluate_gate_rejects_a_model_that_only_rides_the_majority():
    import numpy as np

    from src.crispdm.model import evaluate_gate, naive_baseline

    y = np.array([1] * 936 + [0] * 64)
    baseline = naive_baseline(y)
    # High recall and high PR-AUC, but no minority-class signal at all.
    majority_only = {
        "balanced_accuracy": 0.50,
        "negative_recall": 0.0,
        "pr_auc": 0.94,
    }
    gate = evaluate_gate(majority_only, baseline)
    assert gate["passed"] is False
    assert gate["checks"]["negative_recall"]["passed"] is False
    assert gate["checks"]["balanced_accuracy_lift"]["passed"] is False


def test_evaluate_gate_passes_a_model_with_real_minority_signal():
    import numpy as np

    from src.crispdm.model import evaluate_gate, naive_baseline

    y = np.array([1] * 936 + [0] * 64)
    baseline = naive_baseline(y)
    good = {"balanced_accuracy": 0.72, "negative_recall": 0.55, "pr_auc": 0.985}
    gate = evaluate_gate(good, baseline)
    assert gate["passed"] is True


def test_evaluate_gate_does_not_block_on_pr_auc_lift():
    """PR-AUC lift is a diagnostic, so a shortfall alone cannot fail a fold.

    The model still has to clear both blocking checks; this pins the specific
    behaviour that a weak PR-AUC lift, however measured, is not itself a veto.
    """
    import numpy as np

    from src.crispdm.model import evaluate_gate, naive_baseline

    # 10% negatives, so the PR-AUC comparison is still fair (headroom 0.10)
    # and the lift can be measured as genuinely short of the old margin.
    y = np.array([1] * 900 + [0] * 100)
    baseline = naive_baseline(y)
    strong_but_low_pr_auc = {
        "balanced_accuracy": 0.72,
        "negative_recall": 0.55,
        "pr_auc": 0.915,
    }
    gate = evaluate_gate(strong_but_low_pr_auc, baseline)

    assert gate["passed"] is True
    assert "pr_auc_lift" not in gate["checks"]
    assert gate["diagnostics"]["pr_auc_lift"] < 0.02
    assert gate["diagnostics"]["reliable"] is True


def test_evaluate_gate_flags_pr_auc_as_unreliable_when_prevalence_constrains_it():
    """Two distinct reasons to distrust the PR-AUC comparison, both reported."""
    import numpy as np

    from src.crispdm.model import evaluate_gate, naive_baseline

    model = {"balanced_accuracy": 0.72, "negative_recall": 0.96, "pr_auc": 0.999}

    # 1% negatives: the baseline already reaches 0.99, so the entire headroom
    # is under the reference margin and no model could satisfy the criterion.
    rare = naive_baseline(np.array([1] * 990 + [0] * 10))
    unattainable = evaluate_gate(model, rare, prevalence_guardrail=None)
    assert unattainable["passed"] is True
    assert unattainable["diagnostics"]["reliable"] is False
    assert unattainable["diagnostics"]["pr_auc_headroom"] < 0.02
    assert "unattainable" in unattainable["diagnostics"]["unreliable_reason"]

    # 4% negatives: headroom is still workable, so the empirical guardrail is
    # what marks the comparison unreliable.
    guarded = naive_baseline(np.array([1] * 960 + [0] * 40))
    still_usable = evaluate_gate(model, guarded, prevalence_guardrail=None)
    assert still_usable["diagnostics"]["reliable"] is True

    flagged = evaluate_gate(model, guarded, prevalence_guardrail=0.05)
    assert flagged["passed"] is True
    assert flagged["diagnostics"]["reliable"] is False
    assert "guardrail" in flagged["diagnostics"]["unreliable_reason"]


def _leakage_frame(n_days=900, seed=0, per_day=6):
    """A long labelled frame with a strong, learnable signal.

    900 daily dates leaves enough history for a 365-day horizon to purge while
    still yielding a trainable fold, which is what makes a leak observable: if
    the embargo were dropped, the rows whose labels peek into the test period
    would be back in the training set and the purging assertions below would
    fail rather than pass vacuously.
    """
    rng = np.random.RandomState(seed)
    rows = []
    for i in range(n_days):
        as_of = pd.Timestamp("2019-01-01") + pd.Timedelta(days=i)
        signal = rng.rand(per_day)
        d = {k: rng.rand(per_day) for k in FEATURES}
        d["dividend_coverage"] = signal
        d["dividend_yield"] = signal * 0.05
        d["as_of_date"] = as_of
        d["target_sustainable_dividend"] = (signal > 0.5).astype(int)
        d["security_id"] = [f"S{i}_{j}" for j in range(per_day)]
        rows.append(pd.DataFrame(d))
    return pd.concat(rows, ignore_index=True)


def test_walk_forward_embargo_purges_rows_whose_label_reaches_the_test_period():
    """The core leakage invariant: no training label may observe the test period.

    A row dated ``D`` is labelled from events in ``(D, D + horizon]``. If it
    stays trainable while ``D + horizon >= test_start``, the model is scored on
    events whose outcomes were in its training labels.
    """
    df = _leakage_frame()
    _, metrics, _ = walk_forward(df, max_flag_rate=0.10)
    embargo = metrics["embargo"]
    horizon = pd.Timedelta(days=embargo["horizon_days"])
    test_start = pd.Timestamp(embargo["test_start"])

    last_train = pd.Timestamp(embargo["last_train_date"])
    assert last_train + horizon < test_start, (
        "a training label window still reaches the test period"
    )
    assert embargo["rows_dropped_as_leaky"] > 0, "the embargo dropped nothing, so it is untested"
    assert embargo["retained_share"] < 1.0
    # Candidates are everything before the cut; the purge is the difference.
    assert (
        embargo["rows_before_embargo"] - embargo["rows_dropped_as_leaky"]
        == embargo["rows_retained"]
    )


def test_embargo_boundary_is_strict_at_the_label_window_edge():
    """A window closing exactly on ``test_start`` is still leaky.

    The label reads events in a half-open interval ending on ``D + horizon``, so
    a window that ends precisely when the test period opens has consumed a
    test-period observation. The boundary must be ``<``, not ``<=``.
    """
    from src.crispdm.model import _fit_and_score, implemented_features

    df = _leakage_frame(n_days=600)
    horizon = pd.Timedelta(days=365)
    used = implemented_features(None)
    test_start = pd.Timestamp("2020-03-01")

    _, metrics, _ = _fit_and_score(df, used, horizon, test_start, None, 0.0)

    # test_start - horizon closes exactly on the boundary and must be excluded,
    # so the last trainable date is one day earlier.
    assert pd.Timestamp(
        metrics["embargo"]["last_train_date"]
    ) == test_start - horizon - pd.Timedelta(days=1)
    assert pd.Timestamp(metrics["embargo"]["test_start"]) == test_start


def test_walk_forward_leaves_the_test_set_untouched():
    """Purging may only shrink training data; scoring rows stay intact."""
    df = _leakage_frame(n_days=800)
    labelled = df.dropna(subset=["target_sustainable_dividend"])
    cut = max(1, int(labelled.as_of_date.nunique() * 0.70))
    test_start = pd.Timestamp(sorted(labelled.as_of_date.unique())[cut])

    _, metrics, _ = walk_forward(df, max_flag_rate=0.10)

    assert metrics["n_test"] == int((labelled.as_of_date >= test_start).sum())
    assert metrics["n_train"] < metrics["embargo"]["rows_before_embargo"]


def test_walk_forward_fails_closed_when_a_feature_is_absent_from_training():
    """A declared feature with no training coverage cannot be imputed away.

    ``SimpleImputer`` drops all-missing columns and feeds the estimator a
    narrower matrix than requested, so a model can be scored against features it
    never actually saw. That is a silent contract violation, not a warning.
    """
    df = _leakage_frame(n_days=700)
    dropped = FEATURES[0]
    with pytest.raises(ValueError, match=dropped):
        walk_forward(df.drop(columns=[dropped]), max_flag_rate=0.10)


def test_walk_forward_fails_closed_on_a_single_class_training_target():
    df = _leakage_frame(n_days=700)
    df["target_sustainable_dividend"] = 1
    with pytest.raises(ValueError, match="single target class"):
        walk_forward(df, max_flag_rate=0.10)


def test_walk_forward_records_feature_coverage_for_audit():
    df = _leakage_frame(n_days=700)
    _, metrics, _ = walk_forward(df, max_flag_rate=0.10)
    coverage = metrics["embargo"]["train_feature_coverage"]
    assert set(coverage) == set(implemented_features(None))
    assert all(0.0 <= v <= 1.0 for v in coverage.values())


def test_walk_forward_folds_are_ordered_disjoint_and_cover_the_tail():
    """Fold blocks must tile the reserved tail in order, without overlap."""
    from src.crispdm.model import walk_forward_folds

    df = _leakage_frame(n_days=900)
    folds = walk_forward_folds(df, n_folds=3, max_flag_rate=0.10)
    scored = [f for f in folds if f["status"] == "ok"]
    assert len(scored) == 3

    for earlier, later in zip(scored, scored[1:]):
        assert earlier["test_end"] == later["test_start"], "folds overlap or leave a gap"
    starts = [f["test_start"] for f in scored]
    assert starts == sorted(starts), "folds are not chronological"

    # The final fold must run to the end of the labelled history. test_end is an
    # exclusive bound, so it is one day past the last available date.
    last_date = pd.Timestamp(df.as_of_date.max())
    assert scored[-1]["test_end"] == last_date + pd.Timedelta(days=1)


def test_walk_forward_folds_embargo_each_block_against_its_own_test_start():
    """Each fold purges against its own start, not a shared global cut."""
    from src.crispdm.model import walk_forward_folds

    df = _leakage_frame(n_days=900)
    folds = walk_forward_folds(df, n_folds=3, max_flag_rate=0.10)

    for fold in folds:
        if fold["status"] != "ok":
            continue
        embargo = fold["metrics"]["embargo"]
        horizon = pd.Timedelta(days=embargo["horizon_days"])
        assert embargo["test_start"] == fold["test_start"].date().isoformat()
        assert pd.Timestamp(embargo["last_train_date"]) + horizon < fold["test_start"]


def test_walk_forward_folds_only_expand_the_training_window():
    """Each fold trains on a superset of the previous fold's dates."""
    from src.crispdm.model import walk_forward_folds

    df = _leakage_frame(n_days=900)
    folds = [
        f for f in walk_forward_folds(df, n_folds=3, max_flag_rate=0.10) if f["status"] == "ok"
    ]

    for earlier, later in zip(folds, folds[1:]):
        assert (
            earlier["metrics"]["embargo"]["first_train_date"]
            <= later["metrics"]["embargo"]["first_train_date"]
        ), "training window must only expand"
        assert earlier["metrics"]["n_train"] < later["metrics"]["n_train"]


def test_walk_forward_folds_report_skipped_folds_with_a_reason():
    """A block that cannot be scored is reported, never silently dropped."""
    from src.crispdm.model import walk_forward_folds

    df = _leakage_frame(n_days=900)
    # Collapse the target to one class so the solver cannot fit any fold.
    df["target_sustainable_dividend"] = 1

    folds = walk_forward_folds(df, n_folds=2, max_flag_rate=0.10)

    assert folds, "no folds were produced at all"
    assert all(f["status"] == "skipped" for f in folds)
    for fold in folds:
        assert fold["reason"], "a skipped fold must say why"
        assert "single target class" in fold["reason"]


class _Result:
    """Stand-in for the psycopg2 result of a single statement."""

    def __init__(self, rows, rowcount=0):
        self._rows = rows
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows


class _FakeConnection:
    """Records statements and replays scripted results.

    ``label_targets`` runs one statement for a rebuild clear and one for the
    labelling RETURNING clause, so the fake serves them in order and keeps the
    SQL text to assert on what was actually sent to the database.
    """

    def __init__(self, results):
        self._results = list(results)
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return self._results.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, connection):
        self._connection = connection

    def begin(self):
        return self._connection


def test_label_targets_does_not_count_undecided_rows_as_labeled():
    """A NULL outcome means the evidence was insufficient, not that it was 0.

    Rows past the eligible window are returned with a NULL label. Counting them
    as labeled overstates the labeled population and, because they are all
    recent, silently overstates how much recent history the model has.
    """
    rows = [
        ("A", date(2024, 1, 2), 1),
        ("B", date(2024, 1, 3), 0),
        ("C", date(2024, 1, 4), 1),
        ("D", date(2024, 1, 5), None),
    ]
    connection = _FakeConnection([_Result(rows)])
    original = label_targets.engine
    label_targets.engine = _FakeEngine(connection)
    try:
        total, positive, negative = label_targets.label_targets(date(2025, 6, 1))
    finally:
        label_targets.engine = original

    assert (total, positive, negative) == (3, 2, 1)
    assert total == positive + negative
    assert "IS NULL" in connection.statements[0], "immutable labels must be guarded"


def test_label_targets_rebuild_clears_previous_labels_before_relabeling():
    """A wider-cutoff rebuild must not carry stale labels into the new run."""
    rows = [("A", date(2024, 1, 2), 1), ("B", date(2024, 1, 3), 0)]
    connection = _FakeConnection([_Result([], rowcount=17), _Result(rows)])
    original = label_targets.engine
    label_targets.engine = _FakeEngine(connection)
    try:
        total, positive, negative = label_targets.label_targets(date(2025, 6, 1), rebuild=True)
    finally:
        label_targets.engine = original

    clear_statement, label_statement = connection.statements
    assert "UPDATE model.features SET target_sustainable_dividend = NULL" in clear_statement
    assert "target_sustainable_dividend IS NOT NULL" in clear_statement
    # Without the clear the overwrite guard would be a no-op and pre-existing
    # labels outside the new window would survive as if they were current.
    assert "AND f.target_sustainable_dividend IS NULL" not in label_statement
    assert (total, positive, negative) == (2, 1, 1)


def test_evaluate_gate_rejects_a_model_that_flags_too_much():
    """Recall is not a deployment criterion on its own.

    The model that caught 95% of unsustainable dividends by flagging 48% of the
    universe passed the old gate. It is not a screen, it is a lottery: acting on
    it discards half the investable set to avoid a 2.4% event. The flag rate is
    the check that catches that failure mode.
    """
    import numpy as np

    from src.crispdm.model import evaluate_gate, naive_baseline

    y = np.array([1] * 976 + [0] * 24)
    baseline = naive_baseline(y)
    # Excellent recall and balanced accuracy, but flags 48% of the universe.
    flags_half = {
        "balanced_accuracy": 0.74,
        "negative_recall": 0.95,
        "pr_auc": 0.99,
        "predicted_negative": 480,
        "n_test": 1000,
    }
    gate = evaluate_gate(flags_half, baseline)
    assert gate["passed"] is False
    assert gate["checks"]["flag_rate"]["passed"] is False
    assert gate["checks"]["flag_rate"]["actual"] == pytest.approx(0.48)
    # The other two checks still pass -- it is the flag rate that vetoes.
    assert gate["checks"]["negative_recall"]["passed"] is True
    assert gate["checks"]["balanced_accuracy_lift"]["passed"] is True


def test_evaluate_gate_passes_a_model_within_flag_budget():
    """A model that flags 12% to catch 60% of negatives is a usable screen."""
    import numpy as np

    from src.crispdm.model import evaluate_gate, naive_baseline

    y = np.array([1] * 976 + [0] * 24)
    baseline = naive_baseline(y)
    disciplined = {
        "balanced_accuracy": 0.72,
        "negative_recall": 0.60,
        "pr_auc": 0.99,
        "predicted_negative": 120,
        "n_test": 1000,
    }
    gate = evaluate_gate(disciplined, baseline)
    assert gate["passed"] is True
    assert gate["checks"]["flag_rate"]["passed"] is True


def test_label_excludes_securities_that_had_already_stopped():
    """A security that stopped paying before as_of_date must not be labelled 0.

    The old label taught the model that "not paying now" means "unsustainable",
    which is trivial: 54.3% of label-0 rows were already stopped at the
    observation date. Those rows carry no signal about sustainability -- they
    are just dead securities -- and they swamped the real "was paying, then
    stopped" cases the model should be learning from.
    """
    import inspect

    source = inspect.getsource(label_targets)
    assert "d.ex_dividend_date > f.as_of_date" in source
    assert "d.ex_dividend_date <= f.as_of_date" in source
    assert "d.amount > 0" in source
    # The lookback window matches the outcome window, so a security is only
    # labelled if it was paying within one horizon of the observation date.
    assert source.count("OUTCOME_WINDOW_DAYS") >= 3


def test_label_negative_rate_is_honest():
    """The negative rate should reflect genuine cuts, not payment timing.

    The old label produced 8.1% negatives, of which 54.3% were already stopped
    and 100% paid again later. The new label should produce a much lower
    negative rate -- the honest rate at which active payers actually stop.
    """
    from src.crispdm.db import read_df

    row = read_df("""
        SELECT count(*) AS labeled,
               count(*) FILTER (WHERE target_sustainable_dividend = 0) AS neg
        FROM model.features
        WHERE target_sustainable_dividend IS NOT NULL
    """).iloc[0]
    rate = row.neg / row.labeled
    # The old rate was 8.1%. The new rate should be far lower -- the already
    # stopped securities are gone. If it is still above ~3%, the active-payer
    # restriction is not doing its job.
    assert rate < 0.03, (
        f"negative rate {rate:.2%} is too high -- already-stopped securities are leaking in"
    )
