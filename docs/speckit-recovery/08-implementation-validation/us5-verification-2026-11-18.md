# US5 Verification: As-of and Provenance-Clear Reports

**Feature**: `specs/001-p0-recovery/spec.md`

**Scope**: T036–T040 (P3)

**Status**: Static/code verification complete; interactive UI confirmation pending

## T036 — Provenance labels

`app/views/dashboard.py` `_reports()` emits `resolved_as_of`, `generated_at_utc`, `run_ref`, storage mode, historical-selection status, and simulation caveats. Verified by `test_reports_include_provenance_metadata_and_caveat`.

## T037 — As-of selection

A fail-closed Report as-of selector was added. Selecting any historical date produces an explicit unavailability warning and no historical report. Verified by `test_report_as_of_choice_fails_closed_for_historical_dates`.

## T038 — Run-keyed report persistence

`_persist_report_payload()` writes opt-in report payloads to `<root>/<run_id>/report.json` with content hashes and idempotent reruns. The UI exposes an explicit persistence checkbox/button. Verified by `test_report_payload_is_run_keyed_and_idempotent`.

## T039 — Export labels

Download filenames include report type, resolved as-of, and generated timestamp; exported markdown retains provenance and caveat labels. Verified by `test_report_download_filename_includes_as_of_and_generated_marker` and `test_exported_report_retains_provenance_and_caveat`.

## T040 — UNK-004 checklist

`docs/speckit-recovery/06-execution-prep/unk004-ui-verification-checklist.md` records static/code PASS for checks 2, 3, 5, 8, and 9. Interactive browser confirmation remains pending; no runtime UI pass is claimed.

## US5 checkpoint

Report provenance and fail-closed as-of labeling are reviewable. Historical report generation and interactive UI confirmation remain pending; AC-P0-08 is not fully verified.
