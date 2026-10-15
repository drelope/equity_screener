"""Screener: filter, sort and chart the scored universe."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from app import column_docs, ui
from src.crispdm.feature_window import carry_forward_days, dashboard_features_sql

#: The V0068 point-in-time ratios the screener can display, as
#: ``display label -> (model.features column, kind)``. ``kind`` picks the format:
#: ``percent`` for a fraction (margins, yields), ``multiple`` for a ratio and
#: ``currency`` for the net-debt magnitude. Every one is NULL upstream when its
#: denominator is absent or non-positive, so a blank cell is a real signal.
FINANCIAL_METRICS = {
    "Gross margin": ("gross_margin", "percent"),
    "Operating margin": ("operating_margin", "percent"),
    "Net margin": ("net_margin", "percent"),
    "FCF margin": ("fcf_margin", "percent"),
    "OCF margin": ("ocf_margin", "percent"),
    "Cash conversion": ("cash_conversion", "multiple"),
    "Capex intensity": ("capex_intensity", "percent"),
    "FCF growth": ("fcf_growth", "percent"),
    "Net debt": ("net_debt", "currency"),
    "Net debt/EBITDA": ("net_debt_to_ebitda", "multiple"),
    "Current ratio": ("current_ratio", "multiple"),
    "Debt/equity": ("debt_to_equity", "multiple"),
    "P/E": ("pe_ratio", "multiple"),
    "Earnings yield": ("earnings_yield", "percent"),
    "FCF yield": ("fcf_yield", "percent"),
    "Price/book": ("price_to_book", "multiple"),
}
METRIC_COLUMNS = tuple(column for column, _kind in FINANCIAL_METRICS.values())
#: On by default, so the two most diagnostic ratios are visible without a click.
DEFAULT_METRICS = ["Net margin", "FCF yield"]

COLUMNS = "f.current_price,f.dividend_yield,f.debt_to_ebitda,f.interest_coverage," + ",".join(
    f"f.{column}" for column in METRIC_COLUMNS
)

SORTABLE = {
    "Composite score": "composite_score",
    "Dividend yield": "dividend_yield",
    "Ex-date": "ex_date",
    "Price": "current_price",
    "Ticker": "ticker",
    "Gross margin": "gross_margin",
    "Net margin": "net_margin",
    "FCF yield": "fcf_yield",
    "Price/book": "price_to_book",
}

TABLE_COLUMNS = [
    "ticker",
    "as_of_date",
    "current_price",
    "currency",
    "dividend_yield",
    "ex_date",
    "dividend_amount",
    "liquidation_preference",
    "first_call_date",
    "composite_score",
]

SELECTED_KEY = "selected_ticker"

# The table mixes several relations and renames a few columns, so each output column names
# its source explicitly: (relation, column, note). A note sharpens a column whose value the
# dashboard derives, such as the dividend pulled from the most recent stored event.
TABLE_HELP = {
    "ticker": ("reference.securities", "ticker", None),
    "as_of_date": ("model.features", "as_of_date", None),
    "current_price": ("model.features", "current_price", None),
    "currency": ("reference.securities", "currency", None),
    "dividend_yield": ("model.features", "dividend_yield", None),
    "ex_date": (
        "preferred.v_security_terms",
        "ex_date",
        (
            "Most recent dividend date for the security. OPENBB rows are true ex-dates; "
            "SEC XBRL rows are fiscal period-ends. A preferred series prefers its own "
            "dividend over the issuer's common."
        ),
    ),
    "dividend_amount": (
        "preferred.v_security_terms",
        "dividend_amount",
        "Per-share amount on ex_date; the CashPaid annual aggregate is not shown.",
    ),
    "liquidation_preference": (
        "preferred.v_security_terms",
        "liquidation_preference",
        "Per-share liquidation preference from per-series evidence only; N/A when unknown.",
    ),
    "first_call_date": (
        "preferred.v_security_terms",
        "first_call_date",
        "Earliest issuer call date from the governing document, else reference.securities.call_date.",
    ),
    "composite_score": ("model.scores", "composite_score", None),
}


def _help(column: str) -> str | None:
    relation, source, note = TABLE_HELP[column]
    return column_docs.help_text(relation=relation, column=source, note=note)


#: Table formats by kind. The printf-style strings are handed to the front end verbatim.
_METRIC_FORMATS = {"percent": "percent", "multiple": "%.2fx", "currency": "$%.0f"}


def _metric_config(columns) -> dict:
    """``st.column_config`` for the selected financial-metric columns.

    The label comes from :data:`FINANCIAL_METRICS` and the tooltip from the stored
    ``COMMENT ON COLUMN`` via column_docs, so the header help stays the schema's
    definition rather than a second copy that can drift.
    """
    config = {}
    for label, (column, kind) in FINANCIAL_METRICS.items():
        if column not in columns:
            continue
        config[column] = st.column_config.NumberColumn(
            label,
            format=_METRIC_FORMATS[kind],
            help=column_docs.help_text(relation="model.features", column=column),
        )
    return config


def _median(series, fmt: str) -> str:
    values = series.dropna()
    return fmt.format(values.median()) if len(values) else "N/A"


def metrics(df) -> None:
    """The headline numbers. A blank ratio is ambiguous between "not computable" and "not
    yet built", so each shows how many securities report it beside the value; a column
    empty for everyone then reads as a pipeline gap, not a sector of tidy companies."""
    scored = df.composite_score.dropna()
    cov = df.score_coverage.dropna()
    net = df.net_margin.dropna()
    fcf = df.fcf_yield.dropna()

    def feature(name: str, note: str) -> str | None:
        return column_docs.help_text(relation="model.features", column=name, note=note)

    cells = st.columns(6)
    cells[0].metric("Securities", len(df), help="Active securities matching the current filters.")
    cells[1].metric(
        "Median yield",
        _median(df.dividend_yield, "{:.2%}"),
        help=feature("dividend_yield", "Median across securities that report a yield."),
    )
    cells[2].metric(
        f"Median score ({len(scored)}/{len(df)} scored)",
        _median(scored, "{:.2f}"),
        help=column_docs.help_text(
            relation="model.scores",
            column="composite_score",
            note="Median across the scored securities; the bracket counts how many are scored.",
        ),
    )
    cells[3].metric(
        f"Median coverage ({len(cov)}/{len(df)} scored)",
        _median(cov, "{:.0%}"),
        help=column_docs.help_text(
            relation="model.scores",
            column="score_coverage",
            note="Median across scored securities.",
        ),
    )
    cells[4].metric(
        f"Median net margin ({len(net)}/{len(df)})",
        _median(net, "{:.1%}"),
        help=feature("net_margin", "Median across securities that report a net margin."),
    )
    cells[5].metric(
        f"Median FCF yield ({len(fcf)}/{len(df)})",
        _median(fcf, "{:.1%}"),
        help=feature("fcf_yield", "Median across securities that report an FCF yield."),
    )


def apply_filters(df):
    """Render the filter and sort controls, returning ``(view, metric_columns)``.

    ``metric_columns`` are the ``model.features`` ratio columns the user asked to append
    to the table, so :func:`table` can label and format exactly those.
    """
    with st.expander("Filter and sort", expanded=True):
        a, b, c = st.columns([2, 2, 2])
        min_yield = a.slider("Minimum dividend yield", 0.0, 0.20, 0.0, 0.005, format="%.3f")
        types_all = sorted(df.security_type.dropna().unique())
        default_types = ["preferred stock"] if "preferred stock" in types_all else types_all
        types = b.multiselect("Security type", types_all, default=default_types)
        search = c.text_input("Ticker contains", max_chars=32).strip()

        d, e, f, g = st.columns([2, 2, 2, 2])
        scored_only = d.checkbox("Scored securities only", value=False)
        top = float(df.composite_score.max()) if df.composite_score.notna().any() else 1.0
        min_score = e.slider("Minimum composite score", 0.0, max(top, 0.01), 0.0, 0.01)
        sort_label = f.selectbox("Sort by", list(SORTABLE))
        descending = g.checkbox("Descending", value=sort_label != "Ticker")

        h, i, j = st.columns([3, 2, 2])
        metric_labels = h.multiselect(
            "Financial metric columns",
            list(FINANCIAL_METRICS),
            default=DEFAULT_METRICS,
            help="Extra model.features ratios to append to the table.",
        )
        min_gross = i.number_input(
            "Minimum gross margin",
            value=None,
            step=0.01,
            format="%.3f",
            help="Hide securities below this gross margin. Blank disables the filter.",
        )
        max_pb = j.number_input(
            "Maximum price/book",
            value=None,
            step=0.1,
            format="%.2f",
            help="Hide securities above this price-to-book. Blank disables the filter.",
        )

    view = df[df.dividend_yield.fillna(0) >= min_yield]
    view = view[view.security_type.isin(types)]
    if search:
        view = view[view.ticker.str.contains(search, case=False, regex=False, na=False)]
    if scored_only:
        view = view[view.composite_score.notna()]
    if min_score > 0:
        view = view[view.composite_score.fillna(-1) >= min_score]
    if min_gross is not None:
        view = view[view.gross_margin >= min_gross]
    if max_pb is not None:
        view = view[view.price_to_book <= max_pb]
    ordered = view.sort_values(SORTABLE[sort_label], ascending=not descending, na_position="last")
    return ordered, [FINANCIAL_METRICS[label][0] for label in metric_labels]


def table(view, metric_columns) -> None:
    extra = [column for column in metric_columns if column not in TABLE_COLUMNS]
    shown = view[TABLE_COLUMNS + extra]
    config = {
        "ticker": st.column_config.TextColumn("Ticker", pinned=True, help=_help("ticker")),
        "as_of_date": st.column_config.DateColumn("As of", help=_help("as_of_date")),
        "current_price": st.column_config.NumberColumn(
            "Price", format="%.2f", help=_help("current_price")
        ),
        "currency": st.column_config.TextColumn("Ccy", width="small", help=_help("currency")),
        "dividend_yield": st.column_config.NumberColumn(
            "Yield", format="percent", help=_help("dividend_yield")
        ),
        "ex_date": st.column_config.DateColumn("Ex-date", help=_help("ex_date")),
        "dividend_amount": st.column_config.NumberColumn(
            "Dividend paid", format="%.4f", help=_help("dividend_amount")
        ),
        "liquidation_preference": st.column_config.NumberColumn(
            "Liquidation", format="%.2f", help=_help("liquidation_preference")
        ),
        "first_call_date": st.column_config.DateColumn("First call", help=_help("first_call_date")),
        "composite_score": st.column_config.NumberColumn(
            "Score", format="%.3f", help=_help("composite_score")
        ),
    }
    config.update(_metric_config(extra))
    event = st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="screener_table",
        column_config=config,
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
    view, metric_columns = apply_filters(df)
    st.caption(f"Showing {len(view):,} of {len(df):,} securities")
    if view.empty:
        st.warning("No securities match these filters.")
        return
    table(view, metric_columns)
    charts(view)
