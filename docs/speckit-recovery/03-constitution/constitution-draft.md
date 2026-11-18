# Constitution Draft

| Field | Value |
|---|---|
| Stage | 3 — Constitution reconstruction |
| Status | Draft for `/speckit-constitution` |
| Evidence date | 2026-11-15 |
| Repository revision | `d748cea` plus uncommitted environment and docs changes |
| Inputs | Stage 0 discovery, Stage 1A–1D audits, Stage 2 requirements and principles evidence |
| Rule format | `ID | Rule | Level | Status | Verification | Requirement` |
| Status legend | **Descriptive** = the code or CI already follows the rule; **Aspirational** = the rule should be adopted and is not yet met |

This is a recovered constitution, not a stakeholder-approved one. Descriptive rules are written in the present tense of the implementation and are included so the existing controls are not lost. Aspirational rules are the minimum changes needed to make the recovered system consistent with its own evidence model. Rules are phrased as MUST or SHOULD and name a verification method.

The draft contains 95 rules: 30 Descriptive and 65 Aspirational.

## 1. Guiding Principles

### Descriptive rules (already practised)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `GP-02` | Production scoring MUST use the documented rule score; the ML model MUST remain a gated research path until explicitly promoted. | MUST | `scoring.WEIGHTS`; `model_version=rule_scoring_v1`; ML gate is separate. | FR-SIG-01, FR-EVAL-02 |
| `GP-04` | Required stages and blocking checks MUST fail closed. | MUST | `walk_forward_folds(requires_all_folds)`; pipeline exit codes; nightly verification. | FR-EVAL-01, NFR-REL-02 |
| `GP-07` | Provider provenance and quarantined values MUST be preserved with the source row. | MUST | Provider/feed columns; append-only `audit.quarantined_values`. | FR-DIV-01, FR-DIV-05 |
| `GP-08` | Operational and research surfaces MUST use least privilege. | MUST | API auth; ops catalog; read-only explorer; non-root containers. | NFR-SEC-01..03 |

### Aspirational rules (to adopt)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `GP-01` | Point-in-time integrity MUST take precedence over filling a missing value with current data. | MUST | Add a PIT assertion suite and reject current-state fallbacks on historical paths. | NFR-PIT-01..05 |
| `GP-03` | Every promotion decision MUST be reproducible from stored code, data, policy and environment identity. | MUST | Add run manifests and a frozen holdout. | FR-EVAL-04, NFR-REPRO-03 |
| `GP-05` | Decision evidence (scores, labels, checkpoints, artifacts) MUST be append-only and addressable by run. | MUST | Replace upserts and canonical overwrite with run-keyed stores. | FR-SIG-03, FR-LABEL-03, FR-EVAL-04, FR-BT-05 |
| `GP-06` | Documented architecture MUST distinguish implemented behavior from target behavior. | MUST | Correct README and technical-spec claims; label aspirational sections. | NFR-REPRO-02 |

## 2. Engineering Standards

### Descriptive rules (already practised)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `ES-01` | Python code MUST pass `ruff check` and `ruff format --check` in CI. | MUST | CI lint job and `ruff.toml`. | NFR-TEST-04 |
| `ES-02` | Schema changes MUST be forward-only numbered migrations recorded in `schema_migrations`. | MUST | `scripts/migrate.py`; migration ledger. | NFR-REPRO-02, NFR-REL-02 |
| `ES-05` | Configuration MUST come from `Settings` or environment variables; secrets MUST NOT be committed. | MUST | `Settings`; `.gitignore`; gitleaks CI job. | NFR-SEC-03 |
| `ES-08` | The ops worker MUST execute only catalog-listed modules with coerced parameters and no shell strings. | MUST | `ops.catalog`; `TaskDef`; `run_argv`. | NFR-SEC-02 |
| `ES-10` | Changing a feature or model definition MUST bump its version and hash. | MUST | `FEATURE_VERSION`; `compute_feature_set_hash`; V0095. | FR-FEAT-02, FR-SIG-04 |

