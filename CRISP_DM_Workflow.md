# CRISP-DM Workflow: Dividend Equity Decision Support System (DSS)

## 1. Business Understanding
**Objective:** Define investment constraints, success criteria, and establish the universe of tradable assets aligned to a dual objective.

### 1.1 Goals
- **Primary:** Maximize sustainable cashflow (dividend yield adjusted for sustainability)
- **Secondary:** Mitigate portfolio risk (volatility, drawdown, correlation)

### 1.2 Success Criteria & Metrics (SMART)
| Metric | Target | Measurement | Notes |
| :--- | :--- | :--- | :--- |
| **Dividend Sustainability** | Payout ratio < 1.0 (FCF basis) | Per security in Research Basket | Hard filter via structural modeling |
| **Risk-Adjusted Cashflow** | > benchmark Sharpe/Sortino | vs. dividend aristocrats/index baseline | Must outperform naive strategies |
| **Max Drawdown** | < benchmark max drawdown | Rolling 12-36 month window | Portfolio-level constraint |
| **Cashflow Stability** | High probability of dividend coverage | Bayesian posterior coverage probability | From Phase 4 forecasting |
| **Data Freshness** | < 24h for key sources | Tracked via `audit.nightly_runs` | Enforced by nightly pipeline |

### 1.3 Constraints
- **Universe:** Dividend-paying equities meeting liquidity/coverage criteria (see `scripts/run_full_etl` stages 0-1)
- **Risk Tolerance:** Max drawdown and volatility limits (configurable)
- **Capital Allocation:** Risk-parity approach with constraint optimization
- **Governance:** Follow `docs/requirements.md` acceptance criteria

### 1.4 Stakeholders & Ownership
- **Data Engineering:** Pipeline operations (`skills/data-*`)
- **Investment Analysis:** Thesis generation (`app/views/investment_analysis.py`, `skills/investment-analysis`)
- **Risk/Compliance:** Guardrails (`skills/security-compliance`)
- **Operations:** Monitoring (`skills/observability-nightly-verification`)

---

## 2. Data Understanding
**Objective:** Assess data quality, coverage, freshness, and identify gaps before preparation.

### 2.1 Data Sources
| Source | Purpose | Pipeline Stage | Notes |
| :--- | :--- | :--- | :--- |
| **SEC EDGAR/XBRL** | Company facts, filings, fundamentals | `scripts/run_full_etl` stages 4a-6 | Point-in-time, preferred/common handling |
| **OpenBB/FMP/FRED** | Market data, ratios, macro inputs | Stages 2, 5e-5f | Real-time supplement, stored in `raw.*` |
| **Internal Warehouse** | Normalized features, scores, rankings | Stages 6-9, `model.*`, `clean.*` | Single source of truth |

### 2.2 Quality Assessment
- **Coverage:** Track active dividend payers vs universe (see `audit.nightly_runs.row_counts`)
- **Freshness:** Monitor last update times per source
- **Completeness:** Missingness reports for critical fields (FCF, debt/equity, payout)
- **Corporate Actions:** Splits/dividends/ticker changes handled in reference tables
- **Survivorship/Delistings:** Tracked via `reference.securities.active` flag
- **Preferred vs Common:** Special handling (stages 1a-1b, 5b, repairs)

### 2.3 Data Understanding Artifacts
- **Lineage:** `audit.source_lineage` tracks data provenance
- **Quality:** `audit.data_quality` captures validation results
- **Runs:** `audit.nightly_runs` records pipeline execution and metrics

---

## 3. Data Preparation
**Objective:** Transform raw data into high-fidelity, point-in-time correct features for modeling.

### 3.1 Cleaning & Integration
- **Schema Integrity:** Handoff protocols between Screener and Research Basket with validation
- **Point-in-Time Correctness:** Use as-of dates to prevent lookahead bias
- **Ticker Normalization:** Handle corporate actions, preferred securities, ticker changes
- **Data Repair:** Automated repairs (classification, SEC terms) before modeling

