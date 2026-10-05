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
- **`preferred.contract_terms` has 2 rows.** Contract-document mining has effectively never run at scale. Both rows were verified correct rather than normalized, so the coverage gap — not a data defect — is what remains. Separately, `reference.securities.security_name` is the issuer name for preferreds (`ACRES Commercial Realty Corp.` for both `ACR-PC` and `ACR-PD`), so `series_pattern_from_security` has to fall back to the ticker suffix to tell the series apart; naming the series in `security_name` would make per-series scoping reliable.
- **`classification_evidence` is NULL for 5 payers.** They were the five unevidenced `TRUE` duplicates, now deactivated by V0034, so no active payer lacks evidence. No evidence was fabricated for them.
- **Five inactive `dividend = TRUE` rows remain.** These are the V0034 exceptions above; the unique key is occupied by their valid `FALSE` siblings, so they cannot be re-flagged without deleting or re-keying the survivors.
- **Five `dividend_last_paid` values are in the future** (`MTEX` 2108-11-14; `SQFT`, `SQFTP`, `SQFTW`, `UBSI` 2026-12-31). The dividend-concept match is broad enough to admit dividend-payable and forward-dated facts, and `ENFORCE_DIVIDEND_RECENCY` is `false`, so nothing rejects them. Quarantined in `audit.quarantined_values` by V0038 — left in place, recorded, and unreachable from the composite — rather than silently altering the dividend universe. Matcher fix is backlog item 1.
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

Ordered by risk. None of these block a publish.

1. **Narrow the dividend-concept matcher** in `sec_client.classify_companyfacts()` so
   dividend-payable and forward-dated facts stop setting `dividend_last_paid`. This
   changes the dividend universe, so it needs its own reviewed run — not a fold-in to
   any other migration. Afterwards, re-extract and set `resolved_at` on the five
   `audit.quarantined_values` rows.
2. **Resolve the 61 duplicate active `(cik,ticker)` pairs.** All are
   `dividends = [true, true]` with differing `security_type`. Whatever merges them must
   decide which `security_id` survives, and that decision propagates into
   `preferred.security_terms` and `model.*`, so it wants a migration of its own.
   `validate_securities_reference_fk` already rejects them, which is what keeps a full
   stage re-run unsafe until this is settled.
3. **Clear the five inactive `dividend = TRUE` exceptions.** The unique key is occupied
   by their valid `FALSE` siblings, so they need deleting or re-keying rather than a
   flag update.
4. **Decide `model.scores` pruning semantics.** Upsert-without-delete means a security
   whose composite goes NULL keeps a stale same-date row. Dormant now; worth a decision
   before a run where it is not.
5. **Prefer naming the series in `reference.securities.security_name` for preferreds.**
   Both `ACR-PC` and `ACR-PD` currently carry the issuer name, so
   `series_pattern_from_security` has to fall back to the ticker suffix to scope
   per-series extraction.
