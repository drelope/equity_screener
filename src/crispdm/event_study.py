"""Event studies for ex-dividend dates and monthly options expiration (opex).

Pure functions over price matrices (rows = trading days, columns = securities) so the
statistics are testable without a database. ``scripts.event_study`` loads the data and
prints the results.

Method notes, because the conclusions are only as good as these choices:

* Returns are price returns from ``close``. ``adjusted_close`` is not populated, and
  ``close`` is split-adjusted but not dividend-adjusted (it falls on the ex-date).
* The market is the equal-weight cross-sectional mean return of the same universe on
  the same day, so an abnormal return is net of that day's market move.
* Many stocks share an ex-date, so their abnormal returns are not independent. The
  ex-dividend t-statistics average within ex-date first and test across dates.
* Opex has one observation per month (about 93 over 2019-2026), so its tests have low
  power; a small real effect can easily fail to reach significance.
* Many offsets are tested, so every table carries the Bonferroni threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Trading days either side of an event that are studied.
EX_WINDOW = (-5, 5)
OPEX_WINDOW = (-4, 5)
#: A one-day price return beyond this is treated as a bad print, not a market move.
MAX_ABS_RETURN = 0.5
MIN_PRIOR_CLOSE = 5.0
#: A single dividend above this share of the price is a special distribution or a bad
#: amount, not a regular ex-date event, and the add-back would dominate the average.
MAX_EVENT_YIELD = 0.10
#: Tails clipped on each offset before averaging; a few corrupt events otherwise move
#: the mean by an order of magnitude.
WINSOR = 0.01
#: A stock counts as a dividend payer for this many trading days after an ex-date.
PAYER_LOOKBACK_DAYS = 252


def third_fridays(trading_days: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Monthly opex: each month's third Friday, or the prior trading day if it is a holiday.

    Months at the edge of the data are skipped if their opex day cannot be placed in
    ``trading_days``.
    """
    days = pd.DatetimeIndex(sorted(set(trading_days)))
    if days.empty:
        return []
    out = []
    for period in pd.period_range(days[0], days[-1], freq="M"):
        fridays = pd.date_range(period.start_time, period.end_time, freq="W-FRI")
        if len(fridays) < 3:
            continue
        target = fridays[2]
        if target < days[0] or target > days[-1]:
            continue
        if target in days:
            out.append(target)
        else:
            prior = days[days < target]
            if len(prior) and (target - prior[-1]).days <= 3:
                out.append(prior[-1])
    return out


def daily_returns(close: pd.DataFrame, min_prior_close: float = MIN_PRIOR_CLOSE) -> pd.DataFrame:
    """Price returns, blanked where the prior close is below the floor or the move is absurd."""
    prev = close.shift(1)
    ret = close / prev - 1.0
    ret = ret.where(prev >= min_prior_close)
    return ret.where(ret.abs() <= MAX_ABS_RETURN)


def market_return(returns: pd.DataFrame, mask: pd.DataFrame | None = None) -> pd.Series:
    """Equal-weight mean return across the securities in ``mask`` (all when omitted)."""
    data = returns if mask is None else returns.where(mask)
    return data.mean(axis=1)


