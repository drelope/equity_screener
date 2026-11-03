"""Model long/short portfolio analytics for the analyst dashboard.

The repository has no holdings table and no execution path. The portfolio is
therefore a deterministic model built from the ranked dividend universe: the
top ``LONG_COUNT`` names by composite score are held long and the bottom
``SHORT_COUNT`` are held short, equal-weighted inside each sleeve. It is a
research construct, not an account, and the dashboard labels it as simulated.

Two choices keep the numbers honest:

* Monthly rebalancing uses the last score date of a **completed** month. A
  partial month has not finished, so rebalancing on its latest score date would
  make the portfolio depend on when the page happened to be opened.
* Returns are total returns. A dividend is credited on the first price row on or
  after its ex-date, matching ``src.crispdm.returns`` and ``features.py``, and a
  short position pays that dividend through its negative weight. Borrow,
  financing, slippage and taxes are excluded because the warehouse has no data
  for them.

Every analytics function takes frames rather than querying inside the
calculation. The ``load_*`` helpers at the bottom are the only database-aware
code, so the selection, return, risk and attribution rules are unit-testable
without Postgres.
"""

from __future__ import annotations

from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from ..math_engine import RiskParityCalculator
from .db import read_df

LONG_COUNT = 15
SHORT_COUNT = 8
LONG_GROSS = 1.0
SHORT_GROSS = 0.5
BASE_NAV = 100_000_000.0
MIN_COVERAGE = 0.50
MIN_PRICE = 1.0
TRADING_DAYS = 252
MAX_SINGLE_PAYMENT_RATIO = 1.0

FACTOR_LABELS = {
    "dividend_income_score": "Income",
    "sustainability_score": "Sustainability",
    "appreciation_score": "Appreciation",
    "risk_score": "Low volatility",
    "valuation_score": "Valuation",
}

UNIVERSE_SQL = """
SELECT sc.security_id::text AS security_id,
       sec.ticker, sec.security_name, sec.security_type,
       COALESCE(cp.sector, 'Unclassified') AS sector,
       sc.as_of_date,
       sc.dividend_income_score::float8 AS dividend_income_score,
       sc.sustainability_score::float8 AS sustainability_score,
       sc.appreciation_score::float8 AS appreciation_score,
       sc.risk_score::float8 AS risk_score,
       sc.valuation_score::float8 AS valuation_score,
       sc.composite_score::float8 AS composite_score,
       sc.score_coverage::float8 AS score_coverage
FROM model.scores sc
JOIN reference.securities sec ON sec.security_id = sc.security_id
LEFT JOIN LATERAL (
    SELECT cp.sector
    FROM clean.company_profile cp
    WHERE cp.reference_security_id = sc.security_id
    ORDER BY cp.loaded_at DESC NULLS LAST, cp.profile_id DESC
    LIMIT 1
) cp ON TRUE
JOIN LATERAL (
    -- Price on the formation date. Sub-$1 names in the warehouse carry corrupt
    -- closes (for example 0.0006 followed by 1.50), so they cannot be held.
    SELECT md.close::float8 AS close
    FROM raw.market_data md
    WHERE md.security_id = sc.security_id
      AND md.observation_date = sc.as_of_date
    LIMIT 1
) px ON px.close >= :min_price AND px.close <= :max_price
WHERE sc.as_of_date = COALESCE(CAST(:as_of AS date), (SELECT max(as_of_date) FROM model.scores))
  AND sc.composite_score IS NOT NULL
  AND sc.score_coverage >= :min_coverage
  -- The book holds common stock only. Preferreds, bonds, derivatives, futures and
  -- the ambiguous 'equity' and 'other' types are excluded: the dividend score is
  -- not a valid ranking for them.
  AND sec.security_type = 'common_stock'
ORDER BY sc.composite_score DESC
"""

SCORE_DATES_SQL = """
SELECT DISTINCT as_of_date
FROM model.scores
WHERE composite_score IS NOT NULL
ORDER BY as_of_date
"""

RISK_FREE_SERIES = "UST_3M"

RISK_FREE_SQL = """
SELECT observation_date, value::float8 AS value
FROM raw.macro_series
WHERE series_id = :series
  AND observation_date BETWEEN :date_from AND :date_to
ORDER BY observation_date
"""

