from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict, deque
from datetime import date
from threading import Lock
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status

from src.crispdm import openbb_client, sec_client
from src.crispdm.config import settings
from src.crispdm.db import read_df

# The interactive docs advertise every route and schema, so they are off unless
# a deployment opts in (they are a convenience on a laptop, not a public API).
_DOCS_ENABLED = os.getenv("API_ENABLE_DOCS", "").strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(
    title="Dividend Equity Data API",
    version="1.0.0",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

# A single shared secret behind a brute-forceable header needs a ceiling on
# guesses per minute, independent of whether the guess was right.
_RATE_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120"))
_MAX_TRACKED_CLIENTS = 10_000


class _SlidingWindowLimiter:
    """Best-effort per-client request cap over a rolling window.

    In-process on purpose: ``docker-compose`` runs uvicorn as one process, so
    every request passes through here. Scaling to multiple workers would need a
    shared store (Redis); this is a localhost convenience, not a distributed
    limiter. The tracked-client map is bounded and simply reset if a flood of
    distinct sources would otherwise grow it without limit.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        # A non-positive limit disables the check.
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    @property
    def window_seconds(self) -> float:
        return self._window

    def allow(self, key: str) -> bool:
        if self._limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            cutoff = now - self._window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            if len(self._hits) > _MAX_TRACKED_CLIENTS:
                self._hits.clear()
            return True


_rate_limiter = _SlidingWindowLimiter(_RATE_LIMIT_PER_MINUTE)


def _api_key() -> str | None:
    return os.getenv("API_KEY") or os.getenv("CRISPDM_API_KEY") or settings.api_key


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    # Throttle before validating the key so a wrong-key flood is capped too.
    client = request.client.host if request.client else "unknown"
    if not _rate_limiter.allow(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(int(_rate_limiter.window_seconds))},
        )
    configured_key = _api_key()
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key authentication is not configured",
        )
    # Compare bytes, not str: compare_digest raises TypeError on a non-ASCII
    # str, and a header is attacker-controlled, so a unicode key would have
    # turned a 401 into a 500. Encoding sidesteps that and keeps the constant
    # time, which is the whole reason for not writing `!=`.
    if not x_api_key or not secrets.compare_digest(
        x_api_key.encode("utf-8"), configured_key.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def _ticker(value: str) -> str:
    value = value.strip().upper()
    if not value or len(value) > 32 or any(not (char.isalnum() or char in ".-") for char in value):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if pd.isna(value):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [
        {key: _json_value(value) for key, value in row.items()} for row in frame.to_dict("records")
    ]


def _cap_facts(payload: Any, limit: int) -> dict[str, Any]:
    """Bound a Company Facts payload, which is otherwise tens of MB.

    Caps the number of XBRL concepts per taxonomy while keeping every other
    field intact. ``_truncated`` marks a partial response so a client never
    mistakes a capped view for the issuer's complete fact set; raise ``limit``
    (or use ``/financials`` for a shaped subset) when more is genuinely needed.
    """
    if not isinstance(payload, dict):
        return {"facts": payload, "_truncated": False}
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return {**payload, "_truncated": False}
    capped: dict[str, Any] = {}
    truncated = False
    for taxonomy, concepts in facts.items():
        if isinstance(concepts, dict) and len(concepts) > limit:
            capped[taxonomy] = dict(list(concepts.items())[:limit])
            truncated = True
        else:
            capped[taxonomy] = concepts
    return {**payload, "facts": capped, "_truncated": truncated}


def _company_entry(ticker: str) -> dict[str, Any]:
    for entry in sec_client.get_company_tickers().values():
        if str(entry.get("ticker", "")).upper() == ticker:
            return entry
    raise HTTPException(status_code=404, detail=f"Company {ticker} not found")


def _cik(ticker: str) -> int:
    entry = _company_entry(ticker)
    return int(entry["cik_str"])


def _openbb_call(*paths: str, ticker: str) -> list[dict[str, Any]]:
    target: Any = openbb_client.obb
    try:
        for path in paths:
            target = getattr(target, path)
        response = (
            target(symbol=ticker, provider=settings.openbb_provider)
            if settings.openbb_provider
            else target(symbol=ticker)
        )
        return _records(openbb_client._df(response))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenBB request failed: {exc}") from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/companies/", dependencies=[Depends(require_api_key)])
def companies(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    entries = list(sec_client.get_company_tickers().values())
    page = entries[offset : offset + limit]
    return {"items": page, "offset": offset, "limit": limit, "total": len(entries)}


@app.get("/companies/{ticker}", dependencies=[Depends(require_api_key)])
def company(ticker: str) -> dict[str, Any]:
    ticker = _ticker(ticker)
    entry = _company_entry(ticker)
    issuer = sec_client.get_issuer_data(entry["cik_str"]) or {}
    return {**entry, **issuer, "ticker": ticker}


@app.get("/filings/{ticker}", dependencies=[Depends(require_api_key)])
def filings(ticker: str, limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    ticker = _ticker(ticker)
    payload = sec_client.get_submissions(_cik(ticker))
    recent = payload.get("filings", {}).get("recent", {})
    items = []
    for index in range(min(limit, len(recent.get("form", [])))):
        items.append(
            {
                key: values[index]
                for key, values in recent.items()
                if isinstance(values, list) and index < len(values)
            }
        )
    return {"ticker": ticker, "cik": payload.get("cik"), "items": items}


@app.get("/facts/{ticker}", dependencies=[Depends(require_api_key)])
def facts(
    ticker: str,
    limit: int = Query(
        default=200,
        ge=1,
        le=5000,
        description=(
            "Maximum number of XBRL concepts returned per taxonomy. The raw "
            "Company Facts payload runs to tens of MB; the response is capped "
            "and flagged with _truncated when the cap bites."
        ),
    ),
) -> dict[str, Any]:
    ticker = _ticker(ticker)
    cik = _cik(ticker)
    try:
        stored = read_df(
            """SELECT cf.raw_payload FROM raw.companyfacts cf
               JOIN reference.securities s ON s.cik = cf.cik
               WHERE upper(s.ticker) = :ticker AND s.active = TRUE
               ORDER BY cf.retrieved_at DESC LIMIT 1""",
            {"ticker": ticker},
        )
        if not stored.empty and stored.iloc[0]["raw_payload"] is not None:
            payload = stored.iloc[0]["raw_payload"]
            return _cap_facts(payload, limit)
    except Exception:  # noqa: S110 - a missing/uninitialized DB must not block a live SEC read
        # A missing/uninitialized database should not prevent a live SEC read.
        pass
    try:
        return _cap_facts(sec_client.get_companyfacts(cik), limit)
    except sec_client.SECDataUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SEC_COMPANYFACTS_UNAVAILABLE",
                "ticker": ticker,
                "cik": exc.cik,
                "message": "SEC has no Company Facts dataset for this issuer",
            },
        ) from exc


@app.get("/financials/{ticker}", dependencies=[Depends(require_api_key)])
def financials(
    ticker: str,
    limit: int = Query(default=100, ge=1, le=1000),
    as_of: str | None = Query(
        default=None,
        description=(
            "Return the figures as they were known on this date (YYYY-MM-DD). "
            "Omit for the latest reported vintage of each period."
        ),
    ),
) -> dict[str, Any]:
    """Reported fundamentals, one row per fiscal period.

    The relation is versioned: a period that was restated appears once per
    filing, so 87.6% of periods carry more than one row. Selecting straight out
    of it would return the same period repeatedly -- for one issuer a limit of
    100 covered only 14 distinct periods -- and the limit would silently buy
    fewer periods than requested.

    Two readings are legitimate, so both are available. By default each period
    is reported as most recently filed, which is the current truth. ``as_of``
    reconstructs what was known on a past date, which is the point-in-time
    reading and must not be reconstructed by the client from the latest values.
    """
    ticker = _ticker(ticker)
    if as_of is None:
        frame = read_df(
            """SELECT DISTINCT ON (f.period_end) f.*
               FROM fundamentals.periodic_financials f
               JOIN reference.securities s ON s.security_id = f.security_id
               WHERE upper(s.ticker) = :ticker AND s.active = TRUE
               ORDER BY f.period_end DESC, f.filed DESC LIMIT :limit""",
            {"ticker": ticker, "limit": limit},
        )
    else:
        frame = read_df(
            """SELECT DISTINCT ON (f.period_end) f.*
               FROM fundamentals.periodic_financials f
               JOIN reference.securities s ON s.security_id = f.security_id
               WHERE upper(s.ticker) = :ticker AND s.active = TRUE
                 AND f.filed <= CAST(:as_of AS date)
               ORDER BY f.period_end DESC, f.filed DESC LIMIT :limit""",
            {"ticker": ticker, "as_of": as_of, "limit": limit},
        )
    return {"ticker": ticker, "items": _records(frame)}


@app.get("/openbb/ratios/{ticker}", dependencies=[Depends(require_api_key)])
def ratios(ticker: str) -> dict[str, Any]:
    ticker = _ticker(ticker)
    return {
        "ticker": ticker,
        "items": _openbb_call("equity", "fundamental", "ratios", ticker=ticker),
    }


@app.get("/openbb/valuation/{ticker}", dependencies=[Depends(require_api_key)])
def valuation(ticker: str) -> dict[str, Any]:
    ticker = _ticker(ticker)
    return {
        "ticker": ticker,
        "items": _openbb_call("equity", "fundamental", "overview", ticker=ticker),
    }


@app.get("/openbb/profile/{ticker}", dependencies=[Depends(require_api_key)])
def profile(ticker: str) -> dict[str, Any]:
    ticker = _ticker(ticker)
    return {"ticker": ticker, "items": _records(openbb_client.profile(ticker))}


@app.get("/openbb/analysts/{ticker}", dependencies=[Depends(require_api_key)])
def analysts(ticker: str) -> dict[str, Any]:
    ticker = _ticker(ticker)
    return {
        "ticker": ticker,
        "items": _openbb_call("equity", "estimates", "consensus", ticker=ticker),
    }


@app.get("/openbb/fundamentals/{ticker}", dependencies=[Depends(require_api_key)])
def fundamentals(ticker: str) -> dict[str, Any]:
    ticker = _ticker(ticker)
    ratios_data = ratios(ticker)["items"]
    valuation_data = valuation(ticker)["items"]
    return {"ticker": ticker, "ratios": ratios_data, "valuation": valuation_data}


@app.get("/metrics/enriched/{ticker}", dependencies=[Depends(require_api_key)])
def enriched(ticker: str) -> dict[str, Any]:
    ticker = _ticker(ticker)
    return {
        "ticker": ticker,
        "company": company(ticker),
        "financials": financials(ticker)["items"],
        "fundamentals": fundamentals(ticker),
    }
