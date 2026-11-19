"""Opt-in ledger persistence helper for material run scripts."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from .manifest_store import persist_manifest

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SHARED_DB_NAMES = {"dividend", "prod", "production", "dividend_equity"}


def _safety_issues(
    dsn: str,
    allow_nonlocal: bool,
    allow_shared_name: bool,
) -> list[str]:
    try:
        url = make_url(dsn)
    except Exception as exc:  # noqa: BLE001
        return [f"invalid DSN: {exc}"]
    issues: list[str] = []
    host = (url.host or "").lower()
    if not host:
        issues.append("DSN host is missing")
    elif host not in _LOCAL_HOSTS and not allow_nonlocal:
        issues.append(
            f"DSN host {host!r} is non-local; pass --allow-nonlocal only for isolated disposable target"
        )
    database = (url.database or "").lower()
    if database in _SHARED_DB_NAMES and not allow_shared_name:
        issues.append(
            f"DSN database name {url.database!r} looks shared/production-like; refuse without --allow-shared-name"
        )
    return issues


def persist_run_if_opted_in(
    *,
    manifest: Mapping[str, Any],
    outputs: Sequence[Mapping[str, Any]],
    dsn: str | None,
    enabled: bool,
    acknowledge: bool,
    recorded_by: str,
    allow_nonlocal: bool = False,
    allow_shared_name: bool = False,
) -> dict[str, Any] | None:
    """Persist a manifest/output bundle only when explicitly requested.

    Returns None when persistence is not enabled. Invalid combinations raise
    ValueError; ledger/DB failures propagate from the store layer. Callers decide
    how to report failures so existing file-artifact behavior remains intact.
    """
    if not enabled:
        return None
    if not dsn:
        raise ValueError("ledger DSN is required when persistence is enabled")
    if not acknowledge:
        raise ValueError("explicit ledger-write acknowledgement is required")
    issues = _safety_issues(dsn, allow_nonlocal, allow_shared_name)
    if issues:
        raise ValueError("; ".join(issues))

    engine = create_engine(dsn)
    try:
        with engine.begin() as conn:
            return persist_manifest(
                conn,
                manifest,
                outputs=outputs,
                recorded_by=recorded_by,
            )
    finally:
        engine.dispose()