### Aspirational rules (to adopt)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `ES-03` | Every replay-visible function MUST accept an explicit `as_of` and MUST NOT default to the wall clock in a pipeline path. | MUST | Remove `date.today()`/`Timestamp.now()` defaults from historical paths. | NFR-DET-02 |
| `ES-04` | Ordering and tie-breaks MUST be total and documented for every query that selects one row. | MUST | Add `filed`, accession and provider tie-breaks. | NFR-DET-01, NFR-DET-04 |
| `ES-06` | There MUST be one canonical schema; alternate schemas MUST be archived or documented as non-runtime. | MUST | Archive `sql/silver_schema.sql` or mark it non-canonical. | NFR-REPRO-02 |
| `ES-07` | Every advertised CLI MUST have a smoke test that calls `main()` with minimal valid input. | MUST | Add CLI smoke tests; fix `scripts/dry_run_walk_forward.py`. | FR-EVAL-05, NFR-TEST-04 |
| `ES-09` | Runtime and development dependencies MUST be locked with exact versions and hashes; CI and container builds MUST install from that lock. | MUST | Restore pins and add a hashed lock. | NFR-REPRO-01, NFR-REPRO-02 |

## 3. Data Governance Rules

### Descriptive rules (already practised)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `DG-01` | Every dividend row MUST record provider, underlying feed, retrieval time and amount basis. | MUST | `provider`, `feed`, `amount_feed`, `retrieved_at`, `adjusted_amount`. | FR-DIV-01 |
| `DG-03` | Macro revisions MUST be append-only and keyed by observation and vintage date. | MUST | `raw.macro_series_vintages`; `as_of_series`. | FR-MACRO-01, NFR-REPRO-04 |
| `DG-04` | Quarantined values MUST be append-only and resolved by timestamp, not deleted. | MUST | `audit.quarantined_values`; `resolved_at`. | FR-DIV-05, NFR-AUD-01 |
| `DG-10` | Source freshness, schema drift and data quality MUST be checked and recorded on every nightly run. | MUST | `audit.data_quality`; `audit.source_freshness`; `check_schema_drift`; nightly verification. | NFR-GOV-02 |

### Aspirational rules (to adopt)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `DG-02` | A provider event MUST NOT lose a feed's evidence because the natural key omits the feed. | MUST | Include feed in the key or keep both amounts in append-only evidence. | FR-DIV-01 |
| `DG-05` | Quarantine rules MUST be maintained as runtime data or configuration, not only by a one-time migration. | MUST | Add a rules table or config and write new absurd rows from code. | FR-DIV-05 |
| `DG-06` | An upsert MUST preserve non-NULL stored dividend dates when the incoming payload omits them. | MUST | Use `COALESCE` in `DIVIDEND_UPSERT`. | FR-DIV-04 |
| `DG-07` | SEC-derived dividends MUST store the filing date and become visible only on or after it. | MUST | Persist `filed` and gate features/labels on it. | FR-DIV-03, NFR-PIT-04 |
| `DG-08` | Security membership MUST have valid-from and valid-to bounds and MUST be queryable as of a date. | MUST | Build a membership interval table from dividend, listing and delisting evidence. | FR-UNI-01, NFR-PIT-02 |
| `DG-09` | A delisted security MUST be truncated at its last trade and MUST receive a documented delisting return where available. | MUST | Populate `delisted_date`; stop forward-fill; add delisting return. | FR-UNI-03 |
| `DG-11` | Every provider MUST have documented terms covering internal use, caching, redistribution and derived data. | MUST | Create a provider-terms inventory and a distribution decision. | NFR-GOV-03 |
| `DG-12` | Identity release or merge MUST retain an in-warehouse archive or validity interval for affected history. | MUST | Use closed intervals and tombstones instead of deleting rows. | FR-CA-02, FR-ID-01, NFR-AUD-04 |
| `DG-13` | Raw provider payloads used for historical decisions MUST be retained as versioned snapshots. | MUST | Store SEC and provider payloads by retrieval/vintage. | NFR-REPRO-04, NFR-AUD-02 |

## 4. Testing Requirements

### Descriptive rules (already practised)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `TR-01` | The non-integration suite MUST pass in CI on every change. | MUST | CI runs `pytest -q`; 1,602 non-integration tests are collectable. | NFR-TEST-02 |
| `TR-02` | The integration suite MUST run against a migrated Postgres instance in CI. | MUST | CI provisions Postgres 17.11; `init_db` and `migrate` precede pytest. | NFR-TEST-02 |
| `TR-03` | Every change MUST pass the lint job before merge. | MUST | `ruff check` and `ruff format --check`. | NFR-TEST-04 |

