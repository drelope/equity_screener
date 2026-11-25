# Data Flow Inventory

| Field | Value |
|---|---|
| Stage | 0 — Discovery |
| Scope | Every dataset, source, transform, sink (DF-) |
| Method | Code/DDL inspection + read-only live PostgreSQL queries (2026-11-15) |
| Legend | V = Verified, I = Inferred, A = Assumption, U = Unknown |
| Row format | ID \| Finding \| Evidence \| File path \| Function/Class \| Requirement ID \| CRISP-DM phase \| Risk \| Recommended action \| Confidence \| Type |

## 1. Source and Provider Inventory

| Source | Access path / code | Primary destination | Conf/Type |
|---|---|---|---|
| SEC EDGAR JSON API | `sec_client.get_company_tickers`, `get_submissions`, `get_companyfacts`, `get_companyconcept`; `scripts/populate_raw_tables.py`; `scripts/populate_companyfacts.py` | `raw.company_ticker`, `raw.sec_submissions`, `raw.companyfacts`, `raw.company_taxonomy`, `raw.company_classification`, `reference.*` | 0.99 V |
| SEC bulk ZIPs | `scripts/load_sec_bulk.py` `FACTS_URL`, `SUBMISSIONS_URL` | Same upserts as SEC API | 0.99 V |
| SEC XBRL frames | `src/crispdm/frames.py` `FRAMES_URL`; `scripts/load_xbrl_frames.py` | `raw.xbrl_frames`; peer medians | 0.99 V |
| SEC filing archives / iXBRL | `scripts/populate_sec_instrument_titles.py`; `scripts/populate_contract_terms.py` | `raw.sec_instrument_titles`, `raw.contract_documents`, `preferred.contract_terms` | 0.95 V |
| Nasdaq Trader SymDir | `scripts/populate_exchange_listing_titles.py` `fetch_directory`, `store_listings`, `apply_titles` | `raw.exchange_listings` | 0.99 V |
| OpenBB / yfinance | `openbb_client.historical_prices`, `profile`, `stock_summary`, `equity_command`, `_yahoo_history`; `scripts/populate_market_data.py`; `scripts/populate_dividend_data.py` | `raw.market_data`, `raw.ticker_profile`, `raw.dividend_data`, `clean.*` | 0.99 V |
| FMP via OpenBB and direct REST | `openbb_client.financial_statements`, `filings`, macro helpers; `_fmp_rest_dividends`, `discounted_cash_flow`; `scripts/load_dividend_calendar.py`, `fetch_fmp_splits.py`, `load_split_calendar.py`, `populate_fmp_fundamentals.py` | `raw.dividend_data`, `raw.fmp_statements`, `raw.fmp_dcf`, `raw.fmp_filings`, `raw.dividend_calendar`, `raw.corporate_actions`, `raw.macro_series`, `raw.macro_etf_sectors` | 0.99 V |
| FRED / ALFRED | `openbb_client.macro_fred`; `scripts/load_macro_vintages.py` | `raw.macro_series`, `raw.macro_series_vintages` | 0.99 V |
| Polygon.io | `openbb_client.polygon_dividends`, `reconcile_amounts` | `raw.dividend_amount_check` | 0.99 V |
| API live fallback | `api/main.py` `/companies`, `/filings`, `/facts`, `/financials`, `/openbb/*`, `/metrics/enriched` | Reads warehouse; live OpenBB/SEC fallback; caches SEC submissions | 0.95 V |
| Analyst app / autofill | `app/analysis_autofill.py`; `src/crispdm/analysis/store.py` | Reads model/raw/fundamentals; writes `analysis.*` | 0.95 V |
| Legacy one-off scripts | `scripts/sec_dividend_analysis.py`, `IdentifyingDividend-PayingTickers.py`, `yahoo_FetchPreferredStock.py` | CSV exports / manual profile updates; not in nightly stage list | 0.90 V |

## 2. Data Flow Register (DF-)

