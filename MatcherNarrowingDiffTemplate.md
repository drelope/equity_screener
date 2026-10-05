# Matcher Narrowing Diff Template

Compares two versions of the security-classification matcher (A = current, B = narrowed). The matcher is `classify_security_type` plus the dedupe logic that produces `reference.securities` rows.

## 0. Run Conditions (record before diffing)

- Matcher A version / commit: ______  Matcher B version / commit: ______ (fill per run)
- Same input data for both runs (same raw snapshot): yes / no (fill per run)
- Fixed `as_of` date: ______ (fill per run; pass to `classify_companyfacts(as_of=...)`)
- `ENFORCE_DIVIDEND_RECENCY`: false (default in `.env.example`; set true to make the recency gate apply); `DIVIDEND_RECENCY_DAYS`: 548
- `FEATURE_CARRY_FORWARD_DAYS`: 7 (default)
- Row identity key: `(cik, ticker, security_type, dividend)`. `security_id` is a UUID and may be re-minted, so do not use it as the join key.
- Snapshots: `reference.securities` for A and B, each loaded into a separate schema or table.

## 1. Universe Summary

| Metric | A | B | Delta |
|---|---|---|---|
| Total `reference.securities` rows | | | |
| `active = TRUE` | | | |
| `active = FALSE` | | | |
| `dividend = TRUE` (dividend payers) | | | |
| Rows per `security_type` | | | |
| `preferred.security_terms` rows | | | |
| `model.features` rows in carry-forward window | | | |
| FK violations (must be 0) | | | |
| Violations of `ux_security_cik_ticker_type_dividend` (must be 0) | | | |
| Active duplicate `(cik, ticker)` pairs (must be 0, see V0039) | | | |

## 2. Added Rows (in B, not in A)

Per row: key, `security_id`, `security_type`, `dividend`, rule that added it, active duplicate check (pass/fail), `audit.source_lineage` rows present (pass/fail).

## 3. Removed Rows (in A, not in B)

Per row: key, `security_id`, rule that removed it, `audit.source_lineage` rows orphaned (pass/fail), downstream rows in `model.features` / `model.predictions` / `preferred.security_terms` affected, active securities that lose their feature row within the carry-forward window.

## 4. Changed Classification (same `(cik, ticker)`, different `security_type` or `dividend`)

Per row: old to new `security_type` and `dividend`, rule responsible, two active rows for one `(cik, ticker)` after change (pass/fail), effect on `scoring_features_sql` (filters `active = TRUE`).

## 5. Active Flag Changes

Per row: key, `active` old to new, reason, effect on scoring population, effect on `model.features` carry-forward (impact: high/medium/low).

## 6. Dividend Chronology Changes

Per row: key, `dividend` old to new, `dividend_last_paid` old to new, whether the change depends on the recency lookback (state whether enforcement is on), effect on the next 03:00 America/New_York run of `dividend_equity_nightly_etl`.

## 7. Preferred Series Changes

Per row: key, `preferred.security_terms.preferred_series` old to new, whether `match_security_title` still yields exactly one match (otherwise fallback), duplicate protection (pass/fail).
Note: companyfacts are issuer-level, so per-series term columns on `clean.ticker_profile` must stay NULL; flag any change that fills them.

## 8. Carry-Forward Impact

Per `security_id`: row selected by the `feature_window.py` window (`[MAX(as_of_date) - 7d, MAX(as_of_date)]`) under A vs B; list securities that gain or lose a row.

## 9. Operational Churn Estimate

Dry-run `dividend_equity_nightly_etl` against each snapshot and report row-level changes:

| Table | Inserted | Updated | Deactivated | % of A |
|---|---|---|---|---|
| `reference.securities` | | | | |
| `model.features` | | | | |
| `model.predictions` | | | | |
| `preferred.security_terms` | | | | |

## 10. Decision Gate

| Dimension | Criterion | Result |
|---|---|---|
| Duplicate protection | 0 unique-index violations; 0 active duplicate `(cik, ticker)` pairs (baseline cleared to 0 by V0047 on 2026-10-05) | pass/fail (fail = auto-reject) |
| Referential integrity | 0 FK violations, 0 orphaned lineage rows | pass/fail (fail = auto-reject) |
| Active-flag stability | flips <= 1% of A (~115 rows at 11,670) | pass/fail |
| Dividend chronology stability | changed `dividend` / `dividend_last_paid` <= 2% of `dividend = TRUE` rows (~120 at 5,956) | pass/fail |
| Preferred-series correctness | every change has exactly one title match; no per-series fill from issuer facts | pass/fail |
| Carry-forward coverage | active securities losing a feature row: 0 unexplained; <= 0.5% (~50) with each explained. Baseline daily `model.features` change is 0.0% to 0.5% | pass/fail |
| Operational churn | `reference.securities` inserts/deactivations <= 3% of A (normal nights add 0 to 26 rows, under 0.3%); `model.features` / `model.predictions` <= 5%. Judge by row-level diff, not `updated_at` (bulk-touched on 10-03 and 10-05) | pass/fail |
| Schema drift | `scripts/check_schema_drift.py` exits clean | pass/fail |
| Rebuild reproducibility | two consecutive builds of the same matcher give identical snapshots | pass/fail |

Baseline churn is measured from `audit.nightly_runs.row_counts` (V0048, populated from the first run after 2026-10-05):

```sql
SELECT run_date, row_counts,
       (row_counts->>'securities_active')::int
         - lag((row_counts->>'securities_active')::int) OVER (ORDER BY run_id) AS active_delta
FROM audit.nightly_runs WHERE status = 'success' AND row_counts <> '{}' ORDER BY run_id DESC LIMIT 20;
```

Recalibrate the tolerances above once 10+ runs exist. Thresholds are starting values measured on 2026-10-05 (11,670 securities, 10,625 active, 5,956 dividend payers). Tiers: within tolerance = accept; up to 2x tolerance = defer for manual review; above 2x or any hard invariant failing = reject. Recalibrate if the universe size changes materially. Decision: **accept / reject / defer narrowing**.
