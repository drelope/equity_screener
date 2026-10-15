# Dividend Pipeline Database Audit

**Audit date:** 2026-10-02  
**Database:** `dividend`  
**Method:** Read-only catalog, constraint, data-quality, and PostgreSQL usage-stat queries. Reproducible queries are in [sql/audit_database.sql](../sql/audit_database.sql).

**Remediation update:** V0028 added the audited FK indexes, V0029 applied dividend recency, and V0030 added corroborated dividend-yield units. One redundant index was removed. A later pass added V0033 (prune pre-fix audit snapshots), V0034 (inactive dividend-flag cleanup), V0035/V0036 (restore `dividend_last_paid`), and V0037 (index `model.features(as_of_date)`). Current classification and unit results are listed below.

## Executive Summary

The database has a sound raw-to-clean-to-reference architecture, migration tracking, explicit provenance, and broad table/column documentation. The clean company-profile and officer tables are populated and preserve the source payload; the officer compensation data preserves the distinction between undisclosed (`NULL`) and zero.

The remaining risks are source-level identity/classification alternatives and provider-native ratio semantics. All FK index gaps identified in the baseline audit are closed, and dividend-yield units now have a corroborated normalized field. No tables or source rows were removed during this audit.

## Verified Findings

| Area | Finding |
|---|---|
| Database size | Approximately 12 GB at audit time. `raw` is about 8.1 GB, `model` 3.7 GB, and `fundamentals` 598 MB. |
| Schema footprint | 30 project-owned relations; zero missing table or column comments. No application-defined PostgreSQL routines are present. |
| Constraints | 30 primary keys, 5 unique constraints, 25 foreign keys, and 17 check constraints. |
| FK validation | One FK is `NOT VALID`: `reference.securities(ticker, cik) → raw.company_ticker(ticker, cik)`. This is intentional for the bulk load; `populate_reference_tables` validates it at the end of the stage. |
| FK index coverage (before V0028) | 13 FKs had full leading indexes, one nullable FK was supported by a partial index, and 11 had no leading child index. |
| Raw profile grain | 5,764 `raw.ticker_profile` rows represent 5,764 security IDs and 5,333 tickers. There are 431 repeated `(CIK, ticker)` groups, each with distinct reference security IDs and conflicting classifications; these are not duplicate profile rows safe to delete. |
| Clean ticker profile | 5,333 normalized rows represent all 5,764 raw profile rows. 431 lower-ranked security-type alternatives remain in provenance; zero groups have a tie at the highest evidence rank. The current type-scoped rebuild has zero liquidation-preference conflicts within the selected security type. |
| Company profiles | 5,117 company rows and 34,890 officer rows. All 143 source scalar fields are typed; epoch values are normalized to UTC date/timestamp columns, and `52_week_change` is exposed as `pct_change_52w`. |
| Dividend-yield units | 2,135 rows have a corroborated normalized `dividend_yield_fraction`: 2,133 percent-point inputs and 2 fractional inputs. 90 values are ambiguous/unverified and retain no normalized fraction. ABR normalizes from 25.34 percent points to 0.2534 using annual dividend / current price corroboration. |
| Officer compensation | 19,056 officer rows have `total_pay IS NULL`; zero rows have a reported zero. This preserves the source distinction. The NULL-aware natural-key constraint has zero existing collisions. |
| Leverage tag | 394 company profiles meet the generated `EQUITY` + `real-estate` exemption tag. The tag is informational and does not currently alter C2/C3 scoring. |
| Usage counters | Largest observed relations include `raw.market_data` (~8.1 GB), `model.features` (~3.7 GB), and `fundamentals.periodic_financials` (~598 MB). `audit.source_lineage` showed 56,141 sequential scans versus 2 index scans in the sampled cumulative stats. The database stats view had no reset timestamp; low/zero index scans are therefore not sufficient evidence to drop an index. |

## Recommendations

### High Priority

1. **FK child indexes — implemented in V0028.** Added leading indexes to `audit.source_lineage.security_id`; `clean.company_profile.reference_security_id` and `source_profile_security_id`; `clean.ticker_profile.issuer_id` and `security_id`; `model.predictions.security_id`; `preferred.contract_terms.source_document_id`; `preferred.security_terms.source_document_id`; and `reference.securities`' issuer, exchange, and `(ticker, cik)` references. The nullable `raw.sec_documents.security_id` FK remains covered by its non-NULL partial index.
2. **Review retained classification alternatives.** The clean classifier now prioritizes active rows and stronger evidence, and only flags ties at the best evidence rank. The 431 losing classifications remain in `metadata_conflicts`/`source_profiles`; review them against filings before changing source reference rows.
3. **Keep the deferred FK validation visible.** Retain the current bulk-load pattern, but ensure the full reference ETL stage always validates `fk_securities_company_ticker`; partial runs must not be reported as a complete referential audit.

### Medium Priority

4. **Extend unit contracts carefully.** `dividend_yield_fraction` is now populated only when source yield agrees with annual dividend / current price under either fraction or percent-point interpretation. Other provider ratios remain source-native; add canonical columns only after their source contracts are verified, not by magnitude-only scaling.
5. **Review lineage query plans.** The source-lineage sequential-scan count is high relative to its row count. V0028 added the FK lookup index on `security_id`; confirm actual consumer query patterns before adding `(security_id, field_name)` or `field_name` indexes. Recheck plans and write cost after deployment.
6. **Review large fact/feature scans and analyze cadence.** `raw.companyfacts` and `raw.sec_submissions` show many sequential scans, which may be intentional full-universe sweeps. Use the audit SQL and `EXPLAIN` to distinguish designed scans from missing CIK indexes; keep statistics current on `raw.dividend_data`, `model.features`, and `fundamentals.periodic_financials`.
7. **Treat zero-use indexes as candidates, not cleanup targets.** Check server/statistics age and scheduled workload before dropping any index, especially the 48 MB fundamentals index and migration-era lookup indexes.

