"""Walk-forward backtest of the model portfolio over the stored month-end scores.

At each rebalance date the book is built from that date's scores and held, with
no trading costs, until the next rebalance date. A holding period earns returns
strictly after its formation close, so a position never earns the return of the
day its score was known. The benchmark is the equal-weight scored universe at
the same formation date, matching the dashboard.

Data enters through injected loaders so the arithmetic is testable without the
warehouse. :func:`run_from_warehouse` wires the real loaders in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.crispdm import portfolio as pf
from src.crispdm.db import read_df

PERIODS_PER_YEAR = 12
#: Names the rules in src/crispdm/portfolio.py (clean_prices). Recorded per run.
PRICE_FILTER = "stale_reversal_absurd_split_unreliable_v5"
#: Calendar days of prices read past each period end to confirm a reversal.
CLEANING_LOOKAHEAD = pd.Timedelta(days=14)


@dataclass(frozen=True)
class BacktestResult:
    daily: pd.DataFrame
    periods: pd.DataFrame
    metrics: dict = field(default_factory=dict)


def rebalance_schedule(score_dates) -> pd.DatetimeIndex:
    """The last score date of each calendar month, plus the newest score date.

    The newest date closes the final holding period even when its month is not
    complete, so the most recent month is still evaluated through the latest
    score.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(list(score_dates))).sort_values().unique()
    if len(dates) == 0:
        return pd.DatetimeIndex([])
    frame = pd.Series(dates, index=dates)
    month_end = frame.groupby([dates.year, dates.month]).max()
    schedule = pd.DatetimeIndex(sorted(set(month_end.to_numpy()) | {dates[-1]}))
    return schedule


