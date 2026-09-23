from unittest.mock import patch

from fastapi.testclient import TestClient

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