### Ongoing Controls

8. Run `python -m scripts.migrate --check` before ETL and preserve the one intentional `NOT VALID` constraint's post-load validation step.
9. Keep `raw.*` as source/audit data and `clean.*` as rebuildable typed outputs. Do not describe or remove the raw profile table as a legacy table.
10. Continue testing epoch seconds and milliseconds, NULL-versus-zero handling, officer uniqueness, and generated leverage tags whenever the provider payload mapping changes.

## Scope Notes

This is a schema and operational audit, not a financial validation of every vendor value. PostgreSQL usage statistics are cumulative and had no `stats_reset` timestamp in this audit; findings about scan counts are directional. Index recommendations require query-plan confirmation before implementation.

## Remediation Status

V0028, V0029, and V0030 are applied and `scripts.migrate --check` is clean. The latest FK audit reports **25 FKs: 24 with full leading indexes, 1 with a valid nullable partial index, and 0 without an index**. The duplicate `idx_periodic_financials_security_filed` index (48 MB, zero recorded scans) was dropped; the identical `periodic_financials_filed_idx` remains (86 MB, 11,023 recorded scans). Remaining work is source-backed review of the 431 lower-ranked classification alternatives, corroborating units for other provider ratios, and plan-guided review of lineage/fact scans.

---

# Universe-Scoped Data Quality Audit

**Audit date:** 2026-10-04 (data quality snapshot), 2026-10-02 (model output)
**Scope:** Every table carrying a `security_id`, checked for rows attached to securities that are no longer active. Method: read-only catalog queries for table inventory, plus per-`as_of_date` breakdowns.

## Executive Summary

No live universe leak exists. Every dated table has **zero rows for inactive securities at its latest `as_of_date`**, so all published current-state output is correctly scoped to the active universe. The inactive rows that remain are point-in-time history in dated tables, or landing-zone/reference data in undated tables, and are correct to retain.

One genuine coverage gap remains: **389 of 6,007 active dividend payers (6.5%) have no row in the latest `model.scores` or `model.rankings`** and therefore cannot be scored. Carry-forward has since been implemented and, as documented below, it closed none of this gap: the securities it made readable are too thin to clear the coverage floor.

## Inactive-Security Inventory

| Table | Rows | Inactive | Latest `as_of` | Inactive at latest | Assessment |
|---|---|---|---|---|---|
| `model.features` | 8,537,438 | 275,613 | 2026-10-02 | **0** | Point-in-time history |
| `raw.market_data` | 9,274,415 | 275,613 | n/a | n/a | Landing zone |
| `fundamentals.periodic_financials` | 1,253,679 | 26,181 | `period_end` | n/a | Statement history |
| `model.scores` / `rankings` / `predictions` | 21,392 each | 958 | 2026-10-02 | **0** | 4 `as_of` dates; inactive only in the 3 older ones |
| `raw.ticker_profile` / `raw.sec_documents` | 6,382 / 6,377 | 370 / 370 | n/a | n/a | Landing zone |
| `preferred.security_terms` | 1,288 | 257 | n/a | n/a | Reference enrichment |
| `preferred.dividend_snapshot` | 907 | 103 | n/a | n/a | Reference enrichment |
| `clean.ticker_profile` | 5,951 | 0 | n/a | n/a | Clean |
| `audit.data_quality` | 10,681 | 0 | 2026-10-04 | **0** | Clean |
| `audit.source_lineage` | 30,768 | 0 | n/a | n/a | Clean |
| `raw.companyfacts` / `raw.dividend_data` / `preferred.contract_terms` | — | 0 | n/a | n/a | Clean |

Orphan check (rows whose `security_id` is absent from `reference.securities`): **zero in every table**.

`model.features` shows the expected point-in-time signature for correct behaviour: the inactive count rises monotonically from 148 on 2022-10-31 to 321 on 2026-10-01, because each historical date retains the securities that were active when it was captured and have since been deactivated. This is why these rows must not be pruned — doing so would destroy the backtest history. The distinction from `audit.data_quality` is that a quality snapshot describes the *current* universe, whereas a feature row is keyed to the universe as it stood on its `as_of_date`.

## Finding: unscoreable payers (carry-forward attempted; did not close the gap)

`model.features` emits a row for a security only when it has an observation inside the feature window, and both consumers used to read only `MAX(as_of_date)`, so a security whose newest print was a few days old was dropped entirely rather than scored on its last known price.

| Bucket | Securities |
|---|---|
| Priced on the latest date, scored | 5,618 |
| Priced 1–7 days earlier, **not** scored | 113 |
| Priced 7–30 days earlier, **not** scored | 32 |
| Priced 30–90 days earlier, **not** scored | 9 |
| Priced same day, **not** scored | 1 |
| No market data at all | 239 |
| **Total unscoreable** | **394** |

