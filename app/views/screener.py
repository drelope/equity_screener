"""Screener: filter, sort and chart the scored universe."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from app import ui
from src.crispdm.feature_window import carry_forward_days, dashboard_features_sql

COLUMNS = (
    "f.current_price,f.dividend_yield,f.dividend_growth,f.fcf_payout,"
    "f.dividend_coverage,f.debt_to_ebitda,f.interest_coverage,f.volatility_252d"
)

SORTABLE = {
    "Composite score": "composite_score",
    "Dividend yield": "dividend_yield",
    "Score coverage": "score_coverage",
    "Dividend growth": "dividend_growth",
    "Debt / EBITDA": "debt_to_ebitda",
    "Interest coverage": "interest_coverage",
    "Volatility (252d)": "volatility_252d",
    "Price": "current_price",
    "Ticker": "ticker",
}

TABLE_COLUMNS = [
    "ticker",
    "security_type",
    "as_of_date",
    "current_price",
    "dividend_yield",
    "dividend_growth",
    "composite_score",
    "score_coverage",
    "fcf_payout",
    "dividend_coverage",
    "debt_to_ebitda",
    "interest_coverage",
    "volatility_252d",
]

SELECTED_KEY = "selected_ticker"


def _median(series, fmt: str) -> str:
    values = series.dropna()
    return fmt.format(values.median()) if len(values) else "N/A"


def metrics(df) -> None:
    """The headline numbers. A blank ratio is ambiguous between "not computable" and "not
    yet built", so each shows how many securities report it beside the value; a column
    empty for everyone then reads as a pipeline gap, not a sector of tidy companies."""
    scored = df.composite_score.dropna()
    cov = df.score_coverage.dropna()
    d2e = df.debt_to_ebitda.dropna()
    ic = df.interest_coverage.dropna()
    cells = st.columns(6)
    cells[0].metric("Securities", len(df))
    cells[1].metric("Median yield", _median(df.dividend_yield, "{:.2%}"))
    cells[2].metric(f"Median score ({len(scored)}/{len(df)} scored)", _median(scored, "{:.2f}"))
    cells[3].metric(f"Median coverage ({len(cov)}/{len(df)} scored)", _median(cov, "{:.0%}"))
    cells[4].metric(f"Median debt/EBITDA ({len(d2e)}/{len(df)})", _median(d2e, "{:.2f}x"))
    cells[5].metric(f"Median interest cover ({len(ic)}/{len(df)})", _median(ic, "{:.2f}x"))


def apply_filters(df):
    """Render the filter controls and return the filtered, sorted frame."""
    with st.expander("Filter and sort", expanded=True):
        a, b, c = st.columns([2, 2, 2])
        min_yield = a.slider("Minimum dividend yield", 0.0, 0.20, 0.0, 0.005, format="%.3f")
        types_all = sorted(df.security_type.dropna().unique())
        types = b.multiselect("Security type", types_all, default=types_all)
        search = c.text_input("Ticker contains", max_chars=32).strip()

        d, e, f, g = st.columns([2, 2, 2, 2])
        scored_only = d.checkbox("Scored securities only", value=False)
        top = float(df.composite_score.max()) if df.composite_score.notna().any() else 1.0
        min_score = e.slider("Minimum composite score", 0.0, max(top, 0.01), 0.0, 0.01)
        sort_label = f.selectbox("Sort by", list(SORTABLE))
        descending = g.checkbox("Descending", value=sort_label != "Ticker")

    view = df[df.dividend_yield.fillna(0) >= min_yield]
    view = view[view.security_type.isin(types)]
    if search:
        view = view[view.ticker.str.contains(search, case=False, regex=False, na=False)]
    if scored_only:
        view = view[view.composite_score.notna()]
    if min_score > 0:
        view = view[view.composite_score.fillna(-1) >= min_score]
    return view.sort_values(SORTABLE[sort_label], ascending=not descending, na_position="last")


def table(view) -> None:
    shown = view[TABLE_COLUMNS]
    event = st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="screener_table",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", pinned=True),
            "security_type": "Type",
            "as_of_date": st.column_config.DateColumn("As of"),
            "current_price": st.column_config.NumberColumn("Price", format="%.2f"),
            "dividend_yield": st.column_config.NumberColumn("Yield", format="percent"),
            "dividend_growth": st.column_config.NumberColumn("Div. growth", format="percent"),
            "composite_score": st.column_config.NumberColumn("Score", format="%.3f"),
            "score_coverage": st.column_config.NumberColumn("Coverage", format="percent"),
            "fcf_payout": st.column_config.NumberColumn("FCF payout", format="%.2f"),
            "dividend_coverage": st.column_config.NumberColumn("Div. cover", format="%.2f"),
            "debt_to_ebitda": st.column_config.NumberColumn("Debt/EBITDA", format="%.2f"),
            "interest_coverage": st.column_config.NumberColumn("Int. cover", format="%.2f"),
            "volatility_252d": st.column_config.NumberColumn("Vol 252d", format="%.3f"),
        },
    )
    rows = event.selection.rows if event and event.selection else []
    if rows:
        ticker = str(shown.iloc[rows[0]]["ticker"])
        st.session_state[SELECTED_KEY] = ticker
        st.info(f"{ticker} selected. Open **Security detail** in the sidebar to see it.")
    st.download_button(
        "Download this table as CSV",
        shown.to_csv(index=False).encode("utf-8"),
        file_name="screener.csv",
        mime="text/csv",
    )


def charts(view) -> None:
    scored = view[view.composite_score.notna()]
    if scored.empty:
        st.caption("No scored securities in the current filter, so there is nothing to chart.")
        return
    tab_scatter, tab_hist, tab_top = st.tabs(["Yield vs score", "Score distribution", "Top 20"])
    with tab_scatter:
        plot = scored[scored.dividend_yield.notna()]
        st.plotly_chart(
            px.scatter(
                plot,
                x="dividend_yield",
                y="composite_score",
                color="security_type",
                hover_name="ticker",
                title="Dividend yield vs composite score",
                labels={"dividend_yield": "Dividend yield", "composite_score": "Composite score"},
            ),
            width="stretch",
        )
    with tab_hist:
        st.plotly_chart(
            px.histogram(
                scored,
                x="composite_score",
                color="security_type",
                nbins=30,
                title="Composite score distribution",
            ),
            width="stretch",
        )
    with tab_top:
        top = scored.nlargest(20, "composite_score").sort_values("composite_score")
        st.plotly_chart(
            px.bar(
                top,
                x="composite_score",
                y="ticker",
                orientation="h",
                color="security_type",
                title="Top 20 by composite score",
            ),
            width="stretch",
        )


def render() -> None:
    st.title("Screener")
    st.caption(
        "Income 25% | Sustainability 20% | Legal/Economic Rights 25% | "
        "Appreciation 15% | Risk 10% | Valuation 5%"
    )
    st.caption(
        "Scores are rule-based percentile ranks across the universe, not probabilities. "
        "The ML model was evaluated and not adopted."
    )
    ui.refresh_button("screener_refresh")
    df = ui.query(dashboard_features_sql(COLUMNS), {"carry_days": carry_forward_days()})
    if df.empty:
        st.warning("No data. Run ETL, feature engineering, and scoring first.")
        return

    metrics(df)
    view = apply_filters(df)
    st.caption(f"Showing {len(view):,} of {len(df):,} securities")
    if view.empty:
        st.warning("No securities match these filters.")
        return
    table(view)
    charts(view)
