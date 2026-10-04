import json

import pandas as pd
import pytest

from scripts.evaluate_walk_forward import (
    audit_completeness,
    make_checkpoint,
    split_dates,
)
from src.crispdm import sec_client
from src.crispdm.model import FEATURES, PLACEHOLDER_FEATURES, _fit_and_score


def _checkpoint(**overrides):
    """A checkpoint as ``make_checkpoint`` writes it, under the current contract."""
    dates, cut = split_dates(["2024-01-01", "2024-02-01", "2025-01-01", "2025-03-01", "2026-01-01"])
    checkpoint = make_checkpoint(
        "run-contract",
        0.30,
        _metrics(),
        dates,
        cut,
        n_rows=20,
        baseline=_baseline(),
        gate=_gate(),
        completeness=_completeness(),
    )
    checkpoint.update(overrides)
    return checkpoint


def _fit_frame(test_labels):
    """A feature frame whose training block is sound and whose test block is not.

    The training block has to be genuinely scorable, otherwise the test-block
    checks would never be reached: the embargo, the coverage floor and the
    two-class requirement all run first and each raises on its own.
    """
    import numpy as np
    import pandas as pd

    rows = []
    for day in range(60):
        as_of = pd.Timestamp("2020-01-01") + pd.Timedelta(days=day)
        label = 1 if day % 3 else 0
        rows.append(
            {
                "security_id": f"s{day}",
                "as_of_date": as_of.date(),
                "target_sustainable_dividend": label,
                **{f: float(label) + 0.01 for f in FEATURES},
            }
        )
    for day, label in enumerate(test_labels):
        rows.append(
            {
                "security_id": f"t{day}",
                "as_of_date": (pd.Timestamp("2022-01-01") + pd.Timedelta(days=day)).date(),
                "target_sustainable_dividend": label,
                **{f: float(label) + 0.01 for f in FEATURES},
            }
        )
    del np
    return pd.DataFrame(rows)


def _split():
    """(test_start, test_end) matching the test block built by ``_fit_frame``."""
    import pandas as pd

    return pd.Timestamp("2021-06-01"), pd.Timestamp("2023-01-01")


def _single_class_test_frame():
    """A test block in which every label is positive.

    The minority class is the scarce one in this dataset, so a block can lose it
    while still holding plenty of rows. Balanced accuracy and negative recall
    are both undefined there, and sklearn's zero_division default would report
    0.0 and let the fold look measured rather than impossible.
    """
    return _fit_frame([1, 1, 1, 1, 1, 1])


def _empty_test_block_frame():
    """No rows at all in the test period: a fold that cannot be evaluated."""
    return _fit_frame([])


def _metrics(**overrides):
    """Metrics for a model that clears the naive baseline on every criterion."""
    metrics = {
        "precision": 0.6,
        "recall": 0.35,
        "f1": 0.45,
        "pr_auc": 0.98,
        "roc_auc": 0.7,
        "accuracy": 0.7,
        "balanced_accuracy": 0.65,
        "positive_precision": 0.7,
        "positive_recall": 0.6,
        "negative_precision": 0.5,
        "negative_recall": 0.55,
        "negative_support": 40,
        "positive_support": 960,
        "threshold": 0.4,
        "n_train": 800,
        "n_test": 1000,
    }
    metrics.update(overrides)
    return metrics


def _baseline():
    return {
        "strategy": "always_predict_sustainable",
        "positive_rate": 0.936,
        "accuracy": 0.936,
        "balanced_accuracy": 0.5,
        "precision": 0.936,
        "recall": 1.0,
        "f1": 0.967,
        "pr_auc": 0.936,
    }


def _completeness(ok=True):
    return {
        "declared_features": ["dividend_yield"],
        "implemented_features": ["dividend_yield"],
        "placeholder_features": [] if ok else sorted(PLACEHOLDER_FEATURES),
        "zero_coverage_non_placeholder": [],
        "sparse_features": [],
        "min_required_coverage": 0.01,
        "coverage": {"dividend_yield": 1.0},
        "completeness_ok": ok,
    }


def _gate(passed=True):
    return {
        "passed": passed,
        "checks": {
            "balanced_accuracy_lift": {"required": 0.10, "actual": 0.15, "passed": passed},
            "negative_recall": {"required": 0.10, "actual": 0.55, "passed": passed},
            "pr_auc_lift": {"required": 0.02, "actual": 0.044, "passed": passed},
        },
    }


