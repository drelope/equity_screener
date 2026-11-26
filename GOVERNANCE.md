# GOVERNANCE.md — DRAFT, not approved by project owner

M1 approval authority
- Approver: [PROJECT OWNER TO FILL IN]
- Delegate: none (single-person project)
- Independent reviewer: [NAME] or "none available"
- Approval label: [self-approved, no independent review] OR
  [self-approved, externally reviewed by <name>]
- Approval must reference: commit SHA + CI run URL
- Agents and git identities cannot approve
- Approval record location: [TO BE DEFINED]

M1 approval record (supersedes commit 86f6a59; new commit, no history rewrite):
- approver name [PENDING]
- approval date: 2026-11-19 (owner-supplied; not effective until CI run URL and approved SHA are recorded)
- repository: https://github.com/drelope/equity_screener
- CI run URL (observed, not approved): https://github.com/drelope/equity_screener/actions/runs/45700975373/job/139510657402?pr=10
- approved SHA [PENDING]
- Observed CI: owner-supplied CI job URL; page title identifies `Remove unsupported M1 approval claims and document CI evidence` at `64f74e1`; visible job `Security (dependency audit + secret scan)` failed with exit code 127 (`pip-audit` command not found); warning: Node.js 20 actions forced to Node.js 24; not a passing CI baseline
- Status: M1 approval, CI status, merge, release, push, and tag are BLOCKED
