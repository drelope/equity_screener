import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

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


def _envelope_source(openbb, **extra):
    return {
        "security_id": "security-x",
        "ticker": "x",
        "provider": "SEC_XBRL+OPENBB_YFINANCE",
        "retrieved_at": datetime(2026, 10, 2, tzinfo=timezone.utc),
        "cik": "0000000001",
        "issuer_id": 7,
        "raw_payload": {"openbb": openbb, **extra},
    }


def test_openbb_identity_wins_over_legacy_top_level_keys_and_blanks_are_skipped():
    source = _envelope_source(
        {"symbol": " abr ", "name": "  ", "long_name": "Arbor Realty Trust, Inc."},
        symbol="STALE",
        name="Stale Name",
    )
    source["raw_payload"]["symbol"] = "STALE"

    values, _ = clean_profiles._clean_profile_row(source, {"symbol": "text"})

    assert values["symbol"] == "ABR"
    assert values["parent_name"] == "Arbor Realty Trust, Inc."
    assert values["cik"] == "0000000001"
    assert values["issuer_id"] == 7


def test_non_finite_numerics_load_as_null_and_are_flagged():
    source = _envelope_source(
        {
            "symbol": "ABR",
            "name": "Arbor",
            "trailing_p_e": "Infinity",
            "forward_p_e": "NaN",
            "price_to_sales": 1.5,
        }
    )
    column_types = {
        "trailing_p_e": "numeric",
        "forward_p_e": "numeric",
        "price_to_sales": "numeric",
    }

    values, _ = clean_profiles._clean_profile_row(source, column_types)

    assert values["trailing_p_e"] is None
    assert values["forward_p_e"] is None
    assert values["price_to_sales"] == Decimal("1.5")
    assert values["non_finite_fields"] == ["forward_p_e", "trailing_p_e"]
    assert '"trailing_p_e": "Infinity"' in values["source_payload"]


def test_unmapped_scalars_are_preserved_and_listed_and_nested_arrays_are_routed():
    source = _envelope_source(
        {
            "symbol": "ABR",
            "name": "Arbor",
            "ebitda": 123,
            "company_officers": [{"name": "A"}],
            "executive_team": [{"name": "A"}],
            "corporate_actions": [],
        },
        sec_xbrl={"coupon_rate": 8.5},
    )

    values, officers = clean_profiles._clean_profile_row(source, {"symbol": "text", "name": "text"})

    assert values["unmapped_source_keys"] == ["ebitda"]
    payload = json.loads(values["source_payload"])
    assert payload["unmapped"] == {"ebitda": 123}
    assert payload["sec_xbrl"] == {"coupon_rate": 8.5}
    assert "company_officers" not in payload["openbb"]
    assert "executive_team" not in payload["unmapped"]
    assert officers == [{"name": "A"}]


def test_earnings_timestamp_is_an_instant_not_a_date():
    value = clean_profiles._coerce_profile_value(
        "earnings_timestamp", "timestamp with time zone", 1790884803
    )

    assert value == datetime(2026, 10, 1, 20, 0, 3, tzinfo=timezone.utc)


def test_corporate_actions_flatten_to_typed_rows():
    source = _envelope_source(
        {
            "symbol": "RAY",
            "name": "Raytech",
            "corporate_actions": [
                {
                    "header": "Ticker Change",
                    "message": "RAY is trading under new symbol ATTT effective Sep. 10, 2026",
                    "meta": {
                        "eventType": "TICKER_CHANGE",
                        "newTicker": "ATTT",
                        "dateEpochMs": 1789012800000,
                    },
                },
                {
                    "header": "Dividend",
                    "message": "cash dividend",
                    "meta": {
                        "eventType": "DIVIDEND",
                        "amount": "0.007",
                        "dateEpochMs": 1791518400000,
                    },
                },
            ],
        }
    )

    rows = clean_profiles._clean_corporate_action_rows(source, "RAY")

    assert [row["action_no"] for row in rows] == [1, 2]
    assert rows[0]["event_type"] == "TICKER_CHANGE"
    assert rows[0]["new_ticker"] == "ATTT"
    assert rows[0]["effective_date"] == date(2026, 9, 10)
    assert rows[0]["security_id"] == "security-x"
    assert rows[1]["amount"] == Decimal("0.007")
    assert set(rows[0]) == set(clean_profiles.CORPORATE_ACTION_COLUMNS)


def test_officer_rows_carry_every_insert_column():
    rows = clean_profiles._clean_officer_rows("ABR", "Arbor", [{"name": "A"}])

    assert set(rows[0]) == set(clean_profiles.OFFICER_COLUMNS)


