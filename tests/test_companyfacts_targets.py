from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from scripts import populate_companyfacts


class _Result:
    def mappings(self):
        return self

    def all(self):
        return []


class _Connection:
    def execute(self, *_args, **_kwargs):
        return _Result()


class _CursorConn:
    """Connection whose execute yields the given 1-tuples for any statement."""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_args, **_kwargs):
        return iter(self.rows)


def test_existing_facts_ciks_collects_persisted_ciks():
    conn = _CursorConn([("0001332551", None), ("0000948320", None)])
    assert populate_companyfacts.existing_facts_ciks(conn) == {
        "0001332551",
        "0000948320",
    }


NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
ENTRIES = {"0000000001": [], "0000000002": [], "0000000003": []}


def test_stored_facts_retrieved_at_keeps_the_retrieval_clock():
    stored = populate_companyfacts.stored_facts_retrieved_at(
        _CursorConn([("0000000001", NOW), (None, NOW)])
    )
    assert stored == {"0000000001": NOW}


def test_a_backfill_never_refetches_a_stored_cik():
    """The default is unchanged: a stored payload is skipped, not re-requested."""
    stored = {"0000000001": NOW, "0000000002": NOW - timedelta(days=900)}
    pending, plan = populate_companyfacts.select_pending_ciks(
        ENTRIES, stored, refresh_after_days=None, now=NOW
    )
    assert pending == ["0000000003"]
    assert plan == {"new_ciks": 1, "refreshed": 0, "skipped": 2, "deferred": 0}


def test_refresh_after_days_refetches_only_what_is_stale():
    stored = {
        "0000000001": NOW,  # checked today
        "0000000002": NOW - timedelta(days=6, hours=23),  # just inside a 7-day cycle
        "0000000003": NOW - timedelta(days=400),  # long stale
    }
    pending, plan = populate_companyfacts.select_pending_ciks(
        ENTRIES, stored, refresh_after_days=7, now=NOW
    )
    assert pending == ["0000000003"]
    assert plan == {"new_ciks": 0, "refreshed": 1, "skipped": 2, "deferred": 0}


def test_refresh_rechecks_every_stored_cik():
    """``--refresh`` (``refresh_after_days=0``) must not read as a completed
    backfill, so the re-fetched count is reported separately from the skip."""
    stored = {"0000000001": NOW, "0000000002": NOW}
    pending, plan = populate_companyfacts.select_pending_ciks(
        ENTRIES, stored, refresh_after_days=0, now=NOW
    )
    assert pending == ["0000000001", "0000000002", "0000000003"]
    assert plan == {"new_ciks": 1, "refreshed": 2, "skipped": 0, "deferred": 0}


def test_stored_naive_timestamps_do_not_raise_against_an_aware_cutoff():
    """``retrieved_at`` can come back naive depending on the driver."""
    stored = {"0000000001": NOW.replace(tzinfo=None)}
    pending, plan = populate_companyfacts.select_pending_ciks(
        ENTRIES, stored, refresh_after_days=7, now=NOW
    )
    assert "0000000001" not in pending
    assert plan == {"new_ciks": 2, "refreshed": 0, "skipped": 1, "deferred": 0}


def test_a_naive_now_is_normalised_rather_than_crashing_the_subtraction():
    """A caller passing a naive ``now`` must not raise against an aware cutoff."""
    stored = {"0000000001": NOW, "0000000002": NOW - timedelta(days=400)}
    pending, plan = populate_companyfacts.select_pending_ciks(
        ENTRIES, stored, refresh_after_days=7, now=NOW.replace(tzinfo=None)
    )
    assert pending == ["0000000002", "0000000003"]
    assert plan["refreshed"] == 1


def test_a_truncated_batch_does_not_report_work_it_did_not_do():
    """``max_ciks`` bounds the fetches, so the counts must be bounded with them.

    Counting the refreshes before truncating reported ``refreshed=3`` for a run
    that fetched one CIK -- the stage looked like a full sweep of a 7,066-CIK
    backfill. The deferred remainder is reported as its own bucket instead.
    """
    stored = {c: NOW - timedelta(days=400) for c in ENTRIES}
    pending, plan = populate_companyfacts.select_pending_ciks(
        ENTRIES, stored, refresh_after_days=7, max_ciks=1, now=NOW
    )
    assert pending == ["0000000001"]
    assert plan == {"new_ciks": 0, "refreshed": 1, "skipped": 0, "deferred": 2}


