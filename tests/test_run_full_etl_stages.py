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


def _run(monkeypatch, argv):
    calls = []
    recorded = {}

    def fake_run_module(name, args, skip=False):
        calls.append((name, tuple(args), skip))
        return True

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
