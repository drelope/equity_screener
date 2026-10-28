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


def test_missing_data_produces_a_draft_but_no_recommendation():
    payload = _payload(autofill.CompanyData(ticker="EMPTY"), macro={})

    assert schema.validate_draft(payload) == []
    assert payload["sections"]["final"]["recommendation"] == ""
    assert any("Recommendation" in error for error in schema.validate(payload))
    assert "not have enough reported data" in payload["sections"]["final"]["thesis"]
    assert payload["sections"]["macro"]["credit_verdict"] == "Neutral"
    assert "not loaded" in payload["sections"]["macro"]["macro_backdrop"]


def test_a_single_price_is_not_enough_to_recommend_the_name():
    payload = _payload(autofill.CompanyData(ticker="ONE", quote={"last_price": 100.0}), macro={})

    assert payload["sections"]["final"]["recommendation"] == ""
    assert schema.validate_draft(payload) == []


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


def test_analog_table_falls_back_to_the_securitys_own_windows_without_a_peer_sample():
    # No warehouse in the payload, so there is no peer sample: the own-history
    # table is the fallback and the confidence note says so.
    payload = _payload()
    analog = payload["sections"]["analog"]

    assert analog["similar_setups"].count("| Same security") >= 3
    assert "total return" in analog["similar_setups"]
    assert analog["base_rate"].endswith("%")
    assert "own 12M windows, not a peer sample" in analog["confidence_note"]


def _peer_warehouse(pct_positive=70.1, observations=211):
    return {
        "features": {"as_of_date": "2026-10-19", "current_price": 100.0},
        "base_rate": {
            "ticker": "TEST",
            "industry": "Drug Manufacturers - General",
            "observations": observations,
            "has_sample": True,
            "pct_positive": pct_positive,
            "base_rate": f"{pct_positive:.0f}%",
            "median_return": 0.0888,
            "p05_return": -0.137,
            "p95_return": 0.665,
            "peer_observations": 1680,
            "peer_pct_positive": 64.5,
            "current_yield": 0.0204,
            "current_coverage": 1.6875,
            "caveats": ["Peers are classified by today's industry."],
            "similar_table": (
                "| Date | Conditions | Forward 12M total return | Outcome |\n"
                "| --- | --- | --- | --- |\n"
                "| 2023-01-03 | Drug Manufacturers - General, yield 2.97% | 19.9% | Positive |\n"
                "| 2022-02-01 | Drug Manufacturers - General, yield 2.45% | -0.6% | Negative |"
            ),
        },
    }


def test_the_analog_section_reports_the_peer_base_rate_when_there_is_one():
    payload = autofill.build_payload(
        "TEST",
        _sample_data(),
        macro=MACRO,
        warehouse=_peer_warehouse(),
        today=TODAY,
    )
    analog = payload["sections"]["analog"]

    assert analog["base_rate"] == "70%"
    assert "Drug Manufacturers - General" in analog["similar_setups"]
    assert "Positive" in analog["similar_setups"]
    assert "matched peer setups" in analog["analog_implication"]
    assert "211" in analog["analog_implication"]
    assert "not a peer sample" not in analog["confidence_note"]
    assert "Peers are classified by today's industry." in analog["confidence_note"]


def test_the_peer_base_rate_names_the_conditions_the_sample_did_not_use():
    payload = autofill.build_payload(
        "TEST",
        _sample_data(),
        macro=MACRO,
        warehouse=_peer_warehouse(),
        today=TODAY,
    )
    key_differences = payload["sections"]["analog"]["key_differences"]

    assert "2.04% yield" in key_differences
    assert "1.69x coverage" in key_differences
    assert "does not condition on" in key_differences


def test_the_analog_section_still_passes_the_worksheet_rules_with_a_peer_rate():
    payload = autofill.build_payload(
        "TEST",
        _sample_data(),
        macro=MACRO,
        warehouse=_peer_warehouse(),
        today=TODAY,
    )

    assert schema.validate(payload) == []
    assert schema.validate_draft(payload) == []


