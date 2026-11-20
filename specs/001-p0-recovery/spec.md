# Feature Specification: P0 Recovery Foundations

**Feature Branch**: `feature/speckit-recovery`

**Created**: 2026-11-16

**Status**: Approved at review-spec/review-plan; local implementation validation complete; M1/CI evidence pending; merge and release blocked

**Input**: Recover the P0 foundations of the equity/dividend research platform so historical results are point-in-time correct, decision evidence is immutable and run-addressable, evaluation inputs are decision-grade, runtime is reproducible, and blocking verification gates prevent silent regressions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Trust historical research inputs (Priority: P1)

A quantitative researcher needs universes, features, labels, and dividend facts to reflect only information that was legitimately available at the requested historical date. Today, current-state membership, unresolved filing times, and adjustment uncertainty can silently bias replay results.

**Why this priority**: This is the foundation for every historical claim. Without it, later evidence and performance artifacts cannot be trusted even if they are perfectly preserved.

**Independent Test**: Replay the same historical date twice, including at least one security whose membership or filing availability changes after that date. The researcher receives identical eligible inputs, and no input reflects information first learned after the requested date.

**Acceptance Scenarios**:

1. **Given** a historical date and a security whose status changed after that date, **When** the researcher requests the eligible universe, **Then** the result reflects only eligibility known as of that date.
2. **Given** a fundamental or dividend fact whose availability time is unknown, **When** the fact is considered for a replay, **Then** it is excluded or explicitly labeled as an approved conservative proxy rather than treated as known at its event date.
3. **Given** two replays of the same date with unchanged approved inputs, **When** the researcher compares results, **Then** the historical input sets are identical.

---

### User Story 2 - Preserve defensible decision evidence (Priority: P1)

A model owner needs every material score, label, checkpoint, backtest, and report output to be immutable and addressable by the run that produced it, with a manifest linking code identity, input identity, policy identity, environment identity, and outputs.

**Why this priority**: Promotion and audit decisions depend on evidence that cannot be silently overwritten or detached from its producing conditions.

**Independent Test**: Produce a run, then attempt to replace its evidence. The original evidence remains unchanged, a conflicting payload is rejected, and an identical rerun is recognized as idempotent rather than a new edition.

**Acceptance Scenarios**:

1. **Given** a completed material run, **When** the owner requests that run later, **Then** the exact manifest and output references from that run are retrievable.
2. **Given** an existing run identifier, **When** a different payload is submitted under the same identifier, **Then** the platform refuses the change instead of overwriting the original.
3. **Given** identical inputs and identity metadata, **When** the same run is submitted again, **Then** the platform reports a no-op rather than creating conflicting evidence.

---

### User Story 3 - Evaluate with explicit economics and matched comparisons (Priority: P2)

A backtest reviewer needs formation-correct inputs, documented trading-cost assumptions, and an exposure-matched comparison before any performance result is treated as decision-grade.

**Why this priority**: Gross or unmatched results can materially overstate a strategy and cannot support promotion decisions.

**Independent Test**: Review a completed evaluation and verify that formation timing, costs, net results, cash treatment, and the matched comparison are all present and versioned.

**Acceptance Scenarios**:

1. **Given** an evaluation result, **When** the reviewer opens its evidence bundle, **Then** formation rules and all cost assumptions are present and versioned.
2. **Given** gross results are reported, **When** the reviewer checks net results, **Then** net results reflect the recorded cost model.
3. **Given** a strategy result is presented for review, **When** the reviewer requests its comparison, **Then** an exposure-matched benchmark with aligned universe, holding, and cash treatment is available.

---

### User Story 4 - Reproduce runs and block regressions (Priority: P2)

A platform engineer needs consistent runtime identity and automated gates that fail when point-in-time, determinism, artifact, or advertised-command contracts regress.

**Why this priority**: Fixes that pass locally can otherwise regress silently across environments and releases.

**Independent Test**: Prepare two clean environments from the same approved dependency description and run the same verification suite. Both environments resolve the same dependency identity and both produce the same gate outcome.

**Acceptance Scenarios**:

