import json
from datetime import date

import pandas as pd

from scripts import populate_fmp_fundamentals


class _Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _FakeConnection:
    """Records every statement; returns the canned securities for the loader."""

    def __init__(self, securities=()):
        self.securities = list(securities)
        self.statements = []
        self.params = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        if "FROM reference.securities" in str(statement):
            return _Result(self.securities)
        return _Result()


class _Begin:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_args):
        return False


class _Engine:
    def __init__(self, conn):
        self.conn = conn

    def connect(self):
        return _Begin(self.conn)

    def begin(self):
        return _Begin(self.conn)


def _security(ticker="AAPL", security_id="11111111-1111-1111-1111-111111111111"):
    return {"security_id": security_id, "ticker": ticker}


def test_load_securities_applies_dividend_and_ticker_filters():
    conn = _FakeConnection()

    populate_fmp_fundamentals.load_securities(conn, tickers=["aapl", "ko"])

    sql = conn.statements[0]
    assert "s.dividend = TRUE" in sql
    assert "s.active = TRUE" in sql
    assert "UPPER(s.ticker) = ANY(:tickers)" in sql
    assert conn.params[0] == {"tickers": ["AAPL", "KO"]}


def test_upsert_statement_writes_keyed_columns_and_metrics():
    conn = _FakeConnection()
    row = {
        "period_ending": "2025-12-31",
        "fiscal_period": "FY",
        "fiscal_year": 2025,
        "filing_date": "2026-02-01",
        "reported_currency": "USD",
        "revenue": 100,
    }

    assert populate_fmp_fundamentals.upsert_statement(conn, "sid", "income", row) == 1

    sql = conn.statements[0]
    assert "INSERT INTO raw.fmp_statements" in sql
    assert "ON CONFLICT (security_id, statement, period_end, fiscal_period, filing_date)" in sql
    params = conn.params[0]
    assert params["statement"] == "income"
    assert params["period_end"] == date(2025, 12, 31)
    assert params["fiscal_period"] == "FY"
    assert params["fiscal_year"] == 2025
    assert params["filing_date"] == date(2026, 2, 1)
    assert json.loads(params["metrics"])["revenue"] == 100


def test_upsert_statement_skips_a_row_without_a_filing_date():
    conn = _FakeConnection()

    assert populate_fmp_fundamentals.upsert_statement(conn, "sid", "income", {}) == 0
    assert conn.statements == []


def test_upsert_dcf_skips_a_missing_date():
    conn = _FakeConnection()

    assert populate_fmp_fundamentals.upsert_dcf(conn, "sid", {"dcf": 1}) == 0
    assert conn.statements == []


def test_upsert_filings_skips_rows_missing_a_url():
    conn = _FakeConnection()
    frame = pd.DataFrame([{"filing_date": "2026-01-01", "report_type": "10-K", "report_url": None}])

    assert populate_fmp_fundamentals.upsert_filings(conn, "sid", frame) == 0
    assert conn.statements == []


def test_populate_skips_cleanly_without_an_fmp_key(monkeypatch):
    conn = _FakeConnection([_security()])
    monkeypatch.setattr(populate_fmp_fundamentals, "engine", _Engine(conn))
    monkeypatch.setattr(populate_fmp_fundamentals, "_has_fmp_key", lambda: False)

    stats = populate_fmp_fundamentals.populate_fmp_fundamentals()

    assert stats["skipped"] == 1 and stats["written"] == 0
    assert not any("INSERT INTO raw.fmp_" in sql for sql in conn.statements)


def test_populate_writes_statements_dcf_and_filings(monkeypatch):
    conn = _FakeConnection([_security()])
    monkeypatch.setattr(populate_fmp_fundamentals, "engine", _Engine(conn))
    monkeypatch.setattr(populate_fmp_fundamentals, "_has_fmp_key", lambda: True)
    statement = pd.DataFrame(
        [
            {
                "period_ending": "2025-12-31",
                "fiscal_period": "FY",
                "fiscal_year": 2025,
                "filing_date": "2026-02-01",
                "reported_currency": "USD",
                "revenue": 100,
            }
        ]
    )
    monkeypatch.setattr(
        populate_fmp_fundamentals, "financial_statements", lambda *args, **kwargs: statement
    )
    monkeypatch.setattr(
        populate_fmp_fundamentals,
        "discounted_cash_flow",
        lambda symbol: {
            "as_of_date": date(2026, 10, 20),
            "dcf": 135.6,
            "stock_price": 340.7,
            "reported_currency": None,
        },
    )
    monkeypatch.setattr(
        populate_fmp_fundamentals,
        "filings",
        lambda symbol: pd.DataFrame(
            [{"filing_date": "2026-01-01", "report_type": "10-K", "report_url": "http://x"}]
        ),
    )

    stats = populate_fmp_fundamentals.populate_fmp_fundamentals()

    assert stats["errors"] == 0
    assert stats["written"] == 5, "3 statement rows + 1 DCF + 1 filing"
    assert any("INSERT INTO raw.fmp_statements" in sql for sql in conn.statements)
    assert any("INSERT INTO raw.fmp_dcf" in sql for sql in conn.statements)
    assert any("INSERT INTO raw.fmp_filings" in sql for sql in conn.statements)


def test_populate_counts_a_failing_security_without_stopping(monkeypatch):
    conn = _FakeConnection(
        [_security("AAPL"), _security("MSFT", "22222222-2222-2222-2222-222222222222")]
    )
    monkeypatch.setattr(populate_fmp_fundamentals, "engine", _Engine(conn))
    monkeypatch.setattr(populate_fmp_fundamentals, "_has_fmp_key", lambda: True)

    def boom(*args, **kwargs):
        raise RuntimeError("FMP down")

    monkeypatch.setattr(populate_fmp_fundamentals, "financial_statements", boom)
    monkeypatch.setattr(populate_fmp_fundamentals, "discounted_cash_flow", boom)
    monkeypatch.setattr(populate_fmp_fundamentals, "filings", boom)

    stats = populate_fmp_fundamentals.populate_fmp_fundamentals()

    assert stats["attempted"] == 2 and stats["written"] == 0
    assert stats["errors"] > 0
