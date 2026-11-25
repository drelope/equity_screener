# M1 External Evidence Steps (Pending)

Status: **PENDING** — no effective M1 approval or CI status is recorded.

## Current local state

- Branch: `fix/remove-m1-approval-claims`
- Current commit: `f611a51394c632f004f2fa29c01c7c2e52e815db`
- Repository: https://github.com/drelope/equity_screener
- Approval date recorded locally as owner-supplied: `2026-11-19` (not effective until CI run URL and approved SHA are recorded)
- Approver name: `[PENDING]`
- CI run URL: `[PENDING]`
- Approved SHA: `[PENDING]`

## Remaining steps

- [ ] 1. Project owner pushes the branch, or explicitly authorizes the agent to push.
- [ ] 2. CI runs on the exact commit SHA being approved.
- [ ] 3. Capture the CI run URL in the form `https://github.com/drelope/equity_screener/actions/runs/<run_id>`.
- [ ] 4. Confirm the exact commit SHA approved by that CI run.
- [ ] 5. Supply the approver name.
- [ ] 6. Agent records approver name, CI run URL, and approved SHA in `GOVERNANCE.md`, `docs/speckit-recovery/06-execution-prep/m1-decision-log-template.md`, and `docs/speckit-recovery/08-implementation-validation/p0-acceptance-evidence-tracker.md`.
- [ ] 7. Agent refreshes the evidence index and re-runs closeout, reproducibility, candidate, lint/format, and full-suite validation.
- [ ] 8. Agent commits the record locally and reports the new commit SHA.
- [ ] 9. Merge, release, tag, and push remain BLOCKED until explicitly authorized.

## Gate invariants

- The repository URL is not a CI run URL.
- CI run URL must reference the exact approved commit SHA.
- `promotion_grade` remains `false`.
- M1 approval, CI status, merge, release, push, and tag remain BLOCKED until all steps above are complete.
