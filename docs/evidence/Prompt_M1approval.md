# Prompt_M1approval.md

# M1 Governance Review Prompt (Solo Maintainer)

## Purpose

Review repository evidence and determine the highest supportable M1 status based solely on verifiable evidence recorded in the repository.

This review must not rely on assumptions, memory, or undocumented claims.

All conclusions must be traceable to evidence stored in version control.

---

# Governance Model

This repository is maintained under a solo-maintainer governance model.

Independent reviewer approval is not required.

Evidence-based validation is required.

Milestone progression is:

BLOCKED → CI PASS → COMPLETE

Status advancement must be supported by repository evidence at the time of review.

---

# Core Principles

## Evidence First

Evidence creates status.

Status does not create evidence.

A milestone may only be advanced when supporting evidence already exists.

## No Unsupported Claims

Do not report any of the following unless evidence is present:

- Approval granted
- CI passed
- Verification completed
- Acceptance criteria satisfied
- Milestone complete

Unsupported claims must be reported as findings.

## Repository Truth

When documentation conflicts with evidence:

Repository evidence is authoritative.

Documentation must be corrected.

---

# Required Evidence

## CI Evidence

Required:

- GitHub Actions workflow run exists
- Workflow completed successfully
- Workflow run URL recorded
- Exact tested commit SHA recorded

Optional:

- Workflow screenshots
- CI logs
- Additional artifacts

## Maintainer Evidence

Required:

- Written maintainer attestation
- Attestation references tested SHA
- Attestation stored in repository

## Repository Evidence

Required:

- Evidence files committed
- Evidence references actual repository state
- No placeholder values remain

---

# Review Procedure

Perform the following review sequence.

## Step 1: Inspect Evidence

Review:

- docs/evidence/
- governance documentation
- milestone documents
- recovery documents
- decision logs
- validation records

Identify:

- recorded CI evidence
- attestation records
- milestone status declarations

---

## Step 2: Validate CI Evidence

Verify:

### Workflow Run

Evidence exists for:

- workflow name
- workflow result
- workflow URL

Result:

PASS
FAIL
NOT VERIFIED

### Tested SHA

Verify:

- SHA recorded
- SHA exists in repository history
- SHA matches workflow evidence

Result:

PASS
FAIL
NOT VERIFIED

---

## Step 3: Validate Maintainer Attestation

Verify:

- attestation exists
- attestation references tested SHA
- attestation is committed

Result:

PASS
FAIL
NOT VERIFIED

---

## Step 4: Review Documentation Integrity

Identify:

- unsupported approval claims
- unsupported CI claims
- placeholder URLs
- placeholder SHAs
- contradictory status values

Result:

PASS
FAIL

---

# Status Determination Rules

## BLOCKED

Return BLOCKED when ANY of the following are true:

- CI run not recorded
- CI URL missing
- Tested SHA missing
- Workflow success cannot be verified
- Attestation missing
- Evidence not committed
- Placeholder values present
- Unsupported claims present

Output:

Status: BLOCKED

Reason:
Missing required evidence.

---

## CI PASS

Return CI PASS only when ALL of the following are true:

- GitHub Actions workflow successfully completed
- Run URL recorded
- Tested SHA recorded
- Evidence committed
- No unsupported CI claims remain

Output:

Status: CI PASS

Reason:
CI evidence verified.

Note:
Repository may proceed with implementation and cleanup activities while awaiting final milestone completion requirements.

---

## COMPLETE

Return COMPLETE only when ALL of the following are true:

- CI PASS requirements satisfied
- Maintainer attestation recorded
- Documentation internally consistent
- No unsupported claims remain
- Evidence repository is complete

Output:

Status: COMPLETE

Reason:
Required governance evidence verified.

---

# Required Output Format

Produce the following sections.

## Summary

Brief overall assessment.

## Findings

List verified findings.

## Missing Evidence

List unresolved evidence gaps.

## Unsupported Claims

List any unsupported statements discovered.

## Recommended Actions

Provide prioritized remediation actions.

## Determination

One of:

- BLOCKED
- CI PASS
- COMPLETE

Provide justification.

---

# Repository Cleanup Guidance

Repository cleanup may proceed while status remains BLOCKED.

Examples:

- Removing unsupported approval statements
- Correcting governance documents
- Updating evidence templates
- Refactoring documentation
- Organizing validation records

Such work does not constitute proof of CI success.

Only verified evidence may change milestone status.

---

# Reviewer's Final Rule

If evidence is missing:

Report BLOCKED.

If evidence exists:

Report the highest status fully supported by repository evidence.

Never infer missing evidence.

Never replace evidence with assumptions.

Evidence first.
Status second.