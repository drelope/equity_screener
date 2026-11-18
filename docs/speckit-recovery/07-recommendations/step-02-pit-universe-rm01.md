# Step 2 — PIT Universe and Survivorship (RM-01) Design (Prepared)

| Field | Value |
|---|---|
| Recommendation | Build PIT membership history and filter universe/scoring/features/backtests by `as_of` |
| Status | **Design prepared; blocked on approvals/data/implementation** |
| Traceability | `RM-01`, `FR-UNI-01`, `FR-UNI-03`, `FR-FEAT-03`, `FR-UNI-02` (guard), `NFR-PIT-02`, `NFR-PIT-04`, `RK-01`, `EX-001/04`, `UNK-003`, `TSK-016/017` |

## 1. Current evidence/gaps
- `reference.securities`: 1,708 inactive, `delisted_date` unpopulated (0) (`FR-UNI-03` Missing).
- PIT/survivor proxy evidence: 1,332 score rows / 29 currently-inactive securities; 1,507,383 feature rows for inactive securities; true survivor-vs-PIT delta unresolved (`UNK-003`).
- Recomputes and historical universes risk current-state bias (`FR-UNI-01` Missing, `NFR-PIT-02` Partial).

## 2. Recommended target design
### 2.1 Data model
- **Preferred:** append-only/PIT membership source (e.g. `reference.security_status_history` or `reference.universe_membership_pit`) with `security_id`, `status` (active/inactive/delisted/listed/unknown), `effective_from`, `effective_to`/open-ended, `source`, `source_as_of/retrieved_at`, `evidence_ref`.
- Populate and maintain `reference.securities.delisted_date` as a derived/current convenience where reliable, but do **not** rely on a single current field for historical as-of logic.
- Preserve provenance for listing/delist/status corrections (append-only correction events, not silent overwrite).

### 2.2 Eligibility contract
- `eligible_as_of(as_of)` returns securities where membership/listing status is valid at `as_of` per PIT source.
- Scoring, feature generation, ranking, portfolio construction, and backtests must consume `eligible_as_of(as_of)` (not current active-only set) for historical/replay runs.
- Exclusions (illiquidity, sanctions/blocked where applicable, missing data) must be evaluated as-of and recorded in manifests.

### 2.3 Interfaces/manifests
- Add `universe_as_of`, `universe_source_version/hash`, and eligibility filter parameters to run manifests.
- Record included/excluded counts and reasons per run for audit (`FR-FEAT-03` linkage).

## 3. Verification plan
- **AC:** Historical run at `as_of=T` produces identical eligible universe given same PIT inputs/manifest.
- **UNK-003:** Compare survivor-only vs PIT-aware universe/ranking/performance on agreed periods; record delta/materiality.
- **Regression:** ensure current active-only operational view remains available where intentionally specified, but labeled distinct from PIT research/backtest view.

## 4. Dependencies / blockers
- Approvals: `EX-001/04`, M1 gate.
- Data sourcing for historical listing/delist/status (may require external/provider or curated history).
- Implementation and controlled recompute required for verification.
