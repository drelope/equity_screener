# Reports Center As-Of and Provenance Contract Draft

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation (design draft) |
| Date | 2026-11-15 |
| Status | **Draft; not approved or implemented** |
| Related | `UNK-004`, `BI-37`, `FR-REP-02`, `FR-AI-02`, `NFR-PIT-05`, `AU-09`, `DA-20`, `RK-09`, `TSK-011/024`, `P0-TSK-009` |

## 1. Current observed behavior (repo evidence)

- Source: `app/views/dashboard.py`.
- `_build_context()` / `_load_context()` load portfolio context from warehouse queries (`pf.load_score_dates`, `load_universe`, `load_prices`, `load_analyses`, `load_catalysts`) for latest/formed score dates with cached build; no user-selectable historical report `as_of` parameter was found in inspected code.
- `_reports(context)` generates deterministic markdown in memory from `context` (not from stored report records). Headers use `recent = path.index[-1]` (e.g. `Morning note - {recent:%Y-%m-%d}`); download filename uses `context['latest']`.
- `_reports_tab` renders and offers download; caption states reports are deterministic drafts from the warehouse with no language model called.
- No inspected evidence of report persistence, stored `resolved_as_of`, stored `fetch_time`/generation timestamp, input snapshot/manifest linkage, or historical report retrieval.

## 2. Target contract (proposed)

### 2.1 Inputs and selection
- Every report generation request MUST resolve an explicit `report_as_of` (date/timestamp policy defined by spec) and MUST NOT default to wall clock for historical/replay/reporting paths except explicitly labeled “current/live” views.
- UI/API MUST allow selecting or explicitly displaying the resolved `report_as_of` used.
- All underlying queries/data loaders MUST be parameterized by `report_as_of` (or documented formation/rebalance semantics) so results are reproducible for that as-of context.

### 2.2 Required metadata (persisted and/or embedded)
Each generated report artifact/record MUST carry:
- `report_id` and/or immutable `run_id`
- `report_type` (Morning note, Performance report, Risk report, IC memo, Research note)
- `resolved_as_of` (authoritative report date)
- `generated_at` / `fetch_time` (UTC)
- `code_sha` and dirty flag (or release/version identifier)
- `input_snapshot_id` or hashes/versions for key inputs (scores, prices, analyses, catalysts, manifests as applicable)
- `parameter_hash` / config (limits, book definition, benchmark/exposure assumptions, filters)
- `data_freshness`/source status summary (or references)
- `status` (draft/final/published) and actor/provenance if user-initiated

### 2.3 Presentation requirements
- Report header/body MUST display `resolved_as_of`, `generated_at/fetch_time`, and simulation/caveat labels.
- Download filename SHOULD include `resolved_as_of` and report id/run id (not ambiguous latest-only naming).
- Historical reports MUST be clearly labeled as historical and reproducible from stored metadata.

### 2.4 Storage and reproducibility
- Reports intended for audit/review SHOULD be persisted as immutable artifacts/records addressable by `report_id`/`run_id` (not only regenerated in-memory).
- Regeneration from identical `resolved_as_of` + manifest/input references MUST produce identical content (or record deterministic hash/diff policy).

## 3. Acceptance checks (draft)
- `AC-RPT-01`: UI/API shows resolved `report_as_of` and generation/fetch time for every report.
- `AC-RPT-02`: Selecting a historical `as_of` (where supported) returns data bounded to that as-of context.
- `AC-RPT-03`: Persisted/downloaded report contains required metadata or references manifest.
- `AC-RPT-04`: Compatibility check rejects/labels reports whose inputs/code/rule set mismatch current manifest (as applicable).
- `AC-RPT-05`: Automated test covers current-date independence for fixed historical `as_of`.

## 4. Dependencies / open points
- Alignment with global run manifest schema (`RM-04`, `TSK-008`, `P0-TSK-002/004`).
- Definition of `resolved_as_of` semantics relative to formation date, latest score date, and price availability.
- Storage location/schema (DB table vs artifact file + index) and retention policy.
- UI/runtime confirmation of any behavior not visible in static code (tracked in `UNK-004`).

## 5. Non-goals
- No implementation performed in this draft.
- No claim that Reports Center currently satisfies this contract.