def test_a_thin_peer_sample_falls_back_to_the_own_history_table():
    warehouse = _peer_warehouse()
    warehouse["base_rate"]["has_sample"] = False

    payload = autofill.build_payload(
        "TEST", _sample_data(), macro=MACRO, warehouse=warehouse, today=TODAY
    )
    analog = payload["sections"]["analog"]

    assert analog["similar_setups"].count("| Same security") >= 3
    assert "own 12M windows, not a peer sample" in analog["confidence_note"]


def test_the_own_history_fallback_reads_the_stored_forward_returns():
    warehouse = {
        "features": {"as_of_date": "2026-10-19", "current_price": 100.0},
        "base_rate": {"has_sample": False},
        "own_returns": [
            {
                "as_of_date": "2023-06-01",
                "forward_date": "2024-06-03",
                "window_days": 252,
                "total_return": 0.20,
                "price_return": 0.16,
                "dividend_return": 0.04,
            },
            {
                "as_of_date": "2024-06-03",
                "forward_date": "2025-06-02",
                "window_days": 252,
                "total_return": -0.10,
                "price_return": -0.14,
                "dividend_return": 0.04,
            },
        ],
    }

    payload = autofill.build_payload(
        "TEST", _sample_data(), macro=MACRO, warehouse=warehouse, today=TODAY
    )
    analog = payload["sections"]["analog"]

    assert "2023-06-01 to 2024-06-03" in analog["similar_setups"]
    assert "20.0%" in analog["similar_setups"]
    assert analog["base_rate"] == "50%"
    assert "own 12M windows, not a peer sample" in analog["confidence_note"]


def test_price_return_uses_adjusted_close_so_dividends_are_reinvested():
    rows = [{"date": TODAY, "close": 100.0, "adj_close": 110.0}]

    assert autofill._price_rows(rows)[0]["close"] == 110.0


def test_scenario_and_recommendation_returns_include_the_dividend_yield():
    payload = _payload()

    assert payload["sections"]["scenarios"]["expected_return"] == "18.5%"
    assert "18.5% expected 12M total return" in payload["sections"]["final"]["thesis"]


def test_statement_outflows_are_presented_as_positive_amounts():
    payload = _payload()

    assert (
        "Capex 500.00M USD (5.0% of revenue)"
        in payload["sections"]["capital_cycle"]["capacity_growth"]
    )
    assert (
        "Dividends 400.00M USD" in payload["sections"]["management"]["capital_allocation_history"]
    )
    assert "buybacks 200.00M USD" in payload["sections"]["variant"]["consensus_capital_allocation"]


def test_the_worksheet_assesses_dividend_sustainability_and_cover():
    payload = _payload()
    company = payload["sections"]["company"]["financial_analysis"]

    assert "earnings payout 33.3%" in company
    assert "FCF payout 36.4%" in company
    assert "earnings cover 3.0x" in company
    assert "the dividend is covered" in company
    assert "the dividend is covered" in payload["sections"]["final"]["risk_summary"]


def test_a_stored_sustainability_label_overrides_the_derived_verdict():
    payload = autofill.build_payload(
        "TEST",
        _sample_data(),
        macro=MACRO,
        warehouse={"features": {"target_sustainable_dividend": 0}},
        today=TODAY,
    )

    assert "the dividend is not sustainable" in payload["sections"]["company"]["financial_analysis"]


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
        # The real table names its date column observation_date; guard the mapping.
        assert "observation_date AS as_of" in sql
        assert "ORDER BY series_id, observation_date DESC" in sql
        return pd.DataFrame(
            [
                {"series_id": "IG_OAS", "value": 0.8, "as_of": "2026-10-19", "source": "FRED"},
                {"series_id": "HY_OAS", "value": 3.1, "as_of": "2026-10-19", "source": "FRED"},
            ]
        )

    macro = autofill.load_macro(query=query)

    assert macro["IG_OAS"]["value"] == 0.8
    assert macro["IG_OAS"]["as_of"] == "2026-10-19"
    assert macro["HY_OAS"]["source"] == "FRED"


def test_load_macro_tolerates_an_unloaded_warehouse():
    def query(sql, params=None):
        raise RuntimeError("relation raw.macro_series does not exist")

    assert autofill.load_macro(query=query) == {}


