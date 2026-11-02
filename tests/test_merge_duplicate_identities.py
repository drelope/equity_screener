"""A twin identity is deleted only when it is redundant, and only after it is archived.

Synthetic identities inside a rolled-back transaction, so the real foreign keys and the real
dependent-table graph are exercised and nothing persists.
"""

import json
import uuid
from datetime import date

import pytest
from sqlalchemy import text

from scripts import merge_duplicate_identities as mdi

TICKER, CIK = "ZZTWN", "0009990011"


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
def pair():
    conn = _connect()
    if conn is None:
        pytest.skip("no database available")
    trans = conn.begin()
    active, twin = uuid.uuid4(), uuid.uuid4()
    try:
        conn.execute(
            text(
                "INSERT INTO raw.company_ticker (ticker, cik, title, source_url, raw_payload) "
                "VALUES (:t, :c, 'Twin Corp', 'u', '{}'::jsonb)"
            ),
            {"t": TICKER, "c": CIK},
        )
        for sid, kind, is_active in ((active, "common_stock", True), (twin, "equity", False)):
            conn.execute(
                text(
                    "INSERT INTO reference.securities (ticker, cik, security_id, security_name, "
                    "security_type, dividend, active) VALUES (:t, :c, :s, 'Twin Corp', :k, FALSE, :a)"
                ),
                {"t": TICKER, "c": CIK, "s": sid, "k": kind, "a": is_active},
            )
        yield conn, active, twin
    finally:
        trans.rollback()
        conn.close()


def _price(conn, sid, day, close, provider="TEST"):
    conn.execute(
        text(
            "INSERT INTO raw.market_data (security_id, observation_date, close, provider) "
            "VALUES (:s, :d, :c, :p)"
        ),
        {"s": sid, "d": day, "c": close, "p": provider},
    )


def test_a_twin_with_only_copies_of_the_active_rows_is_redundant(pair):
    conn, active, twin = pair
    for sid in (active, twin):
        _price(conn, sid, date(2024, 1, 2), 10.0)
        _price(conn, sid, date(2024, 1, 3), 11.0)

    report = mdi.report(conn, TICKER)

    assert report["all_redundant"] is True
    assert report["twins"][0]["findings"]["raw.market_data"] == {"twin_rows": 2, "not_on_active": 0}


def test_a_twin_holding_a_row_the_active_identity_lacks_is_not_redundant(pair):
    conn, active, twin = pair
    _price(conn, active, date(2024, 1, 2), 10.0)
    _price(conn, twin, date(2024, 1, 2), 10.0)
    _price(conn, twin, date(2023, 12, 29), 9.0)  # history only the twin has

    report = mdi.report(conn, TICKER)

    assert report["all_redundant"] is False
    assert "raw.market_data: 1 of 2" in report["twins"][0]["blockers"][0]


def test_a_twin_whose_value_disagrees_for_the_same_date_is_not_redundant(pair):
    """The LFMD/PBR case: the same date and provider with a different value."""
    conn, active, twin = pair
    _price(conn, active, date(2024, 1, 2), 10.0)
    _price(conn, twin, date(2024, 1, 2), 5.0)

    assert mdi.report(conn, TICKER)["all_redundant"] is False


def test_a_redundant_twin_is_archived_then_deleted_and_the_active_row_is_untouched(pair, tmp_path):
    conn, active, twin = pair
    for sid in (active, twin):
        _price(conn, sid, date(2024, 1, 2), 10.0)
    archive = tmp_path / "twin.json"

    result = mdi.delete_twins(conn, TICKER, archive)

    assert result["twins_deleted"] == [str(twin)]
    assert (
        conn.execute(
            text("SELECT count(*) FROM reference.securities WHERE security_id = :s"), {"s": twin}
        ).scalar()
        == 0
    )
    assert (
        conn.execute(
            text("SELECT count(*) FROM raw.market_data WHERE security_id = :s"), {"s": active}
        ).scalar()
        == 1
    )
    body = json.loads(archive.read_text())
    assert body["twins"] == [str(twin)] and "raw.market_data" in body["rows"]


def test_a_non_redundant_twin_is_never_deleted(pair, tmp_path):
    conn, active, twin = pair
    _price(conn, twin, date(2024, 1, 2), 10.0)  # the active identity has nothing

    with pytest.raises(RuntimeError, match="not every twin is redundant"):
        mdi.delete_twins(conn, TICKER, tmp_path / "twin.json")

    assert (
        conn.execute(
            text("SELECT count(*) FROM reference.securities WHERE security_id = :s"), {"s": twin}
        ).scalar()
        == 1
    )
    assert not (tmp_path / "twin.json").exists()


def test_serial_ids_and_load_timestamps_do_not_make_a_copy_look_different(pair):
    conn, active, twin = pair
    for sid in (active, twin):
        _price(conn, sid, date(2024, 1, 2), 10.0)
    conn.execute(
        text(
            "UPDATE raw.market_data SET retrieved_at = now() - interval '9 days' WHERE security_id = :s"
        ),
        {"s": twin},
    )

    assert mdi.report(conn, TICKER)["all_redundant"] is True


def test_a_ticker_with_two_active_identities_is_refused(pair):
    conn, active, twin = pair
    conn.execute(
        text("UPDATE reference.securities SET active = TRUE WHERE security_id = :s"), {"s": twin}
    )

    assert "expected one active identity" in mdi.report(conn, TICKER)["error"]
