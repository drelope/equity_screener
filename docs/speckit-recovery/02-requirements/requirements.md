# Recovered Requirements Register

| Field | Value |
|---|---|
| Stage | 2 — Requirements recovery, CRISP-DM mapping and traceability |
| Repository | dividend_equity_crispdm |
| Revision | `d748cea` (working tree has uncommitted environment and docs changes) |
| Evidence snapshot | 2026-11-15 |
| Inputs | `docs/speckit-recovery/00-discovery/` and all files under `docs/speckit-recovery/01-audits/` |
| Output | `docs/speckit-recovery/02-requirements/` |
| Requirements | 53 functional, 31 non-functional, 84 total |
| Status counts | Implemented 18; Partial 53; Missing 12; Unknown 1 |

This register recovers requirements from observed behavior, not from a pre-existing specification. No `specs/` directory or requirements baseline exists in the repository. Each requirement is therefore a normative statement derived from code, schema, tests, documentation and the Stage 0–1D evidence. Where the implementation conflicts with the statement, the requirement records the intended contract and the status column records observed maturity.

## 1. Status and Confidence Semantics

| Status | Meaning |
|---|---|
| **Implemented** | A wired code path exists for the stated behavior; no known material gap in the behavior itself. Test or edge-case gaps may remain. |
| **Partial** | The main path exists but a material control, edge case, provenance field or consistency rule is missing. |
| **Missing** | No implementation of the stated behavior was found. |
| **Unknown** | The evidence is insufficient to decide, or the behavior is outside the inspected scope. |

Confidence is the probability that the requirement statement and status are correct given the evidence, on a 0–1 scale. `Verified` evidence was read in code, schema or live SELECT output; `Inferred` conclusions are marked in the source audit and are not promoted to verified here. A requirement without a test is not a missing requirement, but it is recorded in the RTM and in `coverage-statistics.md`.

## 2. Business Goals

| ID | Goal | Success condition |
|---|---|---|
| `BG-01` | Trustworthy income signal | Rank dividend payers by sustainable income and total-return potential rather than yield alone. |
| `BG-02` | Defensible historical evaluation | Make every historical score, label and backtest reproducible from information available at its as-of date. |
| `BG-03` | Reliable daily operations | Refresh the warehouse, detect failures and recover without corrupting prior state. |
| `BG-04` | Audit-ready provenance | Reconstruct who produced which result, from which code, data and policy. |
| `BG-05` | Explainable portfolio risk | Make exposures, constraints, benchmark mismatch and risk metrics explicit. |
| `BG-06` | Actionable analyst reporting | Produce deterministic, as-of-stamped reports and worksheets for analysts. |
| `BG-07` | Provider resilience and data quality | Reconcile providers, quarantine bad values and preserve provenance. |
| `BG-08` | Controlled AI assistance | Use optional, as-of-bounded AI without writes or unreviewed claims. |

Goals are recovered from the code's actual decisions (income weighting, walk-forward gating, audit tables, analyst UI) and from the Stage 0 capability inventory. They are not quoted from a product brief because none is present.

## 3. Requirement Category Map

| Family | Canonical Stage 2 category | Additional recovered scope |
|---|---|---|
| `FR-ADJ` | Price adjustment | Adjusted-series contract, split residuals |
| `FR-CA` | Corporate actions | Identity continuity across actions |
| `FR-DIV` | Dividend adjustment | Reconciliation, PIT availability, calendar |
| `FR-TR` | Total return | Forward returns, benchmark basis |
| `FR-UNI`, `FR-ID` | Cross-cutting (universe and identity) | Point-in-time membership, delisting, identifier intervals |
| `FR-FEAT` | Signal generation input | Point-in-time features, versioning |
| `FR-LABEL` | Signal generation input | Label horizon, eligibility, immutability |
| `FR-MACRO` | Signal generation input | Vintages, risk-free as-of |
| `FR-SIG` | Signal generation | Composite score, coverage gate, score provenance |
| `FR-EVAL` | Backtesting | Purge, acceptance gate, holdout, checkpoints |
| `FR-BT` | Backtesting | Formation, costs, benchmarks, artifacts |
| `FR-PORT` | Portfolio analytics | Constraints, risk, attribution |
| `FR-REP` | Reporting | Deterministic reports, as-of stamping |
| `FR-AI` | Cross-cutting (analyst workflow) | Optional drafting, as-of bounds, text scope |

## 4. Functional Requirements

### 4.1 Price adjustment

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-ADJ-01` | The system shall provide an explicit adjusted price series, including the adjustment factor and basis, for every security used by features, returns, event study, portfolio construction and backtesting. The series shall reconcile raw closes with confirmed split events and shall not require each consumer to invent its own cleaning rule. | raw.market_data.adjusted_close is 0 of 9,823,774 non-null; adjustment exists only inside portfolio.clean_prices and is not shared with returns or features. | sql/schema.sql; src/crispdm/portfolio.py; src/crispdm/returns.py; src/crispdm/features.py; src/crispdm/event_study.py | clean_prices; total_return_matrix; build_forward_returns; build_features; daily_returns | **Partial** | 0.95 | DF-F01, CMP-F09, PA-P01, PA-P02 |
| `FR-ADJ-02` | When a split event is confirmed by the corporate-action calendar, the system shall apply the reported ratio to prior closes and record the residual between observed and reported moves. A confirmed split shall not be skipped merely because the real same-day move exceeds the ten-percent heuristic tolerance. | clean_prices applies a split only when observed/expected is within ten percent; a confirmed split with a larger real move stays unadjusted (PA-P02). | src/crispdm/portfolio.py; src/crispdm/openbb_client.py; scripts/load_corporate_actions.py | clean_prices; _event_index; split_rows; _price_basis_adjust | **Partial** | 0.90 | PA-P01, PA-P02, PA-P07, FA-P01 |
| `FR-ADJ-03` | Split adjustment shall preserve the real return on the split day rather than forcing it to zero or masking a real move. The tolerance, event window and first-print behavior shall be fixed, documented and covered by boundary tests so a valid split is neither absorbed into a false factor nor left as a crash. | A 2-for-1 split with a ten-percent real move produces closes that absorb the move and a split-day return of zero; index-0 and tolerance boundaries are untested (PA-P01, TG-08). | src/crispdm/portfolio.py; tests/test_portfolio.py | clean_prices; _event_index | **Partial** | 0.85 | PA-P01, PA-P02, PA-P07, TG-08, FA-P01 |
| `FR-ADJ-04` | The system shall use one documented split-ratio convention across ingestion and adjustment, or prove the two existing conventions equivalent. It shall also define whether a split dated on the ex-dividend date applies to that dividend and shall test the case. | Yahoo factors divide dividend amounts while corporate_actions ratios multiply closes; _later_factor uses strict greater-than so a same-day split is excluded (PA-P13, PA-P17). | src/crispdm/openbb_client.py; scripts/load_corporate_actions.py; src/crispdm/portfolio.py | _later_factor; _price_basis_adjust; split_rows; load_split_events | **Partial** | 0.80 | PA-P13, PA-P17, FA-S01, FA-S02, FA-S04 |

### 4.2 Corporate actions

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-CA-01` | The system shall ingest splits and other corporate actions with a stable source event key, source provider and retrieval time so that reloading the same event is idempotent and a repeated or corrected filing does not create duplicate events or silently change history. | raw.corporate_actions holds 8,202 split events; the incremental loader hashes rows and the corporate-action loader writes provider columns. | scripts/load_corporate_actions.py; scripts/load_split_calendar.py; sql/migrations/V0099_dividend_calendar.sql | split_rows; main | **Implemented** | 0.95 | DF-10, CAP-08, PA-P17 |
| `FR-CA-02` | When a corporate action changes a ticker, issuer, share class or listing, the system shall preserve an addressable identity history with validity intervals so that prices, dividends, features and scores remain attributable to the same economic security across the change. | reference.security_identifiers has 0 closed ticker intervals and 1,630 tickers map to more than one security with open intervals; resolve_security_ids cannot resolve a ticker as of a past date. | src/crispdm/identity.py; reference.security_identifiers; scripts/resolve_ticker_conflict.py; scripts/rekey_security_successor.py | resolve_security_ids; perform_release; main | **Partial** | 0.80 | BI-23, DA-14, CAP-20 |

