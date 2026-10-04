from unittest.mock import patch

import pandas as pd
from openbb_core.provider.utils.errors import EmptyDataError

from scripts import populate_market_data


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _FakeConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []
        self.params = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        return _Result(self.rows)


def test_get_target_securities_defaults_to_dividend_payers():
    conn = _FakeConnection([("sid-1", "AAPL"), ("sid-2", "KO")])

    targets = populate_market_data.get_target_securities(conn)

    assert targets == [("sid-1", "AAPL"), ("sid-2", "KO")]
    assert "s.dividend = TRUE" in conn.statements[0]
    assert "s.active = TRUE" in conn.statements[0]
    assert "LIMIT" not in conn.statements[0]


def test_get_target_securities_applies_ticker_and_limit_filters():
    conn = _FakeConnection()

    populate_market_data.get_target_securities(conn, tickers=["aapl"], limit=5)

    assert "UPPER(s.ticker) = ANY(:tickers)" in conn.statements[0]
    assert "LIMIT :limit" in conn.statements[0]
    assert conn.params[0] == {"tickers": ["AAPL"], "limit": 5}


def test_get_target_securities_can_include_non_dividend_securities():
    conn = _FakeConnection()

    populate_market_data.get_target_securities(conn, dividend_only=False)

    assert "s.dividend = TRUE" not in conn.statements[0]


def test_normalize_price_rows_maps_openbb_columns():
    frame = pd.DataFrame(
        [
            {
                "date": "2026-09-24",
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.5,
                "Adj Close": 100.4,
                "Volume": 1000,
            },
            {"date": "2026-09-25", "Open": None, "High": None, "Low": None, "Close": 101.0},
        ]
    )

    rows = populate_market_data.normalize_price_rows("sid-1", "AAPL", frame)

    assert len(rows) == 2
    assert rows[0]["observation_date"].isoformat() == "2026-09-24"
    assert rows[0]["close"] == 100.5
    assert rows[0]["adjusted_close"] == 100.4
    assert rows[0]["volume"] == 1000.0
    assert rows[0]["security_id"] == "sid-1"
    assert rows[0]["provider"] == "OPENBB"
    assert rows[1]["open"] is None


def test_normalize_price_rows_handles_empty_and_datelike_frames():
    assert populate_market_data.normalize_price_rows("sid-1", "AAPL", None) == []
    assert populate_market_data.normalize_price_rows("sid-1", "AAPL", pd.DataFrame()) == []
    frame = pd.DataFrame([{"date": pd.Timestamp("2026-09-25"), "close": 1.0}])
    rows = populate_market_data.normalize_price_rows("sid-1", "AAPL", frame)
    assert rows[0]["observation_date"].isoformat() == "2026-09-25"


def test_normalize_price_rows_reads_the_date_from_the_frame_index():
    """OpenBB returns the observation date as the index, with no date column."""

    frame = pd.DataFrame(
        {"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [1000.0]},
        index=pd.to_datetime(["2026-09-25"]),
    )

    rows = populate_market_data.normalize_price_rows("sid-1", "AAPL", frame)

    assert len(rows) == 1
    assert rows[0]["observation_date"].isoformat() == "2026-09-25"
    assert rows[0]["close"] == 1.5
    assert rows[0]["volume"] == 1000
    assert isinstance(rows[0]["volume"], int)


def test_normalize_price_rows_drops_rows_without_a_usable_date():
    frame = pd.DataFrame([{"open": 1.0, "close": 1.5}], index=pd.to_datetime([None]))

    assert populate_market_data.normalize_price_rows("sid-1", "AAPL", frame) == []


def test_no_data_is_distinguished_from_a_broken_fetch():
    """ "Provider does not carry this symbol" is a coverage gap, not an error.

    yfinance raises instead of returning an empty frame, so unpriced warrants,
    rights and units used to land in the same ``errors`` counter as a network
    failure. The nightly then reported 235 errors on a run that had not actually
    failed at anything, which is the same reporting defect as
    ``missing_securities=5149``: a benign condition counted as a fault, and a
    real fault invisible behind it.
    """
    no_data = [
        # OpenBB's own signal, found by probing the live provider. Its message is
        # a generic "no results found", so the class is what has to be trusted.
        EmptyDataError("[Empty] -> No results found. Try adjusting the query parameters."),
        Exception("$AYR: No data found, symbol may be delisted"),
        Exception("HTTP Error 404: Quote not found for symbol: BDI"),
        Exception("ABPWW: possibly delisted; no price data found"),
        Exception("XYZ: no timezone found"),
    ]
    for exc in no_data:
        assert populate_market_data.is_no_data_error(exc) is True, str(exc)

    real_faults = [
        Exception("Connection reset by peer"),
        Exception("HTTP Error 503: Service Unavailable"),
        Exception("Read timed out. (read timeout=30)"),
        Exception("Too Many Requests. Rate limited"),
    ]
    for exc in real_faults:
        assert populate_market_data.is_no_data_error(exc) is False, str(exc)


def test_no_data_errors_are_not_retried_but_transient_ones_are():
    """Asking a rate-limited provider again for a symbol it never had is waste."""
    attempts = []

    def _boom(exc):
        def _call(_ticker, _start, _end, attempts_=1):
            attempts.append(str(exc))
            raise exc

        return _call

    with patch.object(populate_market_data, "historical_prices", _boom(Exception("No data found"))):
        frame, exc = populate_market_data._fetch_with_retry("ABC", "2025-01-01", "2025-02-01")
    assert frame is None
    assert len(attempts) == 1, "a no-data symbol must not be retried"
    assert populate_market_data.is_no_data_error(exc)

    attempts.clear()
    with (
        patch.object(
            populate_market_data, "historical_prices", _boom(Exception("Connection reset"))
        ),
        patch.object(populate_market_data.time, "sleep"),
    ):
        frame, exc = populate_market_data._fetch_with_retry("ABC", "2025-01-01", "2025-02-01")
    assert frame is None
    assert len(attempts) == 3, "a transient fault should be retried to exhaustion"
    assert not populate_market_data.is_no_data_error(exc)
