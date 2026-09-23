from scripts.dry_run_walk_forward import synthetic_labeled_sample
from scripts.evaluate_walk_forward import make_checkpoint, split_dates
from src.crispdm.model import walk_forward


def test_dry_run_sample_passes_gate_deterministically():
    df = synthetic_labeled_sample(seed=7)
    assert len(df) == 72
    assert df["target_sustainable_dividend"].nunique() == 2

    _, metrics, _ = walk_forward(df, min_recall=0.30)
    dates, cut = split_dates(df["as_of_date"])
    checkpoint = make_checkpoint("dry-run", 0.30, metrics, dates, cut, len(df))
    assert metrics["recall"] >= 0.30
    assert checkpoint["gate_passed"] is True


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
    assert df["as_of_date"].nunique() == 6