Market data itself is fresh: `raw.market_data` holds 5,619 rows on 2026-10-02 and ~5,600–6,000 on every recent trading day, and 5,619 of the 5,773 priced payers have a same-day print. The gap is in feature assembly, not ingestion.

### Carry-forward: implemented, and it changed no scores

`feature_carry_forward_days` (default 7) now makes both consumers read each security's most recent feature row inside the window instead of one global date; `src/crispdm/feature_window.py` holds the query so the two cannot drift. Set it to 0 for the old behaviour.

It works as designed and it did not help:

| | Rows read | Composite scores | Unscoreable |
|---|---|---|---|
| Strict common date | 5,618 | 5,618 | 394 |
| Carry-forward, 7d | 5,732 | 5,618 | 389 |

All 114 securities newly in scope produced a **NULL** composite: their present inputs fall below `MIN_PRESENT_WEIGHT` (50% of total weight), so `score_rank` declines to score them. The 5-row improvement is from V0034 deactivating five securities, not from carry-forward.

The conclusion is that this was never a date-plumbing problem. Of the 394, 239 have no `raw.market_data` at all and no window can help them; the other 155 are readable but too thin to clear the coverage floor. Closing the gap means either denser inputs or a lower floor, and lowering `MIN_PRESENT_WEIGHT` changes composite methodology and the rankings, so it is not a mechanical fix.

**Decision: leave them unscored.** The floor stays where it is, carry-forward stays at 7 days, and the 389 stay out of the published universe. Carry-forward is retained because it is the correct read semantics and costs nothing, not because it fixed anything.

Separately, `model.scores` is upsert-only and never pruned, so a security whose composite goes NULL keeps its previous same-date row and `predictions` and `scores` then disagree about the run. This run left 0 such rows, so the hazard is dormant; accepted as-is for this publish.

## Fixed during this audit

| Finding | Resolution |
|---|---|
| `audit.data_quality.recency` was unclamped, so 5,951 rows scored above 1.0 (max 1.0010) because `as_of` is midnight while rows are retrieved later the same day | Clamped with `LEAST(1.0, GREATEST(0.0, …))` on both branches. `max(recency)` is now 1.0 with zero components outside `[0,1]`. `quality_score` was never affected because its weights sum to 1. |
| `audit.data_quality` held 78,716 rows over 8 dates; 6,152 belonged to inactive securities and inflated completeness/quality averages over a universe the pipeline no longer processes | V0033 deleted the 7 pre-fix dates (68,035 rows), retaining only the 10,681-row 2026-10-04 snapshot, then regenerated so it carries the clamped values. Those snapshots had a different denominator and were not comparable to the corrected ones. No archive table, by design. |
| 370 inactive securities carried `dividend = TRUE` | V0034 set them to `FALSE`. Five unevidenced `TRUE` duplicates (`BTLN`, `OCAC`, `OCAC-RI`, `OCAC-UN`, `OCAC-WT`) were deactivated instead of re-flagged: four collided with `ux_security_cik_ticker_type_dividend`, and their existing `FALSE` siblings are the valid rows. Active payers 6,012 → 6,007; duplicate active `(cik,ticker)` pairs 66 → 61. |
| `dividend_last_paid` was NULL for all 6,012 active payers | Root cause was V0035's cache column gap, not the writer: `classify_companyfacts()` returned the key, the cached branch of `populate_securities` dropped it, and with the column never populated a re-run could not recover it. V0035 added `raw.company_classification.dividend_last_paid` and V0036 backfilled it from the already-persisted `dividend_facts` (no network). All 6,007 active payers now carry a value, mirrored into `classification_evidence`. |
| Every `MAX(as_of_date) FROM model.features` was a full scan of 8.5M rows | V0037 added `idx_features_as_of`. The carry-forward query went from 28s / 42.7M buffer hits (a correlated `MAX`, which the planner de-correlated into a join across every feature row) to 54ms via a per-security `LATERAL … ORDER BY as_of_date DESC LIMIT 1` on `features_pkey`. |
| The two `preferred.contract_terms` rows looked inconsistent — one had `first_call_date` + a schedule, the other NULL + `[]` | Not an inconsistency, and no change was made. Re-extracting both from the stored document text reproduces every stored field exactly (Series D is callable from 2026-05-21; Series C is redeemable at any time, so it has no date). The apparent mismatch was a real difference between the two series. |

## Open, not acted on

