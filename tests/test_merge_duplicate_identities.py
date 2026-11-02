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


def _feature(conn, sid, day, close):
    conn.execute(
        text("INSERT INTO model.features (security_id, as_of_date) VALUES (:s, :d)"),
        {"s": sid, "d": day},
    )


def test_a_derived_table_difference_does_not_block_when_the_history_is_redundant(pair):
    """Features are computed from prices: a twin's older feature rows are rebuildable from the
    active identity's own (identical) prices, so they do not make the twin irreplaceable."""
    conn, active, twin = pair
    for sid in (active, twin):
        _price(conn, sid, date(2024, 1, 2), 10.0)
    _feature(conn, twin, date(2023, 12, 29), 1)  # a feature row only the twin has

    report = mdi.report(conn, TICKER)

    assert report["all_redundant"] is True
    assert report["twins"][0]["rebuilt_metadata_differs"] == {"model.features": 1}


def test_a_derived_difference_is_moot_when_a_history_table_blocks(pair):
    conn, active, twin = pair
    _price(conn, twin, date(2024, 1, 2), 10.0)  # history only the twin has
    _feature(conn, twin, date(2024, 1, 2), 1)

    assert mdi.report(conn, TICKER)["all_redundant"] is False


def test_model_outputs_are_history_not_derived(pair):
    """A past score cannot be regenerated, so a twin owning one is never redundant."""
    assert "model.scores" not in mdi.DERIVED_TABLES
    assert "model.predictions" not in mdi.DERIVED_TABLES
    assert "model.rankings" not in mdi.DERIVED_TABLES


def _dividend(conn, sid, day, amount, adjusted=None, feed="fmp"):
    conn.execute(
        text(
            "INSERT INTO raw.dividend_data (security_id, ex_dividend_date, amount, adjusted_amount, "
            "provider, feed) VALUES (:s, :d, :a, :j, 'TEST', :f)"
        ),
        {"s": sid, "d": day, "a": amount, "j": adjusted, "f": feed},
    )


def _count(conn, table, sid):
    return conn.execute(
        text(f"SELECT count(*) FROM {table} WHERE security_id = :s"),
        {"s": sid},  # noqa: S608
    ).scalar()


def test_merge_moves_the_twins_unique_rows_and_keeps_the_active_row_on_overlap(pair):
    conn, active, twin = pair
    _price(conn, active, date(2024, 1, 3), 11.0)
    _price(conn, twin, date(2024, 1, 3), 11.1)  # overlap: the active row stays
    _price(conn, twin, date(2023, 12, 29), 9.0)  # only the twin has it

    result = mdi.merge_twins(conn, TICKER, None)

    assert result["rows_moved"] == {"raw.market_data": 1}
    assert _count(conn, "raw.market_data", active) == 2
    closes = dict(
        conn.execute(
            text("SELECT observation_date, close FROM raw.market_data WHERE security_id = :s"),
            {"s": active},
        ).all()
    )
    assert float(closes[date(2024, 1, 3)]) == 11.0  # the active value, not the twin's 11.1
    assert float(closes[date(2023, 12, 29)]) == 9.0
    assert (
        _count(conn, "reference.securities", twin) == 0
        or conn.execute(
            text("SELECT count(*) FROM reference.securities WHERE security_id = :s"), {"s": twin}
        ).scalar()
        == 0
    )


def test_merge_refuses_when_an_overlapping_close_is_a_different_price(pair):
    conn, active, twin = pair
    _price(conn, active, date(2024, 1, 3), 10.0)
    _price(conn, twin, date(2024, 1, 3), 14.0)  # 40% apart: not the same series

    with pytest.raises(RuntimeError, match="overlapping closes differ"):
        mdi.merge_twins(conn, TICKER, None)


def test_a_stray_high_or_volume_difference_on_the_same_close_is_not_a_conflict(pair):
    conn, active, twin = pair
    for sid, high, volume in ((active, 15.8, 775574), (twin, 11.8, 775570)):
        conn.execute(
            text(
                "INSERT INTO raw.market_data (security_id, observation_date, open, high, low, close, "
                "volume, provider) VALUES (:s, DATE '2024-06-03', 7.2, :h, 7.1, 10.0, :v, 'TEST')"
            ),
            {"s": sid, "h": high, "v": volume},
        )

    assert mdi.merge_twins(conn, TICKER, None)["rows_moved"] == {}


def test_a_twin_null_where_the_active_row_has_a_value_is_not_a_conflict(pair):
    """The BMNR/BGMS dividends: the older row lacks the adjusted amount and the feed label differs."""
    conn, active, twin = pair
    _dividend(conn, active, date(2025, 4, 29), 36.0, adjusted=8640.0, feed="fmp")
    _dividend(conn, twin, date(2025, 4, 29), 36.0, adjusted=None, feed="yfinance")

    result = mdi.merge_twins(conn, TICKER, None)

    assert result["rows_moved"] == {}
    assert _count(conn, "raw.dividend_data", active) == 1


def test_a_twin_dividend_with_a_different_amount_is_refused(pair):
    conn, active, twin = pair
    _dividend(conn, active, date(2025, 4, 29), 36.0)
    _dividend(conn, twin, date(2025, 4, 29), 40.0)

    with pytest.raises(RuntimeError, match="twin value the active row lacks or contradicts"):
        mdi.merge_twins(conn, TICKER, None)


def test_skip_move_before_leaves_an_earlier_companys_prices_behind(pair):
    """BGMS: the twin's 2019-2025 prices predate the active identity and are another entity's."""
    conn, active, twin = pair
    _price(conn, active, date(2025, 9, 12), 5.0)
    _price(conn, twin, date(2025, 9, 12), 5.0)
    _price(conn, twin, date(2020, 1, 2), 90.0)  # earlier history, not to be moved
    _price(conn, twin, date(2025, 9, 15), 5.5)  # later than the cut-off: moved

    result = mdi.merge_twins(conn, TICKER, None, skip_before=date(2025, 9, 12))

    assert result["rows_moved"] == {"raw.market_data": 1}
    dates = {
        r[0]
        for r in conn.execute(
            text("SELECT observation_date FROM raw.market_data WHERE security_id = :s"),
            {"s": active},
        )
    }
    assert dates == {date(2025, 9, 12), date(2025, 9, 15)}


def test_derived_rows_the_twin_has_move_and_the_active_ones_win_on_overlap(pair):
    conn, active, twin = pair
    _feature(conn, active, date(2024, 1, 3), 1)
    _feature(conn, twin, date(2024, 1, 3), 1)
    _feature(conn, twin, date(2023, 6, 1), 1)

    result = mdi.merge_twins(conn, TICKER, None)

    assert result["rows_moved"] == {"model.features": 1}


def test_the_merge_archives_the_twin_before_it_changes_anything(pair, tmp_path):
    conn, active, twin = pair
    _price(conn, twin, date(2023, 12, 29), 9.0)
    archive = tmp_path / "merge.json"

    mdi.merge_twins(conn, TICKER, archive)

    body = json.loads(archive.read_text())
    assert body["twins"] == [str(twin)] and "raw.market_data" in body["rows"]
