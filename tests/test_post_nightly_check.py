from datetime import date, datetime, timezone

from scripts import post_nightly_check as pnc

RUN_DATE = date(2026, 11, 2)


def _record(**overrides):
    stages = {label: "ok" for label in pnc.REQUIRED_OK}
    stages.update({label: "ok" for label in pnc.SUPPORTING_LABELS})
    stages["_seconds"] = {"scripts.populate_dividend_data": 1.0}
    record = {
        "run_id": 49,
        "trigger": "systemd",
        "started_at": "2026-11-02 08:00",
        "finished_at": "2026-11-02 12:00",
        "status": "success",
        "exit_code": 0,
        "stages": stages,
    }
    record.update(overrides)
    return record


def _by_name(results):
    return {r["name"]: r for r in results}


def test_a_clean_run_passes_every_run_check():
    results = _by_name(pnc.evaluate_run(_record(), RUN_DATE))

    assert all(r["status"] == pnc.PASS for r in results.values())


def test_a_missing_run_record_fails():
    results = pnc.evaluate_run(None, RUN_DATE)

    assert results[0]["status"] == pnc.FAIL and "did not run" in results[0]["detail"]


def test_the_2026_11_01_failure_pattern_is_caught():
    stages = {"scripts.populate_dividend_data": "failed", "scripts.populate_raw_tables": "ok"}
    results = _by_name(
        pnc.evaluate_run(_record(status="failed", exit_code=1, stages=stages), RUN_DATE)
    )

    assert results["run_status"]["status"] == pnc.FAIL
    assert "scripts.populate_dividend_data" in results["failed_stages"]["detail"]
    assert "scripts.build_features=MISSING" in results["required_stages"]["detail"]
    assert results["supporting_loaders"]["status"] == pnc.FAIL


def test_skipped_supporting_loaders_pass_but_missing_or_failed_ones_do_not():
    stages = _record()["stages"]
    stages["scripts.load_xbrl_frames"] = "skipped"
    assert (
        _by_name(pnc.evaluate_run(_record(stages=stages), RUN_DATE))["supporting_loaders"]["status"]
        == pnc.PASS
    )

    stages["scripts.load_xbrl_frames"] = "failed"
    assert (
        _by_name(pnc.evaluate_run(_record(stages=stages), RUN_DATE))["supporting_loaders"]["status"]
        == pnc.FAIL
    )

    del stages["scripts.load_xbrl_frames"]
    detail = _by_name(pnc.evaluate_run(_record(stages=stages), RUN_DATE))["supporting_loaders"][
        "detail"
    ]
    assert "load_xbrl_frames=MISSING" in detail


def test_the_split_calendar_loader_is_one_of_the_checked_stages():
    assert "scripts.load_split_calendar" in pnc.SUPPORTING_LABELS
    assert "scripts.load_sec_bulk" in pnc.SUPPORTING_LABELS


def test_openbb_outliers_fail_only_when_unquarantined():
    assert pnc.evaluate_openbb_outliers(0, 0)["status"] == pnc.PASS
    assert pnc.evaluate_openbb_outliers(65, 0)["status"] == pnc.PASS

    failed = pnc.evaluate_openbb_outliers(65, 1)
    assert failed["status"] == pnc.FAIL
    assert "1 unquarantined" in failed["detail"]
    assert "65 known" in failed["detail"]


def test_freshness_fails_only_on_a_breach_and_not_on_an_unaged_source():
    ok = {"source": "a", "age_hours": 5, "sla_hours": 240, "within_sla": True}
    unaged = {"source": "b", "age_hours": None, "sla_hours": 840, "within_sla": None}
    breach = {"source": "c", "age_hours": 999, "sla_hours": 240, "within_sla": False}

    assert pnc.evaluate_freshness([ok, unaged])["status"] == pnc.PASS
    assert pnc.evaluate_freshness([ok, breach])["status"] == pnc.FAIL
    assert "BREACH" in pnc.evaluate_freshness([ok, breach])["detail"]
    assert pnc.evaluate_freshness([])["status"] == pnc.FAIL