- **`dividend_last_paid` is NULL for all 6,012 active payers.** Resolved by V0035/V0036; see the table above.
- **`preferred.contract_terms` has 2 rows.** Contract-document mining has effectively never run at scale. Both rows were verified correct rather than normalized, so the coverage gap — not a data defect — is what remains. *(Update, 2026-10-13: mining now runs at scale — stage 5b re-mines every active preferred and the table holds 212 rows over 612 active preferreds, 196 with a liquidation preference and 116 with a call price. A third round fixed the *universe* itself: `classify_instrument` no longer lets issuer-level evidence (preferred dividend facts, an issuer name like "Preferred & Income Fund", a preferred-only concept bag) type the submissions **primary** symbol as preferred, so ~241 common classes (CNDT, ATLC, GRBK, MPLX, ET, the SPACs and preferred-income closed-end funds …) reclassified to `common_stock`, their mined terms were pruned, and terms that had been attached to the wrong ticker re-homed to the genuine preferred (`MPLX`→`MPLXP` $1,000, `ET`→`ET-PI` 9.1273). The extractor was hardened with depositary-share scaling and blank-check / value-definition guards, then a second round that drops non-per-share aggregate totals (values scaled by "million"/"billion", "in excess of" thresholds, or figures paired with a prior/next amount), clauses that negate liquidation rights, warrant/exercise-price figures (which also neutralises ~55 blank-check warrant documents mis-typed as preferred), and call candidates whose clause is an issuance purchase price; rows that yield nothing on re-mine are deleted and non-preferred rows pruned.)* Separately, `reference.securities.security_name` is the issuer name for preferreds (`ACRES Commercial Realty Corp.` for both `ACR-PC` and `ACR-PD`), so `series_pattern_from_security` has to fall back to the ticker suffix to tell the series apart; naming the series in `security_name` would make per-series scoping reliable.
- **`classification_evidence` is NULL for 5 payers.** They were the five unevidenced `TRUE` duplicates, now deactivated by V0034, so no active payer lacks evidence. No evidence was fabricated for them.
- **Five inactive `dividend = TRUE` rows remain.** These are the V0034 exceptions above; the unique key is occupied by their valid `FALSE` siblings, so they cannot be re-flagged without deleting or re-keying the survivors.
- **Five `dividend_last_paid` values are in the future** (`MTEX` 2108-11-14; `SQFT`, `SQFTP`, `SQFTW`, `UBSI` 2026-12-31). The dividend-concept match is broad enough to admit dividend-payable and forward-dated facts. `ENFORCE_DIVIDEND_RECENCY` was `false` when this was written and has been on since 2026-10-06 (see WS12 in `data-health-workstreams.md`), but a forward-dated period end still counts as recent, so these five remain quarantined in `audit.quarantined_values` by V0038 — left in place, recorded, and unreachable from the composite.
- **61 duplicate active `(cik,ticker)` pairs remain**, all `dividends = [true, true]` with differing `security_type`. `populate_reference_tables` would reject them (`validate_securities_reference_fk`), which is one reason a full stage re-run stays unsafe.
- **Preferred-term structure is sparse.** 1,015 of 1,022 active preferred payers have `preferred.security_terms` rows, but only 366 have a non-NULL `clean.ticker_profile.coupon_rate`. `preferred.issuer_terms` is issuer-level evidence and is deliberately not promoted into per-series clean columns.

## Publish decision (2026-10-04)

Today's scores are published **as-is, with no methodology change**. Everything below was
reviewed and explicitly accepted rather than deferred by omission:

| Item | Decision | Why it is safe today |
|---|---|---|
| 389 unscoreable payers | Leave unscored; do not relax `MIN_PRESENT_WEIGHT` | They fail on input density, not on scoring rules. Lowering the floor would change the composite and reorder the ranking to accommodate thin names. |
| 5 future `dividend_last_paid` values | Quarantined (V0038), kept in place | Nothing in the composite path reads the column — `build_features()` reads `raw.market_data` and `raw.dividend_data`. All five keep their scores, computed on the same inputs as anyone else. |
| 61 duplicate active `(cik,ticker)` pairs | Run allowed; cleanup scheduled | Hygiene, not correctness: the latest dated outputs carry zero inactive rows, so there is no cross-state contamination. |
| `model.scores` upsert-only | Accepted as-is | 0 stale same-date rows on this run, so the hazard is dormant. |
| Full reference-stage re-run | Not performed | The stage hardcodes `active = TRUE` and would reactivate the 370 rows V0034 just cleaned up. Staying incremental is the lower-risk path. |

Gate evidence for this publish: 480 tests passed, ruff clean, migrations to V0038 with
none pending, zero inactive securities at the latest score date, and a single
`model.predictions` run (`6bd1b6c4`).

## Incident: published scores destroyed by a test, then re-scored

Recorded because it changed the published numbers and because the cause is a
pattern worth not repeating.

`tests/test_score_pruning.py` exercised `prune_stale_run_rows()` — which issues a
real `DELETE` — inside `engine.begin()`. That context manager **commits on normal
exit**, and every assertion passed, so the transaction committed. The delete
removed **5,617 `model.scores` rows and 5,617 `model.rankings` rows at
`2026-10-02`**, leaving 1 row against 5,618 `model.predictions`: a passing test
run silently destroyed published state.

Two things made it worse than a single bad row:

- The test passed a *partial* `scored_sids` list, so the prune correctly deleted
  almost the entire date. The production call site passes the full frame, but the
  test did not exercise that contract.
- There was no backup, and the run was **not reproducible**: the one surviving row
  recomputed to `0.36862` against a stored `0.36975`. `score()` fills
  positionally (`ffill`/`bfill`), so V0039's 58 deactivations shifted fills for
  their neighbours. The old numbers were gone, not merely displaced.

Repair, by decision: `scripts/score_rank.py` was re-run **without**
`--prune-superseded`, so run `6bd1b6c4`'s 5,732 predictions were retained as the
audit trail alongside the new run.

| | before | after |
|---|---|---|
| published run | `6bd1b6c4` | `a94cdc58` |
| `model.scores` @ `2026-10-02` | 5,618 (5,467 scored) | 5,618 (5,395 scored) |
| scored composites | 5,467 | 5,395 |
| active payers | 6,007 | 5,946 |

The 72 fewer scored composites are **not** a methodology change and the floor was
not relaxed: all 223 unscored run-date rows sit below `MIN_PRESENT_WEIGHT`, with a
maximum coverage of `0.214` against the `0.5` floor. The reduction is the 58
V0039 deactivations plus 14 further rows whose positional fills moved across the
coverage boundary. `model.scores` rows at the run date (5,618) still match
`model.features` rows at that date exactly.

