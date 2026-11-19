# Phase 0 Research: P0 Recovery Foundations

## Context

This research consolidates decisions already evidenced in the committed recovery package. No clarification markers remain in the spec, and no new technology is introduced for P0.

## Decision 1: Extend the existing platform instead of adopting the AI-IOS target architecture

- **Decision**: Keep the current modular Python/PostgreSQL/Streamlit/FastAPI platform. AI-IOS is a non-normative future-vision reference.
- **Rationale**: The approved P0 spec is about trustworthy historical evidence and verification gates, not an agent platform rebuild. The current platform already has the components P0 must harden.
- **Alternatives considered**: Build the full AI-IOS architecture now; rejected as out of scope and approval-gated. Replace the current stack; rejected as destructive and untraced.

## Decision 2: Keep candidate migrations outside the canonical migration path

- **Decision**: Maintain `V0107..V0113` under `docs/speckit-recovery/08-implementation-validation/sql-candidates/`.
- **Rationale**: Static hashes, dry-run apply/rollback rehearsals, and backfill readiness checks exist there. Moving files into `sql/migrations/` would make them discoverable before approval.
- **Alternatives considered**: Apply candidates directly to a shared database; rejected as unsafe. Reuse V0045; rejected because its rationale remains undocumented (UNK-006).

## Decision 3: Use additive DDL with explicit rollback

- **Decision**: All numbered candidates are additive-only and paired with rollback scripts.
- **Rationale**: Additive structures allow dual-read/backfill validation without destroying current evidence.
- **Alternatives considered**: In-place key changes and destructive cleanup; rejected until cutover evidence and approval exist.

## Decision 4: Separate DDL readiness from data backfill readiness

- **Decision**: Candidate schema checks and backfill/reconciliation checks are separate gates.
- **Rationale**: Applying additive DDL does not populate trusted data. The readiness checker proved that schemas can be present while data is `not_ready_no_backfill_data`.
- **Alternatives considered**: Treat successful DDL rehearsal as completion; rejected because it hides missing source mappings and taxonomy.

## Decision 5: Preserve current consumers until PIT backfill and comparisons are approved

- **Decision**: PIT helpers and manifest metadata are opt-in/draft; current consumers remain unchanged.
- **Rationale**: Survivor-vs-PIT deltas and status taxonomy are unresolved approval items.
- **Alternatives considered**: Switch consumers to PIT views immediately; rejected because tables are unpopulated and unapproved.

## Decision 6: Use two layers of manifest/output immutability

- **Decision**: Application-level conflict refusal in `manifest_store.py`/`output_store.py`, plus V0111 database triggers for the candidate ledger.
- **Rationale**: The application layer supports dry-run validation and idempotency; the trigger prevents ordinary SQL mutation after approval.
- **Alternatives considered**: Trigger only; rejected because it does not support safe dry-run behavior. Application only; rejected because privileged SQL can overwrite evidence.

## Decision 7: Keep persistence opt-in and explicit

- **Decision**: Ledger writes require `--persist --i-understand-ledger-write`; output writes require `--write --i-understand-run-output-write`.
- **Rationale**: Analysts and operators can inspect planned writes without touching a database or output store.
- **Alternatives considered**: Automatic pipeline persistence; rejected until DEC-002/003/005 approval and run-keyed cutover design.

## Decision 8: Treat governance events as append-only records, not enforcement

- **Decision**: V0113 records holds, exports, purge requests, incidents, and break-glass events with approver/dual-control constraints.
- **Rationale**: It provides an auditable control surface without claiming retention or incident-response policy is approved.
- **Alternatives considered**: Implement purge/retention jobs now; rejected because retention period and incident runbook are undecided.

## Decision 9: Use draft lock artifacts and report enforcement gaps

- **Decision**: Keep `requirements*.lock.txt` as draft snapshots; use checkers to report missing lock enforcement in CI and Docker.
- **Rationale**: Cross-platform/runtime lock strategy is DEC-008-gated. Silent enforcement would claim reproducibility not yet established.
- **Alternatives considered**: Enforce `--require-hashes` immediately; rejected without an approved index/mirror and platform policy.

## Decision 10: Separate evidence completeness from promotion-grade acceptance

- **Decision**: The closeout gate validates artifact presence/hashes and refuses promotion claims; the promotion checker reports explicit policy gaps.
- **Rationale**: Local evidence can be consistent without holdout, cost/benchmark, or statistical validation being complete.
- **Alternatives considered**: A single green gate implying readiness; rejected as misleading.

## Decision 11: Use disposable Postgres for DDL/backfill rehearsals

- **Decision**: All database rehearsals use explicitly named disposable containers with teardown; no shared database writes.
- **Rationale**: This allows real SQL validation without risking project data.
- **Alternatives considered**: Rehearse against the project database; rejected by execution constraints.

## Decision 12: Use existing checker commands as interface contracts

- **Decision**: CLI checkers are the external interface for static/read-only validation in this phase.
- **Rationale**: They already have exit codes, safety checks, JSON output, and tests.
- **Alternatives considered**: New API layer; rejected as unnecessary P0 scope.

## Research outcome

All technical choices needed for Phase 1 are resolved from existing evidence or explicitly deferred to named approval gates. No unresolved clarification markers remain.
