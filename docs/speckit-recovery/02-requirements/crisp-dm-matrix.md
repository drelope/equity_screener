# CRISP-DM Recovery Matrix

| Field | Value |
|---|---|
| Stage | 2 — Requirements recovery and CRISP-DM mapping |
| Inputs | Stage 0 discovery; Stage 1A–1D audits; `requirements.md` |
| Maturity scale | 1 ad hoc; 2 documented but manual; 3 repeatable with material gaps; 4 managed and measured; 5 optimized and continuously verified |
| Evidence rule | Every maturity score is tied to requirement IDs and source audit IDs; no score is based on documentation claims alone |

## 1. Phase Summary

| Phase | Code | Primary workflows | Maturity | Main risk |
|---|---|---|---|---|
| Business Understanding | Capability inventory; analyst worksheet; report set; docs | Nightly research cycle; analyst review; 18-section worksheet | 3 | Documentation overstates architecture; no product brief |
| Data Understanding | SEC/OpenBB/FMP/Polygon/FRED clients; profiles; macro memo | Provider fetch; profiling; exploratory API/UI | 3 | Provider coverage and licensing Unknown; current-state profiles |
| Data Preparation | Loaders, schema, migrations, features, labels | Nightly ETL; feature rebuild; label rebuild; audit population | 3 | PIT, split and dividend overwrite gaps |
| Modeling | Rule scoring, logistic walk-forward, regime, analogs | Score/rank; walk-forward; gate; portfolio selection | 3 | Acceptance policy reused; placeholders; score immutability |
| Evaluation | Backtest, metrics, gate, nightly verification, audit | Walk-forward; gate; backtest artifacts; nightly checks | 2 | No costs, stale artifacts, unmatched benchmark, no holdout |
| Deployment | FastAPI, Streamlit, ops worker, systemd/Airflow, Docker | Serve, schedule, operate, report, draft | 3 | No lockfile, no run manifests, failed nightly runs, no CD |

Average maturity is 2.83 of 5. Evaluation is the weakest phase; Business Understanding, Data Understanding, Data Preparation, Modeling and Deployment each score 3 because the workflow is repeatable but not fully controlled.

## 2. Business Understanding

**Recovered intent.** Build a dividend-equity research and portfolio platform that ranks payers by income, sustainability, appreciation, risk and valuation; supports analyst research through a worksheet and reports; and gates any ML promotion through walk-forward evidence.

| Code | Workflows | Gaps | Undocumented assumptions | Maturity | Risks |
|---|---|---|---|---|---|
| `src/crispdm/scoring.py`; `app/views/investment_analysis.py`; `app/views/dashboard.py`; `docs/AnalystDashboard.md` | Nightly ETL → scores → book → dashboard; analyst 18-section worksheet; five Reports Center reports | No product brief; no explicit scope for watchlist, alerts or text intelligence; README claims dbt, Bayesian and multi-agent designs that are absent | The five factor weights are the intended product definition; “sustainable dividend” means a 365-day forward payment label; the worksheet is the primary analyst workflow | **3** | CAP-F10, CMP-F16, BI-36, CAP-13, CAP-15 |

**Requirements:** BG-01, BG-05, BG-06, BG-08; FR-SIG-01, FR-PORT-01, FR-REP-01, FR-AI-01, FR-AI-03; NFR-GOV-03.

**Key finding.** The code defines a coherent research product, but the documentation describes a broader target architecture than the repository implements. Stage 3 should record the implemented scope and mark aspirational capabilities separately.

## 3. Data Understanding

**Recovered intent.** Assemble a multi-provider dividend and fundamentals warehouse covering SEC filings, prices, dividends, splits, macro series and profiles, with enough breadth to rank roughly 5,000 scored securities.

