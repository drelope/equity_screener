"""The FMP-first/yfinance-fallback autofill: every field filled, rules still hold.

The builder is exercised with synthetic company data, so no provider and no database are
needed; ``equity_command`` is tested with a fake ``obb`` to prove the fallback ordering.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from app import analysis_autofill as autofill
from app import analysis_schema as schema
from src.crispdm import openbb_client as client
from src.crispdm.config import settings

TODAY = pd.Timestamp("2026-10-20")


def _sample_data() -> autofill.CompanyData:
    return autofill.CompanyData(
        ticker="TEST",
        profile={
            "name": "Test Corp",
            "sector": "Industrials",
            "industry_category": "Machinery",
            "stock_exchange": "NYSE",
            "hq_country": "United States",
            "employees": 12000,
            "long_description": "Test Corp makes industrial equipment.",
            "ceo": "Jane Doe",
            "currency": "USD",
            "market_cap": 15e9,
            "last_price": 100.0,
            "beta": 1.1,
        },
        quote={"last_price": 100.0, "market_cap": 15e9, "ma50": 98, "ma200": 95},
        consensus={
            "target_consensus": 115.0,
            "target_high": 135.0,
            "target_low": 90.0,
            "target_median": 114.0,
            "current_price": 100.0,
        },
        ratios={
            "gross_profit_margin": 0.42,
            "operating_profit_margin": 0.18,
            "bottom_line_profit_margin": 0.12,
            "current_ratio": 1.8,
            "debt_to_equity": 0.6,
            "price_to_earnings": 18.0,
            "price_to_book": 2.5,
            "dividend_yield": 0.025,
        },
        metrics={
            "market_cap": 15e9,
            "ev_to_ebitda": 11.0,
            "net_debt_to_ebitda": 1.2,
            "earnings_yield": 0.055,
            "free_cash_flow_yield": 0.045,
            "return_on_equity": 0.17,
            "return_on_invested_capital": 0.14,
            "stock_based_compensation_to_revenue": 0.01,
        },
        income=[
            {
                "period_ending": "2025-12-31",
                "revenue": 1e10,
                "gross_profit": 4.2e9,
                "total_operating_income": 1.8e9,
                "bottom_line_net_income": 1.2e9,
                "ebitda": 2.2e9,
                "diluted_earnings_per_share": 4.0,
            },
            {
                "period_ending": "2024-12-31",
                "revenue": 9.2e9,
                "gross_profit": 3.7e9,
                "total_operating_income": 1.55e9,
                "bottom_line_net_income": 1.05e9,
                "ebitda": 1.95e9,
                "diluted_earnings_per_share": 3.5,
            },
        ],
        balance=[
            {
                "total_assets": 2e10,
                "total_debt": 6e9,
                "cash_and_cash_equivalents": 2e9,
                "total_common_equity": 9e9,
                "total_current_assets": 7e9,
                "total_current_liabilities": 4e9,
            }
        ],
        cash=[
            {
                "operating_cash_flow": 1.6e9,
                "free_cash_flow": 1.1e9,
                "capital_expenditure": -5e8,
                "stock_based_compensation": 1e8,
                "net_dividends_paid": -4e8,
                "repurchase_of_common_equity": -2e8,
                "change_in_working_capital": -5e7,
                "net_income": 1.2e9,
            },
            {"operating_cash_flow": 1.4e9, "capital_expenditure": -4e8},
        ],
        insider=[
            {"transaction_date": "2026-06-01", "transaction_type": "P-Purchase"},
            {"transaction_date": "2026-05-01", "transaction_type": "S-Sale"},
        ],
        peers=[{"symbol": "AAA", "name": "Alpha"}, {"symbol": "BBB", "name": "Beta"}],
        price_target=[
            {"published_date": "2026-09-01", "price_target": 110.0},
            {"published_date": "2026-03-01", "price_target": 105.0},
        ],
        prices=[
            {"date": TODAY - pd.Timedelta(days=30 * i), "close": 100 - i * 0.3} for i in range(60)
        ],
        providers={
            "profile": "fmp",
            "income": "fmp",
            "balance": "fmp",
            "cash": "fmp",
            "ratios": "fmp",
            "metrics": "fmp",
            "consensus": "yfinance",
            "quote": "fmp",
            "prices": "yfinance",
        },
    )


MACRO = {
    "IG_OAS": {"value": 0.85, "as_of": "2026-10-19", "source": "FRED"},
    "HY_OAS": {"value": 3.2, "as_of": "2026-10-19", "source": "FRED"},
    "UST_10Y": {"value": 4.1, "as_of": "2026-10-19", "source": "FMP"},
    "UST_2Y": {"value": 3.8, "as_of": "2026-10-19", "source": "FMP"},
}


def _payload(data=None, macro=None):
    return autofill.build_payload(
        "TEST", data or _sample_data(), macro=MACRO if macro is None else macro, today=TODAY
    )


# --- the generated worksheet -------------------------------------------------------


def test_every_field_is_filled_not_only_the_required_ones():
    payload = _payload()

    for section in schema.SECTIONS:
        values = payload["sections"][section.id]
        for field in section.all_fields:
            raw = values.get(field.id)
            if field.kind == "score":
                assert isinstance(raw, int) and 1 <= raw <= 10, (section.id, field.id, raw)
            else:
                assert str(raw or "").strip(), (section.id, field.id, raw)


def test_the_generated_worksheet_passes_every_final_rule():
    payload = _payload()

    assert schema.validate(payload) == []
    assert schema.validate_draft(payload) == []
    assert schema.missing_required_fields(payload) == {}
    assert schema.prior_steps_complete(payload) is True


def test_the_recommendation_is_safe_because_steps_1_to_17_are_complete():
    payload = _payload()

    assert payload["sections"]["final"]["recommendation"] in ("Buy", "Add", "Hold", "Trim", "Sell")
    filled, total = schema.completion(payload)
    assert filled == total


def test_missing_data_still_produces_a_valid_worksheet():
    payload = _payload(autofill.CompanyData(ticker="EMPTY"), macro={})

    assert schema.validate(payload) == []
    assert schema.validate_draft(payload) == []
    assert payload["sections"]["macro"]["credit_verdict"] == "Neutral"
    assert "not loaded" in payload["sections"]["macro"]["macro_backdrop"]


def test_the_macro_section_reads_the_stored_observations():
    payload = _payload()

    assert "IG OAS" in payload["sections"]["macro"]["macro_backdrop"]
    assert payload["sections"]["macro"]["credit_verdict"] == "Bullish"
    assert "0.85" in payload["sections"]["macro"]["ig_spreads"]
    assert "raw.macro_series" in payload["sections"]["macro"]["sources"]


def test_sources_name_the_provider_that_answered_each_command():
    payload = _payload()

    sources = payload["sections"]["valuation"]["sources"]
    assert "FMP" in sources
    assert "YFINANCE analyst consensus" in sources
    assert "app.analysis_autofill" in sources


def test_analog_table_has_three_historical_windows_and_a_usable_base_rate():
    payload = _payload()
    analog = payload["sections"]["analog"]

    assert analog["similar_setups"].count("| Same security") >= 3
    assert analog["base_rate"].endswith("%")


# --- provider fallback -------------------------------------------------------------


def _fake_obb(**commands):
    equity = SimpleNamespace(**commands)
    return SimpleNamespace(equity=equity)


@pytest.fixture
def fmp_first(monkeypatch):
    monkeypatch.setattr(settings, "openbb_provider", None)
    monkeypatch.setattr(client, "_fmp_throttle", lambda: None)


def test_equity_command_falls_back_to_yfinance_when_fmp_fails(fmp_first, monkeypatch):
    calls = []

    def profile(**kwargs):
        calls.append(kwargs["provider"])
        if kwargs["provider"] == "fmp":
            raise RuntimeError("402 premium endpoint")
        return pd.DataFrame([{"symbol": kwargs["symbol"], "name": "From Yahoo"}])

    monkeypatch.setattr(client, "obb", _fake_obb(profile=profile))

    provider, frame = client.equity_command("profile", "ABC")

    assert calls == ["fmp", "yfinance"]
    assert provider == "yfinance"
    assert frame.iloc[0]["name"] == "From Yahoo"


def test_equity_command_tries_yfinance_when_fmp_returns_nothing(fmp_first, monkeypatch):
    calls = []

    def profile(**kwargs):
        calls.append(kwargs["provider"])
        if kwargs["provider"] == "fmp":
            return pd.DataFrame()
        return pd.DataFrame([{"symbol": kwargs["symbol"], "name": "From Yahoo"}])

    monkeypatch.setattr(client, "obb", _fake_obb(profile=profile))

    provider, frame = client.equity_command("profile", "ABC")

    assert calls == ["fmp", "yfinance"]
    assert provider == "yfinance"
    assert not frame.empty


def test_fetch_company_records_providers_and_keeps_going_after_a_failure():
    def command(name, ticker, **kwargs):
        if name == "insider":
            raise RuntimeError("premium endpoint")
        if name == "prices":
            return "yfinance", pd.DataFrame(
                [{"date": "2026-10-01", "close": 100.0}, {"date": "2025-10-01", "close": 90.0}]
            )
        if name in ("income", "balance", "cash", "insider", "peers", "price_target"):
            return "fmp", pd.DataFrame([{"symbol": ticker, "revenue": 1.0}])
        return "fmp", pd.DataFrame([{"symbol": ticker, "name": "Test"}])

    data = autofill.fetch_company("TEST", command=command, today=TODAY)

    assert data.providers["profile"] == "fmp"
    assert data.providers["prices"] == "yfinance"
    assert "insider" in data.failures
    assert "premium endpoint" in data.failures["insider"]
    assert len(data.prices) == 2


def test_load_macro_reads_the_latest_row_per_series():
    def query(sql, params=None):
        assert "raw.macro_series" in sql
        return pd.DataFrame(
            [
                {"series_id": "IG_OAS", "value": 0.8, "as_of": "2026-10-19", "source": "FRED"},
                {"series_id": "HY_OAS", "value": 3.1, "as_of": "2026-10-19", "source": "FRED"},
            ]
        )

    macro = autofill.load_macro(query=query)

    assert macro["IG_OAS"]["value"] == 0.8
    assert macro["HY_OAS"]["source"] == "FRED"


def test_load_macro_tolerates_an_unloaded_warehouse():
    def query(sql, params=None):
        raise RuntimeError("relation raw.macro_series does not exist")

    assert autofill.load_macro(query=query) == {}


def test_fetch_company_keeps_the_date_index_of_price_history():
    def command(name, ticker, **kwargs):
        if name == "prices":
            frame = pd.DataFrame(
                {"close": [100.0, 90.0]},
                index=pd.Index(pd.to_datetime(["2026-10-01", "2025-10-01"]), name="date"),
            )
            return "fmp", frame
        return "fmp", pd.DataFrame([{"symbol": ticker}])

    data = autofill.fetch_company("TEST", command=command, today=TODAY)

    assert [item["close"] for item in data.prices] == [90.0, 100.0]


def test_yfinance_profile_dividend_yield_is_read_as_a_percentage():
    data = _sample_data()
    data.ratios = {}
    data.providers["profile"] = "yfinance"
    data.profile["dividend_yield"] = 2.5

    payload = autofill.build_payload("TEST", data, macro=MACRO, today=TODAY)

    assert "2.5% dividend yield" in payload["sections"]["final"]["thesis"]
