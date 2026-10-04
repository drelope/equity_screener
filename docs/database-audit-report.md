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