def test_the_report_leads_with_the_verdict_and_escapes_table_pipes():
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    bad = [pnc.check("a", pnc.PASS, "fine"), pnc.check("b", pnc.FAIL, "x | y")]

    report = pnc.render_report(RUN_DATE, bad, now)

    assert "1 CHECK(S) FAILED" in report and "x \\| y" in report
    assert "ALL CHECKS PASSED" in pnc.render_report(RUN_DATE, bad[:1], now)


def test_cron_removal_drops_only_the_marked_line():
    crontab = "0 1 * * * keep-me\n0 7 2 11 * run # post-nightly-check-2026-11-02\n"

    out = pnc.remove_cron_entry(crontab, "post-nightly-check-2026-11-02")

    assert out == "0 1 * * * keep-me\n"
    assert pnc.remove_cron_entry("", "x") == ""


def test_waiting_polls_until_the_lock_is_released_and_then_stops(monkeypatch):
    states = iter([True, True, False])
    sleeps = []
    monkeypatch.setattr(pnc, "pipeline_running", lambda conn=None: next(states))

    message = pnc.wait_for_pipeline(60, poll_seconds=300, sleep=sleeps.append)

    assert sleeps == [300, 300] and "idle" in message


def test_waiting_gives_up_after_the_limit(monkeypatch):
    monkeypatch.setattr(pnc, "pipeline_running", lambda conn=None: True)

    message = pnc.wait_for_pipeline(10, poll_seconds=300, sleep=lambda s: None)

    assert "still running" in message


def test_the_advisory_lock_query_recombines_both_halves_of_a_64_bit_key():
    key = pnc.PIPELINE_LOCK_KEY

    assert key > 2**32  # the high half is nonzero, so a classid = 0 assumption would be wrong
    assert ((key >> 32) << 32 | (key & 0xFFFFFFFF)) == key
    assert "(classid::bigint << 32) | objid::bigint" in pnc.LOCK_SQL


def test_pipeline_running_sees_the_real_lock_in_postgres():
    import pytest
    from sqlalchemy import text

    try:
        from src.crispdm.db import engine

        holder = engine.connect()
        holder.exec_driver_sql("SELECT 1")
    except Exception:  # pragma: no cover - environments without a database
        pytest.skip("no database available")
    key = {"k": pnc.PIPELINE_LOCK_KEY}
    try:
        if not holder.execute(text("SELECT pg_try_advisory_lock(:k)"), key).scalar():
            pytest.skip("a real pipeline run holds the lock right now")
        assert pnc.pipeline_running() is True
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), key)
        assert pnc.pipeline_running() is False
    finally:
        holder.close()


def _base(ids=("a", "b"), total=100):
    return {"total": total, "active": total - 5, "scored_active": list(ids)}


def test_a_scored_security_that_went_inactive_fails_the_identity_guard():
    results = {
        r["name"]: r for r in pnc.evaluate_identities(_base(), {"total": 100, "active": 95}, {"a"})
    }

    assert results["scored_identities_active"]["status"] == pnc.FAIL
    assert (
        "1 of 2" in results["scored_identities_active"]["detail"]
        and "b" in results["scored_identities_active"]["detail"]
    )


def test_a_nightly_that_adds_a_few_listings_passes_and_one_that_mints_many_fails():
    ok = {
        r["name"]: r
        for r in pnc.evaluate_identities(_base(), {"total": 112, "active": 107}, {"a", "b"})
    }
    assert (
        ok["no_minted_identities"]["status"] == pnc.PASS
        and ok["scored_identities_active"]["status"] == pnc.PASS
    )

    bad = {
        r["name"]: r
        for r in pnc.evaluate_identities(_base(), {"total": 400, "active": 395}, {"a", "b"})
    }
    assert bad["no_minted_identities"]["status"] == pnc.FAIL


def test_the_guard_is_informational_without_a_baseline_file(tmp_path):
    results = pnc._identity_checks(tmp_path / "missing.json")

    assert results[0]["status"] == pnc.INFO
