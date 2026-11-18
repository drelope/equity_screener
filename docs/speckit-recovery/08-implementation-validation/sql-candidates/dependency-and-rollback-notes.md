# Candidate Dependency, Backfill, and Rollback Notes

Companion to `candidate-manifest.json` and `README.md`. These notes describe what must be true **before** a candidate is promoted, what backfill is needed after apply, and how to reverse it. No candidate is approved or applied.

## Common preconditions

- M1 constitution/status-taxonomy ratification recorded.
- Per-candidate EX/DEC/UNK gates recorded in `../../06-execution-prep/decision-unknown-tracker.md`.
- Isolated disposable-DB rehearsal with the canonical baseline (`sql/schema.sql` + init inline + versioned migrations) and candidate files; evidence stored alongside `../sql-drafts/rehearsal-full-apply-2026-11-16.json`.
- Ledger check: `public.schema_migrations` max and names still reconcile with `sql/migrations/`; no new duplicate version; V0045 remains unused.
- Rollback rehearsal on a disposable copy using the candidate's `rollback/` script, including the manual ledger deletion.

## V0107 — RM-01 PIT membership

**Hard dependencies:** `reference.securities` exists.
**Soft dependencies:** none for DDL; UNK-003 comparison needs membership backfill first.
**Apply order:** independent; can be first.

**Backfill after apply:**

1. Populate `reference.security_membership_history` from approved membership evidence (exchange listing history, SEC filings, provider status snapshots), one open interval per security plus closed intervals where known.
2. Derive `reference.securities.delisted_date` only from reconciled evidence; leave NULL when unknown. Do not infer delisting from `active = FALSE` alone.
3. Materialize `reference.security_eligibility_asof` only for dates required by validation/recompute; record `source_run_id`.
4. Reconcile counts: active securities, inactive/delisted with/without `delisted_date`, membership intervals overlapping/duplicating.
5. Run survivor-vs-PIT comparison (UNK-003) and record magnitude before any eligibility enforcement.

**Consumer cutover:** none in this candidate. A follow-up change must replace `s.active = TRUE` reads with an as-of eligibility source and carry PIT metadata/manifest refs. Until then, outputs remain survivor-biased and cannot support decision-grade claims.

**Rollback:** `rollback/V0107_rollback.sql` drops the two tables, the `delisted_date` column, and the partial index. Export all three objects first. Dropping `delisted_date` discards any backfilled evidence. Delete ledger row 107 manually after the DDL rollback commits.

**Risks:** status taxonomy drift; duplicate overlapping intervals; treating NULL delisted date as still-listed; backfill silently encoding survivorship.

## V0108 — RM-02 PIT timing

**Hard dependencies:** `raw.dividend_data` exists.
**Soft dependencies:** V0107 for universe context; V0109 for evidence-first known-at semantics.
**Apply order:** independent DDL; typically after V0107.

**Backfill after apply:**

1. Populate dividend `*_known_at` and `available_at` only where provider payloads or retrieval evidence support the timestamp. Otherwise leave NULL and record `timing_confidence`.
2. Do not fabricate knowledge times from event dates. If a conservative proxy is approved, encode it explicitly in `timing_evidence_source`.
3. Run reconciliation for NULL/available-before-event/available-after-retrieval anomalies; quarantine rather than overwrite.
4. Fundamentals availability ALTERs remain disabled until DEC-007 confirms the canonical table; do not uncomment without a new candidate/hash review.

**Consumer cutover:** none in this candidate. Feature/label/dividend queries must be updated in a separate approved change to filter on `available_at <= as_of` (or the approved proxy). The existing `GREATEST(filed, period_end)` feature path remains a leakage-risk proxy until then.

**Rollback:** `rollback/V0108_rollback.sql` drops the indexes and seven dividend columns. Export timing columns first. Revert any consumer cutover before dropping. Delete ledger row 108 manually after the DDL rollback commits.

**Risks:** unverified timestamps presented as PIT-safe; basis decision (UNK-001/002) changing amount semantics while timing is added; partial backfill leaving most rows NULL and consumers silently falling back to event dates.

## V0109 — RM-03 dividend evidence/quarantine

**Hard dependencies:** `reference.securities`, `raw.dividend_data`, `audit` exist.
**Soft dependencies:** V0108 timing columns for evidence-known-at cutover.
**Apply order:** independent DDL; after V0108 if evidence loader will write `*_known_at`.

**Backfill after apply:**

1. Decide the approved conflict key/feed precedence and whether the curated projection is a view or table (UNK-002/UNK-005). Record the decision before writing evidence.
2. Backfill evidence from stored raw rows and retained provider payloads where available; hash payloads; never overwrite raw rows.
3. Seed quarantine from known invalid/duplicate/basis-conflict cases with reason codes; do not delete raw evidence.
4. Dual-read: compare curated projection vs `raw.dividend_data` for counts, amounts, dates, and provider/feed coverage. Record deltas and approval before cutover.
5. Keep the existing loader's deterministic in-batch dedupe and COALESCE date preservation until the evidence-first path is validated.

