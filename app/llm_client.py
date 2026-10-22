"""Local LLM-assisted draft for the investment-analysis worksheet.

Off unless ``settings.llm_enabled`` is set, and pointed at a loopback endpoint by default,
so nothing is generated and nothing leaves the machine until an operator deliberately
turns it on. The client only ever *prefills* a Draft: it returns a payload built from a
known schema and validates it with the same draft rules the form uses. It never writes to
the warehouse -- the analyst still reviews the form and saves through the normal path.

The wiring is deliberately a plain function over an injectable ``requests`` session, so the
page can call it and the tests can drive it without a running model.
"""

from __future__ import annotations

import json
import re

import requests

from app import analysis_schema as schema
from src.crispdm.config import settings


class LLMError(RuntimeError):
    """Generation could not run or did not produce a usable worksheet.

    The message is safe to show a user: it never carries the API key, only the endpoint
    and the failure kind.
    """


def is_enabled() -> bool:
    return bool(settings.llm_enabled)


def build_messages(context_markdown: str) -> list[dict]:
    """The chat messages sent to the local model: a schema contract plus the context."""
    return [
        {"role": "system", "content": _system_prompt()},
        {
            "role": "user",
            "content": (
                "Warehouse context for this security:\n\n"
                f"{context_markdown.strip()}\n\n"
                "Return the JSON worksheet now."
            ),
        },
    ]


def generate_draft(
    context_markdown: str,
    *,
    session: requests.Session | None = None,
    allow_remote: bool = False,
    timeout: float | None = None,
) -> dict:
    """Ask the local model for a worksheet payload; never saves anything.

    Raises :class:`LLMError` when the client is disabled, the endpoint is not local and
    ``allow_remote`` was not given, the request fails, or the answer does not parse and
    pass :func:`analysis_schema.validate_draft`.
    """
    _require_enabled(allow_remote)
    content = _post(
        build_messages(context_markdown),
        session=session or requests.Session(),
        timeout=float(timeout if timeout is not None else settings.llm_timeout_seconds),
    )
    payload = parse_payload(content)
    errors = schema.validate_draft(payload)
    if errors:
        raise LLMError("the generated draft did not pass validation: " + "; ".join(errors[:5]))
    return payload


def parse_payload(content: str) -> dict:
    """Parse a model answer into a payload shaped like :func:`analysis_schema.empty_payload`.

    Models often wrap JSON in a Markdown fence or add a sentence around it, and always
    answer with unknown keys or wrong widget types; both are tolerated here so the caller
    only has to deal with JSON that is genuinely unusable. Unknown sections and fields are
    dropped, selects are forced to a listed option, and scores to an integer 1-10.
    """
    text = _strip_to_object(content or "")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise LLMError("the local model did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise LLMError("the local model JSON was not an object")
    return _clean_payload(data)


def _require_enabled(allow_remote: bool) -> None:
    if not settings.llm_enabled:
        raise LLMError("the local LLM draft is disabled; set LLM_ENABLED=true to turn it on")
    if not settings.llm_endpoint_is_local() and not allow_remote:
        raise LLMError(
            "the configured LLM endpoint is not localhost; confirm you want to send "
            "warehouse context off this machine (allow_remote) before generating"
        )


def _post(messages: list[dict], *, session, timeout: float) -> str:
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    body = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        "stream": False,
    }
    try:
        response = session.post(settings.llm_endpoint, json=body, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise LLMError(
            f"could not reach the local model at {settings.llm_endpoint} ({type(exc).__name__})"
        ) from exc
    if not response.ok:
        raise LLMError(f"the local model returned HTTP {response.status_code}")
    try:
        payload = response.json()
        return payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("the local model response had no message content") from exc


def _system_prompt() -> str:
    return (
        "You draft an investment-analysis worksheet for a dividend-equity researcher. "
        "Return ONLY one JSON object, with no prose and no code fence, shaped as "
        '{"version": <int>, "sections": {"<section id>": {"<field id>": <value>}}}. '
        "Rules: use only the supplied warehouse context and never invent figures; leave a "
        'field as "" (or null for a score) when the context does not support it; give each '
        "analytical section a confidence and cite its data sources; do not state a "
        "recommendation until every earlier section is complete; a select must use one of "
        'its listed options or ""; a score is an integer 1-10.\n\n'
        "Schema (section id -> fields):\n" + _schema_digest()
    )


def _schema_digest() -> str:
    lines: list[str] = []
    for index, section in enumerate(schema.SECTIONS, start=1):
        lines.append(f'{index}. {section.title} ("{section.id}")')
        for field in section.all_fields:
            parts = [field.kind]
            if field.required:
                parts.append("required")
            if field.options:
                parts.append("options: " + " | ".join(field.options))
            lines.append(f'   - "{field.id}": {field.label} [{", ".join(parts)}]')
    return "\n".join(lines)


def _strip_to_object(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _clean_payload(data: dict) -> dict:
    payload: dict = {"version": schema.SCHEMA_VERSION, "sections": {}}
    raw_sections = data.get("sections")
    raw_sections = raw_sections if isinstance(raw_sections, dict) else {}
    for section in schema.SECTIONS:
        given = raw_sections.get(section.id)
        given = given if isinstance(given, dict) else {}
        values: dict = {}
        for field in section.all_fields:
            raw = given.get(field.id)
            if field.kind == "select":
                text = "" if raw is None else str(raw)
                values[field.id] = text if text in field.options else ""
            elif field.kind == "score":
                values[field.id] = raw if isinstance(raw, int) and 1 <= raw <= 10 else None
            else:
                values[field.id] = "" if raw is None else str(raw)
        payload["sections"][section.id] = values
    return payload
