# Prompt_M1approval.md

# M1 Governance Review Prompt (Solo Maintainer)

## Purpose

Review repository evidence and determine the highest supportable M1 status based exclusively on verifiable evidence recorded in the repository.

Do not rely on assumptions, memory, undocumented history, inferred intent, historical conversations, or placeholder documentation.

Every conclusion must be traceable to evidence committed to the repository.

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

Advancement to a higher status is permitted only when supporting evidence already exists and has been committed to the repository.

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
- Approval granted
- Testing completed

Unsupported statements must be identified as findings requiring remediation.

## Repository Truth

When documentation conflicts with evidence:

- Repository evidence is authoritative.
- Documentation must be corrected.
- Status must reflect evidence rather than documentation.

---

# Canonical Evidence Locations

The following files are authoritative sources for milestone governance decisions.

## Primary Evidence Files

```text
docs/evidence/m1.md
docs/evidence/ci/m1-ci-evidence.md
docs/evidence/attestations/m1-attestation.md
docs/evidence/audit-checklist.md
docs/evidence/Prompt_M1approval.md
```

## Review Guidance

Reviewers should prefer canonical evidence locations when determining status.

Evidence stored elsewhere should be referenced from a canonical evidence file.

Evidence found only in:

- PR comments
- Issue comments
- Chat transcripts
- Temporary notes
- Draft documents

must not be considered authoritative unless linked from a canonical evidence file.

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
- Attestation references workflow run
- Attestation committed to repository

## Repository Evidence

Required:

- Evidence committed to version control
- Evidence references actual repository state
- No placeholder values remain
- No sample URLs remain
- No sample SHAs remain

---

# Placeholder Detection Rules

The following values are considered placeholders:

```text
TBD
TODO
Not yet recorded
Pending
Example URL
Example SHA
Sample SHA
Sample Workflow
Dummy Workflow
Placeholder
<run-url>
<sha>
<workflow>
```

The presence of placeholder values in required evidence fields results in:

```text
Status: BLOCKED
```

until corrected.

---

# Review Procedure

Perform the following review sequence in order.

---

## Step 1: Inspect Repository Evidence

Review:

```text
docs/evidence/
governance documentation
recovery documentation
decision logs
validation records
milestone records
```

Identify:

- recorded CI evidence
- maintainer attestations
- milestone declarations
- unsupported claims
- conflicting status statements

---

## Step 2: Validate CI Evidence

### Workflow Verification

Verify:

- workflow exists
- workflow completed successfully
- workflow run URL is recorded
- workflow evidence is internally consistent

Result:

```text
PASS
FAIL
NOT VERIFIED
```

### SHA Verification

Verify:

- tested SHA is recorded
- SHA exists in repository history
- SHA corresponds to workflow evidence
- SHA is not a placeholder value

Result:

```text
PASS
FAIL
NOT VERIFIED
```

---

## Step 3: Validate CI Run Authenticity

A valid CI run must:

- Reference a GitHub Actions workflow run
- Contain a workflow run identifier
- Correspond to the recorded tested SHA
- Be traceable to repository history
- Not be a sample or placeholder URL

Verify:

- Run URL is real
- Workflow exists
- Workflow status can be confirmed
- Workflow references the tested SHA

Result:

```text
PASS
FAIL
NOT VERIFIED
```

---

## Step 4: Validate Maintainer Attestation

Verify:

- attestation exists
- attestation references tested SHA
- attestation references workflow run
- attestation is committed

Result:

```text
PASS
FAIL
NOT VERIFIED
```

---

## Step 5: Validate Documentation Integrity

Identify:

- placeholder URLs
- placeholder SHAs
- unsupported CI claims
- unsupported completion claims
- contradictory status statements
- stale documentation

Result:

```text
PASS
FAIL
```

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
- Contradictory documentation exists

Output:

```text
Status: BLOCKED
```

Reason:

```text
Required evidence is incomplete, unsupported, or unverifiable.
```

---

## CI PASS

Use CI PASS only when all of the following are verified:

- Successful GitHub Actions workflow run
- Workflow run URL recorded
- Tested SHA recorded
- Evidence committed
- No placeholder values remain in CI evidence
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
- Repository cleanup may continue.
- Governance completion may still be pending.
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

Repository:
_________________________

Maintainer:
_________________________

Date:
_________________________

Branch:
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

# Anti-Retroactive Certification Rule

An attestation does not create evidence.

An attestation may only certify:

- Existing CI evidence
- Existing repository records
- Existing tested SHA records
- Existing workflow records

Attestations must not be used as a substitute for:

- Missing CI URLs
- Missing workflow runs
- Missing tested SHAs
- Missing validation records

If the underlying evidence does not exist:

```text
Status: BLOCKED
```

regardless of the presence of an attestation.

---

# Audit Checklist

## Canonical Evidence

Verify:

- [ ] docs/evidence/m1.md exists
- [ ] docs/evidence/ci/m1-ci-evidence.md exists
- [ ] docs/evidence/attestations/m1-attestation.md exists
- [ ] docs/evidence/audit-checklist.md exists

## CI Evidence

Verify:

- [ ] Workflow run exists
- [ ] Run URL recorded
- [ ] Workflow succeeded
- [ ] Tested SHA recorded
- [ ] Tested SHA exists in repository history

## Integrity Review

Verify:

- [ ] No placeholder URLs
- [ ] No placeholder SHAs
- [ ] No TBD values
- [ ] No TODO values
- [ ] No contradictory status statements
- [ ] No unsupported claims

## Attestation Review

Verify:

- [ ] Attestation completed
- [ ] Attestation references workflow run
- [ ] Attestation references tested SHA
- [ ] Attestation committed

---

# Required Output Format

Produce all of the following sections.

## Summary

Concise assessment of milestone readiness.

## Findings

Verified observations supported by repository evidence.

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

Include justification tied directly to evidence.

---

# Repository Cleanup Guidance

Repository cleanup may continue regardless of milestone status.

Examples:

- Removing unsupported approval claims
- Correcting governance documentation
- Updating templates
- Refactoring documentation
- Organizing evidence
- Creating audit records

Such activities are valuable but do not constitute proof of CI success.

Only verified evidence may change milestone status.

---

# Exit Criteria

## BLOCKED → CI PASS

Required:

- Verified workflow run
- Verified workflow URL
- Recorded tested SHA
- Evidence committed
- No placeholder values remain

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

Never use an attestation as a substitute for missing CI records.

Evidence first.

Status second.