Post-repair verification: zero inactive securities and zero non-payers at the
latest score date, zero predictions without a score row, zero scored rows without
a ranking, and 499 tests passing.

The test itself was fixed to run inside an always-rolled-back transaction
(`_rolled_back_conn()`), so it cannot commit regardless of how it ends. Verified
inert by comparing `model.scores` and `model.predictions` totals either side of a
full suite run: unchanged at 5,618 and 27,636.

The general lesson: any test that calls a function issuing `DELETE` against the
live warehouse needs an explicit rollback, not a context manager that commits on
success.

### How quarantine works here

V0038 adds `audit.quarantined_values`, an append-only registry. The five values stay
in `reference.securities` — NULLing or deleting them would hide a real matcher defect
and destroy the evidence needed to verify the fix — and are recorded with the
predicate that found them (`dividend_last_paid > now()::date`). Resolution is recorded
by setting `resolved_at`, never by deleting the row. No constraint blocks ingestion: a
CHECK rejecting future dates would fail the classification write for the whole issuer.

The quarantine covers a *value*, not a *security*. Excluding those five from scoring
would have shrunk the published universe, which is the failure mode this audit has been
avoiding throughout.

## Maintenance backlog (next safe window)

Items 2, 3, 4 and 5 are closed (V0039–V0042). Item 1 is split: the part that was
safe is done, the part that changes the universe is not, and the reason is now a
measurement rather than a suspicion. None of these block a publish.

1. **Narrow the dividend-concept matcher** — **partially done, and the remaining
   part is deliberately deferred.**

   `DIVIDEND_FACT_TERMS = ("dividend", "distributionstoowners")` is matched as a
   substring, so it admits `DividendsPayableCurrentAndNoncurrent` and
   `CommonStockDividendsPerShareDeclared`. UBSI shows the concept list alone cannot
   fix this: `CashDividendsPaidToParentCompanyByConsolidatedSubsidiaries` says
   "Paid" and still carried period end `2026-12-31`.

   Done (V0040): `classify_companyfacts()` now clamps the running max to the run
   date, since a dividend cannot have been paid after it. The five impossible
   dates are corrected and their quarantine rows resolved. The flag did not move,
   so no score, prediction or ranking changed.

   **Deferred, with the number attached:** dropping the payable/receivable/declared
   families instead would clear `dividend` for **3,611 of the 8,105 cached CIKs**
   carrying `dividend_facts` — roughly 45% of the payer population. That is not a
   fold-in to any migration; it needs the reference-stage rebuild that is
   currently unsafe. Re-measure and decide then.

2. **Resolve the 61 duplicate active `(cik, ticker)` pairs** — **done (V0039).**
   They were never arbitrary collisions: each pair is one economic security
   described twice, because `security_type` was inferred from `security_name` and a
   re-classification minted a second row when the name or type changed. `ALTI`
   existed as both `common_stock` "Class A ordinary shares, par value …" and
   `preferred_stock` "AlTi Global, Inc.", so the same ticker was ingested,
   feature-built and scored twice. Survivor rule: keep the most recently created
   row in each group, which is the 2026-09-23 13:08 re-classification batch
   against older rows. Verified before applying: **none** of the 61 deactivated
   rows held a `composite_score` at the run date (their twin did, in every case),
   so the published universe is unchanged — `model.scores` at `2026-10-02` is still
   5,618 and active payers went 6,007 → 5,946. `validate_securities_reference_fk`
   should now pass on this population: `validate_securities_reference_fk()` with its
   default `check_active_identity_duplicates=True` was re-run and returned clean.
   That check was one of the things making a full reference-stage re-run unsafe, so
   this removes one of those blockers; the others are unchanged.

3. **Clear the five inactive `dividend = TRUE` exceptions** — **done (V0041).** Two
   structurally different cases, which is what made this look dangerous. `OCAC`
   has no same-key sibling, so it is a plain flag flip. `BTLN` and `OCAC-RI/UN/WT`
   each have an *active* `dividend = FALSE` sibling, so a flag update would violate
   `ux_security_cik_ticker_type_dividend`, and their `fundamentals.periodic_financials`
   rows all collide with the survivor's on `(period_end, fiscal_year, fiscal_period)`.
   Those counterparts were compared column by column: all 105 BTLN rows (3 each for
   the others) match on every value column, differing only in `security_id` and
   `retrieved_at` — the same figures re-extracted a day later. So the duplicate
   rows are deleted, while `clean.ticker_profile`, `raw.ticker_profile` and
   `audit.source_lineage` are *moved* to the survivor (it owned none, and these are
   the only rows holding the profile for that `(cik, ticker)`). `audit.data_quality`
   is deleted instead, because its PK is `(security_id, as_of_date)` and the
   survivor already has a row for that date. None of the four carried any
   `model.*` or `preferred.*` row, so no score could move.

4. **`model.scores` pruning semantics** — **decided and implemented.**
   `model.scores` and `model.rankings` are keyed by `(security_id, as_of_date)` and
   carry no `run_id`, so the upsert refreshed the rows it wrote and left every
   other row at that date untouched; a security that fell out of the frame kept its
   old `composite_score` and still looked scoreable. `model.predictions` never had
   this problem because it is keyed by `run_id`. `prune_stale_run_rows()` now
   deletes both tables at the **run date only**, before the upsert and inside the
   same transaction, so the surviving set is exactly what the run writes and a later
   failure rolls the prune back. Earlier dates are never touched: they are
   point-in-time history, and a re-run at the newest feature date must not delete
   the record of what a security scored on the day it actually scored.