def test_harmonize_backfills_missing_issuer_attributes_from_primary():
    rows = [
        {
            "symbol": "ABR",
            "parent_name": "Arbor Realty Trust, Inc.",
            "cik": "0000000001",
            "sector": "Real Estate",
            "industry": "REIT - Mortgage",
            "industry_key": "reit-mortgage",
            "city": "Bethesda",
            "employees": 339,
            "last_fiscal_year_end": date(2025, 12, 31),
            "current_price": Decimal("3.71"),
            "market_cap": Decimal("2300000000"),
            "exchange": "NYQ",
            "market": "us_market",
        },
        {
            "symbol": "ABR-PD",
            "parent_name": "Arbor Realty Trust, Inc.",
            "cik": "0000000001",
            "sector": None,
            "industry": "   ",
            "industry_key": None,
            "city": None,
            "employees": None,
            "last_fiscal_year_end": None,
            "current_price": Decimal("25.00"),
            "market_cap": Decimal("1000000000"),
            "exchange": "PNK",
            "market": None,
        },
    ]

    clean_profiles.harmonize_issuer_attributes(rows)
    thin = rows[1]

    assert thin["sector"] == "Real Estate"
    assert thin["industry"] == "REIT - Mortgage"
    assert thin["industry_key"] == "reit-mortgage"
    assert thin["city"] == "Bethesda"
    assert thin["employees"] == 339
    assert thin["last_fiscal_year_end"] == date(2025, 12, 31)
    assert thin["current_price"] == Decimal("25.00")
    assert thin["market_cap"] == Decimal("1000000000")
    assert thin["exchange"] == "PNK"
    assert thin["market"] is None


def test_harmonize_uses_primary_first_as_donor_and_fills_primary_from_siblings():
    rows = [
        {
            "symbol": "AEM",
            "cik": "0000000002",
            "sector": "Basic Materials",
            "total_revenue": None,
            "country": None,
        },
        {
            "symbol": "AEMRF",
            "cik": "0000000002",
            "sector": None,
            "total_revenue": Decimal("8000000000"),
            "country": "Canada",
        },
    ]

    clean_profiles.harmonize_issuer_attributes(rows)

    assert rows[0]["sector"] == "Basic Materials"
    assert rows[1]["sector"] == "Basic Materials"
    assert rows[1]["total_revenue"] == Decimal("8000000000")
    assert rows[0]["total_revenue"] == Decimal("8000000000")
    assert rows[0]["country"] == "Canada"


def test_harmonize_overwrites_never_and_leaves_single_and_null_cik_alone():
    rows = [
        {"symbol": "A", "cik": "0000000003", "city": "Toronto", "sector": "X"},
        {"symbol": "A-PR", "cik": "0000000003", "city": "Vancouver", "sector": None},
        {"symbol": "B", "cik": "0000000004", "city": "New York", "sector": None},
        {"symbol": "C", "cik": None, "city": None, "sector": None},
    ]

    clean_profiles.harmonize_issuer_attributes(rows)

    assert rows[0]["city"] == "Toronto"
    assert rows[1]["city"] == "Vancouver"
    assert rows[1]["sector"] == "X"
    assert rows[2]["city"] == "New York"
    assert rows[2]["sector"] is None
    assert rows[3]["city"] is None
    assert rows[3]["sector"] is None


def test_harmonize_skips_single_listing_issuers():
    rows = [{"symbol": "BRK-B", "cik": "0000000005", "sector": "Financials", "city": "Omaha"}]

    clean_profiles.harmonize_issuer_attributes(rows)

    assert rows[0] == {
        "symbol": "BRK-B",
        "cik": "0000000005",
        "sector": "Financials",
        "city": "Omaha",
    }


def test_view_issuer_keys_are_a_subset_of_the_etl_fill_list():
    """Every issuer key the hierarchy view can still flag must be fillable.

    clean.v_company_hierarchy (V0064) flags a key only when a data column
    disagrees across a CIK's listings; the cleaner must be able to harmonize
    that key, or thin listings would drift forever. cik and issuer_id are the
    exception: they are provenance attached by the security join, not data the
    cleaner derives. The canonical array is read from the LATEST migration
    that declares issuer_keys, so editing either side without the other fails
    loudly.
    """
    repo = Path(__file__).resolve().parents[1]
    declaring = []
    for path in repo.glob("sql/migrations/V*.sql"):
        text = path.read_text()
        match = re.search(r"ARRAY\[\s*([^\]]*?)\]::\w+\[\]\s+AS\s+issuer_keys", text, flags=re.S)
        if match:
            declaring.append((path.stem, match.group(1)))
    assert declaring, "no migration declares issuer_keys"
    latest_stem, array_literal = sorted(declaring, key=lambda item: item[0])[-1]

    view_keys = set(re.findall(r"'([^']*)'", array_literal))
    assert view_keys, f"issuer_keys array in {latest_stem} is empty"

    assert view_keys - {"cik", "issuer_id"} <= set(clean_profiles.ISSUER_ATTRIBUTE_COLUMNS), (
        f"{latest_stem} flags an issuer key the cleaner cannot harmonize; add it to "
        "ISSUER_ATTRIBUTE_COLUMNS or remove it from the view"
    )
