# Capability Inventory

| Field | Value |
|---|---|
| Stage | 0 — Discovery |
| Scope | Feature capability matrix (Present / Partial / Absent) with file evidence |
| Method | Read-only code inspection; live DB counts where noted |
| Legend | Present = implemented and wired; Partial = implemented with material gaps; Absent = not found; V/I/A/U as before |
| Row format | ID \| Finding \| Evidence \| File path \| Function/Class \| Requirement ID \| CRISP-DM phase \| Risk \| Recommended action \| Confidence \| Type |

## 1. Capability Matrix

| ID | Capability | Status | Evidence | Conf/Type |
|---|---|---|---|---|
| CAP-01 | Fundamental research | Present | `src/crispdm/fundamentals.py` (`extract_periodic_financials`), `raw.companyfacts`, `fundamentals.periodic_financials` (1,298,831 rows), `raw.fmp_statements` (41,357), `raw.fmp_filings` (354,322) | 0.97 V |
| CAP-02 | Quantitative research | Present | `src/crispdm/features.py`, `feature_set.py` (10 features), `returns.py`, `analogs.py`, `event_study.py`, walk-forward `validation.py` | 0.95 V |
| CAP-03 | Technical research | Partial | Price/volume data and momentum features (`momentum_252d`, `momentum_63d`, `volatility_252d`); no indicators (RSI/MACD/BB), pattern, or technical scoring module found | 0.90 V |
| CAP-04 | Factor research | Present (fixed set) | 10-feature store; percentile blends; no general factor library or custom factor API | 0.95 V |
| CAP-05 | Multi-factor ratings | Present | `src/crispdm/scoring.py` five weighted factors (income 0.25, sustainability 0.20, appreciation 0.15, risk 0.10, valuation 0.05; normalized by 0.75); `MIN_PRESENT_WEIGHT=0.50`; `model_version="rule_scoring_v1"` | 0.98 V |
| CAP-06 | Macro and market data | Present | `src/crispdm/macro_inputs.py` `PROVIDER_ROUTES`; `macro_vintages.py`; `raw.macro_series` (1,796), `raw.macro_series_vintages` (105,865), `raw.macro_etf_sectors`; FRED/ALFRED; daily prices in `raw.market_data` (9,823,774) | 0.98 V |
| CAP-07 | Dividends | Present | `scripts/populate_dividend_data.py`; `raw.dividend_data` (323,632); `raw.dividend_calendar` (2,121); `raw.upcoming_dividends` view (528); `dividend_universe.py`; `dividend_limits.py`; reconciliation to `raw.dividend_amount_check` (577) | 0.98 V |
| CAP-08 | Price adjustment | Partial | No stored adjusted close (`adjusted_close` 100% NULL); split events in `raw.corporate_actions` (8,202); dividend basis reconciliation in `openbb_client._price_basis_adjust`; total return computed in `returns.py`; backtest price cleaning `PRICE_FILTER="stale_reversal_absurd_split_unreliable_v5"` | 1.0 V |
| CAP-09 | Financial statements | Present | SEC XBRL → `fundamentals.periodic_financials`; FMP statements/DCF/filings in `raw.fmp_*`; API `/financials/{ticker}`, `/openbb/statements/{ticker}`, `/openbb/dcf/{ticker}` | 0.97 V |
| CAP-10 | Earnings intelligence | Partial | Fundamentals and filings exist; no earnings-call transcripts, consensus/estimate revisions, surprise history, or earnings-sentiment module found | 0.90 V |
| CAP-11 | ETF / sector / peer comparison | Partial | Sector fields and `factor_exposures`/`sector_attribution` in `portfolio.py`; peer base rates in `analogs.py`; sector data in `raw.macro_etf_sectors`; no dedicated ETF analytics or peer-comparison UI found | 0.90 V |
| CAP-12 | Portfolio construction | Present | `src/crispdm/portfolio.py` (15 long / 8 short, 150% gross / 50% net, `select_portfolio`, risk-parity option); `src/math_engine.py` `RiskParityCalculator` | 0.98 V |
| CAP-13 | Watchlist | Absent | `grep -rniE 'watchlist' app api src scripts --include='*.py'` → 0 matches; `docs/AnalystDashboard.md` lists as optional/not built | 0.95 V |
| CAP-14 | Screener | Present | `app/views/screener.py`; 16 metrics; filters; CSV; charts | 0.95 V |
| CAP-15 | Alerts | Absent | `grep -rniE 'alert' …` → 0 matches in Python; no email/Slack/webhook integration | 0.95 V |
| CAP-16 | AI summarization | Partial / Absent for summarization | Only optional local LLM worksheet drafting (`app/llm_client.py`, disabled by default, schema-validated, never auto-saved); no filing/news/report summarization; deterministic `final_summary()` is not AI | 0.95 V |
| CAP-17 | Backtesting | Present with caveats | `src/crispdm/backtest.py` monthly walk-forward; `baselines.py`; `scripts/backtest.py` artifacts; `liquidity_floor_study.py`; caveats: survivor-only history, no trading costs, identity fragmentation, event risk | 0.98 V |
| CAP-18 | Data governance | Present | `audit.source_lineage` (26,297), `audit.data_quality` (343,627), `audit.quarantined_values` (2,698), `audit.source_freshness` (72), `audit.nightly_runs` (53); `scripts/migrate.py` forward-only ledger; `scripts/check_schema_drift.py`; secrets in `.gitignore`; ops allowlist | 0.98 V |
| CAP-19 | Reporting | Present | Dashboard Reports Center (5 deterministic report types, Markdown); worksheet Markdown/JSON export; screener CSV; no PDF/email distribution | 0.95 V |
| CAP-20 | Identity / master data | Present | `reference.securities` (12,585), `issuers` (8,223), `security_identifiers` (25,037); repair/merge scripts (`resolve_ticker_conflict`, `merge_duplicate_identities`, `rekey_security_successor`) | 0.95 V |
| CAP-21 | Preferred / fixed-income equities | Present | `preferred.security_terms` (1,391), `preferred.contract_terms` (303), `preferred.dividend_snapshot` (891); `scripts/populate_contract_terms.py` | 0.95 V |
| CAP-22 | Regime / macro overlay | Partial | `src/crispdm/regime.py`, `regime_pipeline.py`; computed but `apply_scores=False` by default; several inputs lack sources (`quick_liquidity`, `refinancing_wall`, `credit_rating`) | 0.95 V |
| CAP-23 | Operational control plane | Present | `ops.tasks` queue, `ops.schedules`, worker heartbeat, logs, cancel; token-gated; catalog allowlist | 0.98 V |
| CAP-24 | Agent/skill workflow | Present | `scripts/agent_runner.py`, `src/agent/*`, 22 `skills/*/SKILL.md`, `SYSTEM.md`; deterministic fixed-entrypoint execution | 0.95 V |
| CAP-25 | API access | Present | FastAPI with 18 route decorators; API key; rate limiting; SEC/OpenBB/metrics endpoints | 0.98 V |

