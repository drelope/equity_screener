import pytest

from scripts.evaluate_walk_forward import make_checkpoint, split_dates
from src.crispdm import sec_client


def _metrics(recall=0.35):
    return {
        "precision": 0.6,
        "recall": recall,
        "f1": 0.45,
        "pr_auc": 0.5,
        "roc_auc": 0.7,
        "accuracy": 0.7,
        "threshold": 0.4,
    }


def test_make_checkpoint_records_iso_dates_and_gate():
    dates, cut = split_dates(["2024-01-01", "2024-02-01", "2025-01-01", "2025-03-01", "2026-01-01"])
    checkpoint = make_checkpoint("run-1", 0.30, _metrics(recall=0.35), dates, cut, n_rows=20)
    assert checkpoint["training_start"] == "2024-01-01"
    assert checkpoint["test_start"] == "2025-03-01"
    assert checkpoint["gate_passed"] is True
    assert checkpoint["n_train"] == cut
    assert checkpoint["metrics"]["recall"] == 0.35


def test_make_checkpoint_fails_gate_below_min_recall():
    dates, cut = split_dates(["2024-01-01", "2024-02-01", "2025-01-01", "2025-03-01", "2026-01-01"])
    checkpoint = make_checkpoint("run-1", 0.30, _metrics(recall=0.20), dates, cut, n_rows=20)
    assert checkpoint["gate_passed"] is False


def test_sec_session_rejects_placeholder_user_agent(monkeypatch):
    monkeypatch.setattr(sec_client.settings, "sec_user_agent", "Your Name your.email@example.com")
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        sec_client._SecSession().get("https://www.sec.gov/files/company_tickers.json")


def test_sec_session_rejects_blank_user_agent(monkeypatch):
    monkeypatch.setattr(sec_client.settings, "sec_user_agent", "")
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        sec_client._SecSession().get("https://www.sec.gov/files/company_tickers.json")
