# Bias and Temporal Integrity Assessment (Stage 1B)

| Field | Value |
|---|---|
| Stage | 1B — Bias and data integrity |
| Companions | `findings.md` (BI-01…BI-38), `leakage-paths.md` (LP-01…LP-41) |
| Method | Read-only static audit; warehouse SELECT queries for survivorship and identity; no pipeline runs; no tests run |
| Framing | Each check lists evidence **for** and **against** leakage or bias. No check is presumed to pass. |
| Type key | V = Verified (read in code, docs, or SELECT); I = Inferred; A = Assumption; U = Unknown |

## 1. Verdict

The point-in-time machinery is sound where it has been built: fundamentals vintages, feature windows, walk-forward purge, and per-fold fitting. The material bias sits in four places:

1. **The universe is current-state.** Survivorship and classification are evaluated against today's flags (BI-01, BI-07). This is the largest single bias source and affects every downstream metric.
2. **Selection uses post-formation information.** Eligibility and cleaning read up to 14 days after formation (BI-03). Scores are overwritten on replay, so the history cannot be audited as it was produced (BI-04).
3. **The validation record is not clean.** One holdout block is reused across gates, guardrails, policy revisions, and label changes (BI-05, BI-06). The headline artifacts do not reproduce from current code (BI-21).
4. **Unpublished data is visible in places.** SEC dividend and some fundamentals rows are usable before filing (BI-02, BI-10).

The Stage 1B audit does not conclude that the strategy is profitable or unprofitable. It concludes that the reported performance cannot yet be read as out-of-sample skill.

## 2. Assessment by Check

Each row gives the check, the evidence for leakage, the evidence against, and a verdict.

### 2.1 Point-in-time fundamentals

| Check | For leakage | Against leakage | Verdict | Refs |
|---|---|---|---|---|
| Filing date vs period-end date | `GREATEST(filed, period_end)` clamp moves availability earlier when `filed < period_end` (966 rows per code comment, not re-measured) | Normal rows use true `filed`; as-of join uses `observation_date >= filed` | **Partially guarded**; clamp is open (BI-10) | `features.py:939-950, 1051-1053` |
| Restated values visible to historical dates | None for the quarterly `LEAD`-interval join | Each vintage visible only from its own `filed` date | **Guarded** | `features.py:1018-1024, 1051-1053`; `fundamentals.py:87-105` |
| Annual statistics | Not forward leakage | `max()` across vintages ignores downward restatement | **Correctness defect** (BI-11) | `portfolio.py:149-166` |
| Run-date ceiling | None | `period_end > as_of` excluded; V0078 removes future periods | **Guarded** | `fundamentals.py:196-197`; `populate_fundamentals.py:294`; `V0078` |
| Raw SEC payload history | Latest-only upsert loses prior snapshots | Companyfacts carries fact vintages; PIT may be rebuildable (A) | **Auditability gap** (BI-12) | `schema.sql:650-658`; `api/main.py:258-276` |

### 2.2 Dividends and corporate actions

| Check | For leakage | Against leakage | Verdict | Refs |
|---|---|---|---|---|
| SEC dividend ex-date | `ex_dividend_date = period end`; `filed` dropped; `d_declared`/`d_annual` join on `ex <= observation_date` | OpenBB precedence in `COALESCE`; XBRL path is fallback (~660 securities per comment) | **Open** (BI-02) | `features.py:774-781, 858-868, 1116-1138`; `populate_dividend_data.py:328, 335, 361-380` |
| Dividend calendars used before announcement | None: no reader in `src/`, `app/`, `api/` | Calendar tables have no consumer | **Guarded by absence** | Stage 1B grep; `V0099` |
| Upcoming-dividends view | `upcoming_dividends` uses `CURRENT_DATE` (non-PIT if read in a replay) | No consumer today | **Latent** | `V0099` |
| Label eligibility | Eligibility counts XBRL proxies filed after `as_of` | Outcome window strictly after `as_of` | **Open** (BI-16) | `label_targets.py:113-120` |
| Split restatement at historical dates | Restatement uses splits known at ingestion (see Stage 1A PA-F/FA-S03) | — | **Open** (inherited from Stage 1A) | `openbb_client.py:230-261` |

### 2.3 Universe construction and survivorship

