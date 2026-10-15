-- V0064 company_hierarchy issuer_keys: noise trim
--
-- The remaining flag noise after V0063 is technical/normalized-duplicate keys,
-- which are neither issuer disagreements nor worth review:
--
--   * max_age - provider cache lifetime in seconds; technical metadata that
--     varies by retrieval, not by issuer.
--   * business_phone_no / company_url / hq_address1 / hq_address_city /
--     hq_country / hq_state / industry_disp / sector_disp /
--     full_time_employees - OpenBB "normalized, normally equal to" duplicates
--     of phone / website / address1 / city / country / state / industry /
--     sector / employees. The parent output already coalesces each pair, so a
--     pair disagreement is a formatting variant, not real drift.
--
-- These keys are removed from issuer_keys: they stop flagging drift and stay
-- on each child. The canonical keys (phone, website, address1, city, state,
-- country, industry, sector, employees) remain issuer keys, as do the
-- statement headlines, fiscal dates, financial_currency and esg_populated.
-- DROP + recreate because CREATE OR REPLACE VIEW cannot remove columns.
--
-- Read-only: drops and recreates a view and its comments. No table, column,
-- or data change, and nothing in the nightly pipeline writes to it.

DROP VIEW IF EXISTS clean.v_company_hierarchy;

CREATE OR REPLACE VIEW clean.v_company_hierarchy AS
WITH params AS (
    SELECT
        ARRAY[
            'cik','issuer_id','phone','website','fax','address1','address2',
            'city','state','zip','country','language','employees','region',
            'industry','industry_key','sector','sector_key','financial_currency',
            'esg_populated','gross_margins','gross_profits','total_revenue',
            'net_income_to_common','debt_to_equity','ebitda_margins','profit_margins',
            'revenue_growth','most_recent_quarter','last_fiscal_year_end',
            'next_fiscal_year_end'
        ]::text[] AS issuer_keys,
        ARRAY[
            'reference_security_id','source_profile_security_id','source_provider','source_retrieved_at'
        ]::text[] AS lineage_keys
),
profile AS (
    SELECT
        cp.*,
        s.security_type,
        -- 1 = primary listing (common stock: no '-'/'.' postfix, then shortest symbol)
        row_number() OVER (
            PARTITION BY cp.cik
            ORDER BY (cp.symbol ~ '[-.]'), length(cp.symbol), cp.symbol
        ) AS listing_rank
    FROM clean.company_profile AS cp
    LEFT JOIN reference.securities AS s
        ON s.security_id = cp.reference_security_id
    WHERE cp.cik IS NOT NULL
),
parent AS (
    -- Issuer-level attributes, one row per CIK, taken from the primary listing.
    SELECT
        p.cik, p.issuer_id
        ,coalesce(p.parent_name, p.long_name, p.name, p.display_name) AS parent_name
        ,coalesce(p.phone, p.business_phone_no) AS phone
        ,p.fax
        ,coalesce(p.website, p.company_url) AS website
        ,coalesce(p.address1, p.hq_address1) AS address1
        ,p.address2
        ,coalesce(p.hq_address_city, p.city) AS city
        ,coalesce(p.hq_state, p.state) AS state
        ,p.zip
        ,coalesce(p.hq_country, p.country) AS country
        ,p.language
        ,p.market
        ,coalesce(p.employees, p.full_time_employees) AS effective_employees
        ,p.region
        ,coalesce(p.industry, p.industry_disp) AS industry
        ,coalesce(p.sector, p.sector_disp) AS sector
        ,coalesce(p.financial_currency, p.currency) AS effective_currency
        ,coalesce(p.type_disp, p.issue_type, p.quote_type) AS issue_type_label
        ,p.full_exchange_name
        ,p.security_type
        ,p.regular_market_time, p.market_state, p.tradeable
        ,p.total_cash, p.total_debt, p.book_value, p.beta
        ,coalesce(p.float_shares, p.shares_float) AS effective_float_shares
        ,p.current_ratio, p.esg_populated, p.gross_margins, p.gross_profits
        ,p.total_revenue, p.net_income_to_common
        ,p.debt_to_equity, p.ebitda_margins
        ,p.profit_margins, p.revenue_growth
        ,p.max_age, p.most_recent_quarter, p.last_fiscal_year_end, p.next_fiscal_year_end
        ,p.market_cap
        ,p.audit_risk, p.board_risk
        ,p.eps_forward, p.forward_eps, p.forward_p_e, p.triggerable
        ,p.overall_risk, p.payout_ratio
        ,p.trailing_eps
        ,p.compensation_risk
        ,p.target_low_price, p.eps_current_year, p.source_interval, p.peg_ratio, p.quick_ratio
        ,p.recommendation_mean, p.target_median_price
        ,p.sand_p52_week_change
        ,p.symbol AS primary_symbol
        ,p.short_name
        ,p.ex_dividend_date
        ,p.dividend_date
        ,p.dividend_rate
        ,p.dividend_yield
        ,p.last_dividend_date
        ,p.last_dividend_value
    FROM profile AS p
    WHERE p.listing_rank = 1
),
officer AS (
    -- Officers are issuer-level: each listing repeats them, so keep one row per
    -- (cik, name, title), preferring the primary listing's copy.
    SELECT DISTINCT ON (p.cik, o.name, o.title)
        p.cik, p.issuer_id, o.officer_no, o.name, o.title, o.age, o.year_born,
        o.fiscal_year, o.total_pay, o.exercised_value, o.unexercised_value
    FROM profile AS p
    JOIN clean.company_officer AS o
        ON o.profile_id = p.profile_id
    ORDER BY p.cik, o.name, o.title, p.listing_rank
),
parent_officers AS (
    -- Officers array for the PARENT (issuer) profile.
    SELECT
        o.cik,
        count(*) AS officer_count,
        jsonb_agg(to_jsonb(o) - ARRAY['cik','issuer_id'] ORDER BY o.officer_no, o.name) AS officers
    FROM officer AS o
    GROUP BY o.cik
),
child_actions AS (
    -- Corporate actions array per CHILD profile (listing-level).
    SELECT
        a.profile_id,
        jsonb_agg(
            to_jsonb(a) - ARRAY['profile_id','symbol','source_payload','loaded_at']
            ORDER BY a.effective_date, a.action_no
        ) AS corporate_actions
    FROM clean.corporate_action AS a
    GROUP BY a.profile_id
),
children AS (
    -- Child profiles (one JSONB object per profile_id) with their own
    -- corporate_actions nested. Only issuer-level keys and lineage are
    -- stripped: each child keeps its own per-listing quote, valuation,
    -- dividend and security_type columns.
    SELECT
        p.cik,
        count(*) AS child_count,
        jsonb_agg(
            (to_jsonb(p) - k.issuer_keys - k.lineage_keys - ARRAY['listing_rank'])
            || jsonb_build_object(
                'is_primary_listing', p.listing_rank = 1,
                'corporate_action_count', jsonb_array_length(coalesce(ca.corporate_actions, '[]')),
                'corporate_actions', coalesce(ca.corporate_actions, '[]')
            )
            ORDER BY p.listing_rank, p.symbol
        ) AS children
    FROM profile AS p
    CROSS JOIN params AS k
    LEFT JOIN child_actions AS ca
        ON ca.profile_id = p.profile_id
    GROUP BY p.cik
),
parent_conflicts AS (
    -- issuer_keys whose value is not the same across a CIK's listings. Quote
    -- and valuation keys are deliberately excluded: they legitimately differ
    -- per listing, so an entry here means real issuer-level drift.
    SELECT g.cik, array_agg(g.key ORDER BY g.key) AS varying_parent_attributes
    FROM (
        SELECT p.cik, e.key
        FROM profile AS p
        CROSS JOIN params AS k
        CROSS JOIN LATERAL jsonb_each(to_jsonb(p)) AS e
        WHERE e.key = ANY (k.issuer_keys)
        GROUP BY p.cik, e.key
        HAVING count(DISTINCT e.value) > 1
    ) AS g
    GROUP BY g.cik
)
SELECT
    par.cik,
    par.issuer_id,
    par.parent_name,
    par.phone,
    par.fax,
    par.website,
    par.address1,
    par.address2,
    par.city,
    par.state,
    par.zip,
    par.country,
    par.language,
    par.market,
    par.effective_employees,
    par.region,
    par.industry,
    par.sector,
    par.effective_currency,
    par.issue_type_label,
    par.full_exchange_name,
    par.security_type,
    par.regular_market_time,
    par.market_state,
    par.tradeable,
    par.total_cash,
    par.total_debt,
    par.book_value,
    par.beta,
    par.effective_float_shares,
    par.current_ratio,
    par.esg_populated,
    par.gross_margins,
    par.gross_profits,
    par.total_revenue,
    par.net_income_to_common,
    par.debt_to_equity,
    par.ebitda_margins,
    par.profit_margins,
    par.revenue_growth,
    par.max_age,
    par.most_recent_quarter,
    par.last_fiscal_year_end,
    par.next_fiscal_year_end,
    par.market_cap,
    par.audit_risk,
    par.board_risk,
    par.eps_forward,
    par.forward_eps,
    par.forward_p_e,
    par.triggerable,
    par.overall_risk,
    par.payout_ratio,
    par.trailing_eps,
    par.compensation_risk,
    par.target_low_price,
    par.eps_current_year,
    par.source_interval,
    par.peg_ratio,
    par.quick_ratio,
    par.recommendation_mean,
    par.target_median_price,
    par.sand_p52_week_change,
    par.primary_symbol,
    par.short_name,
    par.ex_dividend_date,
    par.dividend_date,
    par.dividend_rate,
    par.dividend_yield,
    par.last_dividend_date,
    par.last_dividend_value,
    coalesce(po.officer_count, 0) AS officer_count,
    coalesce(po.officers, '[]') AS officers,
    c.child_count,
    coalesce(pc.varying_parent_attributes, '{}') AS varying_parent_attributes,
    c.children
