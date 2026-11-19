# Tasks: P0 Recovery Foundations

**Input**: Design documents from `specs/001-p0-recovery/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/interface-contracts.md`, and `quickstart.md`

**Status**: Generated after review-plan approval; not implementation-complete

**Organization**: Tasks are grouped by user story so each story can be validated independently. Verification tasks use existing commands and paths; no new test suite is requested by the spec.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks).
- **[Story]**: User story phase label only.
- Every task includes an exact file path.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the approved feature state and governance baseline.

- [ ] T001 Verify active feature state in `.specify/feature.json` and branch state in `specs/001-p0-recovery/plan.md` (SC-012)
- [ ] T002 [P] Confirm approved spec status in `specs/001-p0-recovery/spec.md` and plan status in `specs/001-p0-recovery/plan.md` (SC-012)
- [ ] T003 [P] Block implementation until M1 records constitution disposition in `docs/speckit-recovery/06-execution-prep/m1-decision-log-template.md` and a ratified constitution replaces `.specify/memory/constitution.md` (FR-023, SC-010)

**Checkpoint**: Feature state, approvals, and governance caveats are visible.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish static safety baselines before story work.

- [ ] T004 Freeze candidate inventory and hashes with `scripts/check_migration_candidates.py` (FR-024, SC-012)
- [ ] T005 [P] Verify the hash-locked evidence bundle in `docs/speckit-recovery/08-implementation-validation/evidence-closeout-index.json` (SC-012)
- [ ] T006 [P] Verify draft lock artifacts with `scripts/check_reproducibility_locks.py` (FR-017, SC-007)
- [ ] T007 [P] Confirm disposable-target safety guard in `scripts/rehearse_p0_full.py` (FR-025, SC-012)
- [ ] T008 Run the baseline full suite documented in `specs/001-p0-recovery/quickstart.md` (SC-008, SC-012)

**Checkpoint**: Static baselines pass and no shared/production write path is enabled.

---

## Phase 3: User Story 1 - Trust historical research inputs (Priority: P1) 🎯 MVP

**Goal**: Historical universes, features, labels, and dividend facts reflect only information available as of the requested date.

**Independent Test**: Replay the same historical date twice, including a security whose membership or filing availability changes after that date; the eligible inputs are identical and use no later information.

- [ ] T009 [P] [US1] Verify explicit `as_of` handling for covered replay paths in `src/crispdm/pit.py` and `src/crispdm/feature_window.py` (FR-001, SC-001)
- [ ] T010 [P] [US1] Verify membership interval structures in `docs/speckit-recovery/08-implementation-validation/sql-candidates/V0107_rm01_pit_membership.sql` (FR-002)
- [ ] T011 [US1] Define approved delisting and reclassification backfill rules in `docs/speckit-recovery/08-implementation-validation/migration-backfill-plan.md` (FR-003)
- [ ] T012 [P] [US1] Verify timing-column contract in `docs/speckit-recovery/08-implementation-validation/sql-candidates/V0108_rm02_pit_timing.sql` (FR-004)
- [ ] T013 [US1] Record the availability/proxy policy for unknown timing in `docs/speckit-recovery/06-execution-prep/validation-plans-unk001-007.md` (FR-005, SC-002)
- [ ] T014 [US1] Create the survivor-vs-PIT comparison artifact at `docs/speckit-recovery/08-implementation-validation/pit-delta-2026-11-18.md` (SC-002)
- [ ] T015 [P] [US1] Run read-only backfill checks with `scripts/check_candidate_backfill_readiness.py` and save output under `docs/speckit-recovery/08-implementation-validation/sql-candidates/backfill/` (FR-002, FR-004, SC-002)

**Checkpoint**: PIT inputs, timing policy, and comparison evidence are independently reviewable.

---

## Phase 4: User Story 2 - Preserve defensible decision evidence (Priority: P1)

**Goal**: Material outputs are immutable, run-addressable, and linked to complete manifests.

**Independent Test**: Produce a run, attempt a conflicting replacement, and confirm the original evidence remains unchanged while identical reruns are no-ops.