def test_make_checkpoint_records_iso_dates_and_gate():
    dates, cut = split_dates(["2024-01-01", "2024-02-01", "2025-01-01", "2025-03-01", "2026-01-01"])
    checkpoint = make_checkpoint(
        "run-1",
        0.30,
        _metrics(),
        dates,
        cut,
        n_rows=20,
        baseline=_baseline(),
        gate=_gate(),
        completeness=_completeness(),
    )
    assert checkpoint["training_start"] == "2024-01-01"
    assert checkpoint["test_start"] == "2025-03-01"
    assert checkpoint["gate_passed"] is True
    assert checkpoint["readiness"] == "go"
    assert checkpoint["metrics"]["recall"] == 0.35


def test_make_checkpoint_names_the_date_counts_as_dates():
    # 362 was previously written as n_train while being a count of distinct
    # as_of dates, which read as a row count.
    dates, cut = split_dates(["2024-01-01", "2024-02-01", "2025-01-01", "2025-03-01", "2026-01-01"])
    checkpoint = make_checkpoint(
        "run-1",
        0.30,
        _metrics(),
        dates,
        cut,
        n_rows=20,
        baseline=_baseline(),
        gate=_gate(),
        completeness=_completeness(),
    )
    assert checkpoint["n_train_dates"] == cut
    assert checkpoint["n_test_dates"] == len(dates) - cut
    assert checkpoint["n_train_rows"] == 800
    assert checkpoint["n_test_rows"] == 1000
    assert "n_train" not in checkpoint


def test_make_checkpoint_fails_the_gate_when_the_baseline_is_not_beaten():
    dates, cut = split_dates(["2024-01-01", "2024-02-01", "2025-01-01", "2025-03-01", "2026-01-01"])
    # Balanced accuracy at the baseline's 0.5 and zero minority recall is what
    # a model riding the majority class looks like.
    metrics = _metrics(balanced_accuracy=0.50, negative_recall=0.0, pr_auc=0.936)
    checkpoint = make_checkpoint(
        "run-1",
        0.30,
        metrics,
        dates,
        cut,
        n_rows=20,
        baseline=_baseline(),
        gate=_gate(passed=False),
        completeness=_completeness(),
    )
    assert checkpoint["gate_passed"] is False
    assert checkpoint["readiness"] == "no_go"


def test_make_checkpoint_is_no_go_when_features_are_placeholders_even_if_metrics_pass():
    # The whole point: a model that beats the baseline on placeholder inputs
    # is diagnostic, not production evidence.
    dates, cut = split_dates(["2024-01-01", "2024-02-01", "2025-01-01", "2025-03-01", "2026-01-01"])
    checkpoint = make_checkpoint(
        "run-1",
        0.30,
        _metrics(),
        dates,
        cut,
        n_rows=20,
        baseline=_baseline(),
        gate=_gate(passed=True),
        completeness=_completeness(ok=False),
    )
    assert checkpoint["gate"]["passed"] is True
    assert checkpoint["gate_passed"] is False
    assert checkpoint["readiness"] == "no_go"


def test_audit_completeness_flags_a_reintroduced_placeholder():
    import pandas as pd

    # A retired name re-added to the declared list, all values NULL. The gate
    # must fail closed rather than let the imputer carry a feature that has no
    # source.
    #
    # The name is deliberately one that is *still* retired. This test used to
    # use debt_to_ebitda, which was restored on 2026-09-29 once V0011 supplied
    # the D&A and interest-expense inputs it was retired for lacking. If this
    # name is ever restored in turn, that is a real signal to re-point the test
    # rather than a name to keep hardcoded.
    frame = pd.DataFrame(
        [
            {
                f: (0.05 if f == "dividend_yield" else None)
                for f in FEATURES + ["liquidation_discount"]
            }
        ]
    )
    audit = audit_completeness(frame)
    assert "liquidation_discount" in audit["placeholder_features"]
    assert audit["completeness_ok"] is False


