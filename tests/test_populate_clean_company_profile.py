from datetime import date, datetime, timezone
from decimal import Decimal

from scripts import populate_clean_company_profile as clean_profiles


def test_clean_profile_normalizes_ticker_epoch_fields_and_52_week_key():
    source = {
        "security_id": "security-abr",
        "ticker": "abr",
        "provider": "OPENBB_YFINANCE",
        "retrieved_at": datetime(2026, 10, 2, tzinfo=timezone.utc),
        "raw_payload": {
            "symbol": "ABR",
            "name": "Arbor Realty Trust, Inc.",
            "52_week_change": -0.689461,
            "dividend_date": 1787875200,
            "ex_dividend_date": 1786665600000,
            "regular_market_time": 1790884803,
            "company_officers": [],
        },
    }
    column_types = {
        "symbol": "text",
        "pct_change_52w": "numeric",
        "dividend_date": "date",
        "ex_dividend_date": "date",
        "regular_market_time": "timestamp with time zone",
    }

    values, officers = clean_profiles._clean_profile_row(source, column_types)

    assert values["symbol"] == "ABR"
    assert values["pct_change_52w"] == Decimal("-0.689461")
    assert values["dividend_date"] == date(2026, 8, 28)
    assert values["ex_dividend_date"] == date(2026, 8, 14)
    assert values["regular_market_time"].tzinfo == timezone.utc
    assert '"52_week_change": -0.689461' in values["source_payload"]
    assert officers == []


def test_missing_officer_pay_stays_null_and_zero_values_stay_zero():
    rows = clean_profiles._clean_officer_rows(
        "ABR",
        "Arbor Realty Trust, Inc.",
        [
            {"name": "Officer A", "title": "CEO", "totalPay": 0},
            {"name": "Officer B", "title": "CFO"},
        ],
    )

    assert rows[0]["total_pay"] == 0
    assert rows[1]["total_pay"] is None
    assert [row["officer_no"] for row in rows] == [1, 2]


def test_dividend_yield_fraction_requires_unit_corroboration():
    yield_fraction, source_unit = clean_profiles._normalize_dividend_yield(
        25.34, 0.94, 3.71, "OPENBB_YFINANCE"
    )
    assert yield_fraction == Decimal("0.2534")
    assert source_unit == "percent_points"

    yield_fraction, source_unit = clean_profiles._normalize_dividend_yield(
        0.2534, 0.94, 3.71, "OPENBB_YFINANCE"
    )
    assert yield_fraction == Decimal("0.2534")
    assert source_unit == "fraction"

    yield_fraction, source_unit = clean_profiles._normalize_dividend_yield(
        8.0, 0.94, 3.71, "OPENBB_YFINANCE"
    )
    assert yield_fraction is None
    assert source_unit == "unverified"


def test_combined_source_payload_uses_nested_openbb_fields():
    source = {
        "security_id": "security-abr",
        "ticker": "ABR",
        "provider": "SEC_XBRL+OPENBB_YFINANCE",
        "retrieved_at": datetime(2026, 10, 2, tzinfo=timezone.utc),
        "raw_payload": {
            "sec_xbrl": {"available": True},
            "openbb": {
                "symbol": "ABR",
                "name": "Arbor Realty Trust, Inc.",
                "dividend_yield": 25.34,
                "dividend_rate": 0.94,
                "current_price": 3.71,
            },
            "company_officers": [{"name": "Officer A"}],
        },
    }
    column_types = {
        "symbol": "text",
        "pct_change_52w": "numeric",
        "dividend_yield": "numeric",
        "dividend_rate": "numeric",
        "current_price": "numeric",
        "dividend_yield_fraction": "numeric",
        "dividend_yield_source_unit": "character varying",
    }

    values, officers = clean_profiles._clean_profile_row(source, column_types)

    assert values["symbol"] == "ABR"
    assert values["dividend_yield_fraction"] == Decimal("0.2534")
    assert values["dividend_yield_source_unit"] == "percent_points"
    assert '"sec_xbrl": {"available": true}' in values["source_payload"]
    assert len(officers) == 1
