"""Baseline strategies for comparison."""

from __future__ import annotations

import pandas as pd


def equal_weight_portfolio(tickers: list[str]) -> pd.Series:
    """Equal-weight allocation across all tickers."""
    n = len(tickers)
    if n == 0:
        return pd.Series(dtype=float)
    return pd.Series(1.0 / n, index=tickers)


def yield_weight_portfolio(tickers: list[str], yields: pd.Series) -> pd.Series:
    """Weight by dividend yield."""
    yields = yields.reindex(tickers).fillna(0)
    total = yields.sum()
    if total == 0:
        return equal_weight_portfolio(tickers)
    return yields / total


def inverse_volatility_portfolio(tickers: list[str], volatilities: pd.Series) -> pd.Series:
    """Weight by inverse volatility (price-based baseline)."""
    vols = volatilities.reindex(tickers).fillna(volatilities.mean())
    # Avoid zero/negative
    vols = vols.clip(lower=1e-6)
    inv_vols = 1.0 / vols
    total = inv_vols.sum()
    if total == 0:
        return equal_weight_portfolio(tickers)
    return inv_vols / total


def compute_portfolio_returns(
    weights: pd.Series,
    returns: pd.DataFrame,
) -> pd.Series:
    """Compute portfolio returns given weights and asset returns."""
    weights = weights.reindex(returns.columns).fillna(0)
    return (returns * weights).sum(axis=1)


def compare_baselines(
    returns: pd.DataFrame,
    dividend_yields: pd.Series | None = None,
    volatilities: pd.Series | None = None,
) -> pd.DataFrame:
    """Compare baseline strategies."""
    tickers = list(returns.columns)
    results = {}

    # Equal weight
    w_eq = equal_weight_portfolio(tickers)
    results["equal_weight"] = compute_portfolio_returns(w_eq, returns)

    # Yield weight
    if dividend_yields is not None:
        w_yield = yield_weight_portfolio(tickers, dividend_yields)
        results["yield_weight"] = compute_portfolio_returns(w_yield, returns)

    # Inverse vol
    if volatilities is not None:
        w_inv_vol = inverse_volatility_portfolio(tickers, volatilities)
        results["inverse_volatility"] = compute_portfolio_returns(w_inv_vol, returns)

    return pd.DataFrame(results)
