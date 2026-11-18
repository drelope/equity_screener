# Stage 4 Remediation Plan

| Field | Value |
|---|---|
| Stage | 4 — Synthesis and migration |
| Date | 2026-11-15 |
| Scope | Prioritized remediation planning only (no source/test/config edits in this recovery pass) |
| Inputs | `risk-register.md`, Stage 0–3 findings/requirements/constitution |
| Effort scale | S = days, M = 1–3 weeks, L = multi-week/cross-cutting |

## Prioritized actions

| ID | Priority | Group | Action | Effort | Dependencies | Verification | Addresses |
|---|---|---|---|---|---|---|---|
| RM-01 | P0 | Bias remediation / PIT | Define and implement PIT membership/identity intervals (valid_from/valid_to, delisting handling) and require as-of eligibility in universe, features, labels and backtest | L | DG-08 design; dividend/listing/delisting evidence review; migration strategy | PIT regression tests; survivor-vs-PIT delta report; no current-state flag in historical paths | RK-01, FR-UNI-01, FR-UNI-03, NFR-PIT-02, BI-01, BI-07, BI-09 |
| RM-02 | P0 | Bias remediation / PIT | Enforce filing/availability semantics: persist SEC filed dates, gate SEC dividends/features/labels on filed<=as_of, fix period-end substitution and remove future/current defaults in replay paths | L | RM-01 interfaces; raw schema changes; acceptance of NULL/exclusion policy | Two-date replay and future-row isolation tests; no period-end-visible-before-filed rows; explicit as_of required | RK-02, FR-DIV-03, FR-FEAT-01, NFR-PIT-03..04, BI-02, BI-10, BI-16, DA-01 |
| RM-03 | P0 | Bias remediation / backtest | Restrict selection/cleaning to formation-available data; correct 14-day lookahead, add costs and exposure-matched benchmark; label pre/post-formation exclusions | M | RM-01/RM-02 for PIT inputs; cost/benchmark policy decision | Window assertions, cost/benchmark fields in artifacts, matched-benchmark report, reproducible run comparison | RK-02, RK-04, FR-BT-02..04, BI-03, BI-08, TG-06, TG-10 |
| RM-04 | P0 | Auditability / reproducibility | Introduce immutable run manifest and run-keyed append-only stores for scores, labels, checkpoints and backtest artifacts (code SHA+dirty, policy, env/deps, input snapshot/hash, rule set) | L | Storage/schema design; RM-06 lock for env identity | Manifest completeness checks; no overwrite of canonical checkpoint; artifacts addressable by run_id; replay from manifest | RK-03, RK-04, RK-07, FR-SIG-03, FR-LABEL-03, FR-EVAL-04, FR-BT-05, NFR-REPRO-03, DA-02, DA-09..10, DA-18 |
| RM-05 | P0 | Auditability / lineage | Make raw payloads and lineage append-only and complete: version SEC/provider payloads, stop destructive lineage rebuilds, extend lineage beyond 5 fields, propagate feature hash/version to scores | L | RM-04 run identity; schema/migration plan | Append-only history queries, lineage coverage tests, score rows carry run/feature identity, no delete-and-reinsert | RK-07, NFR-AUD-01..04, FR-SIG-04, DA-03, DA-13, DA-14, PE-07, PE-08 |
| RM-06 | P0 | Reproducibility / environment | Restore exact dependency pins and create hashed lock; align CI/Docker/local installs to lock; reconcile worktree freeze drift and record env identity | M | Decision on dependency manager/lock format | Clean checkout/container build installs identical set; pip/package checks pass; CI green on lock; manifest records env hash | RK-06, NFR-REPRO-01..02, DA-17, PE-05, PE-06, ES-09 |
| RM-07 | P0 | Tests / determinism | Add blocking gates: coverage threshold, CLI `main()` smoke tests (incl. fix broken dry-run contract), frozen-clock replay and PIT regression suite for universe/fundamentals/dividends/macro/reports | L | RM-02/RM-04 interfaces stabilize; CI updates | CI fails below threshold; dry-run and advertised CLIs pass; two-date deterministic replay; PIT tests catch future-row leakage | RK-08, NFR-TEST-01..04, NFR-DET-02, FR-EVAL-05, TG-01, TG-04, TG-14..16, TG-19, TR-04..10 |
| RM-08 | P1 | Dividend integrity | Fix dividend key/evidence and update semantics: include feed or append-only evidence per feed, COALESCE non-NULL dates, runtime quarantine rules, preserve reconciliation history and source metadata | M | RM-05 storage patterns; provider behavior validation | No feed-collision loss, no NULL overwrite, quarantine applied at ingest with append-only audit, reconciliation verdict history retained | RK-10, FR-DIV-01, FR-DIV-04, FR-DIV-05, DA-05, DA-06, DA-21, DG-02, DG-05..06 |
| RM-09 | P1 | Bias remediation / macro & reports | Route production risk-free/macro through ALFRED `as_of_series`; parameterize and stamp resolved as-of on reports, dashboards, worksheets and autofill; remove CURRENT_DATE/latest-only historical reads | M | RM-02 as-of contract; UI/API changes | As-of stamped outputs; no latest-revision leak in historical metrics; report/query tests pass with fixed as-of | RK-09, FR-MACRO-02, FR-REP-02, FR-AI-02, BI-14, BI-34, BI-35, DA-04, DA-20 |
| RM-10 | P1 | Technical debt / data correctness | Validate and correct price adjustment chain: confirm raw close basis, split/dividend amount bases, apply canonical split/dividend adjustments, add golden fixtures for boundaries | M | FA-U01/FA-U03 resolution; sample validation data | Golden return/decomposition tests, split boundary tests, documented adjustment policy and lineage | RK-05, FR-ADJ-01..04, FR-DIV-08, FR-TR-01..03, PA-P01, PA-P02, PA-F05, TG-08..12 |
| RM-11 | P1 | Reliability / operations | Add nightly stage checkpoints, resume semantics, per-stage timeouts, root-cause/error capture and alerting; test advisory-lock contention | M | RM-04 run identity/logging; ops ownership | Failed runs record cause; resume/timeout behavior tested; contention exits cleanly; recent failure classes addressed | RK-11, NFR-REL-01..02, PE-16, PE-17, DA-11 |
| RM-12 | P1 | Documentation / governance | Reconcile docs and governance artifacts: label implemented vs aspirational architecture, update RTM/constitution with behavior changes, create provider-terms and secret-rotation inventories, reconcile migration ledger | S | Legal/product input for provider terms; RM-04/RM-06 artifacts | Docs match implementation; provider/secret inventories present; migration ledger reconciled; change checklist enforced | RK-12, RK-13, RK-15, NFR-GOV-03, NFR-SEC-03, CM-05..06, PE-13, PE-23, PE-28 |
| RM-13 | P2 | Technical debt / maintainability | Reduce structural debt: split oversized portfolio/backtest modules, archive or formalize alternate schema, formalize Streamlit DB boundary, add packaging metadata and representative performance budgets/tests | M | RM-07 tests and RM-12 decisions | Module boundaries documented/tested, non-runtime schema archived, boundary contract explicit, load/perf budget checks in place | RK-12, RK-14, RK-15, PE-21, PE-25, ES-06, QG-12, NFR-SCALE-02 |

## Grouped view
- **Bias remediation:** RM-01, RM-02, RM-03, RM-09 (and RM-10 where adjustment affects returns/labels)
- **Determinism:** RM-02, RM-07 (explicit as_of, frozen-clock replay, ordering/tie-break enforcement)
- **Tests:** RM-07, RM-03/RM-10 verification tests, RM-11 contention tests
- **Auditability:** RM-04, RM-05, RM-08, RM-11
- **Documentation:** RM-12 (and RTM/constitution updates required by all behavior changes)
- **Technical debt:** RM-06, RM-10, RM-11, RM-13

## Execution notes
- Treat RM-01..RM-07 as preconditions for trustworthy model promotion/spec-driven adoption.
- Do not mark remediation complete without verification artifacts (tests, manifests, reports) linked to requirement/PE/risk IDs.
- Any item requiring legal/policy decisions (provider terms, cost model, holdout ownership) must record an explicit decision artifact before closure.
