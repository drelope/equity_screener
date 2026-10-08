"""Operator authentication for the web app's control actions.

The app is a data viewer first. Queueing, scheduling and cancelling tasks change the
warehouse, so they sit behind a shared operator token. The rules:

* Fail closed. With no token configured (or one shorter than ``MIN_TOKEN_LENGTH``) the
  controls are off and the app says why. There is no default token.
* Compare in constant time, over bytes, so a non-ASCII attempt is a failed login and not
  an exception.
* Back off after repeated failures. The counter lives in the session, so it slows a
  person at the keyboard rather than a script that opens new sessions; the real boundary
  is that the app listens on the loopback only (see docker-compose.yml).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

MIN_TOKEN_LENGTH = 12
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60


def configured_token(value: str | None) -> str | None:
    """The usable token, or None when it is unset or too short to trust."""
    if value is None:
        return None
    value = value.strip()
    return value if len(value) >= MIN_TOKEN_LENGTH else None


def check_token(candidate: str | None, configured: str | None) -> bool:
    token = configured_token(configured)
    if token is None or not candidate:
        return False
    return secrets.compare_digest(candidate.encode("utf-8"), token.encode("utf-8"))


@dataclass
class Throttle:
    """Session-scoped failure counter with a fixed lockout."""

    failures: int = 0
    locked_until: float = 0.0

    def remaining(self, now: float | None = None) -> int:
        """Seconds left in a lockout; 0 when attempts are allowed."""
        now = time.monotonic() if now is None else now
        return max(0, int(self.locked_until - now + 0.999))

    def record(self, ok: bool, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if ok:
            self.failures = 0
            self.locked_until = 0.0
            return
        self.failures += 1
        if self.failures >= MAX_FAILURES:
            self.locked_until = now + LOCKOUT_SECONDS
            self.failures = 0


def clean_operator(label: str | None) -> str:
    """A bounded, printable operator label for the audit columns."""
    label = "".join(ch for ch in (label or "") if ch.isprintable()).strip()
    return label[:60] or "operator"
