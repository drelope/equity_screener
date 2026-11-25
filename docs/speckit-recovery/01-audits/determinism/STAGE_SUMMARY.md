# Stage 1D — Determinism and Auditability: Stage Summary

| Field | Value |
|---|---|
| Status | Complete (review); no source, test, or config changes |
| Output | `docs/speckit-recovery/01-audits/determinism/` |
| Inputs | `01-audits/price-adjustment/` (PA-D06, PA-D08, PA-D16, PA-D17, PA-D19, PA-D20); `01-audits/bias/` (BI-04, BI-12, BI-14, BI-21, BI-24, BI-31, BI-32, BI-38); `01-audits/testing/` (TG-01, TG-03, TG-07, TG-15, TG-18, TG-19) |
| Repo HEAD | `d748cea` |
| Date | 2026-11-15 |

## 1. What Was Done

| Pass | Scope | Outcome |
|---|---|---|
| Clock audit | Traced every replay-visible `date.today()`, `pd.Timestamp.now()`, and `CURRENT_DATE` | Ten Python call sites across nine components, plus the nightly `run_date` stamp and five SQL/report `CURRENT_DATE` sites; every path can be made deterministic by explicit `as_of`, none requires it (DA-01, DA-20) |
| Store audit | Keyed, counted, and read the writers for raw, feature, score, prediction, audit, and calendar stores | Scores and feature rows are mutable; SEC payloads, dividends, macro, and calendars are latest-only; predictions and ticker-profile loads are the positive precedents (DA-02, DA-03, DA-05, DA-06, DA-12, DA-15) |
| Ordering audit | Read every `DISTINCT ON`, `LIMIT 1`, `drop_duplicates`, and price join | One live arbitrary fundamentals tie-break; multi-provider price hazards latent but unguarded (DA-07, DA-08, DA-21) |
| Run provenance | Compared checkpoint JSON, `audit.model_runs`, nightly records, and backtest artifacts | Policy version exists only in JSON; nightly has no code/env stamp; backtest artifacts have no manifest (DA-09, DA-10, DA-11, DA-18) |
| Reconstructability | Traced four questions: score, headline backtest, dividend date, acceptance policy | Only predictions are run-addressable end-to-end; the other traces break at mutable or unstamped stores (inventory §2–§3) |
| Environment | Compared committed pins, worktree `requirements.txt`, installed packages, and CI/Docker installs | Worktree is an unpinned freeze with no lockfile; installed pytest/streamlit already drift from pins (DA-17) |
| Test coverage | Reused Stage 1C determinism findings; checked for clock/order/version regression tests | No clock freeze, no two-date replay, no ordering assertions, no provenance assertions (DA-19) |

No writes were issued to the warehouse, no pipeline or backtest was re-run, and no source, test, or config file was changed.

## 2. Files Produced

| File | Contents |
|---|---|
| `findings.md` | DA-01…DA-21 register in the mandated row format; input cross-reference; severity rationale; controls present; limits |
| `determinism-inventory.md` | Clock defaults, replay matrix, ordering/tie-breaks, mutable stores, runtime pins, verification queries |
| `auditability-inventory.md` | Store-by-store evidence table, question-to-evidence matrix, checkpoint/artifact/nightly inventories, provenance maturity, minimum run manifest |
| `provenance-map.md` | End-to-end Mermaid map, hop-by-hop losses, four trace walkthroughs, provenance breaks, target lineage |
| `STAGE_SUMMARY.md` | This file |

Register size: 21 findings — 8 High, 13 Medium, 0 Low.

## 3. Headline Results