def test_load_warehouse_reads_the_latest_rows_and_recent_financials():
    def query(sql, params=None):
        if "reference.securities" in sql:
            return pd.DataFrame([{"security_id": "abc"}])
        if "model.features" in sql:
            return pd.DataFrame(
                [
                    {
                        "as_of_date": "2026-10-19",
                        "dividend_coverage": 2.1,
                        "earnings_payout": 0.45,
                        "fcf_payout": 0.38,
                        "target_sustainable_dividend": 1,
                        "price_quality": "ok",
                    }
                ]
            )
        if "model.scores" in sql:
            return pd.DataFrame(
                [
                    {
                        "as_of_date": "2026-10-19",
                        "composite_score": 0.72,
                        "sustainability_score": 0.8,
                        "risk_score": 0.3,
                        "score_coverage": 0.9,
                        "cvs_tier": "T2",
                    }
                ]
            )
        if "raw.fmp_dcf" in sql:
            return pd.DataFrame([{"as_of_date": "2026-10-18", "dcf": 120.0}])
        if "periodic_financials" in sql:
            return pd.DataFrame(
                [
                    {"period_end": "2025-12-31", "revenue": 1e10, "net_income": 1e9},
                    {"period_end": "2024-12-31", "revenue": 9e9, "net_income": 8e8},
                ]
            )
        raise AssertionError(sql)

    warehouse = autofill.load_warehouse("TEST", query=query)

    assert warehouse["security_id"] == "abc"
    assert warehouse["features"]["dividend_coverage"] == 2.1
    assert warehouse["scores"]["composite_score"] == 0.72
    assert warehouse["dcf"]["dcf"] == 120.0
    assert len(warehouse["financials"]) == 2


def test_load_warehouse_tolerates_missing_tables_and_unknown_tickers():
    def missing_table(sql, params=None):
        if "reference.securities" in sql:
            return pd.DataFrame([{"security_id": "abc"}])
        raise RuntimeError("relation does not exist")

    def unknown_ticker(sql, params=None):
        return pd.DataFrame()

    warehouse = autofill.load_warehouse("TEST", query=missing_table)
    assert warehouse["features"] == {}
    assert warehouse["financials"] == []
    assert autofill.load_warehouse("MISSING", query=unknown_ticker) == {}


def test_load_warehouse_reads_the_peer_base_rate():
    def query(sql, params=None):
        # The sample query names every relation the other reads name, so it is
        # matched first; the industry read joins reference.securities as well.
        if "model.forward_returns" in sql:
            return pd.DataFrame(
                [
                    {
                        "as_of_date": "2020-01-02",
                        "ticker": "AAA",
                        "industry": "Peers",
                        "dividend_yield": 0.03,
                        "dividend_coverage": 2.0,
                        "total_return": 0.10,
                        "price_return": 0.08,
                        "dividend_return": 0.02,
                    }
                ]
            )
        if "clean.ticker_profile" in sql:
            return pd.DataFrame([{"industry": "Peers"}])
        if "reference.securities" in sql:
            return pd.DataFrame([{"security_id": "abc"}])
        if "model.features" in sql:
            return pd.DataFrame(
                [{"as_of_date": "2026-10-19", "dividend_yield": 0.03, "dividend_coverage": 2.0}]
            )
        return pd.DataFrame()

    warehouse = autofill.load_warehouse("TEST", query=query)
    base_rate = warehouse["base_rate"]

    assert base_rate["industry"] == "Peers"
    assert base_rate["observations"] == 1
    assert base_rate["base_rate"] == "100%"
    assert "Date | Conditions" in base_rate["similar_table"]


def test_a_missing_forward_return_table_leaves_the_warehouse_loadable():
    def query(sql, params=None):
        if "reference.securities" in sql:
            return pd.DataFrame([{"security_id": "abc"}])
        if "model.forward_returns" in sql:
            raise RuntimeError("relation model.forward_returns does not exist")
        return pd.DataFrame()

    warehouse = autofill.load_warehouse("TEST", query=query)

    assert warehouse["base_rate"] == {}


