import sys
from unittest.mock import patch

import pytest
import requests

from scripts import populate_companyfacts
from scripts.populate_companyfacts import (
    PREFERRED_TAXONOMY_CONCEPTS,
    _ingest_taxonomy_cik,
    resolve_taxonomy_concepts,
    upsert_company_taxonomy,
    upsert_companyfacts,
    upsert_submissions,
)
from src.crispdm.sec_client import SECDataUnavailableError, get_companyfacts


class _Result:
    def mappings(self):
        return self

    def all(self):
        return []


class _QueueConn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((str(sql), params))
        return _Result()


def test_companyfacts_404_is_typed_as_unavailable():
    response = requests.Response()
    response.status_code = 404
    response.url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001776073.json"

    with patch("src.crispdm.sec_client.SEC_SESSION.get", return_value=response):
        with pytest.raises(SECDataUnavailableError) as error:
            get_companyfacts("0001776073")

    assert error.value.cik == "0001776073"
    assert error.value.url.endswith("CIK0001776073.json")


def test_resolve_taxonomy_concepts_default_map_is_shared():
    assert resolve_taxonomy_concepts(None) is PREFERRED_TAXONOMY_CONCEPTS
    assert "us-gaap" in PREFERRED_TAXONOMY_CONCEPTS
    assert "dei" in PREFERRED_TAXONOMY_CONCEPTS


def test_resolve_taxonomy_concepts_supports_any_taxonomy():
    resolved = resolve_taxonomy_concepts(["us-gaap", "dei", "srt"])

    assert resolved["us-gaap"] == PREFERRED_TAXONOMY_CONCEPTS["us-gaap"]
    assert resolved["dei"] == PREFERRED_TAXONOMY_CONCEPTS["dei"]
    assert resolved["srt"] == []


def test_resolve_taxonomy_concepts_rejects_unknown_taxonomy():
    with pytest.raises(ValueError, match="Unknown taxonomy: unknown"):
        resolve_taxonomy_concepts(["unknown"])


def test_resolve_taxonomy_concepts_rejects_zero_concept_selection():
    with pytest.raises(ValueError, match="At least one taxonomy concept"):
        resolve_taxonomy_concepts(["srt"])


def test_ingest_taxonomy_cik_skips_missing_and_stores_present():
    conn = _QueueConn()
    stats = {"fetched": 0, "stored_taxonomy": 0, "unavailable": 0, "errors": 0}
    security = {"security_id": "uuid-1"}
    taxonomy_concepts = {"us-gaap": ["PresentConcept", "MissingConcept"]}

    def fake_get(cik, taxonomy, concept):
        if concept == "MissingConcept":
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)
        return {"cik": int(cik), "taxonomy": taxonomy, "tag": concept, "units": {}}

    with patch("scripts.populate_companyfacts.get_companyconcept", side_effect=fake_get):
        _ingest_taxonomy_cik(
            conn,
            "0001332551",
            [("ACR-PC", "ACRES Commercial Realty Corp.", security)],
            taxonomy_concepts,
            stats,
        )

    assert stats == {
        "fetched": 1,
        "stored_taxonomy": 1,
        "unavailable": 1,
        "errors": 0,
        "processed_ciks": 1,
    }

    sql, params = conn.executed[0]
    assert sql.strip().startswith("INSERT INTO raw.company_taxonomy")
    assert "PresentConcept" in params["taxonomies"]
    assert "MissingConcept" not in params["taxonomies"]
    assert "PresentConcept" in params["concept_groups"]


def test_ingest_taxonomy_cik_does_not_store_partial_payload_after_error():
    conn = _QueueConn()
    stats = {"fetched": 0, "stored_taxonomy": 0, "unavailable": 0, "errors": 0}
    security = {"security_id": "uuid-1"}

    with patch(
        "scripts.populate_companyfacts.get_companyconcept",
        side_effect=RuntimeError("SEC unavailable"),
    ):
        _ingest_taxonomy_cik(
            conn,
            "0001332551",
            [("ACR-PC", "ACRES Commercial Realty Corp.", security)],
            {"us-gaap": ["BrokenConcept"]},
            stats,
        )

    assert stats["errors"] == 1
    assert stats["failed_ciks"] == 1
    assert stats["stored_taxonomy"] == 0
    assert conn.executed == []


def _companyfacts_payload(tag):
    return {
        "company": "Test Co",
        "full_facts": {"facts": {"x": tag}},
        "concept_groups": {"preferred_stock": [tag]},
    }


def test_upsert_companyfacts_guards_payload_rewrite_on_unchanged_hash():
    conn = _QueueConn()

    upsert_companyfacts(conn, "0000000001", _companyfacts_payload("A"))

    sql, _ = conn.executed[0]
    assert sql.strip().startswith("INSERT INTO raw.companyfacts")
    assert "raw.companyfacts.content_hash IS DISTINCT FROM EXCLUDED.content_hash" in sql
    assert "ELSE raw.companyfacts.raw_payload END" in sql
    assert "ELSE raw.companyfacts.concept_groups END" in sql


def test_upsert_submissions_guards_payload_rewrite_on_unchanged_hash():
    conn = _QueueConn()

    upsert_submissions(conn, "0000000001", "Test Co", {"name": "Test Co"})

    sql, _ = conn.executed[0]
    assert sql.strip().startswith("INSERT INTO raw.sec_submissions")
    assert "raw.sec_submissions.content_hash IS DISTINCT FROM EXCLUDED.content_hash" in sql
    assert "ELSE raw.sec_submissions.raw_payload END" in sql


def test_upsert_company_taxonomy_guards_payload_rewrite_on_unchanged_hash():
    conn = _QueueConn()

    upsert_company_taxonomy(conn, "0000000001", "Test Co", {"us-gaap": {}})

    sql, _ = conn.executed[0]
    assert sql.strip().startswith("INSERT INTO raw.company_taxonomy")
    assert "raw.company_taxonomy.content_hash IS DISTINCT FROM EXCLUDED.content_hash" in sql
    assert "ELSE raw.company_taxonomy.raw_payload END" in sql


def test_main_dividend_sweep_passes_historical_flags(monkeypatch):
    """Regression: main() read args.include_historical / args.historical_only
    without defining the options, so the dividend-universe sweep (stage 4b)
    exited 1 on every run while the preferred and unlinked sweeps passed."""
    calls = {}

    def fake_populate(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(populate_companyfacts, "populate_companyfacts", fake_populate)
    monkeypatch.setattr(sys, "argv", ["populate_companyfacts"])
    assert populate_companyfacts.main() == 0
    assert calls["include_historical"] is False
    assert calls["historical_only"] is False

    monkeypatch.setattr(sys, "argv", ["populate_companyfacts", "--historical-only"])
    assert populate_companyfacts.main() == 0
    assert calls["historical_only"] is True

    monkeypatch.setattr(sys, "argv", ["populate_companyfacts", "--include-historical"])
    assert populate_companyfacts.main() == 0
    assert calls["include_historical"] is True
