import importlib.util
import sys
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from scripts import run_full_etl
from scripts.run_full_etl import record_nightly_run
from scripts.verify_nightly_run import (
    FRESHNESS_SOURCES,
    POC_COMPANYFACTS_BOUND_HOURS,
    POC_DAILY_BOUND_HOURS,
    PREFERRED_PREFERENCE_REVIEW_THRESHOLD,
    _age_hours,
    _coverage_query,
    _freshness_query,
    _security_consistency_query,
    assess,
    target_run_date,
)


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
        "freshness": {
            "sources": {
                "raw.ticker_profile": 6.0,
                "raw.dividend_data": 12.0,
                "raw.market_data": 12.0,
                "reference.securities": 6.0,
                "raw.companyfacts": 72.0,
                "preferred.contract_terms": 6.0,
            }
        },
        "quality": {"n": 100, "good_fair_share": 0.9, "mean_quality_score": 0.75},
        "coverage": {"universe": 100, "covered": 99},
        "security_consistency": {
            "active_identity_duplicates": 0,
            "active_preferred_missing_issuer_id": 0,
            "active_repeated_preferred_titles": 0,
            "active_preferred_missing_coupon": 0,
            "active_preferred_missing_liquidation_preference": 0,
            "active_preferred_preference_over_threshold": 0,
            "active_preferred_issuer_only_titles": 0,
            "active_preferred_warrant_like": 0,
            "active_common_with_preferred_terms": 0,
            "active_ticker_reuse_across_ciks": 0,
        },
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
    # Set the age from the configured bound rather than hard-coding it, so this
    # keeps testing "over the bound is attention" when the PoC bounds are
    # reverted to deployed values, instead of silently becoming a passing test
    # that no longer breaches anything.
    f = _findings()
    f["freshness"]["sources"]["raw.dividend_data"] = (
        FRESHNESS_SOURCES["raw.dividend_data"]["sla_hours"] + 1.0
    )
    r = _f(f)
    assert r["status"] == "attention"
    assert any(c["name"] == "freshness" for c in r["checks"] if c["status"] == "attention")


def test_assess_attention_on_reference_security_anomalies():
    f = _findings()
    f["security_consistency"]["active_identity_duplicates"] = 1
    f["security_consistency"]["active_preferred_missing_liquidation_preference"] = 4
    check = next(c for c in _f(f)["checks"] if c["name"] == "security_consistency")
    assert check["status"] == "attention"
    assert "active_identity_duplicates=1" in check["detail"]
    assert "active_preferred_missing_liquidation_preference=4" in check["detail"]


def test_a_warrant_like_preferred_row_needs_attention():
    f = _findings()
    f["security_consistency"]["active_preferred_warrant_like"] = 2
    check = next(c for c in _f(f)["checks"] if c["name"] == "security_consistency")
    assert check["status"] == "attention"
    assert "active_preferred_warrant_like=2" in check["detail"]


def test_preferred_terms_on_a_common_row_need_attention():
    f = _findings()
    f["security_consistency"]["active_common_with_preferred_terms"] = 5
    check = next(c for c in _f(f)["checks"] if c["name"] == "security_consistency")
    assert check["status"] == "attention"
    assert "active_common_with_preferred_terms=5" in check["detail"]


def test_preferred_reference_gaps_are_informational_not_blocking():
    f = _findings()
    f["security_consistency"]["active_preferred_missing_coupon"] = 806
    f["security_consistency"]["active_preferred_missing_liquidation_preference"] = 435
    r = _f(f)
    check = next(c for c in r["checks"] if c["name"] == "security_consistency")
    assert check["status"] == "info"
    assert "active_preferred_missing_coupon=806" in check["detail"]
    assert r["status"] == "ok"


def test_identity_duplicates_still_need_attention_alongside_reference_gaps():
    f = _findings()
    f["security_consistency"]["active_preferred_missing_coupon"] = 806
    f["security_consistency"]["active_identity_duplicates"] = 1
    r = _f(f)
    check = next(c for c in r["checks"] if c["name"] == "security_consistency")
    assert check["status"] == "attention"
    assert "active_identity_duplicates=1" in check["detail"]
    assert "active_preferred_missing_coupon=806" in check["detail"]
    assert r["status"] == "attention"


