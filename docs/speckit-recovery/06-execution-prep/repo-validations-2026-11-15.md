# Repo Validation Notes (2026-11-15)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation (targeted repo-evidence checks) |
| Date | 2026-11-15 |
| Scope | Read-only code/schema/file inspection plus read-only DB ledger query (`public.schema_migrations`); no DB writes, no pipeline/test execution |
| Purpose | Reduce uncertainty for `UNK-004`, `UNK-005`, `UNK-006` and inform M1/M2 preparation |

## UNK-006 — Migration files vs ledger discrepancy

**Question:** reconcile 104 migration files vs applied max 106 (and prior note of 105 ledger rows).

**Evidence (repository):**
- `sql/migrations/V*.sql` count: **104 files**.
- Version range in filenames: **V0002..V0106** (min 2, max 106).
- Missing filename in range: **V0045** (`missing [45]`).
- Highest present migration: `V0106_us_instrument_view.sql`.

**Evidence (read-only DB query, 2026-11-15):**
- `SELECT version, name FROM public.schema_migrations ORDER BY version`: **105 rows**.
- Min/max: **(1, `baseline: sql/schema.sql + scripts/init_db.py migrations`)** to **(106, `V0106_us_instrument_view.sql`)**.
- Missing applied versions in ledger range: **[45]**.

**Assessment:** Repo and DB state are consistent: 104 migration files + adopted baseline `V0001` = 105 ledger rows; `V0045` is absent both on disk and in the ledger, while ledger max/name matches `V0106`. The previously noted discrepancy is explained by baseline adoption and the numbering gap, not by a mismatched applied migration. Historical reason for the `V0045` gap remains undocumented.

**Status:** **Resolved (evidence-based).** Repo file state and DB ledger reconcile.

**Traceability:** `UNK-006`, `PE-23`, `CM-03`, `ES-02`, `RK-12`, `TSK-007`.

## UNK-004 — Reports Center as-of labeling / persistence

**Question:** does Reports Center store/display resolved as-of and fetch time; can historical reports be generated as-of a selected date?

**Evidence (code):** `app/views/dashboard.py`
- `_reports(context)` builds deterministic markdown from in-memory `context` (not from stored report records): `recent = path.index[-1]` used in report headers (`Morning note - {recent:%Y-%m-%d}`, etc.); content derived from `path`, `table`, `risk`, `performance`, `analyses`, etc.
- `_build_context()` / `_load_context()` load context from warehouse queries (`pf.load_score_dates`, `load_universe`, `load_prices`, `load_analyses`, `load_catalysts`) based on latest/formed score dates and current cached build; no UI parameter for selecting a historical report as-of date was found in the inspected section.
- `_reports_tab` renders selected report markdown and offers `st.download_button` with filename `"{choice}-{context['latest']:%Y-%m-%d}.md"`.
- UI caption states: "Reports are deterministic drafts from the warehouse. No language model is called and no analyst approval is implied."
- No evidence found in inspected paths of report persistence/storage, stored `resolved_as_of`, or `fetch_time` fields for Reports Center outputs.

**Assessment:** Reports are deterministic and generated on demand from current loaded context, labeled by latest path/date values in headers/filename. **No evidence** of persisted report artifacts, explicit stored resolved-as-of/fetch-time metadata, or user-selectable historical as-of report generation in inspected code. This confirms partial/implicit as-of behavior requiring remediation (`FR-REP-02`, `AU-09`, `RK-09`).

**Status:** **Repo-evidence gathered (high confidence).** Running-UI confirmation not performed in this environment but code path is explicit; remediation remains pending.

**Traceability:** `UNK-004`, `BI-37`, `FR-REP-02`, `FR-AI-02`, `NFR-PIT-05`, `AU-09`, `DA-20`, `RK-09`, `TSK-011/024`.

## UNK-005 — Dividend duplicate-key batch and PK/feed contract

**Question:** batch duplicate-key behavior (raise vs silent keep) and feed collision implications of dividend PK.

