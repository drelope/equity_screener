# ADR-0004: Shadow-First Deployment Strategy

**Status:** Adopted  
**Date:** 2024-10-12  
**Deciders:** Risk, Engineering, Investment Team  

## Context
Deploying automated trading strategies carries significant risk. Need validation before committing capital.

## Decision
All strategies must pass through shadow/paper trading before live deployment.

## Rationale
- **Risk Mitigation:** Catch bugs and model failures without capital at risk
- **Validation:** Real market conditions without execution risk
- **Attribution:** Understand decision drivers
- **Confidence Building:** Build track record before going live

## Implementation
- Shadow rebalance in controlled environment
- Compare shadow vs actual market
- Integrity guardrails and constraint checks
- Promotion criteria required before live (TBD)

## Consequences
- **Positive:** Safer deployment, better understanding
- **Negative:** Delayed live deployment, resource intensive
- **Mitigation:** Clear promotion criteria and timeline
