import pytest

from scripts.dry_run_walk_forward import synthetic_labeled_sample
from src.crispdm.model import naive_baseline, walk_forward


def test_dry_run_sample_reports_imbalance_aware_metrics():
    df = synthetic_labeled_sample(seed=7)
    assert df["target_sustainable_dividend"].nunique() == 2

    _, metrics, test = walk_forward(df, max_flag_rate=0.10)
    baseline = naive_baseline(test.target_sustainable_dividend.astype(int))
    assert metrics["recall"] >= 0.30
    # The dry run exists to exercise the plumbing, so assert the imbalance
    # metrics and the baseline are both produced and are self-consistent.
    assert 0.0 <= metrics["balanced_accuracy"] <= 1.0
    assert 0.0 <= metrics["negative_recall"] <= 1.0
    assert baseline["balanced_accuracy"] == pytest.approx(0.5)
    # The label embargo must be exercised, not bypassed.
    assert metrics["embargo"]["rows_dropped_as_leaky"] > 0
    assert metrics["n_train"] < metrics["embargo"]["rows_before_embargo"]


def test_dry_run_sample_is_synthetic_and_self_contained():
    df = synthetic_labeled_sample(seed=11)
    assert {c for c in df.columns} >= {
        "security_id",
        "as_of_date",
        "dividend_coverage",
        "dividend_yield",
        "target_sustainable_dividend",
    }
    assert df["security_id"].str.startswith("SYN-").all()
    # 540 daily snapshots: enough for the 365-day label embargo to leave a
    # trainable set once the 70/30 cut is applied.
    assert df["as_of_date"].nunique() == 540
