"""Security detail: price, dividends, score history and fundamentals for one ticker."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app import column_docs, nav, ui
from app.nav import SELECTED_KEY
from app.views.ticker_picker import render_ticker_picker
from src.crispdm.analysis import store

RANGES = {"1 year": 365, "3 years": 3 * 365, "5 years": 5 * 365, "All": None}

SCORE_PARTS = [
    "dividend_income_score",
    "sustainability_score",
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

# The V0068 point-in-time ratios, grouped the way an analyst reads them. Each entry is
# (model.features column, label, kind); the column resolves the stored COMMENT for the
# hover help, and kind selects the format in _metric_text. Margins, yields, capex
# intensity and FCF growth are fractions; the balance-sheet and pricing ratios are
# multiples; net debt is a dollar magnitude.
FINANCIAL_METRIC_GROUPS = {
    "Margins": [
        ("gross_margin", "Gross margin", "percent"),
        ("operating_margin", "Operating margin", "percent"),
        ("net_margin", "Net margin", "percent"),
        ("fcf_margin", "FCF margin", "percent"),
        ("ocf_margin", "OCF margin", "percent"),
    ],
    "Cash-flow quality": [
        ("cash_conversion", "Cash conversion", "multiple"),
        ("capex_intensity", "Capex intensity", "percent"),
        ("fcf_growth", "FCF growth", "percent"),
    ],
    "Balance sheet": [
        ("net_debt", "Net debt", "currency"),
        ("net_debt_to_ebitda", "Net debt/EBITDA", "multiple"),
        ("current_ratio", "Current ratio", "multiple"),
        ("debt_to_equity", "Debt/equity", "multiple"),
    ],
    "Valuation": [
        ("pe_ratio", "P/E", "multiple"),
        ("earnings_yield", "Earnings yield", "percent"),
        ("fcf_yield", "FCF yield", "percent"),
        ("price_to_book", "Price/book", "multiple"),
    ],
}
FINANCIAL_METRIC_COLUMNS = tuple(
    column for group in FINANCIAL_METRIC_GROUPS.values() for column, _label, _kind in group
)

# Fact labels carry a source column so the header and overview cells can explain themselves
# on hover. A label derived in SQL has no column of its own and falls back to a short note.
# Order is (label, value, relation, column, note); see _fact_cells.
IDENTITY_FACTS = [
    ("Type", "security_type"),
    ("CIK", "cik"),
    ("Last dividend paid", "dividend_last_paid"),
    ("SEC data status", "sec_data_status"),
]
# (label, relation, column). Liquidation and call terms come from the shared
# preferred.v_security_terms view, the same source the Screener reads, so the two
# pages cannot disagree; coupon and currency stay on reference.securities. The rate
# structure (coupon_type, fixed_period_end, floating_spread) is consensus-parsed from
# the security title and lives only on clean.ticker_profile, so it is read from there
# and shows N/A when the title carried no structure. The conversion date is the end of
# a fixed-rate period; US fixed-to-floating preferred titles rarely state one, so it is
# presented as N/A rather than derived. Yield is the latest engineered feature, and the
# ex-date is the selected dividend event from the same terms view.
TERMS_FACTS = [
    ("Coupon rate", "reference.securities", "coupon_rate"),
    ("Rate type", "clean.ticker_profile", "coupon_type"),
    ("Rate converts on", "clean.ticker_profile", "fixed_period_end"),
    ("Floating spread", "clean.ticker_profile", "floating_spread"),
    ("Liquidation preference", "preferred.v_security_terms", "liquidation_preference"),
    ("First call date", "preferred.v_security_terms", "first_call_date"),
    ("Call price", "preferred.v_security_terms", "call_price"),
    ("Yield", "model.features", "dividend_yield"),
    ("Last ex-date", "preferred.v_security_terms", "ex_date"),
    ("Currency", "reference.securities", "currency"),
]
# Dividend source policy (V0080/V0081): OPENBB rows are listing-level events through
# OpenBB and carry true ex-dates -- FMP first (as-declared amount, announced future
# ex-dates), Yahoo Finance as the per-symbol fallback, recorded per row in ``feed``.
# SEC XBRL filings are the last fallback, dated to the fiscal period end.
EX_DATE_PROVIDER = "OPENBB"
FEED_LABELS = {"fmp": "FMP (via OpenBB)", "yfinance": "Yahoo Finance (via OpenBB)"}
PROVIDER_LABELS = {"OPENBB": FEED_LABELS["yfinance"], "SEC_XBRL": "SEC XBRL filing"}
RECOMMENDED_SOURCE = "Recommended: listing ex-dates (FMP, Yahoo fallback)"
SEC_SOURCE = "SEC XBRL filings (fiscal period-ends)"
DIVIDEND_SOURCES = (RECOMMENDED_SOURCE, SEC_SOURCE, "All sources (comparison)")


def _source_label(provider, feed=None) -> str:
    """Display name of a dividend row's source: the OpenBB feed when known."""
    if provider == EX_DATE_PROVIDER and _present(feed):
        return FEED_LABELS.get(feed, f"{feed} (via OpenBB)")
    return PROVIDER_LABELS.get(provider, provider)


