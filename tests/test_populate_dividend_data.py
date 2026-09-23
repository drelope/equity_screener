from unittest.mock import patch

from scripts.populate_dividend_data import (
    extract_sec_dividend_data,
    get_latest_dividend_rate,
    normalize_sec_dividend_rows,
    parse_date,
    populate_preferred_terms,
)


def test_extract_sec_dividend_data_unwraps_live_facts_shape():
    payload = {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "CommonStockDividendsPerShareDeclared": {
                    "units": {"USD/shares": [
                        {"val": 0, "end": "2025-09-27"},
                        {"val": 0.25, "end": "2025-06-01"},
                    ]}
                },
                "DividendsCommonStockCash": {
                    "units": {"USD": [{
                        "val": 15000000000,
                        "end": "2025-09-27",
                        "filed": "2025-11-03",
                        "form": "10-K",
                        "accn": "0000320193-25-000001",
                    }]}
                },
            }
        },
    }

    with patch("scripts.populate_dividend_data.get_companyfacts", return_value=payload):
        with patch("scripts.populate_dividend_data.engine", _FakeEngine()):
            rows = extract_sec_dividend_data("0000320193")

    assert len(rows) == 2
    assert all(row["cik"] == "0000320193" for row in rows)
    assert all(row["amount"] > 0 for row in rows)
    assert {row["concept"] for row in rows} == {
        "CommonStockDividendsPerShareDeclared",
        "DividendsCommonStockCash",
    }
    assert rows[1]["currency"] == "USD"
    assert parse_date(rows[0]["payment_date"]) == parse_date("2025-06-01")
    assert parse_date(rows[1]["payment_date"]) == parse_date("2025-09-27")


def test_extract_sec_dividend_data_accepts_flat_payload():
    payload = {
        "us-gaap": {
            "DividendsCommonStockCash": {"units": {"USD": [{"val": 5.0, "end": "2025-12-31"}]}}
        }
    }

    with patch("scripts.populate_dividend_data.get_companyfacts", return_value=payload):
        with patch("scripts.populate_dividend_data.engine", _FakeEngine()):
            rows = extract_sec_dividend_data(320193)

    assert len(rows) == 1
    assert rows[0]["amount"] == 5.0
    assert rows[0]["cik"] == "0000320193"


def test_extract_sec_dividend_data_returns_empty_on_fetch_error():
    with patch("scripts.populate_dividend_data.get_companyfacts", side_effect=Exception("boom")):
        with patch("scripts.populate_dividend_data.engine", _FakeEngine()):
            assert extract_sec_dividend_data("0000320193") == []


def test_normalize_sec_dividend_rows_preserves_cik_and_drops_bad_amounts():
    sec_rows = [
        {"cik": "0000320193", "amount": 1.5, "ex_dividend_date": "2025-01-01", "payment_date": "2025-02-01", "currency": "USD"},
        {"cik": "0000320193", "amount": 0, "ex_dividend_date": "2025-01-01"},
        {"cik": "0000320193", "amount": None},
        {"cik": "0000320193", "amount": "bad"},
    ]

    normalized = normalize_sec_dividend_rows("AAPL", sec_rows)

    assert len(normalized) == 1
    assert normalized[0]["ticker"] == "AAPL"
    assert normalized[0]["cik"] == "0000320193"
    assert normalized[0]["ex_dividend_date"] == parse_date("2025-01-01")
    assert normalized[0]["frequency"] == "Annual"
    assert normalized[0]["currency"] == "USD"


class _Result:
    def __init__(self, rows=None, scalar_value=None, rowcount=None):
        self._rows = rows
        self._scalar = scalar_value
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class _CacheConn:
    """Fake connection: no stored companyfacts payload, records upserts."""

    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        statement = str(sql)
        self.executed.append((statement, params))
        if "SELECT raw_payload FROM raw.companyfacts" in statement:
            return _Result(scalar_value=None)
        return _Result(scalar_value=1, rowcount=1)

    def commit(self):
        pass

    def close(self):
        pass


class _FakeEngine:
    def __init__(self, stored_payload=None):
        self._conn = _CacheConn()

    def connect(self):
        return self._conn


class _QueueConn:
    def __init__(self, results):
        self._results = list(results)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((str(sql), params))
        return self._results.pop(0)


def test_latest_dividend_rate_reads_latest_positive_amount():
    conn = _QueueConn([_Result(scalar_value=0.25)])

    rate = get_latest_dividend_rate(conn, "some-security-id")

    assert rate == 0.25
    sql, params = conn.executed[0]
    assert "amount > 0" in sql
    assert params == {"security_id": "some-security-id"}


def test_populate_preferred_terms_inserts_gaps_and_keeps_existing():
    candidates = [
        {"security_id": "uuid-1", "ticker": "ACR-PC", "security_name": "Series C Preferred Stock"},
        {"security_id": "uuid-2", "ticker": "ACR-PD", "security_name": "Series D Preferred Stock"},
    ]
    conn = _QueueConn([
        _Result(rows=candidates),
        _Result(scalar_value=2.40),
        _Result(rowcount=1),
        _Result(scalar_value=None),
        _Result(rowcount=0),
    ])

    inserted = populate_preferred_terms(conn)

    assert inserted == 1
    insert_calls = [sql for sql, _ in conn.executed if sql.strip().startswith(
        "INSERT INTO preferred.security_terms"
    )]
    assert len(insert_calls) == 2
    assert "ON CONFLICT (security_id) DO NOTHING" in insert_calls[0]