def payer_mask(
    index: pd.DatetimeIndex,
    columns: pd.Index,
    events: pd.DataFrame,
    lookback_days: int = PAYER_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """True where a security had an ex-date within the trailing ``lookback_days`` trading days.

    The benchmark for an ex-dividend study should be other payers: payers differ
    systematically from the all-stock average, and measuring against the average
    mistakes that gap for an event effect. The event's own day is included in the
    window, which is immaterial across thousands of securities.
    """
    pos = pd.DataFrame(np.nan, index=index, columns=columns)
    col = {c: i for i, c in enumerate(columns)}
    last = np.full((len(index), len(columns)), np.nan)
    for ev in events.itertuples():
        if ev.security_id not in col:
            continue
        p = index.searchsorted(pd.Timestamp(ev.ex_date))
        if p < len(index):
            last[p, col[ev.security_id]] = p
    pos[:] = last
    pos = pos.ffill()
    ahead = np.arange(len(index))[:, None] - pos.to_numpy()
    return pd.DataFrame(ahead <= lookback_days, index=index, columns=columns)


def liquid_mask(close: pd.DataFrame, volume: pd.DataFrame, top: int = 1000, window: int = 60):
    """True for the ``top`` securities by trailing median dollar volume on each day.

    A stand-in for "has listed options": no options-listing data is held, and listed
    options concentrate in the most liquid names.
    """
    dollar = (close * volume).rolling(window, min_periods=window // 2).median()
    rank = dollar.rank(axis=1, ascending=False, method="first")
    return rank <= top


@dataclass(frozen=True)
class OffsetStat:
    offset: int
    n: int
    mean: float
    t: float | None


def _t(values: np.ndarray, baseline_mean: float = 0.0) -> float | None:
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return None
    sd = values.std(ddof=1)
    if sd == 0:
        return None
    return float((values.mean() - baseline_mean) / (sd / math.sqrt(len(values))))


def bonferroni_t(tests: int, alpha: float = 0.05) -> float:
    """Two-sided critical |t| (normal approximation) after a Bonferroni correction."""
    from statistics import NormalDist

    return NormalDist().inv_cdf(1 - alpha / (2 * max(tests, 1)))


def opex_study(
    market: pd.Series, opex_days: list[pd.Timestamp], window: tuple[int, int] = OPEX_WINDOW
) -> list[OffsetStat]:
    """Mean market return at each trading-day offset from opex, tested against the all-day mean.

    The baseline is the mean over all days outside every opex window, so an opex-week
    effect is judged against ordinary days and not against itself.
    """
    market = market.dropna()
    idx = market.index
    positions = {d: idx.get_loc(d) for d in opex_days if d in idx}
    lo, hi = window
    in_window = np.zeros(len(idx), dtype=bool)
    for pos in positions.values():
        in_window[max(pos + lo, 0) : min(pos + hi + 1, len(idx))] = True
    baseline = market.to_numpy()[~in_window]
    base_mean = float(baseline.mean()) if len(baseline) else 0.0
    out = []
    for k in range(lo, hi + 1):
        values = np.array([market.iloc[p + k] for p in positions.values() if 0 <= p + k < len(idx)])
        out.append(
            OffsetStat(
                k,
                len(values),
                float(values.mean()) if len(values) else float("nan"),
                _t(values, base_mean),
            )
        )
    return out


def opex_dispersion(market: pd.Series, opex_days: list[pd.Timestamp]) -> dict[str, float]:
    """Absolute market return on opex days against all other days (a volatility check)."""
    absolute = market.abs().dropna()
    on = absolute[absolute.index.isin(opex_days)]
    off = absolute[~absolute.index.isin(opex_days)]
    if len(on) < 3 or len(off) < 3:
        return {}
    se = math.sqrt(on.var(ddof=1) / len(on) + off.var(ddof=1) / len(off))
    return {
        "opex_mean_abs": float(on.mean()),
        "other_mean_abs": float(off.mean()),
        "t": float((on.mean() - off.mean()) / se) if se else float("nan"),
        "n_opex": len(on),
    }


def ex_dividend_events(
    close: pd.DataFrame,
    returns: pd.DataFrame,
    market: pd.Series,
    events: pd.DataFrame,
    window: tuple[int, int] = EX_WINDOW,
) -> pd.DataFrame:
    """One row per usable event with abnormal returns at each offset and the drop ratio.

    ``events`` has columns security_id, ex_date, amount (split-adjusted, per share).
    Events whose dividend exceeds ``MAX_EVENT_YIELD`` of the prior close are dropped.
    Day 0 is the first trading day on or after the ex-date. On day 0 the dividend is
    added back so the abnormal return is a total return; ``drop_ratio`` is the price
    fall divided by the dividend.
    """
    idx = close.index
    lo, hi = window
    rows = []
    for ev in events.itertuples():
        if ev.security_id not in close.columns:
            continue
        pos = idx.searchsorted(pd.Timestamp(ev.ex_date))
        if pos <= 0 or pos + hi >= len(idx):
            continue
        series = close[ev.security_id]
        p_prev, p0 = series.iloc[pos - 1], series.iloc[pos]
        if not (p_prev >= MIN_PRIOR_CLOSE and p0 > 0 and ev.amount > 0):
            continue
        if ev.amount / p_prev > MAX_EVENT_YIELD:
            continue
        row = {
            "security_id": ev.security_id,
            "ex_date": idx[pos],
            "yield": ev.amount / p_prev,
            "drop_ratio": (p_prev - p0) / ev.amount,
        }
        ok = True
        for k in range(lo, hi + 1):
            r = returns[ev.security_id].iloc[pos + k]
            m = market.iloc[pos + k]
            if k == 0 and np.isfinite(r):
                r = r + ev.amount / p_prev  # add the dividend back: a total return
            if not (np.isfinite(r) and np.isfinite(m)):
                ok = False
                break
            row[k] = r - m
        if ok:
            rows.append(row)
    return pd.DataFrame(rows)


def winsorize(values: pd.Series, tail: float = WINSOR) -> pd.Series:
    """Clip ``values`` to its ``tail`` and ``1 - tail`` quantiles."""
    if tail <= 0 or len(values) < 20:
        return values
    return values.clip(values.quantile(tail), values.quantile(1 - tail))


def ex_dividend_study(
    events: pd.DataFrame, window: tuple[int, int] = EX_WINDOW, winsor: float = WINSOR
) -> dict:
    """Mean abnormal return by offset, cumulative windows and drop ratio, clustered by date.

    Each offset is winsorized across events before averaging within an ex-date.
    """
    if events.empty:
        return {"n": 0, "offsets": [], "cumulative": {}, "drop_ratio": {}}
    lo, hi = window
    cols = list(range(lo, hi + 1))
    events = events.copy()
    for k in cols:
        events[k] = winsorize(events[k], winsor)
    by_date = events.groupby("ex_date")[cols].mean()  # average within date, then test across dates
    offsets = [
        OffsetStat(k, len(by_date), float(by_date[k].mean()), _t(by_date[k].to_numpy()))
        for k in cols
    ]

    def cumulative(a: int, b: int):
        per_date = by_date[[k for k in cols if a <= k <= b]].sum(axis=1)
        return {
            "mean": float(per_date.mean()),
            "t": _t(per_date.to_numpy()),
            "dates": len(per_date),
        }

    ratio = events["drop_ratio"]
    trimmed = ratio[ratio.abs() < 5]
    return {
        "n": len(events),
        "dates": len(by_date),
        "offsets": offsets,
        "cumulative": {
            "CAR[-5,-1]": cumulative(-5, -1),
            "AR[0]": cumulative(0, 0),
            "CAR[+1,+5]": cumulative(1, 5),
            "CAR[0,+5]": cumulative(0, 5),
        },
        "drop_ratio": {
            "median": float(ratio.median()),
            "trimmed_mean": float(trimmed.mean()),
            "n_trimmed": int(len(trimmed)),
        },
    }