### 4.3 Dividend adjustment

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-DIV-01` | Every dividend row shall retain the provider, underlying feed, retrieval time and whether the amount is as declared or restated to a split basis. Rows from different feeds shall not collide under a key that omits the feed. | raw.dividend_data has 323,632 rows (197,179 OPENBB and 126,453 SEC_XBRL) with provider, feed, amount_feed, retrieved_at and adjusted_amount columns, but its primary key is (security_id, ex_dividend_date, provider), so FMP and Yahoo rows for one event collide and only the chosen amount survives. | sql/schema.sql; sql/migrations/V0083_dividend_amount_reconciliation.sql; scripts/populate_dividend_data.py | normalize_sec_dividend_rows; DIVIDEND_UPSERT; merge_dividend_records | **Partial** | 0.90 | DF-F03, CAP-07, PA-D14 |
| `FR-DIV-02` | When providers disagree on a dividend amount, the system shall choose a documented authoritative amount, retain each provider's evidence and distinguish no-evidence from genuine disagreement. A later recheck shall append a new verdict rather than overwrite the earlier one. | raw.dividend_amount_check has 354 unresolved, 171 fmp and 52 yfinance verdicts; unresolved rows are rechecked after seven days and the prior verdict is overwritten. | src/crispdm/openbb_client.py; scripts/populate_dividend_data.py; sql/migrations/V0083_dividend_amount_reconciliation.sql | reconcile_amounts; _verdict; save_amount_check; DIVIDEND_UPSERT | **Partial** | 0.90 | PA-D14, PA-D15, PA-D16, PA-D17, DA-06 |
| `FR-DIV-03` | A dividend derived from SEC XBRL shall become available to features, labels and total return only on or after the date the source filing was accepted. The period end shall not stand in for the ex-dividend date or the filing date. | normalize_sec_dividend_rows sets ex_dividend_date to period end and drops filed; d_declared and d_annual fallbacks join on ex date only (BI-02, PA-D01/02). | scripts/populate_dividend_data.py; src/crispdm/features.py; scripts/label_targets.py | normalize_sec_dividend_rows; build_features; label_targets | **Missing** | 0.85 | BI-02, PA-D01, PA-D02, PA-F01, TG-17 |
| `FR-DIV-04` | A dividend upsert shall preserve non-NULL stored declaration, record, payment and ex-dividend dates when an incoming provider payload omits them. The system shall document which date is authoritative for each source and shall detect implausible date ranges. | DIVIDEND_UPSERT assigns EXCLUDED.declaration_date, record_date and payment_date unconditionally, so an OPENBB row with NULL dates erases prior values; yfinance dates reach 1970 and FMP dates reach 2027. | scripts/populate_dividend_data.py; sql/schema.sql | DIVIDEND_UPSERT; insert_rows; normalize_sec_dividend_rows | **Partial** | 0.95 | PA-D06, DA-05, DF-F06 |
| `FR-DIV-05` | The system shall reject or quarantine dividends that exceed plausibility limits, retain the original value and rule that fired, and exclude quarantined rows from features, total return and backtests. Quarantine rules shall be maintained as runtime data, not only by a one-time migration. | dividend_limits caps per-share amounts and audit.quarantined_values holds 2,698 rows, including 65 absurd OPENBB dividends, with the source row retained; however, normalization drops new absurd OPENBB rows silently and OPENBB_DIVIDEND_AMOUNT_ABSURD is written only by one-time migration V0104. | src/crispdm/dividend_limits.py; scripts/populate_dividend_data.py; sql/migrations/V0104; audit.quarantined_values | normalize_sec_dividend_rows; apply_limits; quarantine | **Partial** | 0.90 | DF-F07, PA-D12, PA-D13, CAP-18 |
| `FR-DIV-06` | The dividend calendar shall land timestamped source snapshots, assign a stable source event id, record cancellations and reschedules as new versions, and expose an as-of query rather than filtering only on the current date. | raw.dividend_calendar is append-only with 2,121 events and no validity marker; raw.upcoming_dividends filters on CURRENT_DATE and has no code consumer. | sql/migrations/V0099_dividend_calendar.sql; scripts/load_dividend_calendar.py | fetch_window; main; upcoming_dividends view | **Partial** | 0.90 | PA-D20, PA-D21, DA-15, TG-05 |
| `FR-DIV-07` | Universe eligibility and dividend-payer status shall be evaluated as of the analysis date from dated evidence such as dividend history, listing status and delisting dates. A name that stopped paying or was delisted after the analysis date shall not be removed retroactively, and a name that began paying later shall not appear early. | get_target_dividend_tickers and observed_payer_keys use current flags or date.today defaults; there is no security membership interval table. | src/crispdm/dividend_universe.py; scripts/populate_dividend_data.py; src/crispdm/feature_window.py | get_target_dividend_tickers; observed_payer_keys; feature_window | **Partial** | 0.85 | BI-01, PA-D18, PA-D19, TG-04 |
| `FR-DIV-08` | All dividend amounts used together shall be expressed on one documented per-share split basis, with the original amount, the restatement factor and the provider basis retained. The system shall cross-check the two split conventions on the same event. | FMP amounts are divided by later split factors into adjusted_amount; yfinance amounts are assumed already adjusted; no cross-provider basis test exists. | src/crispdm/openbb_client.py; src/crispdm/dividend_limits.py; src/crispdm/features.py | _price_basis_adjust; _later_factor; build_features | **Partial** | 0.75 | PA-D14, PA-P13, FA-S01, FA-U03 |

### 4.4 Total return

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-TR-01` | Daily total return shall add each cash dividend on the first priced row on or after its ex-dividend date, exclude SEC period aggregates and implausible payments, and never double-credit or silently drop a dividend because of a missing close. | portfolio.total_return_matrix implements (P+D)/P-1 with a one-times-prior-close guard; returns.FORWARD_RETURN_SQL uses log returns and is never executed by a test; a dividend on a missing-close row is dropped. | src/crispdm/portfolio.py; src/crispdm/returns.py | total_return_matrix; build_forward_returns; FORWARD_RETURN_SQL | **Partial** | 0.90 | PA-P06, PA-P12, PA-P14, TG-09, FA-P02, FA-P03 |
| `FR-TR-02` | The forward-return dataset shall require a complete 252-trading-row window, compute total return as compounded daily total return, and expose price return and dividend return separately so downstream training and evaluation can audit the income contribution. | returns.build_forward_returns requires window_days 252 and writes total, price and dividend returns to model.forward_returns (8,279,088 rows). | src/crispdm/returns.py; scripts/build_forward_returns.py; model.forward_returns | build_forward_returns; FORWARD_RETURN_SQL; persist_forward_returns | **Implemented** | 0.90 | PA-P15, TG-09, FA-P04, FA-P05 |
| `FR-TR-03` | Features, forward returns, portfolio construction, event study and reporting shall use a consistent price basis and consistent simple-versus-log return convention. Any intentional difference shall be documented and cross-checked on a shared fixture. | returns.py uses log returns on raw closes while portfolio.py uses simple returns on forward-filled closes; features and event study each apply different adjustment and cleaning. | src/crispdm/returns.py; src/crispdm/portfolio.py; src/crispdm/features.py; src/crispdm/event_study.py | build_forward_returns; total_return_matrix; build_features; daily_returns | **Partial** | 0.85 | PA-P21, PA-F06, BI-31, FA-P03, FA-P02 |
| `FR-TR-04` | Reporting and backtesting shall compare the book with a benchmark whose gross and net exposure, long and short legs, dividend treatment, cash return and financing assumptions are stated and matched to the strategy, or shall report the unmatched exposure explicitly. | The book is 150 percent gross and 50 percent net while the benchmark is a 100 percent net equal-weight mean of the scored universe; cash periods use zero and a weekday calendar. | src/crispdm/backtest.py; src/crispdm/portfolio.py | run_walk_forward; _cash_period; performance_metrics | **Partial** | 0.80 | BI-08, BI-27, FA-P09, FA-P10 |