def test_ticker_reuse_across_ciks_is_reported_without_assuming_duplicate():
    f = _findings()
    f["security_consistency"]["active_ticker_reuse_across_ciks"] = 3
    check = next(c for c in _f(f)["checks"] if c["name"] == "security_consistency")
    assert check["status"] == "ok"
    assert "active_ticker_reuse_across_ciks=3" in check["detail"]


def test_an_open_ticker_conflict_needs_attention_and_names_the_tickers():
    f = _findings(ticker_conflicts={"open": 2, "tickers": ["PORT-UN", "ABC"]})

    result = _f(f)

    check = next(c for c in result["checks"] if c["name"] == "ticker_conflicts")
    assert check["status"] == "attention"
    assert "2 open" in check["detail"] and "PORT-UN, ABC" in check["detail"]
    assert "resolve_ticker_conflict review" in check["detail"]
    assert result["status"] == "attention"


def test_no_open_ticker_conflicts_is_ok():
    result = _f(_findings(ticker_conflicts={"open": 0, "tickers": []}))
    check = next(c for c in result["checks"] if c["name"] == "ticker_conflicts")
    assert check["status"] == "ok" and result["status"] == "ok"


def test_findings_from_an_older_build_add_no_conflict_check():
    assert "ticker_conflicts" not in {c["name"] for c in _f(_findings())["checks"]}


def test_security_consistency_query_uses_active_rows_and_named_threshold():
    query = str(_security_consistency_query())
    assert "WHERE s.active = TRUE" in query
    assert "> :preference_review_threshold" in query
    assert "AS active_preferred_warrant_like" in query
    assert "AS active_common_with_preferred_terms" in query
    assert PREFERRED_PREFERENCE_REVIEW_THRESHOLD == 1000.0


def test_coverage_query_scopes_both_sides_to_active_securities():
    """A deactivated former payer keeps ``dividend = TRUE`` and must not count.

    A recency reclassification inserts a new ``security_id`` and sets the old
    row ``active = FALSE`` rather than deleting it, so the stale row still
    carries ``dividend = TRUE``. Both the universe count and the covered join
    must therefore require ``active = TRUE``; without it the reported universe
    (and covered share) stays inflated by every retired payer, and the metric
    diverges from the partial index that actually defines the universe.
    """
    query = str(_coverage_query())
    assert query.count("active = TRUE") == 2
    assert "WHERE dividend = TRUE AND active = TRUE" in query
    assert "s.dividend = TRUE AND s.active = TRUE" in query


def test_companyfacts_is_bounded_by_its_own_refresh_cycle():
    """A multi-day snapshot source is not held to the nightly bound.

    ``raw.companyfacts`` is refreshed on a multi-day cycle, so a payload a few
    days old is inside its own bound. Holding it to the daily bound would make
    the check unsatisfiable by a perfectly healthy nightly -- the same ceiling
    problem WS5 found in the PR-AUC criterion. The bound is asserted from the
    table, not hard-coded, so the reverted post-PoC value needs no test edit.
    """
    r = _f(_findings())
    detail = next(c["detail"] for c in r["checks"] if c["name"] == "freshness")
    assert "raw.companyfacts 72.0h (SLA 504.0h)" in detail

    f = _findings()
    f["freshness"]["sources"]["raw.companyfacts"] = 600.0
    r = _f(f)
    detail = next(c["detail"] for c in r["checks"] if c["name"] == "freshness")
    assert "raw.companyfacts 600.0h (SLA 504.0h)" in detail
    assert r["status"] == "attention"


def test_freshness_names_the_breaching_source_not_just_the_worst_age():
    f = _findings()
    f["freshness"]["sources"]["raw.market_data"] = 900.0
    f["freshness"]["sources"]["raw.ticker_profile"] = 3.0
    detail = next(c["detail"] for c in _f(f)["checks"] if c["name"] == "freshness")
    assert "raw.market_data 900.0h" in detail


