# UNK-004 Reports Center UI Verification Checklist (Human)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Status | **Pending human verification** |
| Related | `UNK-004`, `FR-REP-02`, `BI-37`, `AU-09`, `DA-20`, `reports-center-asof-contract-draft.md` |

## Pre-check (repo/runtime evidence already gathered)
- [x] Code evidence: `app/views/dashboard.py` generates deterministic in-memory markdown from loaded context; headers/filename use latest/path dates; no inspected persistence or stored `resolved_as_of`/`fetch_time` fields.
- [x] Runtime reachability: Streamlit container/service health reachable at `127.0.0.1:8501` (`/_stcore/health` ok) at 2026-11-15 check.
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
| 2 | Resolved report as-of displayed | Explicit `resolved_as_of`/report date shown (not ambiguous) |  |  |  |
| 3 | Generation/fetch time displayed | `generated_at`/`fetch_time` shown (UTC or labeled timezone) |  |  |  |
| 4 | Data/context date labeling | Labels distinguish latest score/formation/context dates as applicable |  |  |  |
| 5 | Historical as-of selection | User can select historical `report_as_of` or UI clearly states not supported |  |  |  |
| 6 | Historical report correctness (if supported) | Output bounded to selected as-of context (not wall-clock/latest leakage) |  |  |  |
| 7 | Report metadata/provenance | report type/id/run/input identifiers or manifest refs visible or in artifact |  |  |  |
| 8 | Download filename/content | Filename/content include as-of/run identifiers as applicable; content matches displayed report |  |  |  |
| 9 | Persistence/retrieval | Previously generated reports retrievable with same metadata (or explicitly transient) |  |  |  |
| 10 | Caveats/labels | Deterministic/simulation/caveat labels present as required |  |  |  |

## Findings summary
| Gap ID | Finding | Severity | Related contract item | Recommended action |
|---|---|---|---|---|
|  |  |  |  |  |

## Sign-off
- **Result:** Pending / Pass / Pass with gaps / Fail
- **Attachments:**
- **Reviewer/date:**
- **Tracker updated:** `decision-unknown-tracker.md` (UNK-004)
