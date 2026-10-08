"""The API client: what it sends, what it refuses to send, and what it reports back."""

import pytest
import requests

from src.crispdm.api_client import ENDPOINTS, ApiClient

KEY = "s3cret-api-key-value"


class FakeResponse:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeSession:
    def __init__(self, response=None, raises=None):
        self.response = response or FakeResponse(body={"ok": True})
        self.raises = raises
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if self.raises:
            raise self.raises
        return self.response


def client(session=None, key=KEY):
    return ApiClient("http://api:8000/", key, session=session or FakeSession())


@pytest.mark.parametrize(
    "url",
    ["", "localhost:8000", "ftp://api", "file:///etc/passwd", "javascript:alert(1)", "http://"],
)
def test_only_an_http_base_url_is_accepted(url):
    with pytest.raises(ValueError, match="http"):
        ApiClient(url, None)


def test_health_is_called_without_the_api_key():
    session = FakeSession()
    result = client(session).health()

    assert result.ok and result.data == {"ok": True}
    assert session.calls[0]["url"] == "http://api:8000/health"
    assert "X-API-Key" not in session.calls[0]["headers"]


def test_an_endpoint_call_sends_the_key_in_a_header_never_in_the_url():
    session = FakeSession()
    client(session).call("Company", "ko")

    call = session.calls[0]
    assert call["url"] == "http://api:8000/companies/KO"
    assert call["headers"]["X-API-Key"] == KEY
    assert KEY not in call["url"] and not call["params"]


def test_no_key_header_is_sent_when_none_is_configured():
    session = FakeSession()
    client(session, key=None).call("Company", "KO")
    assert "X-API-Key" not in session.calls[0]["headers"]


@pytest.mark.parametrize(
    "ticker",
    ["", "  ", "../admin", "KO/../x", "KO?x=1", "KO#frag", "-X", "KO KO", "K" * 40, None, "KO;ls"],
)
def test_a_ticker_that_could_change_the_path_is_refused_before_any_request(ticker):
    session = FakeSession()
    with pytest.raises(ValueError, match="ticker"):
        client(session).call("Company", ticker)
    assert session.calls == []


def test_a_preferred_share_ticker_is_allowed_and_escaped_in_the_path():
    session = FakeSession()
    client(session).call("Company", "bac-pk")
    assert session.calls[0]["url"].endswith("/companies/BAC-PK")


def test_an_unknown_endpoint_is_refused():
    with pytest.raises(ValueError, match="unknown endpoint"):
        client().call("../../etc/passwd", "KO")


def test_only_the_parameters_the_endpoint_declares_are_sent():
    session = FakeSession()
    client(session).call("Filings", "KO", {"limit": "5", "evil": "1", "as_of": "2026-01-01"})
    assert session.calls[0]["params"] == {"limit": "5"}


def test_empty_parameters_are_dropped():
    session = FakeSession()
    client(session).call("Company list", None, {"offset": "", "limit": None})
    assert session.calls[0]["params"] is None


def test_an_endpoint_that_needs_no_ticker_ignores_one():
    session = FakeSession()
    client(session).call("Company list", "../x")
    assert session.calls[0]["url"] == "http://api:8000/companies/"


def test_an_error_status_is_reported_with_the_servers_detail():
    session = FakeSession(FakeResponse(404, body={"detail": "unknown ticker"}))
    result = client(session).call("Company", "ZZZZ")

    assert not result.ok and result.status_code == 404
    assert result.error == "HTTP 404: unknown ticker" and result.data is None


def test_a_non_json_body_is_kept_as_bounded_text():
    session = FakeSession(FakeResponse(200, body=None, text="x" * 5000))
    result = client(session).call("Company", "KO")
    assert result.ok and len(result.data) == 2000


def test_a_network_failure_is_a_result_not_an_exception_and_does_not_leak_the_key():
    session = FakeSession(raises=requests.ConnectionError("connection refused"))
    result = client(session).call("Company", "KO")

    assert not result.ok and result.status_code is None
    assert "ConnectionError" in result.error and KEY not in result.error


def test_every_catalogued_endpoint_is_a_get_path_under_the_base():
    for endpoint in ENDPOINTS.values():
        assert endpoint.path.startswith("/")
        assert ("{ticker}" in endpoint.path) == endpoint.needs_ticker
