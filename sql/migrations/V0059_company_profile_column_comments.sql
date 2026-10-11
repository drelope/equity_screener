-- V0059: business definitions for clean.company_profile.
--
-- V0026 commented ~115 provider columns with the generic text
-- 'Scalar OpenBB/yfinance company-profile attribute from source key <col>'.
-- This replaces them with units, basis (TTM / MRQ / per session) and
-- currency semantics. Comments are metadata only; no data changes.

COMMENT ON TABLE clean.company_profile IS
  'Curated company/listing profile from the OpenBB (yfinance) payload in raw.ticker_profile: one row per (symbol, parent_name), surrogate key profile_id. Issuer-level attributes (address, sector, fundamentals) repeat across an issuer''s listings; quote, dividend and valuation attributes are per listing. Linked to reference.securities via reference_security_id, cik and issuer_id. Children: clean.company_officer and clean.corporate_action (profile_id, ON DELETE CASCADE). Non-finite provider numbers load as NULL and are listed in non_finite_fields; unmapped source keys are kept in source_payload.unmapped. Rebuilt in full by scripts.populate_clean_company_profile.';

COMMENT ON COLUMN clean.company_profile.parent_name IS
  'Curated company name paired with symbol to form the natural key (symbol, parent_name); child tables reference profile_id';
COMMENT ON COLUMN clean.company_profile.name IS
  'Company or security name as returned by the provider (OpenBB name); parent_name is the curated key';
COMMENT ON COLUMN clean.company_profile.long_name IS
  'Full legal-style company or security name from the provider';
COMMENT ON COLUMN clean.company_profile.short_name IS
  'Abbreviated provider name; for preferred series it usually carries the coupon and series (e.g. 6.375% Series D)';
COMMENT ON COLUMN clean.company_profile.display_name IS
  'Short marketing name the provider shows for the company';
COMMENT ON COLUMN clean.company_profile.type_disp IS
  'Provider display label for the security type (e.g. Equity, ETF)';
COMMENT ON COLUMN clean.company_profile.quote_type IS
  'Provider quote-type code (EQUITY, ETF, MUTUALFUND, ...)';
COMMENT ON COLUMN clean.company_profile.issue_type IS
  'Issue type normalized by OpenBB (e.g. EQUITY); with sector_key drives c2_c3_leverage_exempt';
COMMENT ON COLUMN clean.company_profile.message_board_id IS
  'Provider discussion-board identifier for the symbol; informational only';
COMMENT ON COLUMN clean.company_profile.language IS
  'Locale of the provider quote record (e.g. en-US)';
COMMENT ON COLUMN clean.company_profile.address1 IS
  'Headquarters street address, line 1';
COMMENT ON COLUMN clean.company_profile.address2 IS
  'Headquarters street address, line 2 (suite, floor)';
COMMENT ON COLUMN clean.company_profile.city IS
  'Headquarters city';
COMMENT ON COLUMN clean.company_profile.state IS
  'Headquarters state or province code';
COMMENT ON COLUMN clean.company_profile.zip IS
  'Headquarters postal code, kept as text to preserve leading zeros';
COMMENT ON COLUMN clean.company_profile.country IS
  'Headquarters country name';
COMMENT ON COLUMN clean.company_profile.phone IS
  'Headquarters main telephone number';
COMMENT ON COLUMN clean.company_profile.fax IS
  'Headquarters fax number';
COMMENT ON COLUMN clean.company_profile.website IS
  'Corporate website URL';
COMMENT ON COLUMN clean.company_profile.company_url IS
  'Corporate website URL as normalized by OpenBB; normally equal to website';
COMMENT ON COLUMN clean.company_profile.hq_address1 IS
  'Headquarters street address as normalized by OpenBB; normally equal to address1';
COMMENT ON COLUMN clean.company_profile.hq_address_city IS
  'Headquarters city as normalized by OpenBB; normally equal to city';
COMMENT ON COLUMN clean.company_profile.hq_state IS
  'Headquarters state as normalized by OpenBB; normally equal to state';
COMMENT ON COLUMN clean.company_profile.hq_country IS
  'Headquarters country as normalized by OpenBB; normally equal to country';