def test_every_target_cik_lands_in_exactly_one_bucket():
    """The buckets must partition the targets, budgeted or not."""
    cases = [
        ({}, None, None),
        ({c: NOW for c in ENTRIES}, 7, None),
        ({c: NOW - timedelta(days=400) for c in ENTRIES}, 7, 1),
        ({"0000000001": NOW - timedelta(days=400)}, 7, None),
        ({"0000000001": NOW, "0000000003": NOW - timedelta(days=400)}, 0, 2),
    ]
    for stored, days, cap in cases:
        pending, plan = populate_companyfacts.select_pending_ciks(
            ENTRIES, stored, refresh_after_days=days, max_ciks=cap, now=NOW
        )
        assert len(pending) == plan["new_ciks"] + plan["refreshed"]
        assert len(ENTRIES) == len(pending) + plan["skipped"] + plan["deferred"]


def test_preferred_facts_skips_already_stored_ciks():
    class _ResumableConn:
        def __init__(self):
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def commit(self):
            self.commits += 1

        def execute(self, statement, _params=None):
            if "FROM raw.companyfacts" in str(statement):
                return iter([("0000000001", NOW)])

            class _Mappings:
                def __init__(self, rows):
                    self._rows = rows

                def mappings(self):
                    return self

                def all(self):
                    return self._rows

            return _Mappings(
                [
                    {
                        "cik": "0000000002",
                        "ticker": "BBB",
                        "title": "B Corp",
                        "security_id": "security-b",
                    },
                    {
                        "cik": "0000000001",
                        "ticker": "AAA",
                        "title": "A Corp",
                        "security_id": "security-a",
                    },
                ]
            ).mappings()

    conn = _ResumableConn()
    fetched = []

    def _fake_ingest(_conn, cik, _entries, _stats):
        fetched.append(cik)

    with (
        patch.object(populate_companyfacts, "engine") as engine,
        patch.object(populate_companyfacts, "_ingest_cik", side_effect=_fake_ingest),
    ):
        engine.connect.return_value = conn
        populate_companyfacts.populate_preferred_companyfacts()

    assert fetched == ["0000000002"]
    assert conn.commits == 1


def test_companyfacts_targets_include_preferred_profile_rows():
    audited = [{"ticker": "AAA", "security_id": "security-a"}]
    profile = [{"ticker": "PFD", "security_id": "security-pfd"}]

    with (
        patch.object(populate_companyfacts, "load_securities", return_value=audited),
        patch.object(populate_companyfacts, "load_ticker_profile_targets", return_value=profile),
    ):
        targets = populate_companyfacts.load_companyfacts_targets(_Connection())

    assert {row["ticker"] for row in targets} == {"AAA", "PFD"}


def _sec_entry(cik, ticker):
    return {"cik_str": cik, "ticker": ticker, "title": f"{ticker} Inc"}


def _run_populate(sec_tickers, wanted_tickers, max_ciks=0):
    """Run populate_companyfacts against stubbed SEC/targets; return final stats.

    ``max_ciks=0`` still performs the target/counter bookkeeping but fetches
    nothing, so the assertion is on planning rather than on network calls.
    """
    captured = {}

    def _capture(_conn, _cik, _entries, stats):
        captured["stats"] = dict(stats)

    with (
        patch.object(populate_companyfacts, "get_company_tickers", return_value=sec_tickers),
        patch.object(populate_companyfacts, "engine") as eng,
        patch.object(populate_companyfacts, "_ingest_cik", side_effect=_capture),
        patch.object(
            populate_companyfacts,
            "load_companyfacts_targets",
            return_value=[{"ticker": t, "cik": "0000000001", "title": t} for t in wanted_tickers],
        ),
        patch.object(populate_companyfacts, "stored_facts_retrieved_at", return_value={}),
    ):
        conn = eng.connect.return_value.__enter__.return_value
        conn.execute.return_value = _Result()
        populate_companyfacts.populate_companyfacts(max_ciks=max_ciks)
    return captured["stats"]


def test_missing_counts_wanted_securities_not_the_sec_ticker_universe():
    """``missing`` must mean "we wanted it and could not reach it".

    The counter used to increment for every SEC ticker outside our universe, so a
    run in which every dividend security mapped cleanly and nothing failed still
    printed ``missing_securities=5149`` -- the size of the non-dividend universe
    reported as if it were a fault. In a nightly log that is indistinguishable
    from data loss, and it would mask a genuine 5,143-security failure.
    """
    sec = {
        "1": _sec_entry("0000000001", "AAA"),
        # SEC also lists tickers we do not target; these must not be counted.
        "2": _sec_entry("0000000002", "ZZZ"),
        "3": _sec_entry("0000000003", "YYY"),
    }
    stats = _run_populate(sec, ["AAA", "BBB"])
    assert stats["missing"] == 1, stats  # only BBB, which SEC does not list


def test_missing_reports_securities_absent_from_the_sec_ticker_file():
    """A target SEC does not list can never gain a payload, so it must be counted."""
    sec = {"1": _sec_entry("0000000001", "AAA")}
    stats = _run_populate(sec, ["AAA", "GONE", "ALSOGONE"])
    assert stats["missing"] == 2, stats