| Code | Workflows | Gaps | Undocumented assumptions | Maturity | Risks |
|---|---|---|---|---|---|
| `sec_client.py`; `openbb_client.py`; `populate_*.py`; `raw.*`; `reference.*`; `audit.source_freshness` | SEC bulk/API ingestion; OpenBB/yfinance prices; FMP/Polygon dividend reconciliation; FRED/ALFRED vintages; profile and listing enrichment | Current-state universe; stale warehouse since 2026-11-09; provider provenance collapsed to OPENBB for prices; no license inventory; 354 unresolved dividend verdicts | SEC companyfacts carries enough vintage data to rebuild some PIT facts (unverified); Yahoo dividends are already split-adjusted (0.6); stored closes are on the provider split basis | **3** | BI-01, DF-F02, DF-F06, DF-F07, DF-F08, DF-F17, SVC-F04, NFR-GOV-03 |

**Requirements:** FR-DIV-01, FR-DIV-02, FR-DIV-07, FR-MACRO-01, FR-UNI-01, NFR-PIT-02, NFR-GOV-02.

**Key finding.** Data breadth is a real strength: 9.8 million prices, 323,632 dividend rows and 105,865 macro vintages. Data understanding is still current-state, not point-in-time, and price provenance is thinner than dividend provenance.

## 4. Data Preparation

**Recovered intent.** Convert raw provider payloads into dated features, forward returns and labels that can be used by a walk-forward model, while retaining audit, quarantine and freshness evidence.

| Code | Workflows | Gaps | Undocumented assumptions | Maturity | Risks |
|---|---|---|---|---|---|
| `features.py`; `returns.py`; `label_targets.py`; `populate_dividend_data.py`; `sql/schema.sql`; `sql/migrations/` | Nightly loaders; feature rebuild; 252-row forward returns; 365-day labels; audit population; migration ledger | SEC dividends available at period end; availability clamp; arbitrary vintage tie-break; full-history price median; NULL date overwrite; label rebuild erases history; SEC payloads latest-only | Stored raw close is split-adjusted (Unknown); Yahoo basis is already adjusted (0.6); OPENBB annual dividend and SEC EPS share a per-share basis (Unknown) | **3** | BI-02, BI-10, BI-32, PA-D06, PA-F04, DA-03, DA-05, DA-07, DA-16 |

**Requirements:** FR-ADJ-01..04, FR-DIV-03..08, FR-FEAT-01..04, FR-LABEL-01..03, FR-TR-01..03, NFR-PIT-01..04, NFR-DET-01..04, NFR-AUD-02.

**Key finding.** Data Preparation is the largest source of risk. The mechanism is repeatable, but the same as-of date can produce different features after a provider refresh or code change, and past labels and scores are not addressable.

## 5. Modeling

**Recovered intent.** Produce a transparent rule-based composite score for production ranking and a gated logistic-regression walk-forward model for research, with optional regime and analog overlays.

| Code | Workflows | Gaps | Undocumented assumptions | Maturity | Risks |
|---|---|---|---|---|---|
| `scoring.py`; `model.py`; `regime.py`; `regime_pipeline.py`; `analogs.py`; `math_engine.py` | Score/rank; five-factor blend; coverage floor; logistic walk-forward with purge; regime overlay; peer base rates; portfolio weights | Score history mutable; no score run id or feature hash; prediction run identity exists but is not used by backtest; regime advisory; risk-parity path uses risk_score; placeholders in ML features | The rule score, not the ML model, is the production signal; regime overlay is intentionally off by default; peer industry is current-state | **3** | DA-02, DA-12, CMP-F03, CMP-F06, PA-P03, BI-18, CAP-22 |

**Requirements:** FR-SIG-01..04, FR-LABEL-01..03, FR-PORT-02, NFR-REPRO-04.

**Key finding.** Production scoring is deliberate and explainable. Modeling maturity is held back by mutable score storage and by the fact that the ML path's provenance is better than the production score's provenance.

## 6. Evaluation

**Recovered intent.** Evaluate the strategy monthly with walk-forward folds, a purge equal to the label horizon, a documented acceptance gate and an audit trail of model runs.