5. **Name the series in `reference.securities.security_name` for preferreds** —
   **partially done (V0042), and the blocker is now identified.**
   All 1,327 active preferreds carried an issuer name with no series, so
   `series_pattern_from_security` could not see one. The obvious source,
   `preferred.security_terms.preferred_series`, is populated with **issuer names**:
   916 distinct values, **0** of which are a bare series letter, reading
   "FEDERAL HOME LOAN MORTGAGE CORP", "Public Storage", "BANK OF AMERICA CORP /DE/".
   The column name says series and the contents say issuer — that mis-population,
   not a missing join, is the real blocker. Four preferreds with an SEC instrument
   title naming a series (`NXDT-PA`, `IMPPP`, `NTRSO`, `ZIONP`) now use the filed
   title. The remaining 1,323 need the series parsed out of filings; `security_name`
   is a display label that no `model.*` table stores and no scoring path reads, so
   the 4 changes cannot move a score.

## Prediction retention: resolved with a view, not a deletion

The repair run in the incident section created the ambiguity this section settles.
`score_rank` was re-run without `--prune-superseded` so the old run's numbers
survived the recovery, which is the right call for an incident and the wrong steady
state: `model.predictions` is append-only across runs, so the latest date now holds
**two** complete sets, one per run, and nothing but `created_at` separates them.

It is not a cosmetic overlap:

- 9 runs, 27,636 prediction rows in total.
- `2026-10-02` holds 2 runs × 5,618 securities = 11,236 rows.
- Of the 5,618 securities present in both, **5,395 disagree on probability**. The
  5,395 that differ are exactly the 5,395 with a non-NULL composite: every scored
  security has two different published predictions.
- Earlier dates carry up to 7 runs each, for the same reason — a scoring-policy
  change forces every date to be recomputed.

An unfiltered query therefore returns an arbitrary run, which is what
`model.predictions`' own docstring warns about and what an incident of this class
makes expensive to guess at.

**Decision: add `model.current_predictions`; delete nothing.** Every superseded run
is the record of which model produced which number on which date, and the incident
above is a demonstration of how hard those numbers are to reproduce from the inputs
alone. Retention is now a policy question that can be answered later without
recovering anything, because the ambiguity that made deletion tempting is gone.

The view resolves per `(security_id, as_of_date)` — the most recent run that has a
row for that pair. Two migrations, because the first attempt was wrong in a way
worth recording:

- **V0043** resolved per *run*: newest `run_id` per `as_of_date`, all its rows.
  This passes any check that only looks at the latest date, where the newest run
  happens to be the widest. It is wrong at older dates, and visibly so. Feature
  carry-forward means each run writes a handful of rows at earlier `as_of_date`s, so
  the newest run shadowed the run beneath it: the view reported **20 rows** for
  `2026-10-01`, where 5,430 predictions exist. A consumer would have concluded most
  securities have no prediction on that date.
- **V0044** resolves per *security*, so a security the newest run did not touch
  keeps its newest available prediction instead of vanishing. Per-date row counts
  then equal `model.scores` for the same date on all 6 dates (5,430 / 4,909 /
  5,445 for `10-01` / `09-30` / `09-29`).

`tests/test_current_predictions_view.py` pins the per-security resolution against a
regression to the per-run form; reverting the view in place fails 2 of its 7 tests
with the shadowing condition named. It also asserts the view never omits coverage
that some single run had, and that `model.predictions` still holds runs the view
does not — so the audit trail cannot be quietly bought with a deletion.

## Closed: schema drift is now detectable, and the repository can rebuild itself

While mutation-testing the view above, `migrate --check` reported *"schema is up to
date; no pending migrations"* against a database whose view had just been replaced
with the broken definition. `scripts/migrate.py` compares only the
`schema_migrations` ledger, so it cannot see an object altered out of band, and it
will not re-apply a migration to repair one. The view had to be restored by
executing V0044's DDL by hand.

The fix is `scripts/check_schema_drift.py`, which builds a scratch database from
the repository — `sql/schema.sql`, `init_db.py`'s inline migrations, then V0001+ —
and diffs its catalog against the live one. It reports tables, columns, indexes,
constraints, views, enums and functions, keyed by name so a table's primary key,
foreign keys and checks cannot overwrite each other. It reads nothing from live
data, and the scratch database is dropped whatever happens.

The reference is a build rather than a checked-in expectation file on purpose. An
expectation file drifts too — this repository already had `sql/schema.sql` 51
objects behind, including every column added to `model.features` since V0015. A
build either reproduces the schema or it does not.

**Verified to fail, not just to pass.** Reverting `model.current_predictions` to
the V0043 definition in place makes the check exit 1 naming `viewdef
model.current_predictions` — the exact drift `migrate --check` missed. It currently
exits 0 with two accepted differences.

Building the reference is also what surfaced the two findings below. Neither is
visible to the ledger; both were sitting in the bootstrap.

### The bootstrap could not build a database

