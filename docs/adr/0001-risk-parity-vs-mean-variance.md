# ADR-0001: Risk-Parity vs Mean-Variance Optimization

**Status:** Adopted  
**Date:** 2024-10-01  
**Deciders:** Investment Team, Data Engineering  

## Context
Portfolio construction needs to balance yield maximization with risk mitigation. Traditional mean-variance optimization is sensitive to covariance estimation errors, especially with limited history.

## Decision
Use Risk-Parity (inverse volatility weighting) as the primary allocation method.

## Rationale
- **Stability:** Less sensitive to estimation errors than full covariance optimization
- **Simplicity:** Inverse volatility is robust and interpretable
- **Risk Balance:** Ensures equal risk contribution across assets
- **Data Efficiency:** Works well with limited correlation history

## Implementation
- `src/crispdm/portfolio.py` - Risk parity calculations
- `TECHNICAL_SPEC.md` - Mathematical specification
- Weights normalized to sum to 1, volatilities must be > 0

## Consequences
- **Positive:** More robust allocations, easier to understand
- **Negative:** May not maximize risk-adjusted returns in all regimes, ignores correlations
- **Mitigation:** Can extend to risk-budgeting with correlations in future iterations
