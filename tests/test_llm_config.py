"""The local LLM-assisted draft stays off and localhost-bound until switched on.

Config only for now: the client and the page are added behind ``llm_enabled`` later, so
these tests pin the safe defaults the rest of that work depends on. ``_env_file=None``
keeps a developer's ``.env`` from changing the outcome.
"""

from __future__ import annotations

from src.crispdm.config import Settings


def test_the_local_draft_is_disabled_and_localhost_by_default():
    settings = Settings(_env_file=None)

    assert settings.llm_enabled is False
    assert settings.llm_endpoint_is_local() is True


def test_generation_defaults_are_conservative():
    settings = Settings(_env_file=None)

    assert settings.llm_temperature <= 0.3
    assert settings.llm_max_tokens > 0
    assert settings.llm_timeout_seconds > 0


def test_a_remote_endpoint_is_not_treated_as_local():
    settings = Settings(_env_file=None, llm_endpoint="https://api.example.com/v1/chat")

    assert settings.llm_endpoint_is_local() is False


def test_every_loopback_spelling_counts_as_local():
    for endpoint in (
        "http://localhost:11434/v1/chat/completions",
        "http://127.0.0.1:8000/v1/chat/completions",
        "http://[::1]:8080/v1/chat/completions",
    ):
        assert Settings(_env_file=None, llm_endpoint=endpoint).llm_endpoint_is_local(), endpoint