- [ ] T016 [P] [US2] Verify manifest conflict and idempotency behavior in `src/crispdm/manifest_store.py` (FR-007, FR-008, FR-010, SC-003, SC-005)
- [ ] T017 [P] [US2] Verify no-overwrite output storage in `src/crispdm/output_store.py` (FR-006, FR-009, FR-011, SC-004, SC-005)
- [ ] T018 [US2] Wire opt-in ledger/output persistence into material runs after DEC-002/003/005 approval in `scripts/score_rank.py`, `scripts/backtest.py`, and `scripts/evaluate_walk_forward.py` (FR-008, FR-011)
- [ ] T019 [US2] Rehearse append-only ledger DDL and rollback with `scripts/rehearse_p0_full.py` against `docs/speckit-recovery/08-implementation-validation/sql-candidates/V0110_rm04_run_manifest_ledger.sql` and `V0111_rm04_manifest_immutability.sql` (SC-004)
- [ ] T020 [P] [US2] Review speculative grants and governance-event candidates in `docs/speckit-recovery/08-implementation-validation/sql-candidates/V0112_rm04_ledger_role_grants.sql` and `V0113_rm04_ledger_governance_events.sql` (FR-006, FR-022, SC-004)
- [ ] T021 [US2] Complete retention and incident-response decisions in `docs/speckit-recovery/08-implementation-validation/manifest-ledger-governance-policy-draft.md` (FR-006, FR-022, FR-024)
- [ ] T022 [US2] Archive run-keyed read and integrity evidence under `docs/speckit-recovery/08-implementation-validation/sql-candidates/backfill/` (FR-008, SC-003, SC-012)

**Checkpoint**: Evidence immutability, retrieval, and governance preconditions are independently reviewable.

---

## Phase 5: User Story 3 - Evaluate with explicit economics and matched comparisons (Priority: P2)

**Goal**: Evaluation evidence includes formation rules, costs, net results, and exposure-matched comparisons.

**Independent Test**: Open a completed evaluation bundle and verify formation rules, versioned costs, gross/net results, and matched comparison are present.

- [ ] T023 [P] [US3] Define approved cost-model fields in `docs/speckit-recovery/08-implementation-validation/promotion-policy-template.json` (FR-012, FR-013)
- [ ] T024 [US3] Replace draft economics placeholders with approved versioned fields in `scripts/backtest.py` (FR-012, FR-013, FR-014, SC-006)
- [ ] T025 [US3] Implement the exposure-matched comparison contract in `src/crispdm/backtest.py` and `scripts/backtest.py` (FR-014, SC-006)
- [ ] T026 [US3] Wire frozen holdout references into `scripts/evaluate_walk_forward.py` (FR-015, SC-006)
- [ ] T027 [US3] Version the accepted evaluation policy in `docs/speckit-recovery/08-implementation-validation/promotion-policy-template.json` (FR-016, SC-006)
- [ ] T028 [P] [US3] Enforce named promotion gaps with `scripts/check_promotion_evidence.py` (FR-015, FR-016)
- [ ] T029 [US3] Produce evaluation evidence under `docs/speckit-recovery/08-implementation-validation/` with a dated acceptance-policy reference (SC-006)

**Checkpoint**: Promotion-grade evaluation inputs are present or explicitly blocked with named gaps.

---

## Phase 6: User Story 4 - Reproduce runs and block regressions (Priority: P2)

**Goal**: Clean environments record matching dependency identity and verification gates block regressions.

**Independent Test**: Prepare two clean environments from the same approved dependency description, compare recorded dependency identity, and run the blocking suite with injected regressions.

- [ ] T030 [US4] Ratify the lock strategy and record DEC-008 in `docs/speckit-recovery/06-execution-prep/decision-unknown-tracker.md` (FR-017)
- [ ] T031 [US4] Enforce approved locked installs in `.github/workflows/ci.yml` and `Dockerfile` (FR-017)
- [ ] T032 [P] [US4] Extend dependency identity capture in `src/crispdm/run_manifest.py` with ratified lock version and platform identity (FR-018)
- [ ] T033 [US4] Add blocking gates for leakage, determinism, artifact contracts, and advertised dry-run commands in `.github/workflows/ci.yml` (FR-019, SC-008)
- [ ] T034 [P] [US4] Verify draft reproducibility gap reporting with `scripts/check_reproducibility_enforcement.py` (FR-017, FR-019, SC-007, SC-008)
- [ ] T035 [US4] Run clean-environment parity validation from `specs/001-p0-recovery/quickstart.md` (SC-007)

**Checkpoint**: Runtime identity is recorded and regression gates fail closed.

---

## Phase 7: User Story 5 - Make reports as-of and provenance clear (Priority: P3)

**Goal**: Reports display fixed resolved-as-of, generation time, evidence reference, and limitations.

**Independent Test**: Generate a report, change source data, reopen the report, and verify displayed provenance remains tied to the generating run.

- [ ] T036 [P] [US5] Verify report provenance labels in `app/views/dashboard.py` (FR-020, SC-009)
- [ ] T037 [US5] Implement historical as-of selection and explicit unavailability labeling in `app/views/dashboard.py` (FR-020, SC-009)
- [ ] T038 [P] [US5] Persist run-keyed reports with `scripts/persist_run_output.py` (FR-021)
- [ ] T039 [US5] Verify exported reports retain as-of and caveat labels in `app/views/dashboard.py` (FR-021, SC-009)
- [ ] T040 [US5] Complete UI verification evidence in `docs/speckit-recovery/06-execution-prep/unk004-ui-verification-checklist.md` (SC-009)