`scripts/init_db.py` runs `ALTER TABLE reference.securities DROP CONSTRAINT IF
EXISTS securities_pkey` unconditionally. On a database created from `schema.sql`
that drop fails: **17 foreign keys** into `reference.securities(security_id)` depend
on that index, so PostgreSQL raises `DependentObjectsStillExist` and initialization
aborts. Since `schema.sql` already declares `PRIMARY KEY (security_id)`, the swap
exists only for databases whose primary key was once `(cik, ticker)` — it was
unnecessary on a fresh build and fatal.

Confirmed by building a fresh database and running the statement verbatim: fails.
**Nobody can rebuild this database from the repository.** The migration is now a
conditional `DO` block that reads the existing primary key and swaps only when the
columns are not already `security_id`, so it stays a no-op on a fresh build and
still does its job on an old one. `tests/test_schema_drift.py` fails if the
unconditional form returns.

### `schema.sql` was missing an index that enforces the V0039 fix

`ux_security_cik_ticker_type_dividend` — the unique index that makes the V0039
duplicate fix hold — is created by `init_db.py`, not by `schema.sql`. A rebuild from
`schema.sql` plus migrations alone therefore produced **no such index**, and nothing
would have said so: the uniqueness that stops a re-classification minting a second
row for the same instrument would simply be absent. It is now declared in
`schema.sql`.

`schema.sql` also declared `ix_contract_documents_security_id`, an index name no
database ever had; V0028 created `ix_contract_documents_security`. A rebuild added
a duplicate index rather than the one that exists. Corrected.

### Two smaller alignments

- **V0046** validates `fk_securities_company_ticker`. `init_db.py` adds it `NOT
  VALID` so initialization cannot fail on unresolved ticker/cik pairs, which is the
  right trade there — but nothing ever validated it afterwards, so a rebuild
  produced a structurally different and weaker database. Live had it validated
  already, and `VALIDATE CONSTRAINT` is a no-op there.
- The `NOT VALID` marker is the only difference the FK had, which is why it surfaced
  at all: `pg_get_constraintdef` reports validation state, so the check compares it.

### Accepted, not fixed

`reference.securities_security_id_key` is a redundant `UNIQUE(security_id)`
alongside the primary key, on an 11,660-row table. It looks free to drop and is
not: `raw.market_data`'s foreign key was created against this index rather than
`securities_pkey`, so removing it means dropping that FK and re-validating it against
**9,274,415 rows** — a pair of `ACCESS EXCLUSIVE` locks on the largest raw table, to
save a duplicate index on a small one. Declared in `ACCEPTED_DIFFERENCES` with that
reason; the check prints accepted differences rather than hiding them, so the count
stays visible. The fix, for a maintenance window: re-point
`market_data_security_id_fkey` at the primary key, then drop this.

### Not wired into the nightly

`migrate --check` stays a cheap ledger check. The drift check builds a database and
costs roughly a minute, which is too expensive for every stage preflight; it is a
deploy-time gate run deliberately:

```
python -m scripts.check_schema_drift     # exit 0 = matches the repository, 1 = does not
```

---

# Raw/Clean Schema Audit

**Audit date:** 2026-10-15
**Scope:** Every `raw.*` and `clean.*` relation — catalog shape, comment coverage, FK
index coverage, data-quality probes, and the query patterns that read them. Method:
read-only catalog and data queries against the live `dividend` database, plus
`scripts/check_schema_drift.py` (a build of the repository diffed against live).

## Verified state

| Check | Result |
|---|---|
| Repository vs live | `check_schema_drift` exits 0; one accepted difference (`reference.securities_security_id_key`, unchanged from the 2026-10-02 audit) |
| Table comments | All 16 raw/clean base tables carry a comment; only the two clean views (`v_company_hierarchy`, `v_corporate_action_reference_exceptions`) have uncommented columns, which is why they carry a view-level comment instead |
| Column comments | Zero uncommented columns on every raw/clean base table |
| FK index coverage | All 11 raw/clean foreign keys have a leading child index; nulls-and-partial cases covered as before |
| Data quality | `raw.market_data`: 0 negative prices, 0 `high < low`, 0 negative volume, 0 future dates, 304/9.70M NULL closes. `raw.dividend_data`: 0 negative amounts, 0 future ex-dates. `clean.ticker_profile`: 0 coupon rates outside 0–100, 0 negative liquidation preferences. `clean.company_profile`: 0 negative market cap/employees/price |
| Orphans | 0 `security_id` orphans (unchanged) |

## Finding: `raw.market_data` had no index for date-only predicates — fixed (V0071)

`raw.market_data` is keyed `(security_id, observation_date, provider)`. Every access
that keys on the date rather than on a security therefore cannot be served by the
primary-key btree: PostgreSQL 17 has no skip scan (that arrives in 18), so the planner
reads the whole 836 MB PK index or sequential-scans the 3 GB table. Two such accesses
run on every feature build:

- `src/crispdm/features.py` runs `SELECT DISTINCT security_id, observation_date FROM
  raw.market_data WHERE close IS NOT NULL AND observation_date >= <start> AND
  observation_date < <end>` once per window, four times per build.
- `scripts/build_features.py` sizes each window with
  `SELECT min(observation_date), max(observation_date) FROM raw.market_data WHERE
  close IS NOT NULL`.

V0071 adds a **partial, covering** index so the DISTINCT probe is answered by an
index-only scan and min/max become index endpoints:

```
CREATE INDEX idx_market_data_observation_date
  ON raw.market_data (observation_date) INCLUDE (security_id)
  WHERE close IS NOT NULL;
```

