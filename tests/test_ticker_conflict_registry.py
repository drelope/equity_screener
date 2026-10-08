"""The ticker-conflict registry SQL against the real table, and the morning check that reads it.

Everything runs in a transaction that is rolled back, so the live registry is untouched.
"""

from datetime import date

import pytest
from sqlalchemy import text

from scripts import populate_raw_tables as prt
from scripts import verify_nightly_run as verify


def _live_engine():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1 FROM audit.quarantined_values LIMIT 1")
        return engine
    except Exception:  # pragma: no cover - no database
        return None


pytestmark = pytest.mark.skipif(_live_engine() is None, reason="no live database")


def conflict(ticker, incoming="0002148436", existing="0001865200"):
    return {
        "ticker": ticker,
        "incoming_cik": incoming,
        "incoming_issuer": "Southport Acquisition Corp. II",
        "existing_cik": existing,
        "existing_issuer": "Angel Studios, Inc.",
        "referencing_securities": 1,
    }


@pytest.fixture
def conn():
    with _live_engine().connect() as connection:
        outer = connection.begin()
        try:
            yield connection
        finally:
            outer.rollback()


def rows(conn, *tickers):
    result = conn.execute(
        text("""
        SELECT row_key, observed_value, cik, resolved_at, resolution_note, detected_at, rule
        FROM audit.quarantined_values
        WHERE table_schema = 'raw' AND table_name = 'company_ticker' AND row_key = ANY(:t)
        ORDER BY row_key, observed_value
    """),
        {"t": list(tickers)},
    )
    return [dict(r) for r in result.mappings()]


def test_a_conflict_is_registered_open_with_both_ciks(conn):
    prt.record_ticker_conflicts(conn, [conflict("0TEST-UN")], sweep=False)

    (row,) = rows(conn, "0TEST-UN")
    assert row["resolved_at"] is None and row["rule"] == "TICKER_CIK_CONFLICT"
    assert (row["cik"], row["observed_value"]) == ("0001865200", "0002148436")


def test_recording_the_same_open_conflict_again_changes_nothing(conn):
    prt.record_ticker_conflicts(conn, [conflict("0TEST-UN")], sweep=False)
    conn.execute(
        text(
            "UPDATE audit.quarantined_values SET detected_at = now() - interval '3 days' "
            "WHERE row_key = '0TEST-UN'"
        )
    )
    (before,) = rows(conn, "0TEST-UN")

    prt.record_ticker_conflicts(conn, [conflict("0TEST-UN")], sweep=False)

    (after,) = rows(conn, "0TEST-UN")
    assert after["detected_at"] == before["detected_at"], "first-detected time must survive"


def test_a_resolved_conflict_that_returns_is_reopened(conn):
    prt.record_ticker_conflicts(conn, [conflict("0TEST-UN")], sweep=False)
    conn.execute(
        text(
            "UPDATE audit.quarantined_values SET resolved_at = now(), resolution_note = 'released' "
            "WHERE row_key = '0TEST-UN'"
        )
    )

    prt.record_ticker_conflicts(conn, [conflict("0TEST-UN")], sweep=False)

    (row,) = rows(conn, "0TEST-UN")
    assert row["resolved_at"] is None and row["resolution_note"] is None


def test_a_full_snapshot_closes_only_the_conflicts_it_no_longer_reports(conn):
    prt.record_ticker_conflicts(conn, [conflict("0TEST-A"), conflict("0TEST-B")], sweep=False)

    prt.record_ticker_conflicts(conn, [conflict("0TEST-A")], sweep=True)

    still, gone = rows(conn, "0TEST-A", "0TEST-B")
    assert still["resolved_at"] is None
    assert gone["resolved_at"] is not None and "no longer reported" in gone["resolution_note"]


def test_the_same_ticker_under_another_incoming_cik_is_a_separate_conflict(conn):
    prt.record_ticker_conflicts(
        conn,
        [conflict("0TEST-A", incoming="0000000001"), conflict("0TEST-A", incoming="0000000002")],
        sweep=False,
    )

    prt.record_ticker_conflicts(conn, [conflict("0TEST-A", incoming="0000000002")], sweep=True)

    first, second = rows(conn, "0TEST-A")
    assert (first["observed_value"], first["resolved_at"] is not None) == ("0000000001", True)
    assert (second["observed_value"], second["resolved_at"] is None) == ("0000000002", True)


def test_a_clean_full_snapshot_closes_everything_open(conn):
    prt.record_ticker_conflicts(conn, [conflict("0TEST-A")], sweep=False)

    prt.record_ticker_conflicts(conn, [], sweep=True)

    (row,) = rows(conn, "0TEST-A")
    assert row["resolved_at"] is not None


def test_a_released_reference_row_is_not_touched_by_the_sweep(conn):
    conn.execute(
        text("""
        INSERT INTO audit.quarantined_values
            (table_schema, table_name, column_name, row_key, ticker, observed_value, reason, rule,
             resolved_at, resolution_note)
        VALUES ('reference', 'securities', 'ticker', '0TEST-REL', '0TEST-REL', '0TEST-REL', 'x',
                'TICKER_CIK_CONFLICT', now() - interval '1 day', 'released')
    """)
    )

    prt.record_ticker_conflicts(conn, [], sweep=True)

    note = conn.execute(
        text("SELECT resolution_note FROM audit.quarantined_values WHERE row_key = '0TEST-REL'")
    ).scalar()
    assert note == "released"


def test_the_morning_check_reports_an_open_conflict_and_clears_when_closed(conn):
    prt.record_ticker_conflicts(conn, [conflict("0TEST-UN")], sweep=False)

    findings = verify.fetch_findings(conn, date.today(), date(2025, 1, 1))
    assert findings["ticker_conflicts"]["open"] >= 1
    assert "0TEST-UN" in findings["ticker_conflicts"]["tickers"]

    result = verify.assess(
        findings, min_quality_score=0.5, min_good_share=0.8, min_coverage=0.95, max_age_hours=26
    )
    check = next(c for c in result["checks"] if c["name"] == "ticker_conflicts")
    assert check["status"] == "attention" and "0TEST-UN" in check["detail"]

    prt.record_ticker_conflicts(conn, [], sweep=True)
    closed = verify.fetch_findings(conn, date.today(), date(2025, 1, 1))
    assert "0TEST-UN" not in closed["ticker_conflicts"]["tickers"]
