# ADR-0005: Point-in-Time Data Requirements

**Status:** Adopted  
**Date:** 2024-10-15  
**Deciders:** Data Engineering, Compliance  

## Context
Using future information (lookahead bias) invalidates backtests and creates false confidence.

## Decision
All features and labels must be computed using only information available as of the decision date.

## Rationale
- **Validity:** Ensures realistic backtest results
- **Compliance:** Avoids lookahead bias
- **Trust:** Credible performance estimates
- **Safety:** Prevents overfitting to future data

## Implementation
- As-of dates on all features (`model.features.as_of_date`)
- Point-in-time fundamentals
- Proper handling of restatements
- Walk-forward validation with purging/embargo
- Leakage checks in validation framework

## Consequences
- **Positive:** Honest performance measurement
- **Negative:** More complex data pipeline, some data unavailable
- **Mitigation:** Careful data sourcing and lineage tracking