FROM parent AS par
JOIN children AS c
    ON c.cik = par.cik
LEFT JOIN parent_officers AS po
    ON po.cik = par.cik
LEFT JOIN parent_conflicts AS pc
    ON pc.cik = par.cik;

COMMENT ON VIEW clean.v_company_hierarchy IS
  'One row per issuer (CIK) built from clean.company_profile: the primary '
  'listing defines the issuer-level parent attributes, with officers and every '
  'listing (child, JSONB, including its own corporate actions) nested beside. '
  'Primary listing = the listing whose symbol has no ''-''/''.'' postfix (the '
  'common stock when one exists), else the shortest symbol. Exactly one '
  'child is primary per CIK. V0061: children strip issuer-level keys only, keep '
  'their own per-listing quote/valuation/dividend values and carry '
  'security_type from reference.securities; varying_parent_attributes reports '
  'issuer_key drift only. V0063: the per-listing venue/naming/currency keys '
  '(parent_name, market, exchange, stock_exchange, full_exchange_name, '
  'currency) are removed from issuer_keys, so they stay on each child and are '
  'never drift. V0064: the technical/normalized-duplicate keys (max_age, '
  'business_phone_no, company_url, hq_address1, hq_address_city, hq_country, '
  'hq_state, full_time_employees, industry_disp, sector_disp) follow. '
  'Read-only; see V0060-V0064.';
