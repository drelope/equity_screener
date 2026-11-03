# UiWorkflowArchitecture_v3
## Dividend Equity CRISP-DM Platform

Version: 3.0

---

# Purpose

This document defines the implementation architecture for:

- Streamlit UI
- Agent orchestration
- Database persistence
- Workflow state management
- Deep linking
- Portfolio intelligence
- Research lifecycle management

The platform supports a closed-loop investment research process aligned with CRISP-DM:

```text
Business Understanding
        ↓
Data Understanding
        ↓
Data Validation
        ↓
Analysis
        ↓
Evaluation
        ↓
Recommendation
        ↓
Portfolio Decision
        ↓
Monitoring
        ↓
Feedback & Learning
```

---

# System Architecture

```text
                   ┌───────────────────┐
                   │ Streamlit UI      │
                   └─────────┬─────────┘
                             │
                             ▼

                   ┌───────────────────┐
                   │ Workflow Engine   │
                   └─────────┬─────────┘

     ┌───────────────────────┼────────────────────────┐
     ▼                       ▼                        ▼

Research Agents      Portfolio Agents         Monitoring Agents

     │                       │                        │
     └──────────────┬────────┴───────────────┬────────┘
                    ▼                        ▼

             Service Layer           Event Bus

                    ▼
             Repository Layer

                    ▼
                PostgreSQL
```

---

# Streamlit Application Structure

```text
src/

├── app.py

├── pages/
│
├── workspaces/
│
├── components/
│
├── services/
│
├── repositories/
│
├── agents/
│
├── workflows/
│
├── models/
│
├── database/
│
└── tests/
```

---

# Streamlit Page Mapping

## Dashboard

File

```text
pages/dashboard.py
```

Purpose

```text
Portfolio intelligence
Research intelligence
Monitoring alerts
```

Components

```text
CoverageMetrics
ConvictionMatrix
ResearchQueue
MonitoringAlerts
PortfolioSummary
```

---

## Screener

File

```text
pages/screener.py
```

Purpose

```text
Opportunity discovery
Ranking
Filtering
Prioritization
```

Components

```text
ScreenerFilters
ScreenerResults
RankingSummary
ComparisonActions
```

---

## Research Queue

File

```text
pages/research_queue.py
```

Purpose

```text
Manage active research pipeline
```

---

## Watchlist

File

```text
pages/watchlist.py
```

Purpose

```text
Monitor opportunities
```

---

## Portfolio

File

```text
pages/portfolio.py
```

Purpose

```text
Holdings
Exposure
Income forecasting
Risk metrics
```

---

# Security Workspace Mapping

## Workspace Root

```text
workspaces/security_workspace/page.py
```

Route

```text
/security/{ticker}
```

Tabs

```text
Overview
Financials
Dividends
Valuation
Quality
Analysis
Notes
Compare
Monitoring
History
```

---

# Component Ownership Matrix

| Component | Owner | Purpose |
|------------|---------|----------|
| Security Header | Workspace | Context |
| Metric Cards | Shared | KPIs |
| Progress Tracker | Analysis | Workflow |
| Thesis Panel | Analysis | Recommendation |
| Comparison Panel | Research | Relative Analysis |
| Monitoring Alerts | Monitoring | Thesis Health |
| Catalyst Tracker | Monitoring | Events |
| Conviction Matrix | Dashboard | Portfolio Intelligence |
| Research Queue | Dashboard | Prioritization |
| Portfolio Summary | Portfolio | Allocation |

---

# Agent Ownership Matrix

| Agent | Domain |
|---------|-----------|
| Objective Agent | Strategy |
| Screener Agent | Discovery |
| Prioritization Agent | Workflow |
| Validation Agent | Data |
| Research Agent | Data Collection |
| Quality Agent | Analysis |
| Financial Agent | Analysis |
| Dividend Agent | Analysis |
| Valuation Agent | Analysis |
| Risk Agent | Analysis |
| Comparison Agent | Research |
| Portfolio Fit Agent | Portfolio |
| Thesis Agent | Recommendation |
| Monitoring Agent | Lifecycle |
| Thesis Validation Agent | Learning |

---

# Agent-to-Database Mapping

## Objective Agent

Writes

```text
investment_profiles
```

Reads

```text
user_settings
```

---

## Screener Agent

Writes

```text
screening_results
```

Reads

```text
financial_metrics
dividend_metrics
```

---

## Quality Agent

Writes

```text
analysis_scores
```

Category

```text
quality
```

---

## Valuation Agent

Writes

```text
valuation_models
```

Stores

```text
fair_value
target_price
margin_of_safety
```

---

## Thesis Agent

Writes

```text
investment_theses
```

---

## Recommendation Agent

Writes

```text
recommendations
```

---

## Monitoring Agent

Writes

```text
monitoring_events
```

---

## Thesis Validation Agent

Writes

```text
thesis_outcomes
```

---

# PostgreSQL Schema

## securities

```sql
CREATE TABLE securities (
    id UUID PRIMARY KEY,
    ticker TEXT UNIQUE,
    company_name TEXT,
    sector TEXT,
    industry TEXT
);
```

---

## analysis_sessions

