"""Integrations: the systems this app talks to, and a way to check each one.

Reading the database status is open. Calling the API uses the server's API key and can
reach paid providers, so the endpoint caller needs a signed-in operator. Secrets are
reported only as set / not set; their values never reach the page.
"""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from app import ui
from src.crispdm.api_client import ENDPOINTS, ApiClient, ApiResult
from src.crispdm.config import settings

PLACEHOLDER_AGENT = "Your Name your.email@example.com"


@st.cache_data(ttl=30, show_spinner=False)
def api_health(base_url: str) -> ApiResult:
    return ApiClient(base_url, None, timeout=5.0).health()


def database_section() -> None:
    st.subheader("Database")
    started = time.perf_counter()
    try:
        info = ui.query(
            """
            SELECT version() AS server, pg_size_pretty(pg_database_size(current_database())) AS size,
                   current_database() AS database,
                   (SELECT max(version) FROM schema_migrations) AS migration
            """
        ).iloc[0]
    except Exception as exc:
        st.error(f"The database is unreachable ({type(exc).__name__}).")
        return
    elapsed = (time.perf_counter() - started) * 1000
    cells = st.columns(4)
    cells[0].metric("Database", info.database)
    cells[1].metric("Size", info["size"])
    cells[2].metric(
        "Latest migration", f"V{int(info.migration):04d}" if pd.notna(info.migration) else "N/A"
    )
    cells[3].metric("Last query", f"{elapsed:.0f} ms", help="Cached results show a lower figure.")
    st.caption(info.server)

    tables = ui.query(
        """
        SELECT n.nspname AS schema, count(*) AS tables,
               sum(greatest(c.reltuples, 0))::bigint AS approx_rows
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'public')
        GROUP BY 1 ORDER BY 3 DESC
        """
    )
    st.dataframe(tables, hide_index=True, width="stretch")
    st.caption("Row counts are the planner's estimates, not exact counts.")


def api_section() -> None:
    st.subheader("API")
    base = settings.api_base_url
    try:
        health = api_health(base)
    except ValueError as exc:
        st.error(str(exc))
        return
    cells = st.columns(3)
    cells[0].metric("Base URL", base)
    cells[1].metric("Health", "up" if health.ok else "down")
    cells[2].metric("Response", f"{health.elapsed_ms:.0f} ms")
    if not health.ok:
        st.warning(f"The API did not answer: {health.error}")
    st.caption(f"Interactive documentation: {base.rstrip('/')}/docs")

    st.markdown("**Try an endpoint**")
    if not ui.controls_enabled():
        ui.require_controls_note()
    if not settings.api_key:
        st.caption("No API_KEY is configured here, so authenticated endpoints will be refused.")

    label = st.selectbox("Endpoint", list(ENDPOINTS), key="api_endpoint")
    endpoint = ENDPOINTS[label]
    st.caption(f"{endpoint.description}  `GET {endpoint.path}`")
    ticker = (
        st.text_input("Ticker", value="KO", max_chars=32, key="api_ticker")
        if endpoint.needs_ticker
        else None
    )
    params = {}
    cols = st.columns(max(len(endpoint.params), 1))
    for col, name in zip(cols, endpoint.params):
        params[name] = col.text_input(name, key=f"api_param_{name}", max_chars=64)

    if st.button("Call", disabled=not ui.controls_enabled(), key="api_call"):
        try:
            result = ApiClient(base, settings.api_key).call(label, ticker, params)
        except ValueError as exc:
            st.error(str(exc))
            return
        _show_result(result)


def _show_result(result: ApiResult) -> None:
    if not result.ok:
        st.error(result.error)
        return
    st.success(f"HTTP {result.status_code} in {result.elapsed_ms:.0f} ms")
    data = result.data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        st.dataframe(pd.DataFrame(data), hide_index=True, width="stretch")
    else:
        st.json(data, expanded=1)


def providers_section() -> None:
    st.subheader("Configuration")
    rows = [
        ("OpenBB provider", settings.openbb_provider or "default"),
        (
            "SEC user agent",
            "set"
            if settings.sec_user_agent and settings.sec_user_agent != PLACEHOLDER_AGENT
            else "NOT SET (still the placeholder; SEC may throttle requests)",
        ),
        ("API key for the API", "set" if settings.api_key else "not set"),
        ("Operator token", "set" if settings.ops_admin_token else "not set (controls are off)"),
        ("API base URL", settings.api_base_url),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["setting", "value"]), hide_index=True, width="stretch")


def render() -> None:
    st.title("Integrations")
    ui.refresh_button("integrations_refresh")
    database_section()
    api_section()
    providers_section()
