import json
from datetime import date
from unittest.mock import patch

import pandas as pd

from scripts import populate_dividend_data as dividend_data
from scripts.populate_dividend_data import (
    SEC_DIVIDEND_CONCEPTS,
    cadence_from_events,
    extract_sec_dividend_data,
    get_latest_dividend_rate,
    infer_frequency,
    normalize_currency,
    normalize_openbb_dividend_rows,
    normalize_sec_dividend_rows,
    parse_date,
    plausible_dividend_date,
    populate_preferred_terms,
    populate_ticker_profiles,
)


def test_infer_frequency_buckets_by_median_interval():
    # Median of the sorted gaps, so an even count interpolates between the two
    # middle values (linear interpolation matches percentile_cont(0.5)).
    assert infer_frequency([30, 30, 29]) == "Monthly"
    assert infer_frequency([35]) == "Monthly"
    assert infer_frequency([60, 90]) == "Quarterly"
    assert infer_frequency([90, 100]) == "Quarterly"
    assert infer_frequency([95, 106]) == "Semi-annual", "median 100.5 sits past the quarterly border"
    assert infer_frequency([177]) == "Semi-annual"
    assert infer_frequency([365]) == "Annual"
    assert infer_frequency([400]) == "Annual"
    assert infer_frequency([30, 400]) == "Annual", "median 215 still sits inside the annual border"
    assert infer_frequency([450]) == "Irregular"


def test_infer_frequency_is_irregular_without_two_events():
    assert infer_frequency([]) == "Irregular"
    assert infer_frequency([None]) == "Irregular"
    assert infer_frequency([450]) == "Irregular"


def test_cadence_from_events_prefers_openbb_with_two_true_ex_dates():
    fresh = [("s1", "OPENBB", date(2025, 3, 15)), ("s1", "OPENBB", date(2025, 6, 15))]
    stored = []

    assert cadence_from_events(fresh, stored) == {"s1": "Quarterly"}


def test_cadence_from_events_falls_back_to_sec_period_end_series():
    fresh = [("s1", "OPENBB", date(2025, 6, 15))]
    stored = [
        ("s1", "SEC_XBRL", date(2025, 1, 1)),
        ("s1", "SEC_XBRL", date(2025, 4, 1)),
        ("s1", "SEC_XBRL", date(2025, 7, 1)),
    ]

    assert cadence_from_events(fresh, stored) == {"s1": "Quarterly"}


def test_cadence_from_events_is_irregular_for_a_single_event():
    fresh = [("s1", "OPENBB", date(2025, 6, 15))]
    stored = [("s1", "SEC_XBRL", date(2025, 1, 1))]

    assert cadence_from_events(fresh, stored) == {"s1": "Irregular"}


def test_cadence_from_events_matches_the_python_median_to_the_sql_backfill():
    # Even counts: percentile_cont(0.5) interpolates the two middle gaps.
    fresh = [("s1", "OPENBB", date(2025, 1, 1)), ("s1", "OPENBB", date(2025, 4, 1))]
    stored = [("s1", "OPENBB", date(2025, 7, 1)), ("s1", "OPENBB", date(2025, 9, 30))]

    assert cadence_from_events(fresh, stored) == {"s1": "Quarterly"}