COMMENT ON COLUMN clean.company_profile.business_phone_no IS
  'Business telephone number as normalized by OpenBB; normally equal to phone';
COMMENT ON COLUMN clean.company_profile.sector IS
  'Provider (Morningstar-based) sector name, e.g. Real Estate';
COMMENT ON COLUMN clean.company_profile.sector_key IS
  'Machine-readable sector slug, e.g. real-estate; with issue_type drives c2_c3_leverage_exempt';
COMMENT ON COLUMN clean.company_profile.sector_disp IS
  'Display label for sector';
COMMENT ON COLUMN clean.company_profile.industry IS
  'Provider industry name, e.g. REIT - Mortgage';
COMMENT ON COLUMN clean.company_profile.industry_key IS
  'Machine-readable industry slug, e.g. reit-mortgage';
COMMENT ON COLUMN clean.company_profile.industry_disp IS
  'Display label for industry';
COMMENT ON COLUMN clean.company_profile.industry_category IS
  'Industry category as normalized by OpenBB; normally equal to industry';
COMMENT ON COLUMN clean.company_profile.market IS
  'Provider market identifier, e.g. us_market';
COMMENT ON COLUMN clean.company_profile.region IS
  'Provider region code, e.g. US';
COMMENT ON COLUMN clean.company_profile.exchange IS
  'Provider exchange code where the symbol is quoted, e.g. NYQ (NYSE)';
COMMENT ON COLUMN clean.company_profile.stock_exchange IS
  'Exchange code as normalized by OpenBB; normally equal to exchange';
COMMENT ON COLUMN clean.company_profile.full_exchange_name IS
  'Human-readable exchange name, e.g. NYSE';
COMMENT ON COLUMN clean.company_profile.exchange_timezone_name IS
  'IANA time zone of the listing exchange, e.g. America/New_York';
COMMENT ON COLUMN clean.company_profile.currency IS
  'Currency of all quote and price fields (ISO 4217)';
COMMENT ON COLUMN clean.company_profile.financial_currency IS
  'Reporting currency of the financial-statement fields (revenue, cash, debt, book value); may differ from currency';
COMMENT ON COLUMN clean.company_profile.market_state IS
  'Trading-session state when the profile was retrieved: PRE, REGULAR, POST, POSTPOST or CLOSED';
COMMENT ON COLUMN clean.company_profile.quote_source_name IS
  'Provider quote feed, e.g. Nasdaq Real Time Price or Delayed Quote';
COMMENT ON COLUMN clean.company_profile.source_interval IS
  'Provider quote delay in minutes (e.g. 15 for delayed feeds)';
COMMENT ON COLUMN clean.company_profile.price_hint IS
  'Number of decimal places the provider uses to display prices';
COMMENT ON COLUMN clean.company_profile.max_age IS
  'Provider cache lifetime of the profile module in seconds; technical metadata';
COMMENT ON COLUMN clean.company_profile.tradeable IS
  'Provider flag: symbol can be traded through the provider platform';
COMMENT ON COLUMN clean.company_profile.triggerable IS
  'Provider flag: price alerts can be set on the symbol';
COMMENT ON COLUMN clean.company_profile.crypto_tradeable IS
  'Provider flag: symbol is a tradeable crypto asset';
COMMENT ON COLUMN clean.company_profile.esg_populated IS
  'Provider flag: ESG scores are available for the symbol';
COMMENT ON COLUMN clean.company_profile.current_price IS
  'Latest trade price in currency at retrieval time';
COMMENT ON COLUMN clean.company_profile.regular_market_price IS
  'Last regular-session trade price in currency';
COMMENT ON COLUMN clean.company_profile.regular_market_open IS
  'Regular-session opening price in currency';
COMMENT ON COLUMN clean.company_profile.regular_market_change IS
  'Absolute change of regular_market_price from previous_close, in currency';
COMMENT ON COLUMN clean.company_profile.regular_market_volume IS
  'Shares traded in the current or last regular session';
COMMENT ON COLUMN clean.company_profile.open IS
  'Opening price of the current or last session, in currency';
COMMENT ON COLUMN clean.company_profile.previous_close IS
  'Prior regular-session closing price, in currency';
COMMENT ON COLUMN clean.company_profile.day_low IS
  'Lowest trade price of the current or last session, in currency';
