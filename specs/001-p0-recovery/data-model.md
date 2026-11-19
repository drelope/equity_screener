# Data Model: P0 Recovery Foundations

## Scope

This model captures the entities named in the approved spec and maps them to existing or candidate structures. It is a design artifact, not a migration or approval record.

## Entities

### As-of eligibility state

- **Purpose**: Represent whether a security was eligible at a historical date.
- **Fields**: security identifier, as-of date, eligibility flag, reason, source run.
- **Candidate structures**: `reference.security_membership_history`, `reference.security_eligibility_asof`, `reference.securities.delisted_date`.
- **Rules**:
  - Membership intervals must not overlap for the same security.
  - Delisted dates must come from approved evidence, not inferred from current inactivity.
  - Eligibility cache rows are non-authoritative until UNK-003 comparison and M1 approval.
- **Relationships**: One security has many membership intervals and many as-of eligibility rows.

### Information availability event

- **Purpose**: Distinguish event occurrence from the time a fact became known or available.
- **Fields**: security, event date, declared/record/payment/ex known-at times, available-at time, evidence source, timing confidence.
- **Existing/candidate structures**: `raw.dividend_data` plus V0108 timing columns.
- **Rules**:
  - Available-at must not precede the corresponding event date unless a documented conservative proxy is approved.
  - Known-at times must not postdate retrieval.
  - Availability without evidence source is an anomaly.
- **Relationships**: One security has many dividend availability events.

### Run manifest

- **Purpose**: Immutable identity record for a material run.
- **Fields**: run ID, run type, creation time, resolved as-of, code SHA/dirty state, parameters, input refs, output refs, environment, status, manifest hash, manifest JSON.
- **Structures**: `src/crispdm/run_manifest.py`, `src/crispdm/manifest_store.py`, candidate `audit.run_manifests`.
- **Rules**:
  - Manifest hash is computed from canonical JSON.
  - Existing run ID with a different hash is a conflict.
  - Identical reruns are idempotent.
  - No update/delete path is allowed in the approved target model.
- **Relationships**: One run has one manifest and many output references.

### Run output reference

- **Purpose**: Stable address of an output produced by a run.
- **Fields**: run ID, output kind, entity type/id, storage reference, content hash, creation time, metadata.
- **Structures**: `src/crispdm/output_store.py`, candidate `audit.run_outputs`.
- **Rules**:
  - Storage path is `<run_id>/<output_kind>.json` in the run output store.
  - Run and output-kind components must be safe path components.
  - Differing payloads under the same pair raise conflict; they are not overwritten.
- **Relationships**: Many outputs belong to one run.

### Evaluation policy

- **Purpose**: Versioned criteria, cost assumptions, and comparison definition for promotion-grade evaluation.
- **Fields**: policy ID/version/status, acceptance criteria, cost model assumptions, benchmark definition, approval references.
- **Structures**: `promotion-policy-template.json`, `promotion-gate-contract-draft.md`, `scripts/check_promotion_evidence.py`.
- **Rules**:
  - Missing required fields are blocking gaps.
  - A draft policy cannot support a promotion-grade claim.
- **Relationships**: Many evaluation runs reference one accepted policy version.

### Holdout reference

- **Purpose**: Controlled, frozen dataset used for promotion-grade evaluation.
- **Fields**: ID, snapshot references, freeze date, owner, access policy, untouched evidence.
- **Structures**: `promotion-policy-template.json`.
- **Rules**: Missing freeze/ownership/untouched evidence blocks promotion-grade claims.
- **Relationships**: One holdout may support many evaluations under an approved policy.

### Dependency identity

- **Purpose**: Recorded identity of the approved runtime dependency set.
- **Fields**: lock artifact name, SHA-256, runtime/platform identity, install policy.
- **Structures**: `requirements.lock.txt`, `requirements-dev.lock.txt`, `run_manifest.py`, reproducibility checkers.
- **Rules**:
  - Draft lock artifacts are parseable but not ratified.
  - CI/Docker/local enforcement is reported as a gap until DEC-008.
- **Relationships**: Many run manifests may share one dependency identity.

### Governance exception

- **Purpose**: Explicit, time-bounded allowance for an unresolved critical gap.
- **Fields**: requirement, owner, rationale, compensating control, expiry, status, evidence.
- **Structures**: `m1-decision-log-template.md`, `decision-unknown-tracker.md`, `constitution-disposition-and-exceptions.md`.
- **Rules**:
  - No unbounded critical exception is acceptable.
  - Promotion claims are blocked while required evidence is missing.
- **Relationships**: Many exceptions may attach to one requirement or decision area.

### As-of report

- **Purpose**: Report whose displayed analysis date and provenance remain fixed to its generating run.
- **Fields**: resolved as-of, generated time, run reference, storage mode, historical-selection limitation, caveat labels.
- **Structures**: `app/views/dashboard.py`, `scripts/persist_run_output.py`.
- **Rules**:
  - Reports show resolved as-of and generated time.
  - Exported reports retain provenance and caveat labels.
  - Transient in-memory storage must be labeled as such.
- **Relationships**: One report is linked to one run manifest.

## State transitions

### Candidate migration

`draft -> numbered candidate -> approved -> applied in isolated rehearsal -> approved for cutover -> canonical migration`

Only the first two states exist today.

### Governance exception

`identified -> owned -> compensating control -> expiry/review -> closed or renewed`

Closure requires evidence or an approved renewal.

### Run evidence

`planned -> dry-run -> persisted -> read/verified -> retained`

Mutation of persisted evidence is not a supported transition; conflicts create a rejection, not an update.

## Cross-entity validation rules

- Every material run must link manifest, outputs, policy, dependency identity, and resolved as-of.
- A run without a complete manifest cannot support a promotion-grade claim.
- PIT eligibility and timing gaps must be visible on affected artifacts until closed.
- Governance exceptions do not convert draft evidence into verified evidence.