**Evidence (code/schema):**
- `sql/schema.sql` / migrations: `raw.dividend_data` primary key is **`(security_id, ex_dividend_date, provider)`**; columns include `feed`, `amount_feed`, `retrieved_at`, `adjusted_amount`.
- `scripts/populate_dividend_data.py`:
  - `DIVIDEND_UPSERT` inserts dividend fields and uses `ON CONFLICT (security_id, ex_dividend_date, provider) DO UPDATE SET ...` (no `COALESCE` for `declaration_date`, `record_date`, `payment_date`; updates amounts/frequency/currency/feed/amount_feed/concept/retrieved_at/is_special from `EXCLUDED`).
  - Loader appends rows to `insert_rows` and executes `conn.execute(DIVIDEND_UPSERT, insert_rows)` as a batch; **no in-batch deduplication on `(security_id, ex_dividend_date, provider)` was found** in the inspected load/insert path.
  - Related logic exists for collapsing/merging/superseding feed rows in-memory and by delete ranges, but persisted identity remains constrained by the PK omitting `feed`.

**Assessment:**
- **Feed contract:** because PK omits `feed`, different feeds under the same provider/event key cannot both be stored as distinct PK rows; persisted evidence may depend on overwrite/supersession behavior. This confirms the structural issue recorded in `FR-DIV-01`/`RK-10`.
- **NULL overwrite:** unconditional assignment from `EXCLUDED` for date fields confirms `FR-DIV-04`/`DA-05` risk.
- **Batch duplicate behavior:** without in-batch dedupe, two rows with the same `(security_id, ex_dividend_date, provider)` in one batch upsert can trigger PostgreSQL "ON CONFLICT DO UPDATE command cannot affect row a second time" behavior; runtime behavior was **not verified** (would require a controlled write test). Silent keep is not indicated by inspected code.

**Status:** **Structural contract issues confirmed from repo evidence.** Batch runtime outcome remains **unverified without controlled write test** (`DA-21`).

**Traceability:** `UNK-005`, `DA-21`, `FR-DIV-01`, `FR-DIV-04`, `FR-DIV-05`, `DA-05/06`, `PA-D08`, `RK-10`, `TSK-019`, `DG-02/05/06`.

## Cross-cutting notes
- These findings support M2 spec/plan inputs but do not resolve external decisions or states outside inspected evidence.
- No source, test, config, or database state was modified (DB access was read-only).

## UNK-001 — Raw close basis / adjusted_close (additional DB evidence)

**Question:** are stored `raw.market_data.close` values split-adjusted/unadjusted consistently; can `adjusted_close` be used?

**Evidence (read-only DB, 2026-11-15):**
- `raw.market_data`: **9,823,774 rows**, `adjusted_close` non-null **0**.
- Sample split with nearby prices: `raw.corporate_actions` security `cdb3b2a3-0f9e-5bb4-8ed3-e2852d940c3e`, `effective_date 2026-11-09`, `ratio 5`. Prices (provider OPENBB): 2026-11-03 close 2.50, 2026-11-04 2.46, 2026-11-05 1.91, 2026-11-06 2.16, 2026-11-09 1.75; `adjusted_close` NULL for all rows.

**Assessment:** No stored adjusted-close series exists in `raw.market_data` for sampled/current data. The sample around a split shows close-level discontinuity with no populated adjusted close, consistent with prior recovery finding that adjustment is not materialized in raw prices; however, canonical basis and whether this sample represents split-adjusted vs unadjusted provider closes cannot be concluded from this single case without provider-basis confirmation.

**Status:** **Additional evidence gathered (partial).** Canonical raw-close basis remains unresolved.

**Traceability:** `UNK-001`, `FA-U01`, `FR-ADJ-01`, `PA-P01/02`, `RK-05`, `TSK-021`.

## UNK-002 — Dividend amount basis (additional DB evidence)

**Question:** are Yahoo/OpenBB/FMP/SEC dividend amounts split-adjusted per event/security as assumed?

**Evidence (read-only DB, 2026-11-15):**
- Provider/feed totals: `OPENBB/yfinance 176,396`, `SEC_XBRL 126,453`, `OPENBB/fmp 20,783`.
- `amount` vs `adjusted_amount`: `OPENBB/yfinance` 176,396 rows differ (total 176,396), sampled rows have `adjusted_amount NULL` with non-null `amount`; `OPENBB/fmp` 20,515 equal and 268 differ (sample differs e.g. amount 0.1275 vs adjusted_amount 0.6375); `SEC_XBRL` 126,453 rows have `adjusted_amount NULL` and `amount` non-null (all neither equal nor non-null-different in the null-adjusted sense).
- 307,046 dividend rows have at least one null among `declaration_date`, `record_date`, `payment_date`.

**Assessment:** Stored amount/adjusted-amount semantics differ materially by provider/feed (and NULL adjusted values are common, especially yfinance/SEC_XBRL samples). This reinforces basis/provenance ambiguity but does not establish the true external provider basis per event; reconciliation against provider payload/split events is still required.

