# Stage 4 Migration Readiness Assessment

| Field | Value |
|---|---|
| Stage | 4 — Synthesis and migration |
| Date | 2026-11-15 |
| Overall readiness | **Conditional / Partial** — suitable for controlled remediation and spec recovery; not yet ready for trustworthy promotion claims or unmanaged modernization |

## Readiness by dimension

| Dimension | Rating | Assessment | Evidence | Required to improve |
|---|---|---|---|---|
| Architecture | Medium | Layered components/services/entry points are discoverable (20 components, 11 services, 24 entry points) with clear domain/API/UI/ops/schema separation, but some modules are broad and docs overstate absent target architecture. | Stage 0 maps; `PE-13, PE-20, PE-21, PE-24, PE-25`; `CMP/SVC/EP/DF` inventories | Confirm boundaries/interfaces, archive non-runtime schema, align docs to implemented vs target state (RM-12, RM-13) |
| Dependencies | Low | Runtime reproducibility is weak: worktree `requirements.txt` unpinned (238 lines, 0 ==), no lock, dev/runtime drift, installed package drift; containers/CI pin base images but can inherit mutable deps. | `NFR-REPRO-01..02`, `PE-05, PE-06`, `DA-17`, `TS-F02..03`, `Dockerfile`, `.github/workflows/ci.yml` | Hashed lock, pinned installs in CI/Docker/local, env identity in manifests (RM-06) |
| Technical debt | Low-Medium | Significant correctness/evidence debt (PIT, mutable stores, dividend/adjustment issues, broken dry-run, missing gates) alongside maintainability debt (oversized modules, migration/doc drift). | 53 Partial + 12 Missing reqs, `RK-01..11`, `PE-02/04/08/10/12/15/17/21/23`, `TG-01` | Execute P0/P1 remediation and add regression gates (RM-01..RM-11, RM-13) |
| Portability | Medium-Low | Docker Compose/CI and Postgres schema provide a baseline, but reproducibility depends on external providers/data, unpinned Python deps, and unverified external scheduler/object-store/backup environments. | `SVC/EP` deployment inventory, `PE-05/06`, `RK-06/13`, `NFR-GOV-03` unknown | Lock dependencies, document external integrations/terms, define deploy/runtime manifests and environment contracts (RM-06, RM-12) |
| Schema evolution | Medium | Forward-only numbered migrations and ledger/preflight checks exist, but migration file count/ledger mismatch (104 files vs applied 106) and planned append-only/identity changes are substantial. | `CM-03`, `ES-02`, `PE-22/23`, `NFR-REL-02`, schema/migration inventories | Reconcile ledger, define migration/backfill strategy for run-keyed/append-only/PIT schema changes (RM-04, RM-05, RM-12) |
| Deployment automation | Medium-Low | CI lint/test/security jobs, Dockerized services and ops catalog/allowlists exist, but recent nightly failures, no resume/root-cause capture, and missing release-grade manifest/gates limit safe automation. | `.github/workflows/ci.yml`, `NFR-SEC`, `NFR-REL-02`, `PE-16/17`, nightly runs 57–60 failed, `QG-07..11` aspirational | Harden pipeline reliability and add blocking quality/reproducibility/release gates (RM-07, RM-11, RM-04) |

## Strengths to preserve during migration
- Security and least-privilege controls: API auth/rate limits, ops allowlist, read-only explorer, non-root containers.
- Existing governance/audit primitives: data quality, quarantine, freshness, schema drift checks, append-only macro vintages/profile loads where present.
- Modular layering and explicit Stage 2/3 traceability artifacts (requirements, RTM, PE, constitution draft).

## Blocking conditions for spec-driven adoption
1. PIT integrity controls not enforced/verified (`RK-01, RK-02, RK-09`; `FR-UNI-01`, `NFR-PIT-01..05`).
2. Decision evidence not immutable/addressable/reproducible (`RK-03, RK-04, RK-07`; manifests/run-keyed stores missing).
3. Runtime/test gates insufficient to prevent regression (`RK-06, RK-08`; no lock/coverage/PIT-determinism gate).

## Recommended readiness gate
Proceed to implementation-heavy modernization only after Phase 3 foundation and Phase 4 P0 exit criteria are met (roadmap M3–M4), with Critical requirement exceptions explicitly owned and time-bounded.
