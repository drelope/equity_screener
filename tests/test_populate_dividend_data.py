import json
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from scripts import populate_dividend_data as dividend_data
from scripts.populate_dividend_data import (
    SEC_DIVIDEND_CONCEPTS,
    cadence_from_events,
    extract_sec_dividend_data,
    get_latest_dividend_rate,
    infer_frequency,
    load_security_ids,
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
    assert infer_frequency([95, 106]) == "Semi-annual", (
        "median 100.5 sits past the quarterly border"
    )
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


class _EmptyMappings:
    def mappings(self):
        return []


class _MappingsConn:
    """Records the statement and returns an empty mappings cursor."""

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(str(sql))
        return _EmptyMappings()


def test_load_security_ids_historical_only_uses_historical_universe():
    """Regression: the writer passed historical_only to load_security_ids,
    which did not accept it, so the dividend stage exited 1 mid-nightly."""
    conn = _MappingsConn()

    load_security_ids(conn, historical_only=True)

    assert "s.historical = TRUE" in conn.statements[0]
    assert "s.active = TRUE" not in conn.statements[0]


def test_load_security_ids_include_historical_unions_both():
    conn = _MappingsConn()

    load_security_ids(conn, include_historical=True)

    assert "(s.active = TRUE OR s.historical = TRUE)" in conn.statements[0]


def test_load_security_ids_defaults_to_active():
    conn = _MappingsConn()

    load_security_ids(conn)

    assert "s.active = TRUE" in conn.statements[0]
    assert "s.historical" not in conn.statements[0]


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
    assert rows[0]["feed"] == "yfinance", "untagged frames are the yfinance feed"


def test_normalize_openbb_dividend_rows_keeps_fmp_feed_and_both_amounts():
    """FMP's amount is as declared; adjusted_amount restates it after splits."""
    frame = pd.DataFrame(
        [
            {
                "ex_dividend_date": "2025-11-03",
                "amount": 0.40,
                "adjusted_amount": 0.1333,
                "payment_date": "2025-11-20",
                "declaration_date": "2025-10-01",
                "frequency": float("nan"),
            }
        ]
    )
    frame.attrs["feed"] = "fmp"

    (row,) = normalize_openbb_dividend_rows("WLFC", frame)

    assert row["feed"] == "fmp"
    assert row["amount"] == 0.40
    assert row["adjusted_amount"] == 0.1333
    assert row["declaration_date"] == date(2025, 10, 1)
    assert row["frequency"] == "Annual", "a NaN cadence must not break normalization"
    assert row["amount_feed"] == "fmp", "without a reconciled amount the feed's own is used"


def test_a_reconciled_amount_keeps_its_amount_feed():
    """CHA: Polygon confirmed Yahoo's 0.92, so the fmp row carries Yahoo's amount."""
    frame = pd.DataFrame(
        [
            {
                "ex_dividend_date": "2025-12-08",
                "amount": 0.92,
                "adjusted_amount": 0.92,
                "amount_feed": "yfinance",
            }
        ]
    )
    frame.attrs["feed"] = "fmp"

    (row,) = normalize_openbb_dividend_rows("CHA", frame)

    assert (row["feed"], row["amount_feed"], row["amount"]) == ("fmp", "yfinance", 0.92)


def test_undeclared_far_future_coupons_are_projections_not_announcements():
    """FMP lists GECCG note coupons out to 2029; only declared or near dates count."""
    from datetime import timedelta

    today = date.today()
    frame = pd.DataFrame(
        [
            {"ex_dividend_date": today + timedelta(days=30), "amount": 0.48},
            {"ex_dividend_date": today + timedelta(days=400), "amount": 0.48},
            {
                "ex_dividend_date": today + timedelta(days=300),
                "amount": 0.36,
                "declaration_date": today - timedelta(days=10),
            },
        ]
    )
    frame.attrs["feed"] = "fmp"

    kept = sorted(r["ex_dividend_date"] for r in normalize_openbb_dividend_rows("X", frame))

    assert kept == [today + timedelta(days=30), today + timedelta(days=300)]


def test_the_incoming_feed_replaces_stale_rows_only_inside_its_own_range():
    """GFIOF: FMP dates every event two days off Yahoo; both must not be kept."""
    import pytest

    pytest.importorskip("sqlalchemy")
    from sqlalchemy import text

    from src.crispdm.db import engine

    try:
        conn = engine.connect()
    except Exception:  # noqa: BLE001
        pytest.skip("no database available")
    with conn:
        trans = conn.begin()
        try:
            sid = conn.execute(
                text("SELECT security_id FROM reference.securities ORDER BY ticker LIMIT 1")
            ).scalar()
            conn.execute(
                text("DELETE FROM raw.dividend_data WHERE security_id = :sid"), {"sid": sid}
            )
            for ex_date, feed in [
                ("2019-03-01", "yfinance"),  # before FMP's first event: kept
                ("2024-02-20", "yfinance"),  # 12 days before it: a distinct payment, kept
                ("2024-02-28", "fmp"),  # same feed, before its first event: kept
                ("2024-03-01", "yfinance"),  # FMP's first payment dated 2 days off: dropped
                ("2024-04-10", "fmp"),  # an ex-date FMP no longer lists: dropped
                ("2024-06-01", "yfinance"),  # same date in FMP: overwritten by upsert
            ]:
                conn.execute(
                    text(
                        "INSERT INTO raw.dividend_data (security_id, ex_dividend_date, "
                        "amount, provider, feed) VALUES (:sid, :d, 0.1, 'OPENBB', :f)"
                    ),
                    {"sid": sid, "d": ex_date, "f": feed},
                )
            incoming = [
                {"sec_id": sid, "provider": "OPENBB", "feed": "fmp", "ex_date": d}
                for d in (date(2024, 3, 3), date(2024, 6, 1))
            ]

            removed = dividend_data._drop_superseded_feed_rows(conn, incoming, "1900-01-01", None)
            left = (
                conn.execute(
                    text(
                        "SELECT ex_dividend_date FROM raw.dividend_data "
                        "WHERE security_id = :sid ORDER BY 1"
                    ),
                    {"sid": sid},
                )
                .scalars()
                .all()
            )
        finally:
            trans.rollback()

    assert removed == 2
    assert left == [date(2019, 3, 1), date(2024, 2, 20), date(2024, 2, 28), date(2024, 6, 1)]


def test_a_payment_listed_under_two_ex_dates_is_kept_once():
    """CAT 11-19 payment at FMP: 10-19 (declared 10-14) and 10-26 (undeclared)."""
    frame = pd.DataFrame(
        [
            {
                "ex_dividend_date": "2026-10-26",
                "amount": 1.63,
                "record_date": "2026-10-26",
                "payment_date": "2026-11-19",
            },
            {
                "ex_dividend_date": "2026-10-19",
                "amount": 1.63,
                "payment_date": "2026-11-19",
                "declaration_date": "2026-10-14",
            },
            # RYAAY: the copy's ex-date falls after the shared record date.
            {
                "ex_dividend_date": "2026-09-11",
                "amount": 0.4453,
                "record_date": "2026-08-07",
                "payment_date": "2026-09-28",
                "declaration_date": "2026-07-23",
            },
            {
                "ex_dividend_date": "2026-08-07",
                "amount": 0.44343,
                "record_date": "2026-08-07",
                "payment_date": "2026-09-28",
                "declaration_date": "2026-07-23",
            },
            # BCIC: a special and a regular paid together are two payments.
            {"ex_dividend_date": "2026-05-15", "amount": 0.09, "payment_date": "2026-05-29"},
            {"ex_dividend_date": "2026-05-18", "amount": 0.03, "payment_date": "2026-05-29"},
        ]
    )
    frame.attrs["feed"] = "fmp"

    kept = [r["ex_dividend_date"] for r in normalize_openbb_dividend_rows("X", frame)]

    assert kept == [
        date(2026, 5, 15),
        date(2026, 5, 18),
        date(2026, 8, 7),
        date(2026, 10, 19),
    ]


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


def test_parse_date_accepts_numeric_and_month_name_dates():
    assert parse_date("2028-07-30") == date(2028, 7, 30)
    assert parse_date("7/30/2028") == date(2028, 7, 30)
    assert parse_date("October 30, 2028") == date(2028, 10, 30)
    assert parse_date("Oct 30, 2028") == date(2028, 10, 30)
    assert parse_date("October 30 2028") == date(2028, 10, 30)


def test_parse_fixed_period_end_reads_the_conversion_date_when_the_title_carries_one():
    from scripts.populate_dividend_data import parse_fixed_period_end

    assert parse_fixed_period_end(
        "6.00% Fixed-to-Floating Rate Non-Cumulative Perpetual Preferred Stock "
        "with a fixed rate period through 7/30/2028"
    ) == date(2028, 7, 30)
    assert parse_fixed_period_end("Fixed Rate Notes until 2028-07-30") == date(2028, 7, 30)
    assert parse_fixed_period_end("Fixed-to-Floating Rate Notes due October 30, 2028") == date(
        2028, 10, 30
    )


def test_parse_fixed_period_end_is_none_without_an_explicit_date():
    from scripts.populate_dividend_data import parse_fixed_period_end

    # The real corpus titles name the structure but carry no date, so the field
    # must stay NULL rather than derive one.
    assert (
        parse_fixed_period_end(
            "8.625% Fixed-to-Floating Series C Cumulative Redeemable Preferred Stock"
        )
        is None
    )
    assert (
        parse_fixed_period_end("Series A Floating-Rate Non-Cumulative Perpetual Preferred Stock")
        is None
    )
    # A month-and-year token has no day, so it is not a stored date.
    assert parse_fixed_period_end("Fixed Rate Notes due Apr 2028") is None


def test_parse_floating_spread_reads_the_reference_rate_margin():
    from scripts.populate_dividend_data import parse_floating_spread

    assert parse_floating_spread("... Term SOFR + 5.592% ...") == 5.592
    assert parse_floating_spread("plus 4.15% per annum") == 4.15
    assert parse_floating_spread("a spread of 3.00% over the benchmark") == 3.0
    assert parse_floating_spread("LIBOR + 2.375%") == 2.375


def test_parse_floating_spread_ignores_structure_without_a_margin():
    from scripts.populate_dividend_data import parse_floating_spread

    # "Fixed-to-Floating" and a hyphen in "Non-Cumulative" are not a spread.
    assert (
        parse_floating_spread(
            "Fixed-to-Floating Rate Non-Cumulative Perpetual Preferred Stock, Series A"
        )
        is None
    )
    assert parse_floating_spread("6.625% Fixed-to-Floating Rate Non-Cumulative Series I") is None


def test_a_depositary_title_gives_no_liquidation_preference():
    """USB-PP's title quotes the underlying share's $1.00 par, not the receipt's $25."""
    from scripts.populate_dividend_data import summarize_ticker_profile

    title = (
        "Depositary Shares (each representing 1/1,000th interest in a share of Series K "
        "Non-Cumulative Perpetual Preferred Stock, par value $1.00)"
    )

    assert (
        summarize_ticker_profile("USB-PP", title, "preferred stock")["liquidation_preference"]
        is None
    )
    assert (
        summarize_ticker_profile("X-PA", "Preferred Stock, par value $25 per share")[
            "liquidation_preference"
        ]
        == 25.0
    )


def test_special_is_taken_from_the_providers_label_not_the_derived_cadence():
    from scripts.populate_dividend_data import is_special_dividend

    assert is_special_dividend("Special") is True
    assert is_special_dividend(" special ") is True
    assert is_special_dividend("Irregular") is False  # a cadence, not a one-off
    assert is_special_dividend("Quarterly") is False
    assert is_special_dividend(None) is False


def test_the_dividend_upsert_executes_against_postgres_and_updates_is_special():
    """The real statement, because a mocked connection cannot see driver typing errors.

    psycopg binds parameters server-side; reusing one parameter under two inferred types
    (a varchar column and a cast) raised AmbiguousParameter at run time and halted a
    nightly while every mocked test passed. Runs in a transaction that is always rolled
    back.
    """
    from datetime import date, datetime, timezone

    pytest.importorskip("sqlalchemy")
    try:
        from sqlalchemy import text

        from scripts.populate_dividend_data import DIVIDEND_UPSERT
        from src.crispdm.db import engine

        conn = engine.connect()
        conn.exec_driver_sql("SELECT 1")
        conn.rollback()  # the probe autobegins; start a transaction we control below
    except Exception:  # pragma: no cover - environments without a database
        pytest.skip("no database available")
    trans = conn.begin()
    try:
        security_id = conn.execute(
            text("SELECT security_id FROM reference.securities LIMIT 1")
        ).scalar()
        if security_id is None:
            pytest.skip("no securities in the database")
        row = {
            "sec_id": security_id,
            "ex_date": date(1900, 1, 1),
            "decl_date": None,
            "rec_date": None,
            "pay_date": None,
            "amount": 1.0,
            "adjusted_amount": None,
            "frequency": "Quarterly",
            "currency": "USD",
            "provider": "TEST_ROLLBACK",
            "feed": None,
            "amount_feed": None,
            "concept": "",
            "retrieved_at": datetime.now(timezone.utc),
            "is_special": False,
        }
        conn.execute(DIVIDEND_UPSERT, [row])
        conn.execute(
            DIVIDEND_UPSERT, [{**row, "is_special": True, "amount": 2.0}]
        )  # the conflict path
        got = conn.execute(
            text(
                "SELECT is_special, amount FROM raw.dividend_data "
                "WHERE security_id = :s AND ex_dividend_date = :d AND provider = 'TEST_ROLLBACK'"
            ),
            {"s": security_id, "d": date(1900, 1, 1)},
        ).one()
        assert got.is_special is True and float(got.amount) == 2.0
    finally:
        trans.rollback()
        conn.close()