COMMENT ON COLUMN clean.company_profile.day_high IS
  'Highest trade price of the current or last session, in currency';
COMMENT ON COLUMN clean.company_profile.volume IS
  'Shares traded in the current or last session';
COMMENT ON COLUMN clean.company_profile.bid IS
  'Best bid price in currency at retrieval time';
COMMENT ON COLUMN clean.company_profile.ask IS
  'Best ask price in currency at retrieval time';
COMMENT ON COLUMN clean.company_profile.bid_size IS
  'Quantity at the best bid as reported by the provider (shares or round lots, provider-dependent)';
COMMENT ON COLUMN clean.company_profile.ask_size IS
  'Quantity at the best ask as reported by the provider (shares or round lots, provider-dependent)';
COMMENT ON COLUMN clean.company_profile.fullday_price IS
  'OpenBB full-day last price including extended hours when available, in currency';
COMMENT ON COLUMN clean.company_profile.fullday_change IS
  'Absolute change of fullday_price from previous_close, in currency';
COMMENT ON COLUMN clean.company_profile.pre_market_price IS
  'Last pre-market trade price, in currency';
COMMENT ON COLUMN clean.company_profile.pre_market_change IS
  'Absolute change of pre_market_price from previous_close, in currency';
COMMENT ON COLUMN clean.company_profile.average_volume IS
  'Average daily share volume over roughly the last 3 months';
COMMENT ON COLUMN clean.company_profile.average_volume10days IS
  'Average daily share volume over the last 10 trading days';
COMMENT ON COLUMN clean.company_profile.fifty_day_average IS
  '50-day simple moving average of the closing price, in currency';
COMMENT ON COLUMN clean.company_profile.fifty_two_week_low IS
  'Lowest trade price over the trailing 52 weeks, in currency';
COMMENT ON COLUMN clean.company_profile.fifty_two_week_high IS
  'Highest trade price over the trailing 52 weeks, in currency';
COMMENT ON COLUMN clean.company_profile.fifty_two_week_range IS
  'Provider text range ''low - high'' of the trailing 52 weeks';
COMMENT ON COLUMN clean.company_profile.all_time_low IS
  'Lowest trade price since listing, in currency';
COMMENT ON COLUMN clean.company_profile.all_time_high IS
  'Highest trade price since listing, in currency';
COMMENT ON COLUMN clean.company_profile.sand_p52_week_change IS
  'S&P 500 index 52-week change as a fraction (0.10 = 10 percent); benchmark for pct_change_52w';
COMMENT ON COLUMN clean.company_profile.beta IS
  'Provider beta of the symbol against the S&P 500 (5-year monthly returns)';
COMMENT ON COLUMN clean.company_profile.shares_outstanding IS
  'Shares outstanding of this symbol''s share class';
COMMENT ON COLUMN clean.company_profile.float_shares IS
  'Free-float shares available to the public (excludes insider and restricted holdings)';
COMMENT ON COLUMN clean.company_profile.shares_float IS
  'Free-float shares as normalized by OpenBB; normally equal to float_shares';
COMMENT ON COLUMN clean.company_profile.shares_short IS
  'Shares sold short as of date_short_interest';
COMMENT ON COLUMN clean.company_profile.short_ratio IS
  'Days to cover: shares_short divided by average daily volume';
COMMENT ON COLUMN clean.company_profile.held_percent_insiders IS
  'Fraction of shares held by insiders (0.05 = 5 percent)';
COMMENT ON COLUMN clean.company_profile.market_cap IS
  'Market capitalization in currency (price x shares outstanding, provider-computed)';
COMMENT ON COLUMN clean.company_profile.enterprise_value IS
  'Enterprise value in currency: market cap plus debt minus cash, provider-computed';
COMMENT ON COLUMN clean.company_profile.total_revenue IS
  'Trailing-twelve-month revenue in financial_currency';
COMMENT ON COLUMN clean.company_profile.gross_profits IS
  'Trailing-twelve-month gross profit in financial_currency';
COMMENT ON COLUMN clean.company_profile.net_income_to_common IS
  'Trailing-twelve-month net income available to common shareholders, in financial_currency';