PRICE_SQL = """
WITH div AS (
  SELECT security_id, ex_dividend_date,
         COALESCE(adjusted_amount, amount) AS amount
  FROM raw.dividend_data
  WHERE amount > 0 AND provider = 'OPENBB'
),
div_on_row AS (
  SELECT e.security_id, m.observation_date, SUM(e.amount) AS amount
  FROM div e
  CROSS JOIN LATERAL (
    SELECT observation_date
    FROM raw.market_data m
    WHERE m.security_id = e.security_id
      AND m.observation_date >= e.ex_dividend_date
      AND m.close IS NOT NULL
    ORDER BY m.observation_date
    LIMIT 1
  ) m
  GROUP BY 1, 2
)
SELECT m.security_id::text AS security_id,
       m.observation_date,
       m.close::float8 AS close,
       m.volume::float8 AS volume,
       COALESCE(dv.amount, 0)::float8 AS dividend
FROM raw.market_data m
LEFT JOIN div_on_row dv
  ON dv.security_id = m.security_id
 AND dv.observation_date = m.observation_date
WHERE m.security_id = ANY(CAST(:ids AS uuid[]))
  AND m.close IS NOT NULL
  AND m.observation_date >= :date_from
  AND m.observation_date <= :date_to
ORDER BY m.observation_date, m.security_id
"""

ANNUAL_SQL = """
WITH annual AS (
  SELECT security_id::text AS security_id, period_end,
         max(net_income) AS net_income,
         max(assets) AS assets,
         max(operating_cash_flow) AS operating_cash_flow,
         max(debt) AS debt,
         max(current_assets) AS current_assets,
         max(current_liabilities) AS current_liabilities,
         max(shares_outstanding) AS shares_outstanding,
         max(gross_profit) AS gross_profit,
         max(revenue) AS revenue
  FROM fundamentals.periodic_financials
  WHERE fiscal_period = 'FY'
    AND filed <= :as_of
    AND security_id = ANY(CAST(:ids AS uuid[]))
  GROUP BY security_id, period_end
),
ranked AS (
  SELECT *, row_number() OVER (PARTITION BY security_id ORDER BY period_end DESC) AS rn
  FROM annual
)
SELECT * FROM ranked WHERE rn <= 2
"""

ANALYSES_SQL = """
SELECT ticker, status, recommendation, confidence,
       overall_risk_score, created_at, updated_at
FROM analysis.investment_analyses
ORDER BY updated_at DESC NULLS LAST, created_at DESC
"""

CATALYST_SQL = """
SELECT sec.ticker, d.ex_dividend_date, COALESCE(d.adjusted_amount, d.amount)::float8 AS amount
FROM raw.dividend_data d
JOIN reference.securities sec ON sec.security_id = d.security_id
WHERE d.provider = 'OPENBB'
  AND d.amount > 0
  AND d.security_id = ANY(CAST(:ids AS uuid[]))
  AND d.ex_dividend_date BETWEEN :date_from AND :date_to
ORDER BY d.ex_dividend_date, sec.ticker
"""


def load_score_dates(query=read_df) -> pd.DatetimeIndex:
    """Every date that has at least one published composite score."""
    frame = query(SCORE_DATES_SQL, {})
    return pd.DatetimeIndex(pd.to_datetime(frame["as_of_date"])).sort_values()


def rebalance_date(score_dates, as_of=None) -> pd.Timestamp:
    """The last score date of the most recent completed month.

    A partial month is deliberately excluded: rebalancing on its latest score
    date would make historical performance depend on the day the dashboard was
    opened. When no month has completed yet, the earliest score date is used so
    a newly seeded warehouse still produces a portfolio.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(score_dates)).sort_values().unique()
    if len(dates) == 0:
        raise ValueError("no score dates")
    as_of = pd.Timestamp(as_of or dates[-1])
    completed = dates[dates.to_period("M") < as_of.to_period("M")]
    if len(completed):
        return pd.Timestamp(completed[-1])
    return pd.Timestamp(dates[0])


def load_universe(as_of_date, min_coverage=MIN_COVERAGE, query=read_df) -> pd.DataFrame:
    """The scored, sufficiently covered universe on one date."""
    frame = query(
        UNIVERSE_SQL,
        {
            "as_of": as_of_date,
            "min_coverage": min_coverage,
            "min_price": MIN_PRICE,
            "max_price": ABSURD_PRICE_HIGH,
        },
    )
    frame["security_id"] = frame["security_id"].astype(str)
    for column in (
        "dividend_income_score",
        "sustainability_score",
        "appreciation_score",
        "risk_score",
        "valuation_score",
        "composite_score",
        "score_coverage",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _risk_parity_weights(frame: pd.DataFrame, volatility_column: str, gross: float) -> np.ndarray:
    """Inverse-volatility weights scaled to a sleeve's gross exposure."""
    volatilities = pd.to_numeric(frame[volatility_column], errors="coerce").to_numpy(dtype=float)
    if np.any(~np.isfinite(volatilities)) or np.any(volatilities <= 0):
        raise ValueError(f"risk parity requires positive finite {volatility_column}")
    weights = RiskParityCalculator.calculate_weights(volatilities)
    return weights * gross


