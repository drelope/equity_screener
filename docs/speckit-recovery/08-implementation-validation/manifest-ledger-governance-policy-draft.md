# Manifest Ledger Governance Policy (Draft)

Status: **draft, not approved, not enforced.** This policy covers the V0110
ledger tables and V0111 append-only triggers. It does not grant roles, alter a
database, approve retention, or prove operational separation of duties.

Machine-readable template: `manifest-ledger-governance-policy-template.json`
Checker: `scripts/check_manifest_ledger_policy.py`
Tests: `tests/test_check_manifest_ledger_policy.py`

## Why This Exists

V0111 blocks `UPDATE`/`DELETE` for all normal sessions, but a trigger alone is not
governance: a superuser can disable it, grants can be too broad, and retention or
incident-response actions still need an approved path. DEC-002/DEC-003/DEC-005 and
M1 must define who may read/write, how long evidence is kept, and how a controlled
exception is handled.

## Role / Grant Invariants

| Role | Allowed | Explicitly forbidden |
|---|---|---|
| `manifest_writer` | `INSERT` on both ledger tables; `USAGE` on `audit.run_outputs_output_id_seq` | `UPDATE`, `DELETE`, `TRUNCATE` |
| `manifest_reader` | `SELECT` on both ledger tables | `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` |
| `ledger_auditor` | `SELECT` on both ledger tables + `public.schema_migrations` | `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` |
| `dba_admin` | owner operations, including controlled trigger disable | routine `UPDATE`/`DELETE` grants |
| `PUBLIC` | nothing | all privileges |

The checker enforces these invariants from the JSON policy. Actual role names/owners
must be mapped to deployment roles before a grants candidate is written.

## Retention

- Legal hold and purge approval/export/dual-control are mandatory.
- `minimum_days` is deliberately `null` in the draft; an approved policy must set a
  positive value after DEC/legal review.
- Purge is **export-then-drop**, not in-place mutation. Existing rows are evidence.
- No retention period is claimed as approved or implemented.

## Incident Response

Preferred remediation is an appended correction/incident record. Break-glass
deletion requires: incident ticket, dual control, export before mutation, trigger
re-enable, post-incident review, and retained evidence. The break-glass role must be
`dba_admin`, never an application writer/reader. None of this is implemented as a
database role model yet.

## Approval Checklist

1. Map policy roles to real deployment roles/owners and record the mapping.
2. Record M1, DEC-002, DEC-003, DEC-005 decisions in
   `../06-execution-prep/m1-decision-log-template.md` and
   `decision-unknown-tracker.md`.
3. Set an approved retention period and legal-hold procedure.
4. Security/DBA review of grants, trigger bypass, and incident runbook.
5. Add a role/grant candidate only after the policy is approved; rehearse on an
   isolated disposable database and prove writer/reader/auditor boundaries.
6. Keep V0110/V0111 outside `sql/migrations/` until all gates are satisfied.

## Run the Checker

```bash
python3 scripts/check_manifest_ledger_policy.py
python3 scripts/check_manifest_ledger_policy.py --json
python3 scripts/check_manifest_ledger_policy.py --require-approved  # expected exit 1
```

`PASS` means the draft policy is structurally complete and its safety invariants hold.
It is **not** approval, enforcement, or operational evidence.

## Explicit Gaps

- No role/grant SQL candidate; deployment role names and ownership are unknown.
- No retention job, legal-hold mechanism, purge procedure, or incident log table.
- No database test that role boundaries are actually enforced.
- No approval records; `status` remains `draft_not_approved`.
