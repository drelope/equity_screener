from datetime import datetime, timezone

from scripts.run_full_etl import record_nightly_run
from scripts.verify_nightly_run import assess, target_run_date


def _findings(**overrides):
    base = {
        "run_date": "2026-09-24",
        "nightly_run": {
            "run_date": "2026-09-24",
            "trigger": "systemd",
            "exit_code": 0,
            "status": "success",
            "stages": {
                "scripts.populate_raw_tables": "ok",
                "scripts.populate_reference_tables": "ok",
                "scripts.populate_dividend_data": "ok",
                "scripts.populate_companyfacts": "ok",
                "scripts.populate_sec_documents": "ok",
                "scripts.populate_fundamentals": "ok",
                "scripts.populate_audit": "ok",
            },
        },
        "freshness": {"max_retrieval_age_hours": 6.0, "dividend_ex_age_hours": 12.0},
        "quality": {"n": 100, "good_fair_share": 0.9, "mean_quality_score": 0.75},
        "coverage": {"universe": 100, "covered": 99},
        "model_gate": {"run_id": None, "recall": None, "created_at": None},
    }
    base.update(overrides)
    return base


def _f(f, **kw):
    return assess(f, min_quality_score=0.5, min_good_share=0.8, min_coverage=0.95, max_age_hours=26)


def test_assess_ok_when_nightly_run_healthy():
    r = _f(_findings())
    assert r["status"] == "ok"
    assert {c["name"] for c in r["checks"] if c["status"] == "info"} == {"walk_forward_gate"}


def test_assess_attention_when_no_run_record():
    r = _f(_findings(nightly_run=None))
    assert r["status"] == "attention"
    assert [c["name"] for c in r["checks"] if c["status"] == "attention"] == ["nightly_run_record"]


def test_assess_attention_on_failed_stage():
    f = _findings()
    f["nightly_run"]["stages"]["scripts.populate_dividend_data"] = "failed"
    f["nightly_run"]["status"] = "failed"
    f["nightly_run"]["exit_code"] = 1
    r = _f(f)
    assert r["status"] == "attention"
    assert any(
        c["name"] == "stages" and "populate_dividend_data" in c["detail"] for c in r["checks"]
    )


def test_assess_attention_when_freshness_sla_exceeded():
    f = _findings()
    f["freshness"]["max_retrieval_age_hours"] = 100.0
    r = _f(f)
    assert r["status"] == "attention"
    assert any(c["name"] == "freshness" for c in r["checks"] if c["status"] == "attention")


def test_assess_model_gate_attention_when_recall_below_min():
    f = _findings(model_gate={"run_id": "r1", "recall": 0.12, "created_at": "2026-09-24T04:00Z"})
    r = _f(f)
    assert r["status"] == "attention"
    assert any(c["name"] == "walk_forward_gate" and c["status"] == "attention" for c in r["checks"])


def test_assess_tracks_missing_tables_as_attention():
    f = _findings()
    for key in ("freshness", "quality", "coverage", "model_gate"):
        f[key] = None
    r = _f(f)
    assert r["status"] == "attention"
    assert len(r["checks"]) > 1


def test_target_run_date_before_3am_et_is_previous_day():
    now = datetime(2026, 9, 24, 6, 30, tzinfo=timezone.utc)  # 02:30 ET
    assert target_run_date(now) == datetime(2026, 9, 23).date()


def test_target_run_date_after_3am_et_is_same_day():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)  # 08:00 ET
    assert target_run_date(now) == datetime(2026, 9, 24).date()


class _ExecConn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((str(sql), params))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_record_nightly_run_inserts_summary(monkeypatch):
    conn = _ExecConn()
    fake_engine = type("_E", (), {"begin": lambda self: conn})
    import scripts.run_full_etl as m

    monkeypatch.setattr(m, "engine", fake_engine())
    record_nightly_run(
        "systemd",
        datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc),
        {"scripts.populate_audit": "ok", "scripts.populate_raw_tables": "failed"},
        1,
    )
    sql, params = conn.executed[0]
    assert "INSERT INTO audit.nightly_runs" in sql
    assert params["trigger"] == "systemd"
    assert params["status"] == "failed"
    assert "failed" in params["stages"]
    assert params["exit_code"] == 1