def test_freshness_ignores_a_source_with_no_stored_rows():
    """An unmeasured source must not read as a stale one."""
    f = _findings()
    f["freshness"]["sources"]["raw.market_data"] = None
    r = _f(f)
    assert r["status"] == "ok"
    assert "raw.market_data" not in next(
        c["detail"] for c in r["checks"] if c["name"] == "freshness"
    )


def test_freshness_still_honours_the_pre_split_finding_keys():
    """A findings document written by an older build must not read as fresh."""
    f = _findings(freshness={"max_retrieval_age_hours": 6.0, "dividend_ex_age_hours": 99.0})
    r = _f(f)
    detail = next(c["detail"] for c in r["checks"] if c["name"] == "freshness")
    assert "dividend_ex_age_hours 99.0h (SLA 26.0h)" in detail
    assert r["status"] == "attention"


def test_assess_model_gate_attention_when_recall_below_min():
    f = _findings(model_gate={"run_id": "r1", "recall": 0.12, "created_at": "2026-09-24T04:00Z"})
    r = _f(f)
    assert r["status"] == "attention"
    assert any(c["name"] == "walk_forward_gate" and c["status"] == "attention" for c in r["checks"])


def test_a_no_go_walk_forward_is_informational_not_a_pass_or_a_failure():
    """The accepted NO-GO: rule-based scoring is the product, so it neither alarms nor passes.

    Its recall (1.0) is the always-"sustainable" model's. Reading it against MIN_RECALL
    reported OK for a model that cannot tell a cut from a payment.
    """
    f = _findings(
        model_gate={
            "run_id": "r1",
            "recall": 1.0,
            "readiness": "no_go",
            "created_at": "2026-10-06T20:19Z",
        }
    )

    result = _f(f)

    check = next(c for c in result["checks"] if c["name"] == "walk_forward_gate")
    assert check["status"] == "info"
    assert "not adopted" in check["detail"] and "rule-based" in check["detail"]
    assert "recall" not in check["detail"]
    assert result["status"] == "ok"


def test_a_go_verdict_is_still_checked_against_the_recall_floor():
    go = _f(
        _findings(model_gate={"run_id": "r1", "recall": 0.5, "readiness": "go", "created_at": "t"})
    )
    assert next(c for c in go["checks"] if c["name"] == "walk_forward_gate")["status"] == "ok"

    weak = _f(
        _findings(model_gate={"run_id": "r1", "recall": 0.1, "readiness": "go", "created_at": "t"})
    )
    assert (
        next(c for c in weak["checks"] if c["name"] == "walk_forward_gate")["status"] == "attention"
    )


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


def test_age_hours_accepts_a_plain_date_and_a_naive_datetime():
    """The retrieval columns are timestamptz; be tolerant of the rest anyway."""

    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    assert _age_hours(date(2026, 9, 24), now) == pytest.approx(12.0)
    assert _age_hours(now.replace(tzinfo=None), now) == pytest.approx(0.0)
    assert _age_hours(now, now) == pytest.approx(0.0)
    assert _age_hours(None, now) is None
    assert _age_hours(now.isoformat(), now) == pytest.approx(0.0)


# All three companyfacts stages invoke the same module and are told apart only by
# the audit label and a flag in argv, so tests identify them by that flag rather
# than by module name -- the module name is identical for all three.
_STAGE_MARKER = {
    "scripts.populate_companyfacts.preferred": "--preferred-facts",
    "scripts.populate_companyfacts.unlinked": "--sweep-unlinked",
}
_STAGE_MODULE = "scripts.populate_companyfacts"


def _free_lock():
    """Drive ``main`` without touching the production advisory lock.

    ``main`` takes the pipeline lock on a real connection before stage 0, so
    every test that invokes it reached the live warehouse. The nightly holds
    that key for the length of a run, which turned assertions about argv and
    stage order into ``main() == 2`` and, on CI where there is no database at
    all, into ``OperationalError``. Neither failure had anything to do with
    what the test was checking.

    Nothing here is under test but the lock, and the lock has its own coverage:
    ``test_second_concurrent_run_is_refused_not_silently_stacked`` exercises
    real acquisition, and ``test_conflicting_run_exits_2_without_running_any_
    stage`` exercises the refusal path. ``_release_run_lock`` returns early on
    ``None``, so a stub handle is all the teardown needs.
    """
    return patch.object(run_full_etl, "_acquire_run_lock", return_value=None)