### Aspirational rules (to adopt)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `TR-04` | CI MUST publish coverage and fail below a project-defined threshold. | MUST | Add `pytest-cov`, a threshold and a coverage artifact. | NFR-TEST-01 |
| `TR-05` | Every advertised CLI MUST have a smoke test that invokes its real entry point. | MUST | Add 96 missing CLI smoke tests. | NFR-TEST-04, FR-EVAL-05 |
| `TR-06` | Point-in-time tests MUST assert that future prints and later revisions cannot change an earlier result. | MUST | Add two-date replay and future-row isolation tests. | NFR-TEST-03, NFR-PIT-01..05 |
| `TR-07` | Determinism tests MUST replay a fixed input twice with a frozen clock and compare the output. | MUST | Add frozen-clock replay tests for features, scores and backtests. | NFR-DET-02, NFR-TEST-03 |
| `TR-08` | Split and dividend boundary cases MUST be tested, including tolerance, index zero and same-day events. | MUST | Add boundary fixtures to `tests/test_portfolio.py`. | FR-ADJ-02/03, NFR-TEST-03 |
| `TR-09` | Critical SQL constants MUST be executed against the migrated schema, not only asserted as substrings. | MUST | Add SQL execution tests for returns, features and universe queries. | NFR-TEST-02 |
| `TR-10` | Backtest and evaluation artifacts MUST have contract tests for required manifest fields. | MUST | Add artifact schema tests and reject stale rule sets. | FR-BT-05, NFR-REPRO-03 |
| `TR-11` | Critical behavior MUST NOT rely only on source-text assertions. | SHOULD | Replace substring guards with executed behavior tests where risk is High. | NFR-TEST-02 |

## 5. Audit Requirements

### Descriptive rules (already practised)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `AU-06` | Predictions MUST carry run id, model, feature and data versions. | MUST | `model.predictions` schema and writer. | FR-SIG-04 |
| `AU-07` | Feature rows MUST carry the feature-set version and hash. | MUST | `feature_version`; `feature_set_hash`; V0096. | FR-FEAT-02 |
| `AU-10` | Quarantine, macro vintage and ticker-profile load history MUST remain append-only. | MUST | Those tables and their writers preserve history. | NFR-AUD-01, NFR-REPRO-04 |

### Aspirational rules (to adopt)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `AU-01` | Every ETL, scoring, evaluation and backtest run MUST have an immutable run id. | MUST | Add run ids to scores, labels, nightly rows and artifacts. | NFR-REPRO-03 |
| `AU-02` | Every published score MUST be append-only and carry run id, scored-at, feature hash/version and data version. | MUST | Replace the `(security_id, as_of_date)` upsert with run-keyed history. | FR-SIG-03 |
| `AU-03` | Labels MUST be append-only by label run, cutoff and version. | MUST | Remove the destructive `--rebuild` clear; store label runs. | FR-LABEL-03 |
| `AU-04` | Every backtest artifact MUST carry a run manifest, code SHA and dirty flag, data snapshot, rule-set version, costs, benchmark and config hash. | MUST | Write a manifest beside each metrics file. | FR-BT-05 |
| `AU-05` | Lineage MUST be append-only and cover every model input, not only five decision fields. | MUST | Stop delete-and-reinsert; add price, dividend, feature and score lineage. | NFR-AUD-01 |
| `AU-08` | Checkpoints MUST record acceptance policy, code, data and environment identity. | MUST | Extend `make_checkpoint` and `audit.model_runs`. | FR-EVAL-04 |
| `AU-09` | Every report and worksheet MUST store and display its resolved as-of date and fetch time. | MUST | Add a stored as-of and parameterize report queries. | FR-REP-02, FR-AI-02 |
| `AU-11` | The canonical checkpoint MUST be addressed by run id and MUST NOT be overwritten by an ordinary run. | MUST | Write `checkpoints/<run_id>.json` and a latest pointer. | FR-EVAL-04, NFR-REPRO-04 |

## 6. Reproducibility Requirements

### Descriptive rules (already practised)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `RP-03` | The runtime Python version MUST be pinned in the container and CI. | MUST | `python:3.12-slim`; CI setup-python 3.12. | NFR-REPRO-02 |

