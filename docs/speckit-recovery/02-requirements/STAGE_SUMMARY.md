# Stage 2 Summary — Requirements Recovery

| Field | Value |
|---|---|
| Stage | 2 — Requirements recovery, CRISP-DM mapping and traceability |
| Status | Complete |
| Evidence date | 2026-11-15 |
| Repository revision | `d748cea` plus uncommitted environment and docs changes |
| Inputs read | All files under `00-discovery/` and `01-audits/`; source, schema, tests and artifacts reopened where needed |
| Outputs | 6 files under `docs/speckit-recovery/02-requirements/` |
| Requirements | 53 FR, 31 NFR, 84 total |
| Status counts | Implemented 18; Partial 53; Missing 12; Unknown 1 |
| Source edits | None |

## 1. What Was Done

- Read the Stage 0 discovery registers (repository map, tech stack, components, services, entry points, data flows, capabilities, system context) and all four Stage 1 audit registers plus their inventories, formula registers and provenance maps.
- Recovered 84 normative requirements from observed implementation, schema, tests, docs, artifacts and live SELECT-only evidence.
- Assigned status (Implemented / Partial / Missing / Unknown), confidence, source findings, files, functions/classes, CRISP-DM phase, business goal, test linkage, validation status and risk to every requirement.
- Mapped every requirement family to the eight Stage 2 functional categories and every NFR to the eight non-functional categories, adding universe/identity, features, labels, macro and AI as recovered cross-cutting families.
- Built the RTM with the required eleven columns and an audit-ID crosswalk back to PA, BI, TG, DA, CAP, CMP, SVC and DF IDs.
- Computed coverage statistics from the same record set, so status counts, family totals and RTM rows cannot drift from the register.
- Wrote the six-phase CRISP-DM matrix with maturity scores, code, workflows, gaps, undocumented assumptions and risks.
- Wrote 23 undocumented-behavior rows, six documentation contradictions and five strengths that later stages must not re-open as defects.

## 2. Files Produced

| File | Contents |
|---|---|
| `requirements.md` | 53 FR and 31 NFR with evidence, status, confidence; 9 constraints; 7 assumptions; 9 business rules; 8 invariants; 12 failure modes |
| `crisp-dm-matrix.md` | Six-phase matrix, maturity 2.83/5, cross-phase gaps and caveats |
| `rtm.md` | 84-row traceability matrix plus 40-row audit-ID crosswalk |
| `coverage-statistics.md` | Status, group, family, phase, confidence, test-linkage and risk distributions |
| `undocumented-behavior.md` | 23 undocumented behaviors, 6 contradictions, 5 strengths |
| `STAGE_SUMMARY.md` | This summary and Stage 3 handoff |

## 3. Key Findings

| Finding | Evidence | Consequence |
|---|---|---|
| The register is 21.4% implemented, 63.1% partial, 14.3% missing and 1.2% unknown. | 18 / 53 / 12 / 1 of 84 | Most capabilities exist, but few meet a defensible production contract. |
| Point-in-time integrity is the dominant cross-cutting gap. | NFR-PIT-01..05 all Partial; BI-01, BI-03, BI-14, PA-F04, DA-04, DA-20 | Universe, fundamentals, dividends, macro and reports each have a separate as-of break. |
| Immutability is missing exactly where evaluation needs it. | FR-SIG-03, FR-LABEL-03, FR-EVAL-04, FR-BT-05, NFR-REPRO-04 | Past scores, labels, checkpoints and artifacts are overwritten or unaddressable. |
| The evaluation phase is the weakest CRISP-DM phase. | Maturity 2/5; BI-03, BI-05, BI-06, BI-08, BI-21, DA-09 | The walk-forward mechanics are sound but promotion evidence is not reproducible and the benchmark is unmatched. |
| Data governance and security are materially stronger than research reproducibility. | NFR-GOV-02, NFR-SEC-01..03, NFR-SCALE-01 | Preserve these controls; do not treat the whole repository as immature. |
| The environment is not reproducible. | NFR-REPRO-01, NFR-REPRO-02, DA-17 | The worktree pins nothing, has no lock, and installed packages already drift. |

## 4. Requirement Highlights