def select_portfolio(
    universe: pd.DataFrame,
    long_count: int = LONG_COUNT,
    short_count: int = SHORT_COUNT,
    long_gross: float = LONG_GROSS,
    short_gross: float = SHORT_GROSS,
    base_nav: float = BASE_NAV,
    *,
    risk_parity: bool = False,
) -> pd.DataFrame:
    """Top names long and bottom names short, equal-weighted within each sleeve.

    Sizing is 100% of NAV long and 50% short, so gross exposure is 150% and net
    exposure is 50% long. Both sleeves are equal-weighted, not score-weighted, so
    the book's return is not dominated by one high-conviction name.

    ``risk_parity`` switches the sleeves from equal-weight sizing to inverse
    volatility risk parity, scaled to each sleeve's gross exposure. The default
    preserves the published equal-weight book.
    """
    frame = universe.dropna(subset=["composite_score"]).drop_duplicates("security_id").copy()
    frame["security_id"] = frame["security_id"].astype(str)
    if len(frame) < long_count + short_count:
        raise ValueError(f"need {long_count + short_count} scored names, found {len(frame)}")
    ranked = frame.sort_values(["composite_score", "security_id"], ascending=[False, True])
    longs = ranked.head(long_count).copy()
    shorts = ranked.tail(short_count).copy()
    if set(longs["security_id"]) & set(shorts["security_id"]):
        raise ValueError("long and short sleeves overlap")

    longs["side"] = "Long"
    if risk_parity:
        longs["weight"] = _risk_parity_weights(longs, "risk_score", long_gross)
    else:
        longs["weight"] = long_gross / long_count
    shorts["side"] = "Short"
    if risk_parity:
        shorts["weight"] = -_risk_parity_weights(shorts, "risk_score", short_gross)
    else:
        shorts["weight"] = -short_gross / short_count

    book = pd.concat([longs, shorts], ignore_index=True)
    book["notional"] = book["weight"].abs() * base_nav
    book["signed_notional"] = book["weight"] * base_nav
    book["rank"] = np.arange(1, len(book) + 1)
    return book.sort_values(["side", "composite_score"], ascending=[True, False]).reset_index(
        drop=True
    )