def test_warehouse_context_fills_gaps_and_is_written_into_the_worksheet():
    data = autofill.CompanyData(ticker="TEST", quote={"last_price": 100.0})
    warehouse = {
        "features": {
            "as_of_date": "2026-10-19",
            "current_price": 100.0,
            "dividend_yield": 0.03,
            "earnings_payout": 0.5,
            "fcf_payout": 0.4,
            "dividend_coverage": 2.0,
            "interest_coverage": 8.0,
            "net_debt_to_ebitda": 1.5,
            "current_ratio": 1.7,
            "pe_ratio": 17.0,
            "fcf_yield": 0.05,
            "gross_margin": 0.4,
            "operating_margin": 0.18,
            "net_margin": 0.1,
            "fcf_margin": 0.08,
            "cash_conversion": 1.1,
            "target_sustainable_dividend": 1,
            "data_quality_score": 8.5,
            "price_quality": "ok",
        },
        "scores": {
            "as_of_date": "2026-10-19",
            "composite_score": 0.72,
            "sustainability_score": 0.80,
            "valuation_score": 0.50,
            "risk_score": 0.30,
            "score_coverage": 0.9,
            "cvs_tier": "T2",
            "market_regime": "neutral",
            "credit_environment": "tight",
        },
        "dcf": {"as_of_date": "2026-10-18", "dcf": 120.0, "stock_price": 100.0},
        "financials": [
            {
                "period_end": "2025-12-31",
                "revenue": 1e10,
                "net_income": 1e9,
                "free_cash_flow": 1.2e9,
            },
            {
                "period_end": "2024-12-31",
                "revenue": 9e9,
                "net_income": 8e8,
                "free_cash_flow": 1.0e9,
            },
        ],
    }

    payload = autofill.build_payload("TEST", data, macro={}, warehouse=warehouse, today=TODAY)
    company = payload["sections"]["company"]["financial_analysis"]
    valuation = payload["sections"]["valuation"]
    final = payload["sections"]["final"]

    assert "Stored features" in company
    assert "dividend cover 2.0x" in company
    assert "Model scores" in company
    assert "FMP DCF" in valuation["valuation_methods"]
    assert "120.00" in valuation["target_price"]
    assert payload["sections"]["risk"]["overall_risk_score"] == 4
    assert "warehouse model" in final["risk_summary"]
    assert "0.9" in final["data_quality"] or "90.0%" in final["data_quality"]
    assert "model.features" in valuation["sources"]


def test_live_provider_values_take_precedence_over_stored_features():
    data = _sample_data()
    warehouse = {"features": {"dividend_yield": 0.09, "pe_ratio": 99.0}}

    payload = autofill.build_payload("TEST", data, macro=MACRO, warehouse=warehouse, today=TODAY)

    assert "2.5% dividend yield" in payload["sections"]["final"]["thesis"]
    assert "P/E 18.0x" in payload["sections"]["variant"]["consensus_multiple"]


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


# --- options positioning (opt-in, descriptive only) --------------------------------


def _option_chain(spot=100.0):
    rows = []
    for dte in (30, 95):
        expiry = (TODAY + pd.Timedelta(days=dte)).date().isoformat()
        for strike in (85, 90, 95, 100, 105, 110, 115):
            for kind in ("call", "put"):
                distance = abs(strike / spot - 1.0)
                iv = 0.24 + 0.30 * distance
                if kind == "put":
                    iv += 0.05 * max(0.0, 1.0 - strike / spot)
                if dte > 60:
                    iv += 0.02
                bid = max(0.05, 3.0 - abs(strike - spot) * 0.2)
                rows.append(
                    {
                        "underlying_price": spot,
                        "expiration": expiry,
                        "dte": dte,
                        "strike": strike,
                        "option_type": kind,
                        "open_interest": 1000 if kind == "call" else 800,
                        "volume": 500 if kind == "call" else 400,
                        "last_trade_price": bid,
                        "bid": bid,
                        "ask": bid + 0.2,
                        "implied_volatility": iv,
                    }
                )
    return rows


def _options_data():
    data = _sample_data()
    data.options_requested = True
    data.options = _option_chain()
    data.index_options = _option_chain(spot=500.0)
    data.vix_term = {"vix": 18.0, "vix3m": 20.5, "as_of": "2026-10-19"}
    return data


