# ADR-0003: Markov Regime Switching for Adaptive Forecasting

**Status:** Adopted  
**Date:** 2024-10-10  
**Deciders:** Data Science, Investment Team  

## Context
Market and economic regimes change over time. Static models fail to adapt to transitions between bull/bear, expansion/recession states.

## Decision
Incorporate Markov regime switching models to detect and adapt to regime changes.

## Rationale
- **Adaptability:** Model parameters change based on detected regime
- **Risk Management:** Adjust position sizing/risk based on regime
- **Better Forecasts:** Regime-specific dynamics improve predictions
- **Economic Intuition:** Aligns with business cycle understanding

## Implementation
- Hidden Markov models for regime detection
- Regime-specific parameters for dividend forecasting
- Integration with Bayesian priors
- Regime state tracked in `model.features.regime_state`

## Consequences
- **Positive:** More robust across market cycles
- **Negative:** Complex, prone to regime misclassification
- **Mitigation:** Use probabilistic regime detection, monitor stability