def total_return_matrix(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily total returns, indexed by date and columned by security id.

    ``prices`` is long: one row per security and observation date, with ``close``
    and an optional ``dividend``. A dividend larger than the prior close is
    dropped as a unit or currency error, exactly as ``returns.py`` does. Missing
    observations are forward-filled at the price level before differencing so a
    one-day price gap does not produce a false return.
    """
    required = {"security_id", "observation_date", "close"}
    missing = required - set(prices)
    if missing:
        raise ValueError(f"prices missing columns: {sorted(missing)}")
    frame = prices.copy()
    frame["security_id"] = frame["security_id"].astype(str)
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if "dividend" in frame:
        frame["dividend"] = pd.to_numeric(frame["dividend"], errors="coerce").fillna(0.0)
    else:
        frame["dividend"] = 0.0
    frame = frame.dropna(subset=["close"]).sort_values(["security_id", "observation_date"])
    frame = frame.drop_duplicates(["security_id", "observation_date"], keep="last")

    close = frame.pivot(index="observation_date", columns="security_id", values="close")
    close = close.sort_index().ffill()
    dividend = frame.pivot(
        index="observation_date", columns="security_id", values="dividend"
    ).reindex(index=close.index, columns=close.columns)
    dividend = dividend.fillna(0.0)
    previous = close.shift(1)
    valid_dividend = dividend.where(dividend <= MAX_SINGLE_PAYMENT_RATIO * previous, 0.0)
    matrix = (close + valid_dividend) / previous - 1.0
    return matrix.replace([np.inf, -np.inf], np.nan)


def portfolio_returns(returns: pd.DataFrame, book: pd.DataFrame) -> pd.DataFrame:
    """Daily portfolio return and NAV from a signed-weight book."""
    weights = book.set_index("security_id")["weight"].astype(float)
    common = [column for column in returns.columns if column in weights.index]
    if not common:
        raise ValueError("no held security has a return series")
    contribution = returns[common].mul(weights[common], axis=1)
    daily = contribution.sum(axis=1, min_count=1).dropna()
    nav = (1.0 + daily).cumprod() * BASE_NAV
    path = pd.DataFrame({"return": daily, "nav": nav})
    path["drawdown"] = path["nav"] / path["nav"].cummax() - 1.0
    return path


def performance_metrics(
    returns: pd.Series,
    benchmark: pd.Series | None = None,
    risk_free: pd.Series | None = None,
) -> dict:
    """Annualised performance and risk-adjusted ratios from daily returns.

    Sharpe uses excess returns over the daily risk-free series when it covers
    every return date. If it does not, Sharpe falls back to a zero rate and the
    result says so in ``risk_free_applied``.
    """
    series = pd.to_numeric(returns, errors="coerce").dropna()
    if series.empty:
        return {}
    rate = None
    if risk_free is not None:
        candidate = pd.to_numeric(risk_free, errors="coerce").reindex(series.index)
        if candidate.notna().all():
            rate = candidate
    excess = series - rate if rate is not None else series
    nav = (1.0 + series).cumprod()
    drawdown = nav / nav.cummax() - 1.0
    annual_return = nav.iloc[-1] ** (TRADING_DAYS / len(series)) - 1.0
    annual_volatility = series.std(ddof=1) * np.sqrt(TRADING_DAYS)
    # Downside deviation with a zero target over all N observations (standard
    # Sortino denominator): sqrt(mean(min(r, 0)^2)).
    downside_deviation = float(np.sqrt(np.mean(np.minimum(series.to_numpy(), 0.0) ** 2)))
    max_drawdown = float(drawdown.min())
    gains = series[series > 0].sum()
    losses = series[series < 0].sum()
    metrics = {
        "cumulative_return": float(nav.iloc[-1] - 1.0),
        "annual_return": float(annual_return),
        "annual_volatility": float(annual_volatility),
        "sharpe": float(excess.mean() / excess.std(ddof=1) * np.sqrt(TRADING_DAYS))
        if excess.std(ddof=1) > 0
        else np.nan,
        "risk_free_applied": rate is not None,
        "sortino": float(series.mean() / downside_deviation * np.sqrt(TRADING_DAYS))
        if downside_deviation > 0
        else np.nan,
        "max_drawdown": max_drawdown,
        "calmar": float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else np.nan,
        "omega": float(gains / abs(losses)) if losses < 0 else np.inf,
        "hit_rate": float((series > 0).mean()),
        "observations": int(len(series)),
    }
    if benchmark is not None:
        aligned = pd.concat([series, benchmark], axis=1, join="inner").dropna()
        if len(aligned) > 1:
            active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
            tracking = active.std(ddof=1)
            metrics["information_ratio"] = (
                float(active.mean() / tracking * np.sqrt(TRADING_DAYS)) if tracking > 0 else np.nan
            )
        else:
            metrics["information_ratio"] = np.nan
    return metrics


def monthly_return_table(returns: pd.Series) -> pd.DataFrame:
    """Calendar-month returns, including a partial first or last month."""
    series = pd.to_numeric(returns, errors="coerce").dropna()
    if series.empty:
        return pd.DataFrame(columns=["year", "month", "return"])
    grouped = (1.0 + series).groupby([series.index.year, series.index.month]).prod() - 1.0
    return pd.DataFrame(
        {
            "year": [key[0] for key in grouped.index],
            "month": [key[1] for key in grouped.index],
            "return": grouped.to_numpy(),
        }
    )


def risk_metrics(
    position_returns: pd.DataFrame,
    book: pd.DataFrame,
    confidence: float = 0.95,
    base_nav: float = BASE_NAV,
) -> dict:
    """Historical VaR/ES plus a parametric component-VaR decomposition.

    Component VaR uses the covariance matrix and signed weights, so a short
    position that hedges the book reports a negative contribution and the
    components sum to the parametric VaR. Historical VaR is the empirical
    quantile and is reported alongside it; the two answer different questions
    and are not expected to agree exactly.
    """
    weights = book.set_index("security_id")["weight"].astype(float)
    common = [column for column in position_returns.columns if column in weights.index]
    if not common:
        raise ValueError("no held security has a return series")
    frame = position_returns[common].dropna(how="all")
    aligned = weights[common]
    portfolio = frame.fillna(0.0).mul(aligned, axis=1).sum(axis=1)
    alpha = 1.0 - confidence
    historical_var = float(-np.nanpercentile(portfolio, alpha * 100.0))
    tail = portfolio[portfolio <= np.nanpercentile(portfolio, alpha * 100.0)]
    expected_shortfall = float(-tail.mean()) if len(tail) else np.nan

    # Covariance and correlation use one common window: only dates on which every
    # held name has a return. Pairwise estimates over uneven histories are not
    # guaranteed positive semi-definite, which would make parametric VaR invalid.
    complete = frame.dropna(how="any")
    covariance = complete.cov()
    variance = float(aligned.to_numpy() @ covariance.to_numpy() @ aligned.to_numpy())
    volatility = float(np.sqrt(max(variance, 0.0)))
    z_score = NormalDist().inv_cdf(confidence)
    marginal = (
        covariance.dot(aligned) / volatility if volatility > 0 else covariance.dot(aligned) * 0
    )
    component = aligned * marginal * z_score
    components = pd.DataFrame(
        {
            "security_id": common,
            "component_var": component.reindex(common).to_numpy(),
            "contribution": (component.reindex(common) / component.sum()).to_numpy()
            if component.sum() != 0
            else np.nan,
        }
    )
    return {
        "historical_var": historical_var,
        "historical_var_amount": historical_var * base_nav,
        "expected_shortfall": expected_shortfall,
        "expected_shortfall_amount": expected_shortfall * base_nav,
        "parametric_var": float(z_score * volatility),
        "parametric_var_amount": float(z_score * volatility * base_nav),
        "annual_volatility": float(volatility * np.sqrt(TRADING_DAYS)),
        "components": components,
        "correlation": complete.corr(),
        "covariance_observations": int(len(complete)),
        # A sample covariance of n names is full rank only with more than n dates.
        # This is a necessary condition, not proof of a stable estimate.
        "parametric_reliable": bool(len(complete) > len(common)),
        "portfolio_returns": portfolio,
    }


def stress_scenarios(returns: pd.Series, horizons=(1, 5, 20)) -> pd.DataFrame:
    """Worst realised loss over each horizon, as a historical stress table."""
    series = pd.to_numeric(returns, errors="coerce").dropna()
    rows = []
    for horizon in horizons:
        if len(series) < horizon:
            continue
        window = (1.0 + series).rolling(horizon).apply(np.prod, raw=True) - 1.0
        worst = float(window.min())
        rows.append({"horizon_days": horizon, "worst_return": worst, "worst_loss": -worst})
    return pd.DataFrame(rows)


def position_returns(returns: pd.DataFrame, book: pd.DataFrame) -> pd.DataFrame:
    """Total return per held security over the loaded window."""
    common = [column for column in returns.columns if column in set(book["security_id"])]
    series = (1.0 + returns[common].fillna(0.0)).prod() - 1.0
    return series.rename_axis("security_id").rename("total_return").reset_index()


def factor_exposures(book: pd.DataFrame) -> pd.DataFrame:
    """Weighted score-component exposure for the long and short sleeves."""
    rows = []
    for column, label in FACTOR_LABELS.items():
        if column not in book:
            continue
        longs = book[book["side"] == "Long"]
        shorts = book[book["side"] == "Short"]
        long_weight = longs["weight"].abs().sum()
        short_weight = shorts["weight"].abs().sum()
        long_value = (longs[column] * longs["weight"].abs()).sum() / long_weight
        short_value = (shorts[column] * shorts["weight"].abs()).sum() / short_weight
        rows.append(
            {
                "factor": label,
                "long": float(long_value),
                "short": float(short_value),
                "net": float(long_value - short_value),
            }
        )
    return pd.DataFrame(rows)


def sector_attribution(
    book: pd.DataFrame, holdings_returns: pd.DataFrame, base_nav: float = BASE_NAV
) -> pd.DataFrame:
    """P&L and excess return by sector, using signed weights."""
    merged = book.merge(holdings_returns, on="security_id", how="left")
    merged["total_return"] = merged["total_return"].fillna(0.0)
    merged["pnl"] = merged["weight"] * merged["total_return"] * base_nav
    merged["contribution"] = merged["weight"] * merged["total_return"]
    portfolio_return = merged["contribution"].sum()
    merged["excess_return"] = merged["total_return"] - portfolio_return
    grouped = merged.groupby("sector", dropna=False)
    table = grouped.apply(
        lambda group: pd.Series(
            {
                "pnl": group["pnl"].sum(),
                "contribution": group["contribution"].sum(),
                "alpha": (group["excess_return"] * group["weight"].abs()).sum()
                / group["weight"].abs().sum(),
                "positions": len(group),
            }
        ),
        include_groups=False,
    ).reset_index()
    return table.sort_values("pnl", ascending=False).reset_index(drop=True)


def piotroski_f_score(current: pd.Series, prior: pd.Series) -> tuple[int, dict, bool]:
    """Nine Piotroski signals from two annual periods.

    Returns ``(score, signals, complete)``. A missing input makes its signal
    ``None`` rather than counting as a failure; ``complete`` is false when any
    signal is missing, so the dashboard can show ``n/a`` instead of presenting a
    partial score as a full F-Score.
    """
    signals: dict[str, bool | None] = {}

    def ratio(row: pd.Series, numerator: str, denominator: str) -> float | None:
        top = pd.to_numeric(row.get(numerator), errors="coerce")
        bottom = pd.to_numeric(row.get(denominator), errors="coerce")
        if pd.isna(top) or pd.isna(bottom) or bottom <= 0:
            return None
        return float(top / bottom)

    roa = ratio(current, "net_income", "assets")
    prior_roa = ratio(prior, "net_income", "assets")
    cfo = pd.to_numeric(current.get("operating_cash_flow"), errors="coerce")
    leverage = ratio(current, "debt", "assets")
    prior_leverage = ratio(prior, "debt", "assets")
    current_ratio = ratio(current, "current_assets", "current_liabilities")
    prior_current_ratio = ratio(prior, "current_assets", "current_liabilities")
    gross_margin = ratio(current, "gross_profit", "revenue")
    prior_gross_margin = ratio(prior, "gross_profit", "revenue")
    turnover = ratio(current, "revenue", "assets")
    prior_turnover = ratio(prior, "revenue", "assets")
    shares = pd.to_numeric(current.get("shares_outstanding"), errors="coerce")
    prior_shares = pd.to_numeric(prior.get("shares_outstanding"), errors="coerce")
    net_income = pd.to_numeric(current.get("net_income"), errors="coerce")

    def compare(left, right, high=True):
        if left is None or right is None or pd.isna(left) or pd.isna(right):
            return None
        return bool(left > right) if high else bool(left < right)

    signals["positive_roa"] = None if roa is None else roa > 0
    signals["positive_cfo"] = None if pd.isna(cfo) else cfo > 0
    signals["roa_improving"] = compare(roa, prior_roa)
    signals["cfo_exceeds_net_income"] = (
        None if pd.isna(cfo) or pd.isna(net_income) else cfo > net_income
    )
    signals["leverage_falling"] = compare(leverage, prior_leverage, high=False)
    signals["current_ratio_improving"] = compare(current_ratio, prior_current_ratio)
    signals["no_share_issuance"] = (
        None if pd.isna(shares) or pd.isna(prior_shares) else shares <= prior_shares
    )
    signals["gross_margin_improving"] = compare(gross_margin, prior_gross_margin)
    signals["asset_turnover_improving"] = compare(turnover, prior_turnover)
    complete = all(value is not None for value in signals.values())
    score = sum(bool(value) for value in signals.values())
    return score, signals, complete


def load_risk_free(index, query=read_df) -> pd.Series:
    """Daily risk-free return on ``index`` from the 3-month Treasury yield.

    The yield is quoted in percent per annum. It is converted to a compounded
    daily rate over 252 trading days and carried onto each return date. Dates
    before the first observation take the first available yield. Returns an
    all-NaN series when the series has no data, so callers can fall back
    explicitly rather than silently assuming a zero rate.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(index))
    if dates.empty:
        return pd.Series(dtype=float)
    frame = query(
        RISK_FREE_SQL,
        {
            "series": RISK_FREE_SERIES,
            "date_from": dates.min().date(),
            "date_to": dates.max().date(),
        },
    )
    if frame is None or frame.empty:
        return pd.Series(np.nan, index=dates)
    yields = pd.Series(
        pd.to_numeric(frame["value"], errors="coerce").to_numpy() / 100.0,
        index=pd.to_datetime(frame["observation_date"]),
    ).dropna()
    if yields.empty:
        return pd.Series(np.nan, index=dates)
    carried = yields.reindex(yields.index.union(dates)).ffill().bfill().reindex(dates)
    return (1.0 + carried) ** (1.0 / TRADING_DAYS) - 1.0