def _companyfacts_stage_args(argv, stage=None):
    """Stage-4 argv the orchestrator would hand ``populate_companyfacts``.

    ``stage`` is the audit label; omit it for 4b, the dividend universe, which is
    the one carrying neither marker flag.
    """
    calls = []

    def _fake_run(name, args, skip=False):
        calls.append((name, list(args), skip))
        return True

    with (
        patch.object(run_full_etl, "run_module", side_effect=_fake_run),
        # Never record a run: these assertions are about argv, and a nightly_runs
        # row written by a unit test would be indistinguishable from a real one.
        patch.object(run_full_etl, "record_nightly_run"),
        patch.object(sys, "argv", ["run_full_etl", *argv]),
        _free_lock(),
    ):
        assert run_full_etl.main() == 0

    marker = _STAGE_MARKER.get(stage)
    for name, args, _skip in calls:
        if name != _STAGE_MODULE:
            continue
        if (marker in args) if marker else (not any(m in args for m in _STAGE_MARKER.values())):
            return args
    raise AssertionError(f"no companyfacts stage matched {stage!r}; calls={calls}")


def _recorded_stages(argv):
    """The label->status mapping the orchestrator would write to audit.nightly_runs."""
    recorded = {}

    def _fake_record(trigger, started_at, stages, exit_code):
        recorded.update(stages)

    with (
        patch.object(run_full_etl, "run_module", return_value=True),
        patch.object(run_full_etl, "record_nightly_run", side_effect=_fake_record),
        patch.object(sys, "argv", ["run_full_etl", *argv]),
        _free_lock(),
    ):
        assert run_full_etl.main() == 0
    return recorded


def test_nightly_refreshes_stored_companyfacts_by_default():
    """A stored CIK is skipped forever unless the nightly asks for a refresh.

    Without the flag the stage completes as ``ok`` having re-requested nothing,
    so ``raw.companyfacts`` -- and every filing vintage derived from it -- stays
    frozen at first sighting while the nightly looks healthy.
    """
    args = _companyfacts_stage_args([])
    assert args[args.index("--refresh-after-days") + 1] == "5"


def test_nightly_refresh_can_be_disabled():
    assert "--refresh-after-days" not in _companyfacts_stage_args(
        ["--companyfacts-refresh-after-days", "-1"]
    )


def test_nightly_limit_is_passed_as_max_ciks():
    """``populate_companyfacts`` has no ``--limit``; stage 4 used to pass one."""
    args = _companyfacts_stage_args(["--limit", "5"])
    assert args[args.index("--max-ciks") + 1] == "5"
    assert "--limit" not in args


def test_companyfacts_freshness_uses_the_oldest_snapshot_not_the_newest():
    """A partial refresh must not be able to pass by moving one row.

    ``raw.companyfacts`` is rewritten wholesale by a refresh run, so its age is
    the age of the stalest payload still carried -- MIN. Reading MAX instead let
    a 2-of-7,066 refresh report the source as fresh while 7,064 snapshots were a
    week old, which is the failure the metric exists to catch, reintroduced
    through the fix.
    """
    spec = FRESHNESS_SOURCES["raw.companyfacts"]
    assert spec["aggregate"] == "MIN"
    assert str(_freshness_query("raw.companyfacts", spec)) == (
        "SELECT MIN(retrieved_at) FROM raw.companyfacts"
    )


def test_append_style_sources_are_still_aged_by_their_newest_row():
    """The other sources re-fetch a moving lookback window, so MAX is the only
    meaningful reading for them: an out-of-window row that was never meant to be
    re-fetched is not staleness."""
    for source, spec in FRESHNESS_SOURCES.items():
        if source == "raw.companyfacts":
            continue
        assert spec["aggregate"] == "MAX", source
        query = str(_freshness_query(source, spec))
        assert f"MAX({spec['column']}) FROM {source}" in query, source


