import hashlib
import json

from scripts.check_migration_candidates import (
    DEFAULT_CANDIDATES_DIR,
    DEFAULT_MIGRATIONS_DIR,
    check_forward_sql,
    check_header,
    run,
    strip_sql_comments,
)

HEADER = """-- CANDIDATE: NOT APPLIED - test
-- APPROVAL-GATES: M1
-- ROLLBACK: rollback/V0107_rollback.sql
BEGIN;
CREATE TABLE IF NOT EXISTS reference.test_table (id BIGSERIAL PRIMARY KEY);
COMMIT;
"""

ROLLBACK = """-- ROLLBACK CANDIDATE: NOT APPLIED - test
BEGIN;
DROP TABLE IF EXISTS reference.test_table;
COMMIT;
"""


def _manifest(
    filename: str, sql: str, *, version=107, rollback="rollback/V0107_rollback.sql", deps=None
):
    return {
        "schema": "p0_migration_candidates/v1",
        "status": "candidate_not_applied",
        "candidates": [
            {
                "version": version,
                "filename": filename,
                "sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                "area": "RM-TEST",
                "title": "test",
                "requirements": ["FR-TEST-01"],
                "approval_gates": ["M1"],
                "depends_on_candidates": deps or [],
                "soft_depends_on": [],
                "backfill_required": False,
                "rollback_file": rollback,
                "rehearsal_ref": "test",
            }
        ],
    }


def _fixture(tmp_path, *, sql=HEADER, manifest=None, rollback=ROLLBACK):
    migrations = tmp_path / "migrations"
    candidates = tmp_path / "candidates"
    (candidates / "rollback").mkdir(parents=True)
    migrations.mkdir()
    (migrations / "V0106_base.sql").write_text("-- base\n", encoding="utf-8")
    (candidates / "V0107_test.sql").write_text(sql, encoding="utf-8")
    (candidates / "rollback" / "V0107_rollback.sql").write_text(rollback, encoding="utf-8")
    payload = manifest if manifest is not None else _manifest("V0107_test.sql", sql)
    (candidates / "candidate-manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return candidates, migrations


def test_valid_candidate_fixture_passes(tmp_path):
    candidates, migrations = _fixture(tmp_path)
    errs, summary = run(candidates, migrations)
    assert errs == []
    assert summary["status"] == "pass"
    assert summary["existing_max_version"] == 106


def test_hash_mismatch_is_reported(tmp_path):
    candidates, migrations = _fixture(tmp_path)
    manifest = _manifest("V0107_test.sql", HEADER)
    manifest["candidates"][0]["sha256"] = "0" * 64
    (candidates / "candidate-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    errs, _ = run(candidates, migrations)
    assert any("sha256 does not match" in err for err in errs)


def test_candidate_version_must_exceed_existing_max(tmp_path):
    candidates = tmp_path / "candidates"
    migrations = tmp_path / "migrations"
    (candidates / "rollback").mkdir(parents=True)
    migrations.mkdir()
    (migrations / "V0107_base.sql").write_text("-- base\n", encoding="utf-8")
    (candidates / "V0107_test.sql").write_text(HEADER, encoding="utf-8")
    (candidates / "rollback" / "V0107_rollback.sql").write_text(ROLLBACK, encoding="utf-8")
    manifest = _manifest("V0107_test.sql", HEADER)
    (candidates / "candidate-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    errs, _ = run(candidates, migrations)
    assert any("must be greater than current max" in err for err in errs)


def test_missing_header_marker_is_reported(tmp_path):
    sql = "BEGIN;\nCREATE TABLE t (id INT);\nCOMMIT;\n"
    candidates, migrations = _fixture(tmp_path, sql=sql)
    errs, _ = run(candidates, migrations)
    assert any("CANDIDATE: NOT APPLIED" in err for err in errs)


def test_destructive_forward_sql_is_rejected(tmp_path):
    sql = HEADER + "\nDROP TABLE reference.old;\n"
    candidates, migrations = _fixture(tmp_path, sql=sql)
    errs, _ = run(candidates, migrations)
    assert any("destructive keyword 'DROP'" in err for err in errs)


def test_dependency_must_be_declared(tmp_path):
    candidates, migrations = _fixture(tmp_path)
    manifest = _manifest("V0107_test.sql", HEADER, deps=[199])
    (candidates / "candidate-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    errs, _ = run(candidates, migrations)
    assert any("dependency V199" in err for err in errs)


def test_missing_rollback_file_is_reported(tmp_path):
    candidates, migrations = _fixture(tmp_path)
    manifest = _manifest("V0107_test.sql", HEADER, rollback="rollback/missing.sql")
    (candidates / "candidate-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    errs, _ = run(candidates, migrations)
    assert any("rollback file missing" in err for err in errs)


def test_manifest_entry_without_file_is_reported(tmp_path):
    candidates, migrations = _fixture(tmp_path)
    manifest = _manifest("V0107_test.sql", HEADER)
    extra = dict(manifest["candidates"][0])
    extra["version"] = 108
    extra["filename"] = "V0108_missing.sql"
    manifest["candidates"].append(extra)
    (candidates / "candidate-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    errs, _ = run(candidates, migrations)
    assert any("no candidate file exists" in err for err in errs)


def test_manifest_baseline_max_is_checked(tmp_path):
    candidates, migrations = _fixture(tmp_path)
    manifest = _manifest("V0107_test.sql", HEADER)
    manifest["baseline"] = {"max_existing_version": 105}
    (candidates / "candidate-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    errs, _ = run(candidates, migrations)
    assert any("baseline max_existing_version=105" in err for err in errs)


def test_candidates_dir_must_not_be_migrations_dir(tmp_path):
    candidates, _ = _fixture(tmp_path)
    errs, _ = run(candidates, candidates)
    assert any("must not be sql/migrations" in err for err in errs)


def test_comment_stripping_ignores_destructive_words_in_comments():
    sql = "-- DROP TABLE fake\nCREATE TABLE x (id INT); /* DELETE FROM y */\n"
    assert "DROP" not in strip_sql_comments(sql)
    assert "DELETE" not in strip_sql_comments(sql)


def test_check_header_and_forward_sql_helpers_on_repo_candidate():
    path = DEFAULT_CANDIDATES_DIR / "V0107_rm01_pit_membership.sql"
    assert check_header(path) == []
    assert check_forward_sql(path) == []


def test_repo_candidates_are_internally_consistent():
    errs, summary = run(DEFAULT_CANDIDATES_DIR, DEFAULT_MIGRATIONS_DIR)
    assert errs == []
    assert summary["candidate_versions"] == [107, 108, 109, 110, 111, 112, 113]
    assert summary["existing_max_version"] == 106


def test_trigger_event_clause_is_not_treated_as_destructive(tmp_path):
    path = tmp_path / "V0111_trigger.sql"
    path.write_text(
        """
-- CANDIDATE: NOT APPLIED - test
-- APPROVAL-GATES: M1
-- ROLLBACK: rollback/V0111_rollback.sql
BEGIN;
CREATE TRIGGER run_manifests_append_only
BEFORE UPDATE OR DELETE ON audit.run_manifests
FOR EACH ROW EXECUTE FUNCTION audit.prevent_run_manifest_mutation();
COMMIT;
""",
        encoding="utf-8",
    )
    assert check_forward_sql(path) == []


def test_trigger_file_still_rejects_real_update(tmp_path):
    path = tmp_path / "V0111_update.sql"
    path.write_text("UPDATE audit.run_manifests SET status = 'x';\n", encoding="utf-8")
    assert any("destructive keyword" in err for err in check_forward_sql(path))