1. **Given** two clean environments prepared from the same approved dependency description, **When** dependency identity is recorded, **Then** the recorded identities match.
2. **Given** a change that introduces a future-data leak, **When** verification runs, **Then** the blocking gate fails and identifies the affected contract.
3. **Given** an advertised command with a dry-run contract, **When** the command is invoked with minimal valid inputs, **Then** it completes without mutation or reports a documented, non-mutating failure.

---

### User Story 5 - Make reports as-of and provenance clear (Priority: P3)

An analyst needs reports to display the resolved as-of date, generation time, and evidence reference so a report opened later cannot be mistaken for current-state analysis.

**Why this priority**: Provenance labels prevent historical analysis from being consumed as present-day advice.

**Independent Test**: Generate a report for a fixed date, wait until source data changes, and reopen the report. The displayed resolved as-of and provenance remain tied to the generating run.

**Acceptance Scenarios**:

1. **Given** a report generated for a fixed analysis date, **When** the analyst views it later, **Then** the resolved as-of and generated time shown are those of the original run.
2. **Given** a report whose historical source selection is unavailable, **When** the analyst views provenance, **Then** the limitation is explicitly displayed rather than hidden.
3. **Given** an exported report, **When** it is shared outside the application, **Then** its as-of and caveat labels remain attached.

---

### User Story 6 - Govern decisions and exceptions explicitly (Priority: P3)

A governance owner needs approvals, exceptions, unknowns, and residual risks recorded with owners and evidence so no Critical gap remains implicit.

**Why this priority**: Several P0 conditions depend on human or external decisions that code alone cannot resolve.

**Independent Test**: Review the governance register and verify that every Critical gap has either closure evidence or an owned, time-bounded exception with a compensating control.

**Acceptance Scenarios**:

1. **Given** a Critical requirement without closure evidence, **When** the owner reviews the register, **Then** an explicit exception with owner, rationale, compensating control, and expiry is present.
2. **Given** a decision required for evaluation, provenance, or runtime reproducibility, **When** the owner reviews evidence, **Then** the decision reference and approval date are recorded.
3. **Given** an unresolved external validation, **When** a promotion claim is considered, **Then** the claim is blocked until evidence or an approved exception exists.

---

### Edge Cases

- An approval or external evidence item remains pending at the time a technical artifact is ready.
- A security is delisted or reclassified after the requested as-of date.
- A fundamental or dividend fact has an event date but no defensible availability time.
- A prior output exists under a run identifier and a new payload conflicts with it.
- A superuser or privileged process can bypass an ordinary immutability control.
- Two clean environments resolve different dependency identities from the same stated intent.
- A report is opened after source data has changed.
- A Critical exception expires without closure evidence.

## Requirements *(mandatory)*

### Covered replay paths and proxy gate

For this feature, covered historical replay paths are: universe construction; feature building; forward-return labeling; score/rank generation; backtesting; and walk-forward evaluation. Report rendering is covered only for its as-of and provenance display contract.

A conservative availability proxy is permitted only when its data basis, approval owner, decision reference, and expiry are recorded before the affected replay is used as acceptance evidence. An unrecorded proxy is not an approved proxy.

### Functional Requirements

