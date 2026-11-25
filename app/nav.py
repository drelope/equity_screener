"""Cross-page navigation: one ticker, one registry, one return route.

Pages never import each other for navigation. ``streamlit_app.py`` registers its
``st.Page`` objects here once and every view calls ``open_page`` / ``set_ticker``.
"""

from __future__ import annotations

import streamlit as st

SELECTED_KEY = "selected_ticker"
RETURN_KEY = "return_route"
COMPARISON_KEY = "selected_comparison"
ORDER_KEY = "screener_order"

SCREENER = "screener"
SECURITY = "security"
ANALYSIS = "analysis"
DASHBOARD = "dashboard"

#: Workflow order, used by the flow bar.
STEPS = (
    (SCREENER, "Screener"),
    (SECURITY, "Security"),
    (ANALYSIS, "Analysis"),
    (DASHBOARD, "Dashboard"),
)
LABELS = dict(STEPS)
_PAGES_KEY = "_nav_pages"


def register(pages: dict[str, st.Page]) -> None:
    """Store the pages built by the entrypoint (rerun-safe)."""
    st.session_state[_PAGES_KEY] = pages


def set_ticker(ticker: str | None) -> None:
    if ticker:
        st.session_state[SELECTED_KEY] = ticker


def open_page(name: str, ticker: str | None = None, *, origin: str | None = None) -> None:
    """Switch to a registered page, optionally handing over a ticker.

    ``origin`` is remembered so the target can offer a "Back" button.
    """
    set_ticker(ticker)
    if origin:
        st.session_state[RETURN_KEY] = origin
    page = st.session_state.get(_PAGES_KEY, {}).get(name)
    if page is None:  # not running under the app entrypoint (e.g. a view in isolation)
        return
    st.switch_page(page)


def back_target(current: str) -> str | None:
    origin = st.session_state.get(RETURN_KEY)
    return origin if origin and origin != current else None


def siblings(ticker: str) -> tuple[str | None, str | None]:
    """Previous and next ticker in the last screener ordering."""
    order = st.session_state.get(ORDER_KEY) or []
    if ticker not in order:
        return None, None
    i = order.index(ticker)
    return (order[i - 1] if i > 0 else None, order[i + 1] if i + 1 < len(order) else None)


def render_flow_bar(current: str, ticker: str | None = None) -> None:
    """Workflow breadcrumb with Back and prev/next controls."""
    ticker = ticker or st.session_state.get(SELECTED_KEY)
    cells = st.columns([1, 1, 1, 1, 1.4, 1, 1])
    for cell, (name, label) in zip(cells, STEPS):
        if name == current:
            cell.markdown(f"**:blue[{label}]**")
        elif name == SCREENER or ticker:
            if cell.button(label, key=f"flow_{current}_{name}", type="tertiary", width="stretch"):
                open_page(name, ticker, origin=current)
        else:
            cell.caption(label)
    back = back_target(current)
    if back and cells[4].button(
        f"Back to {LABELS[back].lower()}", key=f"flow_back_{current}", icon=":material/arrow_back:"
    ):
        open_page(back, ticker)
    if ticker:
        prev, nxt = siblings(ticker)
        if prev and cells[5].button("Prev", key=f"flow_prev_{current}", help=prev):
            set_ticker(prev)
            st.rerun()
        if nxt and cells[6].button("Next", key=f"flow_next_{current}", help=nxt):
            set_ticker(nxt)
            st.rerun()


def selectable_table(frame, *, key: str, origin: str, **kwargs) -> str | None:
    """Show ``frame`` (must have a ``ticker`` column) with single-row select and
    buttons that carry the chosen ticker to Security detail or the worksheet."""
    event = st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=key,
        **kwargs,
    )
    rows = event.selection.rows if event and event.selection else []
    if not rows:
        return None
    ticker = str(frame.iloc[rows[0]]["ticker"])
    set_ticker(ticker)
    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button(f"{ticker}: Security detail", key=f"{key}_sec"):
        open_page(SECURITY, ticker, origin=origin)
    if c2.button(f"{ticker}: Worksheet", key=f"{key}_ws"):
        open_page(ANALYSIS, ticker, origin=origin)
    return ticker


def seed_from_url() -> None:
    """Adopt ``?ticker=`` (shared link) when nothing is selected yet this session."""
    url_ticker = st.query_params.get("ticker")
    if url_ticker and not st.session_state.get(SELECTED_KEY):
        st.session_state[SELECTED_KEY] = url_ticker