def test_restored_leverage_features_are_not_treated_as_placeholders():
    """debt_to_ebitda and interest_coverage left RETIRED_FEATURES, so the
    completeness gate must stop flagging them.

    They are not in the declared ML ``FEATURES`` list -- they are populated
    columns the analyst reads and the composite does not consume -- so this only
    asserts that the retirement bookkeeping moved, which is what re-adding them
    to the declared list would now have to fight.
    """
    from src.crispdm.features import RETIRED_FEATURES

    assert "debt_to_ebitda" not in RETIRED_FEATURES
    assert "interest_coverage" not in RETIRED_FEATURES
    # The three that remain retired are still retired for reasons the data
    # supports, not for reasons that were later disproved.
    assert set(RETIRED_FEATURES) == {
        "liquidation_discount",
        "legal_rights_score",
        "data_quality_score",
    }
    # V0011/V0012 went further than un-retiring them and added both to the
    # declared ML FEATURES list, at coverage above the 20% completeness floor.
    # The docstring above predates that. What matters here is the invariant:
    # nothing may be in both lists, since a name in both would be retired and
    # declared at once, and the completeness gate would read it as a placeholder
    # while training consumed it.
    assert not set(RETIRED_FEATURES) & set(FEATURES)
    assert {"debt_to_ebitda", "interest_coverage"} <= set(FEATURES)


def test_audit_completeness_passes_on_the_current_feature_set():
    import numpy as np
    import pandas as pd

    # Every declared feature present and populated: completeness is a real
    # gate, not one that can only ever fail.
    frame = pd.DataFrame([{f: 0.05 for f in FEATURES}])
    frame["target_sustainable_dividend"] = np.nan
    audit = audit_completeness(frame)
    assert audit["placeholder_features"] == []
    assert audit["completeness_ok"] is True
    assert all(c == pytest.approx(1.0) for c in audit["coverage"].values())


def test_sec_session_rejects_placeholder_user_agent(monkeypatch):
    monkeypatch.setattr(sec_client.settings, "sec_user_agent", "Your Name your.email@example.com")
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        sec_client._SecSession().get("https://www.sec.gov/files/company_tickers.json")


def test_sec_session_rejects_blank_user_agent(monkeypatch):
    monkeypatch.setattr(sec_client.settings, "sec_user_agent", "")
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        sec_client._SecSession().get("https://www.sec.gov/files/company_tickers.json")


def test_failed_completeness_quarantines_a_stale_passing_checkpoint(tmp_path):
    import json

    from scripts.evaluate_walk_forward import invalidate_stale_checkpoint

    # A checkpoint from the old recall-only contract still says gate_passed.
    stale = tmp_path / "walk_forward_checkpoint.json"
    stale.write_text(json.dumps({"run_id": "old", "gate_passed": True}))

    moved = invalidate_stale_checkpoint(stale, {}, "completeness failed")

    assert moved.exists()
    assert json.loads(moved.read_text())["gate_passed"] is True
    # The path anything else reads must no longer resolve to the stale pass.
    assert not stale.exists()


def test_quarantine_is_a_noop_when_there_is_no_checkpoint(tmp_path):
    from scripts.evaluate_walk_forward import invalidate_stale_checkpoint

    assert invalidate_stale_checkpoint(tmp_path / "absent.json", {}, "x") is None


def _labelled_frame(n_days, seed=0, per_day=8):
    import numpy as np
    import pandas as pd

    rng = np.random.RandomState(seed)
    rows = []
    for i in range(n_days):
        score = rng.rand(per_day)
        row = {f: rng.rand(per_day) * (1 + score) for f in FEATURES}
        row["dividend_coverage"] = score + rng.rand(per_day) * 0.1
        row["as_of_date"] = pd.Timestamp("2019-01-01") + pd.Timedelta(days=i)
        row["security_id"] = [f"S{i}_{j}" for j in range(per_day)]
        row["target_sustainable_dividend"] = (score > 0.5).astype(int)
        rows.append(pd.DataFrame(row))
    return pd.concat(rows, ignore_index=True)


def test_rolling_folds_require_every_fold_to_pass():
    from scripts.evaluate_walk_forward import evaluate_folds

    # Long enough that the first fold survives the 365-day label embargo.
    df = _labelled_frame(1200)

    rolling = evaluate_folds(df, n_folds=4, max_flag_rate=0.10)

    assert rolling["n_folds_requested"] == 4
    assert rolling["n_folds_evaluated"] == 4, [f.get("reason") for f in rolling["folds"]]
    # all_folds_passed is the conjunction, never a majority or an average.
    assert rolling["all_folds_passed"] == (
        rolling["n_folds_passed"] == rolling["n_folds_evaluated"]
    )


