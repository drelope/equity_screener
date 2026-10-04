-- Read-only database audit for the dividend pipeline.
-- Run against the application database after migrations have been applied.
-- These result sets are diagnostic; no statement modifies data or schema.

-- 1. Audit context and database footprint.
SELECT current_database() AS database_name,
       current_timestamp AS audited_at,
       pg_postmaster_start_time() AS server_started_at,
       stats_reset AS database_stats_reset_at,
       pg_size_pretty(pg_database_size(current_database())) AS database_size
FROM pg_stat_database
WHERE datname = current_database();

-- 2. Project relation sizes and approximate row counts.
SELECT n.nspname AS schema_name,
       c.relname AS relation_name,
       c.relkind,
       COALESCE(s.n_live_tup, 0) AS estimated_live_rows,
       COALESCE(s.n_dead_tup, 0) AS estimated_dead_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
       s.seq_scan,
       s.idx_scan,
       s.last_analyze,
       s.last_autoanalyze
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables AS s
       ON s.relid = c.oid
WHERE n.nspname IN (
    'raw', 'clean', 'reference', 'fundamentals',
    'dividends', 'preferred', 'market', 'model', 'audit'
)
  AND c.relkind IN ('r', 'p')
ORDER BY pg_total_relation_size(c.oid) DESC,
         n.nspname,
         c.relname;

-- 3. Table, column, routine and database comment coverage.
WITH project_objects AS (
    SELECT 'table'::text AS object_type,
           format('%I.%I', n.nspname, c.relname) AS object_name,
           obj_description(c.oid, 'pg_class') AS comment_text
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname IN (
        'raw', 'clean', 'reference', 'fundamentals',
        'dividends', 'preferred', 'market', 'model', 'audit'
    )
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
    UNION ALL
    SELECT 'column',
           format('%I.%I.%I', n.nspname, c.relname, a.attname),
           col_description(c.oid, a.attnum)
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    JOIN pg_attribute AS a ON a.attrelid = c.oid
    WHERE n.nspname IN (
        'raw', 'clean', 'reference', 'fundamentals',
        'dividends', 'preferred', 'market', 'model', 'audit'
    )
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND a.attnum > 0
      AND NOT a.attisdropped
    UNION ALL
    SELECT 'routine',
           format('%I.%I(%s)', n.nspname, p.proname,
                  pg_get_function_identity_arguments(p.oid)),
           obj_description(p.oid, 'pg_proc')
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname IN (
        'raw', 'clean', 'reference', 'fundamentals',
        'dividends', 'preferred', 'market', 'model', 'audit'
    )
    UNION ALL
    SELECT 'database',
           current_database(),
           shobj_description(d.oid, 'pg_database')
    FROM pg_database AS d
    WHERE d.datname = current_database()
)
SELECT object_type,
       COUNT(*) AS object_count,
       COUNT(*) FILTER (
           WHERE NULLIF(BTRIM(comment_text), '') IS NULL
       ) AS missing_comment_count,
       ARRAY_AGG(object_name ORDER BY object_name)
           FILTER (WHERE NULLIF(BTRIM(comment_text), '') IS NULL)
           AS missing_comment_objects
FROM project_objects
GROUP BY object_type
ORDER BY object_type;

-- 4. Constraint coverage and unvalidated constraints.
SELECT n.nspname AS schema_name,
       COUNT(*) FILTER (WHERE con.contype = 'p') AS primary_keys,
       COUNT(*) FILTER (WHERE con.contype = 'u') AS unique_constraints,
       COUNT(*) FILTER (WHERE con.contype = 'f') AS foreign_keys,
       COUNT(*) FILTER (WHERE con.contype = 'c') AS check_constraints,
       COUNT(*) FILTER (WHERE NOT con.convalidated) AS unvalidated_constraints
FROM pg_constraint AS con
JOIN pg_namespace AS n ON n.oid = con.connamespace
WHERE n.nspname IN (
    'raw', 'clean', 'reference', 'fundamentals',
    'dividends', 'preferred', 'market', 'model', 'audit'
)
GROUP BY n.nspname
ORDER BY n.nspname;

-- 5. Foreign keys whose child columns have no usable leading index.
-- Partial indexes are reported separately: they can support an FK when the
-- predicate includes every referencing row (e.g. security_id IS NOT NULL).
WITH foreign_keys AS (
    SELECT con.oid,
           con.conrelid,
           con.conname,
           con.conkey,
           n.nspname AS schema_name,
           c.relname AS table_name,
           pg_get_constraintdef(con.oid) AS definition
    FROM pg_constraint AS con
    JOIN pg_class AS c ON c.oid = con.conrelid
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE con.contype = 'f'
      AND n.nspname IN (
          'raw', 'clean', 'reference', 'fundamentals',
          'dividends', 'preferred', 'market', 'model', 'audit'
      )
), coverage AS (
    SELECT fk.*,
           EXISTS (
               SELECT 1
               FROM pg_index AS idx
               WHERE idx.indrelid = fk.conrelid
                 AND idx.indisvalid
                 AND idx.indisready
                 AND idx.indpred IS NULL
                 AND idx.indexprs IS NULL
                 AND idx.indnkeyatts >= cardinality(fk.conkey)
                 AND NOT EXISTS (
                     SELECT 1
                     FROM generate_series(0, cardinality(fk.conkey) - 1)
                          AS key_position(position)
                     WHERE idx.indkey[key_position.position]
                           <> fk.conkey[key_position.position + 1]
                 )
           ) AS has_full_leading_index,
           EXISTS (
               SELECT 1
               FROM pg_index AS idx
               WHERE idx.indrelid = fk.conrelid
                 AND idx.indisvalid
                 AND idx.indisready
                 AND idx.indpred IS NOT NULL
                 AND idx.indexprs IS NULL
                 AND idx.indnkeyatts >= cardinality(fk.conkey)
                 AND NOT EXISTS (
                     SELECT 1
                     FROM generate_series(0, cardinality(fk.conkey) - 1)
                          AS key_position(position)
                     WHERE idx.indkey[key_position.position]
                           <> fk.conkey[key_position.position + 1]
                 )
           ) AS has_partial_leading_index
    FROM foreign_keys AS fk
)
SELECT schema_name,
       table_name,
       conname AS foreign_key,
       definition,
       has_partial_leading_index