# Price-quality rules, applied per security to the prices inside a holding period.
#
# A print is rejected when it is stale (zero volume: no trade supports the close)
# or when it spikes away from the last accepted close and reverts within a few
# sessions (a bad tick). A move that persists is kept, because it may be a real
# event, such as a takeover. A rejected print is replaced by the last accepted
# close, so its return is zero and any dividend on that day is kept.
STALE_PRINT_VOLUME = 0.0
SPIKE_THRESHOLD = 0.50
REVERSION_SESSIONS = 5
REVERSION_BAND = 0.20
# A close outside this range is a unit or feed error, not a price. Measured
# on 2026-10-24: 1,924 daily moves of 40% or more had a close above 1e6 or
# below 1e-4 (WHLR alone printed closes in the hundreds of billions).
ABSURD_PRICE_HIGH = 1e6
#: A split is applied only if the observed one-session move is within this
#: fraction of the reported ratio, and the move falls within this many days of the event.
SPLIT_TOLERANCE = 0.10
SPLIT_EVENT_WINDOW_DAYS = 5
#: A security whose prints are rejected more than this share of the time, within
#: the cleaned window, is not a usable price history. It is excluded from selection
#: for that period rather than kept with a cleaned series (judgment call: 20%).
UNRELIABLE_REJECT_SHARE = 0.20
ABSURD_PRICE_LOW = 1e-4


