"# Technical Specification: Dividend Equity DSS

## 1. Data Schema Definitions

To ensure zero-gap integration, the system utilizes two primary data structures. All data must pass through a validation layer before being passed to the next stage.

### 1.1 Research Basket Schema (Input to Phase III)

**Purpose:** High-fidelity feature set for modeling.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `ticker` | `string` | Unique identifier (e.g., 'AAPL'). |
| `price_history` | `float[]` | Array of adjusted closing prices (Time Series). |
| `div_history` | `float[]` | Array of historical dividend payments. |
| `fcf_trend` | `float` | Calculated slope of Free Cash Flow over $N$ periods. |
| `payout_ratio` | `float` | (Dividends / FCF) - must be $< 1.0$ for safety. |
| `debt_to_equity` | `float` | Leverage metric for structural risk assessment. |
| `volatility_ann` | `float` | Annualized historical volatility (Standard Deviation). |

### 1.2 Worksheet Schema (Output of Phase III / Input to Phase IV)

**Purpose:** The actionable "Decision Support" dataset.

| Field Name | Data Type | Description |
| :--- | :--- | :--- |
| `ticker` | `string` | Unique identifier. |
| `expected_yield_mu` | `float` | The mean of the forecasted dividend distribution. |
| `yield_confidence` | `float` | The probability/variance of the dividend being met (Bayesian output). |
| `risk_weight` | `float` | The calculated Risk-Parity weight (Inverse Volatility). |
| `safety_score` | `float` | A composite score (0-1) based on FCF/Debt/Payout. |
| `regime_state` | `int` | Current detected Markov regime (e.g., 0=Expansion, 1=Contraction). |

---
## 2. Mathematical Logic Specifications

### 2.1 Risk-Parity Weighting (Inverse Volatility)

**Objective:** Ensure each asset contributes equally to the portfolio's total volatility.

**Formula:**

For a portfolio of $n$ assets, the weight $w_i$ for asset $i$ is calculated as:

$$w_i = \frac{\frac{1}{\sigma_i}}{\sum_{j=1}^{n} \frac{1}{\sigma_j}}$$

Where $\sigma_i$ is the annualized volatility of asset $i$.

**Implementation Constraint:** Weights must be normalized such that $\sum w_i = 1$.

### 2.2 Probabilistic Dividend Forecasting

**Objective:** Avoid overfitting by modeling the *distribution* of future dividends rather than a single point estimate.

**Approach: Bayesian Inference**

1.  **Prior:** Establish a prior distribution based on structural indicators (FCF growth, industry averages).
2.  **Likelihood:** Use historical dividend series to update the prior.
3.  **Posterior:** The resulting distribution provides both the **Mean ($\mu$)** (expected yield) and the **Uncertainty ($\sigma$)** (risk of a dividend cut).

**Monte Carlo Simulation:**

Run $1,000$ iterations of the posterior distribution to determine the "Value at Risk" (VaR) for the dividend cashflow.

---
## 3. Implementation Roadmap

### Step 1: Data Foundation (The "Screener" & "Research Basket")

*   Implement data ingestion for `price_history` and `div_history`.
*   Build the `StructuralFeatureEngine` to calculate FCF-based safety metrics.

### Step 2: The Modeling Engine (The "Worksheet")

*   Implement `RiskParityCalculator` class.
*   Implement `BayesianForecaster` class using `PyMC` or `scipy.stats`.

### Step 3: The Simulation/Dashboard (The "Shadow Rebalance")

*   Create a loop that simulates portfolio rebalancing using the `Worksheet` outputs.
*   Generate attribution reports comparing `expected_yield` vs `actual_yield`.

"""
import numpy as np

class RiskParityCalculator:
    """Implements Inverse Volatility Weighting."""

    @staticmethod
    def calculate_weights(volatilities: np.ndarray) -> np.ndarray:
        if len(volatilities) == 0:
            raise ValueError("Empty array")
        if np.any(volatilities <= 0):
            raise ValueError("Vols must be > 0")

        inverse_vols = 1.0 / volatilities
        return inverse_vols / np.sum(inverse_vols)

if __name__ == "__main__":
    # Simple Test
    vols = np.array([0.30, 0.15])
    weights = RiskParityCalculator.calculate_weights(vols)
    print(f"Vols: {vols} | Weights: {weights}")
    assert np.isclose(np.sum(weights), 1.0)
    print("Test Passed!")

