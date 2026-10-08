"""Shared helpers for the Streamlit pages: cached reads, formatting and the operator gate.

Reading is open to anyone who can reach the app. Anything that changes the warehouse or
reaches out to another system (queueing, scheduling or cancelling a task, calling the
API with its key) needs the operator token; see ``src.crispdm.ops.auth`` for the rules.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from src.crispdm.config import settings
from src.crispdm.db import engine, read_df
from src.crispdm.ops import auth

OPERATOR_KEY = "operator"
THROTTLE_KEY = "operator_throttle"

STATUS_COLOUR = {
    "ok": "green",
    "succeeded": "green",
    "success": "green",
    "attention": "red",
    "failed": "red",
    "timed_out": "red",
    "info": "blue",
    "running": "orange",
    "queued": "gray",
    "cancelled": "gray",
}


@st.cache_data(ttl=60, show_spinner="Querying the database")
def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """A cached read-only query. The text is always a fixed statement written in this
    package; user input travels only in ``params``."""
    return read_df(sql, params=params)


def refresh_button(key: str) -> None:
    """Drop every cached read so the next rerun queries the database again."""
    if st.button("Refresh data", key=key, help="Discard cached results and re-query"):
        st.cache_data.clear()
        st.rerun()


def status_label(status: str | None) -> str:
    """Coloured text for a status word."""
    word = status or "unknown"
    return f":{STATUS_COLOUR.get(word, 'gray')}[{word}]"


def fmt_ts(value, *, tz: str | None = None) -> str:
    """A compact timestamp, or a dash for a missing one."""
    if value is None or pd.isna(value):
        return "-"
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None and tz:
        stamp = stamp.tz_convert(tz)
    return f"{stamp:%Y-%m-%d %H:%M}"


def fmt_duration(start, end) -> str:
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return "-"
    seconds = int((end - start).total_seconds())
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def now_utc() -> datetime:
    return pd.Timestamp.now(tz="UTC").to_pydatetime()


# --- operator gate ---------------------------------------------------------------


def operator() -> str | None:
    """The signed-in operator's label, or None."""
    return st.session_state.get(OPERATOR_KEY)


def controls_enabled() -> bool:
    return operator() is not None and auth.configured_token(settings.ops_admin_token) is not None


def operator_panel() -> None:
    """The sidebar sign-in. Rendered once by the app shell, before any page runs."""
    token = auth.configured_token(settings.ops_admin_token)
    with st.sidebar:
        st.divider()
        st.subheader("Operator")
        if token is None:
            st.session_state.pop(OPERATOR_KEY, None)
            st.caption(
                "Controls are off. Set OPS_ADMIN_TOKEN (at least "
                f"{auth.MIN_TOKEN_LENGTH} characters) and restart the app to enable them."
            )
            return
        if operator():
            st.caption(f"Signed in as {operator()}")
            if st.button("Sign out", key="operator_sign_out"):
                st.session_state.pop(OPERATOR_KEY, None)
                st.rerun()
            return

        throttle = st.session_state.setdefault(THROTTLE_KEY, auth.Throttle())
        wait = throttle.remaining()
        with st.form("operator_sign_in", clear_on_submit=True):
            name = st.text_input("Your name", max_chars=60)
            secret = st.text_input("Operator token", type="password")
            submitted = st.form_submit_button("Sign in", disabled=wait > 0)
        if wait:
            st.warning(f"Too many attempts. Try again in {wait}s.")
        if submitted and not wait:
            ok = auth.check_token(secret, settings.ops_admin_token)
            throttle.record(ok)
            if ok:
                st.session_state[OPERATOR_KEY] = auth.clean_operator(name)
                st.rerun()
            st.error("That token was not accepted.")


def require_controls_note() -> None:
    """Explain, in place, why a control is disabled."""
    if auth.configured_token(settings.ops_admin_token) is None:
        st.info("Operator controls are off: OPS_ADMIN_TOKEN is not set.")
    elif operator() is None:
        st.info("Sign in as an operator in the sidebar to use these controls.")


__all__ = [
    "controls_enabled",
    "engine",
    "fmt_duration",
    "fmt_ts",
    "now_utc",
    "operator",
    "operator_panel",
    "query",
    "refresh_button",
    "require_controls_note",
    "status_label",
]
