# Recommendation Execution (Step-by-Step)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Scope | Step-by-step preparation for recommendations 1–8 (governance, PIT, adjustments, dividends, reproducibility/eval, Reports Center, external controls) |
| Constraints | Read-only recovery prep: no source/test/config changes, no DB writes, no pipeline/test execution. Only Markdown written under `docs/speckit-recovery/`. Human/external approvals and controlled/prod validations remain required where noted. |
| Status | **Preparation artifacts created; approvals/implementation/verification pending** |

## Execution tracker

| Step | Recommendation | Artifact(s) | Executable now | Status | Blockers / next action |
|---|---|---|---|---|---|
| 1 | M1 governance gate (ratification, `EX-001..05`, `DEC-001..08`) | [`step-01-m1-governance.md`](step-01-m1-governance.md) | Prep/decision package completed | Prepared (pending approval) | Human authority/session: record outcomes in `../06-execution-prep/m1-decision-log-template.md`, `../06-execution-prep/decision-unknown-tracker.md` |
| 2 | PIT universe/survivorship (`RM-01`, `FR-UNI-01`, `NFR-PIT-02`, `UNK-003`) | [`step-02-pit-universe-rm01.md`](step-02-pit-universe-rm01.md) | Design/spec prepared | Prepared (blocked) | Approvals + PIT membership data/design; post-implementation comparison for `UNK-003` |
| 3 | PIT timing for fundamentals/dividends (`RM-02/03`, `NFR-PIT-01`, `FR-DIV-03`, `FR-FEAT-01`) | [`step-03-pit-timing-rm02-rm03.md`](step-03-pit-timing-rm02-rm03.md) | Design/spec prepared | Prepared (pending decision/impl) | Availability-timestamp contract and implementation/verification |
| 4 | Market adjustment integrity (`RM-03/04`, `FR-ADJ-01`, `FR-DIV-07`, `UNK-001`) | [`step-04-market-adjustment-rm03-rm04.md`](step-04-market-adjustment-rm03-rm04.md) | Evidence + recommended contract prepared | Prepared (pending decision) | Canonical basis decision, broader/provider confirmation, backfill/consumer alignment |
| 5 | Dividend evidence, key, batch semantics (`RM-03/04/05`, `FR-DIV-01/04/05/08`, `UNK-002/005`) | [`step-05-dividend-evidence-batch-rm03-rm04.md`](step-05-dividend-evidence-batch-rm03-rm04.md) | Evidence + concrete recommended contract prepared | Prepared (pending decision) | Approve key/feed/precedence/COALESCE policy; isolated project-loader validation |
| 6 | Reproducibility and decision-grade evaluation (`RM-04/05/06`, `FR-EVAL-03`, `DEC-002/003/004/005/008`) | [`step-06-repro-evaluation-rm04-rm05-rm06.md`](step-06-repro-evaluation-rm04-rm05-rm06.md) | Manifest/eval/lock spec prepared | Prepared (pending decision/impl) | Policy/holdout/benchmark/lock decisions and implementation evidence |
| 7 | Reports Center provenance and as-of (`TSK-011/024`, `FR-REP-02`, `UNK-004`) | [`step-07-reports-center.md`](step-07-reports-center.md) | Contract refined from repo/runtime evidence | Prepared (pending UI confirmation/impl) | Manual/browser UI verification and implementation per approved contract |
| 8 | External/operational controls (`DEC-001/006/007`, `UNK-007`) | [`step-08-external-operational-controls.md`](step-08-external-operational-controls.md) | Requests/checklists consolidated | Prepared (pending external evidence) | Legal/provider/platform/SRE evidence and decisions |

## Cross-cutting inputs
- Baseline: `../02-requirements/*`, `../03-constitution/*`, `../04-migration/*`, `../05-speckit/*`
- Execution prep: `../06-execution-prep/*` (m1-decision-log, trackers, contracts, validations, blocked-items, human-external package)
- Readiness rule: do not claim implementation, verification, or promotion-grade status without task-level evidence and required approvals.

## Approved implementation/validation handoff
- Approval recorded: 2026-11-15 (user). Execution package prepared in [`../08-implementation-validation/README.md`](../08-implementation-validation/README.md) (implementation plan, validation plan, migrations/backfill, RTM draft, execution log). Actual source/test/config/DB/CI execution must be performed in an approved implementation environment and recorded with evidence.
