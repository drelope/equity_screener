"""Tests for baseline strategies."""

from __future__ import annotations

import pandas as pd

from src.crispdm.baselines import (
    compare_baselines,
    equal_weight_portfolio,
    inverse_volatility_portfolio,
    yield_weight_portfolio,
)


def test_equal_weight_portfolio():
    w = equal_weight_portfolio(["A", "B", "C"])
    assert len(w) == 3
    assert (w == 1 / 3).all()
    assert w.sum() == 1.0


def test_equal_weight_empty():
    w = equal_weight_portfolio([])
    assert w.empty


def test_yield_weight_portfolio():
    yields = pd.Series({"A": 0.04, "B": 0.02, "C": 0.02})
    w = yield_weight_portfolio(["A", "B", "C"], yields)
    assert w["A"] == 0.5
    assert w["B"] == 0.25
    assert w["C"] == 0.25


def test_yield_weight_fallback_to_equal():
    yields = pd.Series({"A": 0.0, "B": 0.0})
    w = yield_weight_portfolio(["A", "B"], yields)
    assert (w == 0.5).all()


def test_inverse_volatility_portfolio():
    vols = pd.Series({"A": 0.20, "B": 0.10})
    w = inverse_volatility_portfolio(["A", "B"], vols)
    # B has lower vol, gets higher weight
    assert w["B"] > w["A"]
    assert w.sum() == 1.0


def test_compare_baselines():
    returns = pd.DataFrame(
        {
            "A": [0.01, -0.01, 0.02],
            "B": [0.02, 0.01, -0.01],
        }
    )
    yields = pd.Series({"A": 0.03, "B": 0.05})
    vols = pd.Series({"A": 0.15, "B": 0.20})
    result = compare_baselines(returns, yields, vols)
    assert "equal_weight" in result.columns
    assert "yield_weight" in result.columns
    assert "inverse_volatility" in result.columns
    assert len(result) == 3
