# Skill Design: `financial-scoring`

Status: code complete; verification in progress
Owner: analysis
Risk: write
Source of truth: `skills/financial-scoring/SKILL.md`, `src/crispdm/scoring.py`,
`src/crispdm/regime.py`, `scripts/score_rank.py`, `docs/requirements.md`
Token budget: `SKILL.md <= 160 lines / 8,000 chars; each reference <= 260 lines / 12,000 chars`
Open questions: none

## Clarify

- **Problem:** the skill mixed policy ownership with implementation, had no
  standard Runner/Preflight sections, and a handoff incorrectly routed
  "Scoring/labeling policy" back to itself.
- **Decision supported:** implement an approved scoring policy and replay the
  affected dates without changing policy or interpreting results.
- **Audience:** engineer and reviewer changing the composite, regime or
  threshold.
- **In scope:** approved weight/component/regime/threshold implementation,
  historical replay, pruning and rank-diff evidence.
- **Out of scope:** weight/universe/acceptance policy
  (`business-understanding`), feature construction
  (`data-transformation`), validation/reporting (`financial-analysis`), ML gate
  (`modeling-evaluation`), UI-only changes.
- **Evidence:** `src/crispdm/scoring.py` owns `WEIGHTS` and coverage;
  `src/crispdm/regime.py` and `regime_pipeline.py` own the regime layer;
  `scripts/score_rank.py` owns replay/pruning; `tests/test_scoring.py`,
  `test_score_pruning.py`, `test_regime.py` and `test_regime_pipeline.py`
  assert the contracts.
- **Assumptions validated:** the weight policy is documented in
  `docs/requirements.md`; weights must sum to 1; a security below
  `MIN_PRESENT_WEIGHT` is not scored as zero.
- **Success criteria:** policy ownership is explicit; replay/pruning rules are
  testable; the rank diff is reported; no interpretation leaks into scoring.
- **Tool scope:** write, but manual only; no executable runner entrypoint.
- **Token budget:** 8,000 chars / 160 lines for `SKILL.md`; 12,000 chars / 260
  lines per reference.

## Design

- **Trigger:** approved weight/composite/ranking/regime/threshold change;
  historical replay.
- **Non-trigger:** policy decision, feature defect, ML gate, interpretation,
  worksheet, UI-only work.
- **Inputs:** `model.features`, `src/crispdm/scoring.py`,
  `src/crispdm/regime.py`, `docs/requirements.md`,
  `python -m scripts.score_rank`.
- **Outputs:** `model.scores`, `model.predictions`, `model.rankings`, policy/UI
  caption updates and a replay diff.
- **Read/write boundary:** writes only model score outputs after an approved
  policy decision; no schema or feature writes.
- **Handoffs:** `business-understanding`, `data-transformation`,
  `data-acquisition`, `data-storage-schema`,
  `observability-nightly-verification`, `financial-analysis`,
  `modeling-evaluation`, `security-compliance`.
- **Failure modes:** weights not summing to 1, missing policy decision,
  all-NULL component, pruning an older date, unexpected rank diff.
- **Reference plan:**
  - `references/scoring-model.md` — load for weight/component/coverage/regime.
  - `references/change-and-replay.md` — load for replay/pruning/rank diff.
- **Verification:** `scripts.skill_audit --skill financial-scoring`, then the
  targeted scoring/regime pytest set.

## Plan

- **Files to add:** two references; this design record.
- **Files to modify:** `skills/financial-scoring/SKILL.md`; routing/inventory
  docs.
- **Files to delete:** none.
- **Tests:** add `tests/test_financial_scoring_skill.py` for contract,
  ownership, replay rules and references.
- **Rollback:** restore `SKILL.md`, remove references/design record and test;
  no data rollback.
- **Acceptance mapping:** ownership boundary → skill test; replay/pruning →
  skill test and existing scoring tests.

## Code

- **Files changed:** `skills/financial-scoring/SKILL.md` rewritten with the
  standard contract and a corrected boundary.
- **Tests added:** `tests/test_financial_scoring_skill.py`.
- **Deviations:** none.

## Verify

- **Commands:** `python -m scripts.skill_audit --skill financial-scoring`;
  `python -m pytest -q tests/test_financial_scoring_skill.py
  tests/test_scoring.py tests/test_score_pruning.py tests/test_regime.py
  tests/test_regime_pipeline.py`; `ruff check .`; `ruff format --check .`.
- **Audit result:** pending final run.
- **Targeted test result:** pending final run.
- **Ruff result:** pending final run.
- **Residual risks:** historical replay requires a configured database; this
  change verifies the contract and tests, not a production replay.

## Gate log

| Phase | Result | Evidence |
|---|---|---|
| clarify | pass | Ownership conflict and scope recorded above |
| design | pass | Contract, references and handoffs in this record |
| plan | pass | File/test/rollback list above |
| code | pass | `skills/financial-scoring/` and new skill test |
| verify | pending | Final audit, targeted pytest and ruff |