| Check | For bias | Against bias | Verdict | Refs |
|---|---|---|---|---|
| Active, dividend, and type flags | Evaluated against today; names that stopped paying or were delisted are absent from features, labels, and backtest | Historical recovery path exists (V0094, `load_historical_securities.py`) but is opt-in and documented as limited | **Open, Critical** (BI-01) | `populate_dividend_data.py:643-650`; `feature_window.py:85,93`; `portfolio.py:91` |
| Delisted names in price history | Survivorship audit (SELECT): 6,342 securities have prices; only 1 has a last observation before 2026. Structural absence of pre-2026 delistings | 29 later-inactive IDs appear in score history (1,332 rows, 2019–2026) | **Open** (BI-01); doc claim "6,423 of 6,424" holds qualitatively | `docs/AnalystDashboard.md:209-215` |
| Inactive or mis-typed names in the live book | `UNIVERSE_SQL` has no `active` predicate; preferred and ETN-like identities carry common-stock type; inactive longs appear in the 2026-10-30 book (CHTRP, SATA) | `feature_window.py` filters `active`; ticker reuse not double-counted; classification evidence is name- and tape-based and needs SEC confirmation | **Open, High** (BI-07) | `portfolio.py:55-93`; `feature_window.py:85,124` |
| Delisted holdings in replay | Forward-fill gives zero return after last print (upward bias once survivorship is corrected) | Currently inactive by universe default | **Latent** (BI-09) | `portfolio.py:325-330` |
| Identity continuity across ticker change | `resolve_security_ids` cannot resolve across change (0 closed ticker intervals) | Backtest keys on `security_id`, so the scored history is not split by this path | **Open** (BI-23) | `identity.py:19-31` |
| History deletion | Release and merge tools delete rows | Archive written first | **Open, Medium** (BI-24) | `resolve_ticker_conflict.py`; `merge_duplicate_identities.py` docstrings |
| Index membership as-of | No index-constituent data exists in the repo | — | **Absent** (not a leak; a missing control) | git grep |

### 2.4 Backtest timing, scoring, and benchmarks

| Check | For bias | Against bias | Verdict | Refs |
|---|---|---|---|---|
| Signal date vs trade date | Score uses formation close; execution assumed at same close | Returns start after formation (`(start, end]`) | **Partially guarded** (BI-17 execution Inferred) | `backtest.py:112-113` |
| Rebalance lag | None: no lag modelled | — | **Open, Medium** (sensitivity needed) | `backtest.py` |
| Selection and cleaning window | Eligibility and reversal confirmation use prints to end + 14 days | Returns stop at `end`; rejected print replaced by last accepted (past) close | **Open, High** (BI-03) | `backtest.py:27, 88-95`; `portfolio.py:730-737, 753-761` |
| Score replay | Replays use current rules, universe, and cleaning | Feature and score rows are point-in-time by construction | **Open, High** (BI-04) | `score_rank.py:161-170, 267-290` |
| Z-scores and normalization | Percentile rank computed per scoring run over the carried-forward cross-section; a 7-day carry can mix dates within one run | No future data enters; comparability note only | **Guarded** (Low note) | `scoring.py:93-95`; `score_rank.py:171-177`; `config.py:51` |
| Validated baseline volatility | Full-period σ for inverse-vol weights | Path not wired to any production entry point | **Latent, Medium** (BI-15) | `backtest.py:314-315` |
| Benchmark exposure | 100% net-long equal-weight vs 150% gross / +50% net book | Same cleaned universe, so price-source alignment holds | **Open, High** (BI-08) | `backtest.py:128-133`; `portfolio.py:281-290` |
| Cash-period calendar | Weekday index includes holidays; benchmark zero | No impact in latest artifact | **Open, Low** (BI-27) | `backtest.py:206` |
| Sort and concatenation | None | Periods disjoint; sorts before walk-forward | **Guarded** (BI-33) | `model.py:464, 492`; `backtest.py:160-161` |

### 2.5 Machine learning and validation

| Check | For bias | Against bias | Verdict | Refs |
|---|---|---|---|---|
| Purge and embargo | None | Training rows whose 365-day label window closes before test start are kept; `D + horizon < test_start` | **Guarded** | `model.py:337-342` |
| Scaler and imputer per fold | None | Inside Pipeline; fit on training rows | **Guarded** | `model.py:92-94, 406-407` |
| Threshold selection | None | Chosen from training predictions | **Guarded** | `model.py:408` |
| Holdout reuse | One 50% tail block reused for gate, guardrail, revisions, label change | Purge is correct; training-only fitting | **Open, High** (BI-06) | `model.py:469-525`; `evaluate_walk_forward.py:233-270` |
| Criteria revised after results | `MIN_PR_AUC_LIFT` removed after fold 4 failed; `MAX_FLAG_RATE` added after a 4/4 GO | Threshold fitting itself uses training data; guardrail does not gate pass/fail | **Open, High** (BI-05) | `model.py:201-203, 219, 245-253`; `docs/data-health-workstreams.md:145-165` |
| Guardrail derivation | Described as empirical; algebraically equals the 0.02 margin restated | — | **Open, Medium** (BI-22) | `evaluate_walk_forward.py:174-214` |
| Negative-recall gate | At 0.20 flag budget, random flagging already gives ~0.20 recall | Balanced-accuracy lift is the discriminating check | **Weak gate** (Medium, from survivorship audit) | `model.py:202, 219` |
| Label negative rate decay | Attributed to regime; feed-coverage growth (1,914→2,844 securities) is an untested alternative | — | **Unresolved** (BI-19) | `docs/data-health-workstreams.md:117-122` |
| Validation helpers | Default 63-day horizon vs 365-day label | Not used in production | **Latent** (BI-28) | `validation.py:83, 125` |
| Dry-run script | Calls signatures that do not exist | Not production | **Latent bug** (BI-29) | `dry_run_walk_forward.py:83-84` |

