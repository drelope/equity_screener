"""Shared ticker picker for the security and investment-analysis pages.

The default list is the dividend-equity universe: active common stock flagged as a
dividend payer. The worksheet and detail page are dividend tools, so leading with the
full 10k-listing reference table buries the relevant names under funds, debt and
non-payers. An explicit checkbox restores every active listing for one-off research.
"""

from __future__ import annotations

import streamlit as st

from app import ui
from app.views.screener import SELECTED_KEY

DIVIDEND_TICKERS_SQL = (
    "SELECT s.ticker FROM reference.securities s "
    "WHERE s.active AND s.security_type = 'common_stock' AND s.dividend "
    "ORDER BY s.ticker"
)
ALL_TICKERS_SQL = "SELECT s.ticker FROM reference.securities s WHERE s.active ORDER BY s.ticker"


def load_tickers(*, include_all=False, query=None) -> list[str]:
    """Active tickers in the dividend universe, or every active listing on override."""
    query = query or ui.query
    sql = ALL_TICKERS_SQL if include_all else DIVIDEND_TICKERS_SQL
    return query(sql).ticker.tolist()


def render_ticker_picker(key_prefix: str, *, help_text: str | None = None) -> str | None:
    """Render the override and ticker selectbox, returning the chosen ticker.

    A ticker already selected elsewhere (for example the Screener) stays in the list even
    when it falls outside the default universe, so switching pages does not silently
    replace the user's choice.

    The selection is mirrored to the ``ticker`` query parameter so a detail or
    worksheet URL can be shared or bookmarked. Precedence: an external session-state
    write (Screener row, sibling listing, worksheet handoff) beats the widget, the
    widget beats the URL, and the URL seeds a fresh session (shared link).
    """
    widget_key = f"{key_prefix}_ticker"
    synced_key = f"{key_prefix}_ticker_synced"
    url_ticker = st.query_params.get("ticker") or None
    chosen = st.session_state.get(SELECTED_KEY)
    widget_value = st.session_state.get(widget_key)
    synced = st.session_state.get(synced_key)

    if chosen is not None and chosen != synced:
        # External writer: screener row, sibling listing or worksheet handoff.
        st.session_state[widget_key] = chosen
    elif widget_value is not None and widget_value != synced:
        # The user changed the selectbox on the previous run.
        chosen = widget_value
        st.session_state[SELECTED_KEY] = widget_value
    elif url_ticker is not None and url_ticker != synced:
        # Shared link, bookmark or browser navigation.
        chosen = url_ticker
        st.session_state[SELECTED_KEY] = url_ticker
        st.session_state[widget_key] = url_ticker

    show_all = st.checkbox(
        "Show all active securities",
        key=f"{key_prefix}_show_all_tickers",
        help=help_text
        or "Override the default list of active dividend-paying common stock. Use this for "
        "preferreds, non-payers, funds, debt or other listings.",
    )
    tickers = load_tickers(include_all=show_all)
    chosen = st.session_state.get(SELECTED_KEY)
    if chosen and chosen not in tickers:
        tickers = sorted([*tickers, chosen])
    if not tickers:
        st.warning(
            "No active dividend-paying common stock. Tick **Show all active securities** "
            "to use the full reference universe."
        )
        return None
    # Only pass a default index when the widget was not pre-seeded from state,
    # otherwise Streamlit warns about a default combined with session state.
    kwargs = {"index": tickers.index(chosen) if chosen in tickers else 0}
    if widget_key in st.session_state:
        kwargs = {}
    ticker = st.selectbox("Ticker", tickers, key=widget_key, **kwargs)
    st.session_state[SELECTED_KEY] = ticker
    st.session_state[synced_key] = ticker
    if url_ticker != ticker:
        st.query_params["ticker"] = ticker
    return ticker