### 3.2 Feature Engineering
| Feature | Calculation | Purpose |
| :--- | :--- | :--- |
| **FCF Trend** | Slope of Free Cash Flow over N periods | Dividend source sustainability |
| **Payout Ratio** | Dividends / FCF (must be < 1.0) | Margin of safety |
| **Debt/Equity** | Leverage metrics | Structural risk assessment |
| **Volatility (Ann.)** | Historical std dev, annualized | Risk-parity weighting |
| **Price/Div History** | Time series arrays | Forecasting inputs |
| **Macro Regime Features** | Economic/credit cycle indicators | Regime detection context |

**Implementation:** `src/crispdm/features.py`, built via `scripts/run_full_etl` stage 7 (incremental, last `--feature-days`).

---

## 4. Modeling
**Objective:** Apply advanced mathematical models with rigorous validation to generate actionable signals.

### 4.1 Dividend Forecasting (Probabilistic)
- **Approach:** Bayesian inference with structural priors (FCF growth, industry)
- **Posterior:** Mean ($\mu$) and uncertainty ($\sigma$) for dividend distributions
- **Simulation:** Monte Carlo ($\geq$1000 iterations) for VaR on cashflows
- **Regime Awareness:** Markov regime switching to adapt to economic states

### 4.2 Portfolio Construction (Risk-Parity)
- **Weighting:** Inverse volatility $w_i = \frac{1/\sigma_i}{\sum 1/\sigma_j}$, normalized to sum to 1
- **Constraints:** Respect risk limits, diversification, liquidity
- **Optimization:** Solve dual objective (cashflow + risk mitigation)

### 4.3 Validation & Evaluation Plan
| Validation | Method | Purpose |
| :--- | :--- | :--- |
| **Baselines** | Equal-weight, yield-weight, price-vol inverse-vol | Prove value-add over naive strategies |
| **Time-Based Split** | Walk-forward (expanding/rolling window) | Mimic real deployment, avoid leakage |
| **Purging/Embargo** | Remove overlapping labels | Prevent label leakage in time series |
| **Hold-Out** | Out-of-sample period | Unbiased performance estimate |
| **Stability Checks** | Regime stability, prior sensitivity | Model robustness |
| **Leakage Audit** | Point-in-time verification | Ensure no future data used |

**Artifacts:** `model.forward_returns`, `model.predictions`, `model.features.target_sustainable_dividend` (stage 10 labeling).

---

## 5. Evaluation
**Objective:** Rigorously assess model performance against business objectives and baselines.

### 5.1 Performance Metrics
| Category | Metrics | Target |
| :--- | :--- | :--- |
| **Forecast Accuracy** | MAE/RMSE on dividend forecasts, coverage probability | Within acceptable error bands |
| **Risk Metrics** | Volatility, max drawdown, Sharpe, Sortino, VaR | Meet risk constraints |
| **Business Impact** | Sustainable cashflow yield, risk-adjusted return vs baseline | Outperform benchmarks |
| **Attribution** | Factor/risk decomposition of returns | Understand driver contributions |

### 5.2 Evaluation Process
- **Compare to Baselines:** All models vs naive strategies
- **Economic Significance:** Not just statistical, but business value
- **Regime Analysis:** Performance across different market regimes
- **Error Analysis:** Investigate forecast misses and regime detection failures
- **Feedback Loop:** Feed insights back to Business Understanding for iteration

---

## 6. Deployment, Monitoring & Governance
**Objective:** Safely deploy via shadow execution, monitor performance, and maintain governance.

### 6.1 Deployment Strategy
- **Shadow Rebalancing:** Paper trading against live data before capital commitment (`Phase IV`)
- **Attribution Analysis:** Decompose decisions and outcomes
- **Integrity Guardrails:** Automated constraint checks
- **Promotion Criteria:** Define gates before moving from shadow to live (TBD)