# The related-listings table is rebuilt from the hierarchy's children JSON, so its labels
# are not column names; a short note stands in for the stored definition.
RELATED_HELP = {
    "Symbol": "Ticker of this listing.",
    "Type": "Security type of this listing.",
    "Primary": "Whether this is the issuer's primary listing.",
    "Price": "Latest close price in the hierarchy snapshot.",
    "Yield": "Indicated dividend yield for this listing: the annual per-share rate divided by the latest close price.",
    "Ex-date": (
        "Most recent ex-dividend date. When the listing has a call date or a stored corporate "
        "action, those appear beneath it in red."
    ),
    "Dividend": "Most recent per-share dividend for this listing.",
    "Actions": (
        "Corporate-action announcements stored for this listing from the OpenBB profile feed: "
        "dividend, delisting, ticker change, name change and split. Counted per listing, not "
        "per issuer. A 0 means the feed stored none for that listing, not that none ever "
        "occurred."
    ),
}
OVERVIEW_FACTS = {
    "Sector": ("clean.company_profile", "sector", None),
    "Industry": ("clean.company_profile", "industry", None),
    "Employees": (
        "clean.company_profile",
        "employees",
        "Full-time headcount is preferred where reported.",
    ),
    "Headquarters": (None, None, "City, state and country from the company profile."),
    "Website": (None, None, "Company website, preferring the profile website over company_url."),
    "Market cap": ("clean.v_company_hierarchy", "market_cap", None),
    "Exchange": ("clean.company_profile", "exchange", None),
    "Issuer": ("reference.issuers", "issuer_name", None),
}
ISSUER_FACTS = {
    "Issuer": ("clean.v_company_hierarchy", "parent_name", None),
    "Primary listing": ("clean.v_company_hierarchy", "primary_symbol", None),
    "Issuer type": (None, None, "The primary listing's type, reused as the issuer's type."),
    "Sector / industry": (None, None, "Sector and industry of the issuer's primary listing."),
    "Employees": ("clean.v_company_hierarchy", "effective_employees", None),
    "Headquarters": (None, None, "City, state and country of the issuer's primary listing."),
    "Listings": ("clean.v_company_hierarchy", "child_count", None),
    "Market cap": ("clean.v_company_hierarchy", "market_cap", None),
}


def _fact_cells(pairs, columns: int) -> None:
    """Lay out labelled facts in a grid, each label carrying its column definition on hover."""
    cells = st.columns(columns)
    for index, (label, value, relation, column, note) in enumerate(pairs):
        cells[index % columns].markdown(
            f"**{label}**  \n{value}",
            help=column_docs.help_text(relation=relation, column=column, note=note),
        )


def _fmt(name: str, value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.2%}" if name in PERCENT_FEATURES else f"{value:,.2f}"


def _metric_text(kind: str, value) -> str:
    """Render one V0068 ratio. A blank denominator leaves the column NULL, shown as N/A."""
    if value is None or pd.isna(value):
        return "N/A"
    value = float(value)
    if kind == "percent":
        return f"{value:.1%}"
    if kind == "currency":
        return ("-" if value < 0 else "") + _fmt_market_cap(abs(value))
    return f"{value:,.2f}x"


def _text(value) -> str:
    """Display text for a possibly missing value (None, NaN and NaT all read as N/A)."""
    return "N/A" if value is None or pd.isna(value) else str(value)


def _coupon_text(value) -> str:
    """Preferred coupon / stated dividend rate as a percent-per-annum figure."""
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:,.3f}%"


def _liquidation_text(value) -> str:
    """Preferred liquidation preference as a dollar figure."""
    if value is None or pd.isna(value):
        return "N/A"
    return f"${value:,.2f}"


def _spread_text(value) -> str:
    """Floating-rate spread, a percentage added to the reference rate."""
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:,.3f}%"


def _yield_text(value) -> str:
    """Annualized dividend divided by price, as a decimal fraction."""
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.2%}"


def _present(value) -> bool:
    """True when a value is worth rendering (not None, NaN, NaT or blank text)."""
    if value is None or pd.isna(value):
        return False
    return bool(str(value).strip())


def _fmt_count(value) -> str:
    return f"{value:,.0f}" if _present(value) else ""


def _fmt_market_cap(value) -> str:
    """Compact dollar magnitude; raw cap is noisy but the scale is the signal."""
    if not _present(value):
        return ""
    value = float(value)
    if value >= 1e12:
        return f"${value / 1e12:,.2f}T"
    if value >= 1e9:
        return f"${value / 1e9:,.2f}B"
    if value >= 1e6:
        return f"${value / 1e6:,.2f}M"
    return f"${value:,.0f}"


def _hq(ov) -> str:
    parts = [ov.get("city"), ov.get("state"), ov.get("country")]
    return ", ".join(str(p).strip() for p in parts if _present(p))