def clean_prices(
    prices: pd.DataFrame,
    split_events: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, int]:
    """Replace stale and spike-and-revert closes with the last accepted close.

    ``split_events`` (columns security_id, date, ratio) is applied only where the
    price itself shows the split: the one-session move on the event date must be
    within ``SPLIT_TOLERANCE`` of the reported ratio. Earlier prints are then scaled
    by the observed move, so the split day has no return. Events the warehouse has
    already adjusted show no jump and change nothing.

    Returns the cleaned frame and the number of rejected prints. The number of
    splits applied is in ``frame.attrs["splits_adjusted"]``. A missing volume
    is treated as unknown, not as zero, so only an explicit zero rejects a print.
    The reversal test looks at later prints, so it uses the full holding window.
    Persistent moves are kept, and so are moves at the end of the window that have
    no later print to confirm them.
    """
    if prices.empty:
        empty = prices.copy()
        empty.attrs["unreliable_ids"] = []
        return empty, 0
    frame = prices.copy()
    if "volume" not in frame:
        frame["volume"] = np.nan
    frame = frame.sort_values(["security_id", "observation_date"]).reset_index(drop=True)
    events = {}
    if split_events is not None and not split_events.empty:
        for sid, event_frame in split_events.groupby("security_id"):
            events[str(sid)] = list(zip(pd.to_datetime(event_frame["date"]), event_frame["ratio"]))
    rejected_total = 0
    splits_adjusted = 0
    unreliable: set[str] = set()
    cleaned_parts = []
    for sid, group in frame.groupby("security_id", sort=False):
        close = group["close"].to_numpy(dtype=float).copy()
        volume = group["volume"].to_numpy(dtype=float)
        dates = pd.DatetimeIndex(group["observation_date"])
        for event_date, expected in events.get(str(sid), []):
            index = _event_index(dates, event_date)
            if index is None or index == 0:
                continue
            observed = close[index] / close[index - 1]
            if observed > 0 and abs(observed / expected - 1.0) <= SPLIT_TOLERANCE:
                close[:index] *= observed
                splits_adjusted += 1
        stale = volume == STALE_PRINT_VOLUME
        absurd = (close > ABSURD_PRICE_HIGH) | (close < ABSURD_PRICE_LOW)
        unusable = stale | absurd
        rejected = unusable.copy()
        good = np.flatnonzero(~unusable)
        base = None
        for position, index in enumerate(good):
            value = close[index]
            if base is None:
                base = value
                continue
            if abs(value / base - 1.0) <= SPIKE_THRESHOLD:
                base = value
                continue
            later = good[position + 1 : position + 1 + REVERSION_SESSIONS]
            reverts = any(abs(close[j] / base - 1.0) <= REVERSION_BAND for j in later)
            if reverts:
                rejected[index] = True
            else:
                base = value
        # Replace each rejected print with the last accepted close before it. Leading
        # rejected prints take the first accepted close.
        if len(good) == 0:
            # No usable print at all: the series carries no return. Blanking the
            # closes drops the rows, so the name earns nothing rather than noise.
            close[:] = np.nan
            rejected_total += len(close)
            unreliable.add(str(sid))
            cleaned = group.copy()
            cleaned["close"] = close
            cleaned_parts.append(cleaned)
            continue
        last_accepted = close[good[0]]
        group_rejected = int(rejected.sum())
        for index in range(len(close)):
            if rejected[index]:
                if last_accepted is not None:
                    close[index] = last_accepted
                rejected_total += 1
            else:
                last_accepted = close[index]
        if len(close) and group_rejected / len(close) > UNRELIABLE_REJECT_SHARE:
            unreliable.add(str(sid))
        cleaned = group.copy()
        cleaned["close"] = close
        cleaned_parts.append(cleaned)
    result = pd.concat(cleaned_parts, ignore_index=True)
    result.attrs["splits_adjusted"] = splits_adjusted
    result.attrs["unreliable_ids"] = sorted(unreliable)
    return result, rejected_total