**Consumer cutover:** none in this candidate. The loader and feature/return consumers switch only after the curated projection and evidence precedence are approved and reconciled.

**Rollback:** `rollback/V0109_rollback.sql` drops `audit.dividend_corrections`, `audit.dividend_quarantine`, and `raw.dividend_data_evidence`. Export all three first; this destroys the audit trail. Delete ledger row 109 manually after the DDL rollback commits.

**Risks:** encoding an unapproved key/precedence; losing raw evidence; duplicate evidence rows; quarantine status used as a soft delete; correction history being mutated.

## V0110 — RM-04/RM-05 run manifest/output ledger

**Hard dependencies:** `audit` schema exists.
**Soft dependencies:** V0107–V0109 for run context; scripts currently write file manifests only.
**Apply order:** independent DDL; can be first if manifest persistence is prioritized.

**Backfill after apply:**

1. Not required for DDL. Optionally backfill historical file manifests into `audit.run_manifests` with hashes and a recorded backfill run id.
2. Add script persistence behind an approved flag; opt-in scaffolding exists in
   `src/crispdm/manifest_store.py` + `scripts/persist_run_manifest.py` (dry-run
   default, append-only, idempotent/conflict-safe). Keep file artifacts as the
   source until dual-write is validated.
3. Add run-keyed output rows (`audit.run_outputs`) for scores/reports/features/labels only after RM-05 cutover design is approved.
4. Validate immutable-read expectations: no UPDATE/DELETE paths; define role/trigger policy in a follow-up candidate after DEC-002/003/005.
5. Check that manifest hashes in the ledger match the file artifacts and that reruns do not overwrite prior run rows.

**Consumer cutover:** none in this candidate. Reports/scores remain transient or file-keyed until the approved run-keyed store and historical as-of selection land.

**Rollback:** `rollback/V0110_rollback.sql` drops `audit.run_outputs` and `audit.run_manifests`. Export both first; dropping discards provenance. Delete ledger row 110 manually after the DDL rollback commits.

**Risks:** ledger rows treated as mutable evidence; run_id reuse; manifest hash drift between file and DB; output rows referencing deleted run ids.

## V0111 — RM-04 manifest ledger immutability

**Hard dependencies:** V0110 (`audit.run_manifests`, `audit.run_outputs`).
**Soft dependencies:** none.
**Apply order:** after V0110.

**What it adds:** `audit.prevent_run_manifest_mutation()` plus `run_manifests_append_only` and `run_outputs_append_only` triggers. `UPDATE`/`DELETE` on either table raises SQLSTATE `23000`; append/insert remains allowed.

**Backfill after apply:** none.

**Consumer cutover:** none. Persistence stays opt-in (`scripts/persist_run_manifest.py`); no automatic pipeline wiring.

**Rollback:** `rollback/V0111_rollback.sql` drops both triggers and the function. It does not touch V0110 tables or rows. A rollback after data exists must first decide whether to drop the ledger entirely (V0110 rollback) or disable the guard; neither is approved.

**Risks:** legitimate correction/retention/incident-response workflows are blocked until DEC-002/003/005 define a controlled exception path; trigger does not enforce grants/roles; a superuser can still disable triggers.

## V0112 — ledger role grants (speculative)

**Hard dependencies:** V0110 tables, V0111 triggers, and DBA-provisioned NOLOGIN NOINHERIT roles `manifest_writer`, `manifest_reader`, `ledger_auditor`.
**Apply order:** after V0111.

**What it does:** asserts the roles exist and are group roles; revokes PUBLIC and current ledger grants; grants writer INSERT-only (plus sequence usage), reader/auditor SELECT-only, and auditor SELECT on `public.schema_migrations`. It does not create or drop roles.

**Rollback:** `rollback/V0112_rollback.sql` revokes only these grants. It leaves the cluster-level roles in place because they may have other grants.

**Risks:** role names or ownership differ in deployment; revoking PUBLIC/schema privileges may affect other consumers; a superuser or table owner bypasses grants.

## V0113 — ledger governance event log (speculative)

**Hard dependencies:** V0110 `audit.run_manifests`.
**Soft dependencies:** V0111 append-only behavior for the ledger itself.
**Apply order:** after V0110; independent of V0112.

**What it does:** creates append-only `audit.ledger_governance_events` with check constraints for approver separation, dual control on legal holds/purges/break-glass, and export before purge completion. It records decisions only.

**Rollback:** `rollback/V0113_rollback.sql` drops the trigger, function, and table. Export the table first; this destroys governance evidence.

**Risks:** the table records decisions but enforces nothing; retention periods and incident runbooks are unapproved; a superuser can disable the trigger.

## Promotion evidence checklist

For each candidate, record in the execution log:

- approval references and decision dates;
- candidate file SHA-256 and final migration filename;
- disposable rehearsal command/result and artifact path;
- backfill/reconciliation results (counts, NULL rates, deltas) using the read-only
  readiness checker documented in `backfill/README.md`;
- rollback rehearsal command/result;
- consumer cutover PR/commit and manifest refs;
- explicit statement of what remains unverified.
