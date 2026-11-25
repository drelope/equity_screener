# Implementation & Validation Package (Approved — Prepared for Execution)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Status | **Implementation/validation approved and partially executed (2026-11-16): scoped source/test changes and validations completed for dividend batch/date handling, Reports Center provenance labels, and run-manifest foundation; broader P0 RM-01..07 work and human/external gates remain.** |
| Scope | P0 foundation (`RM-01..07`, `P0-TSK-001..010`, `TSK-001..003,008..011,014,016..023,026`) with traceability to recommendations Steps 1–8 |
| Inputs | `../02-requirements/*`, `../04-migration/*`, `../05-speckit/*`, `../06-execution-prep/*`, `../07-recommendations/*` |

## Artifacts

| File | Purpose |
|---|---|
| `implementation-plan.md` | Ordered implementation work packages, target files/areas, code/schema contracts, dependencies, PR slicing |
| `validation-plan.md` | Test/verification matrix mapped to `AC-P0-*`, `QG-*`, FR/NFR/RM, environments, and evidence to capture |
| `migration-backfill-plan.md` | Schema/data migration sequencing, backfill/recompute strategy, rollback and safety controls |
| `rtm-update-draft.md` | RTM/status update template to apply as evidence is produced (no statuses claimed verified) |
| `execution-log.md` | Execution log template for recording commands, results, artifacts, approvals, and deviations |
| `evidence-closeout-index.json` | Hash-locked index of the curated draft evidence bundle; `promotion_claim=false` |
| `scripts/check_evidence_closeout.py` | CI gate that validates the bundle and always refuses promotion-grade claims |
| `scripts/check_reproducibility_enforcement.py` | RM-06 draft reporter for CI/Docker lock-enforcement gaps |
| `run-output-store-draft.md` | RM-05 run-keyed output store design and non-claims |

## Execution constraints (must follow during implementation)
- Treat all Partial/Missing as unverified until task-level evidence exists; do not claim promotion-grade readiness.
- Apply `EX-001..05` interim labeling/compensating controls until resolved/verified per recorded approvals.
- No shared/production DB writes for experimental duplicate-key or loader behavior tests; use isolated disposable DB/schema with teardown/rollback.
- Record `run_id`/manifest, code SHA, config/policy hashes, and evidence paths for all material validation runs.
- Update RTM and decision tracker with actual evidence; keep Descriptive vs Aspirational constitution rules separated unless reclassified with proof.
