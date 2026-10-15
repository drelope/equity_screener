import logging
import random
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_RETRY_STATUSES: Tuple[int, ...] = (429, 500, 502, 503, 504)
DEFAULT_MAX_RETRIES = 4
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 60.0


def _parse_retry_after(response: requests.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        retry_at = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if retry_at is None:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def _sleep_for(attempt: int, base_delay: float, max_delay: float, jitter: bool) -> float:
    delay = min(base_delay * (2**attempt), max_delay)
    if jitter:
        delay *= 1.0 + random.uniform(0.0, 0.1)  # noqa: S311 - backoff jitter, not crypto
    time.sleep(delay)
    return delay


def request_with_backoff(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    retry_statuses: Tuple[int, ...] = DEFAULT_RETRY_STATUSES,
    jitter: bool = True,
    **kwargs,
) -> requests.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            response = session.request(method, url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            delay = _sleep_for(attempt, base_delay, max_delay, jitter)
            logger.warning(
                "Request to %s failed (%s); retrying in %.1fs (attempt %d/%d)",
                url,
                exc,
                delay,
                attempt + 1,
                max_retries,
            )
            continue

        if response.status_code not in retry_statuses or attempt >= max_retries:
            return response

        retry_after = _parse_retry_after(response)
        if retry_after is not None:
            delay = min(retry_after, max_delay)
            time.sleep(delay)
        else:
            delay = _sleep_for(attempt, base_delay, max_delay, jitter)
        logger.warning(
            "Request to %s returned %d; retrying in %.1fs (attempt %d/%d)",
            url,
            response.status_code,
            delay,
            attempt + 1,
            max_retries,
        )

    if last_exc is not None:
        raise last_exc
    return response


class Throttle:
    def __init__(self, min_interval: float):
        self.min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next_allowed - now
            self._next_allowed = max(now, self._next_allowed) + self.min_interval
        if delay > 0:
            time.sleep(delay)
