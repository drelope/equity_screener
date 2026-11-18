import json

from scripts.check_candidate_backfill_readiness import (
    CANDIDATES,
    DEFAULT_CANDIDATES_DIR,
    evaluate_candidate,
    render_sql,
    run_readonly,
    run_static,
    sanitized_target,
)


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class FakeConn:
    def __init__(self, object_answers, query_answers):
        self.object_answers = object_answers
        self.query_answers = query_answers

    def execute(self, statement, params=None):
        sql = str(statement)
        if "to_regclass" in sql:
            return FakeResult(self.object_answers.get(("table", params["qualified"]), False))
        if "information_schema.columns" in sql:
            key = ("column", params["schema"], params["table"], params["column"])
            return FakeResult(self.object_answers.get(key, False))
        return FakeResult(self.query_answers.get(sql.strip(), 0))


def fake_conn(version, values, *, objects_present=True):
    spec = CANDIDATES[version]
    object_answers = {}
    for obj in spec["objects"]:
        if obj[0] == "table":
            object_answers[("table", obj[1])] = objects_present
        elif len(obj) == 3:
            schema, table = obj[1].rsplit(".", 1)
            object_answers[("column", schema, table, obj[2])] = objects_present
        else:
            object_answers[("column", obj[1], obj[2], obj[3])] = objects_present
    query_answers = {sql.strip(): values.get(key, 0) for key, sql, _ in spec["checks"]}
    return FakeConn(object_answers, query_answers)


def test_static_checks_pass_for_numbered_candidates():
    report = run_static()
    assert report["status"] == "pass"
    assert report["candidate_versions"] == [107, 108, 109, 110, 111, 112, 113]
    assert report["existing_max_version"] == 106


def test_catalog_covers_every_data_readiness_candidate():
    manifest = json.loads((DEFAULT_CANDIDATES_DIR / "candidate-manifest.json").read_text())
    versions = {item["version"] for item in manifest["candidates"]}
    assert set(CANDIDATES) == {107, 108, 109, 110}
    assert versions - set(CANDIDATES) == {111, 112, 113}


def test_missing_schema_is_not_applied():
    result = evaluate_candidate(fake_conn(107, {}, objects_present=False), 107, CANDIDATES[107])
    assert result["schema_status"] == "not_applied"
    assert result["data_status"] == "unknown"
    assert "reference.security_membership_history" in result["missing_objects"]


def test_empty_primary_table_is_no_data():
    result = evaluate_candidate(fake_conn(107, {"membership_rows": 0}), 107, CANDIDATES[107])
    assert result["schema_status"] == "present"
    assert result["data_status"] == "no_data"
    assert any("backfill not started" in issue for issue in result["issues"])


def test_overlap_and_inactive_anomalies_require_attention():
    values = {
        "membership_rows": 2,
        "securities_total": 2,
        "securities_with_delisted_date": 1,
        "inactive_securities": 1,
        "inactive_without_delisted_date": 1,
        "open_membership_intervals": 1,
        "overlapping_membership_pairs": 1,
        "eligibility_rows": 1,
    }
    result = evaluate_candidate(fake_conn(107, values), 107, CANDIDATES[107])
    assert result["data_status"] == "attention_required"
    assert any("overlapping membership intervals" in issue for issue in result["issues"])
    assert any("without delisted_date" in issue for issue in result["issues"])


def test_clean_candidate_checks_pass():
    values = {
        "membership_rows": 1,
        "securities_total": 1,
        "securities_with_delisted_date": 1,
        "inactive_securities": 0,
        "inactive_without_delisted_date": 0,
        "open_membership_intervals": 1,
        "overlapping_membership_pairs": 0,
        "eligibility_rows": 1,
    }
    result = evaluate_candidate(fake_conn(107, values), 107, CANDIDATES[107])
    assert result["data_status"] == "checks_passed"
    assert result["issues"] == []


def test_query_error_is_recorded_without_crashing():
    class BrokenConn(FakeConn):
        def execute(self, statement, params=None):
            sql = str(statement)
            if "to_regclass" in sql:
                return FakeResult(True)
            if "information_schema.columns" in sql:
                return FakeResult(True)
            raise RuntimeError("permission denied")

    result = evaluate_candidate(BrokenConn({}, {}), 107, CANDIDATES[107])
    assert result["schema_status"] == "present"
    assert result["check_errors"]
    assert any("query failed" in issue for issue in result["issues"])


def test_safety_refusal_does_not_connect():
    report = run_readonly("postgresql://u:p@localhost:5432/dividend", False, False)
    assert report["status"] == "safety_refused"
    assert any("shared/production-like" in issue for issue in report["issues"])


def test_sanitized_target_omits_credentials():
    target = sanitized_target("postgresql+psycopg://user:secret@localhost:55439/rehearsal")
    assert target == {"host": "localhost", "database": "rehearsal", "driver": "postgresql+psycopg"}
    assert "secret" not in json.dumps(target)


def test_rendered_sql_contains_every_check():
    sql = render_sql()
    for version, spec in CANDIDATES.items():
        assert f"-- V{version:04d}:" in sql
        for key, _query, _issue in spec["checks"]:
            assert f"-- check: {key}" in sql
