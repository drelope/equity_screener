"""Tests for the deterministic risk-parity calculator."""

import numpy as np
import pytest

from src.math_engine import RiskParityCalculator


def test_risk_parity_weights_are_inverse_volatility_and_normalized():
    weights = RiskParityCalculator.calculate_weights(np.array([0.10, 0.20, 0.30]))

    inverse_volatility = np.array([10.0, 5.0, 3.3333333333333335])
    expected = inverse_volatility / inverse_volatility.sum()

    assert weights.sum() == pytest.approx(1.0)
    np.testing.assert_allclose(weights, expected)


def test_risk_parity_weights_prefer_lower_volatility():
    diversified = RiskParityCalculator.calculate_weights(np.array([0.20, 0.20]))
    concentrated = RiskParityCalculator.calculate_weights(np.array([0.10, 0.30]))

    assert diversified[0] == pytest.approx(0.5)
    assert concentrated[0] > concentrated[1]


def test_risk_parity_weights_reject_invalid_volatility_series():
    with pytest.raises(ValueError, match="non-empty"):
        RiskParityCalculator.calculate_weights(np.array([]))

    with pytest.raises(ValueError, match="finite and positive"):
        RiskParityCalculator.calculate_weights(np.array([0.20, 0.0]))