**Checkpoint**: Reports are provenance-labeled and historical-selection limits are visible.

---

## Phase 8: User Story 6 - Govern decisions and exceptions explicitly (Priority: P3)

**Goal**: Critical gaps, approvals, and residual risks are owned, time-bounded, and evidence-linked.

**Independent Test**: Review the governance register and verify every Critical gap has closure evidence or an owned, time-bounded exception with a compensating control.

- [ ] T041 [P] [US6] Complete the critical exception register in `docs/speckit-recovery/06-execution-prep/decision-unknown-tracker.md` (FR-022, SC-010)
- [ ] T042 [US6] Ratify M1 decisions in `docs/speckit-recovery/06-execution-prep/m1-decision-log-template.md` (FR-023, SC-010)
- [ ] T043 [US6] Block promotion claims when required evidence is missing in `scripts/check_promotion_evidence.py` (FR-024, SC-011)
- [ ] T044 [P] [US6] Verify preserved security and least-privilege controls in `tests/test_api.py` and `tests/test_ops_catalog.py` (FR-025)
- [ ] T045 [US6] Update requirement-to-evidence traceability in `docs/speckit-recovery/08-implementation-validation/rtm-update-draft.md` (SC-012)

**Checkpoint**: Governance gates are explicit and no critical gap is implicit.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Refresh evidence and confirm the full feature bundle remains non-promotion.

- [ ] T046 [P] Refresh the hash-locked bundle in `docs/speckit-recovery/08-implementation-validation/evidence-closeout-index.json` (SC-012)
- [ ] T047 [P] Update the status snapshot in `docs/speckit-recovery/08-implementation-validation/STATUS-2026-11-16.md` (SC-012)
- [ ] T048 Run the full local suite from `specs/001-p0-recovery/quickstart.md` (SC-008, SC-012)
- [ ] T049 Re-run the closeout gate with `scripts/check_evidence_closeout.py` (FR-024, SC-012)
- [ ] T050 Record final acceptance evidence in `docs/speckit-recovery/08-implementation-validation/execution-log.md` (SC-012)

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup; blocks all user stories.
- **User Stories (Phases 3-8)**: Depend on Foundational; validate independently in priority order.
- **Polish (Phase 9)**: Depends on all desired user-story checkpoints.

### User story dependencies

- **US1 (P1)**: No dependency on other stories; MVP.
- **US2 (P1)**: Can start after Foundational; integrates with US1 only for run context.
- **US3 (P2)**: Depends on US2 evidence contracts for evaluation artifacts.
- **US4 (P2)**: Depends on US2 manifests for dependency identity capture.
- **US5 (P3)**: Depends on US2 output storage for run-keyed reports.
- **US6 (P3)**: Cross-cutting governance; final approval tasks depend on evidence from all stories.

### Within each user story

1. Verify or define contracts and data rules.
2. Implement or wire only approved behavior.
3. Produce or refresh evidence.
4. Stop at the story checkpoint before integration with later stories.

### Parallel opportunities

- T002/T003 can run in parallel.
- T005/T006/T007 can run in parallel after T004.
- US1 verification tasks T009/T010/T012/T015 can run in parallel.
- US2 tasks T016/T017/T020 can run in parallel.
- US3 tasks T023/T028 can run in parallel.
- US4 tasks T032/T034 can run in parallel.
- US5 tasks T036/T038 can run in parallel.
- US6 tasks T041/T044 can run in parallel.
- T046/T047 can run in parallel.

---

## Parallel Example: User Story 1

```bash
Task: "Verify explicit as_of handling in src/crispdm/pit.py and src/crispdm/feature_window.py"
Task: "Verify membership interval structures in V0107"
Task: "Verify timing-column contract in V0108"
Task: "Run read-only backfill checks with scripts/check_candidate_backfill_readiness.py"
```

---

## Implementation Strategy

### MVP first

1. Complete Setup and Foundational phases.
2. Complete US1 and its checkpoint.
3. Stop and validate PIT inputs and delta evidence.
4. Do not promote candidate migrations or switch consumers without approval.

### Incremental delivery

1. US1 establishes trustworthy historical inputs.
2. US2 preserves defensible run evidence.
3. US3 adds economics and matched comparison.
4. US4 adds reproducibility and blocking gates.
5. US5 makes reports as-of and provenance clear.
6. US6 closes governance and exception registers.

### Parallel team strategy

- One owner per user story after Foundational completion.
- Governance owner handles US6 in parallel but does not close gates without evidence.
- Avoid assigning two workers to the same file path in the same phase.

## Notes

- No implementation work has been performed by task generation.
- Tasks are validation- and closure-oriented because the P0 scaffolding is already committed.
- Any task that would change behavior or promote a candidate remains approval-gated.