| Rank | Result | Type | Confidence |
|---|---|---|---|
| 1 | Score history is mutable and unaddressable. `model.scores`/`rankings` hold 464,691 rows over 271 dates (2019-01-31..2026-11-06) keyed only by `(security_id, as_of_date)`; a past-date re-score overwrites the as-produced row. The backtest cannot distinguish the two. | Mutable history | 1.0 |
| 2 | Raw SEC payloads are latest-only. `raw.companyfacts` (7,177 CIKs) and `raw.sec_submissions` (8,208 CIKs) replace the stored payload on change, so the retrieved state behind a past feature row cannot be reconstructed. | Mutable history | 1.0 |
| 3 | The headline backtest does not reproduce from current code. The latest artifact records `price_filter=..._thin_v6` while current code is `..._v5`; the JSON has no run id, code SHA, data version, costs, or benchmark definition, and the dashboard serves the newest timestamped file. | Incomplete provenance | 1.0 |
| 4 | Acceptance-policy provenance is split. The JSON checkpoint records the policy contract; `audit.model_runs` does not persist `acceptance_policy_version` or `generated_at`. The DB has 18 runs but only one canonical JSON checkpoint remains. | Incomplete provenance | 1.0 |
| 5 | Dividend dates are overwritten with NULL on re-run. `DIVIDEND_UPSERT` takes `declaration_date`, `record_date`, and `payment_date` from `EXCLUDED`, so a later OpenBB payload that omits them erases earlier values (PA-D06). | Mutable history | 0.95 |
| 6 | The risk-free series uses the latest macro revision, not the as-of vintage. `raw.macro_series` has 1,796 latest rows while `raw.macro_series_vintages` keeps 105,865 revisions; the correct as-of reader has no production caller (BI-14/TG-18). | Incomplete provenance | 0.95 |
| 7 | Replay defaults to the wall clock. Identity resolution, SEC classification, payer universe, frame periods, labels, historical universe, calendar windows, macro fetch, and autofill all default to today; Stage 1C found no clock freeze or two-date test. | Clock dependence | 0.95 |
| 8 | The runtime is not reproducible. The worktree replaces 20 direct pins with a 238-line unpinned freeze (0 `==`), has no lockfile, and installed pytest 9.1.1 / streamlit 1.67.0 already differ from the committed 8.4.2 / 1.64.0. | Environment gap | 1.0 |
| 9 | Feature→score lineage is broken. All 9,756,631 feature rows carry `feature_set_hash`/`feature_version`, but scores carry neither, so a score cannot be tied to the feature definition that produced it. | Incomplete provenance | 0.95 |
| 10 | Positive controls exist: predictions are keyed by `run_id` with model/feature/data versions and config hash; `raw.ticker_profile_load` is append-only (210,009 rows); macro vintages are stored; the checkpoint contract detects drift; quarantine is append-only. The gap is propagation, not invention. | Verified control | 1.0 |

## 4. Verification Log

| Command or probe | Result |
|---|---|
| `git rev-parse --short HEAD` | `d748cea` |
| `git status --short` | `requirements.txt` and `opencode.json` modified; `docs/speckit-recovery/`, `.specify/`, `.opencode/`, `Modelfile`, and SpecKit JSON files untracked |
| `model.scores` probe | 464,691 rows, 5,133 securities, 271 dates, 2019-01-31..2026-11-06 |
| `model.features` probe | 9,756,631 rows, 6,342 securities, 2019-01-02..2026-11-06; all `features_v5`, hash `929658405dbc95be` |
| `model.predictions` probe | 216 run ids, 2026-10-17..2026-11-09 |
| `raw.dividend_data` probe | 323,632 rows: OPENBB 197,179, SEC_XBRL 126,453 |
| `raw.dividend_amount_check` probe | 354 unresolved, 171 fmp, 52 yfinance |
| `raw.calendar` probe | 2,121 events; 1,055 with ex-date after the probe date; 526 upcoming rows |
| `raw.macro_series` / `_vintages` probe | 1,796 latest rows / 105,865 vintage rows |
| `raw.companyfacts` / `raw.sec_submissions` probe | 7,177 / 8,208 CIKs |
| `raw.ticker_profile_load` probe | 210,009 append-only rows |
| `audit.source_lineage` probe | 26,297 rows across 5 fields; 0 missing version stamps |
| `audit.data_quality` probe | 343,627 rows, 32 dates, 2026-10-04..2026-11-09 |
| `audit.nightly_runs` probe | 53 runs, 2026-09-24..2026-11-15 |
| Checkpoint inspection | `generated_at=2026-10-06T20:19:50Z`, `run_id=d2eccb6c-7e23-48e7-ae28-d92b1dee8e92`, `gate_passed=false`, contract `balanced_acc_lift_and_negative_recall_v2` |
| Artifact inspection | 7 metrics files, 2026-10-26..2026-11-02; latest `metrics_20261102_153616.json` has no run id and `price_filter=..._thin_v6` |
| Requirements inspection | Worktree 238 lines / 0 `==`; HEAD 22 lines / 20 `==`; no lockfile |
| Test execution | None in Stage 1D; Stage 1C's 302-passed gap-area run and 1,929-test collection remain the latest suite evidence |