- **Missing:** FR-DIV-03 (SEC filing-date availability), FR-UNI-01 (PIT membership), FR-UNI-03 (delisting), FR-LABEL-03 (label immutability), FR-SIG-03 (score immutability), FR-EVAL-03 (frozen holdout), FR-BT-03 (costs), FR-BT-05 (artifact manifest), FR-AI-03 (text scope), NFR-REPRO-03 (run manifest), NFR-TEST-01 (coverage gate), NFR-TEST-03 (PIT/determinism tests).
- **Critical risk:** FR-UNI-01 and NFR-PIT-02 (survivorship), FR-DIV-07 (payer universe), NFR-PIT-01 (aggregate PIT break).
- **High-confidence Partial:** FR-ADJ-01..04, FR-DIV-01/02/04/05/06/08, FR-TR-01/03, FR-UNI-02, FR-FEAT-01/02/03/04, FR-EVAL-04, FR-BT-02/04, FR-PORT-02, NFR-DET-01..03, NFR-AUD-01..03, NFR-GOV-01.
- **Implemented anchors:** FR-CA-01, FR-LABEL-01, FR-MACRO-01, FR-TR-02, FR-SIG-01/02/04, FR-EVAL-01/02, FR-BT-01, FR-PORT-01, FR-REP-01, FR-AI-01, NFR-GOV-02, NFR-SCALE-01, NFR-SEC-01..03.

## 5. Validation Performed

- Every requirement row has a non-empty ID, category, statement, evidence, file list, function or explicit `—`, test reference or explicit `None`, status, confidence, source finding or explicit `—`, phase, business goal, risk and validation status.
- IDs are unique; counts are 53 FR and 31 NFR; statuses and risks are from the allowed sets; confidence is within 0–1.
- Every status count and percentage in `coverage-statistics.md` is generated from the same Python record set used to write `requirements.md` and `rtm.md`, not hand-copied.
- Source audit files were not edited. The Stage 1D `TBD` requirement column remains `TBD` in the source; this register supplies the mapping in `rtm.md`.
- Live facts used in evidence are the 2026-11-15 snapshot: 464,691 scores, 9,756,631 features, 323,632 dividends, 105,865 macro vintages, 18 model runs, 53 nightly runs and 7 backtest artifacts.

## 6. Open Questions

| ID | Question | Why it matters | Owner stage |
|---|---|---|---|
| OQ-01 | Are stored raw closes fully split-adjusted for every security (FA-U01)? | Determines whether FR-ADJ-01 can be satisfied by a factor layer or requires a full price rebuild. | Stage 3 / remediation |
| OQ-02 | Is the Yahoo dividend amount basis already split-adjusted for all rows (FA-U03)? | Affects FR-DIV-08 and total-return accuracy. | Stage 3 / remediation |
| OQ-03 | What is the survivor-versus-PIT return delta (BI-01)? | Sizes the most critical bias; not measurable without a PIT membership build. | Stage 4 risk register |
| OQ-04 | Does the Reports Center label reports with a past as-of date (BI-37)? | Decides whether FR-REP-02 is Partial or Missing in the UI layer. | Stage 3 / UI review |
| OQ-05 | What are the provider licensing and redistribution terms (NFR-GOV-03)? | Blocks external distribution of derived data. | Stage 4 / legal review |
| OQ-06 | Can a duplicate-key dividend batch raise or silently keep one row (DA-21)? | Determines the correct FR-DIV-01 ingest contract and NFR-DET-04 test. | Stage 3 / remediation |
| OQ-07 | Is the production risk-free path intended to use ALFRED vintages, or is latest acceptable? | FR-MACRO-02 is Partial because the correct reader exists but is unused. | Stage 3 constitution |

## 7. Stage 3 Handoff

- Treat `requirements.md` as the normative baseline for the recovered system. The 31 NFRs are the candidate constitution articles; the 53 FRs are the candidate capability requirements.
- Constitution candidates: as-of integrity (NFR-PIT-01..05), determinism (NFR-DET-01..04), reproducibility (NFR-REPRO-01..04), auditability (NFR-AUD-01..04), governance (NFR-GOV-01..03), testability (NFR-TEST-01..04), reliability (NFR-REL-01..02), scalability (NFR-SCALE-01..02) and security (NFR-SEC-01..03).
- Do not re-open the five recorded strengths as defects: append-only macro/profile/quarantine history, prediction versioning, allowlisted ops, advisory-locked nightly stages and purge/all-fold walk-forward controls.
- Carry forward the documented Stage 1D deviation: evidence is under `01-audits/determinism/` with `DA-`, not `01-audits/auditability/` with `AU-`.
- Stage 4 should seed its risk register from the 12 failure modes, the 12 Missing requirements, the four Critical-risk requirements and the seven open questions.
- Stage 5 should not draft a specification that assumes a frozen holdout, immutable scores, PIT membership, cost-aware backtests or run manifests already exist. They do not. Draft them as required future behavior.

