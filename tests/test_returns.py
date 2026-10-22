"""The forward-return engine: the rules that make a 12M total return mean something.

These tests pin the four rules the module docstring names, because each one has a
silent failure mode: a partial window is a valid number that means something else, a
doubly-booked dividend is a return no holder earned, and a payment booked to the wrong
day moves the return without moving the price.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.crispdm import returns


def test_the_window_is_252_trading_days():
    assert returns.FORWARD_WINDOW_DAYS == 252


def test_the_query_uses_only_the_openbb_per_payment_series():
    # SEC_XBRL's ex_dividend_date is a fiscal period end, and summing both
    # series books one payment twice.
    assert "provider = 'OPENBB'" in returns.FORWARD_RETURN_SQL
    assert "SEC_XBRL" not in returns.FORWARD_RETURN_SQL


def test_the_query_takes_the_dividend_from_the_adjusted_amount():
    assert "COALESCE(adjusted_amount, amount)" in returns.FORWARD_RETURN_SQL


def test_the_query_books_a_payment_to_the_first_row_on_or_after_its_ex_date():
    assert "m.observation_date >= e.ex_dividend_date" in returns.FORWARD_RETURN_SQL
    assert "ORDER BY m.observation_date" in returns.FORWARD_RETURN_SQL


def test_the_query_drops_a_payment_larger_than_the_prior_close():
    assert ":max_payment_ratio * LAG(m.close) OVER w" in returns.FORWARD_RETURN_SQL
    assert returns.MAX_SINGLE_PAYMENT_RATIO == 1.0


def test_the_query_keeps_only_complete_windows():
    # A partial sum is a valid number that means something else: the count is
    # checked rather than assumed.
    assert "WHERE window_days = :window_days" in returns.FORWARD_RETURN_SQL
    assert "COUNT(daily_total_return) OVER w AS window_days" in returns.FORWARD_RETURN_SQL


def test_the_query_splits_the_total_return_into_its_price_and_income_parts():
    assert "total_return - price_return AS dividend_return" in returns.FORWARD_RETURN_SQL
    assert "AS price_return" in returns.FORWARD_RETURN_SQL


def test_the_query_bounds_the_output_by_the_requested_dates():
    assert "as_of_date >= :date_from AND as_of_date < :date_to" in returns.FORWARD_RETURN_SQL


def test_db_value_maps_missing_numbers_to_null():
    assert returns._db_value(np.nan) is None
    assert returns._db_value(float("nan")) is None
    assert returns._db_value(np.inf) is None
    assert returns._db_value(-np.inf) is None
    assert returns._db_value(pd.NaT) is None
    assert returns._db_value(None) is None


def test_db_value_keeps_real_values():
    assert returns._db_value(0.1553) == pytest.approx(0.1553)
    assert returns._db_value(np.float64(2.5)) == 2.5
    assert returns._db_value(np.int64(3)) == 3
    assert isinstance(returns._db_value(np.int64(3)), int)
    assert returns._db_value(date(2026, 9, 25)) == date(2026, 9, 25)
    assert returns._db_value(pd.Timestamp("2026-09-25")) == date(2026, 9, 25)


def test_the_payload_binds_every_column_of_the_table():
    frame = pd.DataFrame(
        [
            {
                "security_id": "sid-1",
                "as_of_date": date(2026, 9, 25),
                "forward_date": date(2027, 9, 26),
                "window_days": 252,
                "total_return": 0.12,
                "price_return": 0.08,
                "dividend_return": 0.04,
            }
        ]
    )

    payload = returns.forward_return_payload(frame)

    assert len(payload) == 1
    assert set(payload[0]) == set(returns.FORWARD_COLUMNS)
    assert payload[0]["window_days"] == 252
    assert payload[0]["total_return"] == pytest.approx(0.12)


def test_the_payload_nulls_a_missing_return():
    frame = pd.DataFrame(
        [
            {
                "security_id": "sid-1",
                "as_of_date": date(2026, 9, 25),
                "forward_date": date(2027, 9, 26),
                "window_days": 252,
                "total_return": np.nan,
                "price_return": np.nan,
                "dividend_return": np.nan,
            }
        ]
    )

    payload = returns.forward_return_payload(frame)

    assert payload[0]["total_return"] is None
    assert payload[0]["price_return"] is None
    assert payload[0]["dividend_return"] is None


def test_the_insert_upserts_on_the_key():
    sql = str(returns.INSERT_FORWARD_RETURN)
    assert "ON CONFLICT(security_id, as_of_date) DO UPDATE" in sql
    assert "EXCLUDED.total_return" in sql


def test_persisting_an_empty_frame_writes_nothing():
    assert returns.persist_forward_returns(pd.DataFrame()) == 0


def test_persisting_writes_every_row(monkeypatch):
    frame = pd.DataFrame(
        [
            {
                "security_id": "sid-1",
                "as_of_date": date(2026, 9, 25),
                "forward_date": date(2027, 9, 26),
                "window_days": 252,
                "total_return": 0.12,
                "price_return": 0.08,
                "dividend_return": 0.04,
            },
            {
                "security_id": "sid-2",
                "as_of_date": date(2026, 9, 25),
                "forward_date": date(2027, 9, 26),
                "window_days": 252,
                "total_return": -0.03,
                "price_return": -0.05,
                "dividend_return": 0.02,
            },
        ]
    )
    written = []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement, payload):
            written.extend(payload)

    monkeypatch.setattr(returns, "engine", _FakeEngine(_Conn()))

    assert returns.persist_forward_returns(frame) == 2
    assert [row["security_id"] for row in written] == ["sid-1", "sid-2"]


def test_persisting_splits_the_batch_so_one_statement_stays_bounded(monkeypatch):
    frame = pd.DataFrame(
        [
            {
                "security_id": f"sid-{index}",
                "as_of_date": date(2026, 9, 25),
                "forward_date": date(2027, 9, 26),
                "window_days": 252,
                "total_return": 0.12,
                "price_return": 0.08,
                "dividend_return": 0.04,
            }
            for index in range(5)
        ]
    )
    batches = []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement, payload):
            batches.append(len(payload))

    monkeypatch.setattr(returns, "engine", _FakeEngine(_Conn()))

    assert returns.persist_forward_returns(frame, chunk_size=2) == 5
    assert batches == [2, 2, 1]


class _FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def begin(self):
        return self._conn


def test_the_reader_for_one_security_takes_an_injected_query():
    seen = {}

    def query(sql, params=None):
        seen["sql"] = sql
        seen["params"] = params
        return pd.DataFrame([{"as_of_date": "2026-01-01", "total_return": 0.1}])

    frame = returns.forward_returns_for("11111111-1111-1111-1111-111111111111", query=query)

    assert "model.forward_returns" in seen["sql"]
    assert seen["params"]["sid"] == "11111111-1111-1111-1111-111111111111"
    assert frame.iloc[0]["total_return"] == 0.1


def test_the_reader_can_be_capped_and_dated():
    seen = {}

    def query(sql, params=None):
        seen["sql"] = sql
        seen["params"] = params
        return pd.DataFrame()

    returns.forward_returns_for("sid", as_of_date="2026-01-01", limit=5, query=query)

    assert "as_of_date <= CAST(:as_of AS date)" in seen["sql"]
    assert "LIMIT :limit" in seen["sql"]
    assert seen["params"]["limit"] == 5