**Status:** **Additional evidence gathered (partial).** Provider basis/adjustment correctness remains unresolved.

**Traceability:** `UNK-002`, `FA-U03`, `FR-DIV-08`, `PA-D14`, `RK-05/10`, `TSK-019/021`.
## UNK-001 — Raw close basis / adjusted_close (follow-up DB evidence)

**Additional evidence (read-only DB, 2026-11-15):**
- `raw.market_data`: 9,823,774 rows total, 0 with non-null `adjusted_close`.
- `raw.corporate_actions` split sample with nearby prices: security `cdb3b2a3-0f9e-5bb4-8ed3-e2852d940c3e`, `effective_date 2026-11-09`, `ratio 5` (numerator 5, denominator 1). `raw.market_data` closes (OPENBB): 2026-11-03 2.52, 2026-11-04 2.46, 2026-11-05 1.91, 2026-11-06 2.16, 2026-11-09 1.75; `adjusted_close` NULL for all sampled rows. The series shows a discontinuity around the split date but the canonical provider basis/convention cannot be concluded from this sample alone.

**Assessment:** Confirms absence of materialized adjusted closes and presence of split-adjacent raw close discontinuity in sample. Canonical raw-close basis remains unresolved (`FA-U01`).

**Status:** **Partial evidence gathered; unresolved.**

## UNK-002 — Dividend amount basis (follow-up DB evidence)

**Additional evidence (read-only DB, 2026-11-15):**
- Provider/feed totals: `OPENBB/yfinance 176,396`, `SEC_XBRL 126,453`, `OPENBB/fmp 20,783`.
- `adjusted_amount` null/not-null by provider/feed: `OPENBB/yfinance` 176,396 null / 0 not-null; `SEC_XBRL` 126,453 null / 0 not-null; `OPENBB/fmp` 0 null / 20,783 not-null.
- `amount` vs `adjusted_amount`: `OPENBB/yfinance` 176,396 differ (all sampled cases have `adjusted_amount NULL`); `OPENBB/fmp` 20,515 equal, 268 differ (sample: amount 0.1275 vs adjusted_amount 0.6375); `SEC_XBRL` has `adjusted_amount NULL` for all 126,453 rows.
- Date completeness: 307,046 dividend rows have at least one null among `declaration_date`, `record_date`, `payment_date`.

**Assessment:** Stored basis/provenance fields are heterogeneous by provider/feed and frequently incomplete (especially adjusted amounts/dates), reinforcing basis ambiguity and PIT/quality risks; external/provider reconciliation still required (`FA-U03`).

**Status:** **Partial evidence gathered; unresolved.**

## UNK-003 — Survivorship magnitude (observable proxies)

**Question:** quantify survivor-vs-PIT delta (`BI-01`).

**Evidence (read-only DB, 2026-11-15):**
- `reference.securities`: 1,708 inactive securities total; 0 rows with `delisted_date` populated.
- `model.scores` joined to `reference.securities`: 464,691 score rows / 5,133 securities total; 1,332 rows / 29 securities are currently inactive.
- `model.features` joined to `reference.securities`: 1,507,383 feature rows for currently inactive securities.
- No PIT membership interval table/evidence available to compute true historical eligibility or return/performance delta.

**Assessment:** Current-state inactivity intersects historical outputs (notably in features), but these counts do not measure survivor-vs-PIT bias magnitude or historical universe exclusion/inclusion effects. True delta remains blocked by `FR-UNI-01`/RM-01 PIT membership design and data.

**Status:** **Proxy evidence gathered; magnitude unresolved (blocked).**

**Traceability:** `UNK-003`, `BI-01`, `FR-UNI-01`, `NFR-PIT-02`, `RK-01`, `TSK-016`.

## UNK-007 — External systems/state inventory

**Question:** scheduler/object-store/backup/restore/provider audit-log state outside repo.

**Evidence:** Inspected repository, config, compose, CI, SQL, scripts and local DB snapshot only. No authoritative evidence of external scheduler configuration/state, object-store/archive retention, backup/restore procedures/results, or provider-side audit logs was found in-scope.

**Assessment:** Unknown remains external to repository evidence; requires operational inventory and access.

**Status:** **Unresolved (outside inspected scope).**

**Traceability:** `UNK-007`, `RK-13`, `NFR-REPRO-04` (scope limit), `TSK-004`, `DEC-001`.