### 2.6 Calendar and timezone

| Check | For bias | Against bias | Verdict | Refs |
|---|---|---|---|---|
| Observation date type | None | `observation_date DATE`, no time zone | **Guarded** | `schema.sql:161-163` |
| Filing acceptance time | Filings accepted after close treated as public on the filing date | Date-granular comparison is one-session optimistic | **Open, Low** (BI-25) | `features.py:1051-1053, 1112-1113` |
| Weekday vs trading calendar | See §2.4 | — | **Open, Low** (BI-27) | `backtest.py:206` |

### 2.7 Caching, joins, and sorts

| Check | For bias | Against bias | Verdict | Refs |
|---|---|---|---|---|
| Latest-visible-row selection | None | `ROW_NUMBER ... ORDER BY period_end DESC` correct | **Guarded** | `features.py:1044-1046, 1114` |
| Non-EPS `DISTINCT ON` ties | Arbitrary row when labels disagree | — | **Latent, Low** (BI-32) | `features.py:947-962` |
| Price LATERAL without `ORDER BY` | Arbitrary price row if duplicates | 0 duplicate rows currently | **Latent, Low** (BI-31) | `portfolio.py:79-84` |
| Predictions merge | None | Left merge on `(security_id, as_of_date)` | **Guarded** | `scoring.py:341` |

### 2.8 Text, consensus, macro, and AI

| Check | For bias | Against bias | Verdict | Refs |
|---|---|---|---|---|
| Consensus and estimate revisions in model | None: absent | Latest snapshot only; not in features, scores, or labels | **Guarded by absence** (BI-13 for autofill) | `schema.sql:425-478`; `features.py`, `scoring.py` |
| Analyst data in worksheet autofill | Latest DCF and profile fields used for a possibly past-dated analysis | Worksheet use is human-reviewed; nothing auto-saved | **Open, Medium** (BI-13) | `analysis_autofill.py:585-604, 1695` |
| Macro in model | None | `read_macro_state` returns None | **Guarded** (BI-26 in leakage-paths LP-26) | `score_rank.py:16-30` |
| Macro in metrics | Risk-free uses latest revision | ALFRED path exists and is correct | **Open, Medium** (BI-14) | `portfolio.py:104-110, 615`; `macro_vintages.py` |
| Macro in memos and API | Latest values presented | Presentation only | **Open, Low** (BI-35) | `macro_inputs.py:605-618` |
| Transcripts, surprises, sentiment, news | None: no ingestion | Absence, so no text path exists | **Guarded by absence** (BI-36) | repo-wide grep |
| LLM worksheet draft | Live provider data and latest DB rows; `now()` default date; no stored as-of enforced on autofill | Optional, disabled by default, nothing written without review | **Open, Medium** (BI-34) | `analysis_autofill.py:61, 546-549, 585-604, 653`; `app/llm_client.py` |
| Peer analogs | Industry classification is a current snapshot applied to historical dates | Conditions read as-of each historical date; monthly sampling controls overlap | **Open, Medium** (BI-18) | `analogs.py:12-16, 22-28, 33-34` |
| Reports Center labelling | Not verified | — | **Unknown** (BI-37) | `dashboard.py` `_reports` (not read in this stage) |

### 2.9 Parameter selection and result governance

| Check | For bias | Against bias | Verdict | Refs |
|---|---|---|---|---|
| Cleaning thresholds | Iterated v1–v6 against backtest outcomes; `thin_v6` added then removed | Rule removal was a correction (adjustment artifact) | **Open, Medium** (BI-20) | `portfolio.py:654-670`; commits `5aef921`, `e1305f3`, `84fa31d` |
| Coverage floor | Moved 0.25 → 0.50 after counting cohorts | Documented | **Open, Medium** (BI-20) | `portfolio.py:42`; `data-health-workstreams.md:1484-1524` |
| Long and short counts (15, 8) | No derivation or sensitivity | Stated design | **Undocumented** (BI-20) | `portfolio.py:37-38` |
| Reported artifacts | Headline numbers from a different rule set than current code | Docs state the rule set | **Open, Medium** (BI-21) | `metrics_20261102_153616.json`; `AnalystDashboard.md:179-189` |
| Replay reproducibility | `date.today()` defaults | Explicit `as_of` makes replay deterministic | **Open, Medium** (BI-38) | `identity.py:53-66`; `sec_client.py:1465` |