def test_contract_terms_is_aged_by_the_latest_mine_with_the_daily_bound():
    """The miner re-persists every term-bearing security each run, so the newest
    updated_at is the last successful mine -- the freshness of the table the view
    and screener read."""
    spec = FRESHNESS_SOURCES["preferred.contract_terms"]
    assert spec["column"] == "updated_at"
    assert spec["aggregate"] == "MAX"
    assert spec["sla_hours"] == POC_DAILY_BOUND_HOURS
    assert str(_freshness_query("preferred.contract_terms", spec)) == (
        "SELECT MAX(updated_at) FROM preferred.contract_terms"
    )


def test_the_document_cache_is_not_a_freshness_source():
    """raw.contract_documents is a cache written with ON CONFLICT DO NOTHING, so
    its retrieved_at only moves on a new fetch. Aging it would breach on a
    healthy nightly that had nothing new to fetch."""
    assert "raw.contract_documents" not in FRESHNESS_SOURCES


def test_nightly_refreshes_the_preferred_set_on_a_tighter_cadence():
    """The preferred half is the priority: it runs first and refreshes more often.

    Both halves are still required -- the freshness check ages raw.companyfacts by
    its oldest row, so a population that is never refreshed pins the whole source
    to a permanent breach. The ordering and the split cadence are what make the
    priority real when a nightly is cut short by its timeout, or by a WSL2 host
    that suspends mid-run.
    """
    args = _companyfacts_stage_args([], stage="scripts.populate_companyfacts.preferred")
    assert "--preferred-facts" in args
    assert args[args.index("--refresh-after-days") + 1] == "3"


def test_preferred_runs_before_the_dividend_universe():
    """On a cut-short nightly the priority population must already be done.

    Order is read from the flag in each call's argv, since all three stages share
    one module name and position in the call sequence is the thing under test.
    """
    order = []

    def _fake_run(name, args, skip=False):
        if name == _STAGE_MODULE:
            for label, marker in _STAGE_MARKER.items():
                if marker in args:
                    order.append(label)
                    break
            else:
                order.append("scripts.populate_companyfacts.dividend")
        return True

    with (
        patch.object(run_full_etl, "run_module", side_effect=_fake_run),
        patch.object(run_full_etl, "record_nightly_run"),
        patch.object(sys, "argv", ["run_full_etl"]),
        _free_lock(),
    ):
        assert run_full_etl.main() == 0

    assert order == [
        "scripts.populate_companyfacts.preferred",
        "scripts.populate_companyfacts.dividend",
        "scripts.populate_companyfacts.unlinked",
    ], order


def test_nightly_also_sweeps_the_ciks_in_neither_universe():
    """A third population is reachable from neither universe sweep.

    2,896 of 7,066 stored CIKs belong to neither the dividend nor the preferred
    universe. Both sweeps walk a security universe, so without this stage their
    ``retrieved_at`` stays at first sighting forever and ``MIN`` pins the source to
    a permanent breach on rows no stage log ever mentions.
    """
    args = _companyfacts_stage_args([], stage="scripts.populate_companyfacts.unlinked")
    assert "--sweep-unlinked" in args
    assert args[args.index("--refresh-after-days") + 1] == "5"


@pytest.mark.parametrize(
    "flag,stage",
    [
        ("--skip-preferred-companyfacts", "scripts.populate_companyfacts.preferred"),
        ("--skip-unlinked-companyfacts", "scripts.populate_companyfacts.unlinked"),
    ],
)
def test_each_companyfacts_stage_can_be_skipped_explicitly(flag, stage):
    """Each population needs its own skip flag, and the audit row must say which.

    The status is checked by audit label rather than by module: all three stages
    run the same module, so keying on it would make the three indistinguishable
    and would hide a flag that silently stopped working.
    """
    recorded = _recorded_stages([flag])
    assert stage in recorded, f"label {stage!r} missing from {sorted(recorded)}"
    assert recorded[stage] == "skipped", recorded[stage]