### 4.5 Universe and identity

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-UNI-01` | The system shall maintain dated security membership with valid-from and valid-to bounds so that every historical feature, score and backtest book uses the names eligible on that date, including names later delisted or removed from the dividend payer set. | No membership table or interval model exists; feature_window filters current active, UNIVERSE_SQL omits active, dividend_universe defaults to today and 29 later-inactive IDs appear in score history. | src/crispdm/feature_window.py; src/crispdm/portfolio.py; reference.securities | feature_window; UNIVERSE_SQL; load_universe | **Missing** | 0.90 | BI-01, BI-07, TG-04, CAP-20 |
| `FR-UNI-02` | The scored universe and the long and short book shall exclude inactive identities and non-common equity instruments unless the strategy explicitly includes them, using the same as-of rule as feature eligibility. | UNIVERSE_SQL has no active predicate and only a current security_type label; feature_window does filter active, so the two readers disagree; inactive CHTRP and preferred-series examples were observed. | src/crispdm/portfolio.py; src/crispdm/feature_window.py | UNIVERSE_SQL; load_universe; feature_window | **Partial** | 0.90 | BI-07, TG-04, PA-F04 |
| `FR-UNI-03` | A security that stops trading shall not be forward-filled at its last price into later books. The system shall truncate its return series, apply a documented delisting return where available and report the treatment. | total_return_matrix forward-fills closes up to the end of the index; reference.securities.delisted_date is read into identifier intervals but no code populates it from listing or price evidence. | src/crispdm/portfolio.py; reference.securities; scripts/sync_security_identifiers.py | total_return_matrix; load_universe | **Missing** | 0.75 | BI-09, BI-01 |
| `FR-ID-01` | Ticker, CIK and issuer identifiers shall carry valid-from and valid-to timestamps and shall be resolvable as of a date. Closing or reusing an identifier shall not merge the histories of two economic securities. | reference.security_identifiers holds 25,037 rows but 0 closed intervals; 1,630 tickers map to more than one security and resolve_security_ids cannot resolve across a change. | src/crispdm/identity.py; reference.security_identifiers; scripts/resolve_ticker_conflict.py | resolve_security_ids; main | **Partial** | 0.70 | BI-23, DA-14, CAP-20 |

### 4.6 Fundamental features

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-FEAT-01` | Every fundamental and dividend feature shall use the value visible at the observation date, based on the filing acceptance date. Values whose filing date precedes the period end, or whose filing occurs after the observation date, shall not be treated as available. | Availability uses GREATEST(filed, period_end), so a filed date earlier than period end is replaced by period end, making the row visible before the real filing; filing is date-granular and SEC dividends use period end. | src/crispdm/features.py; scripts/populate_dividend_data.py | build_features; classify_price_quality; normalize_sec_dividend_rows | **Partial** | 0.90 | BI-02, BI-10, BI-25, PA-F01 |
| `FR-FEAT-02` | Every feature row shall carry the feature-set version, a deterministic hash of the ordered feature names, the data version and a rebuild timestamp so a score or model can identify the exact feature definition that produced it. | model.features has 9,756,631 rows, all stamped features_v5 with hash 929658405dbc95be, but it has no data_version or rebuilt_at column; the row identifies the feature definition, not the input snapshot or rebuild time. | src/crispdm/features.py; src/crispdm/versioning.py; sql/migrations/V0095_feature_model_versioning.sql | build_features; compute_feature_set_hash; FEATURE_VERSION | **Partial** | 0.90 | DA-12, CMP-F07, CAP-04 |
| `FR-FEAT-03` | Dividend yield, annual dividend, dividend growth, earnings payout and free-cash-flow payout shall use compatible per-share bases, half-open windows and trailing data only. Implausible yields shall be a backstop, not the primary remedy for unadjusted prices. | Growth windows both include obs minus 365; payout divides OPENBB annual dividends by SEC EPS with unverified basis; price-quality median uses full history; yield band masks reverse-split symptoms. | src/crispdm/features.py; tests/test_features.py | build_features; classify_price_quality; null_implausible_yields | **Partial** | 0.85 | PA-F02, PA-F03, PA-F04, PA-F05, BI-26, FA-F02, FA-F03, FA-F04, FA-F07 |
| `FR-FEAT-04` | When multiple fundamental vintages share an availability date and period, the system shall select one row with a documented total order such as filed date, accession and metric preference. It shall not use max aggregation across vintages as a substitute for the latest filed value. | Quarterly DISTINCT ON orders only by eps-null and fiscal_period after the availability key; annual statistics use max across vintages and can mix fields. | src/crispdm/features.py; src/crispdm/portfolio.py | build_features; load_f_scores | **Partial** | 0.90 | DA-07, BI-11, BI-32 |

### 4.7 Labels

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-LABEL-01` | The training label shall be computed from a documented 365-day forward window and a documented definition of sustainable dividend payment, using only information after the observation date for the outcome and only available information for eligibility. | label_targets uses settings.label_horizon_days 365, a dividend-in-window rule and writes target_sustainable_dividend onto model.features. | scripts/label_targets.py; src/crispdm/config.py; model.features | label_value; label_targets; main | **Implemented** | 0.90 | DA-16, BI-06, BI-16 |
| `FR-LABEL-02` | Label eligibility shall not depend on an SEC period-end row whose filing occurs after the observation date. SEC-only evidence shall be gated by filed date, or the label population shall be restricted to rows with acceptable provenance. | label_targets eligibility uses ex_dividend_date within the prior 365 days without a filed-at-or-before-as_of predicate; SEC rows use period end. | scripts/label_targets.py; src/crispdm/features.py; raw.dividend_data | label_targets; build_features | **Partial** | 0.80 | BI-16, TG-17, PA-D02 |
| `FR-LABEL-03` | Labels shall be stored with a label run id, cutoff date, labeled-at timestamp and label version, and a rebuild shall not erase labels consumed by an earlier training run. Training shall pin a label run. | label_targets --rebuild first sets every non-NULL target to NULL and recomputes; the label lives on the mutable feature row with no label run or version. | scripts/label_targets.py; sql/schema.sql | label_targets; main | **Missing** | 0.90 | DA-16, BI-06 |

### 4.8 Macro inputs

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-MACRO-01` | The system shall ingest macro series with observation date, revision or vintage date, source and retrieval time, and shall retain historical revisions rather than only the latest value. | raw.macro_series_vintages holds 105,865 rows from 2010-01-04 to 2026-11-06; raw.macro_series holds 1,796 current rows. | src/crispdm/macro_vintages.py; scripts/load_macro_vintages.py; scripts/populate_macro_inputs.py | as_of_series; load_macro_vintages; populate_macro_inputs | **Implemented** | 0.95 | CAP-06, DF-14, DA-04 |
| `FR-MACRO-02` | Sharpe, information ratio, excess return, backtest cash and any other historical risk-free calculation shall use the macro revision visible at each evaluation date, not the latest revision. A later vintage shall not leak into an earlier calculation. | load_risk_free reads raw.macro_series latest values; macro_vintages.as_of_series is correct and tested but has no production caller. | src/crispdm/portfolio.py; src/crispdm/macro_vintages.py; tests/test_macro_vintages.py | load_risk_free; as_of_series; performance_metrics | **Partial** | 0.90 | BI-14, DA-04, TG-18, FA-N02 |