COMMENT ON COLUMN clean.company_profile.operating_cashflow IS
  'Trailing-twelve-month operating cash flow in financial_currency';
COMMENT ON COLUMN clean.company_profile.revenue_per_share IS
  'Trailing-twelve-month revenue per share in financial_currency';
COMMENT ON COLUMN clean.company_profile.total_cash IS
  'Cash and short-term investments at the most recent quarter, in financial_currency';
COMMENT ON COLUMN clean.company_profile.total_cash_per_share IS
  'total_cash divided by shares outstanding, in financial_currency';
COMMENT ON COLUMN clean.company_profile.total_debt IS
  'Total debt at the most recent quarter, in financial_currency';
COMMENT ON COLUMN clean.company_profile.book_value IS
  'Book value per share at the most recent quarter, in financial_currency';
COMMENT ON COLUMN clean.company_profile.price_to_book IS
  'current_price divided by book_value; NULL when the provider value is non-finite';
COMMENT ON COLUMN clean.company_profile.enterprise_to_revenue IS
  'enterprise_value divided by total_revenue';
COMMENT ON COLUMN clean.company_profile.trailing_eps IS
  'Trailing-twelve-month diluted earnings per share';
COMMENT ON COLUMN clean.company_profile.trailing_p_e IS
  'current_price divided by trailing_eps; NULL when the provider value is non-finite (see non_finite_fields)';
COMMENT ON COLUMN clean.company_profile.forward_eps IS
  'Consensus earnings per share estimate for the next twelve months';
COMMENT ON COLUMN clean.company_profile.eps_forward IS
  'Forward EPS as normalized by OpenBB; normally equal to forward_eps';
COMMENT ON COLUMN clean.company_profile.forward_p_e IS
  'current_price divided by forward_eps; NULL when the provider value is non-finite (see non_finite_fields)';
COMMENT ON COLUMN clean.company_profile.eps_current_year IS
  'Consensus earnings per share estimate for the current fiscal year';
COMMENT ON COLUMN clean.company_profile.peg_ratio IS
  'Price/earnings-to-growth ratio as reported by the provider';
COMMENT ON COLUMN clean.company_profile.dividend_rate IS
  'Indicated annual dividend per share in currency (forward rate)';
COMMENT ON COLUMN clean.company_profile.last_dividend_value IS
  'Per-share amount of the most recent dividend, in currency';
COMMENT ON COLUMN clean.company_profile.recommendation_key IS
  'Analyst consensus recommendation code: strong_buy, buy, hold, underperform, sell or none';
COMMENT ON COLUMN clean.company_profile.recommendation_mean IS
  'Mean analyst rating on a 1 (strong buy) to 5 (sell) scale';
COMMENT ON COLUMN clean.company_profile.average_analyst_rating IS
  'Provider text form of the mean analyst rating, e.g. ''2.0 - Buy''';
COMMENT ON COLUMN clean.company_profile.target_low_price IS
  'Lowest analyst 12-month price target, in currency';
COMMENT ON COLUMN clean.company_profile.target_high_price IS
  'Highest analyst 12-month price target, in currency';
COMMENT ON COLUMN clean.company_profile.target_mean_price IS
  'Mean analyst 12-month price target, in currency';
COMMENT ON COLUMN clean.company_profile.target_median_price IS
  'Median analyst 12-month price target, in currency';
COMMENT ON COLUMN clean.company_profile.audit_risk IS
  'ISS Governance QualityScore for audit, 1 (lowest risk) to 10 (highest risk)';
COMMENT ON COLUMN clean.company_profile.board_risk IS
  'ISS Governance QualityScore for board structure, 1 (lowest risk) to 10 (highest risk)';
COMMENT ON COLUMN clean.company_profile.compensation_risk IS
  'ISS Governance QualityScore for compensation, 1 (lowest risk) to 10 (highest risk)';
COMMENT ON COLUMN clean.company_profile.overall_risk IS
  'ISS Governance QualityScore overall, 1 (lowest risk) to 10 (highest risk)';
COMMENT ON COLUMN clean.company_profile.employees IS
  'Full-time employee count as normalized by OpenBB; normally equal to full_time_employees';
COMMENT ON COLUMN clean.company_profile.full_time_employees IS
  'Full-time employee count reported by the provider';