def test_the_companyfacts_cadence_leaves_room_to_miss_a_nightly():
    """Cadence and bound must leave room for missed nightlies, not merely coexist.

    They are set in different modules -- the bound in ``FRESHNESS_SOURCES``, the
    cadence as a ``run_full_etl`` default -- so nothing else connects them and
    nothing stops either being edited without the other. A cadence equal to the
    bound satisfies "cadence <= bound" and is useless: the source breaches the
    moment one nightly does not run.

    The tolerance is ``bound - cadence`` in days, because the age at check time is
    ``cadence + (days missed)``. At 5d cadence against an 8d bound that is 3
    consecutive missed nightlies -- enough for a laptop lid left shut over a
    weekend, and exactly nothing more. Cadence 7 would cut it to 1, which is why
    the default is not 7.
    """
    sla_days = FRESHNESS_SOURCES["raw.companyfacts"]["sla_hours"] / 24.0
    for flag, stage, expected in (
        ("--preferred-companyfacts-refresh-after-days", "preferred", 3),
        ("--companyfacts-refresh-after-days", "", 5),
        ("--companyfacts-refresh-after-days", "unlinked", 5),
    ):
        full = "scripts.populate_companyfacts" + (f".{stage}" if stage else "")
        argv = _companyfacts_stage_args([flag, str(expected)], stage=full)
        cadence = int(argv[argv.index("--refresh-after-days") + 1])
        assert cadence == expected, flag

        misses_tolerated = sla_days - cadence
        assert misses_tolerated >= 2, (
            f"{flag}: a {cadence}d cadence against a {sla_days}d bound tolerates "
            f"{misses_tolerated} missed nightly(ies); two is the minimum, because "
            f"on a host that sleeps a missed run is normal, not exceptional"
        )


def test_every_stage_module_actually_exists():
    """Each stage must name a module ``python -m`` can resolve.

    Mocking ``run_module`` is what allowed ``scripts.populate_companyfacts.preferred``
    and ``.unlinked`` to reach production: a dotted pseudo-module is not importable,
    so the real subprocess died with ModuleNotFoundError and the nightly failed at
    stage 4a -- after two stages had already done real work. Every other test here
    mocks the call, so none of them could see it.

    The stage label and the module are now separate arguments; this asserts the
    module half is a real, importable module, so a label can never leak back into
    the subprocess call.
    """
    calls = []

    def _fake_run(name, args, skip=False):
        calls.append(name)
        return True

    with (
        patch.object(run_full_etl, "run_module", side_effect=_fake_run),
        patch.object(run_full_etl, "record_nightly_run"),
        patch.object(sys, "argv", ["run_full_etl", "--all"]),
        _free_lock(),
    ):
        assert run_full_etl.main() == 0

    assert calls, "expected the orchestrator to run at least one stage"
    for name in calls:
        # find_spec raises ModuleNotFoundError rather than returning None for a
        # dotted name whose parent is a module, which is the case that bit us.
        assert importlib.util.find_spec(name) is not None, (
            f"stage {name!r} is not an importable module; `python -m {name}` "
            f"would fail. Use a real module plus a distinct audit label."
        )


def test_poc_bounds_are_looser_than_the_refresh_cadences():
    """Every bound must tolerate missed runs, and the PoC bounds must be labelled.

    ``POC_DAILY_BOUND_HOURS`` is a placeholder, not a target. This pins the two
    properties that must survive any edit: each bound is strictly looser than the
    cadence it covers, so a healthy nightly never breaches its own check, and the
    constants exist so a revert is a single edit rather than a hunt.
    """
    daily_cadence_days = 1.0
    companyfacts_cadence_days = 5.0

    assert FRESHNESS_SOURCES["raw.companyfacts"]["sla_hours"] == POC_COMPANYFACTS_BOUND_HOURS
    assert POC_COMPANYFACTS_BOUND_HOURS > companyfacts_cadence_days * 24
    for source, spec in FRESHNESS_SOURCES.items():
        if source == "raw.companyfacts":
            continue
        assert spec["sla_hours"] > daily_cadence_days * 24, source
        assert spec["sla_hours"] == POC_DAILY_BOUND_HOURS, source

    # A daily cadence on a 10-day bound tolerates a long stretch of missed runs.
    assert POC_DAILY_BOUND_HOURS / 24 - daily_cadence_days >= 3


