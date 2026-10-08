"""Security detail: price, dividends, score history and fundamentals for one ticker."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app import ui
from app.views.screener import SELECTED_KEY

RANGES = {"1 year": 365, "3 years": 3 * 365, "5 years": 5 * 365, "All": None}

SCORE_PARTS = [
    "dividend_income_score",
    "sustainability_score",
    "legal_rights_score",
    "appreciation_score",
    "risk_score",
    "valuation_score",
    "composite_score",
]

FEATURE_LABELS = {
    "current_price": "Price",
    "annualized_dividend": "Annual dividend",
    "dividend_yield": "Yield",
    "dividend_growth": "Dividend growth",
    "earnings_payout": "Earnings payout",
    "fcf_payout": "FCF payout",
    "dividend_coverage": "Dividend cover",
    "debt_to_ebitda": "Debt/EBITDA",
    "interest_coverage": "Interest cover",
    "volatility_252d": "Volatility 252d",
    "momentum_252d": "Momentum 252d",
    "momentum_63d": "Momentum 63d",
}
PERCENT_FEATURES = {"dividend_yield", "dividend_growth", "earnings_payout", "fcf_payout"}


def _fmt(name: str, value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.2%}" if name in PERCENT_FEATURES else f"{value:,.2f}"


def _text(value) -> str:
    """Display text for a possibly missing value (None, NaN and NaT all read as N/A)."""
    return "N/A" if value is None or pd.isna(value) else str(value)


def profile(ticker: str) -> pd.DataFrame:
    return ui.query(
        """
        SELECT CAST(security_id AS text) AS security_id, ticker, security_name, security_type,
               cik, exchange_id, currency, coupon_rate, liquidation_preference, call_date,
               dividend_last_paid, sec_data_status
        FROM reference.securities WHERE ticker = :t AND active ORDER BY security_id LIMIT 1
        """,
        {"t": ticker},
    )


def prices(security_id: str, days: int | None) -> pd.DataFrame:
    since = (pd.Timestamp.today() - pd.Timedelta(days=days)).date() if days else None
    return ui.query(
        """
        SELECT DISTINCT ON (observation_date) observation_date, close, adjusted_close, volume
        FROM raw.market_data
        WHERE security_id = CAST(:sid AS uuid)
          AND (CAST(:since AS date) IS NULL OR observation_date >= CAST(:since AS date))
        ORDER BY observation_date, provider
        """,
        {"sid": security_id, "since": since},
    )


def price_section(security_id: str) -> None:
    st.subheader("Price")
    label = st.radio("Range", list(RANGES), index=1, horizontal=True, key="detail_range")
    df = prices(security_id, RANGES[label])
    if df.empty:
        st.caption("No market data stored for this security.")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.observation_date, y=df.close, name="Close", mode="lines"))
    if df.adjusted_close.notna().any():
        fig.add_trace(
            go.Scatter(
                x=df.observation_date,
                y=df.adjusted_close,
                name="Adjusted close",
                mode="lines",
                line={"dash": "dot"},
            )
        )
    fig.update_layout(margin={"t": 10}, yaxis_title="Price", xaxis_title=None)
    st.plotly_chart(fig, width="stretch")
    low, high = df.close.min(), df.close.max()
    st.caption(
        f"{len(df):,} trading days, {df.observation_date.min()} to {df.observation_date.max()}. "
        f"Close range {low:,.2f} to {high:,.2f}."
    )


def dividend_section(security_id: str) -> None:
    st.subheader("Dividends")
    df = ui.query(
        """
        SELECT ex_dividend_date, payment_date, amount, frequency, currency, provider
        FROM raw.dividend_data WHERE security_id = CAST(:sid AS uuid)
        ORDER BY ex_dividend_date DESC
        """,
        {"sid": security_id},
    )
    if df.empty:
        st.caption("No dividend events stored for this security.")
        return
    plot = df[df.amount.notna()]
    if not plot.empty:
        st.plotly_chart(
            px.bar(
                plot,
                x="ex_dividend_date",
                y="amount",
                color="provider",
                barmode="group",
                labels={"ex_dividend_date": "Ex-dividend date", "amount": "Per share"},
            ),
            width="stretch",
        )
    st.dataframe(df, hide_index=True, width="stretch")


def score_section(security_id: str) -> None:
    st.subheader("Scores")
    df = ui.query(
        f"SELECT as_of_date, {', '.join(SCORE_PARTS)}, score_coverage "
        "FROM model.scores WHERE security_id = CAST(:sid AS uuid) ORDER BY as_of_date",
        {"sid": security_id},
    )
    if df.empty:
        st.caption("This security has not been scored.")
        return
    latest = df.iloc[-1]
    coverage = "N/A" if pd.isna(latest.score_coverage) else f"{latest.score_coverage:.0%}"
    st.caption(f"Latest score date {latest.as_of_date}, coverage {coverage}")
    long = df.melt(
        id_vars="as_of_date", value_vars=SCORE_PARTS, var_name="component", value_name="score"
    ).dropna(subset=["score"])
    if len(df) > 1 and not long.empty:
        st.plotly_chart(
            px.line(long, x="as_of_date", y="score", color="component", markers=True),
            width="stretch",
        )
    elif not long.empty:
        st.plotly_chart(
            px.bar(
                long[long.component != "composite_score"],
                x="component",
                y="score",
                title=f"Component scores on {latest.as_of_date}",
            ),
            width="stretch",
        )
    st.dataframe(df.sort_values("as_of_date", ascending=False), hide_index=True, width="stretch")


def feature_section(security_id: str) -> None:
    st.subheader("Latest features")
    df = ui.query(
        f"SELECT as_of_date, {', '.join(FEATURE_LABELS)} FROM model.features "
        "WHERE security_id = CAST(:sid AS uuid) ORDER BY as_of_date DESC LIMIT 1",
        {"sid": security_id},
    )
    if df.empty:
        st.caption("No engineered features for this security.")
        return
    row = df.iloc[0]
    st.caption(f"As of {row.as_of_date}")
    cells = st.columns(4)
    for index, name in enumerate(FEATURE_LABELS):
        cells[index % 4].metric(FEATURE_LABELS[name], _fmt(name, row[name]))


def fundamentals_section(security_id: str) -> None:
    st.subheader("Fundamentals")
    df = ui.query(
        """
        SELECT period_end, fiscal_year, fiscal_period, revenue, operating_income, net_income,
               free_cash_flow, cash, debt, equity, filed, source
        FROM fundamentals.periodic_financials WHERE security_id = CAST(:sid AS uuid)
        ORDER BY period_end DESC, filed DESC NULLS LAST LIMIT 12
        """,
        {"sid": security_id},
    )
    if df.empty:
        st.caption("No reported fundamentals for this security.")
        return
    st.dataframe(df, hide_index=True, use_container_width=True)


def render() -> None:
    st.title("Security detail")
    tickers = ui.query(
        "SELECT ticker FROM reference.securities WHERE active ORDER BY ticker"
    ).ticker.tolist()
    if not tickers:
        st.warning("No active securities. Run the reference-data load first.")
        return

    chosen = st.session_state.get(SELECTED_KEY)
    index = tickers.index(chosen) if chosen in tickers else 0
    # No widget key: a keyed selectbox keeps its own state and would ignore a ticker
    # picked on the Screener after the first render.
    ticker = st.selectbox("Ticker", tickers, index=index)
    st.session_state[SELECTED_KEY] = ticker

    found = profile(ticker)
    if found.empty:
        st.error(f"{ticker} is not an active security.")
        return
    info = found.iloc[0]
    st.markdown(f"### {info.ticker}")
    st.caption(_text(info.security_name))
    # Text facts, not st.metric: a metric truncates a long value such as "common_stock".
    cells = st.columns(4)
    for cell, (label, value) in zip(
        cells,
        [
            ("Type", info.security_type),
            ("CIK", info.cik),
            ("Last dividend paid", info.dividend_last_paid),
            ("SEC data status", info.sec_data_status),
        ],
    ):
        cell.markdown(f"**{label}**  \n{_text(value)}")

    tabs = st.tabs(["Price", "Dividends", "Scores", "Features", "Fundamentals"])
    sid = info.security_id
    with tabs[0]:
        price_section(sid)
    with tabs[1]:
        dividend_section(sid)
    with tabs[2]:
        score_section(sid)
    with tabs[3]:
        feature_section(sid)
    with tabs[4]:
        fundamentals_section(sid)
