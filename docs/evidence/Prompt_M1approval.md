# Prompt_M1approval.md

# M1 Governance Review Prompt (Solo Maintainer)

## Purpose

Review repository evidence and determine the highest supportable M1 status based exclusively on verifiable evidence recorded in the repository.

Do not rely on assumptions, memory, undocumented history, or inferred intent.

Every conclusion must be traceable to evidence stored in version control.

---

# Governance Model

This repository operates under a solo-maintainer governance model.

Independent reviewer approval is not required.

Repository status progression is:

```text
BLOCKED
    ↓
CI PASS
    ↓
COMPLETE
```

Advancement to a higher status is permitted only when the supporting evidence already exists in the repository.

---

# Core Principles

## Evidence First

Evidence creates status.

Status does not create evidence.

A milestone may only advance when supporting evidence has been collected, verified, and committed.

## No Unsupported Claims

Do not report any of the following unless verifiable evidence exists:

- Milestone approved
- CI passed
- Validation completed
- Acceptance criteria satisfied
- Milestone complete

Unsupported statements must be identified as findings requiring remediation.

## Repository Truth

When documentation conflicts with evidence:

- Repository evidence is authoritative.
- Documentation must be corrected.
- Status must reflect the evidence rather than the documentation.

---

# Required Evidence

## CI Evidence

Required:

- Verified GitHub Actions workflow run
- Successful workflow completion
- Recorded workflow run URL
- Recorded tested commit SHA

Optional:

- Build logs
- Test reports
- Screenshots
- Additional validation artifacts

## Maintainer Evidence

Required for COMPLETE:

- Written maintainer attestation
- Attestation references tested SHA
- Attestation references CI run
- Attestation committed to the repository

## Repository Evidence

Required:

- Evidence committed to version control
- Evidence references actual repository state
- No placeholder values remain
- No sample URLs remain
- No sample SHAs remain

---

# Review Procedure

Perform the following review sequence.

---

## Step 1: Inspect Repository Evidence

Review all relevant evidence locations including:

- docs/evidence/
- governance documentation
- recovery documentation
- decision logs
- validation records
- milestone records

Identify:

- recorded CI evidence
- maintainer attestations
- milestone status declarations
- unsupported claims

---

## Step 2: Validate CI Evidence

### Workflow Verification

Verify:

- workflow exists
- workflow completed successfully
- workflow run URL is recorded
- workflow evidence is internally consistent

Result:

- PASS
- FAIL
- NOT VERIFIED

### SHA Verification

Verify:

- tested SHA is recorded
- SHA exists in repository history
- SHA corresponds to workflow evidence

Result:

- PASS
- FAIL
- NOT VERIFIED

---

## Step 3: Validate Maintainer Attestation

Verify:

- attestation exists
- attestation references tested SHA
- attestation references workflow run
- attestation is committed

Result:

- PASS
- FAIL
- NOT VERIFIED

---

## Step 4: Validate Documentation Integrity

Identify:

- placeholder URLs
- placeholder SHAs
- unsupported CI claims
- unsupported completion claims
- contradictory status statements

Result:

- PASS
- FAIL

---

# Status Matrix

## BLOCKED

Use BLOCKED when any required CI evidence is missing.

Conditions include:

- Missing workflow run URL
- Missing tested SHA
- Workflow success cannot be verified
- Evidence not committed
- Placeholder values remain
- Unsupported claims remain

Output:

```text
Status: BLOCKED
```

Reason:

```text
Required evidence is incomplete or unverifiable.
```

---

## CI PASS

Use CI PASS only when all of the following are verified:

- Successful GitHub Actions workflow run
- Workflow run URL recorded
- Tested SHA recorded
- Evidence committed
- No unsupported CI claims remain

Output:

```text
Status: CI PASS
```

Reason:

```text
Required CI evidence has been verified and recorded.
```

Notes:

- Implementation work may continue.
- Documentation cleanup may continue.
- Maintainer attestation may still be pending.

---

## COMPLETE

Use COMPLETE only when all of the following are verified:

- CI PASS requirements satisfied
- Maintainer attestation recorded
- Attestation references tested SHA
- Attestation references workflow run
- Documentation internally consistent
- No unsupported claims remain

Output:

```text
Status: COMPLETE
```

Reason:

```text
Required governance evidence has been verified and recorded.
```

---

# Maintainer Attestation Template

```text
Maintainer Attestation

Maintainer:
_________________________

Date:
_________________________

Tested SHA:
_________________________

GitHub Actions Run:
_________________________

Workflow:
_________________________

Attestation:

I attest that:

1. The commit identified above successfully completed the required CI workflow.
2. The recorded SHA matches the commit evaluated for M1.
3. Repository evidence accurately reflects the current state of validation.
4. No known unsupported approval or CI claims remain.
5. M1 acceptance criteria have been reviewed and satisfied.

Signed:

_________________________
```

---

# Required Output Format

Produce the following sections.

## Summary

Concise assessment of milestone readiness.

## Findings

Verified observations supported by evidence.

## Missing Evidence

List unresolved evidence gaps.

## Unsupported Claims

List unsupported or contradictory statements.

## Recommended Actions

Provide prioritized remediation actions.

## Determination

One of:

```text
BLOCKED
CI PASS
COMPLETE
```

Provide supporting justification.

---

# Repository Cleanup Guidance

Repository cleanup may continue regardless of milestone status.

Examples:

- Removing unsupported approval claims
- Correcting governance documentation
- Updating evidence templates
- Refactoring repository documentation
- Organizing validation records

Such activities do not constitute proof of CI success.

Only verified evidence may change milestone status.

---

# Exit Criteria

## BLOCKED → CI PASS

Required:

- Verified workflow run
- Recorded workflow URL
- Recorded tested SHA
- Evidence committed

## CI PASS → COMPLETE

Required:

- Maintainer attestation completed
- Attestation committed
- Documentation internally consistent
- No unsupported claims remain

---

# Reviewer's Final Rule

If evidence is missing:

```text
Report BLOCKED.
```

If evidence exists:

```text
Report the highest status fully supported by evidence.
```

Never infer missing evidence.

Never replace evidence with assumptions.

Evidence first.
Status second.