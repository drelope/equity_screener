import copy
import json

from scripts.check_manifest_ledger_policy import (
    DEFAULT_POLICY,
    check_policy,
    is_approved,
    main,
)


def load_template():
    return json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))


def approved_policy():
    policy = copy.deepcopy(load_template())
    policy["status"] = "approved"
    policy["retention"]["minimum_days"] = 2555
    policy["approvals"] = {
        "M1": "M1-2026-11-16",
        "DEC-002": "DEC-002-2026-11-16",
        "DEC-003": "DEC-003-2026-11-16",
        "DEC-005": "DEC-005-2026-11-16",
    }
    return policy


def test_draft_template_passes_structure_and_safety_invariants():
    policy = load_template()
    assert check_policy(policy) == []
    assert is_approved(policy) is False


def test_approved_fixture_passes():
    policy = approved_policy()
    assert check_policy(policy) == []
    assert is_approved(policy) is True


def test_writer_update_is_rejected():
    policy = load_template()
    policy["roles"]["manifest_writer"]["grants"].append(
        {"table": "audit.run_manifests", "privileges": ["UPDATE"]}
    )
    assert any("manifest_writer must not have UPDATE" in err for err in check_policy(policy))


def test_reader_insert_is_rejected():
    policy = load_template()
    policy["roles"]["manifest_reader"]["grants"].append(
        {"table": "audit.run_outputs", "privileges": ["INSERT"]}
    )
    assert any("manifest_reader must not have INSERT" in err for err in check_policy(policy))


def test_missing_role_is_rejected():
    policy = load_template()
    del policy["roles"]["ledger_auditor"]
    assert any("missing required roles" in err for err in check_policy(policy))


def test_retention_legal_hold_is_required():
    policy = load_template()
    policy["retention"]["legal_hold"] = False
    assert any("retention.legal_hold must be true" in err for err in check_policy(policy))


def test_incident_dual_control_is_required():
    policy = load_template()
    policy["incident_response"]["dual_control"] = False
    assert any("incident_response.dual_control must be true" in err for err in check_policy(policy))


def test_approved_policy_requires_retention_period():
    policy = approved_policy()
    policy["retention"]["minimum_days"] = None
    assert any("minimum_days" in err for err in check_policy(policy))


def test_approved_policy_requires_approval_evidence():
    policy = approved_policy()
    policy["approvals"]["DEC-005"] = None
    assert any("approvals.DEC-005" in err for err in check_policy(policy))


def test_cli_draft_passes_but_require_approved_fails(capsys):
    assert main([]) == 0
    capsys.readouterr()
    assert main(["--require-approved"]) == 1
    assert "not approved" in capsys.readouterr().out


def test_cli_approved_file_passes(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(approved_policy()), encoding="utf-8")
    assert main(["--policy", str(path), "--require-approved"]) == 0


def test_cli_invalid_json_returns_2(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text("{not json", encoding="utf-8")
    assert main(["--policy", str(path)]) == 2
