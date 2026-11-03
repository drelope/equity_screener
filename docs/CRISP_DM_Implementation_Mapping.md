# CRISP-DM Implementation Mapping

This document maps the CRISP-DM phases in [CRISP_DM_Workflow.md](../CRISP_DM_Workflow.md) to concrete implementation artifacts in this repository.

## Phase 1: Business Understanding
| Task | Implementation | Notes |
| :--- | :--- | :--- |
| Universe Definition | [app/views/screener.py](../app/views/screener.py) | Dividend-paying securities filtered by criteria |
| Requirements & Constraints | [docs/requirements.md](requirements.md) | Acceptance criteria, weights, screening rules |
| Investment Thesis | [app/views/investment_analysis.py](../app/views/investment_analysis.py), [docs/InvestmentAnalysisWorkflow.md](InvestmentAnalysisWorkflow.md) | 18-step institutional workflow |
| Skill Support | [skills/business-understanding/](../skills/business-understanding/) | Business understanding skill procedures |

## Phase 2: Data Understanding
| Task | Implementation | Notes |
| :--- | :--- | :--- |
| Data Exploration | [app/views/data_explorer.py](../app/views/data_explorer.py) | Interactive data inspection |
| Data Quality Monitoring | [audit.data_quality](../sql/) | Populated by `scripts/run_full_etl` stage 9 |
| Pipeline Health | [app/views/health.py](../app/views/health.py), [audit.nightly_runs](../sql/) | Run history and health checks |
| Source Lineage | [audit.source_lineage](../sql/) | Provenance tracking |
| Skill Support | [skills/data-understanding/](../skills/data-understanding/), [skills/data-validation/](../skills/data-validation/) | Exploration and validation procedures |

## Phase 3: Data Preparation
| Task | Implementation | Notes |
| :--- | :--- | :--- |
| Orchestration | [scripts/run_full_etl.py](../scripts/run_full_etl.py) | Stages 0-10, pipeline lock, audit recording |
| Data Acquisition | Stages 0-5f | SEC, OpenBB, FMP, FRED ingestion |
| Normalization | [src/crispdm/etl.py](../src/crispdm/etl.py), [sql/](../sql/) | Schema transformations |
| Repairs | `repair_security_classification`, `repair_ticker_profile_sec_terms` | Preferred/common classification fixes |
| Feature Engineering | Stage 7, [src/crispdm/features.py](../src/crispdm/features.py) | FCF trends, ratios, volatility, etc. |
| Contract Terms | Stage 5b, [src/crispdm/](../src/crispdm/) | Preferred security terms mining |
| Skills | [skills/data-acquisition/](../skills/data-acquisition/), [skills/data-transformation/](../skills/data-transformation/), [skills/data-storage-schema/](../skills/data-storage-schema/) | Acquisition, transformation, schema management |

## Phase 4: Modeling
| Task | Implementation | Notes |
| :--- | :--- | :--- |
| Scoring & Ranking | Stage 8, [src/crispdm/model.py](../src/crispdm/model.py) | Rules-based scoring + rankings |
| Forward Returns | Stage 7b, [src/crispdm/features.py](../src/crispdm/features.py) | For evaluation/labeling |
| Labeling | Stage 10, [docs/model-labeling-plan.md](model-labeling-plan.md) | Target creation (post-12mo data) |
| Risk Models | [src/crispdm/portfolio.py](../src/crispdm/portfolio.py), [TECHNICAL_SPEC.md](../TECHNICAL_SPEC.md) | Risk-parity calculations |
| Skills | [skills/modeling-evaluation/](../skills/modeling-evaluation/), [skills/financial-scoring/](../skills/financial-scoring/) | Modeling and scoring procedures |

## Phase 5: Evaluation
| Task | Implementation | Notes |
| :--- | :--- | :--- |
| Backtesting | [src/crispdm/backtest.py](../src/crispdm/backtest.py) | Historical performance evaluation |
| Investment Analysis | [app/views/investment_analysis.py](../app/views/investment_analysis.py) | Thesis validation, scenarios, analogs (steps 14-15) |
| Analytics Store | [src/crispdm/analysis/](../src/crispdm/analysis/) | Analysis persistence |
| Skills | [skills/financial-analysis/](../skills/financial-analysis/), [skills/investment-analysis/](../skills/investment-analysis/) | Analysis and investment evaluation |

## Phase 6: Deployment, Monitoring & Governance
| Task | Implementation | Notes |
| :--- | :--- | :--- |
| Dashboard | [app/views/dashboard.py](../app/views/dashboard.py) | Performance monitoring, rankings |
| Operations Console | [app/views/operations.py](../app/views/operations.py) | Pipeline control, manual runs |
| Nightly Verification | [docs/nightly-verification.md](nightly-verification.md), [skills/observability-nightly-verification/](../skills/observability-nightly-verification/) | Daily checks |
| Agent Workflow | [SYSTEM.md](../SYSTEM.md), [scripts/agent_runner.py](../scripts/agent_runner.py), [skills/](../skills/) | Orchestration and governance |
| Deployment | [docs/deployment-runbook.md](deployment-runbook.md), [skills/deployment-release/](../skills/deployment-release/) | Release/rollback procedures |
| Security | [skills/security-compliance/](../skills/security-compliance/), [api/](../api/) | Auth, compliance checks |

## Validation Commands
```bash
# Pipeline health
python -m scripts.verify_nightly_run

# Schema safety
python -m scripts.migrate --check
python -m scripts.check_schema_drift --quiet

# Code quality
ruff check . && ruff format --check .
python -m pytest -q

# Skill audit
python -m scripts.skill_audit --all
```

## Quick Start (Following CRISP-DM)
1. **BU:** Review universe in Screener, define thesis in Investment Analysis
2. **DU:** Check Health/Dashboard for data freshness
3. **DP:** Run `python -m scripts.run_full_etl` (or via Operations)
4. **M:** Review scores/rankings in Dashboard
5. **E:** Validate thesis with Investment Analysis, backtest results
6. **Dep:** Monitor via Operations/Health, shadow before live deployment
