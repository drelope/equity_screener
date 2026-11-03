"""Deterministic portfolio mathematics for the dividend DSS."""

from __future__ import annotations

from typing import ClassVar

import numpy as np


class RiskParityCalculator:
    """Inverse-volatility risk-parity weights."""

    METHOD: ClassVar[str] = "inverse_volatility"

    @staticmethod
    def calculate_weights(volatilities: np.ndarray) -> np.ndarray:
        values = np.asarray(volatilities, dtype=float)
        if values.ndim != 1 or values.size == 0:
            raise ValueError("volatilities must be a non-empty one-dimensional array")
        if not bool(np.all(np.isfinite(values))) or bool(np.any(values <= 0.0)):
            raise ValueError("volatilities must be finite and positive")

        inverse_volatility = 1.0 / values
        return inverse_volatility / inverse_volatility.sum()
