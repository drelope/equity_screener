# P0 SQL Drafts (Non-applied)

Additive draft DDL for RM-01..05 implementation planning. **Not placed in `sql/migrations/`** to avoid accidental migrator discovery/application; promote to versioned migrations only after DEC/UNK approvals, isolated validation, and ledger/numbering reconciliation.

| File | RM/Area | Purpose |
|---|---|---|
| `rm01_pit_membership_additive.sql` | RM-01, WP1 | Membership/status history, as-of eligibility scaffold, `reference.securities.delisted_date` additive column |
| `rm02_pit_timing_additive.sql` | RM-02, WP2 | Fundamentals filing/acceptance/availability timing fields and dividend known-as-of support fields (additive) |
| `rm03_dividend_evidence_quarantine.sql` | RM-03, WP3 | Append-only dividend evidence, quarantine, and correction/audit tables; curated projection TBD |
| `rm04_run_manifest_ledger.sql` | RM-04/05, WP4/5 | Immutable run manifest ledger and run-keyed output references (complements file artifacts) |

All drafts require: approved contracts (`UNK/DEC`), isolated DB validation, backfill/reconciliation plans, manifest capture, and rollback/cutover review before production use.

**Numbered candidates (still non-applied):** `../sql-candidates/` contains V0107–V0110 candidates derived from these drafts, with a hash manifest, additive-only guard checks, dependency/backfill notes, and rollback scripts. They remain outside `sql/migrations/` and are not approved for application. Run `python3 scripts/check_migration_candidates.py` to validate consistency; see `../sql-candidates/README.md`.
