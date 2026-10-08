"""Dividend Equity Decision System: data views and operations console.

Run with ``streamlit run app/streamlit_app.py``. This file only builds the navigation and
the operator sign-in; each page lives in ``app/views`` and exposes ``render()``.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ui  # noqa: E402
from app.views import (  # noqa: E402
    data_explorer,
    health,
    integrations,
    operations,
    screener,
    security,
)

st.set_page_config(page_title="Dividend Equity CRISP-DM", layout="wide")

navigation = st.navigation(
    {
        "Data": [
            st.Page(
                screener.render,
                title="Screener",
                icon=":material/filter_alt:",
                url_path="screener",
                default=True,
            ),
            st.Page(
                security.render,
                title="Security detail",
                icon=":material/query_stats:",
                url_path="security",
            ),
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
navigation.run()
