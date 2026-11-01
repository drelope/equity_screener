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
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "period_ending": "2025-09-27",
                    "fiscal_period": "FY",
                    "fiscal_year": 2025,
                    "filing_date": "2025-10-31",
                    "reported_currency": "USD",
                    "revenue": 1,
                }
            ]
        ),
    )

    response = TestClient(app).get(
        "/openbb/statements/TEST?statement=balance", headers={"X-API-Key": "test-key"}
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["period_end"] == "2025-09-27"
    assert item["fiscal_period"] == "FY"
    assert item["fiscal_year"] == 2025
    assert item["filing_date"] == "2025-10-31"
    assert item["reported_currency"] == "USD"
    assert item["metrics"]["revenue"] == 1
    assert "period_ending" not in item


def test_openbb_statements_live_drops_unkeyable_rows(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "_security_id", lambda ticker: "sid")
    monkeypatch.setattr(api_main, "read_df", lambda sql, params: pd.DataFrame())
    monkeypatch.setattr(
        api_main.openbb_client,
        "financial_statements",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {"period_ending": "2025-09-27", "filing_date": None, "revenue": 1},
                {
                    "period_ending": "2025-09-27",
                    "filing_date": "2025-10-31",
                    "revenue": 2,
                },
            ]
        ),
    )

    response = TestClient(app).get("/openbb/statements/TEST", headers={"X-API-Key": "test-key"})

    items = response.json()["items"]
    assert [item["metrics"]["revenue"] for item in items] == [2]


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


def test_openbb_macro_inputs_reads_stored_series_and_renders_markdown(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    frames = {
        "raw.macro_series": pd.DataFrame(
            [
                {
                    "series_id": "UST_2Y",
                    "observation_date": "2026-10-20",
                    "value": 4.79,
                    "unit": "percent",
                    "source": "FMP",
                },
                {
                    "series_id": "VIX",
                    "observation_date": "2026-10-20",
                    "value": 17.31,
                    "unit": "index points",
                    "source": "FMP",
                },
            ]
        ),
        "raw.macro_etf_sectors": pd.DataFrame(
            [{"symbol": "PFF", "sector": "Financial Services", "value": 0.4705}]
        ),
    }

    def fake_read_df(sql, params=None):
        for table, frame in frames.items():
            if table in sql:
                return frame
        return pd.DataFrame()

    monkeypatch.setattr(api_main, "read_df", fake_read_df)

    response = TestClient(app).get(
        "/openbb/macro/inputs?markdown=true", headers={"X-API-Key": "test-key"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2026-10-20"
    entries = {entry["id"]: entry for entry in body["inputs"]}
    assert entries["UST_2Y"]["status"] == "Observed"
    assert entries["UST_2Y"]["value"] == 4.79
    assert entries["UST_2Y"]["as_of"] == "2026-10-20"
    assert entries["MOVE"]["status"] == "UNVERIFIED"
    assert entries["2s10s"]["status"] == "UNVERIFIED"
    assert body["benchmarks"][0]["symbol"] == "PFF"
    assert body["benchmarks"][0]["financials_weight"] == 0.4705
    assert "**Curve / rates**" in body["markdown"]
    assert "`UST_2Y` 4.79% **Observed** (FMP, 2026-10-20)" in body["markdown"]


def test_openbb_macro_inputs_falls_back_to_a_live_fetch_when_nothing_is_stored(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "read_df", lambda sql, params=None: pd.DataFrame())
    live_rows = [
        {
            "series_id": "SOFR",
            "observation_date": date(2026, 10, 20),
            "value": 3.87,
            "unit": "percent",
            "source": "FRED",
            "provider": "economy.fred_series",
        }
    ]
    monkeypatch.setattr(
        api_main.macro_inputs,
        "collect_rows",
        lambda **kwargs: (
            live_rows,
            [],
            {"attempted": 1, "written": 0, "skipped": 0, "errors": 0, "empty": 0},
        ),
    )

    response = TestClient(app).get("/openbb/macro/inputs", headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2026-10-20"
    entries = {entry["id"]: entry for entry in body["inputs"]}
    assert entries["SOFR"]["status"] == "Observed"
    assert entries["SOFR"]["source"] == "FRED"
    assert entries["HY_OAS"]["status"] == "UNVERIFIED"
    assert "markdown" not in body


def test_company_entry_prefers_the_warehouse_over_live_sec(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "read_df",
        lambda sql, params=None: pd.DataFrame(
            [{"cik": "0000320193", "ticker": "AAPL", "security_name": "Apple"}]
        ),
    )

    def _boom():
        raise AssertionError("live SEC must not be called")

    monkeypatch.setattr(api_main.sec_client, "get_company_tickers", _boom)

    assert api_main._company_entry("AAPL")["cik_str"] == 320193


def test_company_entry_falls_back_to_live_sec_when_unknown(monkeypatch):
    monkeypatch.setattr(api_main, "read_df", lambda sql, params=None: pd.DataFrame())
    monkeypatch.setattr(
        api_main.sec_client,
        "get_company_tickers",
        lambda: {"0": {"ticker": "ZZZ", "cik_str": 9}},
    )

    assert api_main._company_entry("ZZZ")["cik_str"] == 9


def test_filings_read_stored_submissions_without_calling_sec(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    payload = {"cik": "1", "filings": {"recent": {"form": ["10-K"], "accessionNumber": ["a"]}}}
    monkeypatch.setattr(api_main, "_company_entry", lambda t: {"cik_str": 1})
    monkeypatch.setattr(api_main, "_stored_submissions", lambda cik: payload)

    def _boom(cik):
        raise AssertionError("live SEC must not be called")

    monkeypatch.setattr(api_main.sec_client, "get_submissions", _boom)

    response = TestClient(app).get("/filings/TEST", headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    assert response.json()["items"] == [{"form": "10-K", "accessionNumber": "a"}]


def test_filings_fall_back_to_live_sec_when_not_stored(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr(api_main, "_company_entry", lambda t: {"cik_str": 1})
    monkeypatch.setattr(api_main, "_stored_submissions", lambda cik: None)
    stored = []
    monkeypatch.setattr(api_main, "_store_submissions", lambda cik, payload: stored.append(cik))
    monkeypatch.setattr(
        api_main.sec_client,
        "get_submissions",
        lambda cik: {"cik": "1", "filings": {"recent": {"form": ["8-K"]}}},
    )

    response = TestClient(app).get("/filings/TEST", headers={"X-API-Key": "test-key"})

    assert response.json()["items"] == [{"form": "8-K"}]
    assert stored == [1]


def test_a_failed_write_through_does_not_fail_the_request(monkeypatch):
    def broken(sql, params=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(api_main, "execute", broken)

    api_main._store_submissions(1, {"name": "X"})


def test_write_through_uses_the_per_cik_hash_scheme(monkeypatch):
    import hashlib
    import json

    seen = {}
    monkeypatch.setattr(api_main, "execute", lambda sql, params=None: seen.update(params))
    payload = {"name": "X", "b": 1, "a": 2}

    api_main._store_submissions(320193, payload)

    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert seen["cik"] == "0000320193"
    assert seen["hash"] == expected