def test_rolling_folds_gate_each_fold_against_its_own_baseline():
    from scripts.evaluate_walk_forward import evaluate_folds

    df = _labelled_frame(1200)

    rolling = evaluate_folds(df, n_folds=3, max_flag_rate=0.10)

    for fold in rolling["folds"]:
        if fold["status"] != "ok":
            continue
        assert set(fold["checks"]) == {
            "balanced_accuracy_lift",
            "negative_recall",
            "flag_rate",
        }
        assert fold["embargo"]["horizon_days"] == 365
        assert fold["embargo"]["last_train_date"] < fold["test_start"]
        assert "train_negative_rate" in fold["embargo"]


def test_rolling_folds_report_skipped_folds_with_a_reason():
    from scripts.evaluate_walk_forward import evaluate_folds

    # Too short for 4 folds: fold 1's embargoed training set is empty.
    df = _labelled_frame(600)

    rolling = evaluate_folds(df, n_folds=4, max_flag_rate=0.10)

    assert rolling["n_folds_evaluated"] < 4
    assert rolling["all_folds_passed"] is False
    for fold in rolling["folds"]:
        if fold["status"] == "skipped":
            assert fold["reason"]


def test_prevalence_guardrail_is_derived_from_the_folds():
    """The cutoff must be measured from headroom, not asserted."""
    from scripts.evaluate_walk_forward import derive_prevalence_guardrail

    def fold(fold_id, minority, model_pr):
        return {
            "fold": fold_id,
            "metrics": {"pr_auc": model_pr},
            "baseline": {
                "pr_auc": 1 - minority / 1000,
                "positive_rate": 1 - minority / 1000,
            },
        }

    derived = derive_prevalence_guardrail(
        [fold(1, 100, 0.70), fold(2, 40, 0.90), fold(3, 5, 0.999)]
    )

    # Headroom is 1 - baseline pr_auc, so only the 0.5% fold is unusable.
    assert derived["cutoff"] == pytest.approx(0.005)
    assert derived["lowest_usable_minority_rate"] == pytest.approx(0.04)
    assert derived["highest_unusable_minority_rate"] == pytest.approx(0.005)
    assert derived["n_folds_used"] == 3
    assert "derived from the evaluated folds" in derived["method"]
    # The cutoff is only as trustworthy as its evidence.
    assert len(derived["evidence"]) == 3

    # With no unusable fold the cutoff is 0.0, so nothing is pre-emptively
    # flagged on prevalence alone.
    clean = derive_prevalence_guardrail([fold(1, 100, 0.70), fold(2, 40, 0.90)])
    assert clean["cutoff"] == 0.0
    assert clean["highest_unusable_minority_rate"] is None


def test_rolling_folds_record_pr_auc_as_a_diagnostic_with_prevalence():
    from scripts.evaluate_walk_forward import evaluate_folds

    df = _labelled_frame(1200)
    rolling = evaluate_folds(df, n_folds=3, max_flag_rate=0.10)

    assert rolling["acceptance_policy"]["blocking_checks"] == [
        "balanced_accuracy_lift",
        "negative_recall",
    ]
    assert rolling["acceptance_policy"]["requires_all_folds"] is True
    assert rolling["acceptance_policy"]["skipped_folds_fail_closed"] is True
    assert "prevalence_guardrail" in rolling
    assert rolling["prevalence_guardrail"]["n_folds_used"] == rolling["n_folds_evaluated"]

    for fold in rolling["folds"]:
        if fold["status"] != "ok":
            continue
        diagnostics = fold["diagnostics"]
        assert diagnostics["minority_rate"] > 0
        assert diagnostics["pr_auc_headroom"] > 0
        assert isinstance(diagnostics["reliable"], bool)
        if not diagnostics["reliable"]:
            assert diagnostics["unreliable_reason"]