## 2. Status Summary

| Status | Count | Capabilities |
|---|---|---|
| Present | 17 | CAP-01, 02, 04, 05, 06, 07, 09, 12, 14, 17, 18, 19, 20, 21, 23, 24, 25 |
| Partial | 6 | CAP-03, 08, 10, 11, 16, 22 |
| Absent | 2 | CAP-13, CAP-15 |

Counts: Present 17, Partial 6, Absent 2, total 25 (CAP-01…CAP-25). `[V]`

## 3. Findings Register

| ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| CAP-F01 | Dividends and fundamentals are the strongest implemented capabilities | 323,632 dividend rows; 1.29M fundamentals rows; dedicated modules | `raw.dividend_data`; `fundamentals.periodic_financials` | — | TBD | Data Understanding | Low | Use as anchor for requirement recovery | 1.0 | Verified |
| CAP-F02 | Price adjustment is implicit, not a first-class stored/factorized capability | `adjusted_close` 100% NULL; split events separate; cleaning heuristic in backtest | `sql/schema.sql`; `src/crispdm/backtest.py`; `src/crispdm/returns.py` | `_cleaned_prices` / `build_forward_returns` | TBD | Data Preparation | Critical | Add explicit adjustment-factor requirement and tests (Stage 1A/1C) | 1.0 | Verified |
| CAP-F03 | Watchlist and alerts are absent, contradicting any requirement expecting them | 0 grep matches; docs list optional/not built | — | — | TBD | Business Understanding | Med | Confirm scope; if required, add to backlog | 0.95 | Verified |
| CAP-F04 | AI summarization is not implemented; only optional worksheet drafting | only `app/llm_client.py` call site; disabled by default | `app/llm_client.py`; `app/views/investment_analysis.py` | `generate_draft` | TBD | Modeling | Low | Clarify AI scope in requirements | 0.95 | Verified |
| CAP-F05 | Earnings intelligence is limited to filings/fundamentals; no transcripts or estimates | no transcript/estimate modules found | `src/crispdm/fundamentals.py`; `raw.fmp_filings` | — | TBD | Data Understanding | Med | Confirm requirement; add provider if needed | 0.90 | Verified |
| CAP-F06 | Technical analysis is limited to momentum/volatility features | no indicator library found | `src/crispdm/feature_set.py` | `FEATURES` | TBD | Data Preparation | Low | Mark technical research as partial | 0.90 | Verified |
| CAP-F07 | Regime layer exists but is advisory only | `apply_regime_layer(..., apply_scores=False)` default | `src/crispdm/regime_pipeline.py` | `apply_regime_layer` | TBD | Modeling | Med | Document when regime weights are allowed | 0.95 | Verified |
| CAP-F08 | Backtest survivorship and cost caveats are documented but unresolved | survivor-only 6,423/6,424; no costs | `docs/AnalystDashboard.md`; `src/crispdm/backtest.py` | — | TBD | Evaluation | High | Promote to explicit NFR/acceptance criteria | 0.95 | Verified |
| CAP-F09 | Data governance is materially implemented, unlike many research repos | lineage, quality, quarantine, freshness tables and checks | `scripts/populate_audit.py`; `scripts/verify_nightly_run.py` | — | TBD | Evaluation | Low | Formalize in constitution (Stage 3) | 0.98 | Verified |
| CAP-F10 | Capability documentation overstates architecture in several places | dbt/Bayesian/multi-agent described but absent | `README.md`; `TECHNICAL_SPEC.md`; `docs/UiWorkflowArchitecture.md` | — | TBD | Business Understanding | Med | Reconcile docs before spec recovery | 0.90 | Verified |