def exclude_unreliable(universe: pd.DataFrame, cleaned: pd.DataFrame) -> pd.DataFrame:
    """Drop securities whose cleaned price history is flagged unreliable."""
    flagged = set(cleaned.attrs.get("unreliable_ids", []))
    if not flagged:
        return universe
    return universe[~universe["security_id"].astype(str).isin(flagged)].reset_index(drop=True)


def _event_index(dates: pd.DatetimeIndex, event_date: pd.Timestamp) -> int | None:
    """Position of the first print on or after the event, within a few sessions."""
    later = np.flatnonzero(dates >= event_date)
    if len(later) == 0:
        return None
    index = int(later[0])
    if (dates[index] - event_date).days > SPLIT_EVENT_WINDOW_DAYS:
        return None
    return index


SECURITY_TICKERS_SQL = """
SELECT security_id::text AS security_id, ticker
FROM reference.securities
WHERE security_type = 'common_stock'
"""


SPLIT_EVENTS_SQL = """
SELECT security_id::text AS security_id, effective_date AS date, ratio::float8 AS ratio
FROM raw.corporate_actions
WHERE action_type = 'split' AND security_id IS NOT NULL AND ratio > 0
ORDER BY security_id, effective_date
"""


def load_split_events(path=None, query=read_df) -> pd.DataFrame:
    """Split events as (security_id, date, ratio), where ratio = denominator / numerator.

    Read from ``raw.corporate_actions`` (loaded by ``scripts.load_corporate_actions``).
    ``clean_prices`` applies each event only where the price shows the jump, so a
    ticker shared by several identities cannot adjust the wrong one. ``path`` is the
    legacy CSV artifact and is read only when given explicitly; it maps tickers to
    identities as the old loader did. Returns an empty frame when nothing is stored.
    """
    columns = ["security_id", "date", "ratio"]
    if path is None:
        frame = query(SPLIT_EVENTS_SQL, {})
        if frame is None or frame.empty:
            return pd.DataFrame(columns=columns)
        frame = frame[columns].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return frame.reset_index(drop=True)
    if not Path(path).exists():
        return pd.DataFrame(columns=columns)
    raw = pd.read_csv(path, dtype={"ticker": str})
    raw["numerator"] = pd.to_numeric(raw["numerator"], errors="coerce")
    raw["denominator"] = pd.to_numeric(raw["denominator"], errors="coerce")
    raw = raw.dropna(subset=["date", "numerator", "denominator"])
    raw = raw[(raw["numerator"] > 0) & (raw["denominator"] > 0)]
    raw["date"] = pd.to_datetime(raw["date"])
    raw["ratio"] = raw["denominator"] / raw["numerator"]
    securities = query(SECURITY_TICKERS_SQL, {})
    merged = raw.merge(securities, on="ticker", how="inner")
    return merged[columns].reset_index(drop=True)


