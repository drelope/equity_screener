import json

from src.crispdm.run_manifest import (
    build_run_manifest,
    canonical_json,
    get_dependency_lock_hashes,
    sha256_hex,
    write_manifest_file,
)


def test_sha256_hex_is_deterministic_for_dict_key_order():
    a = {"b": 2, "a": 1}
    b = {"a": 1, "b": 2}
    assert canonical_json(a) == canonical_json(b)
    assert sha256_hex(a) == sha256_hex(b)


def test_build_run_manifest_includes_hashes_and_core_fields():
    manifest = build_run_manifest(
        run_type="score",
        code_sha="abc123",
        code_dirty=False,
        config={"model_version": "rule_scoring_v1"},
        parameters={"as_of": "2026-11-15"},
        inputs={"scores_table": "model.scores", "snapshot": "snap-1"},
        outputs={"rows": 10},
        resolved_as_of="2026-11-15",
        acceptance_policy_id="policy-a",
        acceptance_policy_version="v1",
        environment={"python": "3.11", "lock_hash": "lock123"},
        run_id="run-1",
        created_at_utc="2026-11-16T00:00:00+00:00",
    )

    assert manifest["run_id"] == "run-1"
    assert manifest["run_type"] == "score"
    assert manifest["created_at_utc"] == "2026-11-16T00:00:00+00:00"
    assert manifest["code"] == {"sha": "abc123", "dirty": False}
    assert manifest["acceptance_policy"]["hash"]
    assert manifest["hashes"]["config_hash"] == sha256_hex({"model_version": "rule_scoring_v1"})
    assert manifest["hashes"]["inputs_hash"] == sha256_hex(
        {"scores_table": "model.scores", "snapshot": "snap-1"}
    )
    assert manifest["hashes"]["manifest_core_hash"]


def test_build_run_manifest_requires_run_type():
    try:
        build_run_manifest(run_type="  ")
    except ValueError as exc:
        assert "run_type" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_get_dependency_lock_hashes_reports_missing_files(tmp_path):
    hashes = get_dependency_lock_hashes(tmp_path)
    assert hashes["requirements.lock.txt"] is None
    assert hashes["requirements-dev.lock.txt"] is None
    assert hashes["lock_strategy"] == "exact_pins_plus_lock_sha256"
    assert hashes["lock_strategy_version"] == "1.0.0"
    assert hashes["platform_python"]
    assert hashes["platform_system"]
    assert hashes["platform_machine"]


def test_build_run_manifest_includes_dependency_lock_hashes(tmp_path, monkeypatch):
    (tmp_path / "requirements.lock.txt").write_text("pkg==1.0.0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    manifest = build_run_manifest(
        run_type="score",
        environment={"dependency_lock_hashes": get_dependency_lock_hashes(tmp_path)},
    )
    import hashlib

    expected = hashlib.sha256(b"pkg==1.0.0\n").hexdigest()
    assert manifest["environment"]["dependency_lock_hashes"]["requirements.lock.txt"] == expected
    assert manifest["environment"]["dependency_lock_hashes"]["requirements-dev.lock.txt"] is None
    assert manifest["hashes"]["environment_hash"] == sha256_hex(manifest["environment"])


def test_write_manifest_file_appends_registry(tmp_path):
    manifest = build_run_manifest(run_type="score", run_id="run-1")
    path = tmp_path / "runs" / "score_x" / "manifest.json"
    write_manifest_file(manifest, path)
    assert path.exists()
    registry = tmp_path / "runs" / "manifest_registry.jsonl"
    assert registry.exists()
    lines = registry.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["run_id"] == "run-1"
    assert rec["run_type"] == "score"
    assert rec["manifest_path"] == str(path)
    assert rec["manifest_hash"] == sha256_hex(manifest)


def test_write_manifest_file_can_disable_registry(tmp_path):
    manifest = build_run_manifest(run_type="score")
    path = tmp_path / "runs" / "x" / "manifest.json"
    write_manifest_file(manifest, path, append_registry=False)
    assert path.exists()
    assert not (tmp_path / "runs" / "manifest_registry.jsonl").exists()
