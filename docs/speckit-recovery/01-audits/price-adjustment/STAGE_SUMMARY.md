# Stage 1A — Price Adjustment Audit: Stage Summary

| Field | Value |
|---|---|
| Status | Complete (audit); no source, test, or config changes |
| Output | `docs/speckit-recovery/01-audits/price-adjustment/` |
| Input | `docs/speckit-recovery/00-discovery/` (all 10 files present) |
| Repo HEAD | `d748cea` |

## 1. What Was Done

Three read-only explore audits, each reporting with file path, function, and confidence:

1. **Dividend and corporate-action lineage**: ingestion, normalization, reconciliation, upsert, split loaders, migrations.
2. **Adjusted price, total return, benchmarks, normalization**: `returns.py`, `portfolio.py`, `backtest.py`, `baselines.py`, `features.py`, `event_study.py`, `math_engine.py`.
3. **Tests and fixtures**: mapped test coverage per behavior and ran 22 targeted test files.

The orchestrator then wrote the five deliverables. Quoted formulas and numbers come from agent reports, which cite file and line. Items marked Inferred or Unknown were not executed.

## 2. Files Produced

| File | Contents |
|---|---|
| `dividend-adjustment-audit.md` | Dividend ingestion path, PA-D register (22), worked examples from tests, rounding, idempotency, as-of reconstruction |
| `adjustment-lineage.md` | Mermaid lineage from providers to outputs; lineage table; date semantics; gaps |
| `formula-inventory.md` | FA- formula register, constant register, adjustment chain, open items |
| `findings.md` | PA-P (21), PA-F (6), PA-D summary, Stage 0 cross-reference, priorities |
| `STAGE_SUMMARY.md` | This file |

## 3. Headline Results

| # | Result | Type | Confidence |
|---|---|---|---|
| 1 | Split adjustment of closes happens in one place only (`portfolio.clean_prices`), and only where a price jump matches the reported ratio within 10% and 5 days. Return, feature, and event paths read unadjusted closes. | Verified (code) | 0.9 |
| 2 | Real moves up to 10% on a split day are absorbed into the split factor; real moves above 10% are left unadjusted (experiments, synthetic inputs). | Verified (experiment) | 0.85 |
| 3 | Validated walk-forward baseline uses full-period volatility and omits split events. | Verified (code) | 0.95 |
| 4 | Backtest selection uses price data up to 14 calendar days after formation. | Verified (code) | 0.85 |
| 5 | Risk-parity path weights by a percentile score in the wrong direction; default book unaffected. | Verified (code) | 0.9 |
| 6 | SEC-derived dividends use fiscal period end as ex-date and drop the filing date, enabling look-ahead in the features fallback. | Verified (code); impact Inferred | 0.85 |
| 7 | Dividend date upsert overwrites with NULL on re-run (no COALESCE). | Verified (code) | 0.85 |
| 8 | Provider exception can be swallowed after an empty earlier provider result. | Verified (code) | 0.9 |
| 9 | Total-return SQL and ex-date timing are not executed by any test; coverage is substring only. | Verified (test read) | 0.95 |
| 10 | Targeted pytest run: 398 passed, 0 failed, 0 skipped, 0 xfail (22 files, live DB reachable). | Verified (run, agent-reported) | 0.9 |
| 11 | Two split-ratio conventions coexist without a cross-check test. | Verified | 0.8 |
| 12 | No xfail markers in the repo; known-bug cases are pinned as passing regression tests. | Verified (grep) | 0.95 |

## 4. Unknowns and Limits

| ID | Unknown | Why it matters |
|---|---|---|
| U-1 | Whether stored `raw.market_data.close` is split-adjusted per security | Decides whether PA-P01/P02 and PA-F05/F06 affect real data |
| U-2 | Whether `raw.market_data.adjusted_close` is populated (documented NULL, not queried in 1A) | Decides whether any stored adjusted series exists |
| U-3 | Whether Yahoo dividends are on the split-adjusted basis | Assumed by `reconcile_amounts` comparison |
| U-4 | Frequency of real split-day moves over 10% in production | Sets practical impact of PA-P01/P02 |
| U-5 | Whether a duplicate-PK batch raises in `DIVIDEND_UPSERT` | PA-D08 |
| U-6 | SEC EPS per-share basis vs OPENBB annual dividend | PA-F03 |

No live warehouse query was run in Stage 1A. Stage 0 live results are used only where cited.

## 5. Caveats on Agent Reports

- The dividend agent did not query the live warehouse; its findings are from code only.
- The test agent's targeted run is reported as 398 passed. I did not re-run it in the orchestrator session, so treat it as agent-verified.
- Experiments in PA-P01, PA-P02, PA-P12, PA-P19 used synthetic inputs through production functions. They are not committed tests.
- Two features (PA-F03, PA-F06) are confidence ≤0.6 and need confirmation before remediation.

## 6. Handoff to Next Stages

| Stage | Inputs from 1A |
|---|---|
| 1B Bias and temporal integrity | PA-P04, PA-P05, PA-D01, PA-D02, PA-D19, PA-F01, PA-F04, formula FA-S03 (split on ex-date) |
| 1C Testing review | PA-P07, PA-P15, PA-P16, PA-P17, PA-P18, PA-P20 |
| 1D Determinism and auditability | PA-D06, PA-D08, PA-D16, PA-D17, PA-D19, PA-D20 |
| Stage 2 requirements | FR-ADJ, FR-DIV, FR-TR, FR-BT, FR-FEAT, FR-PORT, FR-RISK, FR-ATTR (TBD IDs) |

## 7. Next Step

Stage 1B (bias and temporal integrity) is next in the SpecKit sequence. It requires no new discovery; its input is the Stage 0 folder plus this Stage 1A folder.
