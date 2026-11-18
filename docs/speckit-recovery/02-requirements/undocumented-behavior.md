# Undocumented Behavior Register

| Field | Value |
|---|---|
| Stage | 2 — Requirements recovery |
| Scope | Behavior that is real in the repository but absent or contradicted in user-facing documentation |
| Row format | ID | Behavior | Evidence | File | Requirement | Risk | Recommended action | Confidence | Type |
| Method | Read-only code, schema, database and artifact inspection; no source, test or config changes |

This register is not a defect list. It records behavior a new maintainer or specification reader would not know from the README, technical spec or dashboard guide. Several items are undocumented strengths or deliberate boundaries, not failures. Items marked `Unknown` are explicitly not verified.

## 1. Undocumented Behavior

| ID | Behavior | Evidence | File | Requirement | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|
| `UB-01` | The production signal is the rule-based five-factor score, not the walk-forward logistic model. | scoring.model_version='rule_scoring_v1'; scripts/score_rank.py calls scoring, not model.walk_forward | src/crispdm/scoring.py; scripts/score_rank.py | FR-SIG-01, FR-EVAL-02 | High | State the model split in the constitution and UI; keep ML promotion separate | 0.98 | Verified |
| `UB-02` | raw.market_data.adjusted_close is never populated; consumers reconstruct adjustment or ignore it. | 0 non-null of 9,823,774 rows; clean_prices adjusts only inside backtest/dashboard | sql/schema.sql; src/crispdm/portfolio.py | FR-ADJ-01 | High | Declare the column reserved or implement an adjusted-series contract | 1.00 | Verified |
| `UB-03` | The ten-percent split tolerance can absorb a real split-day move or skip a confirmed split. | 2-for-1 split with -10 percent real move yields zero split-day return; -15 percent move is unadjusted | src/crispdm/portfolio.py | FR-ADJ-02, FR-ADJ-03 | High | Separate confirmed-event adjustment from the heuristic and record residuals | 0.95 | Verified |
| `UB-04` | SEC dividends use period end as ex-date and drop the filing date. | ex_dividend_date = end; filed parsed then not stored; feature fallback joins on ex date | scripts/populate_dividend_data.py; src/crispdm/features.py | FR-DIV-03, NFR-PIT-04 | High | Store filed and gate features/labels by it | 0.90 | Verified |
| `UB-05` | A provider payload that omits dates erases earlier dividend dates. | DIVIDEND_UPSERT sets declaration, record and payment dates to EXCLUDED.* | scripts/populate_dividend_data.py | FR-DIV-04, NFR-AUD-02 | High | Use COALESCE on conflict and record the source of each date | 0.95 | Verified |
| `UB-06` | unresolved dividend verdicts mix no-evidence and disagreement and are rechecked after seven days. | 354 unresolved; RECHECK_UNRESOLVED_DAYS = 7; cache upsert overwrites the prior verdict | scripts/populate_dividend_data.py; src/crispdm/openbb_client.py | FR-DIV-02 | Medium | Add distinct reason codes and append-only attempts | 0.90 | Verified |
| `UB-07` | The dividend calendar is append-only with no withdrawal marker and no as-of reader. | 2,121 events; view filters CURRENT_DATE; grep finds no consumer | sql/migrations/V0099_dividend_calendar.sql; scripts/load_dividend_calendar.py | FR-DIV-06, NFR-PIT-04 | Medium | Version events and parameterize the view by as-of | 0.90 | Verified |
| `UB-08` | The scored universe has no active predicate while feature eligibility does. | UNIVERSE_SQL lacks s.active; feature_window filters active; inactive and preferred examples observed | src/crispdm/portfolio.py; src/crispdm/feature_window.py | FR-UNI-02 | High | Align both readers on an as-of active rule | 0.90 | Verified |
| `UB-09` | Delisted names are forward-filled and earn zero after their last print. | total_return_matrix ffill; no delisted_date writer | src/crispdm/portfolio.py | FR-UNI-03 | High | Truncate at last trade and apply a documented delisting return | 0.75 | Verified mechanism |
| `UB-10` | The risk-parity option weights a risk score, not volatility, in the opposite direction. | _risk_parity_weights(longs, 'risk_score'); risk_score is inverse volatility percentile | src/crispdm/portfolio.py; src/crispdm/scoring.py | FR-PORT-02 | High | Use volatility with inverse weights or remove the flag | 0.90 | Verified |
| `UB-11` | The backtest benchmark is a 100 percent net equal-weight book while the strategy is 150/50. | Book 15 long at 6.67 and 8 short at 6.25; benchmark mean of scored universe | src/crispdm/backtest.py | FR-BT-04, FR-TR-04 | High | Produce long-only and exposure-matched benchmarks | 0.80 | Verified |
| `UB-12` | Backtest cleaning reads 14 days after formation and can change period membership. | prices_for(ids, start, end + CLEANING_LOOKAHEAD); exclude_unreliable and reversal use the window | src/crispdm/backtest.py; src/crispdm/portfolio.py | FR-BT-02, NFR-PIT-01 | High | End eligibility at formation and report post-formation rejections separately | 0.85 | Verified |
| `UB-13` | The acceptance policy and cleaning rules were revised after viewing the same folds. | PR-AUC lift demoted from a Go/No-Go criterion after fold 4 failed; MAX_FLAG_RATE added after a 4/4 GO | src/crispdm/model.py; scripts/evaluate_walk_forward.py; docs/data-health-workstreams.md | FR-EVAL-03, NFR-GOV-01 | High | Pre-register a fresh policy and an untouched holdout | 0.85 | Verified in docs and code |
| `UB-14` | The canonical walk-forward checkpoint is overwritten by an ordinary run. | evaluate_walk_forward writes args.out after every run; only contract drift moves the old file | scripts/evaluate_walk_forward.py; data/walk_forward_checkpoint.json | FR-EVAL-04, NFR-REPRO-04 | High | Address checkpoints by run id and maintain a latest pointer | 0.90 | Verified |
| `UB-15` | Only 11 of 107 test modules call a script main; the advertised dry-run is broken. | python -m scripts.dry_run_walk_forward raises TypeError; README claims PASS | scripts/dry_run_walk_forward.py; README.md; tests/ | FR-EVAL-05, NFR-TEST-04 | High | Smoke-test every advertised entry point | 1.00 | Verified by execution |
| `UB-16` | model.scores has no run id or feature hash, but model.predictions is fully versioned. | scores PK (security_id, as_of_date); predictions keyed by run_id with versions | sql/schema.sql; scripts/score_rank.py; script/predictions | FR-SIG-03, FR-SIG-04 | High | Carry the prediction provenance model into score storage | 0.95 | Verified |
| `UB-17` | Feature rows are stamped with features_v5 and a hash, but scoring does not carry either. | 9,756,631 rows all features_v5, hash 929658405dbc95be; scores have neither | src/crispdm/features.py; model.features; model.scores | FR-FEAT-02, NFR-AUD-01 | High | Join score runs to feature run and hash | 0.90 | Verified |
| `UB-18` | The latest backtest artifact uses a removed rule set, thin_v6, while current code uses v5. | metrics_20261102_153616.json price_filter thin_v6; backtest.PRICE_FILTER v5; dashboard scans newest | artifacts/backtests/metrics_20261102_153616.json; src/crispdm/backtest.py; app/views/dashboard.py | FR-BT-05, NFR-REPRO-03 | High | Reject or label rule-set mismatch at serve time | 0.95 | Verified |
| `UB-19` | The working tree replaces 20 direct pins with a 238-line unpinned freeze. | HEAD requirements.txt has 20 pins; worktree has zero ==; no lock file; installed pytest and streamlit drift | requirements.txt; requirements-dev.txt; Dockerfile; .github/workflows/ci.yml | NFR-REPRO-01, NFR-REPRO-02 | High | Restore pins and add a hashed lock | 1.00 | Verified git state |
| `UB-20` | The nightly run audit records stage status but no root cause or environment identity. | audit.nightly_runs columns omit code, image, args and error excerpt; last four runs failed | scripts/run_full_etl.py; sql/schema.sql; audit.nightly_runs | NFR-AUD-03, NFR-REL-01 | High | Persist a run manifest and per-stage log excerpt | 0.95 | Verified |
| `UB-21` | Reports use CURRENT_DATE and autofill defaults to Timestamp.now, but the worksheet has no enforced as-of. | CURRENT_DATE in API and app views; analysis_autofill fetch_company today=None; worksheet date not enforced | api/main.py; app/views/investment_analysis.py; app/analysis_autofill.py | FR-REP-02, FR-AI-02, NFR-PIT-05 | Medium | Store as-of on the worksheet and parameterize every query | 0.85 | Verified code |
| `UB-22` | Identity release and merge delete dependent history after writing a local JSON archive. | perform_release deletes security and dependents; merge deletes twins; no tombstone or DB archive | scripts/resolve_ticker_conflict.py; scripts/merge_duplicate_identities.py | FR-CA-02, FR-ID-01, NFR-AUD-04 | Medium | Use validity intervals and a warehouse-resident archive | 0.85 | Verified code |
| `UB-23` | Provider licensing and redistribution terms are undocumented and unverified. | No license inventory for SEC, OpenBB, yfinance, FMP, Polygon or FRED | repo-wide; docs/ | NFR-GOV-03 | Medium | Add a provider-terms inventory before external distribution | 0.60 | Unknown |