def load_prices(
    security_ids,
    date_from,
    date_to,
    query=read_df,
) -> pd.DataFrame:
    """Daily close and ex-date dividend for a set of securities."""
    ids = [str(value) for value in security_ids]
    frame = query(
        PRICE_SQL,
        {
            "ids": ids,
            "date_from": pd.Timestamp(date_from).date(),
            "date_to": pd.Timestamp(date_to).date(),
        },
    )
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    return frame


def load_f_scores(security_ids, as_of_date, query=read_df) -> pd.DataFrame:
    """Piotroski F-Score for each security from its two latest filed fiscal years."""
    ids = [str(value) for value in security_ids]
    frame = query(ANNUAL_SQL, {"ids": ids, "as_of": pd.Timestamp(as_of_date).date()})
    rows = []
    for security_id, group in frame.groupby("security_id"):
        ordered = group.sort_values("period_end", ascending=False)
        current = ordered.iloc[0]
        prior = ordered.iloc[1] if len(ordered) > 1 else pd.Series(dtype=float)
        score, _signals, complete = piotroski_f_score(current, prior)
        rows.append(
            {
                "security_id": str(security_id),
                "f_score": score if complete else None,
                "f_score_max": 9,
                "f_score_complete": complete,
            }
        )
    return pd.DataFrame(rows, columns=["security_id", "f_score", "f_score_max", "f_score_complete"])


def conviction(score: float, coverage: float, f_score: float | None, side: str) -> str:
    """A coarse label that combines score strength, evidence and accounting quality.

    F-Score is an optional overlay, not a prerequisite: the annual fundamentals
    table does not cover every ranked name, and labelling an otherwise strong,
    fully covered position "Low" merely because the accounting history is absent
    would confuse missing evidence with bad evidence.
    """
    strength = score if side == "Long" else 1.0 - score
    measured = f_score is not None and not pd.isna(f_score)
    quality = float(f_score) if measured else None
    if strength >= 0.80 and coverage >= 0.75:
        if measured and quality < 5:
            return "Medium"
        return "High"
    if strength >= 0.60 and coverage >= 0.50:
        if measured and quality < 3:
            return "Low"
        return "Medium"
    return "Low"


def holdings_table(
    book: pd.DataFrame,
    returns: pd.DataFrame,
    f_scores: pd.DataFrame,
    risk: dict,
    base_nav: float = BASE_NAV,
) -> pd.DataFrame:
    """The position book: return, P&L, F-Score, VaR contribution and conviction."""
    table = book.copy()
    table = table.merge(position_returns(returns, book), on="security_id", how="left")
    table = table.merge(f_scores, on="security_id", how="left")
    components = risk.get("components")
    if components is not None:
        table = table.merge(components, on="security_id", how="left")
    table["pnl"] = table["weight"] * table["total_return"] * base_nav
    table["conviction"] = [
        conviction(row.composite_score, row.score_coverage, row.f_score, row.side)
        for row in table.itertuples(index=False)
    ]
    return table.sort_values(["side", "pnl"], ascending=[True, False]).reset_index(drop=True)


def load_analyses(query=read_df) -> pd.DataFrame:
    """Research worksheet status, latest per ticker."""
    frame = query(ANALYSES_SQL, {})
    if frame.empty:
        return frame
    # Keep only the most recent worksheet per ticker to avoid duplicates
    # in the Research Pipeline join.
    frame = frame.copy()
    frame["updated_at"] = pd.to_datetime(frame["updated_at"], errors="coerce")
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    frame = frame.sort_values(
        ["ticker", "updated_at", "created_at"], ascending=[True, False, False]
    )
    return frame.drop_duplicates(subset=["ticker"], keep="first").reset_index(drop=True)


def load_catalysts(security_ids, date_from, date_to, query=read_df) -> pd.DataFrame:
    """Upcoming OPENBB ex-dividend dates for the coverage universe."""
    ids = [str(value) for value in security_ids]
    return query(
        CATALYST_SQL,
        {
            "ids": ids,
            "date_from": pd.Timestamp(date_from).date(),
            "date_to": pd.Timestamp(date_to).date(),
        },
    )
