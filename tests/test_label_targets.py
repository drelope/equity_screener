import numpy as np
import pandas as pd

from scripts.evaluate_walk_forward import make_checkpoint, split_dates
from scripts.label_targets import OUTCOME_WINDOW_DAYS, label_value
from src.crispdm.model import FEATURES, walk_forward


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


def test_walk_forward_smoke_returns_metrics_and_passes_gate():
    rng = np.random.RandomState(0)
    rows = []
    for i in range(6):
        as_of = pd.Timestamp("2024-01-01") + pd.DateOffset(months=i)
        n = 8
        score = rng.rand(n)
        label = (score > 0.5).astype(int)
        d = {k: rng.rand(n) * (1 + score) for k in FEATURES}
        d["dividend_coverage"] = score + rng.rand(n) * 0.1
        d["as_of_date"] = as_of
        d["target_sustainable_dividend"] = label
        d["security_id"] = [f"S{len(rows) + j}" for j in range(n)]
        rows.append(pd.DataFrame(d))
    df = pd.concat(rows, ignore_index=True)

    model, metrics, test = walk_forward(df, min_recall=0.30)
    assert set(metrics) == {
        "precision",
        "recall",
        "f1",
        "pr_auc",
        "roc_auc",
        "accuracy",
        "threshold",
    }
    assert metrics["recall"] >= 0.30

    dates, cut = split_dates(df["as_of_date"])
    checkpoint = make_checkpoint("test-run", 0.30, metrics, dates, cut, len(df))
    assert checkpoint["gate_passed"] is True
    assert checkpoint["n_train"] == cut
    assert len(test) == len(df) - (8 * cut)
