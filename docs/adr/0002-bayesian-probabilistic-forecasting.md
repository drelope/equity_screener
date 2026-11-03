# ADR-0002: Bayesian Probabilistic vs Point Forecasting

**Status:** Adopted  
**Date:** 2024-10-05  
**Deciders:** Data Science, Investment Team  

## Context
Dividend forecasting needs to account for uncertainty, especially for sustainability assessment. Point estimates ignore the risk of dividend cuts.

## Decision
Use Bayesian inference with Monte Carlo simulation to produce probabilistic dividend forecasts.

## Rationale
- **Uncertainty Quantification:** Captures forecast confidence
- **Prior Integration:** Incorporates fundamental knowledge (FCF, payout ratios)
- **Risk Management:** Enables VaR-style analysis for cashflows
- **Robustness:** Better handles regime changes

## Implementation
- Bayesian updating with structural priors
- Monte Carlo simulation (≥1000 iterations)
- Posterior distributions yield mean and uncertainty
- Integration with Markov regime switching

## Consequences
- **Positive:** Better risk-adjusted decision making, explicit uncertainty
- **Negative:** More complex, computationally intensive
- **Mitigation:** Use efficient implementations, clear documentation