| ID | Flow and evidence | CRISP-DM phase | Conf/Type |
|---|---|---|---|
| DF-01 | **SEC registrant/ticker reference:** `sec_client.get_company_tickers` → `populate_raw_tables.populate_company_tickers` → `raw.company_ticker`; `populate_reference_tables` → `reference.exchanges/issuers/securities` | Data Understanding | 0.99 V |
| DF-02 | **SEC submissions and company facts:** `get_submissions`, `get_companyfacts`, `get_companyconcept` → `populate_companyfacts` / `populate_preferred_companyfacts` / `refresh_unlinked_companyfacts`; bulk path `load_sec_bulk` → `raw.sec_submissions`, `raw.companyfacts` | Data Understanding | 0.99 V |
| DF-03 | **SEC concept index:** `populate_sec_documents.populate_concept_groups` reads stored `raw.companyfacts` → `raw.sec_documents.concept_groups` (no network) | Data Preparation | 0.99 V |
| DF-04 | **SEC cover-title extraction:** `populate_sec_instrument_titles` → `raw.sec_instrument_titles`; updates `reference.securities` and `raw.ticker_profile` | Data Preparation | 0.95 V |
| DF-05 | **Nasdaq listing titles:** `populate_exchange_listing_titles.fetch_directory` → `store_listings` → `raw.exchange_listings`; `apply_titles` fills missing preferred names/types | Data Preparation | 0.99 V |
| DF-06 | **Daily prices:** `openbb_client.historical_prices` → `populate_market_data.populate_market_data` → `raw.market_data`; consumed by `features.build_features`, `returns.build_forward_returns`, `portfolio.py` | Data Preparation | 0.99 V |
| DF-07 | **Dividends:** `populate_dividend_data.extract_sec_dividend_data`, `fetch_dividend_data`, `merge_dividend_records` + `openbb_client.dividends`, `reconcile_amounts` → `raw.dividend_data`, `raw.dividend_amount_check` | Data Preparation | 0.98 V |
| DF-08 | **FMP fundamentals:** `populate_fmp_fundamentals` → `raw.fmp_statements`, `raw.fmp_dcf`, `raw.fmp_filings` | Data Understanding | 0.99 V |
| DF-09 | **FMP dividend calendar:** `load_dividend_calendar.fetch_window`/`main` → `raw.dividend_calendar`; `raw.upcoming_dividends` view filters future events absent from `raw.dividend_data` | Data Preparation | 0.99 V |
| DF-10 | **FMP splits/corporate actions:** `fetch_fmp_splits` → `artifacts/corporate_actions/fmp_splits.csv` → `load_corporate_actions` → `raw.corporate_actions`; incremental `load_split_calendar`; consumed by `portfolio.py` | Data Preparation | 0.99 V |
| DF-11 | **SEC-derived fundamentals:** `fundamentals.extract_periodic_financials` → `populate_fundamentals` → `fundamentals.periodic_financials`; consumed by `features.py` | Data Preparation | 0.99 V |
| DF-12 | **Profiles and cleaning:** `populate_raw_tables.populate_ticker_profiles`, `populate_dividend_data.populate_ticker_profiles`, `populate_preferred_profiles` → `raw.ticker_profile`; `populate_clean_company_profile`, `populate_clean_ticker_profile` → `clean.*` | Data Preparation | 0.97 V |
| DF-13 | **Preferred contract terms:** `populate_contract_terms.fetch_source_documents` → `raw.contract_documents`; `populate_contract_terms` → `preferred.contract_terms` | Data Preparation | 0.95 V |
| DF-14 | **Macro inputs:** `populate_macro_inputs` → `raw.macro_series`, `raw.macro_etf_sectors`; `load_macro_vintages` → `raw.macro_series_vintages`; API/macro memo only, not model features | Data Understanding | 0.99 V |
| DF-15 | **XBRL frames:** `load_xbrl_frames.fetch_frame` → `raw.xbrl_frames`; peer medians in `src/crispdm/frames.py` | Data Preparation | 0.99 V |
| DF-16 | **Feature/label/score chain:** `features.build_features` → `model.features`; `returns.build_forward_returns` → `model.forward_returns`; `score_rank.main` → `model.scores`, `model.predictions`, `model.rankings`; `label_targets` → optional target column | Modeling | 0.99 V |
| DF-17 | **Audit and freshness:** `populate_audit` → `audit.source_lineage`, `audit.data_quality`; `verify_nightly_run` → `audit.nightly_checks`, `audit.source_freshness`; `run_full_etl` → `audit.nightly_runs` | Evaluation | 0.99 V |
| DF-18 | **Serving and analyst writes:** `api/main.py` reads stored tables and may live-fetch/cache SEC submissions; `app/views/*` reads; `analysis.store` writes `analysis.*` | Deployment | 0.95 V |
| DF-19 | **Operations control plane:** `ops/catalog.py` validates catalog keys/params and rebuilds argv from fixed modules; `ops/store.py` persists tasks | Deployment | 0.98 V |
| DF-20 | **Identity maintenance:** `resolve_ticker_conflict`, `merge_duplicate_identities`, `rekey_security_successor`, `repair_security_classification` repair/merge identities outside the nightly path | Data Preparation | 0.95 V |

