# Step 5 — Dividend Evidence, Key, and Batch Semantics (RM-03/04) Recommended Contract (Prepared)

| Field | Value |
|---|---|
| Recommendation | Append-only evidence + deterministic curated state; fix batch dedupe, date preservation, and feed-evidence retention |
| Status | **Prepared; decisions and implementation pending** |
| Traceability | `RM-03`, `RM-04`, `RM-05` (auditability), `FR-DIV-01/03/04/05/08`, `DG-02/04/05/06`, `DA-21`, `RK-10`, `UNK-002/005`, `TSK-019`, `P0-TSK-002` |
| Evidence | `../06-execution-prep/dividend-batch-key-contract-draft.md`, `../06-execution-prep/unk001-unk002-basis-analysis-2026-11-15.md`, `../06-execution-prep/unk005-isolated-batch-test-2026-11-15.md`, `../06-execution-prep/unk005-actual-upsert-isolated-test-2026-11-15.md`, `scripts/populate_dividend_data.py` |

## 1. Evidence summary
- **Key/feed:** `raw.dividend_data` PK `(security_id, ex_dividend_date, provider)` omits `feed`; actual-upsert isolated test showed same key/provider with different `feed` supersedes to 1 row (`fmp` replaced prior state) -> evidence loss/collision risk. DB evidence: OPENBB has `yfinance` and `fmp` feeds.
- **Upsert semantics:** unconditional `EXCLUDED.*` assignment; isolated actual-upsert test showed known `declaration_date` overwritten to NULL by later upsert.
- **Batch behavior:** multi-values same-key insert with `ON CONFLICT DO UPDATE` raised `CardinalityViolation` in isolated tests; row-wise execution may appear to succeed but is order/driver-dependent without explicit contract.
- **Basis heterogeneity (`UNK-002`):** yfinance `adjusted_amount` NULL (176,396), FMP adjusted non-null (20,783; 268 amount!=adjusted), SEC_XBRL adjusted NULL (126,453), cross-provider amount differences and 307,046 rows with >=1 null date.

## 2. Recommended target solution
### 2.1 Evidence retention (preferred)
- **Option A (preferred):** Append-only `raw.dividend_events_evidence` (or equivalent) keyed by retrieval/event identity including provider/feed/source ids/hashes/timestamps and full payload fields; maintain deterministic curated/current projection for consumers.
- **Option B (staged):** Redesign current-state key/constraints to prevent unintended feed collisions (e.g. include `feed`/source identity where meaningful) while adding append-only audit/reconciliation records. Do not rely on silent supersession.

### 2.2 Deterministic in-batch pre-deduplication (required)
- Before execute, collapse rows sharing the effective conflict key within a batch.
- **Recommended precedence (approve explicitly):** (1) audited/manual correction marker if present, (2) higher completeness (non-null declaration/record/payment/amount fields), (3) approved feed/provider priority for use case, (4) latest `retrieved_at`/source timestamp, (5) stable tiebreaker (e.g. source hash).
- Log dedupe decisions/counts and losers as audit evidence (append-only).

### 2.3 Date/field preservation
- Use `COALESCE(EXCLUDED.field, existing.field)` for declaration/record/payment dates (and other fields where null means unknown, not correction), **unless** an explicit correction/version event is recorded.
- Corrections must be append-only/auditable: who/when/source/reason/prior value/new value.

### 2.4 Quarantine and reconciliation
- Runtime quarantine for implausible/new bad rows with append-only audit (`FR-DIV-05`, `DG-04/05`).
- Reconciliation verdicts append-only with reason codes (no-evidence vs disagreement).

### 2.5 Canonical amount/basis (`UNK-002`)
- Publish provider/feed basis matrix and canonical consumer fields (raw amount, adjusted amount, basis flag, currency/unit normalization) per approved decision.
- Do not mix incompatible bases in total return/features without explicit conversion/policy.

## 3. Verification plan (isolated then project-path)
- `V-DIV-01`: key/model retains required feed-level evidence.
- `V-DIV-02`: non-NULL stored dates survive NULL incoming update (COALESCE/correction rule).
- `V-DIV-03`: duplicate-key batch pre-deduped deterministically; multi-values duplicate case cannot fail unexpectedly (isolated DB evidence already captured; repeat on project loader path).
- `V-DIV-04`: quarantine/reconciliation/corrections append-only.
- `V-DIV-05`: downstream PIT/total-return/feature outputs align to canonical basis.
- **Constraint:** project-loader runtime validation must run in isolated project test DB/schema with rollback/teardown; no shared DB writes.

## 4. Decisions required
- Key/feed-evidence strategy (Option A/B), dedupe precedence order, correction policy, and canonical amount basis owners/approval (`DEC-*`/M1-M2).