### 6.2 Monitoring & Observability
| Area | Tool/Location | Purpose |
| :--- | :--- | :--- |
| **Pipeline Health** | `audit.nightly_runs`, `skills/observability-nightly-verification` | Track ETL success, freshness, row counts |
| **Data Quality** | `audit.data_quality`, `scripts/verify_nightly_run` | Detect anomalies and schema drift |
| **Model Performance** | `model.scores`, `model.predictions`, Dashboard | Monitor drift, forecast errors |
| **Operations** | `app/views/operations.py`, `app/views/health.py` | Operator console and alerts |
| **Migrations** | `python -m scripts.migrate --check` | Schema safety (enforced by gates) |

### 6.3 Governance & SDLC Gates
| Gate | Command/Check | When |
| :--- | :--- | :--- |
| **Pre-commit/Lint** | `ruff check . && ruff format --check .` | All code changes |
| **Tests** | `python -m pytest -q` | All code changes |
| **Schema Safety** | `python -m scripts.migrate --check` | Before schema writes |
| **Schema Drift** | `python -m scripts.check_schema_drift --quiet` | CI/verification |
| **Skill Audit** | `python -m scripts.skill_audit --all` | Skill/workflow changes |
| **Security** | `skills/security-compliance` checks | Secrets, keys, access control |

### 6.4 Resiliency
- **Pipeline Lock:** Advisory lock prevents concurrent ETL runs
- **Idempotency:** All stages use upserts, safe to re-run
- **Rollback:** Documented in `docs/deployment-runbook.md`
- **Incident Response:** Follow `docs/nightly-verification.md` procedures
- **Secrets Management:** Never commit secrets; use env vars (see README/compose)

---

## 7. Mathematical Frameworks (Reference)
| Component | Method | Purpose |
| :--- | :--- | :--- |
| **Weighting** | Risk-Parity (Inverse Volatility) | Equalize risk contribution across portfolio |
| **Forecasting** | Bayesian Inference + Monte Carlo | Probabilistic distributions vs point estimates |
| **Regime Detection** | Markov Switching Models | Adapt to changing economic/market states |
| **Sustainability** | Structural/Causal Modeling | Link dividend security to FCF and balance sheet health |

---

## 8. System Integration Map
| CRISP-DM Phase | Implementation | Key Artifacts |
| :--- | :--- | :--- |
| **1. Business Understanding** | Screener, requirements, constraints | `docs/requirements.md`, `app/views/screener.py` |
| **2. Data Understanding** | Data exploration, quality checks | `app/views/data_explorer.py`, `audit.*` tables |
| **3. Data Preparation** | ETL pipeline | `scripts/run_full_etl.py` (stages 0-7), `src/crispdm/features.py` |
| **4. Modeling** | Scoring, forecasting, optimization | `src/crispdm/model.py`, `model.*` schema, `skills/modeling-evaluation` |
| **5. Evaluation** | Backtesting, attribution | `src/crispdm/backtest.py`, `model.forward_returns`, `app/views/investment_analysis.py` |
| **6. Deployment** | Shadow, monitoring, operations | `app/views/operations.py`, `app/views/dashboard.py`, `skills/observability-nightly-verification` |

**Governance:** All work follows `SYSTEM.md` precedence and `skills/` workflow with deterministic execution via `scripts/agent_runner.py`.

### 6.5 Architecture Decision Records (ADRs)
Key decisions should be documented in `docs/` as ADRs:
| Decision | Rationale | Status |
| :--- | :--- | :--- |
| **Risk-Parity vs Mean-Variance** | More stable with limited data, avoids covariance estimation pitfalls | Adopted |
| **Bayesian vs Point Forecasts** | Captures uncertainty, enables probabilistic risk management | Adopted |
| **Markov Regime Switching** | Adapts to changing economic states | Adopted |
| **Shadow-first Deployment** | Validate before capital commitment, minimize risk | Adopted |

### 6.6 Model & Data Versioning
- **Code:** Git version control
- **Features:** Feature set hash tracked per run
- **Models:** Config/priors versioned; predictions tagged with model version
- **Data:** Point-in-time via as-of dates, lineage in `audit.source_lineage`
- **Experiments:** Track in artifacts or experiment store as needed