#: Adjacent to -- and distinct from -- ``PIPELINE_LOCK_KEY``, so the two tests
#: below can take a real lock while the nightly holds the production one. Advisory
#: locks are cluster-wide, so a separate schema or a separate database on the same
#: server would share the namespace and still collide; only the key separates them.
_TEST_LOCK_KEY = 4_713_155_002


def _live_connection():
    """Return the engine if a database is reachable, else ``None`` to skip on."""
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return engine
    except Exception:  # pragma: no cover - environments without a database
        return None


def test_second_concurrent_run_is_refused_not_silently_stacked(monkeypatch):
    """A second writer against the same tables must fail loudly.

    The nightly's one real concurrency exposure was a hand-started run overlapping
    the timer-driven one, not the timer overlapping itself -- systemd will not
    start a second instance of a unit it already has active. Without the advisory
    lock, both wrote to the same tables and the run still reported success.

    Unlike every other test in this file, this one needs a real database:
    advisory locks are re-entrant within a session, so the second acquire only
    fails because ``engine.connect()`` opens a second one. Stubbing that away
    would test the stub, so this runs live and skips where there is no database.
    """
    assert run_full_etl.PIPELINE_LOCK_KEY == 4_713_155_001
    if _live_connection() is None:
        pytest.skip("no database available")

    monkeypatch.setattr(run_full_etl, "PIPELINE_LOCK_KEY", _TEST_LOCK_KEY)

    held = run_full_etl._acquire_run_lock()
    try:
        with pytest.raises(run_full_etl.PipelineAlreadyRunning):
            run_full_etl._acquire_run_lock()
    finally:
        run_full_etl._release_run_lock(held)

    # The lock must actually be released, or the next nightly would be a no-op.
    reacquired = run_full_etl._acquire_run_lock()
    run_full_etl._release_run_lock(reacquired)


def test_lock_is_released_even_when_a_stage_explodes(monkeypatch):
    """A crashed run must not wedge every future run behind a dead lock."""
    if _live_connection() is None:
        pytest.skip("no database available")

    monkeypatch.setattr(run_full_etl, "PIPELINE_LOCK_KEY", _TEST_LOCK_KEY)

    held = run_full_etl._acquire_run_lock()
    try:
        with pytest.raises(RuntimeError):
            try:
                raise RuntimeError("stage blew up")
            finally:
                run_full_etl._release_run_lock(held)
    except run_full_etl.PipelineAlreadyRunning:
        pytest.fail("lock was not released after the run failed")
    reacquired = run_full_etl._acquire_run_lock()
    run_full_etl._release_run_lock(reacquired)


def test_conflicting_run_exits_2_without_running_any_stage():
    """Exit 2 distinguishes 'refused, nothing happened' from 'ran and failed'."""
    argv = ["run_full_etl", "--limit", "1"]
    with (
        patch.object(sys, "argv", argv),
        patch.object(
            run_full_etl,
            "_acquire_run_lock",
            side_effect=run_full_etl.PipelineAlreadyRunning("busy"),
        ),
        patch.object(run_full_etl.subprocess, "run") as run_subprocess,
        patch.object(run_full_etl, "record_nightly_run") as record,
    ):
        assert run_full_etl.main() == 2
    run_subprocess.assert_not_called()
    record.assert_not_called()


def test_nightly_runs_the_schema_preflight_before_anything_else():
    """The preflight has to come first, or it is not a preflight.

    A stage that reads a column the database does not have fails at execution --
    hours in, with the rows it did manage to write already committed. Checking
    the schema after the network stages would catch the same pending migration
    far too late to save the run.
    """
    recorded = _recorded_stages([])
    assert "scripts.migrate --check" in recorded
    assert recorded["scripts.migrate --check"] == "ok"

    order = list(recorded)
    assert order[0] == "scripts.migrate --check"