| Code | Workflows | Gaps | Undocumented assumptions | Maturity | Risks |
|---|---|---|---|---|---|
| `backtest.py`; `evaluate_walk_forward.py`; `verify_nightly_run.py`; `audit.model_runs`; `artifacts/backtests/` | Monthly walk-forward; fold metrics; gate; checkpoint; nightly verification; dashboard artifact scan | 14-day post-formation cleaning; no costs; unmatched benchmark; shared holdout; no frozen policy; stale thin_v6 artifact; checkpoints overwritten; no manifest | The latest artifact is assumed reproducible; the canonical checkpoint is assumed to represent the current policy; execution at the formation close is assumed | **2** | BI-03, BI-05, BI-06, BI-08, BI-21, DA-09, DA-10, DA-18 |

**Requirements:** FR-EVAL-01..05, FR-BT-01..05, FR-TR-04, NFR-PIT-01, NFR-GOV-01, NFR-REPRO-03, NFR-REPRO-04.

**Key finding.** Evaluation is the weakest phase. The walk-forward mechanics are sound, but the promotion evidence is not reproducible and the benchmark does not match the book's exposure.

## 7. Deployment

**Recovered intent.** Run a nightly ETL, serve a read API and analyst UI, expose an allowlisted ops plane and produce deterministic reports and optional AI drafts.

| Code | Workflows | Gaps | Undocumented assumptions | Maturity | Risks |
|---|---|---|---|---|---|
| `api/main.py`; `app/`; `ops/`; `scripts/run_full_etl.py`; `Dockerfile`; `docker-compose.yml` | Nightly schedule; API/UI serving; ops queue; reports; worksheet; AI draft | Unpinned environment; no lockfile; nightly failures since 2026-11-09; no run manifest; CURRENT_DATE reports; AI/autofill not as-of bounded; no CD job | The host scheduler is the deployment mechanism; the canonical checkpoint is current; AI remains disabled; the local filesystem is a sufficient identity archive | **3** | DA-01, DA-11, DA-17, DA-20, SVC-F04, SVC-F05, SVC-F10, BI-34, BI-37 |

**Requirements:** FR-REP-01..02, FR-AI-01..02, NFR-REPRO-01..03, NFR-REL-01..02, NFR-SEC-01..03, NFR-SCALE-01..02.

**Key finding.** The operational and security surface is stronger than the research reproducibility surface. Containers are hardened and the ops plane is allowlisted, but the runtime is not pinned and a failed nightly run leaves only a coarse audit row.

## 8. Cross-Phase Gaps

| Gap | Phases affected | Requirements | Consequence |
|---|---|---|---|
| Current-state universe | Data Understanding → Data Preparation → Modeling → Evaluation | FR-UNI-01, FR-UNI-02, NFR-PIT-02 | Survivorship and mis-typed names affect features, scores and backtest |
| Latest-only raw payloads | Data Preparation → Evaluation → Deployment | NFR-AUD-02, NFR-REPRO-04 | A past feature or score cannot be rebuilt from raw state |
| Mutable score/label history | Modeling → Evaluation → Reporting | FR-SIG-03, FR-LABEL-03 | A replay can overwrite the evidence a backtest consumed |
| Missing run manifests | Data Preparation → Evaluation → Deployment | NFR-REPRO-03, FR-BT-05, FR-EVAL-04 | Results cannot be tied to code, data, policy or environment |
| Acceptance-policy reuse | Modeling → Evaluation | FR-EVAL-03, NFR-GOV-01 | A future GO is not backed by an untouched holdout |
| Current-date reporting | Data Understanding → Deployment | FR-REP-02, NFR-PIT-05 | A report opened later can mix today's data with a past analysis date |

## 9. Maturity Caveats

- Scores are based on observed controls and gaps, not on outcome quality. A phase can be mature in process and still produce a biased result.
- The repository has strong Data Governance instrumentation, but governance is scored under the nearest phase rather than as a seventh CRISP-DM phase.
- Evaluation would score 1 if only research validity were considered; it scores 2 because fold construction, purge, fail-closed behavior and nightly verification are real controls.
- Business Understanding would score 2 if documentation were the only evidence; it scores 3 because the scoring, portfolio and reporting decisions are consistently implemented.
