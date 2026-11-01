"""The successor re-key moves a security to a new CIK without losing its history.

The database tests build a synthetic security inside a transaction that is always rolled
back, so they exercise the real constraints (including the non-deferrable composite
foreign key the tool has to work around) and leave no data behind.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from scripts import rekey_security_successor as rk

TICKER, OLD, NEW = "ZZREK", "0009990001", "0009990002"
ENTRIES = [{"cik_str": 9990002, "ticker": TICKER, "title": "Successor Holdings, Inc."}]


def test_cik_is_zero_padded():
    assert rk.normalize_cik("2152623") == "0002152623"
    assert rk.normalize_cik(" 0002152623 ") == "0002152623"


def test_sec_entry_requires_the_ticker_to_be_listed_under_that_cik():
    entries = [{"cik_str": 2152623, "ticker": "NAVI", "title": "Navient Holdings, Inc."}]

    assert rk.sec_entry(entries, "NAVI", "0002152623")["title"] == "Navient Holdings, Inc."
    assert rk.sec_entry(entries, "NAVI", "0001593538") is None  # the old CIK is not listed
    assert rk.sec_entry(entries, "JSM", "0002152623") is None


def test_identifier_dates_are_contiguous_with_no_overlap_or_gap():
    old_to, new_from = rk.identifier_dates(date(2026, 10, 28))

    assert old_to == date(2026, 10, 27) and new_from == date(2026, 10, 28)
    assert (new_from - old_to).days == 1


def test_every_history_table_is_keyed_by_security_id():
    # the re-key promises these do not move, so each must be reachable by security_id
    assert "raw.market_data" in rk.HISTORY_TABLES
    assert "fundamentals.periodic_financials" in rk.HISTORY_TABLES
    assert "model.features" in rk.HISTORY_TABLES


def _connect():
    try:
        from src.crispdm.db import engine

        conn = engine.connect()
        conn.exec_driver_sql("SELECT 1")
        conn.rollback()
        return conn
    except Exception:  # pragma: no cover - environments without a database
        return None


@pytest.fixture
def synthetic():
    """A security under OLD with its mapping, issuers, profile and identifier; rolled back."""
    conn = _connect()
    if conn is None:
        pytest.skip("no database available")
    trans = conn.begin()
    security_id = uuid.uuid4()
    try:
        issuer_old = conn.execute(
            text(
                "INSERT INTO reference.issuers (cik, issuer_name) VALUES (:c, 'Old Corp') RETURNING issuer_id"
            ),
            {"c": OLD},
        ).scalar()
        issuer_new = conn.execute(
            text(
                "INSERT INTO reference.issuers (cik, issuer_name) VALUES (:c, 'Successor Holdings') RETURNING issuer_id"
            ),
            {"c": NEW},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO raw.company_ticker (ticker, cik, title, source_url, raw_payload) "
                "VALUES (:t, :c, 'Old Corp', 'u', '{}'::jsonb)"
            ),
            {"t": TICKER, "c": OLD},
        )
        conn.execute(
            text(
                "INSERT INTO reference.securities (ticker, cik, security_id, security_name, "
                "security_type, issuer_id, active) VALUES (:t, :c, :s, 'Old Corp', 'common_stock', :i, TRUE)"
            ),
            {"t": TICKER, "c": OLD, "s": security_id, "i": issuer_old},
        )
        conn.execute(
            text(
                "INSERT INTO clean.ticker_profile (cik, ticker, security_id, source_security_ids, "
                "profile_count, security_name, active, dividend) "
                "VALUES (:c, :t, :s, ARRAY[:s]::uuid[], 1, 'Old Corp', TRUE, FALSE)"
            ),
            {"c": OLD, "t": TICKER, "s": security_id},
        )
        conn.execute(
            text(
                "INSERT INTO reference.security_identifiers (security_id, id_type, id_value, source) "
                "VALUES (:s, 'cik', :c, 'test')"
            ),
            {"s": security_id, "c": OLD},
        )
        yield conn, security_id, issuer_new
    finally:
        trans.rollback()
        conn.close()


def _rekey(conn, entries=ENTRIES):
    return rk.apply_rekey(conn, TICKER, NEW, date(2026, 10, 28), "8-K12B test", "tester", entries)


def test_the_security_keeps_its_id_and_moves_to_the_new_cik(synthetic):
    conn, security_id, issuer_new = synthetic

    summary = _rekey(conn)

    row = conn.execute(
        text("SELECT security_id, cik, issuer_id FROM reference.securities WHERE ticker = :t"),
        {"t": TICKER},
    ).one()
    assert row.security_id == security_id and row.cik == NEW and row.issuer_id == issuer_new
    assert summary["old_cik"] == OLD and summary["new_cik"] == NEW
    mapped = conn.execute(
        text("SELECT cik, title FROM raw.company_ticker WHERE ticker = :t"), {"t": TICKER}
    ).one()
    assert mapped.cik == NEW and mapped.title == "Successor Holdings, Inc."
    assert (
        conn.execute(
            text("SELECT cik FROM clean.ticker_profile WHERE security_id = :s"), {"s": security_id}
        ).scalar()
        == NEW
    )


def test_the_identifier_history_is_closed_and_reopened_without_a_gap(synthetic):
    conn, security_id, _ = synthetic

    _rekey(conn)

    rows = {
        r.id_value: (r.valid_from, r.valid_to)
        for r in conn.execute(
            text(
                "SELECT id_value, valid_from, valid_to FROM reference.security_identifiers "
                "WHERE security_id = :s AND id_type = 'cik'"
            ),
            {"s": security_id},
        )
    }
    assert rows[OLD] == (None, date(2026, 10, 27))
    assert rows[NEW] == (date(2026, 10, 28), None)


def test_the_foreign_key_is_not_left_deferrable_and_the_resolution_is_recorded(synthetic):
    conn, security_id, _ = synthetic

    _rekey(conn)

    assert not conn.execute(
        text("SELECT condeferrable FROM pg_constraint WHERE conname = :n"), {"n": rk.FK_NAME}
    ).scalar()
    note = conn.execute(
        text(
            "SELECT resolution_note FROM audit.quarantined_values "
            "WHERE row_key = :k AND rule = 'TICKER_CIK_CONFLICT' AND resolved_at IS NOT NULL"
        ),
        {"k": str(security_id)},
    ).scalar()
    assert note and "8-K12B test" in note and "tester" in note


def test_a_second_rekey_is_refused_because_it_is_already_mapped(synthetic):
    conn, _, _ = synthetic
    _rekey(conn)

    with pytest.raises(rk.RekeyRefused, match="already mapped"):
        _rekey(conn)


def test_a_cik_the_sec_does_not_assign_the_ticker_to_is_refused_and_nothing_changes(synthetic):
    conn, security_id, _ = synthetic
    wrong = [{"cik_str": 1234567, "ticker": TICKER, "title": "Someone Else"}]

    with pytest.raises(rk.RekeyRefused, match="does not list"):
        _rekey(conn, entries=wrong)

    assert (
        conn.execute(
            text("SELECT cik FROM reference.securities WHERE security_id = :s"), {"s": security_id}
        ).scalar()
        == OLD
    )


def test_a_missing_successor_issuer_row_is_refused(synthetic):
    conn, _, _ = synthetic
    conn.execute(text("DELETE FROM reference.issuers WHERE cik = :c"), {"c": NEW})

    with pytest.raises(rk.RekeyRefused, match="no reference.issuers row"):
        _rekey(conn)


def test_history_in_tables_keyed_by_security_id_is_not_touched(synthetic):
    conn, security_id, _ = synthetic
    conn.execute(
        text(
            "INSERT INTO raw.market_data (security_id, observation_date, close, provider) "
            "VALUES (:s, DATE '2020-01-02', 10, 'TEST')"
        ),
        {"s": security_id},
    )
    before = rk.history_counts(conn, security_id)

    summary = _rekey(conn)

    assert before["raw.market_data"] == 1
    assert summary["history_counts"] == before


def test_the_conflict_row_stage_zero_registered_is_closed_with_the_reason(synthetic):
    conn, _, _ = synthetic
    conn.execute(
        text(
            "INSERT INTO audit.quarantined_values (table_schema, table_name, column_name, "
            "row_key, cik, ticker, observed_value, reason, rule) "
            "VALUES ('raw', 'company_ticker', 'cik', :key, :old, :short, :new, "
            "'stage 0 skipped it', 'TICKER_CIK_CONFLICT')"
        ),
        {"key": TICKER, "short": TICKER, "old": OLD, "new": NEW},
    )

    summary = _rekey(conn)

    assert summary["stage_conflict_rows_closed"] == 1
    row = conn.execute(
        text(
            "SELECT resolved_at, resolution_note FROM audit.quarantined_values "
            "WHERE table_schema = 'raw' AND row_key = :t AND rule = 'TICKER_CIK_CONFLICT'"
        ),
        {"t": TICKER},
    ).one()
    assert row.resolved_at is not None and "successor re-key" in row.resolution_note


def test_closing_an_already_resolved_conflict_closes_nothing(synthetic):
    conn, _, _ = synthetic

    assert rk.close_stage_conflict(conn, TICKER, NEW, "n") == 0