def test_extract_sec_dividend_data_unwraps_live_facts_shape():
    payload = {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "CommonStockDividendsPerShareDeclared": {
                    "units": {
                        "USD/shares": [
                            {"val": 0, "end": "2025-09-27"},
                            {"val": 0.25, "end": "2025-06-01"},
                        ]
                    }
                },
                "CommonStockDividendsPerShareCashPaid": {
                    "units": {
                        "USD/shares": [
                            {
                                "val": 0.26,
                                "end": "2025-09-27",
                                "filed": "2025-11-03",
                                "form": "10-K",
                                "accn": "0000320193-25-000001",
                            }
                        ]
                    }
                },
                "DividendsCommonStockCash": {
                    "units": {
                        "USD": [
                            {
                                "val": 15000000000,
                                "end": "2025-09-27",
                                "filed": "2025-11-03",
                                "form": "10-K",
                                "accn": "0000320193-25-000001",
                            }
                        ]
                    }
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
    # the aggregate-dollar fact in the payload is deliberately not ingested
    assert {row["concept"] for row in rows} == {
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    }
    assert rows[1]["currency"] == "USD"
    assert parse_date(rows[0]["payment_date"]) == parse_date("2025-06-01")
    assert parse_date(rows[1]["payment_date"]) == parse_date("2025-09-27")


def test_extract_sec_dividend_data_accepts_flat_payload():
    payload = {
        "us-gaap": {
            "CommonStockDividendsPerShareDeclared": {
                "units": {"USD/shares": [{"val": 0.25, "end": "2025-12-31"}]}
            }
        }
    }

    with patch("scripts.populate_dividend_data.get_companyfacts", return_value=payload):
        with patch("scripts.populate_dividend_data.engine", _FakeEngine()):
            rows = extract_sec_dividend_data(320193)

    assert len(rows) == 1
    assert rows[0]["amount"] == 0.25
    assert rows[0]["cik"] == "0000320193"


def test_extract_sec_dividend_data_ignores_aggregate_dollar_concepts():
    """Aggregate totals must never reach raw.dividend_data.amount."""

    payload = {
        "facts": {
            "us-gaap": {
                "CommonStockDividendsPaid": {
                    "units": {"USD": [{"val": 20_153_000_000, "end": "2025-12-31"}]}
                },
                "DividendsCommonStockCash": {
                    "units": {"USD": [{"val": 15_000_000_000, "end": "2025-09-27"}]}
                },
            }
        }
    }

    with patch("scripts.populate_dividend_data.get_companyfacts", return_value=payload):
        with patch("scripts.populate_dividend_data.engine", _FakeEngine()):
            assert extract_sec_dividend_data("0000320193") == []


def test_extract_sec_dividend_data_returns_empty_on_fetch_error():
    with patch("scripts.populate_dividend_data.get_companyfacts", side_effect=Exception("boom")):
        with patch("scripts.populate_dividend_data.engine", _FakeEngine()):
            assert extract_sec_dividend_data("0000320193") == []


def test_normalize_currency_strips_xbrl_unit_suffixes():
    assert normalize_currency("USD/shares") == "USD"
    assert normalize_currency("CAD/shares") == "CAD"
    assert normalize_currency("EUR/per-shares") == "EUR"
    assert normalize_currency("gbp") == "GBP"
    assert normalize_currency("USD") == "USD"
    assert normalize_currency("") == "USD"
    assert normalize_currency(None) == "USD"
    assert normalize_currency("shares") == "USD"
    assert normalize_currency("US Dollar") == "USD"
    assert all(len(normalize_currency(unit)) <= 8 for unit in ("CAD/shares", "XYZ"))


def test_extract_sec_dividend_data_normalizes_non_usd_units():
    payload = {
        "facts": {
            "us-gaap": {
                "CommonStockDividendsPerShareDeclared": {
                    "units": {
                        "CAD/shares": [{"val": 0.4, "end": "2025-06-01"}],
                        "shares": [{"val": 0.9, "end": "2025-06-01"}],
                    }
                }
            }
        }
    }

    with patch("scripts.populate_dividend_data.get_companyfacts", return_value=payload):
        with patch("scripts.populate_dividend_data.engine", _FakeEngine()):
            rows = extract_sec_dividend_data(320193)

    assert {row["currency"] for row in rows} == {"CAD", "USD"}


def test_normalize_sec_dividend_rows_preserves_cik_and_drops_bad_amounts():
    sec_rows = [
        {
            "cik": "0000320193",
            "concept": "CommonStockDividendsPerShareDeclared",
            "amount": 1.5,
            "ex_dividend_date": "2025-01-01",
            "payment_date": "2025-02-01",
            "currency": "USD",
        },
        {
            "cik": "0000320193",
            "concept": "CommonStockDividendsPerShareDeclared",
            "amount": 0,
            "ex_dividend_date": "2025-01-01",
        },
        {"cik": "0000320193", "concept": "CommonStockDividendsPerShareDeclared", "amount": None},
        {"cik": "0000320193", "concept": "CommonStockDividendsPerShareDeclared", "amount": "bad"},
        {
            "cik": "0000320193",
            "amount": 2.0,
            "ex_dividend_date": "2025-01-01",
        },
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


def _run_dividend_profile(monkeypatch, openbb_payload):
    conn = _QueueConn([_Result(rowcount=1), _Result(rowcount=1), _Result(rowcount=1)])
    monkeypatch.setattr(
        dividend_data,
        "get_dividend_paying_securities",
        lambda *_args, **_kwargs: [
            {
                "security_id": "security-acr-pd",
                "ticker": "ACR-PD",
                "security_name": "Series D Preferred Stock",
                "security_type": "preferred stock",
            }
        ],
    )
    monkeypatch.setattr(
        dividend_data,
        "fetch_ticker_profile",
        lambda *_args, **_kwargs: {
            "provider": "OPENBB_YFINANCE",
            "coupon_rate": None,
            "liquidation_preference": None,
            "raw_payload": openbb_payload,
        },
    )
    populate_ticker_profiles(conn)
    return conn


def test_ticker_profile_write_appends_history_then_upserts_owned_columns(monkeypatch, capsys):
    conn = _run_dividend_profile(monkeypatch, "{}")

    load_sql, load_params = conn.executed[0]
    assert "INSERT INTO raw.ticker_profile_load" in load_sql
    assert load_params["loader"] == "populate_dividend_data"

    profile_sql, profile_params = conn.executed[1]
    assert "INSERT INTO raw.ticker_profile AS current_profile" in profile_sql
    # Name-parse columns are owned: a NULL parse clears a stale value.
    assert "coupon_rate = EXCLUDED.coupon_rate" in profile_sql
    assert "liquidation_preference = EXCLUDED.liquidation_preference" in profile_sql
    # OpenBB returned nothing, so sector/industry are preserved.
    assert "sector = EXCLUDED.sector" not in profile_sql
    assert "SEC_XBRL+OPENBB_YFINANCE" in profile_sql
    assert profile_params["coupon_rate"] is None
    assert json.loads(profile_params["raw_payload"]) == {}
    assert "UPDATE reference.securities" in conn.executed[2][0]
    capsys.readouterr()


def test_ticker_profile_write_owns_openbb_columns_when_openbb_answered(monkeypatch, capsys):
    conn = _run_dividend_profile(monkeypatch, '{"symbol": "ACR-PD", "sector": "Real Estate"}')

    profile_sql, profile_params = conn.executed[1]
    assert "sector = EXCLUDED.sector" in profile_sql
    assert json.loads(profile_params["raw_payload"]) == {
        "openbb": {"symbol": "ACR-PD", "sector": "Real Estate"}
    }
    capsys.readouterr()


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
    conn = _QueueConn(
        [
            _Result(rows=candidates),
            _Result(scalar_value=2.40),
            _Result(rowcount=1),
            _Result(scalar_value=None),
            _Result(rowcount=0),
        ]
    )

    inserted = populate_preferred_terms(conn)

    assert inserted == 1
    insert_calls = [
        sql
        for sql, _ in conn.executed
        if sql.strip().startswith("INSERT INTO preferred.security_terms")
    ]
    assert len(insert_calls) == 2
    assert "ON CONFLICT (security_id) DO NOTHING" in insert_calls[0]


def test_plausible_dividend_date_rejects_far_future_typos():
    """XBRL fact.end is only a proxy; a 2108 period end is a filer typo."""

    today = date(2026, 9, 25)

    assert plausible_dividend_date("2108-11-14", today) is None
    assert plausible_dividend_date("2031-01-01", today) is None
    assert plausible_dividend_date("2030-01-01", today) is None
    assert plausible_dividend_date("2026-09-24", today) == date(2026, 9, 24)
    assert plausible_dividend_date("2027-06-30", today) == date(2027, 6, 30)
    assert plausible_dividend_date("2005-03-31", today) == date(2005, 3, 31)
    assert plausible_dividend_date("not-a-date", today) is None
    assert plausible_dividend_date(None, today) is None


def test_sec_concepts_are_all_per_share():
    """Aggregate-dollar concepts made dividend_yield meaningless when summed."""

    for concept in SEC_DIVIDEND_CONCEPTS:
        assert "PerShare" in concept, concept


def test_normalize_sec_dividend_rows_drops_aggregate_concepts():
    """The normalizer is the real ingest path: it must refuse aggregate dollars."""

    rows = normalize_sec_dividend_rows(
        "BAC",
        [
            {
                "cik": "0000070858",
                "concept": "CommonStockDividendsPerShareDeclared",
                "amount": 4.3,
                "ex_dividend_date": "2025-12-31",
            },
            {
                "cik": "0000070858",
                "concept": "DividendsCommonStockCash",
                "amount": 20_153_000_000,
                "ex_dividend_date": "2025-12-31",
            },
        ],
    )

    assert len(rows) == 1
    assert rows[0]["amount"] == 4.3
    assert rows[0]["concept"] == "CommonStockDividendsPerShareDeclared"


def test_normalize_sec_dividend_rows_drops_implausible_dates():
    rows = normalize_sec_dividend_rows(
        "MTEX",
        [
            {
                "concept": "CommonStockDividendsPerShareDeclared",
                "amount": 0.5,
                "ex_dividend_date": "2108-11-14",
            },
            {
                "concept": "CommonStockDividendsPerShareDeclared",
                "amount": 0.12,
                "ex_dividend_date": "2018-05-10",
            },
        ],
    )

    assert [r["amount"] for r in rows] == [0.12]


def test_normalize_openbb_dividend_rows_tags_empty_concept():
    frame = pd.DataFrame([{"Date": "2026-06-01", "Dividends": 0.5}])
    rows = normalize_openbb_dividend_rows("AAPL", frame)

    assert len(rows) == 1
    assert rows[0]["provider"] == "OPENBB"
    assert rows[0]["concept"] == ""


def test_normalize_sec_dividend_rows_drops_aggregate_amounts_in_per_share_concepts():
    """HIG tags 1,125,000,000 as PreferredStockDividendsPerShareDeclared."""

    rows = normalize_sec_dividend_rows(
        "HIG",
        [
            {
                "concept": "PreferredStockDividendsPerShareDeclared",
                "amount": 1_125_000_000,
                "ex_dividend_date": "2019-09-30",
            },
            {
                "concept": "PreferredStockDividendsPerShareDeclared",
                "amount": 12.5,
                "ex_dividend_date": "2019-09-30",
            },
        ],
    )

    assert [r["amount"] for r in rows] == [12.5]


def test_liquidation_preference_ignores_nominal_par_value():
    from scripts.populate_dividend_data import parse_liquidation_preference

    assert parse_liquidation_preference("Class A common stock, par value $0.0001") is None
    assert parse_liquidation_preference("Preferred Stock, par value $25 per share") == 25.0
    assert parse_liquidation_preference("Series B, liquidation preference $1,000") == 1000.0
    assert (
        parse_liquidation_preference(
            "5.50% Series A Cumulative Preferred Shares, par value$0.001 per share "
            "($25.00 liquidation preference per share)"
        )
        == 25.0
    )