# --- Contract versioning -----------------------------------------------------
#
# The acceptance policy changed twice in one session: PR-AUC lift was added as a
# criterion, then removed as a criterion (not relaxed). Nothing recorded which
# policy produced a checkpoint, and the only automatic retirement path was a
# feature-completeness failure, so a passing artifact from a superseded policy
# stayed readable at the canonical path.


def test_checkpoint_records_the_contract_it_was_judged_under():
    from scripts.evaluate_walk_forward import (
        ACCEPTANCE_POLICY_VERSION,
        current_contract,
    )

    checkpoint = _checkpoint()

    assert checkpoint["contract"]["acceptance_policy_version"] == ACCEPTANCE_POLICY_VERSION
    # The three long-standing top-level version fields are mirrored inside the
    # contract block, so the two cannot drift apart silently.
    for field, wanted in current_contract().items():
        assert checkpoint["contract"][field] == wanted
    for field in ("model_version", "feature_version", "data_version"):
        assert checkpoint[field] == checkpoint["contract"][field]
    assert checkpoint["contract"]["blocking_checks"] == [
        "balanced_accuracy_lift",
        "negative_recall",
    ]
    assert checkpoint["contract"]["diagnostics"] == ["pr_auc_lift"]


def test_a_checkpoint_from_another_policy_is_drift_not_a_match():
    from scripts.evaluate_walk_forward import contract_drift, current_contract

    superseded = _checkpoint()
    superseded["contract"]["acceptance_policy_version"] = "pr_auc_lift_v1"

    drift = contract_drift(superseded)

    assert set(drift) == {"acceptance_policy_version"}
    assert drift["acceptance_policy_version"][1] == current_contract()["acceptance_policy_version"]
    # A checkpoint judged under the same contract is not drift.
    assert contract_drift(_checkpoint()) == {}


def test_a_checkpoint_with_no_recorded_policy_counts_as_drift():
    from scripts.evaluate_walk_forward import contract_drift

    # An older file with only the top-level version strings, and one with no
    # version information at all, both cannot be shown to have been judged under
    # the current policy.
    legacy = {
        "run_id": "x",
        "gate_passed": True,
        "model_version": "logistic_regression_walk_forward_v2",
    }

    assert "acceptance_policy_version" in contract_drift(legacy)
    assert contract_drift({"gate_passed": True})


def test_changing_the_policy_retires_the_previous_verdict(tmp_path):
    from scripts.evaluate_walk_forward import invalidate_superseded_contract

    path = tmp_path / "walk_forward_checkpoint.json"
    path.write_text(json.dumps(_checkpoint()))

    assert invalidate_superseded_contract(path) is None, "current contract is left alone"

    superseded = _checkpoint()
    superseded["contract"]["feature_version"] = "features_v2"
    path.write_text(json.dumps(superseded))
    moved = invalidate_superseded_contract(path)

    assert moved is not None and moved.exists()
    assert not path.exists(), "a verdict under another feature definition must leave the path"
    # The retired file is preserved, not deleted, so it can still be reviewed.
    assert json.loads(moved.read_text())["gate_passed"] is True


def test_unreadable_checkpoint_does_not_crash_the_run(tmp_path):
    from scripts.evaluate_walk_forward import invalidate_superseded_contract, read_checkpoint

    corrupt = tmp_path / "walk_forward_checkpoint.json"
    corrupt.write_text("{not json")

    assert read_checkpoint(corrupt) is None
    assert invalidate_superseded_contract(corrupt) is None


# --- Declared feature contract and test-block validity -----------------------


def test_a_model_declared_for_a_subset_refuses_a_different_frame():
    import pandas as pd

    from src.crispdm.model import make_model

    frame = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    y = pd.Series([0, 1])

    make_model(["a", "b"]).fit(frame, y)  # the declared set is accepted

    with pytest.raises(ValueError, match="absent from the frame"):
        make_model(["a", "c"]).fit(frame, y)


def test_a_test_block_with_one_class_fails_closed():
    frame = _single_class_test_frame()

    with pytest.raises(ValueError, match="single target class"):
        _fit_and_score(frame, FEATURES, pd.Timedelta(days=365), *_split(), 0.30)


def test_an_empty_test_block_fails_closed():
    frame = _empty_test_block_frame()

    with pytest.raises(ValueError, match="contains no labelled rows"):
        _fit_and_score(frame, FEATURES, pd.Timedelta(days=365), *_split(), 0.30)
