"""A small client for the project's own data API (``api/main.py``).

Used by the web app's Integrations page. Only paths from ``ENDPOINTS`` can be called and
the ticker is validated and URL-quoted, so input cannot choose where the request goes.
The base URL and key come from server-side settings; the key is sent as ``X-API-Key``
and is never placed in a result or an error message.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import requests

TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,31}$")


@dataclass(frozen=True)
class Endpoint:
    label: str
    path: str  # may contain {ticker}
    needs_ticker: bool
    description: str
    params: tuple[str, ...] = ()


ENDPOINTS: dict[str, Endpoint] = {
    e.label: e
    for e in (
        Endpoint("Company", "/companies/{ticker}", True, "SEC entry plus issuer data."),
        Endpoint("Filings", "/filings/{ticker}", True, "Recent SEC filings.", ("limit",)),
        Endpoint(
            "Financials", "/financials/{ticker}", True, "Stored fundamentals.", ("limit", "as_of")
        ),
        Endpoint("Company facts", "/facts/{ticker}", True, "XBRL company facts payload."),
        Endpoint("OpenBB profile", "/openbb/profile/{ticker}", True, "Profile via OpenBB."),
        Endpoint("OpenBB ratios", "/openbb/ratios/{ticker}", True, "Ratios via OpenBB."),
        Endpoint(
            "Enriched metrics",
            "/metrics/enriched/{ticker}",
            True,
            "Company, financials and ratios.",
        ),
        Endpoint(
            "Company list", "/companies/", False, "SEC ticker file, paged.", ("offset", "limit")
        ),
    )
}


@dataclass
class ApiResult:
    ok: bool
    status_code: int | None
    data: Any
    error: str | None
    elapsed_ms: float


class ApiClient:
    def __init__(self, base_url: str, api_key: str | None, *, timeout: float = 20.0, session=None):
        parsed = urlparse(base_url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("the API base URL must be an http(s) URL")
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self.timeout = timeout
        self._session = session or requests.Session()

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def _get(self, path: str, params: dict | None, *, auth: bool) -> ApiResult:
        headers = {"Accept": "application/json"}
        if auth and self._key:
            headers["X-API-Key"] = self._key
        started = time.perf_counter()
        try:
            response = self._session.get(
                self.base_url + path, params=params or None, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            # The message of a requests error can include the URL but never our header.
            return ApiResult(False, None, None, f"{type(exc).__name__}: {exc}", _ms(started))
        elapsed = _ms(started)
        try:
            body = response.json()
        except ValueError:
            body = response.text[:2000]
        if response.ok:
            return ApiResult(True, response.status_code, body, None, elapsed)
        detail = body.get("detail") if isinstance(body, dict) else body
        return ApiResult(
            False, response.status_code, None, f"HTTP {response.status_code}: {detail}", elapsed
        )

    def health(self) -> ApiResult:
        return self._get("/health", None, auth=False)

    def call(self, label: str, ticker: str | None = None, params: dict | None = None) -> ApiResult:
        try:
            endpoint = ENDPOINTS[label]
        except KeyError:
            raise ValueError(f"unknown endpoint {label!r}") from None
        path = endpoint.path
        if endpoint.needs_ticker:
            symbol = (ticker or "").strip().upper()
            if not TICKER_RE.fullmatch(symbol):
                raise ValueError("enter a ticker such as KO or BAC-PK")
            path = path.format(ticker=quote(symbol, safe=""))
        allowed = {
            k: v for k, v in (params or {}).items() if k in endpoint.params and v not in (None, "")
        }
        return self._get(path, allowed, auth=True)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
