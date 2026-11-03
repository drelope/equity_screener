from datetime import datetime

from scripts.load_cover_titles_all import parse_deadline, run

NOW = datetime(2026, 11, 1, 18, 0)


def test_the_deadline_is_today_at_the_given_local_time():
    assert parse_deadline("23:30", NOW) == datetime(2026, 11, 1, 23, 30)
    assert parse_deadline(None, NOW) is None


def _loader(results):
    calls = []

    def load(cik):
        calls.append(cik)
        outcome = results[cik]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    load.calls = calls
    return load


def test_each_issuer_is_loaded_separately_and_counted():
    load = _loader({"1": (1, 3, 0, 0), "2": (1, 0, 1, 0), "3": (1, 2, 0, 0)})

    totals = run(["1", "2", "3"], load=load, report_every=1000)

    assert load.calls == ["1", "2", "3"]
    assert totals["titled"] == 2 and totals["no_titles"] == 1 and totals["errors"] == 0


def test_one_failing_issuer_does_not_stop_the_rest():
    load = _loader({"1": RuntimeError("boom"), "2": (1, 1, 0, 0)})

    totals = run(["1", "2"], load=load, report_every=1000)

    assert totals["errors"] == 1 and totals["titled"] == 1 and load.calls == ["1", "2"]


def test_the_run_stops_cleanly_at_the_deadline_without_loading_more():
    load = _loader({"1": (1, 1, 0, 0), "2": (1, 1, 0, 0), "3": (1, 1, 0, 0)})
    times = iter(
        [datetime(2026, 11, 1, 23, 0), datetime(2026, 11, 1, 23, 31), datetime(2026, 11, 1, 23, 40)]
    )

    totals = run(
        ["1", "2", "3"],
        deadline=datetime(2026, 11, 1, 23, 30),
        load=load,
        report_every=1000,
        clock=lambda: next(times),
    )

    assert load.calls == ["1"] and totals["stopped_at_deadline"] is True


def test_errors_reported_by_the_stage_are_added_to_the_total():
    load = _loader({"1": (1, 0, 1, 2)})

    assert run(["1"], load=load, report_every=1000)["errors"] == 2