### 4.9 Signal generation

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-SIG-01` | The production signal shall be a documented composite of income, sustainability, appreciation, risk and valuation factors with fixed weights, a stated normalization rule and a model version. Any change to weights or normalization shall create a new version. | scoring.WEIGHTS uses five factors with weights 0.25, 0.20, 0.15, 0.10 and 0.05, normalized by 0.75 and stamped rule_scoring_v1. | src/crispdm/scoring.py; scripts/score_rank.py | score; pct; predictions; rankings; WEIGHTS | **Implemented** | 0.95 | CAP-05, CMP-F03 |
| `FR-SIG-02` | A security shall receive a published composite score only when the available factor weight meets the configured minimum coverage, and the threshold shall have boundary tests. Missing factor values shall not be silently treated as neutral without disclosure. | scoring.MIN_PRESENT_WEIGHT is 0.50; score returns no composite when present weight is below the floor; weights are renormalized over present factors. | src/crispdm/scoring.py | score; pct | **Implemented** | 0.95 | CMP-F04, CAP-05 |
| `FR-SIG-03` | Every scoring run shall write an append-only score record identified by a run id, with scored-at time, feature-set hash, feature version, data version and code revision. Replaying a past date shall create a new run and shall not overwrite the as-produced score. | model.scores is keyed (security_id, as_of_date), holds 464,691 rows and has no run id, scored-at, feature hash or code revision; score_rank upserts on conflict. | scripts/score_rank.py; sql/schema.sql; src/crispdm/portfolio.py | main; prune_stale_run_rows; SCORE_DATES_SQL | **Missing** | 0.95 | DA-02, BI-04, TG-07 |
| `FR-SIG-04` | When the ML classifier is used, every prediction shall be keyed by run id and shall carry the model version, feature version, data version, model configuration hash and training run id. | model.predictions is keyed by run_id and carries model, feature and data versions plus model_config_hash and training_run_id; 467,178 rows across 216 run ids. | src/crispdm/scoring.py; sql/migrations/V0095_feature_model_versioning.sql; model.predictions | predictions; score; rankings | **Implemented** | 0.90 | DA-12, DF-16, CMP-F05 |

### 4.10 Evaluation

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-EVAL-01` | Walk-forward training and test periods shall be separated by a purge and embargo at least as long as the label horizon, labels shall be sorted before cutting, and every fold shall be evaluated with a fail-closed policy when data is incomplete. | model.walk_forward sorts labels and purges rows whose 365-day label reaches the test period; walk_forward_folds requires all folds and skipped folds fail closed. | src/crispdm/model.py; scripts/evaluate_walk_forward.py | walk_forward; walk_forward_folds; evaluate_folds | **Implemented** | 0.90 | BI-33, TG-03, CAP-02 |
| `FR-EVAL-02` | Model promotion shall require a documented acceptance policy with blocking checks, diagnostic metrics and a baseline comparison. A failed blocking check shall produce no-go; diagnostics shall not silently override the gate. | Current contract balanced_acc_lift_and_negative_recall_v2 records blocking checks, diagnostics and an all-folds requirement; gate_passed is false in the canonical checkpoint. | scripts/evaluate_walk_forward.py; src/crispdm/model.py | evaluate_gate; evaluate_folds; current_contract | **Implemented** | 0.90 | BI-05, BI-22, DA-10 |
| `FR-EVAL-03` | The acceptance policy, cleaning rules and decision thresholds shall be versioned and frozen before evaluation on a fresh, untouched holdout. Fold results used to revise the policy shall not be reused as the promotion evidence. | The same last-50-percent block served the gate, a guardrail, a policy revision, label redefinition and feature versions v3-v5; PR-AUC lift was demoted from a Go/No-Go criterion to a monitoring diagnostic after fold 4 failed. | src/crispdm/model.py; scripts/evaluate_walk_forward.py; docs/data-health-workstreams.md | evaluate_gate; walk_forward_folds; main | **Missing** | 0.85 | BI-05, BI-06, BI-20, BI-22 |
| `FR-EVAL-04` | Every evaluation run shall persist a manifest with run id, code revision and dirty flag, data snapshot, feature and model versions, acceptance-policy version, environment hash, arguments and timestamp, and shall be addressable after later runs. | make_checkpoint records contract versions and gate but no code, data snapshot or environment hash; audit.model_runs omits acceptance_policy_version and generated_at; the canonical JSON checkpoint is overwritten on ordinary runs. | scripts/evaluate_walk_forward.py; sql/schema.sql; data/walk_forward_checkpoint.json | make_checkpoint; persist; contract_drift; invalidate_superseded_contract | **Partial** | 0.90 | DA-10, DA-18, BI-06, BI-21 |
| `FR-EVAL-05` | Every advertised evaluation, dry-run and backtest command shall execute successfully on a documented minimal input, and a test shall call the command's entry point so argument and signature drift fail the suite. | python -m scripts.dry_run_walk_forward raises TypeError for min_recall and a six-argument make_checkpoint; only 11 of 107 test modules call a script main. | scripts/dry_run_walk_forward.py; scripts/evaluate_walk_forward.py; src/crispdm/model.py; tests/test_dry_run_walk_forward.py | main; walk_forward; make_checkpoint | **Partial** | 1.00 | TG-01, TG-15, BI-29 |

