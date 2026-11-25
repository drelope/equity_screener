# Stage 1B — Bias and Temporal Integrity: Stage Summary

| Field | Value |
|---|---|
| Status | Complete (audit); no source, test, or config changes |
| Output | `docs/speckit-recovery/01-audits/bias/` |
| Inputs | `00-discovery/`, `01-audits/price-adjustment/` |

## 1. What Was Done

| Pass | Scope | Outcome |
|---|---|---|
| Explore agent A | Point-in-time fundamentals, consensus, macro vintages, dividend calendars, universe, backtest timing, walk-forward, calendar, caching | Completed; 18 findings (F-01…F-18) |
| Explore agent B | Survivorship, identity, benchmark alignment, sorts, parameter selection, test-set reuse, SELECT-only warehouse checks | Completed; 21 findings (I1…X1) |
| Explore agent C | AI, transcripts, summarization, LLM and autofill, analogs, regime, live fallbacks | **Failed three times** (upstream "assistant message prefill" and "thinking block" errors) |
| Orchestrator (replacement for C) | Targeted grep of `analysis_autofill.py`, `analogs.py`, `regime_pipeline.py`, `macro_inputs.py`, tests; two file reads | Covered the AI path at grep and read depth; Reports Center labelling not read (BI-37 Unknown) |

The orchestrator consolidated the three passes into 38 IDs (BI-01…BI-38) with 41 leakage paths (LP-01…LP-41).

## 2. Files Produced

| File | Contents |
|---|---|
| `bias-assessment.md` | Verdict, per-check for/against assessment across eight areas, verified controls, unmeasured quantities, priorities, limits |
| `leakage-paths.md` | Mermaid information-flow diagram; 41-path register with status (21 open, 2 latent, 18 guarded) |
| `findings.md` | BI-01…BI-38 register in the mandated row format; Stage 1A cross-reference; agent disagreements resolved |
| `STAGE_SUMMARY.md` | This file |

## 3. Headline Results

| Rank | Result | Risk | Type | Confidence |
|---|---|---|---|---|
| 1 | Universe is current-state (`active`, `dividend`, `security_type` evaluated today); survivorship bias throughout features, labels, backtest | Critical | Verified (mechanism); magnitude Unknown | 0.9 |
| 2 | Live book selects names without an `active` predicate; preferred and ETN-like identities appear as common stock; inactive longs in the 2026-10-30 book | High | Verified (SQL); classification Inferred | 0.9 / 0.6 |
| 3 | Eligibility and cleaning use prices up to 14 days after formation | High | Verified | 0.8 |
| 4 | Scores are overwritten on replay; no as-produced archive | High | Verified | 0.8 |
| 5 | One holdout reused for gate, guardrail, policy revisions, and label change; gate criteria revised after fold results | High | Verified | 0.85 |
| 6 | Benchmark is 100% net-long; book is 150% gross / +50% net; reported comparison is not exposure-matched | High | Verified | 0.8 |
| 7 | SEC dividends and dividend fallback usable from period end, before filing | High | Verified (mechanism) | 0.9 |
| 8 | Delisted names forward-filled (latent until survivorship fixed) | High (latent) | Verified | 0.75 |
| 9 | Headline backtest artifact uses a rule set (`thin_v6`) absent from current code and docs | Medium | Verified | 0.8 |
| 10 | Point-in-time controls verified: fundamentals vintages, feature anchor, label window, purge, per-fold fitting, threshold on training data | Control | Verified | 0.9 |

## 4. Disagreements and Corrections

| Item | Resolution |
|---|---|
| Stage 1A rated the validated baseline (`run_walk_forward_validated`) Critical (PA-P04) | Rated Medium (latent) in Stage 1B: no production entry point calls it. The bias is real if wired |
| Point-in-time agent says score history is replayed; survivorship agent says history includes 29 later-inactive IDs | Both true: universe is current-state; history is not survivor-only in the narrow sense |
| Doc claim "982 of 2,526 CIKs held only by a superseded identity" | Not reproduced by the survivorship agent (0.75%); definition may differ; recorded as unverified |
| Stage 1A PA-P05 (14-day lookahead) | Confirmed and given its own ID BI-03 |

## 5. Unknowns and Caveats

| ID | Unknown | Why it matters |
|---|---|---|
| U-1 | Magnitude of survivorship effect (BI-01) | Determines whether headline performance survives correction |
| U-2 | Classification of mis-typed identities (BI-07) | Evidence is name- and tape-based; must be checked against SEC records before any correction |
| U-3 | Rows affected by period-end clamp (BI-10) and XBRL fallback share (BI-02) | Only code comments give 966 rows and ~660 securities; not re-measured |
| U-4 | Feed-coverage share of label decay (BI-19) | Alternative explanation for the negative-rate decline |
| U-5 | Reports Center as-of labelling (BI-37) | Not read; left Unknown |
| U-6 | Whether `run_walk_forward_validated` will be wired | Determines whether BI-15 becomes production |

No live pipeline or backtest was re-run. The survivorship audit ran SELECT-only warehouse queries; all other evidence is static.

## 6. Handoff to Next Stages

| Stage | Inputs from 1B |
|---|---|
| 1C Testing review | BI-28, BI-29 (dry run broken), BI-33 (controls to test), absence of leakage tests on universe and calendar; LP-12 and LP-14 need tests |
| 1D Determinism and auditability | BI-04, BI-12, BI-24, BI-32, BI-38; `date.today()` defaults |
| Stage 2 requirements | FR-UNI, FR-EVAL, FR-BT, FR-DIV, FR-FEAT, FR-MACRO, FR-AI, NFR-PIT, NFR-GOV, NFR-REPRO (TBD IDs) |
| Stage 3 constitution | Point-in-time rule (MUST), holdout discipline (MUST), replay labelling (SHOULD) |

## 7. Next Step

Stage 1C (testing review) is next. It starts from the Stage 0 test inventory, the Stage 1A test coverage notes (398 targeted passing tests; no xfail; SQL paths not executed), and this stage's test gaps.