## 3. Warehouse Inventory (live, 2026-11-15)

| Schema | Key tables / row counts | Role |
|---|---|---|
| `raw` | `market_data` 9,823,774; `dividend_data` 323,632; `companyfacts` 7,177; `sec_submissions` 8,208; `ticker_profile` 6,731; `ticker_profile_load` 210,009; `corporate_actions` 8,202; `dividend_calendar` 2,121; `dividend_amount_check` 577; `fmp_statements` 41,357; `fmp_dcf` 40,792; `fmp_filings` 354,322; `macro_series` 1,796; `macro_series_vintages` 105,865; `xbrl_frames` 203,555; `contract_documents` 1,749; `exchange_listings` 13,286 | Provider payloads, normalized source data, staging |
| `reference` | `securities` 12,585; `issuers` 8,223; `exchanges` 7; `security_identifiers` 25,037; view `v_us_instruments` 12,585 | Security/issuer identity and identifiers |
| `fundamentals` | `periodic_financials` 1,298,831 | Filing-vintage financial fundamentals |
| `model` | `features` 9,756,631; `forward_returns` 8,279,088; `predictions` 467,178; `scores` 464,691; `rankings` 464,691; view `current_predictions` | Features, targets, scores, predictions, rankings |
| `clean` | `company_profile` 5,846; `ticker_profile` 5,476; `company_officer` 40,665; `corporate_action` 851; hierarchy/reference-exception views | Curated profiles |
| `preferred` | `security_terms` 1,391; `dividend_snapshot` 891; `contract_terms` 303; `issuer_terms` and `v_security_terms` views | Preferred terms and contract evidence |
| `audit` | `data_quality` 343,627; `source_lineage` 26,297; `quarantined_values` 2,698; `source_freshness` 72; `nightly_runs` 53; `nightly_checks` 26; `model_runs` 18 | Provenance, quality, quarantine, freshness, run history |
| `analysis` / `ops` | `investment_analyses` 23; `investment_analysis_revisions` 23; `ops.workers` 1; `ops.tasks` 0; `ops.schedules` 0 | Analyst records and ops control plane |
| `market` | `trade`, `quote`, `bar` + `_default` partitions all 0 rows | Reserved intraday storage; not wired |
| `dividends` | Schema exists; **0 tables** | Unused schema |
| Artifacts | `artifacts/sec_bulk/`, `artifacts/sec_historical/`, `artifacts/historical_securities/*.csv`, `artifacts/corporate_actions/fmp_splits.csv`, `artifacts/event_study/`, `data/` | Staging/review files |

## 4. Data-Quality and Provenance Findings

| ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| DF-F01 | `raw.market_data.adjusted_close` is 100% NULL; only raw OHLCV is stored | 0 non-null of 9,823,774 rows | `sql/schema.sql`; `raw.market_data` | — | TBD | Data Preparation | Critical | Define explicit price-adjustment lineage in Stage 1A | 1.0 | Verified |
| DF-F02 | Price provenance is collapsed to `provider='OPENBB'`; FMP vs yfinance origin not stored | `PROVIDER="OPENBB"` | `scripts/populate_market_data.py` | `PROVIDER` | TBD | Data Preparation | High | Persist underlying feed per row | 1.0 | Verified |
| DF-F03 | Dividend provenance is richer: `provider`, `feed`, `amount_feed`, `adjusted_amount` | columns present | `sql/migrations/V0083`; `raw.dividend_data` | — | TBD | Data Preparation | Med | Use as model for price provenance | 1.0 | Verified |
| DF-F04 | FMP dividends are restated to Yahoo split basis; yfinance amounts already split-adjusted | `_price_basis_adjust`; dividend limits comments | `src/crispdm/openbb_client.py`; `src/crispdm/dividend_limits.py` | `_price_basis_adjust` | TBD | Data Preparation | Critical | Unit-test both provider bases in Stage 1A | 0.98 | Verified |
| DF-F05 | Dividend conflict key `(security_id, ex_dividend_date, provider)` excludes `feed`, so FMP/yfinance under `OPENBB` can collide | DDL conflict key | `scripts/populate_dividend_data.py`; `sql/schema.sql` | `DIVIDEND_UPSERT` | TBD | Data Preparation | High | Add provider-feed uniqueness tests | 0.95 | Inferred |
| DF-F06 | Dividend dates include suspicious extremes: yfinance min 1970-01-19; FMP max 2027-11-12 (future-dated) | live min/max queries | `raw.dividend_data` | — | TBD | Data Preparation | High | Add date-range sanity rules and tests | 1.0 | Verified |
| DF-F07 | 65 absurd OPENBB dividend rows above $1,000,000 are quarantined; raw rows retained | `audit.quarantined_values` count 65 | `sql/migrations/V0104`; `src/crispdm/dividend_limits.py` | — | TBD | Data Preparation | high | Keep quarantine; ensure downstream filters exclude | 1.0 | Verified |
| DF-F08 | `raw.dividend_amount_check` has 577 verdicts: 354 unresolved, 171 FMP, 52 yfinance | live group-by | `raw.dividend_amount_check` | — | TBD | Evaluation | Med | Expose unresolved count in nightly verification | 1.0 | Verified |
| DF-F09 | SEC XBRL dividend rows are mostly period aggregates and are excluded from true ex-date total return | `provider='OPENBB'` filter | `src/crispdm/returns.py`; `scripts/event_study.py` | — | TBD | Data Preparation | High | Document exclusion rationale; test it | 0.98 | Verified |
| DF-F10 | `fundamentals.periodic_financials` PK is `(security_id, period_end, fiscal_period, filed)`, not the README's three-column key | live constraints; `V0009` | `sql/migrations/V0009`; `scripts/populate_fundamentals.py` | `upsert_periodic_financials` | TBD | Data Preparation | Med | Correct README schema docs | 1.0 | Verified |
| DF-F11 | `reference.securities`: 2,959 active payers, 7,918 active non-payers, 651 inactive payers, 1,057 inactive non-payers | live group-by | `reference.securities` | — | TBD | Data Understanding | Med | Use counts as universe baseline | 1.0 | Verified |
| DF-F12 | `reference.v_us_instruments` exists but is unread by code | no code references; view has 12,585 rows | `sql/migrations/V0106` | — | TBD | Data Preparation | Low | Adopt or remove in roadmap | 1.0 | Verified |
| DF-F13 | `raw.upcoming_dividends` currently exposes 528 future calendar events with no history row | live count | `sql/migrations/V0099` | — | TBD | Data Understanding | Low | Document as informational view | 1.0 | Verified |
| DF-F14 | Intraday `market.*` tables exist but are empty and unwired | 0 rows | `sql/schema.sql` | — | TBD | Data Understanding | Low | Remove or reserve explicitly | 1.0 | Verified |
| DF-F15 | `dividends` schema is created but contains no tables | 0 tables | `sql/schema.sql` | — | TBD | Data Preparation | Low | Drop or document reserved status | 1.0 | Verified |
| DF-F16 | README/database-audit report row counts and relation list are stale | 2026-10-02 report vs live schema | `docs/database-audit-report.md` | — | TBD | Data Understanding | Low | Regenerate audit report | 0.95 | Verified |
| DF-F17 | Live warehouse is stale: last market data 2026-11-09 after four failed nightly runs | max observation date | `raw.market_data`; `audit.nightly_runs` | — | TBD | Evaluation | Critical | Remediate ETL failures before research use | 1.0 | Verified |