def test_options_are_not_used_until_requested_and_say_so():
    payload = _payload()

    risk = payload["sections"]["risk"]
    assert risk["options_data_status"] == "Unavailable"
    assert "Not requested" in risk["options_iv"]
    assert "Not requested" in payload["sections"]["macro"]["index_put_call_ratio"]


def test_options_block_fills_every_metric_from_the_chain():
    payload = _payload(_options_data())

    macro = payload["sections"]["macro"]
    risk = payload["sections"]["risk"]
    assert "SPY proxy" in macro["index_put_call_ratio"]
    assert "contango" in macro["vix_term_structure"]
    assert "ATM straddle" in payload["sections"]["consensus"]["options_implied_move"]
    assert "+/-" in payload["sections"]["consensus"]["options_implied_move"]
    assert risk["options_data_status"] == "Observed"
    assert "ATM IV" in risk["options_iv"]
    assert "25-delta" in risk["options_skew"]
    assert "slope" in risk["options_term_structure"]
    assert "Open interest" in risk["options_liquidity"]
    assert (
        "descriptive positioning" in payload["sections"]["variant"]["options_positioning"].lower()
    )
    assert schema.validate(payload) == []


def test_options_block_does_not_change_the_recommendation_or_risk_score():
    base = _payload(_sample_data())
    with_options = _payload(_options_data())

    assert (
        with_options["sections"]["final"]["recommendation"]
        == base["sections"]["final"]["recommendation"]
    )
    assert with_options["sections"]["risk"]["confidence"] == base["sections"]["risk"]["confidence"]
    assert (
        with_options["sections"]["risk"]["overall_risk_score"]
        == base["sections"]["risk"]["overall_risk_score"]
    )
    assert (
        with_options["sections"]["risk"]["liquidity_risk"]
        == base["sections"]["risk"]["liquidity_risk"]
    )


def test_requested_options_without_a_chain_are_marked_unavailable():
    data = _sample_data()
    data.options_requested = True

    payload = _payload(data)

    assert payload["sections"]["risk"]["options_data_status"] == "Unavailable"
    assert "no options data" in payload["sections"]["risk"]["options_iv"]


def test_fetch_company_reads_options_only_when_asked():
    calls = []

    def command(name, ticker, **kwargs):
        calls.append((name, ticker))
        if name == "options":
            return "yfinance", pd.DataFrame(_option_chain())
        if name == "index_prices":
            frame = pd.DataFrame(
                {"close": [18.0 if ticker == "^VIX" else 20.5]},
                index=pd.Index([TODAY], name="date"),
            )
            return "yfinance", frame
        if name == "prices":
            return "yfinance", pd.DataFrame([{"date": "2026-10-19", "close": 100.0}])
        return "fmp", pd.DataFrame([{"symbol": ticker, "name": "Test"}])

    data = autofill.fetch_company("TEST", command=command, today=TODAY)
    assert data.options_requested is False
    assert data.options == []
    assert not [call for call in calls if call[0] == "options"]

    calls.clear()
    data = autofill.fetch_company("TEST", command=command, today=TODAY, include_options=True)

    assert ("options", "TEST") in calls
    assert ("options", "SPY") in calls
    assert ("index_prices", "^VIX") in calls
    assert ("index_prices", "^VIX3M") in calls
    assert data.options_requested is True
    assert data.providers["options"] == "yfinance"
    assert data.providers["index_options"] == "yfinance"
    assert data.vix_term == {"vix": 18.0, "vix3m": 20.5, "as_of": "2026-10-20"}


def test_options_command_is_yfinance_only_even_when_fmp_is_pinned(fmp_first, monkeypatch):
    monkeypatch.setattr(settings, "openbb_provider", "fmp")
    calls = []

    def chains(**kwargs):
        calls.append(kwargs["provider"])
        return pd.DataFrame([{"symbol": kwargs["symbol"], "strike": 100.0}])

    fake = SimpleNamespace(
        derivatives=SimpleNamespace(options=SimpleNamespace(chains=chains)),
    )
    monkeypatch.setattr(client, "obb", fake)

    provider, frame = client.equity_command("options", "ABC")

    assert calls == ["yfinance"]
    assert provider == "yfinance"
    assert frame.iloc[0]["strike"] == 100.0
