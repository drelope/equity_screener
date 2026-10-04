# Dividend Pipeline Database Audit

**Audit date:** 2026-10-02  
**Database:** `dividend`  
**Method:** Read-only catalog, constraint, data-quality, and PostgreSQL usage-stat queries. Reproducible queries are in [sql/audit_database.sql](../sql/audit_database.sql).

**Remediation update:** V0028 added the audited FK indexes, V0029 applied dividend recency, and V0030 added corroborated dividend-yield units. One redundant index was removed. Current classification and unit results are listed below.

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

One genuine coverage gap was found: **394 of 6,012 active dividend payers (6.5%) have no row in the latest `model.features`, `model.scores`, or `model.rankings`** and therefore cannot be scored.

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

## Finding: 394 payers are unscoreable

`model.features` emits a row for a security only when it has an observation inside the feature window. There is no last-observation carry-forward, so a security whose newest print is a few days old is dropped entirely rather than scored on its last known price.

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

Fixing this requires a decision, not a mechanical change: carrying a stale price forward changes model inputs, so it requires rebuilding `model.features` and re-running `score_rank`, and it interacts with the stale-price question that recency enforcement (`ENFORCE_DIVIDEND_RECENCY`, currently `false`) would otherwise answer. Left open pending that decision.

## Fixed during this audit

| Finding | Resolution |
|---|---|
| `audit.data_quality.recency` was unclamped, so 5,951 rows scored above 1.0 (max 1.0010) because `as_of` is midnight while rows are retrieved later the same day | Clamped with `LEAST(1.0, GREATEST(0.0, …))` on both branches. `max(recency)` is now 1.0 with zero components outside `[0,1]`. `quality_score` was never affected because its weights sum to 1. |
| `audit.data_quality` held 78,716 rows over 8 dates; 6,152 belonged to inactive securities and inflated completeness/quality averages over a universe the pipeline no longer processes | V0033 deleted the 7 pre-fix dates (68,035 rows), retaining only the 10,681-row 2026-10-04 snapshot, then regenerated so it carries the clamped values. Those snapshots had a different denominator and were not comparable to the corrected ones. No archive table, by design. |

## Open, not acted on

- **`dividend_last_paid` is NULL for all 6,012 active payers.** The R1 writer exists but the reference stage has not been re-run since it was added. Inert today because no consumer reads the column; populating it requires lifting the hold on that stage.
- **`preferred.contract_terms` has 2 rows.** Contract-document mining has effectively never run at scale.
- **`classification_evidence` is NULL for 5 active payers.**
- **370 inactive securities still carry `dividend = TRUE`.** The accepted consequence of keeping recency enforcement dark: a deactivating security keeps its dividend flag until enforcement is switched on.
- **Preferred-term structure is sparse.** 1,015 of 1,022 active preferred payers have `preferred.security_terms` rows, but only 366 have a non-NULL `clean.ticker_profile.coupon_rate`. `preferred.issuer_terms` is issuer-level evidence and is deliberately not promoted into per-series clean columns.