# Offline Labeling Plan — `target_sustainable_dividend`

The starter code deliberately does **not** fabricate labels
(`README.md:666`): `model.features.target_sustainable_dividend` is created as
`NaN` and the model cannot be evaluated until labels are populated. This plan
defines who labels, when, from what, and how the labels are accepted.

## 1. Problem being labeled

Forward-looking sustainability of the dividend for each screened security:

- **Positive (1):** the dividend stream is **maintained or increased** over a
  12-month outcome window after the feature `as_of_date`, AND declared amount
  does not drop to zero.
- **Negative (0):** any of the following within the 12-month window: dividend
  **cut**, **omitted**, **suspended**, or the security is delisted without a
  successor dividend.

A label is only written for feature rows whose `as_of_date` is at least 12
months before the observation cutoff; rolling 12-month windows keep labels
partial at the tail and prevent look-ahead bias.

## 2. Label owner and cadence

- **Owner:** the Data Scientist / ML Engineer role (single owner today).
- **Cadence:** labels are recomputed **nightly after the ETL**, appended at
  ETL end or as a separate `scripts.label_targets` step, and frozen at every
  walk-forward evaluation run. A label is immutable once a feature row has been
  used in training (no retrospective rewrites of consumed labels).
- **Recording:** each labeled row writes a provenance entry
  (`audit.source_lineage` with source `offline-label:dividend-sustainability`)
  so labels are auditable like any other fact.

## 3. Label sources

1. **Future dividend events** — `raw.dividend_data` rows with
   `ex_dividend_date` inside the 12-month window and `amount > 0`, joined to
   the security. Source providers: SEC XBRL and OpenBB.
2. **Fundamental coverage** — `fundamentals.periodic_financials` (net income,
   free cash flow) used to confirm the dividend remained covered
   (`dividend_coverage >= 1` on the latest period in the window).
3. **Reference flags** — `reference.securities.active` and `sec_data_status`;
   a security deactivated mid-window is evidence for a negative label.

## 4. Labeling SQL sketch (implemented as `scripts.label_targets`, 2026-09-23)

The implemented command is `python -m scripts.label_targets [--cutoff YYYY-MM-DD]
[--rebuild]`. It is also available as ETL stage 7 via `--run-labels` on
`scripts.run_full_etl` (refused on `--limit`/`--tickers` partial runs, since
labels are immutable once written).

Implemented semantics refine the sketch below (365-day window, matching the
`annual_dividend` feature convention):

- **1** — ≥ one positive dividend event (`ex_dividend_date` in window, `amount > 0`).
- **0** — no in-window positive payment, but monitoring extends to/past the
  window end (`MAX(ex_dividend_date) >= as_of_date + 365d`, counting any
  record incl. `amount = 0`, which marks a deliberate omission): a genuine
  cut, not lost coverage.
- **NULL** — otherwise-eligible rows whose monitoring data stops before the
  window end are left unlabeled (insufficient evidence), rather than being
  forced to 0.

```sql
WITH windowed AS (
  SELECT security_id, ex_dividend_date, amount,
         MAX(ex_dividend_date) OVER (PARTITION BY security_id) AS last_ex,
         COUNT(*) FILTER (WHERE amount > 0)
           OVER (PARTITION BY security_id, EXTRACT(YEAR FROM ex_dividend_date)) AS pays_in_year
  FROM raw.dividend_data
)
UPDATE model.features f
SET target_sustainable_dividend = CASE
      WHEN EXISTS (SELECT 1 FROM windowed w
                   WHERE w.security_id = f.security_id
                     AND w.ex_dividend_date > f.as_of_date
                     AND w.ex_dividend_date <= f.as_of_date + INTERVAL '12 months'
                     AND w.amount > 0)
       THEN 1::double precision
      ELSE 0::double precision END
WHERE f.as_of_date <= :cutoff - INTERVAL '12 months'
  AND f.target_sustainable_dividend IS NULL;
```

The exact query must be reviewed before enabling; it is intentionally
parameterized by `cutoff` (the label horizon) so partial windows are never
labeled.

## 5. Acceptance for a label cohort

- Every row labeled in a run must be ≥ 12 months before the run cutoff
  (no partial outcomes).
- Cohort imbalance is expected (dividend payers are mostly stable); the
  logistic model uses `class_weight="balanced"` and `threshold_for_recall` is
  tuned on training data to hit `MIN_RECALL` (0.30) while maximizing precision.
- Gate: `python -m scripts.evaluate_walk_forward` must exit 0
  (recall >= MIN_RECALL) for the Azure Go/No-Go decision; the checkpoint
  (metrics + window boundaries) is persisted to `audit.model_runs`.

## 6. Data / feature / model versioning

- Labels bind to `feature_version="features_v1"` and
  `data_version="sec_xbrl_v1"`; a schema change that alters a factor bumps
  `features_v1 -> features_v2` and forces a fresh label backfill, never a
  silent retrofit of past rows.
- `model.predictions` rows reference `model_version`; compare evaluation runs
  only within the same (data, feature) version pair.

## 7. Open decisions to confirm with the domain owner (product role)

- Window length (12 months assumed) vs. ex-date-annualized amount thresholds.
- Whether omitted-but-reinstated dividends within a window are negative or
  neutral.
- Minimum coverage ratio threshold used to confirm "covered" (1.0 assumed).