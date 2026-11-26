# M1 External Evidence Steps (Pending)

Status: **PENDING** — no effective M1 approval or CI status is recorded.

## Current local state

- Branch: `fix/remove-m1-approval-claims`
- Current commit: `f611a51394c632f004f2fa29c01c7c2e52e815db`
- Repository: https://github.com/drelope/equity_screener
- Approval date recorded locally as owner-supplied: `2026-11-19` (not effective until CI run URL and approved SHA are recorded)
- Approver name: `[PENDING]`
- CI run URL observed (not approved): `https://github.com/drelope/equity_screener/actions/runs/45700975373/job/139510657402?pr=10`
- Approved SHA: `[PENDING]`

## Remaining steps

- [ ] 1. Project owner pushes the branch, or explicitly authorizes the agent to push.
- [ ] 2. CI runs on the exact commit SHA being approved.
- [x] 3. Captured CI run URL: `https://github.com/drelope/equity_screener/actions/runs/45700975373/job/139510657402?pr=10` (owner-supplied CI job URL; page title identifies `Remove unsupported M1 approval claims and document CI evidence` at `64f74e1`; visible job `Security (dependency audit + secret scan)` failed with exit code 127 (`pip-audit` command not found); warning: Node.js 20 actions forced to Node.js 24; not a passing CI baseline).
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
- M1 approval, CI status, merge, release, push, and tag remain BLOCKED; the captured CI job failed and is not a passing baseline.