FROM coverage
WHERE NOT has_full_leading_index
ORDER BY schema_name, table_name, conname;

-- 6. Profile-table grain, missingness and duplicate identities.
SELECT COUNT(*) AS raw_profile_rows,
       COUNT(DISTINCT security_id) AS distinct_profile_security_ids,
       COUNT(DISTINCT ticker) AS distinct_tickers,
       COUNT(*) FILTER (WHERE sector IS NULL) AS missing_sector,
       COUNT(*) FILTER (WHERE industry IS NULL) AS missing_industry,
       COUNT(*) FILTER (WHERE coupon_rate IS NULL) AS missing_coupon_rate,
       COUNT(*) FILTER (WHERE liquidation_preference IS NULL)
           AS missing_liquidation_preference,
       (SELECT COUNT(*) FROM (
            SELECT s.cik, p.ticker
            FROM raw.ticker_profile AS p
            JOIN reference.securities AS s ON s.security_id = p.security_id
            GROUP BY s.cik, p.ticker
            HAVING COUNT(*) > 1
        ) AS repeated_identities) AS repeated_cik_ticker_groups
FROM raw.ticker_profile;

-- 7. Clean ticker-profile consolidation and unresolved conflicts.
SELECT COUNT(*) AS normalized_instruments,
       SUM(profile_count) AS represented_source_profiles,
       COUNT(*) FILTER (WHERE profile_count > 1) AS consolidated_groups,
       COUNT(*) FILTER (WHERE classification_conflict)
           AS unresolved_top_evidence_ties,
       COUNT(*) FILTER (
           WHERE metadata_conflicts ? 'security_type_candidates'
             AND NOT classification_conflict
       ) AS resolved_lower_rank_type_alternatives,
       COUNT(*) FILTER (WHERE liquidation_preference_conflict)
           AS liquidation_preference_conflict_groups,
       COUNT(*) FILTER (WHERE NULLIF(metadata_conflicts, '{}'::jsonb) IS NOT NULL)
           AS rows_with_metadata_conflicts
FROM clean.ticker_profile;

-- 8. Provider units: keep native values visible and count only corroborated
-- canonical dividend-yield conversions.
SELECT dividend_yield_source_unit,
       COUNT(*) AS profile_count,
       COUNT(*) FILTER (WHERE dividend_yield_fraction IS NOT NULL)
           AS normalized_yield_count
FROM clean.company_profile
GROUP BY dividend_yield_source_unit
ORDER BY dividend_yield_source_unit NULLS FIRST;

-- 9. Company-profile parent/child completeness and officer NULL semantics.
SELECT (SELECT COUNT(*) FROM clean.company_profile) AS company_profiles,
       (SELECT COUNT(*) FROM clean.company_officer) AS officer_rows,
       (SELECT COUNT(*) FROM clean.company_officer WHERE total_pay IS NULL)
           AS officers_with_undisclosed_pay,
       (SELECT COUNT(*) FROM clean.company_officer WHERE total_pay = 0)
           AS officers_with_reported_zero_pay,
       (SELECT COUNT(*) FROM (
            SELECT symbol, parent_name, name, title
            FROM clean.company_officer
            GROUP BY symbol, parent_name, name, title
            HAVING COUNT(*) > 1
        ) AS duplicate_officers) AS duplicate_officer_identities,
       (SELECT COUNT(*)
        FROM clean.company_officer AS officer
        LEFT JOIN clean.company_profile AS profile
          USING (symbol, parent_name)
        WHERE profile.symbol IS NULL) AS orphan_officer_rows,
       (SELECT COUNT(*) FROM clean.company_profile
        WHERE c2_c3_leverage_exempt) AS leverage_exemption_tags;

-- 10. High-cardinality scan and index-use observations.
-- pg_stat counters are cumulative; do not drop an index solely because idx_scan
-- is zero until the stats-reset window and workload seasonality are known.
SELECT schemaname,
       relname,
       n_live_tup,
       n_dead_tup,
       seq_scan,
       idx_scan,
       last_analyze,
       last_autoanalyze
FROM pg_stat_user_tables
WHERE schemaname IN (
    'raw', 'clean', 'reference', 'fundamentals',
    'dividends', 'preferred', 'market', 'model', 'audit'
)
ORDER BY seq_scan DESC
LIMIT 30;

SELECT schemaname,
       relname,
       indexrelname,
       idx_scan,
       idx_tup_read,
       pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE schemaname IN (
    'raw', 'clean', 'reference', 'fundamentals',
    'dividends', 'preferred', 'market', 'model', 'audit'
)
ORDER BY idx_scan ASC,
         pg_relation_size(indexrelid) DESC
LIMIT 30;

-- 11. Migration state. Compare the latest applied version with sql/migrations/.
SELECT version,
       name,
       applied_at
FROM public.schema_migrations
ORDER BY version DESC;