### 4.11 Backtesting

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-BT-01` | The backtest shall form a portfolio on a documented monthly schedule, hold it for the stated period, credit returns strictly after the formation close and record each period's holdings, returns, turnover and cash period. | backtest.run_walk_forward builds monthly periods, a 15-long and 8-short book and writes period artifacts; returns are taken after the formation close. | src/crispdm/backtest.py; src/crispdm/portfolio.py; scripts/backtest.py | run_walk_forward; select_portfolio; portfolio_returns | **Implemented** | 0.90 | CAP-17, BI-17, FA-P07 |
| `FR-BT-02` | The set of names eligible for a backtest period, and the decision to reject a price, shall use only prices, volumes and corporate actions available on or before the formation date. Post-formation prints shall be reported separately and shall not change period membership. | run_walk_forward requests prices through end plus CLEANING_LOOKAHEAD of 14 days; exclude_unreliable and reversal confirmation use those future prints. | src/crispdm/backtest.py; src/crispdm/portfolio.py | run_walk_forward; exclude_unreliable; clean_prices | **Partial** | 0.90 | BI-03, PA-P05, PA-P04, TG-06 |
| `FR-BT-03` | Backtest returns shall include documented commissions, slippage, short borrow or financing costs and cash return. The cost model and its assumptions shall be stored with each result and varied in a sensitivity analysis. | run_walk_forward has no cost, slippage, borrow or financing inputs; the benchmark cash return is zero and the latest artifact records no cost assumptions. | src/crispdm/backtest.py; scripts/backtest.py | run_walk_forward; performance_metrics | **Missing** | 0.90 | CAP-17, BI-08, BI-20 |
| `FR-BT-04` | The backtest report shall show the strategy against at least a long-only benchmark and a benchmark matched to the strategy's gross and net exposure, with alpha, beta and the contribution of the short leg. A single unmatched benchmark shall not be presented as the primary comparison. | The benchmark is a 100 percent net equal-weight mean of the scored universe while the book is 150 percent gross and 50 percent net; no long-only or matched benchmark is produced. | src/crispdm/backtest.py; src/crispdm/portfolio.py | run_walk_forward; performance_metrics | **Partial** | 0.85 | BI-08, FA-P09 |
| `FR-BT-05` | Every backtest artifact shall be immutable and identified by run id, with code revision and dirty flag, data snapshot, price-filter and cleaning-rule version, cost assumptions, benchmark definition and configuration hash. The dashboard shall refuse or clearly label an artifact whose rule set or code does not match the running code. | Seven metrics files exist from 2026-10-26 to 2026-11-02 with no run id, code SHA, data version or cost assumptions; the latest records thin_v6 while current code uses v5. | scripts/backtest.py; src/crispdm/backtest.py; app/views/dashboard.py; artifacts/backtests | run_walk_forward; main; _reports | **Missing** | 0.95 | DA-09, BI-21, BI-20 |

### 4.12 Portfolio analytics

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-PORT-01` | Portfolio construction shall enforce the configured long count, short count, gross exposure, net exposure, equal-weight or risk-weight rule and minimum price and liquidity filters, and shall fail closed when the candidate set cannot satisfy them. | portfolio.select_portfolio uses 15 long and 8 short positions at 6.67 and 6.25 percent, giving 150 percent gross and 50 percent net; UNIVERSE_SQL applies price bounds. | src/crispdm/portfolio.py | select_portfolio; UNIVERSE_SQL; clean_prices | **Implemented** | 0.95 | CAP-12, BI-07, BI-08 |
| `FR-PORT-02` | VaR, expected shortfall, parametric VaR, component VaR, volatility and drawdown shall be computed on holding-period returns without treating pre-listing or missing days as zero, and the covariance sample and reliability flag shall be reported. | risk_metrics fills missing returns with zero and drops any date with a missing name for parametric covariance; the optional risk-parity path weights risk_score rather than volatility. | src/crispdm/portfolio.py; src/crispdm/math_engine.py; src/crispdm/scoring.py | risk_metrics; position_returns; select_portfolio; RiskParityCalculator | **Partial** | 0.90 | PA-P03, PA-P09, PA-P10, FA-R01, FA-R03, FA-R07 |
| `FR-PORT-03` | Sector and factor attribution shall use as-of sector classification where available, shall not silently treat a missing return as zero, and shall document the sign convention for short positions so the reported attribution reconciles to portfolio return. | sector_attribution fills missing returns with zero and subtracts the portfolio return uniformly; sector uses the latest profile rather than an as-of classification. | src/crispdm/portfolio.py; src/crispdm/analogs.py | sector_attribution; sample builder | **Partial** | 0.85 | PA-P11, BI-18, BI-31, FA-R06 |