- **FR-001**: The platform MUST require an explicit as-of date for every covered historical replay path.
- **FR-002**: The platform MUST determine universe eligibility from information available as of the requested date, not from current state.
- **FR-003**: The platform MUST preserve historical delisting and reclassification information without inferring delisting solely from a current inactive flag.
- **FR-004**: The platform MUST distinguish an event date from the date the fact became known or available.
- **FR-005**: The platform MUST exclude or explicitly label facts whose availability time is unknown when they are used in a replay.
- **FR-006**: The platform MUST prevent ordinary overwrite of material decision evidence, including scores, labels, checkpoints, backtests, and report outputs.
- **FR-007**: Every material run MUST have an identifier that remains stable and unique for that run.
- **FR-008**: Every material run MUST have a manifest linking code identity, input identity, policy identity, environment identity, and output references.
- **FR-009**: Identical resubmission of a run MUST be recognized as idempotent and MUST NOT create a conflicting evidence edition.
- **FR-010**: Conflicting resubmission under an existing run identifier MUST be rejected.
- **FR-011**: Report and score outputs MUST be retrievable by run identifier.
- **FR-012**: Evaluation evidence MUST record formation rules and all trading-cost assumptions.
- **FR-013**: Evaluation evidence MUST report gross and net results using the recorded cost assumptions.
- **FR-014**: Evaluation evidence MUST include an exposure-matched comparison with aligned universe, holding horizon, and cash treatment.
- **FR-015**: A frozen evaluation holdout MUST be referenced before any promotion-grade claim is accepted.
- **FR-016**: An accepted policy version MUST be referenced by material evaluation and reporting runs.
- **FR-017**: Clean environments prepared from the same approved dependency description MUST record identical dependency identity.
- **FR-018**: Run manifests MUST record the dependency identity used for the run.
- **FR-019**: Blocking verification gates MUST fail on future-data leakage, non-deterministic replay, broken evidence contracts, and broken advertised dry-run commands.
- **FR-020**: Reports MUST display resolved as-of date, generated time, evidence reference, and any historical-selection limitation.
- **FR-021**: Exported reports MUST retain their as-of and caveat labels.
- **FR-022**: Every critical unresolved requirement MUST have either closure evidence or an explicit, owned, time-bounded exception with a compensating control.
- **FR-023**: Every required human or external decision MUST have a recorded owner, due date, and evidence reference.
- **FR-024**: Promotion-grade claims MUST be blocked while required evidence or approvals are missing.
- **FR-025**: Existing security, least-privilege, audit, and quarantine controls MUST be preserved.

### Key Entities *(include if feature involves data)*

- **As-of eligibility state**: The known membership and delisting status of a security at a historical date.
- **Information availability event**: The evidence that a fact became known or available, distinct from the event date itself.
- **Run manifest**: The immutable identity record for a material run, linking code, inputs, policy, environment, and outputs.
- **Run output reference**: The stable address of an output produced by a specific run.
- **Evaluation policy**: The versioned criteria, cost assumptions, and comparison definition used for an evaluation.
- **Holdout reference**: The controlled, frozen dataset used to support promotion-grade evaluation.
- **Dependency identity**: The recorded identity of the approved runtime dependency set.
- **Governance exception**: An owned, time-bounded allowance for a critical gap with compensating control and expiry.
- **As-of report**: A report whose displayed analysis date and provenance remain fixed to its generating run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of covered replay paths in the verification suite require an explicit as-of date.
- **SC-002**: 0 covered replay inputs in the verification suite reflect information first available after the requested as-of date.
- **SC-003**: 100% of material runs in the verification suite have complete manifests with code, input, policy, environment, and output linkage.
- **SC-004**: 0 ordinary overwrite operations succeed against material decision evidence in the verification suite.
- **SC-005**: 100% of conflicting run resubmissions are rejected, and 100% of identical reruns are reported as no-ops.
- **SC-006**: 100% of promotion-grade evaluation bundles in the verification suite include formation rules, cost assumptions, net results, and an exposure-matched comparison.
- **SC-007**: Two clean environments prepared from the same approved dependency description record matching dependency identity in 100% of parity checks.
- **SC-008**: The blocking verification suite fails on 100% of injected future-data, determinism, evidence-contract, and advertised-command regression cases.
- **SC-009**: 100% of verified reports display resolved as-of date, generated time, evidence reference, and any historical-selection limitation.
- **SC-010**: 100% of unresolved Critical requirements have either closure evidence or an owned, time-bounded exception with a named compensating control.
- **SC-011**: 0 promotion-grade claims are accepted while a required approval or evidence item is missing.
- **SC-012**: 100% of P0 acceptance checks linked to this feature have a recorded verification artifact or an explicitly approved exception.

## Assumptions

- The existing platform remains modular and preserves its current security, least-privilege, audit, quarantine, and rule-based production scoring controls.
- P0 scope covers foundations required for trustworthy evidence and verification; full adjustment correctness, provider legal determinations, production cutover, and new alpha research remain outside this feature.
- Human approvals and external evidence for M1, EX, DEC, and UNK items are prerequisites for closure even when technical artifacts are ready.
- Existing recovered drafts under `docs/speckit-recovery/` are inputs to this specification, not approved decisions.
- Technical work already committed on this branch is evidence to be traced during planning; it does not bypass spec review, plan review, or acceptance gates.
- Reasonable defaults apply where no business choice changes scope: user-facing labels are clear, failed gates are diagnostic, and dry-run operations do not mutate state.
