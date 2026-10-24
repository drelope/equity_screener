# Extended HF-Grade SKILL
**Hedge Fund Financial Analyst — Advanced Quantitative Framework**
> Version 1.0 | October 2026 | For use with Stock Screener Workflow

---

## Table of Contents
1. [Overview](#overview)
2. [Extended Metric Library](#extended-metric-library)
3. [Quantitative Scoring Engine](#quantitative-scoring-engine)
4. [Piotroski F-Score Framework](#piotroski-f-score-framework)
5. [Sharpe Proxy — Risk-Adjusted Return Signal](#sharpe-proxy--risk-adjusted-return-signal)
6. [Conviction Tier Methodology](#conviction-tier-methodology)
7. [Factor Weighting & Scenario Analysis](#factor-weighting--scenario-analysis)
8. [Long / Short Signal Rules](#long--short-signal-rules)
9. [Sector Rotation Analytics](#sector-rotation-analytics)
10. [Due Diligence Checklist Framework](#due-diligence-checklist-framework)
11. [AI Investment Memo — Structure & Standards](#ai-investment-memo--structure--standards)
12. [Institutional KPI Benchmarks](#institutional-kpi-benchmarks)
13. [Reporting & Communication Standards](#reporting--communication-standards)

---

## Overview

This skill document defines the complete analytical framework for a Hedge Fund Financial
Analyst operating at the institutional level. It extends the base stock screening workflow
with advanced quantitative techniques, qualitative research protocols, scenario analysis,
and standardized reporting formats aligned with buy-side best practices.

**Core Analytical Pillars:**
- **Quantitative Research** — Percentile-rank normalization, multi-factor scoring, F-Score computation
- **Fundamental Research** — Bottom-up company analysis using extended financial metrics
- **Risk Analysis** — Beta-adjusted return proxies, leverage assessments, scenario stress-testing
- **Reporting** — Investment memo writing, due diligence checklists, institutional KPI dashboards

---

## Extended Metric Library

Beyond standard screening metrics (P/E, ROE, Revenue Growth), the HF-Grade framework
incorporates six additional data points essential for institutional-quality analysis.

### 2.1 Return on Invested Capital (ROIC) %

| Attribute     | Detail                                                                              |
|---------------|-------------------------------------------------------------------------------------|
| **Formula**   | `NOPAT / Invested Capital × 100`                                                    |
| **Benchmark** | ≥ 10% = above estimated WACC; ≥ 20% = high-quality compounder                      |
| **Signal**    | Measures how efficiently capital is deployed — the primary test for economic moat   |
| **Usage**     | Compare ROIC vs. WACC spread; positive spread = value creation                     |
| **HF Relevance** | Core criterion for quality-factor scoring; separates durable earners from capital destroyers |

### 2.2 Gross Margin %

| Attribute     | Detail                                                                              |
|---------------|-------------------------------------------------------------------------------------|
| **Formula**   | `(Revenue − COGS) / Revenue × 100`                                                 |
| **Benchmark** | > 40% = strong pricing power; > 60% = software/platform business                   |
| **Signal**    | Structural indicator of competitive positioning and input cost resilience           |
| **Usage**     | Track trend over 3–5 years; declining gross margin = competitive pressure          |
| **HF Relevance** | Key input to Piotroski test #3; used in margin expansion thesis                |

### 2.3 Operating Margin %

| Attribute     | Detail                                                                              |
|---------------|-------------------------------------------------------------------------------------|
| **Formula**   | `Operating Income / Revenue × 100`                                                 |
| **Benchmark** | > 15% = operationally efficient; > 25% = best-in-class                             |
| **Signal**    | Reveals fixed-cost leverage and scalability of the business model                  |
| **Usage**     | Operating margin × Revenue Growth = earnings power trajectory                     |
| **HF Relevance** | Key input to Piotroski test #4; core to DCF terminal value assumptions         |

### 2.4 Current Ratio

| Attribute     | Detail                                                                              |
|---------------|-------------------------------------------------------------------------------------|
| **Formula**   | `Current Assets / Current Liabilities`                                             |
| **Benchmark** | > 1.0 = technically solvent; > 1.5 = comfortable liquidity buffer                  |
| **Signal**    | Short-term liquidity adequacy — critical under stress scenarios                    |
| **Usage**     | Combined with D/E and Interest Coverage to build a full balance sheet picture      |
| **HF Relevance** | Piotroski test #5; liquidity stress-test input in bear-case scenario          |

### 2.5 Interest Coverage Ratio

| Attribute     | Detail                                                                              |
|---------------|-------------------------------------------------------------------------------------|
| **Formula**   | `EBIT / Interest Expense`                                                          |
| **Benchmark** | > 3.0× = adequate; > 10× = conservatively financed                                 |
| **Signal**    | Debt servicing capacity under earnings compression                                 |
| **Usage**     | Stress-test: what multiple compression makes coverage < 1.0×?                     |
| **HF Relevance** | Piotroski test #6; essential for leveraged or high-yield name analysis        |

### 2.6 Free Cash Flow Growth YoY %

| Attribute     | Detail                                                                              |
|---------------|-------------------------------------------------------------------------------------|
| **Formula**   | `(FCF_current − FCF_prior) / \|FCF_prior\| × 100`                                 |
| **Benchmark** | > 10% = growing cash engine; > 30% = accelerating compounder                       |
| **Signal**    | Earnings quality check — FCF growth diverging from EPS growth signals accrual risk |
| **Usage**     | Compare FCF Growth vs. EPS Growth; gap > 20 pts warrants accounting scrutiny      |
| **HF Relevance** | Confirms sustainability of FCF Yield; used in bull-case DCF build-up          |

---

## Quantitative Scoring Engine

### 3.1 Percentile-Rank Normalization

All raw metrics are normalized on a 0–100 scale using cross-sectional percentile ranking
across the current stock universe. This eliminates scale bias and makes metrics comparable
regardless of unit.