## 3. Controls Verified (Against Leakage)

| Control | Evidence | Confidence |
|---|---|---|
| Fundamentals as-of join selects exactly one vintage per date | `features.py:1018-1024, 1051-1053`; tests `test_fundamentals_and_predictions.py` (restatement and vintage tests) | 0.9 |
| Run-date ceiling on fundamentals | `fundamentals.py:196-197`; `populate_fundamentals.py:294` | 0.9 |
| Future-dated periods removed | `V0078`; `test_api.py:79-102` (forward-dated period never served as latest) | 0.9 |
| Feature anchor cannot read future rows | `feature_window.py:31-35, 73-77`; live test `test_feature_carry_forward.py:250-275` (passed in Stage 1A run) | 0.95 |
| Momentum and volatility use trailing windows | `features.py:727-737, 1231-1242` | 0.95 |
| Label outcome strictly after as-of | `label_targets.py:55-56, 92-93, 121` | 0.9 |
| Walk-forward purge | `model.py:337-342`; test `test_label_targets` and walk-forward tests | 0.95 |
| Per-fold scaler and imputer | `model.py:92-94, 406-407` | 0.95 |
| Threshold chosen on training predictions | `model.py:408` | 0.9 |
| Returns after formation | `backtest.py:112-116` | 0.85 |
| Calendar tables not read by features or backtest | Grep (Stage 1B) | 0.9 |
| ALFRED as-of query correct | `macro_vintages.py:16-23, 59-64` | 0.9 |
| Analogs condition on historical as-of values; monthly sampling | `analogs.py:12-28` | 0.9 |

## 4. Quantities Not Measured

Per the ground rules, these magnitudes are not stated as fact. Each is marked Unknown and would need a measurement.

| Quantity | Why it matters | Source of the only number |
|---|---|---|
| Size of the survivorship effect (BI-01) | Direction is upward for long-side; magnitude unknown | None in repo; docs say net effect unknown |
| Rows affected by the period-end clamp (BI-10) | Scope of LP-03 | Code comment: 966 rows, 612 over a year early (not re-measured) |
| Share of `dividend_yield` from XBRL fallback (BI-02) | Scope of LP-01 | Comment: "~660 securities" (not re-measured) |
| Share of label eligibility from SEC proxies (BI-16) | Selection bias scope | Not measured |
| Effect of 14-day lookahead on book (BI-03) | Eligibility change | Not measured |
| Effect of the 50/50 benchmark mismatch (BI-08) | Comparison validity | Not measured |
| Feed-coverage share of label decay (BI-19) | Attribution of the 13.6% → 0.96% decline | Not measured |

## 5. Recommended Actions (priority order)

1. **Build a point-in-time universe** with `(security_id, valid_from, valid_to)` and delisting data. Gate the live book on `active` as of formation (BI-01, BI-07). Report the survivor-vs-PIT delta.
2. **Gate SEC dividend and fallback fundamentals on `filed`** and fix the period-end clamp (BI-02, BI-10).
3. **Make selection causal:** eligibility and cleaning decisions use data up to formation only (BI-03).
4. **Archive scores per run** with `run_id`, `scored_at`, and a code hash; backtest only archived scores (BI-04).
5. **Freeze a final holdout** and the acceptance policy before any further GO claim. Disclose the existing GO-without-flag-check history (BI-05, BI-06, BI-22).
6. **Add an exposure-matched benchmark** and regenerate artifacts with the code hash (BI-08, BI-21).
7. **Require `as_of` in replay paths** and stamp it on worksheets, autofill inputs, and reports (BI-34, BI-37, BI-38).
8. Clean up latent items: BI-09, BI-15, BI-28, BI-29, BI-31, BI-32.

## 6. Limits of This Assessment

- Static audit plus SELECT-only queries. No test was run in Stage 1B, and no pipeline or backtest was re-executed.
- The AI-path audit subagent failed three times on an upstream error. Its coverage was re-done by targeted grep and two file reads (`analysis_autofill.py:540-564`, `analogs.py:1-60`). Reports Center labelling (BI-37) was not read and is Unknown.
- Survivorship and identity figures come from one SELECT-based explore pass. The mis-typing evidence is name- and tape-based and must be confirmed against SEC records before correction.
- Figures quoted from docs and code comments are attributed and not re-measured.
