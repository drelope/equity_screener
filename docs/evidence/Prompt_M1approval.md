# Prompt_M1approval.md

## Purpose

This prompt guides reviewers through M1 governance validation without making unsupported claims.

## Objective

Determine whether Milestone M1 can advance based on verifiable evidence.

## Required Evidence

1. Verified GitHub Actions run URL
2. Exact tested commit SHA
3. Approval evidence OR documented solo-maintainer exception
4. Evidence committed to the repository

## Review Procedure

- Inspect the pull request.
- Open the Checks tab.
- Locate the latest successful workflow run.
- Record the workflow URL.
- Record the tested commit SHA.
- Verify governance documentation references only documented evidence.
- Ensure no approval claims exist without supporting evidence.

## Status Rules

### BLOCKED
Use when any required evidence is missing.

### CI PASS
Use only when:
- A successful workflow run is verified.
- The workflow URL is recorded.
- The tested SHA is recorded.

### APPROVAL PASS
Use only when:
- Approval evidence is documented, or
- An approved solo-maintainer exception is documented.

## Required Output

Report:

- Current status
- Missing evidence
- Verified CI evidence
- Verified approval evidence
- Recommended next actions

## Audit Principle

Do not infer, assume, or fabricate approval status, CI results, approvers, SHAs, dates, or workflow URLs. Record only evidence that can be independently verified.