COMMENT ON COLUMN clean.v_company_hierarchy.cik IS
  'Zero-padded 10-digit SEC CIK from clean.company_profile.cik; the issuer key, '
  'never NULL (NULL-cik profiles are excluded)';
COMMENT ON COLUMN clean.v_company_hierarchy.issuer_id IS
  'Denormalized reference.issuers key of the matched reference security; NULL '
  'when the primary listing never resolved to a reference security';
COMMENT ON COLUMN clean.v_company_hierarchy.parent_name IS
  'Issuer display name, preferring parent_name then long_name/name/display_name '
  'from the primary listing';
COMMENT ON COLUMN clean.v_company_hierarchy.primary_symbol IS
  'Symbol of the primary listing (listing_rank = 1); the common stock when one exists';
COMMENT ON COLUMN clean.v_company_hierarchy.security_type IS
  'reference.securities.security_type of the PRIMARY listing (canonical '
  'lowercase vocabulary: common_stock, preferred stock, ...)';
COMMENT ON COLUMN clean.v_company_hierarchy.effective_employees IS
  'employees falling back to full_time_employees; NULL when neither is reported';
COMMENT ON COLUMN clean.v_company_hierarchy.effective_currency IS
  'financial_currency falling back to currency';
COMMENT ON COLUMN clean.v_company_hierarchy.issue_type_label IS
  'Best-effort issue-type label of the primary listing: type_disp, else '
  'issue_type, else quote_type';
COMMENT ON COLUMN clean.v_company_hierarchy.officer_count IS
  'Distinct officers across this issuer (deduplicated on name+title), preferring '
  'each officer''s copy on the primary listing';
COMMENT ON COLUMN clean.v_company_hierarchy.officers IS
  'JSONB array of distinct officers; each element is the company_officer row '
  'minus the cik/issuer_id join keys';
COMMENT ON COLUMN clean.v_company_hierarchy.child_count IS
  'Number of listings sharing this CIK; greater than one means the parent '
  'attributes describe the issuer, not one instrument';
COMMENT ON COLUMN clean.v_company_hierarchy.children IS
  'JSONB array, one element per listing (ordered primary first, then symbol): '
  'the company_profile row minus issuer-level keys and lineage, plus the '
  'per-listing security_type, is_primary_listing, corporate_action_count and '
  'its own corporate_actions array. Per-listing quote, valuation, dividend, '
  'venue, technical and normalized-duplicate columns are kept on each child';
COMMENT ON COLUMN clean.v_company_hierarchy.varying_parent_attributes IS
  'Issuer-level keys (identity, contact, HQ, sector/industry, fiscal dates, '
  'statement) whose value differs across this CIK''s listings - real drift worth '
  'review. Quote/valuation keys, per-listing venue/naming/currency keys '
  '(parent_name, market, exchange, stock_exchange, full_exchange_name, '
  'currency) and technical/normalized-duplicate keys (max_age, '
  'business_phone_no, company_url, hq_*, full_time_employees, industry_disp, '
  'sector_disp) are excluded by design. Empty array/object when all issuer '
  'keys agree';