### Aspirational rules (to adopt)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `RP-01` | A clean checkout MUST install an exact, hashed dependency set. | MUST | Add a lock file and restore exact pins. | NFR-REPRO-01 |
| `RP-02` | CI, Docker and local development MUST install the same locked dependency set. | MUST | Use the same lock in all three paths. | NFR-REPRO-02 |
| `RP-04` | A clean-environment reproduction test MUST run the pipeline smoke path and compare outputs. | MUST | Add a container-based end-to-end smoke test. | NFR-REPRO-02 |
| `RP-05` | Every run manifest MUST record the code SHA and a dirty flag. | MUST | Add git state to ETL, score, evaluation and backtest runs. | NFR-REPRO-03 |
| `RP-06` | Every run manifest MUST record an environment or dependency identity. | MUST | Hash the lock or image digest into the manifest. | NFR-REPRO-03 |
| `RP-07` | Every run manifest MUST record an input snapshot or content hash. | MUST | Hash raw inputs and feature rows read by the run. | NFR-REPRO-03 |
| `RP-08` | Result artifacts MUST be immutable and addressable by run id. | MUST | Stop timestamp-only naming; add run ids and manifests. | FR-BT-05, NFR-REPRO-04 |
| `RP-09` | Raw provider payloads used in a historical decision MUST be retained by retrieval or vintage. | MUST | Store SEC and provider payloads versioned by retrieval. | NFR-REPRO-04 |
| `RP-10` | A canonical checkpoint MUST be addressable after later runs. | MUST | Use run-keyed checkpoint files and an explicit latest pointer. | FR-EVAL-04 |

## 7. Change Management

### Descriptive rules (already practised)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `CM-03` | Schema changes MUST use forward-only migrations recorded in the ledger. | MUST | `scripts/migrate.py`; `schema_migrations`; max applied 106. | NFR-REPRO-02, NFR-REL-02 |
| `CM-07` | A change to feature or model definitions MUST bump the feature or model version. | MUST | `FEATURE_VERSION`; `MODEL_VERSION`; V0095. | FR-FEAT-02, FR-SIG-04 |

### Aspirational rules (to adopt)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `CM-01` | Acceptance policy, cleaning rules, thresholds and holdout definitions MUST be versioned before evaluation. | MUST | Freeze a policy version and record it on every run. | FR-EVAL-03, NFR-GOV-01 |
| `CM-02` | A post-hoc policy or threshold change MUST invalidate earlier promotion evidence and require a fresh holdout. | MUST | Add contract drift invalidation and a holdout ledger. | FR-EVAL-03, NFR-GOV-01 |
| `CM-04` | A destructive migration or identity change MUST archive affected history in the warehouse or require explicit review. | MUST | Add tombstone/interval patterns and a review checklist. | NFR-AUD-04, FR-ID-01 |
| `CM-05` | A behavior change MUST update the affected requirement, RTM row and user documentation in the same change. | MUST | Add a documentation checklist to the change template. | NFR-AUD-01 |
| `CM-06` | README and technical documentation MUST label target architecture as aspirational. | MUST | Move dbt, Bayesian and multi-agent claims to a roadmap section. | NFR-REPRO-02 |
| `CM-08` | A change to a risk control MUST be reviewed, versioned and accompanied by a regression test. | MUST | Add a control-change checklist and tests. | FR-EVAL-02, NFR-GOV-01 |
| `CM-09` | A normal run MUST NOT overwrite the canonical promotion checkpoint. | MUST | Write to a run-specific path and update a pointer atomically. | FR-EVAL-04, NFR-REPRO-04 |

## 8. Quality Gates

### Descriptive rules (already practised)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `QG-01` | Lint and formatting MUST pass before merge. | MUST | CI lint job with ruff. | NFR-TEST-04 |
| `QG-02` | The full test suite MUST pass before merge. | MUST | CI test job; targeted run passed 302 tests. | NFR-TEST-02 |
| `QG-03` | A fresh database MUST initialize and migrate successfully before tests run. | MUST | CI `init_db` then `migrate`. | NFR-REPRO-02 |
| `QG-04` | Dependency audit and secret scanning MUST pass before merge. | MUST | pip-audit and gitleaks CI job. | NFR-SEC-03 |
| `QG-05` | Schema drift MUST be checked against the canonical schema. | MUST | `scripts/check_schema_drift.py`. | NFR-GOV-02 |
| `QG-06` | Nightly verification MUST check freshness, quality, model gate and schema drift. | MUST | `scripts/verify_nightly_run.py`; `post_nightly_check.py`. | NFR-GOV-02, NFR-REL-01 |