def _link(url) -> str:
    if not _present(url):
        return ""
    url = str(url).strip()
    host = url.split("://", 1)[-1].rstrip("/")
    return f"[{host}]({url})"


def profile(ticker: str) -> pd.DataFrame:
    """One active security's identity, terms and latest yield for the header.

    The rate structure comes from ``clean.ticker_profile`` and the yield from the
    latest ``model.features`` row, both through a ``LATERAL ... LIMIT 1``: neither
    relation is guaranteed unique on ``security_id`` (the clean profile is keyed on
    (cik, ticker), features are one row per as-of date), so a plain join would fan
    the header out to several rows.
    """
    return ui.query(
        """
        SELECT CAST(s.security_id AS text) AS security_id, s.ticker, s.security_name,
               s.security_type, s.cik, s.exchange_id, s.currency, s.coupon_rate,
               v.liquidation_preference, v.liquidation_source,
               v.first_call_date, v.call_price, v.call_source,
               v.ex_date, v.ex_date_is_period_end,
               tp.coupon_type, tp.fixed_period_end, tp.floating_spread,
               f.dividend_yield,
               s.dividend_last_paid, s.sec_data_status
        FROM reference.securities s
        LEFT JOIN preferred.v_security_terms v ON v.security_id = s.security_id
        LEFT JOIN LATERAL (
            SELECT p.coupon_type, p.fixed_period_end, p.floating_spread
            FROM clean.ticker_profile p
            WHERE p.security_id = s.security_id
            ORDER BY p.cleaned_at DESC NULLS LAST
            LIMIT 1
        ) tp ON TRUE
        LEFT JOIN LATERAL (
            SELECT x.dividend_yield
            FROM model.features x
            WHERE x.security_id = s.security_id
            ORDER BY x.as_of_date DESC
            LIMIT 1
        ) f ON TRUE
        WHERE s.ticker = :t AND s.active ORDER BY s.security_id LIMIT 1
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


def dividend_dates(security_id: str) -> pd.DataFrame:
    """True ex-dividend dates for the price chart.

    Only OPENBB (FMP or Yahoo Finance) rows carry the listing's ex-date; SEC XBRL rows
    are fiscal period-ends, so marking them on the price series would place a drop on
    a day nothing traded ex. The amount is split-adjusted, like the price series.
    """
    return ui.query(
        """
        SELECT ex_dividend_date, COALESCE(adjusted_amount, amount) AS amount
        FROM raw.dividend_data
        WHERE security_id = CAST(:sid AS uuid) AND ex_dividend_date IS NOT NULL
          AND provider = :provider
        ORDER BY ex_dividend_date
        """,
        {"sid": security_id, "provider": EX_DATE_PROVIDER},
    )


def overview(security_id: str) -> pd.Series | None:
    """Company overview for the header: short name, description and issuer facts.

    The company profile is joined through a LATERAL ... LIMIT 1 because
    ``clean.company_profile`` is unique on (symbol, parent_name), so one security
    can match more than one company record. A plain join would fan the header out.
    The business summary is not flattened into a clean column; it is read from the
    OpenBB profile payload.
    """
    df = ui.query(
        """
        SELECT COALESCE(NULLIF(BTRIM(cpx.short_name), ''),
                        NULLIF(BTRIM(cpx.display_name), ''),
                        NULLIF(BTRIM(cpx.long_name), ''),
                        i.issuer_name, s.security_name) AS short_name,
               i.issuer_name, cpx.sector, cpx.industry,
               COALESCE(cpx.full_time_employees, cpx.employees) AS employees,
               cpx.city, cpx.state, cpx.country,
               COALESCE(cpx.website, cpx.company_url) AS website,
               cpx.exchange AS profile_exchange,
               NULLIF(BTRIM(tp.raw_payload->'openbb'->>'long_description'), '') AS description,
               v.dividend_amount AS announced_amount, v.ex_date AS announced_ex_date,
               v.ex_date_is_period_end AS announced_is_period_end,
               v.dividend_provider AS announced_provider,
               v.dividend_feed AS announced_feed,
               s.currency AS announced_currency
        FROM reference.securities s
        LEFT JOIN reference.issuers i ON i.issuer_id = s.issuer_id
        LEFT JOIN raw.ticker_profile tp ON tp.security_id = s.security_id
        LEFT JOIN LATERAL (
            SELECT c.* FROM clean.company_profile c
            WHERE c.reference_security_id = s.security_id
            ORDER BY c.source_retrieved_at DESC NULLS LAST, c.profile_id
            LIMIT 1
        ) cpx ON TRUE
        LEFT JOIN preferred.v_security_terms v ON v.security_id = s.security_id
        WHERE s.security_id = CAST(:sid AS uuid)
        LIMIT 1
        """,
        {"sid": security_id},
    )
    return None if df.empty else df.iloc[0]


def price_section(security_id: str) -> None:
    st.subheader("Price")
    controls, toggle = st.columns([3, 1])
    label = controls.radio("Range", list(RANGES), index=1, horizontal=True, key="detail_range")
    show_ex = toggle.checkbox("Show ex-dates", key="detail_show_ex")
    df = prices(security_id, RANGES[label])
    if df.empty:
        st.caption("No market data stored for this security.")
        return
    df["observation_date"] = pd.to_datetime(df["observation_date"])
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
    if show_ex:
        _add_ex_dividend_markers(fig, df, security_id)
    fig.update_layout(margin={"t": 10}, yaxis_title="Price", xaxis_title=None)
    st.plotly_chart(fig, width="stretch")
    low, high = df.close.min(), df.close.max()
    st.caption(
        f"{len(df):,} trading days, {df.observation_date.min().date()} to "
        f"{df.observation_date.max().date()}. Close range {low:,.2f} to {high:,.2f}."
    )


def _add_ex_dividend_markers(fig: go.Figure, df: pd.DataFrame, security_id: str) -> None:
    """Overlay ex-dividend dates on the close series for the visible range.

    The ex-date is snapped to the nearest trading day because the market-data
    calendar and the dividend feed do not always share a date.
    """
    divs = dividend_dates(security_id)
    if divs.empty:
        st.caption(
            "No true ex-dividend dates stored for this security (SEC filings carry "
            "fiscal period-ends only)."
        )
        return
    divs = divs.assign(ex_dividend_date=pd.to_datetime(divs["ex_dividend_date"]))
    divs = divs[
        (divs.ex_dividend_date >= df.observation_date.min())
        & (divs.ex_dividend_date <= df.observation_date.max())
    ]
    if divs.empty:
        st.caption("No ex-dividend dates fall inside the selected range.")
        return
    merged = pd.merge_asof(
        divs.sort_values("ex_dividend_date"),
        df[["observation_date", "close"]].sort_values("observation_date"),
        left_on="ex_dividend_date",
        right_on="observation_date",
        direction="nearest",
    )
    fig.add_trace(
        go.Scatter(
            x=merged.ex_dividend_date,
            y=merged.close,
            mode="markers",
            name="Ex-dividend",
            marker={"symbol": "triangle-down", "size": 10, "color": "crimson"},
            customdata=merged.amount,
            hovertemplate="Ex-date %{x|%Y-%m-%d}<br>Per share %{customdata:.4f}<extra></extra>",
        )
    )


def dividend_section(security_id: str) -> None:
    st.subheader("Dividends")
    df = ui.query(
        """
        SELECT ex_dividend_date, amount, adjusted_amount, frequency, currency, provider,
               feed, amount_feed, concept
        FROM raw.dividend_data WHERE security_id = CAST(:sid AS uuid)
        ORDER BY ex_dividend_date DESC
        """,
        {"sid": security_id},
    )
    if df.empty:
        st.caption("No dividend events stored for this security.")
        return
    source = st.selectbox(
        "Source",
        list(DIVIDEND_SOURCES),
        key="detail_dividend_provider",
        help=(
            "The recommended source is the listing's own dividend events through OpenBB: "
            "FMP (as-declared amounts that match SEC filings, a split-adjusted amount, "
            "and announced upcoming ex-dates), with Yahoo Finance where FMP has none. "
            "SEC XBRL filings report declared per-share amounts dated to the fiscal "
            "period end and arrive a filing cycle later."
        ),
    )
    recommended = df[df.provider == EX_DATE_PROVIDER]
    if source == RECOMMENDED_SOURCE:
        if recommended.empty:
            df = df[df.provider != EX_DATE_PROVIDER]
            st.caption(
                "FMP and Yahoo Finance have no dividend events for this security; showing "
                "the SEC XBRL filing fallback."
            )
        else:
            df = recommended
    elif source == SEC_SOURCE:
        df = df[df.provider != EX_DATE_PROVIDER]
    if df.empty:
        st.caption("No dividend events from the selected source.")
        return
    if (df.provider != EX_DATE_PROVIDER).any():
        st.caption(
            "SEC XBRL dates are fiscal period-ends (not ex-dates) with per-share declared "
            "amounts; CashPaid rows are annual aggregates and are excluded from the chart. "
            "FMP and Yahoo Finance dates are true ex-dates."
        )
    upcoming = pd.to_datetime(df.ex_dividend_date) > pd.Timestamp.today().normalize()
    if upcoming.any():
        st.caption(f"Includes {int(upcoming.sum())} announced upcoming ex-date(s) not yet reached.")
    if df.adjusted_amount.notna().any():
        st.caption(
            "amount is the dividend as declared; adjusted_amount restates it per "
            "current share after splits. The chart plots the split-adjusted figure."
        )
    if "amount_feed" not in df:
        df = df.assign(amount_feed=df.feed)
    reconciled = (
        (df.provider == EX_DATE_PROVIDER) & df.amount_feed.notna() & (df.amount_feed != df.feed)
    )
    if reconciled.any():
        st.caption(
            f"{int(reconciled.sum())} amount(s) come from "
            f"{FEED_LABELS.get('yfinance', 'Yahoo Finance')} rather than FMP: the two "
            "disagreed and Polygon.io confirmed Yahoo's figure (see amount_feed)."
        )
    df = df.assign(provider=[_source_label(p, f) for p, f in zip(df.provider, df.feed)])
    plot = df[df.amount.notna() & (df.concept != "CommonStockDividendsPerShareCashPaid")]
    # Yahoo rows are already split-adjusted and FMP's adjusted_amount is restated by
    # the same split factors, so one series stays continuous across a feed switch or
    # a split. A series whose adjusted_amount is entirely NULL arrives as object dtype;
    # coerce before fillna so it stays float and pandas does not downcast object arrays.
    per_share = pd.to_numeric(plot.adjusted_amount, errors="coerce").fillna(plot.amount)
    plot = plot.assign(per_share=per_share)
    if not plot.empty:
        st.plotly_chart(
            px.bar(
                plot,
                x="ex_dividend_date",
                y="per_share",
                color="provider",
                barmode="group",
                labels={"ex_dividend_date": "Ex-dividend date", "per_share": "Per share"},
            ),
            width="stretch",
        )
    shown = df.drop(columns=["concept", "feed"])
    if reconciled.any():
        shown = shown.assign(
            amount_feed=[
                FEED_LABELS.get(f, f) if r else "" for f, r in zip(shown.amount_feed, reconciled)
            ]
        )
    else:
        shown = shown.drop(columns=["amount_feed"])
    if shown.adjusted_amount.isna().all():
        shown = shown.drop(columns=["adjusted_amount"])
    st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        column_config=column_docs.config_for("raw.dividend_data", shown.columns),
    )


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
    st.dataframe(
        df.sort_values("as_of_date", ascending=False),
        hide_index=True,
        width="stretch",
        column_config=column_docs.config_for("model.scores", df.columns),
    )


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
        cells[index % 4].metric(
            FEATURE_LABELS[name],
            _fmt(name, row[name]),
            help=column_docs.help_text(relation="model.features", column=name),
        )


def financials_section(security_id: str) -> None:
    st.subheader("Financial metrics")
    df = ui.query(
        f"SELECT as_of_date, {', '.join(FINANCIAL_METRIC_COLUMNS)} FROM model.features "
        "WHERE security_id = CAST(:sid AS uuid) ORDER BY as_of_date DESC LIMIT 1",
        {"sid": security_id},
    )
    if df.empty:
        st.caption("No engineered financial metrics for this security.")
        return
    row = df.iloc[0]
    st.caption(
        f"Point-in-time ratios as of {row.as_of_date}, each derived from the vintaged "
        "reported financials keyed by filing date -- never from the current provider "
        "snapshot. A blank means the denominator was absent or non-positive, not zero."
    )
    for group, metrics in FINANCIAL_METRIC_GROUPS.items():
        st.markdown(f"**{group}**")
        cells = st.columns(len(metrics))
        for cell, (column, label, kind) in zip(cells, metrics):
            cell.metric(
                label,
                _metric_text(kind, row[column]),
                help=column_docs.help_text(relation="model.features", column=column),
            )
        st.write("")


def fundamentals_section(security_id: str) -> None:
    st.subheader("Fundamentals")
    df = ui.query(
        """
        SELECT period_end, fiscal_year, fiscal_period, revenue, cost_of_revenue,
               gross_profit, operating_income, net_income, free_cash_flow, cash, debt,
               equity, filed, source
        FROM fundamentals.periodic_financials WHERE security_id = CAST(:sid AS uuid)
          AND period_end <= CURRENT_DATE
        ORDER BY period_end DESC, filed DESC NULLS LAST LIMIT 12
        """,
        {"sid": security_id},
    )
    if df.empty:
        st.caption("No reported fundamentals for this security.")
        return
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config=column_docs.config_for("fundamentals.periodic_financials", df.columns),
    )


FMP_STATEMENT_LABELS = {
    "income": (
        ("revenue", "Revenue"),
        ("gross_profit", "Gross profit"),
        ("total_operating_income", "Operating income"),
        ("bottom_line_net_income", "Net income"),
        ("diluted_earnings_per_share", "Diluted EPS"),
    ),
    "balance": (
        ("cash_and_cash_equivalents", "Cash"),
        ("total_current_assets", "Current assets"),
        ("total_assets", "Total assets"),
        ("total_current_liabilities", "Current liabilities"),
        ("total_liabilities", "Total liabilities"),
        ("total_debt", "Total debt"),
        ("total_equity_non_controlling_interests", "Total equity"),
    ),
    "cash": (
        ("operating_cash_flow", "Operating cash flow"),
        ("capital_expenditure", "Capex"),
        ("free_cash_flow", "Free cash flow"),
        ("common_dividends_paid", "Common dividends"),
        ("repurchase_of_common_equity", "Buybacks"),
    ),
}


def _fmp_metric_text(value) -> str:
    """A statement line item: cents for per-share figures, compact dollars otherwise."""
    if not _present(value):
        return "N/A"
    value = float(value)
    if abs(value) < 1000:
        return f"${value:,.2f}"
    return _fmt_market_cap(value)


def fmp_section(security_id: str) -> None:
    """FMP supporting fundamentals: latest statement per type, the DCF estimate, filings.

    Read from raw.fmp_* (gathered by scripts.populate_fmp_fundamentals). Supporting
    data for the worksheet, never a model input, so a blank here does not affect scoring.
    """
    st.subheader("FMP fundamentals")
    df = ui.query(
        "SELECT statement, period_end, fiscal_period, filing_date, metrics "
        "FROM raw.fmp_statements WHERE security_id = CAST(:sid AS uuid) "
        "ORDER BY statement, period_end DESC, filing_date DESC",
        {"sid": security_id},
    )
    if df.empty:
        st.caption("No FMP statements stored for this security.")
    else:
        latest = df.drop_duplicates(subset=["statement"], keep="first")
        for _, row in latest.iterrows():
            st.markdown(
                f"**{str(row['statement']).title()}** — {row['period_end']} "
                f"({row['fiscal_period']})"
            )
            metrics = row["metrics"] or {}
            labels = FMP_STATEMENT_LABELS.get(row["statement"], ())
            cells = st.columns(max(1, len(labels)))
            for cell, (key, label) in zip(cells, labels):
                cell.metric(label, _fmp_metric_text(metrics.get(key)))
            st.write("")
    dcf = ui.query(
        "SELECT as_of_date, dcf, stock_price FROM raw.fmp_dcf "
        "WHERE security_id = CAST(:sid AS uuid) ORDER BY as_of_date DESC LIMIT 1",
        {"sid": security_id},
    )
    if not dcf.empty:
        row = dcf.iloc[0]
        margin = None
        if _present(row["dcf"]) and _present(row["stock_price"]) and float(row["stock_price"]):
            margin = float(row["dcf"]) / float(row["stock_price"]) - 1
        st.markdown("**DCF (FMP)**")
        left, right = st.columns(2)
        left.metric("Intrinsic value", _fmp_metric_text(row["dcf"]))
        right.metric("Margin of safety", "N/A" if margin is None else f"{margin:.1%}")
    filings = ui.query(
        "SELECT count(*) AS n, max(filing_date) AS latest FROM raw.fmp_filings "
        "WHERE security_id = CAST(:sid AS uuid)",
        {"sid": security_id},
    )
    if not filings.empty and filings.iloc[0]["n"]:
        st.caption(
            f"FMP filings: {int(filings.iloc[0]['n'])} stored, latest {filings.iloc[0]['latest']}"
        )


def recommendation_section(security_id: str) -> None:
    """The saved calls for this security, one row per change, newest first.

    Read from the append-only worksheet revisions (V0088) so the track record cannot drift
    from what was actually saved; the query collapses re-saves that kept the same call.
    """
    st.subheader("Recommendation history")
    with ui.engine.connect() as conn:
        rows = store.recommendation_history(conn, security_id)
    if not rows:
        st.caption("No recommendations recorded for this security yet.")
        return
    df = pd.DataFrame(rows)
    st.caption(
        "The sequence of saved calls for this security, newest first, one row per change. "
        "A worksheet re-saved without changing its call is collapsed, and a call withdrawn "
        "to an empty cell is not shown. Derived from the append-only revision history "
        "(V0088), so it matches what was saved."
    )
    display = pd.DataFrame(
        {
            "Date": [ui.fmt_ts(row["saved_at"]) for row in rows],
            "Call": df["recommendation"],
            "From": df["previous"].where(df["previous"].notna(), "—"),
            "Status": df["status"].str.title(),
            "By": df["saved_by"],
        }
    )
    st.dataframe(display, hide_index=True, width="stretch")


def _announced_dividend(ov) -> None:
    """The most recent announced cash dividend and its ex-date, under the ticker."""
    if ov is None or not _present(ov.get("announced_amount")):
        return
    amount = f"{float(ov['announced_amount']):,.4f}"
    currency = f" {ov['announced_currency']}" if _present(ov.get("announced_currency")) else ""
    line = f"Announced cash dividend **{amount}{currency}**"
    if _present(ov.get("announced_ex_date")):
        label = (
            "Period end (SEC filing)" if _is_true(ov.get("announced_is_period_end")) else "Ex-date"
        )
        line += f"  \n{label} **{ov['announced_ex_date']}**"
    provider = ov.get("announced_provider")
    if _present(provider):
        line += f"  \nSource: {_source_label(provider, ov.get('announced_feed'))}"
    st.markdown(line)


def _is_true(value) -> bool:
    return _present(value) and bool(value)


def _ex_date_text(value, is_period_end) -> str:
    """The selected dividend date, flagged when it is an SEC fiscal period end."""
    text_value = _text(value)
    if text_value != "N/A" and _is_true(is_period_end):
        return f"{text_value} (SEC period end)"
    return text_value


def _company_overview(ov) -> None:
    """Issuer description and facts, rendered to the right of the ticker block."""
    st.subheader("Company overview")
    if ov is None:
        st.caption("No company profile stored for this security.")
        return
    if _present(ov.get("description")):
        st.write(ov["description"])
    facts = [
        ("Sector", ov.get("sector")),
        ("Industry", ov.get("industry")),
        ("Employees", _fmt_count(ov.get("employees"))),
        ("Headquarters", _hq(ov)),
        ("Website", _link(ov.get("website"))),
        ("Market cap", _fmt_market_cap(ov.get("market_cap"))),
        ("Exchange", ov.get("profile_exchange")),
        ("Issuer", ov.get("issuer_name")),
    ]
    shown = []
    for label, value in facts:
        if not _present(value):
            continue
        relation, column, note = OVERVIEW_FACTS.get(label, (None, None, None))
        shown.append((label, _text(value), relation, column, note))
    if not shown:
        return
    _fact_cells(shown, 2)


def _issuer_facts(cik) -> pd.DataFrame:
    """The issuer row of clean.v_company_hierarchy for one CIK, or an empty frame."""
    return ui.query(
        """
        SELECT parent_name, primary_symbol, security_type, sector, industry,
               effective_employees, city, state, country, market_cap,
               child_count, varying_parent_attributes
        FROM clean.v_company_hierarchy WHERE cik = :cik
        """,
        {"cik": cik},
    )


def related_listings(cik) -> pd.DataFrame:
    """Every listing sharing the issuer's CIK, one row per related security.

    Read from clean.v_company_hierarchy so the primary-listing rule, the
    per-listing security_type and the nesting stay in one place instead of
    being re-derived here. The call date and the corporate-action text are
    looked up per listing: the call date from the preferred terms (falling back
    to reference.securities.call_date), the actions from the children JSON, so a
    reader can see a redemption date or a delisting against the ex-date.
    """
    return ui.query(
        """
        SELECT j->>'symbol' AS symbol,
               j->>'security_type' AS security_type,
               (j->>'is_primary_listing')::boolean AS is_primary_listing,
               (j->>'current_price')::numeric AS current_price,
               (j->>'dividend_rate')::numeric
                   / NULLIF((j->>'current_price')::numeric, 0) AS dividend_yield,
               (j->>'dividend_rate')::numeric AS dividend_rate,
               (j->>'ex_dividend_date')::date AS ex_dividend_date,
               (j->>'market_cap')::numeric AS market_cap,
               (j->>'corporate_action_count')::int AS corporate_action_count,
               sd.call_date,
               (SELECT string_agg(
                           COALESCE(a->>'header', a->>'event_type')
                           || CASE WHEN a->>'effective_date' IS NOT NULL
                                   THEN ' ' || (a->>'effective_date') ELSE '' END,
                           '; ' ORDER BY a->>'effective_date')
                FROM jsonb_array_elements(COALESCE(j->'corporate_actions', '[]'::jsonb)) AS a)
                   AS action_text
        FROM clean.v_company_hierarchy h
        CROSS JOIN LATERAL jsonb_array_elements(h.children) AS j
        LEFT JOIN LATERAL (
            SELECT v.first_call_date AS call_date
            FROM reference.securities s
            JOIN preferred.v_security_terms v ON v.security_id = s.security_id
            WHERE s.ticker = j->>'symbol'
            ORDER BY s.security_id
            LIMIT 1
        ) sd ON TRUE
        WHERE h.cik = :cik
        ORDER BY is_primary_listing DESC, symbol
        """,
        {"cik": cik},
    )


def _sibling_buttons(rows: pd.DataFrame, current_symbol: str) -> None:
    """Buttons that jump to a sibling listing, chunked so they wrap."""
    others = [s for s in rows.symbol if s != current_symbol]
    if not others:
        return
    per_row = 10
    for start in range(0, len(others), per_row):
        cells = st.columns(per_row)
        for cell, symbol in zip(cells, others[start : start + per_row]):
            if cell.button(symbol, key=f"sibling_{symbol}"):
                st.session_state[SELECTED_KEY] = symbol
                st.rerun()


def issuer_section(cik, current_symbol) -> None:
    """Issuer facts and the related listings that share this CIK."""
    st.subheader("Issuer & related listings")
    facts = _issuer_facts(cik)
    if facts.empty:
        st.caption("No company profile stored for this security.")
        return
    h = facts.iloc[0]
    issuer_facts = [
        ("Issuer", h.parent_name),
        ("Primary listing", h.primary_symbol),
        ("Issuer type", h.security_type),
        ("Sector / industry", _text(h.sector) + " / " + _text(h.industry)),
        ("Employees", _fmt_count(h.effective_employees)),
        ("Headquarters", _hq(h)),
        ("Listings", _fmt_count(h.child_count)),
        ("Market cap", _fmt_market_cap(h.market_cap)),
    ]
    shown = []
    for label, value in issuer_facts:
        if not _present(value):
            continue
        relation, column, note = ISSUER_FACTS.get(label, (None, None, None))
        shown.append((label, _text(value), relation, column, note))
    _fact_cells(shown, 2)

    rows = related_listings(cik)
    if rows.empty:
        st.caption("No related listings.")
        return
    _sibling_buttons(rows, current_symbol)
    display = rows.copy()
    display["Primary"] = display.is_primary_listing.fillna(False).map(
        lambda b: "primary" if b else ""
    )
    display["Price"] = display.current_price.map(lambda v: f"{v:,.2f}" if _present(v) else "")
    display["Yield"] = display.dividend_yield.map(lambda v: f"{v:.2%}" if _present(v) else "")
    display["Dividend"] = display.dividend_rate.map(lambda v: f"{v:,.4f}" if _present(v) else "")
    display["Actions"] = display.corporate_action_count.map(lambda v: f"{v}" if _present(v) else "")

    # Under the ex-date, stack the call date and any corporate action (event name + date).
    # A call date warns the series may be redeemed; a corporate action is an announcement
    # such as a delisting. Either one tints the whole Ex-date cell red, because a Streamlit
    # table can colour a cell but not a single line inside it.
    flagged = rows.call_date.notna() | rows.action_text.notna()

    def _ex_date_cell(row) -> str:
        lines = []
        if _present(row.ex_dividend_date):
            lines.append(pd.Timestamp(row.ex_dividend_date).strftime("%Y-%m-%d"))
        if _present(row.call_date):
            lines.append(f"Call {pd.Timestamp(row.call_date):%Y-%m-%d}")
        if _present(row.action_text):
            lines.append(str(row.action_text))
        return "\n".join(lines)

    display["Ex-date"] = rows.apply(_ex_date_cell, axis=1)
    final = display[
        ["symbol", "security_type", "Primary", "Price", "Yield", "Ex-date", "Dividend", "Actions"]
    ].rename(columns={"symbol": "Symbol", "security_type": "Type"})

    def red_flag(frame: pd.DataFrame):
        def row_colour(row):
            colour = "color: red" if flagged.loc[row.name] else ""
            return [colour if column == "Ex-date" else "" for column in frame.columns]

        return frame.style.apply(row_colour, axis=1)

    st.dataframe(
        red_flag(final),
        hide_index=True,
        width="stretch",
        column_config={
            column: st.column_config.Column(help=text)
            for column, text in RELATED_HELP.items()
            if column in final.columns
        },
    )
    with_actions = rows[rows.corporate_action_count.fillna(0) > 0]
    example = (
        f" Here {with_actions.iloc[0].symbol} shows {int(with_actions.iloc[0].corporate_action_count)}."
        if not with_actions.empty
        else " Most listings show 0."
    )
    st.caption(
        "Actions counts stored corporate-action announcements per listing -- dividends, "
        "delistings, ticker or name changes and splits -- not per issuer. A 0 means the feed "
        "stored none for that listing, not that none ever happened." + example
    )


def render() -> None:
    st.title("Security detail")
    ticker = render_ticker_picker("security")
    if ticker is None:
        return
    nav.render_flow_bar(nav.SECURITY, ticker)
    _, action = st.columns([4, 1])
    if action.button(
        "Analyze",
        key="security_analyze",
        help="Open the investment-analysis worksheet for this ticker",
        type="primary",
    ):
        nav.open_page(nav.ANALYSIS, ticker, origin=nav.SECURITY)

    found = profile(ticker)
    if found.empty:
        st.error(f"{ticker} is not an active security.")
        return
    info = found.iloc[0]
    ov = overview(info.security_id)
    st.markdown(f"### {info.ticker}")
    st.text(_text(info.security_name), width="stretch", wrap=True)
    left, right = st.columns([1, 2])
    with left:
        _announced_dividend(ov)
    with right:
        _company_overview(ov)
    # Text facts, not st.metric: a metric truncates a long value such as "common_stock".
    _fact_cells(
        [
            (label, _text(info[column]), "reference.securities", column, None)
            for label, column in IDENTITY_FACTS
        ],
        4,
    )
    term_formatters = {
        "coupon_rate": _coupon_text,
        "liquidation_preference": _liquidation_text,
        "call_price": _liquidation_text,
        "floating_spread": _spread_text,
        "dividend_yield": _yield_text,
        "ex_date": lambda value: _ex_date_text(value, info.get("ex_date_is_period_end")),
    }
    _fact_cells(
        [
            (
                label,
                term_formatters.get(column, _text)(info[column]),
                relation,
                column,
                None,
            )
            for label, relation, column in TERMS_FACTS
        ],
        4,
    )

    issuer_section(info.cik, info.ticker)

    # Lazy sections: a segmented control reruns the page on change, so only the
    # selected section queries and renders. st.tabs switches client-side with no
    # rerun, which forces every section to render eagerly on each page load.
    sid = info.security_id
    sections = {
        "Price": price_section,
        "Dividends": dividend_section,
        "Scores": score_section,
        "Features": feature_section,
        "Financials": financials_section,
        "Fundamentals": fundamentals_section,
        "Recommendations": recommendation_section,
    }
    selected = st.segmented_control(
        "Section",
        list(sections),
        default="Price",
        key="security_active_section",
        width="stretch",
    )
    if selected is not None:
        sections[selected](sid)
