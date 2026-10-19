"""The local LLM draft client: disabled by default, loopback-bound, never saves.

Every test injects a fake ``requests`` session, so no model and no network are needed. The
shared ``settings`` object is patched in place, which is what the client reads at call time.
"""

from __future__ import annotations

import json

import pytest

from app import analysis_schema as schema
from app import llm_client
from src.crispdm.config import settings

LOCAL = "http://localhost:11434/v1/chat/completions"


class _Response:
    def __init__(self, *, body=None, status=200, json_error=False):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._body


class _Session:
    """Minimal stand-in for ``requests.Session`` that records the one POST it receives."""

    def __init__(self, response):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._response


def _chat(content: str) -> _Response:
    return _Response(body={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_endpoint", LOCAL)
    monkeypatch.setattr(settings, "llm_model", "test-model")
    monkeypatch.setattr(settings, "llm_temperature", 0.2)
    monkeypatch.setattr(settings, "llm_max_tokens", 512)


# --- the off switch ---------------------------------------------------------------


def test_the_client_is_disabled_until_switched_on(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", False)

    assert llm_client.is_enabled() is False
    with pytest.raises(llm_client.LLMError, match="disabled"):
        llm_client.generate_draft("context", session=_Session(_chat("{}")))


def test_a_remote_endpoint_needs_an_explicit_opt_in(enabled, monkeypatch):
    monkeypatch.setattr(settings, "llm_endpoint", "https://api.example.com/v1/chat")

    with pytest.raises(llm_client.LLMError, match="not localhost"):
        llm_client.generate_draft("context", session=_Session(_chat("{}")))

    # With the opt-in, the request is actually attempted (and then fails to parse "{}").
    with pytest.raises(llm_client.LLMError):
        llm_client.generate_draft("context", session=_Session(_chat("{}")), allow_remote=True)


# --- prompt and parsing -----------------------------------------------------------


def test_the_prompt_carries_the_schema_and_the_context(enabled):
    messages = llm_client.build_messages("Ticker: ABC")

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "universe_filters" in messages[0]["content"]
    assert schema.SECTIONS[0].id in messages[0]["content"]
    assert "Ticker: ABC" in messages[1]["content"]


def test_parsing_strips_a_fence_and_ignores_unknown_keys():
    content = 'Here you go:\n```json\n{"sections": {"universe": {"universe_filters": "Tech", "bogus": 1}}}\n```'

    payload = llm_client.parse_payload(content)

    assert payload["sections"]["universe"]["universe_filters"] == "Tech"
    assert "bogus" not in payload["sections"]["universe"]
    assert set(payload["sections"]) == {section.id for section in schema.SECTIONS}


def test_parsing_forces_selects_to_a_listed_option_and_scores_to_int():
    content = json.dumps(
        {
            "sections": {
                "macro": {"credit_verdict": "Sideways"},
                "management": {"management_score": "7"},
                "universe": {"universe_filters": "Banks"},
            }
        }
    )

    payload = llm_client.parse_payload(content)

    assert payload["sections"]["macro"]["credit_verdict"] == ""  # not an option
    assert payload["sections"]["management"]["management_score"] is None  # not an int
    assert payload["sections"]["universe"]["universe_filters"] == "Banks"


def test_non_json_output_is_refused():
    with pytest.raises(llm_client.LLMError, match="valid JSON"):
        llm_client.parse_payload("I cannot help with that.")


# --- the full call ----------------------------------------------------------------


def test_generate_draft_posts_to_the_local_model_and_returns_a_payload(enabled):
    session = _Session(_chat(json.dumps({"sections": {"universe": {"universe_filters": "Tech"}}})))

    payload = llm_client.generate_draft("Ticker: ABC", session=session)

    assert payload["sections"]["universe"]["universe_filters"] == "Tech"
    (url, kwargs), = session.calls
    assert url == LOCAL
    assert kwargs["json"]["model"] == "test-model"
    assert kwargs["json"]["temperature"] == 0.2


def test_a_draft_that_fails_validation_is_refused(enabled):
    # An empty worksheet is not a valid draft, so generation must not hand one back.
    session = _Session(_chat("{}"))

    with pytest.raises(llm_client.LLMError, match="did not pass validation"):
        llm_client.generate_draft("Ticker: ABC", session=session)


def test_an_http_error_is_reported_without_the_key(enabled, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "secret-token")
    session = _Session(_Response(status=500))

    with pytest.raises(llm_client.LLMError, match="HTTP 500") as excinfo:
        llm_client.generate_draft("Ticker: ABC", session=session)

    assert "secret-token" not in str(excinfo.value)


def test_a_response_without_message_content_is_refused(enabled):
    session = _Session(_Response(body={"choices": []}))

    with pytest.raises(llm_client.LLMError, match="no message content"):
        llm_client.generate_draft("Ticker: ABC", session=session)