### 4.13 Reporting

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-REP-01` | The Reports Center shall generate its documented report types from stored warehouse data with deterministic ordering and formatting, and the same inputs and as-of date shall produce the same report content. | The Streamlit Reports Center exposes five deterministic Markdown report types; worksheet Markdown and JSON export and screener CSV are available. | app/views/dashboard.py; app/views/investment_analysis.py; src/crispdm/analysis/store.py | _reports; render; export | **Implemented** | 0.90 | CAP-19 |
| `FR-REP-02` | Every report and analyst worksheet shall store and display the as-of date and the data fetch time used to build it. Queries shall be parameterized by that as-of date; the current date shall not silently substitute for it. | CURRENT_DATE filters appear in the API and three app views; autofill defaults to Timestamp.now; Reports Center labelling was not re-read. | app/views/dashboard.py; app/views/investment_analysis.py; app/views/security.py; app/analysis_autofill.py; api/main.py | _reports; fetch_company; load_warehouse | **Partial** | 0.80 | DA-20, BI-34, BI-37 |

### 4.14 AI assistance

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `FR-AI-01` | LLM assistance shall be disabled by default, loopback-only unless explicitly enabled, schema-validated before display, and shall never write to the database without explicit analyst confirmation. | app.llm_client is disabled by default, validates the draft schema and does not auto-save; the worksheet stores revisions only on operator action. | app/llm_client.py; app/views/investment_analysis.py; src/crispdm/config.py | generate_draft; parse_payload; _generate_section; Settings | **Implemented** | 0.90 | CAP-16, CMP-F15, CAP-20 |
| `FR-AI-02` | Autofill and any AI context shall use data available at the worksheet's stored as-of date, label live-sourced fields with fetch time, and refuse to silently substitute current data for a past analysis date. | fetch_company defaults today to None and fetches live; load_warehouse uses latest rows; _generate_section defaults to Timestamp.now; the worksheet stores no enforced as-of date. | app/analysis_autofill.py; app/views/investment_analysis.py | fetch_company; load_warehouse; _generate_section | **Partial** | 0.80 | BI-34, DA-20 |
| `FR-AI-03` | The system shall not claim earnings-call, news, surprise or sentiment intelligence until a timestamped source with as-of retrieval is ingested. Such sources remain explicitly out of scope for current scoring and reporting. | No transcript, surprise, news or sentiment ingestion exists; only two worksheet prose labels mention them. | repo-wide; src/crispdm/features.py; app/analysis_autofill.py | build_features; fetch_company | **Missing** | 0.90 | BI-36, CAP-10, CAP-F05 |

## 5. Non-Functional Requirements

### 5.1 Point-in-time integrity

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `NFR-PIT-01` | Every historical computation shall be reproducible from the information set available at its as-of date, including prices, fundamentals, dividends, corporate actions, macro revisions and universe membership. Future prints, later revisions and current flags shall not influence an earlier result. | Cleaning uses 14 future days, price-quality medians use full history, risk-free uses the latest macro revision, reports use CURRENT_DATE and universe flags are current-state. | src/crispdm/backtest.py; src/crispdm/features.py; src/crispdm/portfolio.py; src/crispdm/event_study.py | run_walk_forward; build_features; load_risk_free; _reports | **Partial** | 0.90 | BI-03, BI-14, PA-F04, DA-04, DA-20 |
| `NFR-PIT-02` | The eligible universe, active status, security type and dividend-payer status used by a historical computation shall be those that were knowable on that date, not those observed when the query runs. | feature_window filters current active; UNIVERSE_SQL has no active predicate; dividend_universe defaults to today; no membership interval table. | src/crispdm/feature_window.py; src/crispdm/portfolio.py; src/crispdm/dividend_universe.py | feature_window; UNIVERSE_SQL; observed_payer_keys | **Partial** | 0.90 | BI-01, BI-07, BI-38, TG-04 |
| `NFR-PIT-03` | Fundamental values shall be selected from the latest filing visible at the as-of date. Later restatements, same-period duplicate filings and rows whose filed date precedes the period end shall be handled with an explicit, documented rule. | Availability clamps filed to period end, uses date granularity and leaves a tie-break without filed or accession; annual statistics aggregate with max across vintages. | src/crispdm/features.py; src/crispdm/portfolio.py | build_features; load_f_scores | **Partial** | 0.90 | BI-10, BI-11, BI-25, DA-07, BI-32 |
| `NFR-PIT-04` | SEC dividend rows, dividend calendar events and label eligibility shall be visible only after their filing or publication timestamp. Cancellations and reschedules shall not rewrite what was known earlier. | SEC dividends use period end and drop filed; calendar has no withdrawal marker and the view is CURRENT_DATE; label eligibility lacks a filed predicate. | scripts/populate_dividend_data.py; scripts/label_targets.py; scripts/load_dividend_calendar.py | normalize_sec_dividend_rows; label_targets; fetch_window | **Partial** | 0.90 | BI-02, BI-16, PA-D01, PA-D02, DA-15 |
| `NFR-PIT-05` | Macro values, report labels and AI or autofill context shall use the revision or snapshot visible at the requested as-of date. Live data may supplement a current-date view only when it is labelled with fetch time and not presented as historical. | Risk-free uses the latest macro revision; API and memo show latest observations; reports use CURRENT_DATE; autofill fetches live and defaults to now. | src/crispdm/portfolio.py; src/crispdm/macro_inputs.py; app/analysis_autofill.py; api/main.py | load_risk_free; latest_observations; fetch_company; _reports | **Partial** | 0.85 | BI-14, BI-34, BI-35, DA-04, DA-20 |

### 5.2 Determinism

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `NFR-DET-01` | Every selection, deduplication, tie-break and price pick shall use an explicit total order. Equal sort keys shall not leave the chosen row dependent on database or provider iteration order. | UNIVERSE_SQL uses LIMIT 1 without ORDER BY; total_return_matrix keeps the last duplicate; feature DISTINCT ON lacks a total tie-break; provider scope is implicit. | src/crispdm/portfolio.py; src/crispdm/features.py; src/crispdm/returns.py | UNIVERSE_SQL; total_return_matrix; build_features | **Partial** | 0.85 | DA-07, DA-08, BI-31, BI-32 |
| `NFR-DET-02` | Library and CLI paths that reconstruct a historical state or write dated rows shall require an explicit as-of date. A wall-clock default shall be permitted only for live-fetch commands that are labelled as current. | Ten call sites across nine components default to today or now; passing as_of makes them deterministic but the defaults do not. | src/crispdm/identity.py; src/crispdm/sec_client.py; src/crispdm/dividend_universe.py; scripts/label_targets.py; scripts/load_dividend_calendar.py | resolve_security_ids; classify_companyfacts; observed_payer_keys; label_targets; fetch_window | **Partial** | 0.90 | DA-01, BI-38, TG-19 |
| `NFR-DET-03` | Replay and write paths shall obtain time from an injectable clock and persist the resolved timestamp with the result. Tests shall freeze the clock and assert identical output for a fixed as-of date on two different run dates. | No clock fixture or injection exists; date.today and Timestamp.now are called directly in identity, SEC classification, labels, calendar, reports and autofill. | src/crispdm/identity.py; src/crispdm/sec_client.py; app/analysis_autofill.py; scripts/label_targets.py | resolve_security_ids; classify_companyfacts; fetch_company; label_targets | **Partial** | 0.90 | DA-01, DA-20, TG-19 |
| `NFR-DET-04` | Stochastic model components shall use a recorded seed, provider responses shall be reduced to one authoritative value with a deterministic priority, and duplicate keys within an ingestion batch shall be resolved deterministically before insert. | LogisticRegression uses random_state 42; providers are collapsed to OPENBB; duplicate-key batch behavior is unverified (Unknown, confidence 0.6). | src/crispdm/model.py; src/crispdm/openbb_client.py; scripts/populate_dividend_data.py | walk_forward; reconcile_amounts; DIVIDEND_UPSERT | **Partial** | 0.80 | DA-08, DA-21, CMP-F05, PA-D08 |

### 5.3 Reproducibility

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `NFR-REPRO-01` | Runtime and development dependencies shall be pinned to exact versions, including transitive dependencies, with hashes or a lock file. CI and container builds shall install from that locked set. | HEAD requirements.txt has 20 direct pins; the worktree is a 238-line unpinned freeze with zero double-equals; there is no lock file; installed pytest and streamlit already differ. | requirements.txt; requirements-dev.txt; Dockerfile; .github/workflows/ci.yml | — | **Partial** | 1.00 | DA-17, SVC-F08 |
| `NFR-REPRO-02` | A clean environment built from the repository shall execute the same stages, produce the same feature and score values, and pass the same smoke checks as the recorded run. Container and CI images shall be pinned by digest or lock. | Dockerfile pins python:3.12-slim but installs the mutable requirements; CI uses action tags and a Postgres tag; no end-to-end clean-environment reproduction test exists. | Dockerfile; docker-compose.yml; .github/workflows/ci.yml | — | **Partial** | 0.90 | DA-17, SVC-F08, SVC-F10 |
| `NFR-REPRO-03` | Every ETL, scoring, evaluation and backtest run shall persist a manifest containing run id, code revision and dirty flag, arguments, dependency or image identity, input snapshot, output hashes and timestamps. | audit.nightly_runs records status and row counts only; audit.model_runs omits policy and generated-at; backtest metrics have no run id; checkpoints have no code or environment hash. | scripts/run_full_etl.py; scripts/evaluate_walk_forward.py; scripts/backtest.py; sql/schema.sql | record_nightly_run; persist; main | **Missing** | 0.95 | DA-09, DA-10, DA-11, SVC-F05 |
| `NFR-REPRO-04` | Raw provider payloads, labels, checkpoints and result artifacts shall be append-only and addressable by run or version. A later normal run shall not overwrite the evidence needed to reproduce an earlier result. | SEC payloads are latest-only keyed by CIK; labels are overwritten by rebuild; the canonical checkpoint is overwritten; raw macro vintages and ticker-profile history are positive counterexamples. | sql/schema.sql; scripts/populate_companyfacts.py; scripts/label_targets.py; scripts/evaluate_walk_forward.py | main; label_targets; make_checkpoint; persist | **Partial** | 0.90 | DA-03, DA-16, DA-18, BI-12 |

### 5.4 Auditability and traceability

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `NFR-AUD-01` | Every published score, prediction, backtest and report shall be traceable through stored lineage to the raw inputs and transformation versions that produced it, including prices, dividends, fundamentals, labels and feature versions. | audit.source_lineage holds 26,297 rows for only five fields; scores carry no feature hash; model inputs have no row-level lineage; lineage is rebuilt destructively. | scripts/populate_audit.py; audit.source_lineage; sql/schema.sql | source_lineage; lineage_provenance_gaps; populate_audit | **Partial** | 0.90 | DA-12, DA-13, DF-03, CAP-18 |
| `NFR-AUD-02` | Raw provider payloads, dividend revisions, reconciliation verdicts, labels and lineage shall be append-only, with retrieval or recorded timestamps and a projection for current-state readers. Corrections shall add a version, not erase the prior value. | ticker_profile_load, macro vintages and quarantine are append-only; SEC payloads, dividend dates, verdicts and labels overwrite. | sql/schema.sql; scripts/populate_companyfacts.py; scripts/populate_dividend_data.py; scripts/label_targets.py | main; DIVIDEND_UPSERT; label_targets | **Partial** | 0.90 | DA-03, DA-05, DA-06, DA-13, DA-16 |
| `NFR-AUD-03` | Nightly and evaluation run records shall include code and environment identity, arguments, start and finish times, per-stage exit and duration, row counts, resolved as-of dates and a log or error excerpt for each failure. | audit.nightly_runs has 53 rows with status and row counts but no code, image, arguments or error excerpt; audit.model_runs has 18 rows without policy or generated-at. | scripts/run_full_etl.py; scripts/verify_nightly_run.py; sql/schema.sql | record_nightly_run; main | **Partial** | 0.90 | DA-11, SVC-F05, SVC-F04 |
| `NFR-AUD-04` | Releasing a ticker conflict, merging duplicate identities or repairing a classification shall deactivate or version records with validity intervals and a warehouse-resident archive. It shall not delete the security or its dependent history. | release and merge write a local JSON archive and then delete the security, prices, dividends and scores; no tombstone or valid-to column is used. | scripts/resolve_ticker_conflict.py; scripts/merge_duplicate_identities.py; reference.securities | perform_release; main | **Partial** | 0.85 | DA-14, BI-24 |

### 5.5 Governance

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `NFR-GOV-01` | Acceptance criteria, cleaning rules, thresholds and holdout definitions shall be versioned, frozen before evaluation and recorded with every run. Post-hoc revisions shall invalidate earlier promotion evidence and require a fresh holdout. | The checkpoint records acceptance_policy_version but audit.model_runs does not; PR-AUC lift was demoted from a Go/No-Go criterion and MAX_FLAG_RATE added after viewing the same folds. | scripts/evaluate_walk_forward.py; src/crispdm/model.py; sql/schema.sql | current_contract; contract_drift; evaluate_gate | **Partial** | 0.85 | BI-05, BI-06, DA-10, BI-22 |
| `NFR-GOV-02` | The pipeline shall run documented data-quality checks, quarantine implausible values, monitor source freshness against an SLA and detect schema drift, with results stored in audit tables and exposed by nightly verification. | audit.data_quality has 343,627 rows, quarantined_values 2,698, source_freshness 72 and nightly_checks 26; check_schema_drift and verify_nightly_run are wired. | scripts/populate_audit.py; scripts/verify_nightly_run.py; scripts/check_schema_drift.py | data_quality; populate_audit; main | **Implemented** | 0.95 | CAP-18, CAP-F09, DF-F07 |
| `NFR-GOV-03` | Every external provider used by ingestion or serving shall have documented terms covering internal use, redistribution, caching and derived data. The system shall not redistribute provider data beyond those terms. | No license or terms inventory was found for SEC, OpenBB, yfinance, FMP, Polygon or FRED; no evidence either way was located in this stage. | repo-wide; docs/; api/main.py | — | **Unknown** | 0.60 | CAP-06, DF-01, DF-06 |

### 5.6 Testability

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `NFR-TEST-01` | CI shall measure line and branch coverage, publish the report and fail below a ratcheting threshold. Coverage shall include SQL builders, CLI branches and error paths, not only imported modules. | CI runs bare pytest -q; pytest-cov is not a dev dependency; no coverage configuration or threshold exists. | .github/workflows/ci.yml; scripts/crispdm_validate.py; requirements-dev.txt | — | **Missing** | 1.00 | TG-14, SVC-F07 |
| `NFR-TEST-02` | Every production SQL constant and loader statement shall be executed against a migrated warehouse or at least explained by the database. Substring assertions alone shall not count as coverage. | FORWARD_RETURN_SQL is never executed; universe and feature SQL are asserted as substrings; several tests use fake connections that only capture SQL. | tests/test_returns.py; tests/test_portfolio.py; tests/test_feature_carry_forward.py; src/crispdm/returns.py | build_forward_returns; UNIVERSE_SQL; build_features | **Partial** | 0.90 | TG-09, TG-16, PA-P15 |
| `NFR-TEST-03` | The suite shall include fixtures that fail on post-formation data, current-state universe flags, most-recent macro revisions, missing clock injection, unsorted labels and arbitrary tie-breaks. These tests shall be required in CI. | No clock freeze or two-date replay test exists; universe tests assert current active; the backtest loader ignores the requested window; no macro-vintage integration test. | tests/; src/crispdm/model.py; src/crispdm/backtest.py; src/crispdm/features.py | walk_forward; run_walk_forward; build_features | **Missing** | 0.95 | TG-03, TG-04, TG-06, TG-18, TG-19, DA-19 |
| `NFR-TEST-04` | Every CLI or module advertised in the README, ops catalog or runbook shall have a test that executes its main path or help path. Checkpoint and manifest builders shall have a contract test that fails on signature or field drift. | Only 11 of 107 test modules call a script main; the dry-run walk-forward command is broken; the ops catalog has 22 tasks but no parametrized help-path test. | tests/; scripts/ops_worker.py; src/crispdm/ops/catalog.py; scripts/dry_run_walk_forward.py | main; build_argv; TaskDef | **Partial** | 0.90 | TG-01, TG-15, BI-29 |

### 5.7 Reliability

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `NFR-REL-01` | The nightly pipeline shall fail closed on a required-stage failure, preserve the last known-good state, record stage-level diagnostics and surface freshness or gate failures to verification and the dashboard. | The last four nightly runs (57-60) failed and the warehouse is stale since 2026-11-09; audit records stage names and exit codes but no root-cause excerpt. | scripts/run_full_etl.py; scripts/verify_nightly_run.py; audit.nightly_runs | run_module; record_nightly_run; main | **Partial** | 1.00 | SVC-F04, SVC-F05, DA-11 |
| `NFR-REL-02` | Re-running a stage or the full pipeline shall produce the same logical result without duplicates, and a failed run shall be resumable from the last completed stage. A concurrent run shall fail closed without partial writes. | The pipeline holds an advisory lock and exits 2 on contention, but stages have no checkpoint or per-stage idempotency contract; duplicate-key batch behavior is unverified. | scripts/run_full_etl.py; scripts/ops_worker.py; src/crispdm/ops/store.py | run_module; main; loop_once | **Partial** | 0.90 | CMP-F01, CMP-F02, SVC-F12, DA-21 |

### 5.8 Scalability

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `NFR-SCALE-01` | The system shall process the current scale of roughly 9.8 million price rows and 9.8 million feature rows, and shall expose query bounds such as row limits and read-only explorer transactions so a user cannot trigger an unbounded scan. | raw.market_data holds 9,823,774 rows and model.features 9,756,631; explorer enforces a 5,000-row cap and a read-only transaction. | src/crispdm/explorer.py; raw.market_data; model.features | run_query; build_query; Dataset | **Implemented** | 0.85 | DF-06, DF-16, CMP-F11 |
| `NFR-SCALE-02` | The ops worker and API shall have documented concurrency and rate limits, queue-depth visibility and a tested behavior when those limits are reached. The single-worker model shall be stated as a capacity constraint. | The worker executes one task at a time and polls every five seconds; the API has a sliding-window limiter; no load or queue-depth test exists. | scripts/ops_worker.py; api/main.py; src/crispdm/ops/store.py | loop_once; require_api_key; _SlidingWindowLimiter; _SlidingWindowLimiter | **Partial** | 0.90 | SVC-F06, CAP-25 |

### 5.9 Security

| ID | Requirement | Evidence | Files | Functions / classes | Status | Conf. | Source findings |
|---|---|---|---|---|---|---|---|
| `NFR-SEC-01` | The data API shall require an API key for non-health endpoints and enforce a documented rate limit, returning a clear error when the key is missing or the limit is exceeded. | api.main exposes a public health endpoint and applies require_api_key plus _SlidingWindowLimiter to data routes; tests cover auth and limits. | api/main.py; tests/test_api.py | require_api_key; _SlidingWindowLimiter; health; _SlidingWindowLimiter | **Implemented** | 0.95 | CAP-25, SVC-03 |
| `NFR-SEC-02` | Operational execution shall accept only catalog-listed modules with validated parameters, require operator authentication, and expose warehouse browsing through an allowlisted read-only transaction with bounded rows. | ops.catalog fixes module names and coerces parameters; ops auth gates the worker; explorer runs SET TRANSACTION READ ONLY with MAX_ROWS 5,000. | src/crispdm/ops/catalog.py; src/crispdm/ops/auth.py; src/crispdm/explorer.py | get_task; validate_params; build_argv; run_query; TaskDef, Dataset, Throttle | **Implemented** | 0.90 | CMP-F10, CMP-F11, CAP-23 |
| `NFR-SEC-03` | Credentials shall be supplied through environment or mounted files excluded from version control, and containers shall run as non-root with a read-only root filesystem where feasible. Secrets shall not appear in logs or artifacts. | Secrets are gitignored; Dockerfile and compose use non-root UIDs, read-only rootfs, tmpfs and cap_drop ALL for API and UI services. | Dockerfile; docker-compose.yml; .gitignore; src/crispdm/config.py | Settings; Settings | **Implemented** | 0.90 | CAP-18, SVC-03 |

## 6. Constraints

| ID | Constraint |
|---|---|
| `C-01` | The recovery is read-only: no source, test or configuration changes; only Markdown under docs/speckit-recovery/ is written. |
| `C-02` | PostgreSQL 17 is the canonical warehouse; sql/schema.sql and forward-only migrations define the schema. |
| `C-03` | Python 3.12 is the runtime in Docker and CI; tests require a PostgreSQL service. |
| `C-04` | SEC, OpenBB/yfinance, FMP, Polygon and FRED/ALFRED remain external provider dependencies. |
| `C-05` | The nightly ETL is a host process, not a Compose service, and may be scheduled by systemd or Airflow. |
| `C-06` | The production signal is rule-based percentile scoring; the logistic-regression walk-forward model is gated and not the default ranking. |
| `C-07` | No text, transcript, news or sentiment feed is in scope until a timestamped source is ingested. |
| `C-08` | No database write or pipeline re-run is permitted for recovery evidence; live probes are SELECT-only. |
| `C-09` | Warehouse counts and artifact contents are a snapshot taken on 2026-11-15. |

## 7. Assumptions

| ID | Assumption | Impact if false |
|---|---|---|
| `A-01` | Stored raw closes are the provider's split basis; whether every close is fully split-adjusted is Unknown (FA-U01). | Split adjustment of every historical close is wrong to an unknown degree. |
| `A-02` | Yahoo dividend amounts are already on the split-adjusted basis; the code assumes this at confidence 0.6 (FA-U03). | Dividend amounts across providers are not on one basis. |
| `A-03` | The five stored lineage fields are representative of the intended lineage model, not its full scope. | Lineage coverage is even narrower than observed. |
| `A-04` | The last four failed nightly runs did not publish partial rows that downstream readers treat as current. | Downstream readers may have consumed partial failed-run output. |
| `A-05` | Provider payloads replaced by latest-only upserts cannot be recovered from an external archive inside this repository. | Past raw states are unrecoverable from this repository. |
| `A-06` | The rules in docs/data-health-workstreams.md describe the intended policy history, though the docs may be stale. | Policy history and maturity claims may be understated. |
| `A-07` | A report or worksheet's displayed date is intended to be its analysis as-of date; BI-37 leaves Reports Center behavior Unknown. | Reports may be mislabelled rather than merely unstamped. |

## 8. Business Rules

| ID | Rule | Evidence |
|---|---|---|
| `BR-01` | A security must meet the configured factor-weight coverage floor (0.50) before a composite score is published. | scoring.MIN_PRESENT_WEIGHT = 0.50 |
| `BR-02` | A dividend is credited only when it does not exceed the prior close; the inclusive boundary is currently untested. | MAX_SINGLE_PAYMENT_RATIO = 1.0 |
| `BR-03` | The default book holds 15 long and 8 short equal-weight positions, 150 percent gross and 50 percent net. | portfolio.LONG_COUNT / SHORT_COUNT / weights |
| `BR-04` | The label horizon is 365 days and training folds must purge labels that overlap the test period. | settings.label_horizon_days = 365; model.walk_forward |
| `BR-05` | A confirmed split applies only when the observed move is within 10 percent of the reported ratio. | SPLIT_TOLERANCE = 0.10 |
| `BR-06` | Unresolved dividend amounts are rechecked after seven days; no-evidence and disagreement currently share one verdict. | RECHECK_UNRESOLVED_DAYS = 7 |
| `BR-07` | The ML gate requires all folds and fails closed on skipped folds or placeholder features. | walk_forward_folds(..., requires_all_folds=True) |
| `BR-08` | Only OPENBB dividend rows enter total return; SEC_XBRL period aggregates are excluded by design. | returns.FORWARD_RETURN_SQL OPENBB filter |
| `BR-09` | An LLM draft is optional, schema-validated and never auto-saved. | app/llm_client.py; worksheet save path |

## 9. Domain Invariants

| ID | Invariant | Current evidence |
|---|---|---|
| `I-01` | For a fixed as-of date, feature, score and backtest outputs are byte-identical on repeated runs with the same inputs and code. | Not enforced; DA-19 finds no determinism test. |
| `I-02` | Every published score has exactly one run id, one feature-set hash and one data version. | Violated; model.scores has no run id (DA-02). |
| `I-03` | For any published result, raw input to report lineage is walkable without parsing free-text logs. | Partly; lineage covers five fields only (DA-13). |
| `I-04` | No historical computation reads a row whose availability timestamp is later than its as-of date. | Violated by 14-day cleaning, full-history median and latest macro (BI-03, PA-F04, DA-04). |
| `I-05` | Sum of long weights minus absolute sum of short weights equals net exposure; absolute sums equal gross exposure. | Holds by construction in select_portfolio. |
| `I-06` | Every dividend is credited exactly once, on the first priced row on or after its ex-date. | Mostly; missing-close rows can drop a credit (PA-P12). |
| `I-07` | An identifier interval is open for at most one security at any timestamp. | Violated; 1,630 tickers have multiple open intervals (BI-23). |
| `I-08` | A failed required stage leaves the previous known-good warehouse state readable. | Partly; no stage checkpoint or resume contract (NFR-REL-02). |

## 10. Failure Modes

| ID | Failure mode | Source | Risk |
|---|---|---|---|
| `FM-01` | A replay re-scores a past date under current rules and overwrites the as-produced score, so the backtest reads a look-ahead result. | DA-02, BI-04, TG-07 | High |
| `FM-02` | A NULL dividend date payload overwrites a populated date, erasing the only record of the declaration or payment date. | DA-05, PA-D06 | High |
| `FM-03` | The latest macro revision feeds a historical Sharpe ratio, producing an unattainable result. | DA-04, BI-14, TG-18 | Medium |
| `FM-04` | A confirmed split with a large real move is left unadjusted and appears as a one-day crash. | PA-P02, PA-F06 | High |
| `FM-05` | A survivor-only universe removes delisted names, inflating historical returns. | BI-01, TG-04 | Critical |
| `FM-06` | Post-formation prints change period membership, leaking future information into selection. | BI-03, PA-P05, TG-06 | High |
| `FM-07` | A stale backtest artifact with a removed rule set is served as current by the dashboard. | DA-09, BI-21 | High |
| `FM-08` | A provider order change or duplicate key silently changes a price or score. | DA-08, DA-21 | Medium |
| `FM-09` | A label rebuild erases the training labels used by an earlier model run. | DA-16 | High |
| `FM-10` | An unpinned environment installs different library versions and changes model or UI behavior. | DA-17 | High |
| `FM-11` | A report opened later mixes current data with a past analysis date without a warning. | DA-20, BI-37 | Medium |
| `FM-12` | Releasing a ticker conflict deletes the security and its dependent history. | DA-14, BI-24 | Medium |

## 11. Trace Conventions and Limits

- Source audit IDs are preserved verbatim: `PA-` (Stage 1A), `BI-` (Stage 1B), `TG-` (Stage 1C), `DA-` (Stage 1D), `CAP-`/`CMP-`/`SVC-`/`DF-` (Stage 0).
- `TBD` requirement IDs in the earlier audit registers are now resolved by this register; the earlier files were not edited.
- The Stage 1D template named `01-audits/auditability/` with an `AU-` prefix; actual evidence is under `01-audits/determinism/` with `DA-`. This is a documented deviation, not a missing input.
- No requirement claims external provider terms, off-repository archives or scheduler state. Those remain Unknown.
- Status is about implementation, not research validity. A function may be implemented and still produce a biased result; the source finding carries that risk.

## 12. Coverage Summary

| Measure | Value |
|---|---|
| Functional requirements | 53 |
| Non-functional requirements | 31 |
| Implemented | 18 (21.4%) |
| Partial | 53 (63.1%) |
| Missing | 12 (14.3%) |
| Unknown | 1 (1.2%) |
| Linked to at least one audit finding | 84 (100.0%) |
| Requirements with no direct test | 24 |

Detailed counts by category, phase and confidence band are in `coverage-statistics.md`. Requirement-to-test and requirement-to-evidence links are in `rtm.md`.