### Aspirational rules (to adopt)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `QG-07` | Coverage MUST be measured and MUST meet the project threshold. | MUST | Add `pytest-cov` and a threshold. | NFR-TEST-01 |
| `QG-08` | A frozen-clock determinism replay MUST pass before a release. | MUST | Add replay test and a release gate. | NFR-DET-02, NFR-TEST-03 |
| `QG-09` | The point-in-time suite MUST pass before a release. | MUST | Add PIT tests for universe, fundamentals, dividends, macro and reports. | NFR-PIT-01..05 |
| `QG-10` | Run manifest completeness MUST be checked before an evaluation or backtest is published. | MUST | Validate required manifest fields at write time. | NFR-REPRO-03, FR-BT-05 |
| `QG-11` | An artifact whose rule set or code does not match the running code MUST be rejected or clearly labelled. | MUST | Add a serve-time compatibility check. | FR-BT-05 |
| `QG-12` | Representative-volume performance MUST be measured against a documented budget. | SHOULD | Add a load test for features, scores and reports. | NFR-SCALE-02 |

## 9. Decision Criteria

### Descriptive rules (already practised)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `DC-01` | Production ranking MUST use the rule score until an ML model is explicitly promoted. | MUST | `rule_scoring_v1`; ML gate is separate. | FR-SIG-01, FR-EVAL-02 |
| `DC-08` | Remote LLM use MUST require explicit opt-in and MUST NOT write to the warehouse. | MUST | `allow_remote`; disabled by default; no auto-save. | FR-AI-01 |

### Aspirational rules (to adopt)

| ID | Rule | Level | Verification | Requirement |
|---|---|---|---|---|
| `DC-02` | An ML promotion MUST require all folds to pass, a frozen policy and an untouched holdout. | MUST | Reserve a holdout and re-run under a frozen policy. | FR-EVAL-02, FR-EVAL-03 |
| `DC-03` | A new factor MUST have PIT evidence, coverage evidence and a regression test before it is scored. | MUST | Add a factor admission checklist. | FR-FEAT-01, NFR-PIT-03 |
| `DC-04` | A new provider MUST have documented terms, provenance, freshness and quarantine rules before ingestion. | MUST | Add a provider onboarding gate. | NFR-GOV-03, FR-DIV-01 |
| `DC-05` | Decision evidence SHOULD prefer append-only, run-keyed storage over upserts. | SHOULD | Adopt run-keyed scores, labels and checkpoints. | FR-SIG-03, FR-LABEL-03, FR-EVAL-04 |
| `DC-06` | A stale or rule-set-mismatched backtest artifact MUST NOT be presented as current. | MUST | Add dashboard compatibility checks. | FR-BT-05 |
| `DC-07` | An ambiguous as-of date MUST be treated as a defect, not a default. | MUST | Reject missing as-of in historical paths. | NFR-PIT-01, NFR-DET-02 |
| `DC-09` | Identity release or merge MUST require an archive and review before deletion. | MUST | Add a DB archive and review checklist. | FR-CA-02, FR-ID-01, NFR-AUD-04 |
| `DC-10` | A strategy claim MUST include costs and an exposure-matched benchmark. | MUST | Add cost and benchmark fields before publishing performance. | FR-BT-03, FR-BT-04 |
| `DC-11` | A report MUST NOT present a historical analysis without its stored as-of date. | MUST | Store and display as-of on every report and worksheet. | FR-REP-02, FR-AI-02 |

## 10. Adoption Notes

- Adopt the Aspirational rules in the order of the Stage 4 risk register, not alphabetically. Point-in-time integrity and append-only decision evidence unlock most other controls.
- Do not mark an Aspirational rule Descriptive until a test, CI job or runtime check enforces it. A code comment or a design document is not verification.
- Keep the Descriptive rules in the constitution even after remediation; they are the controls that already work and are easy to regress.
- The four Critical-risk requirements from Stage 2 (`FR-UNI-01`, `FR-DIV-07`, `NFR-PIT-01`, `NFR-PIT-02`) should be the first constitution exceptions if the team cannot meet every MUST immediately.
- Re-run `/speckit-constitution` after Stage 4 so risk acceptance decisions and remediation sequencing are visible in the same document.

## 11. Limits

- This draft does not resolve policy questions: provider licensing, holdout ownership and the cost model remain open.
- Descriptive does not mean bug-free. It means the named control is present and verified at the snapshot.
- The constitution is scoped to the recovered repository, not to a future Azure or multi-agent deployment.
