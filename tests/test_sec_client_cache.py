"""The ticker universe is cached so API ticker lookups stop calling SEC per request."""

from __future__ import annotations

import pytest

from src.crispdm import sec_client


class _Response:
    status_code = 200
    headers: dict = {}

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cache():
    sec_client.clear_company_tickers_cache()
    yield
    sec_client.clear_company_tickers_cache()


def _install(monkeypatch, payload, calls):
    def fake_get(url, **kwargs):
        calls.append(url)
        return _Response(payload)

    monkeypatch.setattr(sec_client.SEC_SESSION, "get", fake_get)


def test_repeated_calls_hit_the_network_once(monkeypatch):
    calls = []
    _install(monkeypatch, {"0": {"ticker": "AAPL"}}, calls)

    first = sec_client.get_company_tickers()
    second = sec_client.get_company_tickers()

    assert first is second
    assert len(calls) == 1


def test_clear_forces_a_refetch(monkeypatch):
    calls = []
    _install(monkeypatch, {"0": {"ticker": "AAPL"}}, calls)

    sec_client.get_company_tickers()
    sec_client.clear_company_tickers_cache()
    sec_client.get_company_tickers()

    assert len(calls) == 2


def test_expired_ttl_refetches(monkeypatch):
    calls = []
    _install(monkeypatch, {"0": {"ticker": "AAPL"}}, calls)
    monkeypatch.setattr(sec_client, "COMPANY_TICKERS_TTL_SECONDS", 0)

    sec_client.get_company_tickers()
    sec_client.get_company_tickers()

    assert len(calls) == 2


class _Conditional:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture
def _clear_conditional():
    sec_client.clear_conditional_cache()
    yield
    sec_client.clear_conditional_cache()


def test_revalidation_sends_the_etag_and_reuses_the_payload_on_304(monkeypatch, _clear_conditional):
    sent = []
    responses = [
        _Conditional(200, {"a": 1}, {"ETag": '"v1"'}),
        _Conditional(304),
    ]

    def fake_get(url, headers=None, **kwargs):
        sent.append(dict(headers or {}))
        return responses.pop(0)

    monkeypatch.setattr(sec_client.SEC_SESSION, "get", fake_get)

    first = sec_client.conditional_get_json("https://x/y.json")
    second = sec_client.conditional_get_json("https://x/y.json")

    assert first == second == {"a": 1}
    assert "If-None-Match" not in sent[0]
    assert sent[1]["If-None-Match"] == '"v1"'


def test_a_changed_resource_replaces_the_cached_payload(monkeypatch, _clear_conditional):
    responses = [
        _Conditional(200, {"a": 1}, {"ETag": '"v1"'}),
        _Conditional(200, {"a": 2}, {"ETag": '"v2"'}),
        _Conditional(304),
    ]
    monkeypatch.setattr(sec_client.SEC_SESSION, "get", lambda url, **kw: responses.pop(0))

    sec_client.conditional_get_json("https://x/y.json")
    assert sec_client.conditional_get_json("https://x/y.json") == {"a": 2}
    assert sec_client.conditional_get_json("https://x/y.json") == {"a": 2}


def test_responses_without_validators_are_not_cached(monkeypatch, _clear_conditional):
    monkeypatch.setattr(
        sec_client.SEC_SESSION, "get", lambda url, **kw: _Conditional(200, {"a": 1})
    )

    sec_client.conditional_get_json("https://x/y.json")

    assert not sec_client._conditional_cache


def test_the_conditional_cache_is_bounded(monkeypatch, _clear_conditional):
    monkeypatch.setattr(sec_client, "CONDITIONAL_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(
        sec_client.SEC_SESSION,
        "get",
        lambda url, **kw: _Conditional(200, {"u": url}, {"ETag": url}),
    )

    for n in range(5):
        sec_client.conditional_get_json(f"https://x/{n}.json")

    assert list(sec_client._conditional_cache) == ["https://x/3.json", "https://x/4.json"]
