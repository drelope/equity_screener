# AI-IOS Future-Vision Traceability

**Purpose**: Classify the external AI-IOS document against the current P0 recovery feature without importing it as requirements.

**Source**: [AI-IOS-source.md](AI-IOS-source.md)

**Status**: Non-normative future reference. Not approved, not adopted, not a P0 requirement source.

**P0 spec**: [../../../specs/001-p0-recovery/spec.md](../../../specs/001-p0-recovery/spec.md)

**Import date**: 2026-11-18

## Classification legend

| Classification | Meaning |
|---|---|
| Covered in P0 | The underlying need is represented in the P0 spec, though not necessarily verified or implemented. |
| Partial overlap | Some P0 work touches the area, but the AI-IOS scope is broader or different. |
| Out of scope for P0 | Not part of the current P0 recovery feature. Needs a later decision or separate feature. |
| Decision required later | Potentially relevant, but requires an explicit owner, approval, or scope decision before any work. |

## Section map

| # | AI-IOS section | Classification | Disposition / next gate |
|---:|---|---|---|
| 1 | Vision | Partial overlap | P0 covers PIT correctness, evidence, reproducibility, governance, and verification foundations. Full research-to-portfolio automation remains future scope. |
| 2 | Goals | Partial overlap | Governance goals overlap P0; macro/commodity/volatility/currency/flow/social intelligence are out of scope. |
| 3 | Core Principles | Covered in P0 | Shared truth, governance-first, and forecast accountability are reflected as PIT, approval, and evaluation-evidence requirements. No automatic forecast weighting in P0. |
| 4 | Architecture Overview | Out of scope for P0 | The current architecture is not being replaced. P0 hardens existing data-to-evidence paths. |
| 5 | Platform Components | Out of scope for P0 | Agent and command-center components are future-state concepts. Use for roadmap planning only. |
| 6 | Agent Architecture | Out of scope for P0 | No agent fleet is introduced by P0. Requires a separate governance and capability decision. |
| 7 | Macro State Engine | Out of scope for P0 | Existing macro/vintage concerns remain under PIT/reporting constraints; no shared score engine in P0. |
| 8 | Investment Committee Workflow | Partial overlap | P0 records human approvals/exceptions and blocks promotion claims. Automated research-review-red-team-audit-consensus flow is future scope. |
| 9 | Governance Model | Partial overlap | M1/EX/DEC/UNK trackers and promotion gates cover part of this. Entra/OIDC/JWT/RBAC model is not adopted by P0. |
| 10 | TradingView Integration | Out of scope for P0 | No TradingView integration is included in the current feature. |
| 11 | Security Architecture | Decision required later | Preserve existing least-privilege controls. Any identity-provider change needs a dedicated security decision. |
| 12 | API Contracts | Out of scope for P0 | Current API contracts are unchanged by P0; AI-IOS agent APIs are reference only. |
| 13 | Database Schemas | Partial overlap | P0 candidates cover PIT structures, dividend evidence, and run/ledger tables. AI-IOS state stores and knowledge-graph schemas are not adopted. |
| 14 | Knowledge Graph | Out of scope for P0 | Requires separate scope, data governance, and provenance design. |
| 15 | OpenCode Work Breakdown Structure | Decision required later | Treat as future planning input, not as the current tasks artifact. Current tasks remain in `specs/001-p0-recovery/tasks.md` when generated. |
| 16 | Deployment Architecture | Out of scope for P0 | Do not replace current Compose deployment. Kubernetes/topology changes need a separate infrastructure feature. |
| 17 | Local Development | Partial overlap | Reproducible dependency identity is in P0. Specific AI-IOS prerequisites are not adopted. |
| 18 | Environment Variables | Decision required later | Existing environment/secret inventories remain authoritative. No AI-IOS variables are introduced. |
| 19 | Docker Deployment | Partial overlap | Current Docker build is preserved; AI-IOS service topology is reference only. |
| 20 | Kubernetes Deployment | Out of scope for P0 | No Kubernetes manifests or deployment model are added. |
| 21 | Observability | Partial overlap | P0 preserves audit, quarantine, freshness, and verification evidence. Agent accuracy and committee metrics are future scope. |
| 22 | Disaster Recovery | Decision required later | Owner-attested backup/restore evidence remains an external gate. No AI-IOS backup policy is adopted. |
| 23 | Success Metrics | Partial overlap | P0 defines measurable evidence and gate outcomes. Portfolio and platform uptime metrics are future scope. |
| 24 | Future Roadmap | Out of scope for P0 | Autonomous research, self-optimizing committee weights, and continuous agent evolution are explicitly outside P0. |

## P0-relevant takeaways

- The P0 spec already captures the aspirational principles that map cleanly to recovery work: shared truth, governance-first, forecast accountability, reproducibility, and verification gates.
- Do not copy AI-IOS technology choices, schemas, APIs, deployment topology, or agent roles into the P0 plan.
- Any move from reference to requirement must occur through a separate scope decision and, where applicable, M1/DEC/UNK approval.

## Non-claims

- This map does not approve the AI-IOS document.
- It does not change the active SpecKit spec, constitution, plan, or tasks.
- It does not verify that any AI-IOS capability exists in the repository.
