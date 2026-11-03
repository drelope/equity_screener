"""Analyst dashboard: the 7-tab KPI, performance, risk and research suite.

The portfolio is the deterministic model in ``src.crispdm.portfolio``. This page
only formats it: it names the simulated book, the rebalance date and the
exclusions so a reader cannot mistake the output for an account or a backtest
with transaction costs. Every tab reads the same loaded context, so the numbers
on the position book and the risk monitor cannot disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app import nav, ui
from src.crispdm import portfolio as pf

PAGE_TITLE = "Analyst dashboard"
PAGE_PATH = "dashboard"

GROSS_LIMIT = 2.0
NET_LIMIT = 0.75
SINGLE_NAME_LIMIT = 0.10
SECTOR_LIMIT = 0.35

TAB_NAMES = (
    "Portfolio Dashboard",
    "Performance Analytics",
    "Risk Monitor",
    "Position Book",
    "Factor Attribution",
    "Research Pipeline",
    "Reports Center",
)


def _pct(value, digits: int = 1) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.{digits}%}"


def _money(value, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value) / 1_000_000:.{digits}f}M"


def _signed_money(value) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value) / 1_000:.0f}K"


def _ratio(value, digits: int = 2) -> str:
    if value is None or pd.isna(value) or not np.isfinite(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _load_context() -> dict | None:
    try:
        dates = pf.load_score_dates(query=ui.query)
        if len(dates) == 0:
            return None
        formed = pf.rebalance_date(dates)
        latest = pd.Timestamp(dates[-1])
        scored = pf.load_universe(formed, query=ui.query)
        if scored.empty:
            return None
        split_events = pf.load_split_events(query=ui.query)
        # One cleaned pass over the scored universe. Names with unreliable histories are
        # removed before the book is chosen, the same rule the backtest applies.
        cleaned, _ = pf.clean_prices(
            pf.load_prices(scored["security_id"], formed, latest, query=ui.query),
            split_events=split_events,
        )
        universe = pf.exclude_unreliable(scored, cleaned)
        if universe.empty:
            return None
        book = pf.select_portfolio(universe)
        prices = cleaned[cleaned["security_id"].isin(book["security_id"].astype(str))]
        returns = pf.total_return_matrix(prices)
        path = pf.portfolio_returns(returns, book)
        if path.empty:
            return None
        benchmark = None
        benchmark_prices = cleaned[cleaned["security_id"].isin(universe["security_id"].astype(str))]
        if not benchmark_prices.empty:
            benchmark = pf.total_return_matrix(benchmark_prices).mean(axis=1, skipna=True)
        risk_free = pf.load_risk_free(path.index, query=ui.query)
        performance = pf.performance_metrics(path["return"], benchmark, risk_free=risk_free)
        risk = pf.risk_metrics(returns, book)
        f_scores = pf.load_f_scores(book["security_id"], formed, query=ui.query)
        table = pf.holdings_table(book, returns, f_scores, risk)
        analyses = pf.load_analyses(query=ui.query)
        catalysts = pf.load_catalysts(
            book["security_id"], latest, latest + pd.Timedelta(days=90), query=ui.query
        )
        completed = [
            period for period in dates.to_period("M").unique() if period <= formed.to_period("M")
        ]
        return {
            "dates": dates,
            "formed": formed,
            "latest": latest,
            "universe": universe,
            "book": book,
            "returns": returns,
            "path": path,
            "benchmark": benchmark,
            "performance": performance,
            "risk": risk,
            "table": table,
            "analyses": analyses,
            "catalysts": catalysts,
            "rebalances": len(completed),
        }
    except Exception:
        # Keep user-facing messages safe while logging context for debugging.
        import logging
        import uuid

        incident = uuid.uuid4().hex[:10]
        logging.getLogger("app.views.dashboard").exception(
            "dashboard._load_context failed [incident=%s]", incident
        )
        st.error(f"Failed to load the model portfolio (incident {incident}). See logs for details.")
        if st.button("Retry", key="dashboard_retry"):
            try:
                ui.refresh_button()
            except Exception:
                st.cache_data.clear()
                st.rerun()
        st.stop()


def _nav_chart(path: pd.DataFrame) -> None:
    st.line_chart(path["nav"], y_label="NAV ($)")


def _allocation_chart(book: pd.DataFrame) -> None:
    allocation = (
        book.groupby(["sector", "side"], as_index=False)["notional"].sum().sort_values("notional")
    )
    figure = px.bar(
        allocation,
        x="notional",
        y="sector",
        color="side",
        orientation="h",
        barmode="group",
        labels={"notional": "Notional ($)", "sector": "", "side": "Side"},
        color_discrete_map={"Long": "#2ca02c", "Short": "#d62728"},
    )
    figure.update_layout(height=360, legend_title_text="")
    st.plotly_chart(figure, width="stretch")


def _portfolio_tab(context: dict) -> None:
    path = context["path"]
    book = context["book"]
    risk = context["risk"]
    performance = context["performance"]
    latest_return = path["return"].iloc[-1]
    day_pnl = path["nav"].iloc[-1] - path["nav"].iloc[-2] if len(path) > 1 else 0.0
    with st.container(horizontal=True):
        st.metric(
            "Model NAV",
            _money(path["nav"].iloc[-1]),
            delta=_pct(performance.get("cumulative_return")),
            border=True,
            chart_data=path["nav"].tolist(),
            chart_type="line",
        )
        st.metric("Latest day", _pct(latest_return), delta=_signed_money(day_pnl), border=True)
        st.metric("1-day 95% VaR", _pct(risk["historical_var"]), border=True)
        st.metric(
            "Gross / net",
            f"{_pct(book['weight'].abs().sum())} / {_pct(book['weight'].sum())}",
            border=True,
        )
    st.caption(
        f"Simulated 15 long / 8 short book formed at the {context['formed']:%Y-%m-%d} close. "
        "The next rebalance uses the last score date of the next completed month. "
        "Borrow, financing, slippage and taxes are excluded."
    )
    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.subheader("NAV since formation")
            _nav_chart(path)
    with right:
        with st.container(border=True):
            st.subheader("Sector allocation")
            _allocation_chart(book)
    with st.container(border=True):
        st.subheader("Largest long and short positions")
        top = pd.concat(
            [
                context["table"].query("side == 'Long'").nlargest(5, "weight"),
                context["table"].query("side == 'Short'").nsmallest(5, "weight"),
            ]
        )
        shown = top[["ticker", "side", "sector", "weight", "total_return", "pnl", "conviction"]]
        nav.selectable_table(
            shown.reset_index(drop=True),
            key="dashboard_top_positions",
            origin=nav.DASHBOARD,
            column_config={
                "weight": st.column_config.NumberColumn("Weight", format="percent"),
                "total_return": st.column_config.NumberColumn("Return", format="percent"),
                "pnl": st.column_config.NumberColumn("P&L", format="$%.0f"),
            },
        )


def _monthly_heatmap(monthly: pd.DataFrame) -> None:
    if monthly.empty:
        st.info("No monthly returns yet.")
        return
    month_names = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    pivot = monthly.pivot(index="year", columns="month", values="return").reindex(
        columns=range(1, 13)
    )
    text = pivot.map(lambda value: "n/a" if pd.isna(value) else f"{value:.1%}")
    figure = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(dtype=float),
            x=month_names,
            y=[str(year) for year in pivot.index],
            text=text.to_numpy(),
            texttemplate="%{text}",
            colorscale="RdYlGn",
            zmid=0,
            colorbar={"title": "Return"},
        )
    )
    figure.update_layout(height=300, xaxis_title="", yaxis_title="")
    st.plotly_chart(figure, width="stretch")


BACKTEST_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "backtests"


@st.cache_data(ttl=300, show_spinner="Loading the latest backtest")
def _load_latest_backtest(directory: str) -> dict | None:
    """The newest run with all three outputs written: metrics, daily series, periods."""
    for metrics_path in sorted(Path(directory).glob("metrics_*.json"), reverse=True):
        stamp = metrics_path.stem.removeprefix("metrics_")
        daily_path = metrics_path.with_name(f"daily_{stamp}.csv")
        periods_path = metrics_path.with_name(f"periods_{stamp}.csv")
        if not (daily_path.exists() and periods_path.exists()):
            continue
        return {
            "stamp": stamp,
            "metrics": json.loads(metrics_path.read_text(encoding="utf-8")),
            "daily": pd.read_csv(daily_path, index_col=0, parse_dates=True),
            "periods": pd.read_csv(periods_path, parse_dates=["formation", "end"]),
        }
    return None


def _backtest_section() -> None:
    run = _load_latest_backtest(str(BACKTEST_DIR))
    with st.container(border=True):
        st.subheader("Walk-forward backtest")
        if run is None:
            st.info(
                "No backtest run found. Run `python -m scripts.backtest` to build it "
                "from the stored month-end scores (about four minutes)."
            )
            return
        metrics = run["metrics"]
        daily = run["daily"]
        periods = run["periods"]
        held = int(metrics.get("held_periods", 0))
        cash = int(metrics.get("cash_periods", 0))
        st.warning(
            "Under review. The price filter removes stale prints and spike reversals, "
            "but corporate actions (splits) are not adjusted, the history is survivor-only, "
            "and short-squeeze risk is not limited. The figures below are not evidence "
            "about the score."
        )
        st.caption(
            f"Run {run['stamp']}: {held} monthly rebalances held, {cash} in cash, "
            f"{daily.index.min():%Y-%m-%d} to {daily.index.max():%Y-%m-%d}. "
            "Costs, borrow and financing are excluded. Each book is built from that "
            "month-end's scores and held to the next month-end, and it is compared with "
            "the equal-weight scored universe at the same formation dates."
        )
        with st.container(horizontal=True):
            st.metric("Cumulative return", _pct(metrics.get("cumulative_return")), border=True)
            st.metric("Sharpe", _ratio(metrics.get("sharpe")), border=True)
            st.metric("Max drawdown", _pct(metrics.get("max_drawdown")), border=True)
            st.metric(
                "Information ratio",
                _ratio(metrics.get("information_ratio")),
                border=True,
            )
            st.metric(
                "Avg one-way turnover / yr",
                _pct(metrics.get("average_one_way_turnover_annual")),
                border=True,
            )
        nav = pd.DataFrame(
            {
                "Model portfolio": daily["nav"],
                "Equal-weight universe": (1.0 + daily["benchmark"].fillna(0.0)).cumprod()
                * pf.BASE_NAV,
            }
        )
        st.line_chart(nav, y_label="NAV ($)")
        with st.expander("Rebalance periods"):
            st.dataframe(
                periods[
                    [
                        "formation",
                        "end",
                        "status",
                        "long_names",
                        "short_names",
                        "period_return",
                        "benchmark_return",
                        "turnover",
                        "missing_days",
                    ]
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "formation": st.column_config.DateColumn("Formed"),
                    "end": st.column_config.DateColumn("Next rebalance"),
                    "status": "Status",
                    "long_names": st.column_config.NumberColumn("Longs", format="%d"),
                    "short_names": st.column_config.NumberColumn("Shorts", format="%d"),
                    "period_return": st.column_config.NumberColumn("Model", format="percent"),
                    "benchmark_return": st.column_config.NumberColumn("Universe", format="percent"),
                    "turnover": st.column_config.NumberColumn("One-way turnover", format="percent"),
                    "missing_days": st.column_config.NumberColumn(
                        "Missing-return days", format="%d"
                    ),
                },
            )


def _performance_tab(context: dict) -> None:
    performance = context["performance"]
    if not performance.get("risk_free_applied", False):
        st.caption(
            "Sharpe uses a zero risk-free rate: the 3-month Treasury series does not "
            "cover every return date in this window."
        )
    with st.container(horizontal=True):
        st.metric("Sharpe", _ratio(performance.get("sharpe")), border=True)
        st.metric("Sortino", _ratio(performance.get("sortino")), border=True)
        st.metric("Calmar", _ratio(performance.get("calmar")), border=True)
        st.metric(
            "Information ratio",
            _ratio(performance.get("information_ratio")),
            border=True,
        )
        st.metric("Omega", _ratio(performance.get("omega")), border=True)
    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.subheader("Monthly return heatmap")
            _monthly_heatmap(pf.monthly_return_table(context["path"]["return"]))
    with right:
        with st.container(border=True):
            st.subheader("Drawdown")
            st.line_chart(context["path"]["drawdown"], y_label="Drawdown")
    with st.container(border=True):
        st.subheader("Model vs equal-weight scored universe")
        benchmark = context["benchmark"]
        if benchmark is None:
            st.info("Benchmark prices are unavailable.")
        else:
            aligned = benchmark.reindex(context["path"].index).fillna(0.0)
            comparison = pd.DataFrame(
                {
                    "Model portfolio": context["path"]["nav"],
                    "Equal-weight universe": (1.0 + aligned).cumprod() * pf.BASE_NAV,
                }
            )
            st.line_chart(comparison, y_label="NAV ($)")
            st.caption(
                "The benchmark is the equal-weight total return of every scored name with a "
                "price, not a published index, and it carries no costs either."
            )
    monthly = pf.monthly_return_table(context["path"]["return"])
    with st.expander("Monthly return table"):
        st.dataframe(
            monthly,
            hide_index=True,
            width="stretch",
            column_config={
                "year": st.column_config.NumberColumn("Year", format="%d"),
                "month": st.column_config.NumberColumn("Month", format="%d"),
                "return": st.column_config.NumberColumn("Return", format="percent"),
            },
        )
    _backtest_section()


def _component_var_chart(components: pd.DataFrame) -> None:
    ordered = components.sort_values("component_var")
    figure = px.bar(
        ordered,
        x="component_var",
        y="ticker",
        orientation="h",
        color="component_var",
        color_continuous_scale="RdYlGn",
        labels={"component_var": "Component VaR (fraction of NAV)", "ticker": ""},
    )
    figure.update_layout(height=420, coloraxis_showscale=False)
    st.plotly_chart(figure, width="stretch")


def _correlation_chart(correlation: pd.DataFrame) -> None:
    if correlation.empty:
        st.info("Not enough overlapping returns for a correlation matrix.")
        return
    figure = go.Figure(
        go.Heatmap(
            z=correlation.to_numpy(dtype=float),
            x=list(correlation.columns),
            y=list(correlation.index),
            colorscale="RdBu",
            zmin=-1,
            zmax=1,
            colorbar={"title": "Correlation"},
        )
    )
    figure.update_layout(height=520)
    st.plotly_chart(figure, width="stretch")


def _limit_table(book: pd.DataFrame) -> pd.DataFrame:
    gross = float(book["weight"].abs().sum())
    net = float(book["weight"].sum())
    single = float(book["weight"].abs().max())
    sector = float(
        book.assign(abs_weight=book["weight"].abs()).groupby("sector")["abs_weight"].sum().max()
    )
    rows = [
        ("Gross exposure", gross, GROSS_LIMIT),
        ("Net exposure", abs(net), NET_LIMIT),
        ("Largest single name", single, SINGLE_NAME_LIMIT),
        ("Largest sector", sector, SECTOR_LIMIT),
    ]
    return pd.DataFrame(
        [
            {
                "limit": label,
                "current": value,
                "maximum": maximum,
                "status": "Within limit" if value <= maximum else "Breach",
            }
            for label, value, maximum in rows
        ]
    )


def _risk_tab(context: dict) -> None:
    risk = context["risk"]
    book = context["book"]
    with st.container(horizontal=True):
        st.metric("Historical VaR 95", _pct(risk["historical_var"]), border=True)
        st.metric("Expected shortfall 95", _pct(risk["expected_shortfall"]), border=True)
        st.metric("Parametric VaR 95", _pct(risk["parametric_var"]), border=True)
        st.metric("Annualised volatility", _pct(risk["annual_volatility"]), border=True)
    if not risk.get("parametric_reliable", False):
        st.warning(
            f"Parametric VaR is not reliable: the covariance window has "
            f"{risk.get('covariance_observations', 0)} common dates for "
            f"{len(risk['components'])} names. It needs more dates than names. "
            "Read historical VaR instead."
        )
    components = risk["components"].merge(
        book[["security_id", "ticker", "sector", "side", "weight"]], on="security_id", how="left"
    )
    components["component_var_amount"] = components["component_var"] * pf.BASE_NAV
    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.subheader("VaR decomposition")
            _component_var_chart(components)
    with right:
        with st.container(border=True):
            st.subheader("Stress tests")
            stress = pf.stress_scenarios(risk["portfolio_returns"])
            st.dataframe(
                stress,
                hide_index=True,
                width="stretch",
                column_config={
                    "horizon_days": st.column_config.NumberColumn("Horizon (days)", format="%d"),
                    "worst_return": st.column_config.NumberColumn("Worst return", format="percent"),
                    "worst_loss": st.column_config.NumberColumn("Worst loss", format="percent"),
                },
            )
            st.caption("Realised worst window in the loaded history, not a hypothetical shock.")
        with st.container(border=True):
            st.subheader("Limit dashboard")
            limits = _limit_table(book)
            st.dataframe(
                limits,
                hide_index=True,
                width="stretch",
                column_config={
                    "current": st.column_config.NumberColumn("Current", format="percent"),
                    "maximum": st.column_config.NumberColumn("Limit", format="percent"),
                },
            )
            st.caption(
                "Illustrative research limits: 200% gross, 75% net, 10% single name, 35% sector."
            )
    with st.expander("Correlation matrix", expanded=True):
        tickers = book.set_index("security_id")["ticker"]
        correlation = risk["correlation"].rename(index=tickers, columns=tickers)
        _correlation_chart(correlation)


def _position_book_tab(context: dict) -> None:
    table = context["table"].copy()
    table["f_score_text"] = table["f_score"].map(
        lambda value: "n/a" if pd.isna(value) else f"{int(value)}/9"
    )
    table["component_var_amount"] = table["component_var"].fillna(0.0) * pf.BASE_NAV
    shown = table[
        [
            "ticker",
            "side",
            "sector",
            "weight",
            "notional",
            "total_return",
            "pnl",
            "f_score_text",
            "component_var_amount",
            "conviction",
        ]
    ]
    nav.selectable_table(
        shown.reset_index(drop=True),
        key="dashboard_position_book",
        origin=nav.DASHBOARD,
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", pinned=True),
            "side": st.column_config.TextColumn("Side"),
            "sector": st.column_config.TextColumn("Sector"),
            "weight": st.column_config.NumberColumn("Weight", format="percent"),
            "notional": st.column_config.NumberColumn("Notional", format="$%.0f"),
            "total_return": st.column_config.NumberColumn("Return", format="percent"),
            "pnl": st.column_config.NumberColumn("P&L", format="$%.0f"),
            "f_score_text": st.column_config.TextColumn("F-Score"),
            "component_var_amount": st.column_config.NumberColumn("Component VaR", format="$%.0f"),
            "conviction": st.column_config.TextColumn("Conviction"),
        },
    )
    st.caption(
        "F-Score is the nine-signal Piotroski score from the two latest filed fiscal "
        "years and is n/a when any signal is missing. Component VaR is parametric at 95%."
    )
    st.download_button(
        "Download position book (CSV)",
        shown.to_csv(index=False).encode("utf-8"),
        file_name=f"model-portfolio-{context['latest']:%Y-%m-%d}.csv",
        mime="text/csv",
        key="dashboard_position_csv",
    )


def _factor_tab(context: dict) -> None:
    exposures = pf.factor_exposures(context["book"])
    with st.container(border=True):
        st.subheader("Factor exposure")
        figure = go.Figure()
        for column, colour in (("long", "#2ca02c"), ("short", "#d62728")):
            figure.add_trace(
                go.Scatterpolar(
                    r=list(exposures[column]) + [exposures[column].iloc[0]],
                    theta=list(exposures["factor"]) + [exposures["factor"].iloc[0]],
                    fill="toself",
                    name=column.title(),
                    line_color=colour,
                )
            )
        figure.update_layout(
            height=430,
            polar={"radialaxis": {"range": [0, 1]}},
            legend_title_text="Sleeve",
        )
        st.plotly_chart(figure, width="stretch")
        st.caption(
            "Exposures are weighted score components (0-1 percentile ranks), not a "
            "Fama-French regression. The net series is long minus short."
        )
    with st.container(border=True):
        st.subheader("Sector weights vs scored universe")
        model = context["book"].groupby("sector")["weight"].apply(lambda values: values.abs().sum())
        model = model / model.sum()
        benchmark = context["universe"]["sector"].value_counts(normalize=True)
        comparison = pd.concat(
            [model.rename("model"), benchmark.rename("universe")], axis=1
        ).fillna(0.0)
        comparison["active"] = comparison["model"] - comparison["universe"]
        comparison = comparison.sort_values("active", ascending=False).reset_index()
        st.dataframe(
            comparison,
            hide_index=True,
            width="stretch",
            column_config={
                "model": st.column_config.NumberColumn("Model gross", format="percent"),
                "universe": st.column_config.NumberColumn("Universe share", format="percent"),
                "active": st.column_config.NumberColumn("Active", format="percent"),
            },
        )
        st.caption(
            "The benchmark is the equal-weight scored universe by security count, not a "
            "sector index."
        )
    with st.container(border=True):
        st.subheader("Sector P&L and excess return")
        attribution = pf.sector_attribution(
            context["book"], pf.position_returns(context["returns"], context["book"])
        )
        st.dataframe(
            attribution,
            hide_index=True,
            width="stretch",
            column_config={
                "pnl": st.column_config.NumberColumn("P&L", format="$%.0f"),
                "contribution": st.column_config.NumberColumn("Contribution", format="percent"),
                "alpha": st.column_config.NumberColumn("Excess return", format="percent"),
                "positions": st.column_config.NumberColumn("Positions", format="%d"),
            },
        )
        st.caption(
            "Excess return is the weighted position return minus the book return within "
            "each sector, so it measures selection, not a published sector index."
        )
    with st.container(border=True):
        st.subheader("Style drift")
        if context["rebalances"] < 2:
            st.info(
                "One completed monthly rebalance is stored. Style drift needs at least "
                "two rebalances; the current long and short exposures are shown above."
            )
        else:
            st.info("Style-drift history is not materialised in this warehouse yet.")


def _research_tab(context: dict) -> None:
    table = context["table"]
    analyses = context["analyses"]
    merged = table.merge(analyses[["ticker", "status", "recommendation"]], on="ticker", how="left")
    merged["status"] = merged["status"].fillna("Uncovered")
    columns = st.columns(3, border=True)
    for column, status in zip(columns, ("Draft", "Final", "Uncovered")):
        with column:
            subset = merged[merged["status"] == status]
            st.subheader(status)
            st.metric("Positions", len(subset), border=False)
            nav.selectable_table(
                subset[["ticker", "side", "sector"]].reset_index(drop=True),
                key=f"dashboard_research_{status.lower()}",
                origin=nav.DASHBOARD,
            )
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Coverage universe")
            coverage = (
                table.groupby("sector", as_index=False)
                .agg(
                    positions=("ticker", "count"),
                    gross_notional=("notional", "sum"),
                    f_score_complete=("f_score_complete", "mean"),
                )
                .sort_values("gross_notional", ascending=False)
            )
            st.dataframe(
                coverage,
                hide_index=True,
                width="stretch",
                column_config={
                    "gross_notional": st.column_config.NumberColumn(
                        "Gross notional", format="$%.0f"
                    ),
                    "f_score_complete": st.column_config.NumberColumn(
                        "F-Score coverage", format="percent"
                    ),
                },
            )
    with right:
        with st.container(border=True):
            st.subheader("Catalysts calendar")
            catalysts = context["catalysts"]
            if catalysts.empty:
                st.info("No ex-dividend dates in the next 90 days for the held names.")
            else:
                st.dataframe(
                    catalysts,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "ex_dividend_date": st.column_config.DateColumn("Ex-date"),
                        "amount": st.column_config.NumberColumn("Amount", format="%.4f"),
                    },
                )
    st.caption(
        "Pipeline status comes from the investment-analysis worksheet. A held name "
        "with no worksheet row is Uncovered, not unanalysed by the score."
    )


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def _reports(context: dict) -> dict[str, str]:
    path = context["path"]
    table = context["table"]
    risk = context["risk"]
    performance = context["performance"]
    recent = path.index[-1]
    top = table.nlargest(3, "pnl")
    bottom = table.nsmallest(3, "pnl")
    caveat = (
        "Simulated model portfolio; not an account. Borrow, financing, slippage "
        "and taxes are excluded."
    )
    morning = "\n".join(
        [
            f"# Morning note - {recent:%Y-%m-%d}",
            "",
            caveat,
            "",
            f"Model NAV **{_money(path['nav'].iloc[-1])}**, "
            f"latest day **{_pct(path['return'].iloc[-1])}**.",
            f"Since formation: **{_pct(performance.get('cumulative_return'))}**.",
            f"1-day 95% VaR: **{_pct(risk['historical_var'])}**.",
            "",
            "## Top contributors",
            _md_table(
                ["Ticker", "Side", "P&L"],
                [[row.ticker, row.side, _signed_money(row.pnl)] for row in top.itertuples()],
            ),
            "",
            "## Largest detractors",
            _md_table(
                ["Ticker", "Side", "P&L"],
                [[row.ticker, row.side, _signed_money(row.pnl)] for row in bottom.itertuples()],
            ),
        ]
    )
    performance_report = "\n".join(
        [
            f"# Performance report - {recent:%Y-%m-%d}",
            "",
            caveat,
            "",
            _md_table(
                ["Metric", "Value"],
                [
                    ["Cumulative return", _pct(performance.get("cumulative_return"))],
                    ["Annualised return", _pct(performance.get("annual_return"))],
                    ["Annualised volatility", _pct(performance.get("annual_volatility"))],
                    ["Sharpe", _ratio(performance.get("sharpe"))],
                    ["Sortino", _ratio(performance.get("sortino"))],
                    ["Max drawdown", _pct(performance.get("max_drawdown"))],
                    ["Calmar", _ratio(performance.get("calmar"))],
                    ["Omega", _ratio(performance.get("omega"))],
                ],
            ),
        ]
    )
    components = (
        risk["components"]
        .merge(table[["security_id", "ticker", "side"]], on="security_id", how="left")
        .nlargest(5, "component_var")
    )
    risk_report = "\n".join(
        [
            f"# Risk report - {recent:%Y-%m-%d}",
            "",
            caveat,
            "",
            f"Historical VaR 95: **{_pct(risk['historical_var'])}** "
            f"({_money(risk['historical_var_amount'])}).",
            f"Expected shortfall 95: **{_pct(risk['expected_shortfall'])}**.",
            f"Parametric VaR 95: **{_pct(risk['parametric_var'])}**.",
            "",
            "## Largest component VaR",
            _md_table(
                ["Ticker", "Side", "Component VaR"],
                [
                    [row.ticker, row.side, _pct(row.component_var)]
                    for row in components.itertuples()
                ],
            ),
        ]
    )
    analyses = context["analyses"]
    if analyses.empty:
        ic_memo = (
            f"# IC memo - {recent:%Y-%m-%d}\n\n"
            f"{caveat}\n\n"
            "No Final investment-analysis worksheet exists for the coverage universe. "
            "Open the worksheet from a covered name before drafting an IC memo."
        )
        research_note = (
            f"# Research note - {recent:%Y-%m-%d}\n\n"
            f"{caveat}\n\n"
            "No saved research note exists in the coverage universe."
        )
    else:
        final = analyses[analyses["status"] == "Final"]
        ic_memo = "\n".join(
            [
                f"# IC memo - {recent:%Y-%m-%d}",
                "",
                caveat,
                "",
                "## Final recommendations",
                _md_table(
                    ["Ticker", "Recommendation", "Confidence", "Risk"],
                    [
                        [
                            row.ticker,
                            "" if pd.isna(row.recommendation) else row.recommendation,
                            "" if pd.isna(row.confidence) else row.confidence,
                            "" if pd.isna(row.overall_risk_score) else int(row.overall_risk_score),
                        ]
                        for row in final.itertuples()
                    ],
                )
                if not final.empty
                else "No Final worksheet yet.",
            ]
        )
        latest = analyses.iloc[0]
        research_note = "\n".join(
            [
                f"# Research note - {recent:%Y-%m-%d}",
                "",
                caveat,
                "",
                f"Latest worksheet: **{latest['ticker']}**, status **{latest['status']}**.",
                "Recommendation: "
                + (
                    "not set"
                    if pd.isna(latest["recommendation"])
                    else str(latest["recommendation"])
                )
                + ".",
                "Confidence: "
                + ("not set" if pd.isna(latest["confidence"]) else str(latest["confidence"]))
                + ".",
            ]
        )
    return {
        "Morning note": morning,
        "Performance report": performance_report,
        "Risk report": risk_report,
        "IC memo": ic_memo,
        "Research note": research_note,
    }


def _reports_tab(context: dict) -> None:
    reports = _reports(context)
    choice = st.selectbox("Report", list(reports), key="dashboard_report_choice")
    report = reports[choice]
    st.download_button(
        "Download markdown",
        report.encode("utf-8"),
        file_name=f"{choice.lower().replace(' ', '-')}-{context['latest']:%Y-%m-%d}.md",
        mime="text/markdown",
        key="dashboard_report_download",
    )
    with st.container(border=True):
        st.markdown(report)
    st.caption(
        "Reports are deterministic drafts from the warehouse. No language model is "
        "called and no analyst approval is implied."
    )


def render() -> None:
    st.title(PAGE_TITLE)
    nav.seed_from_url()
    st.caption(
        "Simulated 15 long / 8 short model portfolio built from the ranked dividend "
        "universe. Research construct, not an account or investment advice."
    )
    st.warning("Simulated Portfolio — not an account or investment advice.", icon="⚠️")
    ui.refresh_button("dashboard_refresh")
    try:
        context = _load_context()
    except ValueError as error:
        st.warning(f"No model portfolio can be formed yet: {error}")
        return
    if context is None:
        st.warning("No published scores yet. Run feature engineering and scoring first.")
        return
    nav.render_flow_bar(nav.DASHBOARD)
    tabs = st.tabs(TAB_NAMES)
    with tabs[0]:
        _portfolio_tab(context)
    with tabs[1]:
        _performance_tab(context)
    with tabs[2]:
        _risk_tab(context)
    with tabs[3]:
        _position_book_tab(context)
    with tabs[4]:
        _factor_tab(context)
    with tabs[5]:
        _research_tab(context)
    with tabs[6]:
        _reports_tab(context)
