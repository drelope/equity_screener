# Dividend Batch, Key, and Date-Integrity Contract Draft

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation (design draft) |
| Date | 2026-11-15 |
| Status | **Draft; not approved or implemented** |
| Related | `UNK-005`, `DA-21`, `FR-DIV-01`, `FR-DIV-04`, `FR-DIV-05`, `DG-02`, `DG-05`, `DG-06`, `RK-10`, `TSK-019`, `P0-TSK-002` |

## 1. Current observed behavior (repo/DB evidence)

- Schema: `raw.dividend_data` PK is `(security_id, ex_dividend_date, provider)`; columns include `feed`, `amount_feed`, `adjusted_amount`, `retrieved_at`.
- Loader (`scripts/populate_dividend_data.py`): `DIVIDEND_UPSERT` uses `ON CONFLICT (security_id, ex_dividend_date, provider) DO UPDATE SET ...` with unconditional assignment of `declaration_date`, `record_date`, `payment_date`, amounts, feed fields, etc. from `EXCLUDED` (no `COALESCE` preservation for non-NULL stored dates).
- Batch path: rows appended to `insert_rows` and executed as `conn.execute(DIVIDEND_UPSERT, insert_rows)`; no in-batch deduplication on the conflict key was found in inspected code.
- DB evidence (read-only, 2026-11-15): no OPENBB duplicate `(security_id, ex_dividend_date)` rows observed; multi-provider same-date rows exist (e.g. OPENBB + SEC_XBRL), consistent with provider-scoped PK. 307,046 rows have >=1 null date field; provider/feed amount-adjusted semantics are heterogeneous.

## 2. Risks / gaps

- **Feed collision (`FR-DIV-01`, `DG-02`):** PK omits `feed`, so different feeds for same provider/event key cannot be independently persisted by key; evidence retention depends on supersession/overwrite logic.
- **NULL overwrite (`FR-DIV-04`, `DG-06`, `DA-05`):** incoming NULL declaration/record/payment dates can overwrite previously known non-NULL values.
- **Batch duplicate ambiguity (`DA-21`):** duplicate conflict keys within one batch upsert may cause PostgreSQL error ("ON CONFLICT DO UPDATE command cannot affect row a second time") or require deterministic pre-deduplication; runtime behavior not yet verified by controlled write test.
- **Quarantine/provenance (`FR-DIV-05`, `DG-05`):** runtime quarantine and append-only reconciliation/evidence requirements need alignment with key design.

## 3. Target contract (proposed)

### 3.1 Identity and evidence retention
- Persist dividend evidence so provider **and feed/source payload identity** do not collide when both are meaningful.
- Preferred options (to decide in spec): (A) include `feed` in natural key/unique constraint where applicable, or (B) introduce append-only raw dividend event/evidence table keyed by retrieval/event identity with a curated current-state projection.
- Retain `provider`, `feed`, `amount_feed`, `retrieved_at`, source identifiers/hashes, and filing/reconciliation provenance needed for audit.

### 3.2 Upsert/date semantics
- Upserts MUST preserve existing non-NULL `declaration_date`, `record_date`, `payment_date` when incoming value is NULL, unless an explicit correction/versioning rule applies.
- Any correction/override MUST be auditable (who/when/source/reason), preferably via append-only evidence/version records.

### 3.3 Batch determinism
- Loader MUST deterministically deduplicate rows targeting the same conflict key within a batch before execute (document precedence: e.g. feed priority, retrieval time, completeness, amount basis).
- Batch handling MUST be tested for duplicate-key cases; behavior MUST be deterministic and documented (no silent arbitrary winner).

### 3.4 Quarantine and reconciliation
- Implausible/newly detected bad rows MUST follow runtime quarantine rules and append-only audit records (`FR-DIV-05`, `DG-04/05`).
- Reconciliation verdicts/history MUST be append-only with distinct reason codes (no-evidence vs disagreement).

## 4. Verification plan (draft)

- **V-DIV-01 (schema/contract):** tests/spec assert key allows required feed-level evidence or equivalent append-only model.
- **V-DIV-02 (COALESCE):** unit/integration test proves non-NULL stored dates survive NULL incoming update.
- **V-DIV-03 (batch duplicate):** controlled isolated test inserts two same-key rows in one batch and asserts deterministic outcome (prefer pre-deduped success, not runtime error).
- **V-DIV-04 (provenance):** reconciliation/quarantine actions append auditable records.
- **V-DIV-05 (regression):** PIT/feature/total-return consumers use intended dated/basis-correct dividend values.

> `V-DIV-03` runtime verification requires a safe isolated environment/transactional sandbox; not executed against the shared DB in this preparation pass.

## 5. Dependencies / open points
- Alignment with PIT/filing-date work (`RM-02`, `FR-DIV-03`) and lineage/manifest work (`RM-04/05`).
- Canonical amount basis per provider/feed (`UNK-002`, `FA-U03`) and downstream consumer expectations.
- Migration/backfill strategy for existing PK and historical rows (dual-read/write, reconciliation).

## 6. Non-goals
- No schema/code changes made in this draft.
- No claim that current behavior satisfies this contract.
