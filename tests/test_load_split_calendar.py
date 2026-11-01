import pandas as pd

from scripts.load_corporate_actions import split_rows
from scripts.load_split_calendar import UPSERT, calendar_split_rows

SECURITIES = pd.DataFrame({"security_id": ["id-1", "id-2"], "ticker": ["AAPL", "WHLR"]})


def _event(symbol, date="2026-12-02", numerator=2, denominator=1):
    return {"symbol": symbol, "date": date, "numerator": numerator, "denominator": denominator}


def test_untracked_tickers_are_skipped_unlike_the_full_loader():
    rows = calendar_split_rows([_event("AAPL"), _event("ZZZZF")], SECURITIES)

    assert [r["ticker"] for r in rows] == ["AAPL"]
    assert rows[0]["security_id"] == "id-1" and rows[0]["ratio"] == 0.5


def test_calendar_rows_hash_the_same_as_the_full_loader_so_they_do_not_duplicate():
    full = split_rows(
        pd.DataFrame([{"ticker": "AAPL", "date": "2026-12-02", "numerator": 2, "denominator": 1}]),
        SECURITIES,
    )
    calendar = calendar_split_rows([_event("AAPL")], SECURITIES)

    assert [r["source_hash"] for r in full] == [r["source_hash"] for r in calendar]


def test_malformed_events_are_dropped_and_an_empty_feed_is_fine():
    events = [_event("AAPL", numerator=None), _event("AAPL", date=""), _event("AAPL", numerator=0)]

    assert calendar_split_rows(events, SECURITIES) == []
    assert calendar_split_rows([], SECURITIES) == []


def test_a_row_seen_again_refreshes_retrieved_at_instead_of_being_ignored():
    sql = " ".join(str(UPSERT).split())

    assert "ON CONFLICT (source_hash) DO UPDATE SET retrieved_at = now()" in sql
    assert "DO NOTHING" not in sql