## 8. Targeted Family Validation

The families the user named were re-read against source, schema, tests and artifacts after the register was generated. The table records the result and every status or evidence correction made during that pass.

| Family | Requirements checked | Evidence checked | Result | Correction made |
|---|---|---|---|---|
| Universe and identity | FR-UNI-01..03 | `UNIVERSE_SQL`, `feature_window`, `total_return_matrix` forward-fill, `delisted_date` readers/writers, 29 later-inactive score IDs | 01 Missing; 02 Partial; 03 Missing | UNI-01 and UNI-03 evidence corrected to distinguish current active filtering from the missing membership and delisting writers. |
| Evaluation | FR-EVAL-01..05 | Walk-forward purge and all-fold gate, checkpoint contract, `audit.model_runs`, canonical checkpoint overwrite, dry-run execution, policy history | 01/02 Implemented; 03 Missing; 04/05 Partial | EVAL-03 wording corrected from `MIN_PR_AUC_LIFT` removed to PR-AUC lift demoted to a diagnostic; code retains the constant. |
| Backtesting | FR-BT-01..05 | 14-day post-formation lookahead, 15/8 book and 100% net benchmark, cost inputs, seven artifact manifests and rule-set drift | 01 Implemented; 02/04 Partial; 03/05 Missing | None. |
| Dividend adjustment | FR-DIV-01..08 | Primary key and feed columns, reconciliation cache overwrite, SEC period-end rows and dropped filed date, NULL upsert, quarantine path, calendar view, today-based payer flags, split-basis conversion | 03 Missing; 01/02/04/05/06/07/08 Partial | DIV-01 downgraded from Implemented: the primary key omits `feed`. DIV-05 downgraded: new absurd rows are dropped silently and the rule is written only by V0104. |
| Fundamental features | FR-FEAT-01..04 | Availability clamp, feature provenance columns, growth/payout windows and price-quality median, quarterly vintage ordering | 01/02/03/04 Partial | FEAT-02 downgraded from Implemented: no `data_version` or rebuild timestamp column exists on `model.features`. FEAT-01 wording corrected to period-end substitution. |
| Macro inputs | FR-MACRO-01..02 | Vintage table and loader, `as_of_series`, `load_risk_free` caller, absence of a vintage reader in production | 01 Implemented; 02 Partial | None. |
| AI assistance | FR-AI-01..03 | LLM disabled/loopback/schema validation/no-write path, live autofill defaults, absence of text ingestion | 01 Implemented; 02 Partial; 03 Missing | None. |
| Point-in-time integrity | NFR-PIT-01..05 | Future cleaning, current universe flags, filing clamp and tie-break, SEC dividend availability, calendar and reports, latest macro and autofill clocks | All five Partial | None. |
| Governance | NFR-GOV-01..03 | Checkpoint policy version vs audit table, data-quality/quarantine/freshness controls, provider-terms search | 01 Partial; 02 Implemented; 03 Unknown | GOV-01 wording corrected to match the demoted PR-AUC criterion. |
| Reproducibility | NFR-REPRO-01..04 | Pin/lock state, Docker and CI image tags, nightly/model/backtest manifests, append-only raw/label/checkpoint evidence | 01/02/04 Partial; 03 Missing | None. |

No targeted requirement moved from Missing to Implemented. Three over-graded requirements moved from Implemented to Partial (FR-DIV-01, FR-DIV-05, FR-FEAT-02). No Missing or Unknown classification was contradicted by the evidence.

## 9. Limits

- No pipeline, backtest, model or database write was executed. Evidence is static code/schema/artifact inspection plus SELECT-only counts.
- The requirements are recovered, not elicited. There is no stakeholder interview, product brief or pre-existing `specs/` baseline.
- Status reflects implementation maturity at the snapshot, not the correctness of every value or the quality of the investment strategy.
- Coverage percentages describe the recovered register only. They are not code coverage and cannot be used to claim requirement completeness against an unseen specification.
