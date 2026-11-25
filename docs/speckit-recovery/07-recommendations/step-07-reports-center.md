# Step 7 — Reports Center Provenance and As-Of (Refined Contract, Prepared)

| Field | Value |
|---|---|
| Recommendation | Explicit `report_as_of`, parameterized loaders, persisted/displayed provenance metadata, historical retrieval or explicit transient labeling |
| Status | **Refined; UI confirmation and implementation pending** |
| Traceability | `TSK-011/024`, `FR-REP-02`, `FR-AI-02`, `NFR-PIT-05`, `AU-09`, `DA-20`, `RK-09`, `UNK-004` |
| Evidence | `../06-execution-prep/reports-center-asof-contract-draft.md`, `../06-execution-prep/unk004-ui-verification-checklist.md`, `app/views/dashboard.py` (repo), Streamlit health reachable `127.0.0.1:8501` (2026-11-15) |

## 1. Current observed behavior (evidence)
- `app/views/dashboard.py`: `_reports(context)` builds deterministic markdown in memory from loaded context; headers/filenames use latest/path-derived dates (e.g. `context['latest']`, `path.index[-1]`); `_reports_tab` renders and downloads; caption states deterministic/no LLM.
- No inspected evidence of persisted report records, stored `resolved_as_of`/`fetch_time`, input snapshot/manifest linkage, or user-selectable historical `report_as_of`.

## 2. Refined target contract
### 2.1 Selection and computation
- Resolve and require explicit `report_as_of` for every report request (policy-defined semantics relative to formation/latest score/price availability).
- Parameterize all context queries/loaders by `report_as_of` (or documented as-of formation semantics); prohibit wall-clock leakage for historical/replay reports.
- UI must display resolved `report_as_of` and clearly indicate current/live vs historical context.

### 2.2 Provenance metadata (display + persist/embed)
Minimum fields: `report_id`/`run_id`, `report_type`, `resolved_as_of`, `generated_at`/`fetch_time` (UTC), `code_sha`+dirty or release version, input snapshot/manifest refs or hashes (scores/prices/analyses/catalysts), parameter/config hash, data freshness/source status, status/actor where applicable.

### 2.3 Storage and retrieval
- Audit/review-relevant reports: persist immutable artifacts/records addressable by `report_id`/`run_id` (not only regenerated in-memory).
- If historical retrieval unsupported initially, label as transient/current-only explicitly and provide deterministic regeneration inputs/manifest refs.
- Filename convention should include `resolved_as_of` and run/report identifier.

### 2.4 Labels and caveats
- Include simulation/caveat/deterministic labels as required (`NFR-PIT-03/05` linkage); no implied approval.

## 3. Acceptance checks (to implement/verify)
- AC-RPT-01: UI shows resolved as-of and generation/fetch time.
- AC-RPT-02: Fixed historical `report_as_of` returns same data independent of current date.
- AC-RPT-03: Downloaded/persisted artifact contains required metadata or manifest reference.
- AC-RPT-04: Compatibility/mismatch checks label or reject incompatible report manifests.
- AC-RPT-05: Tests cover deterministic regeneration and as-of parameterization.

## 4. Immediate next actions
- Complete `../06-execution-prep/unk004-ui-verification-checklist.md` in running UI (human/browser).
- Approve this contract and wire into M2 P0 (`P0-TSK-009`, `TSK-011/024`) after M1 gate.
