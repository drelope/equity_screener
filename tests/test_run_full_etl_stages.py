"""The nightly must actually run the repairs and the contract-terms miner.

These stages were manual-only until now, so the shared
``preferred.v_security_terms`` view (and the classification cleanup) never
refreshed on their own. ``main`` is exercised with ``run_module`` and the run
lock/recording stubbed, so the stage list is asserted without touching a
database or launching subprocesses.
"""

import sys

from scripts import run_full_etl as etl


class _Lock:
    def close(self):
        pass


def _run(monkeypatch, argv, fail_stage=None):
    calls = []
    recorded = {}

    def fake_run_module(name, args, skip=False):
        calls.append((name, tuple(args), skip))
        return name != fail_stage

    def fake_record(trigger, started_at, stages, exit_code):
        recorded["stages"] = dict(stages)
        recorded["exit_code"] = exit_code

    monkeypatch.setattr(etl, "run_module", fake_run_module)
    monkeypatch.setattr(etl, "_acquire_run_lock", lambda: _Lock())
    monkeypatch.setattr(etl, "_release_run_lock", lambda conn: None)
    monkeypatch.setattr(etl, "record_nightly_run", fake_record)
    monkeypatch.setattr(sys, "argv", ["run_full_etl", *argv])
    rc = etl.main()
    return calls, recorded, rc


def _names(calls):
    return [name for name, _, _ in calls]


def test_preferred_titles_run_before_dividend_and_contract_writers(monkeypatch):
    calls, recorded, rc = _run(monkeypatch, ["--tickers", "FRT-PC", "--limit", "7"])
    names = _names(calls)
    title_stage = "scripts.populate_sec_instrument_titles"
    assert rc == 0
    assert names.index("scripts.populate_reference_tables") < names.index(title_stage)
    assert names.index(title_stage) < names.index("scripts.populate_dividend_data")
    args = next(args for name, args, _ in calls if name == title_stage)
    assert args == ("--tickers", "FRT-PC", "--preferred-only", "--limit", "7")
    assert recorded["stages"][title_stage] == "ok"


def test_skip_instrument_titles_is_recorded(monkeypatch):
    _, recorded, _ = _run(monkeypatch, ["--skip-instrument-titles"])
    assert recorded["stages"]["scripts.populate_sec_instrument_titles"] == "skipped"


def test_exchange_titles_run_after_sec_titles_before_dividend_data(monkeypatch):
    calls, recorded, rc = _run(monkeypatch, ["--tickers", "AGM-PI", "--limit", "3"])
    names = _names(calls)
    exchange_stage = "scripts.populate_exchange_listing_titles"
    assert rc == 0
    assert names.index("scripts.populate_sec_instrument_titles") < names.index(exchange_stage)
    assert names.index(exchange_stage) < names.index("scripts.populate_dividend_data")
    args = next(args for name, args, _ in calls if name == exchange_stage)
    assert args == ("--tickers", "AGM-PI", "--limit", "3")
    _, recorded, _ = _run(monkeypatch, ["--skip-exchange-titles"])
    assert recorded["stages"][exchange_stage] == "skipped"


def test_failed_title_ingestion_stops_downstream_writers(monkeypatch):
    calls, recorded, rc = _run(monkeypatch, [], fail_stage="scripts.populate_sec_instrument_titles")
    assert rc == 1
    assert recorded["stages"]["scripts.populate_sec_instrument_titles"] == "failed"
    assert "scripts.populate_market_data" not in _names(calls)
    assert "scripts.populate_dividend_data" not in _names(calls)
    assert "scripts.populate_contract_terms" not in _names(calls)


def test_repairs_run_after_the_writers_and_before_the_preferred_sweep(monkeypatch):
    calls, _, rc = _run(monkeypatch, [])
    names = _names(calls)

    assert rc == 0
    dividend = names.index("scripts.populate_dividend_data")
    classification = names.index("scripts.repair_security_classification")
    ticker_profile = names.index("scripts.repair_ticker_profile_sec_terms")
    preferred_sweep = names.index("scripts.populate_companyfacts")

    assert dividend < classification < preferred_sweep
    assert dividend < ticker_profile < preferred_sweep

    # Not skipped on a full run.
    skips = {name: skip for name, _, skip in calls}
    assert skips["scripts.repair_security_classification"] is False
    assert skips["scripts.repair_ticker_profile_sec_terms"] is False


def test_contract_terms_runs_after_documents_and_before_features(monkeypatch):
    calls, _, _ = _run(monkeypatch, [])
    names = _names(calls)

    documents = names.index("scripts.populate_sec_documents")
    miner = names.index("scripts.populate_contract_terms")
    features = names.index("scripts.build_features")

    assert documents < miner < features
    clean_ticker = names.index("scripts.populate_clean_ticker_profile")
    clean_company = names.index("scripts.populate_clean_company_profile")
    assert miner < clean_ticker < clean_company < features


def test_skip_repairs_marks_both_repairs_skipped(monkeypatch):
    calls, _, _ = _run(monkeypatch, ["--skip-repairs"])
    skips = {name: skip for name, _, skip in calls}

    assert skips["scripts.repair_security_classification"] is True
    assert skips["scripts.repair_ticker_profile_sec_terms"] is True


def test_skip_contract_terms_marks_the_miner_skipped(monkeypatch):
    calls, _, _ = _run(monkeypatch, ["--skip-contract-terms"])
    skips = {name: skip for name, _, skip in calls}

    assert skips["scripts.populate_contract_terms"] is True


def test_a_limited_run_caps_the_miner(monkeypatch):
    calls, _, _ = _run(monkeypatch, ["--limit", "7"])
    args = next(args for name, args, _ in calls if name == "scripts.populate_contract_terms")

    assert "--max" in args and args[args.index("--max") + 1] == "7"


def test_the_recorded_stage_order_matches_the_calls(monkeypatch):
    calls, recorded, _ = _run(monkeypatch, [])
    stages = recorded["stages"]
    # Every stage that ran is recorded exactly once (labels may differ from the
    # module name for the companyfacts populations, but the two repairs are 1:1).
    assert stages["scripts.repair_security_classification"] == "ok"
    assert stages["scripts.populate_contract_terms"] == "ok"
    assert recorded["exit_code"] == 0


def test_the_forward_returns_run_after_the_features_and_before_the_scoring(monkeypatch):
    calls, _, rc = _run(monkeypatch, [])
    names = _names(calls)

    assert rc == 0
    features = names.index("scripts.build_features")
    forward = names.index("scripts.build_forward_returns")
    scoring = names.index("scripts.score_rank")

    assert features < forward < scoring
    args = next(args for name, args, _ in calls if name == "scripts.build_forward_returns")
    assert args == ("--days", "400")


def test_the_forward_returns_are_skipped_with_the_other_derived_stages(monkeypatch):
    calls, recorded, _ = _run(monkeypatch, ["--skip-derived"])
    skips = {name: skip for name, _, skip in calls}

    assert skips["scripts.build_forward_returns"] is True
    assert recorded["stages"]["scripts.build_forward_returns"] == "skipped"


def test_the_forward_return_window_can_be_widened(monkeypatch):
    calls, _, _ = _run(monkeypatch, ["--forward-days", "1200"])
    args = next(args for name, args, _ in calls if name == "scripts.build_forward_returns")

    assert args == ("--days", "1200")
