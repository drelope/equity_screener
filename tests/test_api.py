from datetime import date
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app
from src.crispdm.sec_client import SECDataUnavailableError


def test_facts_returns_stable_not_found_for_unavailable_sec_dataset(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    error = SECDataUnavailableError(
        "0001776073",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0001776073.json",
    )

    with (
        patch("api.main._company_entry", return_value={"cik_str": 1776073}),
        patch("api.main.sec_client.get_companyfacts", side_effect=error),
    ):
        response = TestClient(app).get(
            "/facts/TEST",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "SEC_COMPANYFACTS_UNAVAILABLE",
        "ticker": "TEST",
        "cik": "0001776073",
        "message": "SEC has no Company Facts dataset for this issuer",
    }


def _companyfacts(concepts: int) -> dict:
    return {"facts": {"us-gaap": {f"concept_{i}": {"units": {}} for i in range(concepts)}}}


def _get_facts(monkeypatch, concepts, limit=None):
    monkeypatch.setenv("API_KEY", "test-key")
    url = "/facts/TEST" if limit is None else f"/facts/TEST?limit={limit}"
    with (
        patch("api.main._company_entry", return_value={"cik_str": 1}),
        patch(
            "api.main.sec_client.get_companyfacts",
            return_value=_companyfacts(concepts),
        ),
    ):
        return TestClient(app).get(url, headers={"X-API-Key": "test-key"})


def test_facts_over_the_cap_is_truncated_and_flagged(monkeypatch):
    response = _get_facts(monkeypatch, concepts=50, limit=10)

    assert response.status_code == 200
    body = response.json()
    assert body["_truncated"] is True
    assert len(body["facts"]["us-gaap"]) == 10


def test_facts_within_the_cap_is_not_flagged(monkeypatch):
    response = _get_facts(monkeypatch, concepts=50)

    assert response.status_code == 200
    body = response.json()
    assert body["_truncated"] is False
    assert len(body["facts"]["us-gaap"]) == 50


def test_interactive_docs_are_disabled_unless_opted_in():
    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_financials_bounds_period_end_to_the_present(monkeypatch):
    """A forward-dated period must never be served as the latest vintage.

    The query orders by period_end, so without the bound a 2039 XBRL context
    (V0078's anomaly) wins the sort and the endpoint reports it as current.
    """
    monkeypatch.setenv("API_KEY", "test-key")
    captured = {}

    def fake_read_df(sql, params):
        captured["sql"] = sql
        return pd.DataFrame()

    monkeypatch.setattr(api_main, "read_df", fake_read_df)
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}

    client.get("/financials/TEST", headers=headers)
    assert "f.period_end <= CURRENT_DATE" in captured["sql"]

    # The point-in-time reading is bounded on both legs, matching the feature
    # build's GREATEST(filed, period_end) availability rule.
    client.get("/financials/TEST?as_of=2024-01-01", headers=headers)
    assert "f.period_end <= CAST(:as_of AS date)" in captured["sql"]
    assert "f.filed <= CAST(:as_of AS date)" in captured["sql"]


def test_a_client_over_the_rate_ceiling_gets_429_with_retry_after(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "_rate_limiter", api_main._SlidingWindowLimiter(2))
    monkeypatch.setattr(api_main.sec_client, "get_company_tickers", lambda: {})
    client = TestClient(app, client=("10.0.0.1", 1234))
    headers = {"X-API-Key": "test-key"}

    assert client.get("/companies/", headers=headers).status_code == 200
    assert client.get("/companies/", headers=headers).status_code == 200
    throttled = client.get("/companies/", headers=headers)

    assert throttled.status_code == 429
    assert throttled.headers["Retry-After"] == "60"


def test_the_rate_ceiling_is_per_client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "_rate_limiter", api_main._SlidingWindowLimiter(1))
    monkeypatch.setattr(api_main.sec_client, "get_company_tickers", lambda: {})
    headers = {"X-API-Key": "test-key"}

    first = TestClient(app, client=("10.0.0.2", 1))
    second = TestClient(app, client=("10.0.0.3", 1))

    assert first.get("/companies/", headers=headers).status_code == 200
    assert first.get("/companies/", headers=headers).status_code == 429
    assert second.get("/companies/", headers=headers).status_code == 200


def test_openbb_statements_reads_stored_rows(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "_security_id", lambda ticker: "sid")
    captured = {}

    def fake_read_df(sql, params):
        captured["sql"] = sql
        return pd.DataFrame(
            [
                {
                    "period_end": "2025-12-31",
                    "fiscal_period": "FY",
                    "fiscal_year": 2025,
                    "filing_date": "2026-02-01",
                    "reported_currency": "USD",
                    "metrics": {"revenue": 100},
                }
            ]
        )

    monkeypatch.setattr(api_main, "read_df", fake_read_df)
    response = TestClient(app).get("/openbb/statements/TEST", headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["statement"] == "income"
    assert body["items"][0]["metrics"]["revenue"] == 100
    assert "raw.fmp_statements" in captured["sql"]


def test_openbb_statements_falls_back_to_a_live_read(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "_security_id", lambda ticker: "sid")
    monkeypatch.setattr(api_main, "read_df", lambda sql, params: pd.DataFrame())
    monkeypatch.setattr(
        api_main.openbb_client,
        "financial_statements",
        lambda *args, **kwargs: pd.DataFrame([{"revenue": 1}]),
    )

    response = TestClient(app).get(
        "/openbb/statements/TEST?statement=balance", headers={"X-API-Key": "test-key"}
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["revenue"] == 1


def test_openbb_statements_reject_an_unknown_statement(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")

    response = TestClient(app).get(
        "/openbb/statements/TEST?statement=cashflow", headers={"X-API-Key": "test-key"}
    )

    assert response.status_code == 422


def test_openbb_dcf_reads_the_stored_vintage(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "_security_id", lambda ticker: "sid")
    monkeypatch.setattr(
        api_main,
        "read_df",
        lambda sql, params: pd.DataFrame(
            [
                {
                    "as_of_date": "2026-10-20",
                    "dcf": 135.6,
                    "stock_price": 340.7,
                    "reported_currency": None,
                }
            ]
        ),
    )

    response = TestClient(app).get("/openbb/dcf/TEST", headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    assert response.json()["items"][0]["dcf"] == 135.6


def test_openbb_dcf_falls_back_to_a_live_read(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "_security_id", lambda ticker: "sid")
    monkeypatch.setattr(api_main, "read_df", lambda sql, params: pd.DataFrame())
    monkeypatch.setattr(
        api_main.openbb_client,
        "discounted_cash_flow",
        lambda symbol: {"as_of_date": date(2026, 10, 20), "dcf": 135.6},
    )

    response = TestClient(app).get("/openbb/dcf/TEST", headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    assert response.json()["items"][0]["dcf"] == 135.6


def test_openbb_filings_reads_stored_rows(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "_security_id", lambda ticker: "sid")
    monkeypatch.setattr(
        api_main,
        "read_df",
        lambda sql, params: pd.DataFrame(
            [
                {
                    "filing_date": "2026-01-01",
                    "report_type": "10-K",
                    "report_url": "http://x",
                    "filing_url": None,
                    "accepted_date": None,
                }
            ]
        ),
    )

    response = TestClient(app).get("/openbb/filings/TEST", headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    assert response.json()["items"][0]["report_type"] == "10-K"
