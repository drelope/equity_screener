# Skill Design: `financial-analysis`

Status: verified
Owner: analysis
Risk: read
Source of truth: `skills/financial-analysis/SKILL.md`, `src/crispdm/scoring.py`,
`src/crispdm/portfolio.py`, `docs/AnalystDashboard.md`
Token budget: `SKILL.md <= 160 lines / 8,000 chars; each reference <= 260 lines / 12,000 chars`
Open questions: none

## Clarify

- **Problem:** the skill was 363 lines / 19.4k chars and mixed contract, KPI
  definitions, validation, risk, reporting and dashboard detail. It exceeded
  the token budget and was expensive to load for a single KPI question.
- **Decision supported:** validate an investment and interpret the composite
  and dashboard without changing score policy.
- **Audience:** analyst, PM and reviewer preparing an evidence-backed view.
- **In scope:** KPI/as-of interpretation, score/coverage explanation,
  investment validation, model-portfolio risk and the seven report tabs.
- **Out of scope:** weights/universe policy (`business-understanding`), score
  implementation (`financial-scoring`), worksheet/Final
  (`investment-analysis`), data acquisition/features/schema, ML gate, live
  trading.
- **Evidence:** `src/crispdm/scoring.py` defines `WEIGHTS` and the coverage
  floor; `src/crispdm/portfolio.py` defines return/risk/report calculations;
  `app/views/dashboard.py` defines the tabs; tests `test_portfolio.py`,
  `test_dashboard_view.py`, `test_requirements_weights.py` and
  `test_financial_analysis_skill.py` assert the contract.
- **Assumptions validated:** the seven tab names and weights were verified in
  code/tests on 2026-10-26; the partial `docs/FinancialAnalyst.md` is not
  authoritative.
- **Success criteria:** contract stays under budget; every refused scope has a
  handoff; the KPI, validation/risk and reporting detail remains available
  on demand; the seven tabs, weights and `0.50` floor remain discoverable.
- **Tool scope:** read-only, no tools.
- **Token budget:** 8,000 chars / 160 lines for `SKILL.md`; 12,000 chars / 260
  lines per reference.

## Design

- **Trigger:** dividend validation; KPI/score/rank/coverage interpretation;
  model-portfolio risk; dashboard/report preparation.
- **Non-trigger:** policy, scoring implementation, worksheet, pipelines, ML
  gate, live execution.
- **Inputs:** `model.features`, `model.scores`, `model.rankings`,
  `model.current_predictions`, `model.forward_returns`,
  `fundamentals.periodic_financials`, `analysis.investment_analyses`,
  dashboard docs.
- **Outputs:** evidence-attributed score/rank explanation, validated view,
  risk/sizing view, seven-tab dashboard and Markdown reports.
- **Read/write boundary:** read-only. Any write is handed to a write skill.
- **Handoffs:** `business-understanding`, `financial-scoring`,
  `investment-analysis`, `data-acquisition`, `data-transformation`,
  `data-storage-schema`, `observability-nightly-verification`,
  `modeling-evaluation`, `security-compliance`, `deployment-release`.
- **Failure modes:** stale as-of, coverage below `MIN_PRESENT_WEIGHT`, NULL
  component, unavailable metric, Draft presented as Final, weights disagree
  with code, LLM invents a number.
- **Reference plan:**
  - `references/kpi-library.md` — load when interpreting a KPI/component.
  - `references/validation-and-risk.md` — load for checklist/risk/sizing.
  - `references/reports-and-dashboard.md` — load for reports/tabs.
- **Verification:** `scripts.skill_audit --skill financial-analysis`, then the
  targeted pytest set in the skill.

## Plan

- **Files to add:** three references; this design record.
- **Files to modify:** `skills/financial-analysis/SKILL.md`;
  `tests/test_financial_analysis_skill.py`; routing/inventory docs.
- **Files to delete:** none.
- **Tests:** assert standard contract, boundaries, references, weights, floor
  and all seven tab names.
- **Rollback:** restore the previous `SKILL.md` and remove the references and
  design record; no data rollback.
- **Acceptance mapping:** every Clarify criterion maps to the audit or the
  targeted test set.

## Code

- **Files changed:** `skills/financial-analysis/SKILL.md` compressed;
  `references/kpi-library.md`, `references/validation-and-risk.md` and
  `references/reports-and-dashboard.md` added.
- **Tests added/changed:** `tests/test_financial_analysis_skill.py` updated for
  the standard sections and reference links.
- **Deviations:** none.

## Verify

- **Commands:** `python -m scripts.skill_audit --skill financial-analysis`;
  `python -m pytest -q tests/test_financial_analysis_skill.py
  tests/test_portfolio.py tests/test_dashboard_view.py
  tests/test_requirements_weights.py`; `ruff check .`; `ruff format --check .`.
- **Audit result:** `PASS` (0 findings) for the skill once this gate is `pass`.
- **Targeted test result:** 61 passed (`test_financial_analysis_skill.py`,
  `test_portfolio.py`, `test_dashboard_view.py`,
  `test_requirements_weights.py`).
- **Ruff result:** `ruff check .` and `ruff format --check .` exit 0.
- **Fixes applied during verification:** restated the five composite weights
  in `SKILL.md` (the test contract requires them), replaced the unknown
  `developing-with-streamlit` handoff with `deployment-release`, trimmed
  `SKILL.md` to 158 lines (< 160), formatted
  `tests/test_fundamentals_and_predictions.py`, and built the backtest
  artifacts (`python -m scripts.backtest`) that the dashboard
  "Under review" warning test requires.
- **Residual risks:** dashboard/report prose can drift from the app; the
  targeted tests and `docs/AnalystDashboard.md` remain the check. The
  dashboard render test needs a live database and the backtest artifacts.

## Gate log

| Phase | Result | Evidence |
|---|---|---|
| clarify | pass | Problem, boundary, evidence and success criteria recorded above |
| design | pass | Reference split and handoffs in this record |
| plan | pass | File/test/rollback list above |
| code | pass | `skills/financial-analysis/` and test update |
| verify | pass | Audit PASS; 61 targeted tests pass; ruff exit 0 |
