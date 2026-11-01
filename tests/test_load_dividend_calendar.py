from datetime import date

from scripts.load_dividend_calendar import calendar_rows, windows

TICKERS = {"AAPL": "id-aapl", "KO": "id-ko"}


def test_windows_cover_the_range_without_gaps_or_overlap():
    got = windows(date(2026, 1, 1), date(2026, 7, 1), days=90)

    assert got[0][0] == date(2026, 1, 1) and got[-1][1] == date(2026, 7, 1)
    for (_, prev_end), (next_start, _) in zip(got, got[1:], strict=False):
        assert (next_start - prev_end).days == 1
    assert all((end - start).days < 90 for start, end in got)


def test_only_active_tickers_with_an_ex_date_become_rows():
    events = [
        {"symbol": "AAPL", "date": "2026-11-10", "dividend": 0.26, "frequency": "Quarterly"},
        {"symbol": "ZZZ", "date": "2026-11-10", "dividend": 1},
        {"symbol": "KO", "date": "", "dividend": 0.5},
    ]

    rows = calendar_rows(events, TICKERS)

    assert [r["security_id"] for r in rows] == ["id-aapl"]
    assert rows[0]["amount"] == 0.26


def test_blank_dates_and_numbers_become_none():
    row = calendar_rows(
        [
            {
                "symbol": "KO",
                "date": "2026-11-10",
                "recordDate": "",
                "paymentDate": "",
                "dividend": "",
            }
        ],
        TICKERS,
    )[0]

    assert row["record_date"] is None and row["payment_date"] is None and row["amount"] is None


def test_special_is_flagged_only_from_an_explicit_special_frequency():
    events = [
        {"symbol": "AAPL", "date": "2026-11-10", "frequency": "Special"},
        {"symbol": "KO", "date": "2026-11-10", "frequency": "Irregular"},
    ]

    flags = {r["security_id"]: r["is_special"] for r in calendar_rows(events, TICKERS)}

    assert flags == {"id-aapl": True, "id-ko": False}


def test_a_repeated_event_collapses_to_one_row():
    event = {"symbol": "KO", "date": "2026-11-10", "dividend": 0.5}

    assert len(calendar_rows([event, event], TICKERS)) == 1


def test_a_reloaded_row_keeps_first_seen_and_only_moves_last_changed_when_it_changed():
    from scripts.load_dividend_calendar import UPSERT

    sql = " ".join(str(UPSERT).split())

    assert "first_seen_at" not in sql  # set once by the column default, never updated
    assert "last_changed_at = CASE" in sql
    assert "IS DISTINCT FROM" in sql and "ELSE raw.dividend_calendar.last_changed_at" in sql
