# US1 Verification: Trust Historical Research Inputs

**Feature**: `specs/001-p0-recovery/spec.md`

**Scope**: T009–T015 (P1 MVP)

**Status**: Verified scaffolding and policy; PIT consumer cutover remains approval-gated

## T009 — Explicit as-of handling

- `src/crispdm/pit.py` exposes `normalize_as_of`, `require_as_of`, `is_available_as_of`, `pit_manifest_metadata`, `merge_pit_parameters`, and `pit_context` helpers. `require_as_of` raises for missing as-of in a PIT-sensitive context.
- `src/crispdm/feature_window.py` binds `:as_of` in the feature-window SQL anchor and exposes `feature_window_pit_metadata`; the SQL still has a `COALESCE(..., MAX(as_of_date))` fallback for non-PIT callers.
- Current eligibility mode is `current_state_active_flag_with_as_of_scores`; `verified_pit_compliant` remains false. This is a verified draft, not PIT enforcement.

## T010 — Membership interval structures

- `V0107_rm01_pit_membership.sql` creates `reference.security_membership_history` with `security_id`, `status`, `effective_from`, `effective_to`, `listed_date`, `delisted_date`, source/run metadata, and `CHECK (effective_to IS NULL OR effective_to >= effective_from)`.
- It creates `reference.security_eligibility_asof` keyed by `(as_of_date, security_id)` and adds `reference.securities.delisted_date`.
- Status taxonomy is intentionally unconstrained pending M1/DEC disposition; interval overlap and backfill completeness are checked by `check_candidate_backfill_readiness.py`.

## T011 — Delisting and reclassification rules

See `migration-backfill-plan.md` section 7.7. Summary:

- Populate `delisted_date` only from authoritative listing/exchange/filing evidence or an explicitly approved proxy.
- Never infer delisting solely from `active = FALSE`.
- Reclassification and identity release must preserve closed intervals or tombstones; historical rows are not deleted.
- Until PIT membership is reconciled, outputs remain labeled survivor-biased and non-decision-grade under EX-001/EX-004.

## T012 — Timing-column contract

- `V0108_rm02_pit_timing.sql` adds `declared_known_at`, `record_known_at`, `payment_known_at`, `ex_known_at`, `available_at`, `timing_evidence_source`, and `timing_confidence` to `raw.dividend_data`.
- Indexes support reads on `(security_id, available_at)` and partial `ex_known_at`.
- Fundamentals availability ALTERs remain commented pending canonical table reconciliation.
- Consumer filtering on `available_at <= as_of` is not enabled by this candidate.

## T013 — Availability/proxy policy

See `validation-plans-unk001-007.md` section UNK-002/UNK-003. Policy:

- Absent defensible availability evidence, exclude the fact from covered replay or label it as an approved conservative proxy.
- A proxy is approved only when basis, owner, decision reference, and expiry are recorded.
- An unrecorded proxy is not evidence of availability.

## T014 — Survivor-vs-PIT comparison

See `pit-delta-2026-11-18.md`. True delta remains blocked by missing approved membership data; proxy evidence is recorded without claiming materiality closure.

## T015 — Read-only readiness evidence

Report: `sql-candidates/backfill/readiness-us1-2026-11-18.json`.

## US1 checkpoint

Scaffolding, contracts, proxy policy, and read-only checks are independently reviewable. No PIT consumer cutover, approved backfill, or decision-grade claim is authorized.