All warehouse probes were `SELECT` only. No `INSERT`, `UPDATE`, `DELETE`, DDL, or pipeline invocation was issued.

## 5. Unknowns and Limits

| ID | Unknown | Why it matters |
|---|---|---|
| U-1 | How often a wall-clock default actually changes a stored result | Proving the mechanism does not measure its historical impact; that needs controlled re-runs, which this stage did not perform |
| U-2 | Whether any operations runbook or external scheduler pins `as_of` | The repo defaults are wall-clock; an external caller may pass an explicit date |
| U-3 | Whether copies of overwritten SEC payloads, checkpoints, or dividend rows exist outside the repo | A backup or object store could restore history even though the warehouse does not |
| U-4 | Duplicate-key batch behaviour (raise vs silent last-write) | DA-21 is Unknown; resolving it requires a write experiment |
| U-5 | Reports Center as-of labelling (BI-37) | The explore agent failed in Stage 1B and the view was not re-read here; DA-20 covers the code that was read |
| U-6 | Contents and retention of `data/ticker_conflict_archive/*.json` | DA-14 relies on the writer path and archive format, not on an enumeration of existing files |
| U-7 | Warehouse snapshot identity | Counts are a 2026-11-15 snapshot; there is no snapshot marker to prove which state a past run read |
| U-8 | Installed environment beyond the checked packages | The audit checked pytest, streamlit, pandas, numpy, scikit-learn, sqlalchemy, psycopg, yfinance, and openbb; a full hash was not recorded |

## 6. Handoff to Next Stages

| Stage | Inputs from 1D |
|---|---|
| Stage 2 Requirements | NFR-REPRO: explicit `as_of`, immutable run manifest, pinned lockfile, artifact reproducibility. NFR-AUD: append-only raw payloads and provenance, no destructive delete, versioned scores/labels. NFR-DET: deterministic tie-breaks, authoritative provider, clock injection. NFR-GOV: persisted acceptance policy, run/label lineage, artifact gate. FR mapping: FR-BT (DA-09), FR-DIV (DA-05/06/15/21), FR-EVAL (DA-10/18), FR-FEAT (DA-07/12), FR-LABEL (DA-16), FR-MACRO (DA-04), FR-AI/FR-REP (DA-20), FR-UNI (DA-01/08) |
| Stage 3 Constitution | Candidate MUSTs: no row read by a later stage may be overwritten without a new run id; every report/artifact must name the run and as-of that produced it; every replay entry point must require `as_of`; every run must pin code, dependencies, and input snapshot |
| Remediation (post-stage) | P0: restore dependency pins; persist `acceptance_policy_version`/`generated_at`; add `run_id` + feature hash/version to scores; stop NULL date overwrite; stamp backtest artifacts. P1: append-only SEC landing; score archive; explicit `as_of`; provider `ORDER BY`. P2: calendar snapshots; append-only lineage; identity soft-delete; label runs |

## 7. Next Step

Stage 2 (requirements) is the next authored artefact: FR-UNI, FR-EVAL, FR-BT, FR-DIV, FR-FEAT, FR-MACRO, FR-AI, FR-LABEL, FR-REP and NFR-PIT, NFR-GOV, NFR-REPRO, NFR-AUD, NFR-DET, NFR-TEST.

There is still **no requirements register** in the repo, so a Stage 2 *validation* cannot run yet. Stage 1D completes the audit evidence the register must cite. After the register exists, validation can check each FR/NFR against the Stage 0–1D evidence before Stage 3 drafts the constitution.
