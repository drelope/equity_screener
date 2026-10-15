-- raw.dividend_data.frequency held a hard-coded 'Annual' label on every row,
-- which concealed that most series pay quarterly. Re-derive the cadence from
-- the median gap between consecutive ex-dates and label every row of a
-- security with the same value.
--
-- Buckets (days ≤ border) mirror scripts/populate_dividend_data.py:
--   FREQUENCY_BUCKETS  Monthly 35 / Quarterly 95 / Semi-annual 200 / Annual 400
-- The median uses percentile_cont(0.5), which interpolates linearly between
-- the two middle gaps for an even count -- identical to the Python helper.
--
-- The OpenBB series (true ex-dates) is preferred when it holds at least two
-- events; the SEC XBRL series (fiscal period-end proxies) is the fallback.
-- Securities with fewer than two events in either series are 'Irregular'.

WITH events AS (
    SELECT security_id, provider,
           ex_dividend_date - LAG(ex_dividend_date) OVER (
               PARTITION BY security_id, provider ORDER BY ex_dividend_date
           ) AS gap_days
    FROM raw.dividend_data
),
medians AS (
    SELECT security_id, provider,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_days) AS median_gap
    FROM events
    WHERE gap_days IS NOT NULL
    GROUP BY security_id, provider
),
per_security AS (
    SELECT security_id,
           COALESCE(MAX(median_gap) FILTER (WHERE provider = 'OPENBB'),
                    MAX(median_gap)) AS median_gap
    FROM medians
    GROUP BY security_id
),
all_securities AS (
    SELECT s.security_id, ps.median_gap
    FROM (SELECT security_id FROM raw.dividend_data GROUP BY security_id) s
    LEFT JOIN per_security ps USING (security_id)
),
labelled AS (
    SELECT security_id,
           CASE
               WHEN median_gap IS NULL THEN 'Irregular'
               WHEN median_gap <= 35 THEN 'Monthly'
               WHEN median_gap <= 95 THEN 'Quarterly'
               WHEN median_gap <= 200 THEN 'Semi-annual'
               WHEN median_gap <= 400 THEN 'Annual'
               ELSE 'Irregular'
           END AS frequency
    FROM all_securities
)
UPDATE raw.dividend_data d
SET frequency = labelled.frequency
FROM labelled
WHERE d.security_id = labelled.security_id;

COMMENT ON COLUMN raw.dividend_data.frequency IS
  'Payment-interval cadence (Monthly/Quarterly/Semi-annual/Annual/Irregular), '
  'inferred from the median gap between consecutive ex-dates across the stored and '
  'incoming series (OpenBB true ex-dates first, SEC period-end proxies as fallback). '
  'One label per security. Informational; the feature build does not key on this column';