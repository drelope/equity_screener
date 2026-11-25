# M1 Corrections Audit

| Field | Value |
|---|---|
| Branch | `fix/remove-m1-approval-claims` |
| Correction commit | `4dfff7e` |
| Status | Locally Verified; M1/CI pending; Governance Approval blocked; Merge/Release blocked |
| Scope | Approval, ratification, Conditional GO, and promotion claims removed or changed after the project owner confirmed M1/CI evidence is not available |

## Why these corrections were made

The project owner confirmed that M1 approval and external CI evidence have been requested but not supplied. The assistant must not infer, record, or simulate either. Git identity (`drelo <drelo@localhost>`) is not an approver record. All role-based recommendations, draft constitutions, and local enforcement checks remain preparation only.

## Per-file changes

| File | Before | Now | Claim corrected |
|---|---|---|---|
| `docs/speckit-recovery/06-execution-prep/decision-unknown-tracker.md` | Status said M1 outcomes recorded by user direction. DEC-002/003/004/007/008 were “Approved outcome; evidence pending”; DEC-005 “Ratified”; DEC-001/006 deferred with dates; EX register rows open/time-bounded. | Status says draft, M1/CI evidence requested but not supplied. DEC rows are “Proposed outcome; pending approval” or “Proposed deferral; pending approval”; DEC-005 pending; DEC-008 “Proposed/local strategy … pending approval”; EX rows “Proposed; pending approval”. | Approval, ratification |
| `docs/speckit-recovery/06-execution-prep/m1-decision-log-template.md` | Status said recorded by user direction; session date 2026-11-18; facilitator/participants named by role; Go/No-Go “Conditional GO”; principles and 95-rule batch “Ratified”; EX/DEC outcomes approved/ratified; exit criteria “Met”; M1 status “Conditional GO …”; authorized by Governance Lead (role). | Status prepared for external approval, no M1/CI evidence supplied; session and identities Pending; Go/No-Go Pending; principles/rules pending review; EX/DEC proposed; exit criteria Pending; M1 status Pending external approval; authorized by Pending. | Approval, ratification, Conditional GO |
| `docs/speckit-recovery/06-execution-prep/m1-ratification-packet-2026-11-18.md` | Status “Adopted by user direction”; approval rule recorded role-based authority; decision log described as formal approval record; checklist as Met; step 7 allowed clearing T003 after ratification; outcome said M1 Conditional GO. | Status prepared for external approval; no approval recorded; decision log/checklist Pending; step 7 says T003 may be cleared only after recorded external approval; outcome says no GO recorded and merge/release blocked. | Approval, ratification, Conditional GO |
| `docs/speckit-recovery/06-execution-prep/m1-readiness-checklist.md` | Status recorded by user direction; packet adopted; M1-01..07 and M1-D/V rows Met; exit boxes checked including “Conditional GO recorded”. | Status prepared for external approval; M1 rows Pending/proposed; all exit boxes unchecked; final box says “No GO recorded; M1 approval pending; merge and release blocked.” | Approval, Conditional GO |
| `docs/speckit-recovery/06-execution-prep/project-constitution-ratification-draft.md` | Title “Ratified (Role-Based Authority)”; status ratified by user direction; approval rule effective from 2026-11-18; outcome ratified and Conditional GO. | Title “Ratification Draft”; status prepared for external approval; approval pending; outcome says no approval supplied and merge/release/promotion/cutover blocked. | Ratification, Conditional GO |
| `docs/speckit-recovery/08-implementation-validation/STATUS-2026-11-16.md` | “M1 record adopted” with ratified constitution, exit items Met, T003 cleared, Conditional GO. | “M1 preparation only”; external approval not supplied; M1 Pending; merge/release/promotion/cutover blocked; do not infer approval from git identity. | Approval, ratification, Conditional GO |
| `docs/speckit-recovery/08-implementation-validation/evidence-closeout-index.json` | Hashes reflected prior approval claims; generated at 17:30. | Hashes refreshed for corrected files; generated at 18:45. `promotion_claim=false` and `promotion_grade=false` unchanged. | Promotion claim integrity |
| `docs/speckit-recovery/08-implementation-validation/execution-log.md` | Historical row said M1 recommended record adopted, constitution ratified, T003 cleared, Conditional GO. | Row corrected to “M1 preparation: recommendations recorded” with no approval/CI status. Added availability check, governance status correction, and approval-gated task status correction rows. | Approval, ratification, Conditional GO |
| `docs/speckit-recovery/08-implementation-validation/p0-acceptance-evidence-tracker.md` | External gates listed but no availability check. | Added external-evidence availability check: no remote, no `gh`, no upstream, git identity not authoritative; M1 and CI remain blocked. | Approval/CI evidence |
| `docs/speckit-recovery/08-implementation-validation/reproducibility-lock-policy-draft.md` | Status “Ratified 2026-11-18”; lock files described as ratified; format ratified. | Status draft with local enforcement implemented and DEC-008 approval pending; lock files and format described as exact-pin/proposed with formal approval pending. | Ratification |
| `docs/speckit-recovery/08-implementation-validation/rtm-update-draft.md` | No correction rows. | Added M1/CI status correction and approval-gated task status correction rows; no approval or CI status recorded. | Approval/CI evidence |
| `docs/speckit-recovery/08-implementation-validation/us4-verification-2026-11-18.md` | DEC-008 “ratified”; enforcement reporter described ratified checks. | DEC-008 proposed/local strategy with formal approval pending; reporter described local checks. | Ratification |
| `docs/speckit-recovery/08-implementation-validation/us6-verification-2026-11-18.md` | M1 log “records M1 Conditional GO … Authority is role-based”. | M1 log contains prepared recommendations; approval pending; no named approver or CI evidence supplied. | Conditional GO, approval |
| `scripts/check_evidence_closeout.py` | Required policy text “Ratified 2026-11-18” and reported “lost DEC-008 ratification record”. | Requires “approval pending”; reports policy does not mark DEC-008 approval as pending. | Ratification |
| `scripts/check_reproducibility_enforcement.py` | Required “Ratified 2026-11-18” and reported missing DEC-008 ratification. | Requires “approval pending”; reports policy does not mark DEC-008 approval as pending. | Ratification |
| `specs/001-p0-recovery/plan.md` | Status M1 ratified and implementation gate cleared; gate status “RATIFIED FOR GOVERNED IMPLEMENTATION (ROLE-BASED AUTHORITY)”; constitution ratified; implementation may begin. | Status local validation only, M1/CI pending, merge/release blocked; gate pending external M1 approval; constitution draft; merge/release/promotion/cutover blocked until evidence. | Ratification, approval |
| `specs/001-p0-recovery/quickstart.md` | Stop condition referred to ratified constitution but allowed implementation. | Stop condition says missing M1 approval/ratification blocks merge, release, promotion, and cutover. | Ratification, approval |
| `specs/001-p0-recovery/spec.md` | Status “M1 ratified by user direction”. | Status local validation complete, M1/CI evidence pending, merge and release blocked. | Ratification, approval |
| `specs/001-p0-recovery/tasks.md` | T003, T030, T042 were complete; T032 said “ratified lock version”. | T003/T030/T042 unchecked and approval-gated; T032 says “lock strategy version”. | Approval-gated tasks |