```sql
CREATE TABLE analysis_sessions (
    id UUID PRIMARY KEY,
    ticker TEXT,
    status TEXT,
    assigned_analyst TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

## analysis_scores

```sql
CREATE TABLE analysis_scores (
    id UUID PRIMARY KEY,
    analysis_id UUID,
    category TEXT,
    score NUMERIC,
    rationale TEXT
);
```

---

## investment_theses

```sql
CREATE TABLE investment_theses (
    id UUID PRIMARY KEY,
    analysis_id UUID,
    thesis TEXT,
    recommendation TEXT,
    confidence NUMERIC
);
```

---

## recommendations

```sql
CREATE TABLE recommendations (
    id UUID PRIMARY KEY,
    ticker TEXT,
    recommendation TEXT,
    confidence NUMERIC,
    approved BOOLEAN,
    approved_by TEXT
);
```

---

## investment_catalysts

```sql
CREATE TABLE investment_catalysts (
    id UUID PRIMARY KEY,
    ticker TEXT,
    description TEXT,
    expected_date DATE,
    impact_score NUMERIC,
    status TEXT
);
```

---

## monitoring_events

```sql
CREATE TABLE monitoring_events (
    id UUID PRIMARY KEY,
    ticker TEXT,
    event_type TEXT,
    event_date TIMESTAMP,
    event_payload JSONB
);
```

---

## thesis_outcomes

```sql
CREATE TABLE thesis_outcomes (
    id UUID PRIMARY KEY,
    thesis_id UUID,
    outcome TEXT,
    accuracy_score NUMERIC,
    evaluated_at TIMESTAMP
);
```

---

# Event-Driven Workflow

## Event Sources

```text
User
Agent
Database
External Market Data
Portfolio Events
```

---

## Event Types

```text
SecuritySelected
AnalysisStarted
AnalysisCompleted
RecommendationDrafted
RecommendationApproved
PortfolioAdded
MonitoringTriggered
ThesisValidated
```

---

# State Machine

```text
NEW

    ↓

PRIORITIZED

    ↓

DATA_VALIDATED

    ↓

IN_PROGRESS

    ↓

UNDER_REVIEW

    ↓

APPROVED

    ↓

PORTFOLIO_CANDIDATE

    ↓

MONITORING

    ↓

REVIEW_REQUIRED

    ↓

THESIS_VALIDATION

    ↓

ARCHIVED
```

---

# Event Processing

## Example

```text
Security Selected
    ↓
Create Analysis Session
    ↓
Launch Research Agents
    ↓
Aggregate Outputs
    ↓
Generate Thesis
    ↓
Request Approval
```

---

# Deep-Link Routing Specification

## Dashboard

```text
/dashboard
```

---

## Screener

```text
/screener
```

---

## Security Workspace

```text
/security/{ticker}
```

Example

```text
/security/MSFT
```

---

## Security Tabs

```text
/security/MSFT/overview

/security/MSFT/financials

/security/MSFT/dividends

/security/MSFT/valuation

/security/MSFT/quality

/security/MSFT/analysis

/security/MSFT/compare

/security/MSFT/history
```

---

## Analysis Detail

```text
/analysis/{analysis_id}
```

---

## Thesis Detail

```text
/thesis/{thesis_id}
```

---

# Session State Management

```python
st.session_state.current_ticker

st.session_state.current_analysis

st.session_state.workspace_tab

st.session_state.return_route

st.session_state.selected_comparison
```

---

# Multi-Agent Orchestration

## Research Pipeline

```text
Objective Agent
      ↓

Screener Agent
      ↓

Prioritization Agent
      ↓

Validation Agent
      ↓

Research Agent
```

---

## Analysis Pipeline

```text
Research Agent
       ↓

+----------------------+
| Parallel Execution   |
+----------------------+

Quality Agent
Financial Agent
Dividend Agent
Valuation Agent
Risk Agent

       ↓

Comparison Agent

       ↓

Portfolio Fit Agent

       ↓

Thesis Agent

       ↓

Recommendation Agent
```

---

# Sequence Diagram

```text
User
 │
 │ Select Security
 ▼

Security Workspace
 │
 ▼

Research Agent
 │
 ├────────► Quality Agent
 │
 ├────────► Financial Agent
 │
 ├────────► Dividend Agent
 │
 ├────────► Valuation Agent
 │
 └────────► Risk Agent

      ▼

Aggregate Results

      ▼

Comparison Agent

      ▼

Portfolio Fit Agent

      ▼

Thesis Agent

      ▼

Recommendation Agent

      ▼

Human Review

      ▼

Approved Recommendation
```

---

# Monitoring Sequence

```text
Market Event

      ▼

Monitoring Agent

      ▼

Score Impact

      ▼

Alert Generated

      ▼

Research Queue

      ▼

Analyst Review

      ▼

Thesis Validation

      ▼

Update Historical Accuracy
```

---

# Explainability Requirements

Every recommendation must contain:

```json
{
  "recommendation": "BUY",
  "confidence": 0.84,
  "drivers": [],
  "constraints": [],
  "evidence": [],
  "sources": []
}
```

---

# Future Roadmap

## V4

```text
Multi-user collaboration

Role-based permissions

Investment committee workflow

LLM-assisted thesis generation

Automated research packets

Agent memory framework

Vector search

Knowledge graph integration
```

---

# Architecture Goal

Create an institutional-grade investment intelligence platform that supports:

```text
Discover
Research
Analyze
Compare
Recommend
Approve
Monitor
Validate
Learn
Improve
```

through a fully traceable, auditable, event-driven research workflow.