## 2. Documentation Contradictions

| Claim | Observed behavior | Evidence | Requirement |
|---|---|---|---|
| README describes a broad dbt, Bayesian and multi-agent architecture. | The repository implements a Python ETL, rule scoring and a gated logistic model; dbt and Bayesian components are absent. | CAP-F10, CMP-F16 | FR-SIG-01, NFR-REPRO-02 |
| README says the dry-run walk-forward demo passes. | The command raises `TypeError` and no test executes `main()`. | TG-01, BI-29 | FR-EVAL-05 |
| The docs present the score history as point-in-time. | The score table is overwritten on replay and has no run id. | DA-02, TG-07 | FR-SIG-03 |
| The dashboard presents the latest backtest as current. | The latest artifact uses a removed `thin_v6` rule set; current code uses `v5`. | DA-09, BI-21 | FR-BT-05 |
| The feature store is described as PIT. | Availability clamps filed to period end, SEC dividends use period end, and price-quality medians use full history. | BI-02, BI-10, PA-F04 | FR-FEAT-01, NFR-PIT-01 |
| The lineage table is described as end-to-end. | Only five decision fields are stored and lineage is rebuilt destructively. | DA-13 | NFR-AUD-01 |

## 3. Strengths Worth Recording

- Macro revisions, ticker-profile history and quarantine records are append-only and materially better than the rest of the raw layer (`DA-13` §5, `CAP-F09`).
- Predictions and the ML checkpoint contract carry model, feature and data versions; the gap is score storage, not prediction storage (`FR-SIG-04`, `DA-12`).
- The operations plane is catalog-allowlisted, token-gated and read-only for explorer queries (`NFR-SEC-02`).
- The nightly pipeline has an advisory lock, migration preflight and fail-closed stage behavior (`NFR-REL-02`).
- Walk-forward purging, label sorting and all-fold requirements are implemented even though regression tests are missing (`FR-EVAL-01`).

## 4. Limits

- Reports Center as-of labeling remains Unknown (BI-37); no claim is made here.
- Provider licensing remains Unknown (NFR-GOV-03); no legal conclusion is drawn.
- Behavior outside the repository (external scheduler state, object-store archives, provider audit logs) was not inspected.
