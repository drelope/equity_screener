---
name: financial-analysis
description: "Use when validating a dividend investment, interpreting KPIs, scores, rankings or coverage, assessing model-portfolio risk, or preparing the 7-tab analyst dashboard and its reports. Do not use for score policy, the worksheet, data pipelines, or the ML gate."
version: 1
risk: read
owner: analysis
entrypoint: none
tools: []
tags: [analysis, kpi, risk, reporting, dashboard, lifecycle]
---

# Financial Analysis

Turn point-in-time KPIs, the rule-based score and portfolio risk into an
evidence-backed investment view. This is the analyst-facing layer; it does not
change the score and does not write the warehouse.

## When to use / when not to use

Use when:

- validating a dividend candidate or explaining a score, rank or coverage move;
- interpreting a KPI, component percentile, risk figure or dashboard tab;
- preparing a morning note, performance report, risk report, IC memo or
  research note;
- checking whether a recommendation has the evidence and risk work it needs.

Do not use when:

- changing weights, the composite, rankings or thresholds
  (`business-understanding` decides policy; `financial-scoring` implements it);
- filling or saving the 18-step worksheet (`investment-analysis`);
- acquiring data, building features or changing schema;
- evaluating the ML model (`modeling-evaluation`);
- executing trades, sizing a live book or assuming financing/costs.

## Runner

- **Mode:** Manual only. There is no executable entrypoint.
- **Confirmation:** `risk: read`; any warehouse write is handed to a write skill.

## Preflight

- [ ] Read `SYSTEM.md` and confirm this skill owns the task.
- [ ] `git status --short` reviewed.
- [ ] Confirm the as-of date, universe, benchmark and data freshness.
- [ ] Confirm no score/weight change is hidden inside an analysis request.
- [ ] Do not read `.env`; check env names only.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Table | `model.features` | yes | Point-in-time KPI inputs. |
| Table | `model.scores`, `model.rankings` | yes | Composite, coverage and rank. |
| Table | `model.current_predictions`, `model.forward_returns` | no | Rank and base-rate context. |
| Table | `fundamentals.periodic_financials` | no | F-Score and reported fundamentals. |
| Table | `analysis.investment_analyses` | no | Final/Draft worksheets. |
| Doc | `docs/AnalystDashboard.md`, `docs/InvestmentAnalysisWorkflow.md` | yes | Dashboard and Final gate. |

## Procedure

1. Run the preflight.
2. Frame the question: security or model portfolio, decision, horizon and
   as-of date. Name the universe and benchmark.
3. Load point-in-time evidence and record coverage/freshness. Stop if the
   as-of date is stale or the security is below the score floor.
4. Decompose the composite into its five components; state each weight and
   coverage. Explain a score move as a component and universe move, not a
   forecast.
5. Work the validation checklist and risk decomposition. Label every item
   observed, derived, inferred or unavailable.
6. Form the view: variant perception, scenarios, base rate, catalysts and kill
   switch. Do not record a call while any is missing.
7. Write the report in the standard structure. Use the dashboard for
   quantitative tables and the worksheet for the qualitative record.
8. Attach sources, as-of dates, confidence reasons and open questions.
9. Hand off policy to `business-understanding`, scoring to
   `financial-scoring`, and worksheet/Final to `investment-analysis`.

`MIN_PRESENT_WEIGHT` is 0.50. The regime layer only changes the blend after a
security clears that floor. `model.predictions` is a relative rank, never a
calibrated probability.

## Outputs

- A score/rank/coverage explanation and a validated view with scenarios, risk
  and kill switch.
- The seven tabs: **Portfolio Dashboard**, **Performance Analytics**,
  **Risk Monitor**, **Position Book**, **Factor Attribution**,
  **Research Pipeline** and **Reports Center**.
- No warehouse writes; a Final call is saved through `investment-analysis`.

## Verification

Pass when:

- `tests/test_financial_analysis_skill.py` confirms the contract and tabs.
- Portfolio, dashboard and requirements-weight tests pass.
- Every metric has a source/as-of; the composite is never called a probability.

```bash
python -m scripts.skill_audit --skill financial-analysis
python -m pytest -q tests/test_financial_analysis_skill.py tests/test_portfolio.py \
  tests/test_dashboard_view.py tests/test_requirements_weights.py
```

## Failure handling

- Stale or missing as-of data: stop and report the latest date.
- Coverage below `MIN_PRESENT_WEIGHT`: do not score or rank the security.
- All-NULL component: report the upstream gap; never substitute zero.
- Unavailable metric: show N/A and the reason; never infer it from peers.
- No Final worksheet: no IC memo; show Draft or "no call".
- Weights disagree with code: code wins; route the docs fix to `business-understanding`.
- The local LLM returns a number or recommendation: discard it.

## Handoffs

- **Policy:** route to `business-understanding` with the proposed rule.
- **Scoring:** route to `financial-scoring` with the approved decision.
- **Worksheet:** route to `investment-analysis` for the Final gate.
- **Source data:** route to `data-acquisition` with the coverage gap.
- **Features:** route to `data-transformation` with the defect.
- **Schema:** route to `data-storage-schema` with the drift output.
- **Health:** route to `observability-nightly-verification`.
- **ML gate:** route to `modeling-evaluation`.
- **Security:** route to `security-compliance`.
- **Dashboard UI:** route to `developing-with-streamlit`; release via
  `deployment-release`.

## Stop conditions

- [ ] Task is outside this skill's scope.
- [ ] A quantitative claim has no relation, filter or as-of.
- [ ] A score/rank is requested below `MIN_PRESENT_WEIGHT`.
- [ ] A recommendation lacks risk, sizing and a kill switch.
- [ ] A Draft is presented as an IC memo or Final call.
- [ ] The model portfolio is presented as live or cost-free.
- [ ] A weight/universe change is requested inside this skill.
- [ ] A secret would be printed, logged or committed.
- [ ] Unexpected `git status` changes appear in the scoped area.

## Evidence required

- **Commands:** argv, cwd, exit codes and timestamps.
- **State:** tables/rows read and the as-of date.
- **Findings:** relation/filter/as-of; component and coverage attribution.
- **Reports:** type, artifact path, source and caveats shown.

## Source of truth

- `src/crispdm/scoring.py`, `src/crispdm/regime.py`, `src/crispdm/returns.py`
- `src/crispdm/portfolio.py`, `app/views/dashboard.py`, `app/analysis_schema.py`
- `docs/AnalystDashboard.md`, `docs/InvestmentAnalysisWorkflow.md`
- `docs/requirements.md`, `docs/FinancialAnalyst.md` (partial reference only)

## References

- [KPI library](references/kpi-library.md) — load for a KPI or component.
- [Validation and risk](references/validation-and-risk.md) — load for risk or sizing.
- [Reports and dashboard](references/reports-and-dashboard.md) — load for a report or tab.

## Context budget

- Always load this file, the design record and the as-of evidence; otherwise load only the named reference.
