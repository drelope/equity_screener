from scripts.check_clean_environment_parity import PROJECT_ROOT, check_parity


def test_real_repo_parity_passes():
    report = check_parity(PROJECT_ROOT)
    assert report["status"] == "pass_local_parity"
    assert report["runtime_pins"] == 220
    assert report["dev_pins"] == 220
    assert report["issues"] == []
    assert report["strategy"] == "exact_pins_plus_lock_sha256"


def test_missing_lock_fails(tmp_path):
    report = check_parity(tmp_path)
    assert report["status"] == "fail"
    assert any("missing requirements.lock.txt" in issue for issue in report["issues"])
