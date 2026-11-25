# UNK-004 Reports Center UI Verification Checklist (Human)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Status | **Static/code verification complete 2026-11-18; interactive human UI verification still pending** |
| Related | `UNK-004`, `FR-REP-02`, `BI-37`, `AU-09`, `DA-20`, `reports-center-asof-contract-draft.md` |

## Pre-check (repo/runtime evidence already gathered)
- [x] Code evidence: `app/views/dashboard.py` generates deterministic in-memory markdown from loaded context; headers/filename use latest/path dates; no inspected persistence or stored `resolved_as_of`/`fetch_time` fields.
- [x] Runtime reachability: Streamlit container/service health reachable at `127.0.0.1:8501` (`/_stcore/health` ok) at 2026-11-15 check.
- [x] Code-level provenance verified: `_reports()` emits `resolved_as_of`, `generated_at_utc`, `run_ref`, storage mode, historical-selection status, and caveat labels; `test_reports_include_provenance_metadata_and_caveat` passes.
- [x] Code-level export verified: download filenames include report type, resolved as-of, and generated timestamp; `test_report_download_filename_includes_as_of_and_generated_marker` passes.
- [x] Code-level historical selection verified: historical dates fail closed with an explicit unavailability warning; `test_report_as_of_choice_fails_closed_for_historical_dates` passes.
- [x] Run-keyed persistence verified: report payloads write to `<run_id>/report.json` with content hashes and idempotent reruns; `test_report_payload_is_run_keyed_and_idempotent` passes.
- [ ] Interactive UI behavior confirmed (requires human/browser in running environment).

## Environment
| Field | Entry |
|---|---|
| Date/time checked |  |
| Checker name/role |  |
| Environment (local/non-prod/prod-readonly) |  |
| App URL |  |
| Code version/SHA |  |
| DB/data context notes |  |

## Checklist
| # | Check | Expected/target contract | Observed | Pass/Fail/Gap | Evidence (screenshot/note) |
|---|---|---|---|---|---|
| 1 | Navigate to Reports Center tab/page | Reports Center accessible |  |  |  |
| 2 | Resolved report as-of displayed | Explicit `resolved_as_of`/report date shown (not ambiguous) | Code/test PASS: provenance line and caption | Pass (static) | `tests/test_dashboard_view.py::test_reports_include_provenance_metadata_and_caveat` |
| 3 | Generation/fetch time displayed | `generated_at`/`fetch_time` shown (UTC or labeled timezone) | Code/test PASS: `generated_at_utc` in report and caption | Pass (static) | same test |
| 4 | Data/context date labeling | Labels distinguish latest score/formation/context dates as applicable |  |  |  |
| 5 | Historical as-of selection | User can select historical `report_as_of` or UI clearly states not supported | Selector added; historical dates fail closed with explicit warning | Pass (static) | `tests/test_dashboard_view.py::test_report_as_of_choice_fails_closed_for_historical_dates` |
| 6 | Historical report correctness (if supported) | Output bounded to selected as-of context (not wall-clock/latest leakage) |  |  |  |
| 7 | Report metadata/provenance | report type/id/run/input identifiers or manifest refs visible or in artifact |  |  |  |
| 8 | Download filename/content | Filename/content include as-of/run identifiers as applicable; content matches displayed report | Filename includes type/as-of/timestamp; content retains provenance/caveat | Pass (static) | `test_report_download_filename_includes_as_of_and_generated_marker`, `test_exported_report_retains_provenance_and_caveat` |
| 9 | Persistence/retrieval | Previously generated reports retrievable with same metadata (or explicitly transient) | Opt-in run-keyed payload persistence added; default remains transient | Pass (static) | `test_report_payload_is_run_keyed_and_idempotent` |
| 10 | Caveats/labels | Deterministic/simulation/caveat labels present as required |  |  |  |

## Findings summary
| Gap ID | Finding | Severity | Related contract item | Recommended action |
|---|---|---|---|---|
|  |  |  |  |  |

## Sign-off
- **Result:** Static PASS; interactive verification pending
- **Attachments:**
- **Reviewer/date:**
- **Tracker updated:** `decision-unknown-tracker.md` (UNK-004)
