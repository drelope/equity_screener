# M1 Review Checklist — DRAFT, not approved by project owner

All fields are intentionally blank and all boxes unchecked. This is a time-separated self-review artifact for the project owner.

## 1. Scope and claims — before review

- [ ] Confirm review date/time:
- [ ] Confirm candidate commit SHA:
- [ ] Confirm candidate CI run URL:
- [ ] Confirm status is Locally Verified, M1/CI pending, Governance Approval blocked, Merge/Release blocked
- [ ] Confirm no approval, ratification, Conditional GO, promotion, or release-ready claim is recorded
- [ ] Confirm agent-generated governance rules were not substituted for owner approval rules

## 2. Task status — during review

- [ ] Confirm T003 remains unchecked pending M1 approval
- [ ] Confirm T030 remains unchecked pending DEC-008 approval
- [ ] Confirm T042 remains unchecked pending M1 ratification
- [ ] Confirm all non-approval-gated local tasks are complete
- [ ] Record discrepancies:

## 3. Clean-checkout re-verification — during review

- [ ] Re-clone/checkout candidate SHA in a clean directory:
- [ ] Confirm lock files install from `requirements*.lock.txt`
- [ ] Re-run closeout gate; record output:
- [ ] Re-run reproducibility enforcement; record output:
- [ ] Re-run candidate checker; record output:
- [ ] Re-run lint/format; record output:
- [ ] Re-run full pytest; record counts:
- [ ] Record skipped/xfailed tests and reasons:

## 4. Guardrail integrity — during review

- [ ] Confirm `promotion_grade=false`
- [ ] Confirm `--require-promotion-grade` still fails
- [ ] Confirm `--require-enforced` still fails without parity evidence
- [ ] Confirm shared/production DSNs are refused by write helpers
- [ ] Confirm candidates remain outside `sql/migrations/`
- [ ] Confirm no test was deleted, skipped, or loosened locally
- [ ] Record guardrail concerns:

## 5. CI evidence — after external run

- [ ] Paste external CI run URL:
- [ ] Record CI commit SHA:
- [ ] Record CI conclusion:
- [ ] Record pytest passed/failed/skipped counts from CI:
- [ ] Record skipped/xfailed tests and reasons from CI:
- [ ] Confirm CI SHA matches candidate SHA
- [ ] Record mismatches:

## 6. Risks and exceptions — after evidence review

- [ ] Review EX-001..EX-005 residual risk and expiry:
- [ ] Review DEC-001..DEC-008 closure evidence:
- [ ] Review UNK-001..UNK-007 closure evidence:
- [ ] Confirm no unbounded Critical exception remains
- [ ] Record accepted risks:
- [ ] Record rejected risks:

## 7. Bias check — final review

- [ ] Review survivor-vs-PIT delta evidence:
- [ ] Review adjustment/basis caveats:
- [ ] Review Reports Center as-of and provenance evidence:
- [ ] Review promotion benchmark/cost evidence:
- [ ] Record bias findings:

## 8. Decision — project owner only

- [ ] Approver name:
- [ ] Approver role:
- [ ] Approval date/time:
- [ ] Approval label:
- [ ] Referenced commit SHA:
- [ ] Referenced CI run URL:
- [ ] Decision:
- [ ] Approval record location:
