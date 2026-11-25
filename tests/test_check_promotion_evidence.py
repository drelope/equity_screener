import json

from scripts.check_promotion_evidence import (
    check_backtest_metrics,
    check_checkpoint,
    check_manifest,
)


def test_check_checkpoint_reports_missing_promotion_grade_fields(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "r1",
                "contract": {
                    "acceptance_policy_version": "v1",
                    "model_version": "m",
                    "feature_version": "f",
                    "data_version": "d",
                },
                "gate": {"passed": False, "checks": {}},
                "readiness": "no_go",
            }
        ),
        encoding="utf-8",
    )
    errs = check_checkpoint(path)
    assert "promotion-grade field absent (expected draft gap): holdout" in errs
    assert "promotion-grade field absent (expected draft gap): cost_model" in errs
    assert "promotion-grade field absent (expected draft gap): benchmark" in errs


def test_check_backtest_metrics_requires_core_and_flags_gaps(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text(
        json.dumps({"periods": 1, "held_periods": 1, "cash_periods": 0}), encoding="utf-8"
    )
    errs = check_backtest_metrics(path)
    assert "promotion-grade gap: cost_model not applied/approved (draft or missing)" in errs
    assert (
        "promotion-grade gap: exposure_matched_benchmark not applied/approved (draft or missing)"
        in errs
    )
    assert "promotion-grade gap: net metrics not computed (draft)" in errs


def test_check_backtest_metrics_flags_draft_placeholders(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text(
        json.dumps(
            {
                "periods": 1,
                "held_periods": 1,
                "cash_periods": 0,
                "cost_model": {"status": "draft_pending_dec_004", "applied": False},
                "exposure_matched_benchmark": {"status": "draft_pending_dec_004", "applied": False},
                "net_metrics_status": "not_computed_draft",
            }
        ),
        encoding="utf-8",
    )
    errs = check_backtest_metrics(path)
    assert any("cost_model not applied" in e for e in errs)
    assert any("exposure_matched_benchmark not applied" in e for e in errs)
    assert any("net metrics not computed" in e for e in errs)


def test_check_manifest_passes_minimal_structure(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "r1",
                "run_type": "x",
                "created_at_utc": "2026-11-16T00:00:00Z",
                "code": {"sha": "abc"},
                "hashes": {},
            }
        ),
        encoding="utf-8",
    )
    assert check_manifest(path) == []


def _complete_policy():
    import copy
    import json

    from scripts.check_promotion_evidence import DEFAULT_POLICY

    policy = copy.deepcopy(json.loads(DEFAULT_POLICY.read_text(encoding="utf-8")))
    policy["status"] = "approved"
    policy["holdout"].update(
        {
            "id": "HO-1",
            "freeze_date": "2026-01-01",
            "owner": "owner",
            "untouched_evidence_ref": "ev",
            "snapshot_refs": ["snap"],
        }
    )
    policy["acceptance_policy"]["change_control_ref"] = "CC-1"
    policy["cost_model"].update({"id": "CM-1", "version": "1"})
    policy["cost_model"]["assumptions"].update(
        {"commission_bps": 1, "spread_bps": 2, "slippage_bps": 3, "cash_treatment": "zero"}
    )
    policy["benchmark"].update(
        {
            "id": "BM-1",
            "version": "1",
            "universe_alignment": "pit",
            "exposure_alignment": "matched",
            "rebalance_alignment": "same",
            "cash_treatment": "zero",
        }
    )
    policy["promotion_decision"].update(
        {"approver": "x", "approved_at": "2026-02-01", "evidence_refs": ["e"]}
    )
    return policy


def test_template_policy_reports_gaps():
    from scripts.check_promotion_evidence import DEFAULT_POLICY, check_policy_gaps

    gaps = check_policy_gaps(DEFAULT_POLICY)
    assert any("cost_model.assumptions.commission_bps" in g for g in gaps)
    assert any("holdout.snapshot_refs is empty" in g for g in gaps)
    assert any("status is 'draft_pending_decisions'" in g for g in gaps)


def test_complete_policy_has_no_gaps(tmp_path):
    import json

    from scripts.check_promotion_evidence import check_policy_gaps

    path = tmp_path / "policy.json"
    path.write_text(json.dumps(_complete_policy()), encoding="utf-8")
    assert check_policy_gaps(path) == []


def test_require_promotion_grade_still_fails_on_complete_policy(tmp_path):
    import json

    from scripts.check_promotion_evidence import main

    path = tmp_path / "policy.json"
    path.write_text(json.dumps(_complete_policy()), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"run_id": "r", "run_type": "t", "created_at_utc": "x", "code": {}, "hashes": {}}
        ),
        encoding="utf-8",
    )
    assert (
        main(["--manifest", str(manifest), "--policy", str(path), "--require-promotion-grade"]) == 1
    )


def test_missing_policy_is_reported(tmp_path):
    from scripts.check_promotion_evidence import check_policy_gaps

    assert "missing promotion policy" in check_policy_gaps(tmp_path / "nope.json")[0]
