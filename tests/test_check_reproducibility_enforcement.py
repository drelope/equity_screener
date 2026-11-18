from scripts.check_reproducibility_enforcement import (
    PROJECT_ROOT,
    check_ci,
    check_docker,
    check_lock_files,
    check_manifest_capture,
    run,
)


def test_real_repo_produces_draft_gap_report(capsys):
    from scripts.check_reproducibility_enforcement import main

    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "status=pass_draft_gap_report" in out
    assert "enforcement_claim=false" in out


def test_require_enforced_fails():
    report = run(PROJECT_ROOT, require_enforced=True)
    assert report["status"] == "fail_enforcement_not_approved"
    assert report["enforcement_claim"] is False


def test_ci_gap_detection():
    compliant = (
        "pip install -r requirements.lock.txt --require-hashes\ncheck_reproducibility_locks.py"
    )
    assert check_ci(compliant) == []
    found = check_ci("pip install -r requirements.txt\ncheck_reproducibility_locks.py")
    assert "CI does not install from requirements.lock.txt" in found
    assert "CI still installs unpinned requirements.txt" in found
    assert "CI does not enforce --require-hashes" in check_ci(
        "pip install -r requirements.lock.txt"
    )


def test_docker_gap_detection():
    gaps = check_docker("pip install -r requirements.lock.txt --require-hashes")
    assert gaps == []
    text = "pip install -r requirements.txt\nRUN pip install --ignore-installed pillow"
    found = check_docker(text)
    assert "Dockerfile still installs unpinned requirements.txt" in found
    assert "Dockerfile has an unpinned pillow override" in found


def test_manifest_capture_detection():
    assert check_manifest_capture("get_dependency_lock_hashes()") == []
    assert check_manifest_capture("pass") == ["run manifests do not capture dependency lock hashes"]


def test_missing_lock_files_reported(tmp_path):
    errors, counts = check_lock_files(tmp_path)
    assert any("missing lock file" in err for err in errors)
    assert counts == {}
