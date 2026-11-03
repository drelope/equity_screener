"""Dividend Equity Decision System: data views and operations console.

Run with ``streamlit run app/streamlit_app.py``. This file only builds the navigation and
the operator sign-in; each page lives in ``app/views`` and exposes ``render()``.
"""

import sys
from pathlib import Path

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

# `streamlit run app/streamlit_app.py` puts `app/` on sys.path, not the repository root,
# so `import app.views` needs the root added explicitly. Remove this if the package is
# ever installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import column_docs, nav, ui  # noqa: E402
from app.views import (  # noqa: E402
    dashboard,
    data_explorer,
    health,
    integrations,
    investment_analysis,
    operations,
    screener,
    security,
)

st.set_page_config(
    page_title="Dividend Equity CRISP-DM",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get help": None,
        "Report a bug": None,
        "About": (
            "Dividend Equity Decision System. Scores are rule-based percentile ranks: "
            f"{column_docs.SCORING_CAPTION}."
        ),
    },
)

PAGES = {
    nav.SCREENER: st.Page(
        screener.render,
        title="Screener",
        icon=":material/filter_alt:",
        url_path="screener",
        default=True,
    ),
    nav.SECURITY: st.Page(
        security.render,
        title="Security detail",
        icon=":material/query_stats:",
        url_path="security",
    ),
    nav.ANALYSIS: st.Page(
        investment_analysis.render,
        title=investment_analysis.PAGE_TITLE,
        icon=":material/edit_note:",
        url_path=investment_analysis.PAGE_PATH,
    ),
    nav.DASHBOARD: st.Page(
        dashboard.render,
        title=dashboard.PAGE_TITLE,
        icon=":material/space_dashboard:",
        url_path=dashboard.PAGE_PATH,
    ),
}
nav.register(PAGES)
navigation = st.navigation(
    {
        "Workflow": list(PAGES.values()),
        "Data": [
            st.Page(
                data_explorer.render,
                title="Data explorer",
                icon=":material/table_view:",
                url_path="explorer",
            ),
        ],
        "Operations": [
            st.Page(
                health.render, title="Health", icon=":material/monitor_heart:", url_path="health"
            ),
            st.Page(
                operations.render,
                title="Operations",
                icon=":material/schedule:",
                url_path="operations",
            ),
            st.Page(
                integrations.render,
                title="Integrations",
                icon=":material/hub:",
                url_path="integrations",
            ),
        ],
    }
)
ui.operator_panel()
try:
    navigation.run()
except SQLAlchemyError:
    # The most likely runtime failure: Postgres is down or DATABASE_URL is wrong. Show a
    # readable message instead of a traceback; any other exception still propagates.
    st.error(
        "Database unavailable. Check that PostgreSQL is running and that DATABASE_URL "
        "is correct, then reload the page."
    )
