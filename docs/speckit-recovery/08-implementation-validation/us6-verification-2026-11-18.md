# US6 Verification: Governance and Traceability

**Feature**: `specs/001-p0-recovery/spec.md`

**Scope**: T041–T045 (P3)

**Status**: Governance gates explicit; implementation accepted only under named exceptions

## T041 — Critical exception register

`docs/speckit-recovery/06-execution-prep/decision-unknown-tracker.md` now contains EX-001..EX-005 with disposition, compensating control, owner, expiry, authority/date, and status. All are open/time-bounded or remediation-required; none is closed.

## T042 — M1 decisions

`docs/speckit-recovery/06-execution-prep/m1-decision-log-template.md` records M1 Conditional GO, 14-principle and 95-rule disposition, EX/DEC/UNK outcomes, named role owners, and due dates. Authority is role-based; named individual substitution remains an audit-hygiene follow-up.

## T043 — Promotion blocking

`scripts/check_promotion_evidence.py` reports named policy gaps and `--require-promotion-grade` exits 1 on the draft policy. Verified with `tests/test_check_promotion_evidence.py`; no promotion claim is accepted.

## T044 — Security / least privilege

`tests/test_api.py` and `tests/test_ops_catalog.py` pass (64 tests combined), preserving API auth/rate-limit and catalog-allowlisted ops controls.

## T045 — RTM traceability

`docs/speckit-recovery/08-implementation-validation/rtm-update-draft.md` records US1–US6 evidence and the remaining external gates.

## US6 checkpoint

No critical gap is implicit. Promotion, candidate migration, and production cutover remain blocked until closure evidence and approvals are recorded.