def run_walk_forward(
    rebalance_dates,
    universe_for,
    prices_for,
    risk_free_for=None,
    *,
    split_events=None,
    long_count: int = pf.LONG_COUNT,
    short_count: int = pf.SHORT_COUNT,
    base_nav: float = pf.BASE_NAV,
) -> BacktestResult:
    """Chain the book's holding-period returns into one daily series.

    ``universe_for(date)`` returns the scored universe on a date.
    ``prices_for(ids, start, end)`` returns long prices (see ``load_prices``).
    ``risk_free_for(index)`` returns the daily risk-free return on ``index``.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(list(rebalance_dates))).sort_values().unique()
    if len(dates) < 2:
        raise ValueError("a walk-forward run needs at least two rebalance dates")

    daily_parts: list[pd.DataFrame] = []
    period_rows: list[dict] = []
    rejected_prints = 0
    splits_applied = 0
    unreliable_excluded: set[str] = set()
    previous = pd.Series(dtype=float)

    for start, end in zip(dates[:-1], dates[1:]):
        scored = universe_for(start)
        # Prices run past the period end so a spike near the end can be confirmed or
        # rejected. Returns are still taken only up to the end (see the window below).
        # The whole scored universe is cleaned first, so a name with an unreliable
        # history is removed before the book is chosen, not after.
        ids = sorted(set(scored["security_id"].astype(str)))
        prices, rejected = pf.clean_prices(
            prices_for(ids, start, end + CLEANING_LOOKAHEAD),
            split_events=split_events,
        )
        rejected_prints += rejected
        splits_applied += prices.attrs.get("splits_adjusted", 0)
        unreliable_excluded.update(prices.attrs.get("unreliable_ids", []))
        universe = pf.exclude_unreliable(scored, prices)
        try:
            book = pf.select_portfolio(
                universe,
                long_count=long_count,
                short_count=short_count,
                base_nav=base_nav,
            )
        except ValueError as err:
            # Too few reliable scored names: the book stays in cash for the period.
            period_rows.append(_period_row(start, end, status=f"cash: {err}"))
            daily_parts.append(_cash_period(start, end))
            previous = pd.Series(dtype=float)
            continue

        weights = book.set_index("security_id")["weight"].astype(float)
        returns = pf.total_return_matrix(prices) if not prices.empty else pd.DataFrame()
        window = (
            returns.loc[(returns.index > start) & (returns.index <= end)]
            if len(returns)
            else returns
        )
        if window.empty:
            period_rows.append(_period_row(start, end, status="cash: no prices"))
            daily_parts.append(_cash_period(start, end))
            previous = pd.Series(dtype=float)
            continue

        held = window[[column for column in window.columns if column in weights.index]]
        contribution = held.mul(weights[held.columns], axis=1)
        book_return = contribution.sum(axis=1, min_count=1)
        missing_days = int(book_return.isna().sum())
        book_return = book_return.fillna(0.0)
        universe_ids = [
            column
            for column in window.columns
            if column in set(universe["security_id"].astype(str))
        ]
        benchmark = window[universe_ids].mean(axis=1, skipna=True).fillna(0.0)

        turnover = 0.5 * _weight_change(previous, weights)
        period_return = float((1.0 + book_return).prod() - 1.0)
        benchmark_return = float((1.0 + benchmark).prod() - 1.0)
        period_rows.append(
            _period_row(
                start,
                end,
                status="held",
                period_return=period_return,
                benchmark_return=benchmark_return,
                turnover=turnover,
                long_names=int((book["side"] == "Long").sum()),
                short_names=int((book["side"] == "Short").sum()),
                gross=float(weights.abs().sum()),
                net=float(weights.sum()),
                missing_days=missing_days,
            )
        )
        daily_parts.append(
            pd.DataFrame({"return": book_return, "benchmark": benchmark}, index=window.index)
        )
        previous = weights

    if not daily_parts:
        raise ValueError("no holding period produced returns")
    daily = pd.concat(daily_parts).sort_index()
    daily = daily[~daily.index.duplicated(keep="last")]
    daily["nav"] = (1.0 + daily["return"]).cumprod() * base_nav
    daily["drawdown"] = daily["nav"] / daily["nav"].cummax() - 1.0

    periods = pd.DataFrame(period_rows)
    rf = risk_free_for(daily.index) if risk_free_for is not None else None
    metrics = pf.performance_metrics(daily["return"], daily["benchmark"], risk_free=rf)
    held_periods = periods[periods["status"] == "held"]
    metrics["price_filter"] = PRICE_FILTER
    metrics["rejected_prints"] = int(rejected_prints)
    metrics["splits_adjusted"] = int(splits_applied)
    metrics["unreliable_securities_excluded"] = len(unreliable_excluded)
    metrics["periods"] = int(len(periods))
    metrics["held_periods"] = int(len(held_periods))
    metrics["cash_periods"] = int(len(periods) - len(held_periods))
    if len(held_periods):
        metrics["average_one_way_turnover_annual"] = float(
            held_periods["turnover"].mean() * PERIODS_PER_YEAR
        )
        metrics["periods_beating_benchmark"] = float(
            (held_periods["period_return"] > held_periods["benchmark_return"]).mean()
        )
    return BacktestResult(daily=daily, periods=periods, metrics=metrics)


def _period_row(start, end, status, **values) -> dict:
    row = {
        "formation": pd.Timestamp(start),
        "end": pd.Timestamp(end),
        "status": status,
        "period_return": np.nan,
        "benchmark_return": np.nan,
        "turnover": np.nan,
        "long_names": 0,
        "short_names": 0,
        "gross": 0.0,
        "net": 0.0,
        "missing_days": 0,
    }
    row.update(values)
    return row


def _cash_period(start, end) -> pd.DataFrame:
    """A flat period: zero return on each trading day it spans, with no prices."""
    index = pd.bdate_range(pd.Timestamp(start) + pd.Timedelta(days=1), end)
    return pd.DataFrame({"return": 0.0, "benchmark": 0.0}, index=index)


def _weight_change(previous: pd.Series, current: pd.Series) -> float:
    """Sum of absolute weight changes across the union of names."""
    union = previous.index.union(current.index)
    old = previous.reindex(union).fillna(0.0)
    new = current.reindex(union).fillna(0.0)
    return float((new - old).abs().sum())


def run_from_warehouse(query=read_df, **kwargs) -> BacktestResult:
    """Run the backtest on the stored month-end scores using the real loaders."""
    dates = pf.load_score_dates(query=query)
    schedule = rebalance_schedule(dates)
    return run_walk_forward(
        schedule,
        universe_for=lambda day: pf.load_universe(day, query=query),
        prices_for=lambda ids, start, end: pf.load_prices(ids, start, end, query=query),
        risk_free_for=lambda index: pf.load_risk_free(index, query=query),
        split_events=pf.load_split_events(query=query),
        **kwargs,
    )
