# Requirements Coverage Statistics

| Field | Value |
|---|---|
| Stage | 2 — Requirements recovery |
| Register | `requirements.md`; generated from the same record set as `rtm.md` |
| Snapshot | 2026-11-15; repository revision `d748cea` |
| Total requirements | 84 |

## 1. Overall Status Distribution

| Status | Count | Percentage |
|---|---|---|
| **Implemented** | 18 | 21.4% |
| **Partial** | 53 | 63.1% |
| **Missing** | 12 | 14.3% |
| **Unknown** | 1 | 1.2% |
| **Total** | **84** | **100.0%** |

## 2. Functional versus Non-Functional

| Group | Total | Implemented | Partial | Missing | Unknown |
|---|---|---|---|---|---|
| Functional (FR-) | 53 | 13 | 31 | 9 | 0 |
| Non-functional (NFR-) | 31 | 5 | 22 | 3 | 1 |

## 3. Coverage by Requirement Family

| Family | Total | Implemented | Partial | Missing | Unknown | Implementation completeness |
|---|---|---|---|---|---|---|
| Price adjustment | 4 | 0 | 4 | 0 | 0 | 50.0% |
| Corporate actions | 2 | 1 | 1 | 0 | 0 | 75.0% |
| Dividend adjustment | 8 | 0 | 7 | 1 | 0 | 43.8% |
| Total return | 4 | 1 | 3 | 0 | 0 | 62.5% |
| Universe and identity | 4 | 0 | 2 | 2 | 0 | 25.0% |
| Fundamental features | 4 | 0 | 4 | 0 | 0 | 50.0% |
| Labels | 3 | 1 | 1 | 1 | 0 | 50.0% |
| Macro inputs | 2 | 1 | 1 | 0 | 0 | 75.0% |
| Signal generation | 4 | 3 | 0 | 1 | 0 | 75.0% |
| Evaluation | 5 | 2 | 2 | 1 | 0 | 60.0% |
| Backtesting | 5 | 1 | 2 | 2 | 0 | 40.0% |
| Portfolio analytics | 3 | 1 | 2 | 0 | 0 | 66.7% |
| Reporting | 2 | 1 | 1 | 0 | 0 | 75.0% |
| AI assistance | 3 | 1 | 1 | 1 | 0 | 50.0% |
| Point-in-time integrity | 5 | 0 | 5 | 0 | 0 | 50.0% |
| Determinism | 4 | 0 | 4 | 0 | 0 | 50.0% |
| Reproducibility | 4 | 0 | 3 | 1 | 0 | 37.5% |
| Auditability and traceability | 4 | 0 | 4 | 0 | 0 | 50.0% |
| Governance | 3 | 1 | 1 | 0 | 1 | 50.0% |
| Testability | 4 | 0 | 2 | 2 | 0 | 25.0% |
| Reliability | 2 | 0 | 2 | 0 | 0 | 50.0% |
| Scalability | 2 | 1 | 1 | 0 | 0 | 75.0% |
| Security | 3 | 3 | 0 | 0 | 0 | 100.0% |

Completeness is a reporting index: fully implemented counts 1.0, partial counts 0.5, missing and unknown count 0. It is not a code-coverage percentage and is not a quality score.

## 4. Coverage by CRISP-DM Phase

| Phase | Total | Implemented | Partial | Missing | Unknown |
|---|---|---|---|---|---|
| Business Understanding | 2 | 0 | 0 | 1 | 1 |
| Data Understanding | 3 | 0 | 2 | 1 | 0 |
| Data Preparation | 28 | 3 | 24 | 1 | 0 |
| Modeling | 7 | 5 | 1 | 1 | 0 |
| Evaluation | 20 | 3 | 10 | 7 | 0 |
| Deployment | 18 | 6 | 11 | 1 | 0 |
| Data Governance | 6 | 1 | 5 | 0 | 0 |

`Data Governance` is a cross-cutting phase used by the repository's audit schema; the Stage 2 prompt's six-phase matrix treats those requirements under the nearest CRISP-DM phase. The matrix file maps each phase explicitly.

## 5. Confidence Distribution

| Confidence band | Count | Percentage |
|---|---|---|
| 0.90–1.00 | 60 | 71.4% |
| 0.80–0.89 | 20 | 23.8% |
| 0.70–0.79 | 3 | 3.6% |
| Below 0.70 | 1 | 1.2% |

## 6. Evidence and Test Linkage

| Linkage | Count | Percentage |
|---|---|---|
| Linked to at least one audit finding | 84 | 100.0% |
| Direct or named test reference | 55 | 65.5% |
| Partial, substring or planner-only test | 5 | 6.0% |
| No direct test found | 24 | 28.6% |

## 7. Status by Risk

| Risk | Total | Implemented | Partial | Missing | Unknown |
|---|---|---|---|---|---|
| Critical | 4 | 0 | 3 | 1 | 0 |
| High | 45 | 1 | 35 | 9 | 0 |
| High latent | 1 | 0 | 0 | 1 | 0 |
| Medium | 22 | 7 | 14 | 0 | 1 |
| Low | 12 | 10 | 1 | 1 | 0 |

## 8. Interpretation

- The register is majority **Partial** because the repository implements broad capabilities but leaves provenance, point-in-time and consistency controls incomplete. This is consistent with Stage 0's 17 Present / 6 Partial / 2 Absent capability profile.
- Every **Missing** requirement is backed by a specific code or schema gap: PIT membership, delisting, label immutability, score immutability, frozen holdout, costs, artifact manifests, text intelligence and coverage tooling.
- A high confidence value with a Partial status is not a contradiction: the evidence about the implementation is strong, while the implementation itself is incomplete.
- Percentages describe this recovered register, not the repository's true requirement universe. There is no pre-existing specification against which recall can be measured.