def test_nightly_reaches_the_score():
    """The regression that emptied the dashboard.

    `run_full_etl` had no `build_features` or `score_rank` stage, so the nightly
    refreshed prices and dividends and stopped. `model.scores` stayed empty and
    the app's Median Score read N/A while every nightly was recorded as a
    success. Both stages are asserted by name, and the audit snapshot is
    asserted to come after them so it records the scores just written.
    """
    recorded = _recorded_stages([])
    assert recorded.get("scripts.build_features") == "ok"
    assert recorded.get("scripts.score_rank") == "ok"

    order = list(recorded)
    assert order.index("scripts.build_features") < order.index("scripts.score_rank")
    assert order.index("scripts.score_rank") < order.index("scripts.populate_audit")


def test_nightly_rebuilds_clean_profile_after_profile_writers():
    recorded = _recorded_stages([])
    assert recorded.get("scripts.populate_clean_ticker_profile") == "ok"
    assert recorded.get("scripts.populate_clean_company_profile") == "ok"

    order = list(recorded)
    assert order.index("scripts.populate_dividend_data") < order.index(
        "scripts.populate_clean_ticker_profile"
    )
    assert order.index("scripts.populate_clean_ticker_profile") < order.index(
        "scripts.populate_clean_company_profile"
    )
    assert order.index("scripts.populate_clean_company_profile") < order.index(
        "scripts.populate_companyfacts.preferred"
    )


def test_the_nightly_feature_rebuild_exceeds_the_price_lookback():
    """`--feature-days` has to clear 252 trading days or the features degrade.

    `volatility_252d` and `momentum_252d` are computed from a trailing window
    that reaches back before the rebuild start. A window shorter than the
    lookback silently drops both columns to NULL for the first rows of every
    rebuild, which looks like a coverage regression rather than a bad argument.
    """
    with (
        patch.object(run_full_etl, "run_module", return_value=True) as run,
        patch.object(run_full_etl, "record_nightly_run"),
        patch.object(sys, "argv", ["run_full_etl"]),
        _free_lock(),
    ):
        assert run_full_etl.main() == 0

    extra = next(
        call.args[1]
        for call in run.call_args_list
        if call.args and call.args[0] == "scripts.build_features"
    )
    days = int(extra[extra.index("--days") + 1])
    assert days > 252, f"--feature-days {days} is inside the 252-day price lookback"


def test_skip_derived_also_skips_the_preflight():
    """Deliberate, and worth pinning.

    `--skip-derived` is how a backfill is run without the derived stages, so
    skipping the preflight with it is consistent. The trade is that a backfill
    can then run against a schema the code does not expect -- which is why the
    default nightly does not skip either.
    """
    recorded = _recorded_stages(["--skip-derived"])
    for stage in ("scripts.build_features", "scripts.score_rank", "scripts.migrate --check"):
        assert recorded[stage] == "skipped"


def test_a_failing_stage_stops_the_ones_that_depend_on_it():
    """Short-circuiting is the point of the ordering.

    Scoring features that were never built would write a fresh empty score set
    over a good one. `all_ok` gates each stage on every stage before it, so a
    fundamentals failure must prevent build_features and score_rank from running.
    """

    def _fail_on_fundamentals(module, extra, skip=False):
        return module != "scripts.populate_fundamentals"

    recorded = {}
    with (
        patch.object(run_full_etl, "run_module", side_effect=_fail_on_fundamentals),
        patch.object(
            run_full_etl,
            "record_nightly_run",
            side_effect=lambda trigger, started_at, stages, exit_code: recorded.update(stages),
        ),
        patch.object(sys, "argv", ["run_full_etl"]),
        _free_lock(),
    ):
        assert run_full_etl.main() == 1

    assert recorded["scripts.populate_fundamentals"] == "failed"
    # Short-circuit: the dependent stages are never invoked, so they are absent
    # from the audit record rather than marked skipped. Either way they did not
    # run, and the run exited non-zero.
    assert "scripts.build_features" not in recorded
    assert "scripts.score_rank" not in recorded
    assert "scripts.populate_audit" not in recorded