## Approval-gated task changes

| Task | Before | Now | Why approval-gated |
|---|---|---|---|
| T003 | `[X]` M1 constitution disposition recorded and ratified constitution in `.specify/memory/constitution.md`; named individual substitution was an audit follow-up. | `[ ]` Obtain external M1 approval for the prepared constitution and record named authority/date in `m1-decision-log-template.md`; merge/release blocked until supplied. | Only the sole project owner can approve M1. No named approver/date was supplied, so the task cannot be complete. |
| T030 | `[X]` Ratify the lock strategy and record DEC-008 in `decision-unknown-tracker.md`. | `[ ]` Obtain external DEC-008 approval for the locally enforced lock strategy and record it. | Local lock enforcement is not formal DEC-008 approval; external approval evidence is missing. |
| T042 | `[X]` Ratify M1 decisions in `m1-decision-log-template.md`. | `[ ]` Obtain external ratification of M1 decisions; no approval evidence supplied. | M1 decisions require the sole owner’s approval, which has not been provided. |

## Non-claims

- No approval, ratification, Conditional GO, promotion-grade status, CI run, or release readiness is recorded by this audit.
- The governance/checklist drafts added under this correction are drafts only and are not approved by the project owner.
- Merge, release, promotion, and cutover remain blocked.

## Additional stale claims found in leftover sweep

| File | Stale text | Corrected text | Accurate? |
|---|---|---|---|
| `docs/speckit-recovery/08-implementation-validation/STATUS-2026-11-16.md` | “DEC-008 ratified for exact pins plus lock-file SHA-256 and enforced locally” | “DEC-008 exact-pins-plus-lock-SHA strategy is locally enforced but not externally approved” | No — removed ratification claim |
| `docs/speckit-recovery/08-implementation-validation/p0-acceptance-evidence-tracker.md` | “DEC-008 ratified exact pins + lock SHA-256” | “DEC-008 exact pins + lock SHA-256 locally enforced … external approval pending” | No — removed ratification claim |

All other `approval`/`approved` hits are accurate when read in context: they describe pending approvals, draft/non-approval status, approval gates, planned required approvals, historical execution-log wording that was corrected in the same file, or code/test constants such as `draft_not_approved` and `--require-approved`. `GO` hits are accurate as `no_go`, `go/no_go`, or draft non-claim language; no standalone approved GO remains. No `promotion_grade=true` or `release ready` hit was found.

### Additional stale wording fixed in the same sweep

| File | Before | Now |
|---|---|---|
| `docs/speckit-recovery/06-execution-prep/decision-unknown-tracker.md` | DEC-005 status “Ratified” with 2026-11-18 | “Proposed; pending approval” with Pending date |
| `docs/speckit-recovery/06-execution-prep/m1-decision-log-template.md` | Column label “ratified/modified/deferred/rejected” | “approve/modify/defer/reject” |
| `docs/speckit-recovery/08-implementation-validation/evidence-closeout-index.json` | Blocker “DEC-008 lock strategy not ratified” | “DEC-008 lock strategy approval pending” |
| `scripts/check_clean_environment_parity.py` | Docstring “both ratified lock files” | “both exact-pin lock files” |
| `scripts/check_evidence_closeout.py` | Error text “lost the ratified lock strategy” | “lost the proposed lock strategy” |
| `scripts/check_reproducibility_enforcement.py` | Docstring/error text “ratified lock strategy” | “proposed lock strategy” |
| `src/crispdm/run_manifest.py` | Docstring “Return ratified dependency identity” | “Return dependency identity” |

## Full claim-sweep report

- Hit-by-hit classifications are in `docs/M1_CLAIM_SCAN_REPORT.md`.
- The sweep covers all tracked/untracked repo text files and all 54 closeout artifacts. It uses the owner's literal terms: `ratified`, `Conditional GO`, `approved`, `approval`, `GO`, `promotion_grade=true`, `release ready`.
- No `promotion_grade=true` or `release ready` claim was found.
- No active M1 ratification or Conditional GO claim remains after the fixes above.
- Hits needing manual review are historical model GO/NO-GO findings, future approval requirements, or blank approval fields in draft governance files; none records an M1 approval.
