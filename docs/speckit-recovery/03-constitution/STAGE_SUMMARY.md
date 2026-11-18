# Stage 3 Summary — Constitution Reconstruction

| Field | Value |
|---|---|
| Stage | 3 — Constitution |
| Date | 2026-11-15 |
| Status | Complete |
| Snapshot | `d748cea` at `2026-11-15` |
| Input | `docs/speckit-recovery/00-discovery/`, `01-audits/`, `02-requirements/` |
| Output | `principles-evidence.md`, `constitution-draft.md`, `STAGE_SUMMARY.md` |
| Source edits | None |

## 1. What Was Done

- Re-read the Stage 0 discovery inventory, all four Stage 1 audit outputs, and all six Stage 2 requirements artifacts.
- Re-opened the highest-value source, schema, CI, container and artifact paths cited by the constitution: scoring/model/backtest/feature lineage, API auth, ops allowlist, read-only explorer, Docker/CI, requirements, schema, and backtest/checkpoint artifacts.
- Probed schema and repository facts only where needed to confirm counts already established in prior stages (for example: 104 migration files vs applied ledger 106; 238-line unpinned worktree `requirements.txt`).
- Did not run pipelines, tests or mutating database commands in Stage 3.

## 2. Files Produced

| File | Contents |
|---|---|
| `docs/speckit-recovery/03-constitution/principles-evidence.md` | 14-principle summary (3 Practised, 11 Partial, 0 Absent, 0 Unknown), 30 detailed `PE-01..PE-30` evidence rows in the required 11-column format, principle-by-principle reading, search coverage and limits. |
| `docs/speckit-recovery/03-constitution/constitution-draft.md` | Draft constitution for `/speckit-constitution` with the required nine sections, 95 testable MUST/SHOULD rules split into 30 Descriptive and 65 Aspirational, adoption notes and limits. |
| `docs/speckit-recovery/03-constitution/STAGE_SUMMARY.md` | This summary, counts, key decisions, open questions and Stage 4 handoff. |

## 3. Counts

| Metric | Count | Notes |
|---|---:|---|
| Principles assessed | 14 | Determinism, auditability, reproducibility, lineage, testability, traceability, risk controls, reliability, performance, modularity, maintainability, separation of concerns, security, data governance. |
| Practised | 3 | Modularity, separation of concerns, security. |
| Partial | 11 | All remaining principles. |
| Absent | 0 | No principle is wholly absent. |
| Unknown | 0 | External scheduler/object-store and provider-audit state remain outside scope but did not make a principle Unknown. |
| Detailed evidence rows | 30 | `PE-01..PE-30`, each with the required 11 columns. |
| Verified evidence rows | 26 | Read from code, schema, tests, artifacts or prior validated registers. |
| Inferred evidence rows | 4 | `PE-20`, `PE-21`, `PE-24`, `PE-25` (architecture/boundary judgments). |
| Constitution rules | 95 | 30 Descriptive, 65 Aspirational. |
| MUST rules | 91 | — |
| SHOULD rules | 4 | `TR-11`, `QG-12`, `DC-05`, plus none others. |

## 4. Key Decisions

- **Descriptive vs aspirational split is strict:** a rule is Descriptive only when a current control can be named (code, schema, CI, container or test). Absence of enforcement moves the rule to Aspirational even if intent is documented.
- **Security is Practised, not complete:** API key + rate limiting, catalog allowlist, read-only explorer and non-root containers are verified controls; missing rotation/governance is captured as Aspiration (`ES-09`/`DG-11`/`PE-28`) rather than downgrading the principle.
- **Determinism and PIT are the central gaps:** most other constitution failures (audit identity, lineage, reproducibility, traceability) are downstream of missing run manifests, append-only decision stores and explicit as-of enforcement.
- **Critical-risk handoff preserved:** the four Stage 2 Critical requirements (`FR-UNI-01`, `FR-DIV-07`, `NFR-PIT-01`, `NFR-PIT-02`) are called out as first exceptions in adoption notes because they dominate risk.
- **No invented evidence:** provider licensing, external scheduler/object-store/backup state, BI-01 survivorship magnitude, BI-37 Reports Center as-of behavior and DA-21 duplicate-key behavior remain open and are not asserted as practised.

## 5. Open Questions

- `NFR-GOV-03`: what are the internal-use, caching, redistribution and derived-data terms for yfinance, FMP, SEC and other configured providers?
- Who owns and stores the frozen promotion holdout and acceptance-policy versions (`FR-EVAL-03`, `CM-01`)?
- What cost model and exposure-matched benchmark should be required before publishing backtest performance (`FR-BT-03`, `FR-BT-04`, `DC-10`)?
- Should Streamlit direct warehouse reads be formalized as an allowed boundary or moved behind API/service clients (`PE-25`, `NFR-SEC-02`)?
- Is `sql/silver_schema.sql` intentionally retained as an alternate design or should it be archived as non-runtime (`ES-06`, `PE-21`)?
- What is the authoritative migration state given 104 migration files and applied ledger version 106 (`PE-23`, `CM-03`)?

## 6. Handoff Notes for Stage 4

- Use `principles-evidence.md` as the control-gap register: `PE-02,04,06,08,10,12,15,17,19,23,30` are the highest-value High-risk gaps.
- Prioritize remediation around three dependency chains: **PIT integrity** (`GP-01`, `ES-03/04`, `DG-06..09,12,13`, `TR-06/07/08/09`, `QG-08/09`), **append-only decision evidence** (`GP-03/05`, `AU-01..05,08,11`, `RP-05..10`, `CM-09`, `DC-05/06`), and **runtime reproducibility** (`ES-07/09`, `TR-04/05/10`, `RP-01/02/04`, `QG-07/10/11`).
- Carry forward Stage 2 Critical requirements and all `NFR-PIT-*` Partial ratings into the Stage 4 risk register.
- Do not create remediation items that require source edits in this recovery pass; Stage 4 should plan and sequence them only.
- If Stage 4 finds a requirement/principle conflict, update the RTM or constitution draft explicitly rather than silently reconciling.