| probe (live) | before | after |
|---|---|---|
| 1-day DISTINCT | 423 ms, 109,275 buffers | 3.5 ms, 43 buffers |
| 365-day DISTINCT | 2301 ms, 287,370 buffers (seq) | 1618 ms, 9,676 buffers |
| min/max window sizer | full scan | 0.2 ms (index endpoints) |

Index size 375 MB against a 3.08 GB table. Plain `CREATE INDEX` (not `CONCURRENTLY`),
because `migrate.py` runs one transaction per file; it is a single `ACCESS EXCLUSIVE`
pass over the largest raw table. Declared in `sql/schema.sql` as well, so a fresh build
and the migration converge.

## Finding: `schema.sql` declared an index twice — fixed

`ix_contract_documents_security` was declared twice in `schema.sql` (once under its
explanatory comment and again just below). The second was a leftover and a no-op
(`IF NOT EXISTS`), but two identical declarations invite a future edit to only one of
them. Removed.

## Reviewed and deliberately left in place

- **No CHECK constraints on `raw.market_data` / `raw.dividend_data` for OHLC shape or
  non-negative amounts.** The data would pass every candidate today, but on a raw
  landing table a single bad provider row would abort the whole issuer's ingestion —
  the same reasoning that kept a future-date CHECK off `reference.securities` in the
  2026-10-02 audit.
- **`clean.company_officer` carries two foreign keys into `clean.company_profile`**
  (`(symbol, parent_name)` and `profile_id`), both `ON DELETE CASCADE`. Redundant but
  harmless; the surrogate `profile_id` path is the one the loader actually rebuilds on.
- **`clean.company_profile.cik`** has a supporting index but no format CHECK or FK;
  `clean.corporate_action.security_id` intentionally has no FK (nullable, and the row
  must survive reference churn).
- **CIK width is inconsistent across raw tables** (`VARCHAR(10)` on `company_ticker`
  and `clean.ticker_profile`, `VARCHAR(20)` elsewhere). Cosmetic; all values are short.
- **`raw.ticker_profile` column order is jumbled** (`field_sources` last, `sector`
  mid-table) from successive `ALTER TABLE ... ADD COLUMN`. Cosmetic; not worth a
  table rewrite.

Gate for this audit: `migrate --check` and `check_schema_drift` clean, ruff clean,
1066 tests pass, working tree clean.

---

# Market/Reference Data Storage Efficiency Audit (2026-10-15)

Follow-up pass on the size and write-cost of the raw market-data and reference-data
structures.

## Finding: nightly re-fetch rewrote unchanged JSONB payloads — fixed

`raw.companyfacts`, `raw.sec_submissions`, `raw.company_taxonomy` and
`raw.sec_documents` advance `retrieved_at` on every re-fetch (it is the freshness
clock the audit reads) but also unconditionally rewrote the full JSONB payload,
even when `content_hash` proved it had not changed. For `raw.companyfacts` that
copied a ~1.8 MB payload into fresh TOAST chunks on every run, leaving the previous
copy dead: a **4.5 GB TOAST relation for 2.2 GB of live payloads**.

Fixed by guarding the payload columns with `CASE WHEN <table>.content_hash IS
DISTINCT FROM EXCLUDED.content_hash THEN EXCLUDED.<col> ELSE <table>.<col> END`, so
`retrieved_at` still advances but the stored payload (and its TOAST chunks) is
reused when identical. Verified on a scratch table: repeated identical upserts grow
the TOAST relation 0.2 MB → 1.7 MB unguarded and hold flat at 0.2 MB guarded.

`raw.company_classification` is left unguarded on purpose: its `content_hash` covers
only `dividend_facts`, so a guard keyed on it would skip legitimate changes to the
other columns.

Commit: `perf(raw): avoid rewriting unchanged JSONB payloads on upsert`.

## Reclaimed existing bloat

`VACUUM (FULL, ANALYZE) raw.companyfacts` reclaimed **2.24 GB** (4.59 GB → 2.36 GB,
−49%) in 15 s; the TOAST relation now equals the live payload size. Database total:
**14 GB → 12 GB**.

## Reviewed and deliberately left in place

- **`raw.market_data.adjusted_close` is 100% NULL** on all 9.7M rows — the only
  provider is `OPENBB`, which never supplies it. A dead column, but NULLs occupy
  only the null bitmap, so dropping it frees no meaningful space while risking a
  break if another provider starts populating it. Recorded, not changed.
- **`raw.market_data` price columns are unbounded `NUMERIC`** (split-adjusted values
  carry up to 20 decimal places). `NUMERIC` stores by actual digits, so a typmod
  would not shrink storage; `double precision`/`real` would, at the cost of exact
  decimal semantics on a raw landing table. Left as `NUMERIC`.
- **`model.features.idx_features_price_quality`** (221 MB, 3 scans) and
  `idx_features_as_of` (351 MB, 1129 scans). Not dropped: too little uptime to call
  either unused with confidence, and dropping the wrong one costs a table-sized
  reindex.
- **`reference.securities.securities_security_id_key`** (2.3 MB, 0 scans) is the
  redundant UNIQUE already tracked in `check_schema_drift.ACCEPTED_DIFFERENCES`;
  `raw.market_data`'s foreign key is built against it, so dropping it means
  re-validating that FK across 9.7M rows. Left.

Gate for this pass: ruff clean, 1073 tests pass, working tree clean.


