# FMP / OpenBB / SEC EDGAR: Capability Gap Analysis and Data Recipe

This document replaces the raw FMP plan capability list with a gap analysis against
what the pipeline actually consumes today. It answers three questions:

1. Which provider endpoints are wired into the warehouse, and where?
2. Which capabilities the plan already grants are unused, and what breaks because
   of that?
3. What is the ordered recipe (and shopping list) to close the gaps?

"Starter" access varies by add-on and usage tier. Treat every "available" claim as
"verify against the current dashboard before committing to a design".

## 1. What the pipeline uses today

Verified against the source at the time of writing.

| Domain | Provider / endpoint | Code | Warehouse target |
| --- | --- | --- | --- |
| Ticker universe | SEC `company_tickers.json` | `sec_client.get_company_tickers` | `raw.company_ticker`, `reference.securities` |
| Issuer filings index | SEC submissions | `sec_client.get_submissions` | `raw.sec_submissions` |
| XBRL facts | SEC companyfacts / companyconcept | `sec_client.get_companyfacts`, `get_companyconcept` | `raw.companyfacts`, `raw.company_taxonomy` |
| Filing documents | SEC archive index + instance XML | `fetch_archive_index`, `fetch_filing_xml` | `raw.sec_documents`, `raw.contract_documents` |
| Prices | OpenBB `equity.price.historical` | `openbb_client.historical_prices` | `raw.market_data` |
| Dividends | OpenBB `fundamental.dividends`, FMP `stable/dividends`, yfinance, Polygon | `openbb_client.dividends`, `_fmp_rest_dividends`, `_yahoo_history`, `polygon_dividends` | `raw.dividend_data` |
| Company profile | OpenBB `equity.profile` | `openbb_client.profile` | `raw.ticker_profile` |
| FMP filings | OpenBB `equity.fundamental.filings` | `openbb_client.filings` | `raw.fmp_filings` |
| Statements | OpenBB/FMP statement commands | `openbb_client.financial_statements` | `raw.fmp_statements` |
| DCF | FMP `stable/discounted-cash-flow` | `openbb_client.discounted_cash_flow` | `raw.fmp_dcf` |
| Treasury rates | OpenBB `fixedincome.government.treasury_rates` | `macro_treasury_rates` | `raw.macro_series` |
| FRED | OpenBB `economy.fred_series` | `macro_fred` | `raw.macro_series` |
| Sector weights | OpenBB `etf.sectors` | `macro_etf_sectors` | `raw.macro_etf_sectors` |
| Risk premium | OpenBB `economy.risk_premium` | `macro_risk_premium` | `raw.macro_series` |
| ETF history | OpenBB `etf.historical` | `macro_etf_history` | `raw.macro_series` |
| Splits | FMP `stable/splits` | `scripts/fetch_fmp_splits.py` | `artifacts/corporate_actions/fmp_splits.csv` (not a table) |

SEC access goes through `_SecSession`, which enforces the fair-access User-Agent
and throttles to `SEC_MIN_INTERVAL` (default 0.15s) with retry/backoff. The ticker
universe is now cached in-process for `SEC_COMPANY_TICKERS_TTL` (default 300s);
nothing else is cached.

## 2. Gap analysis

### 2.1 Identity and universe (highest impact)

| Gap | Evidence | Impact | Priority |
| --- | --- | --- | --- |
| CUSIP/ISIN search is unused | No `cusip`/`isin` in `reference.securities`; matching uses ticker, CIK and title heuristics (`bind_dei_titles_to_symbol`, `match_security_title`) | Preferreds and dual-class lines are resolved by title text; an identifier mapping would make the binding deterministic | High |
| Symbol changes and delisted companies are not ingested | `build_historical_universe.py` reads submissions but does not apply a symbol-change map; no delisted feed | Historical universe is survivorship-biased; a renamed ticker can create a duplicate or a dropped security | High |
| Share-class and ETF/fund type are inferred, not sourced | `classify_security_symbol`, `classify_instrument` heuristics | Misclassification propagates to yield and payout features | Medium |
| M&A events are unused | Not present in the pipeline | Universe gaps around acquisitions/mergers; corporate-action context missing | Low |

### 2.2 Fundamentals and filings

| Gap | Evidence | Impact | Priority |
| --- | --- | --- | --- |
| Bulk EDGAR datasets are unused | Per-CIK `companyfacts`/`submissions` pulls in `populate_*` scripts; no `companyfacts.zip`/`submissions.zip` path | Onboarding thousands of CIKs spends the fair-access budget and wall-clock time; every full rebuild refetches | High |
| SEC Frames API is unused | No frames call in `sec_client` | Cross-sectional factor checks and peer comparisons require one pull per company instead of one per concept/period | Medium |
| Dimensional (segment) facts are ignored | `build_companyfacts_concept_groups` reads consolidated values only | Segment revenue/geography and some preferred terms are invisible | Medium |
| As-reported statements and restatement history are not stored | Only XBRL facts and FMP standardized statements are kept | A later restatement cannot be replayed against the vintage that was live at the time | Medium |
| Financial statement growth / key-metrics TTM from FMP are unused | Only raw statements and DCF are ingested | Growth and TTM comparisons are recomputed or missing | Medium |
| EDGAR full-text search is unused | Contract terms come from archive index + XML parsing | Discovery of terms in exhibits depends on knowing which filing to open | Low |
| 8-K item taxonomy is not extracted | `raw.fmp_filings` stores report metadata only | Event-driven signals and dividend-cut context are unavailable | Low |

### 2.3 Dividends and corporate actions

| Gap | Evidence | Impact | Priority |
| --- | --- | --- | --- |
| Splits live in a CSV artifact, not the warehouse | `fetch_fmp_splits.py` writes `artifacts/corporate_actions/fmp_splits.csv`; `_price_basis_adjust` consumes it in-process | Split adjustment is not reproducible from the database; a lost artifact silently changes history | High |
| Dividend calendar / announced future dividends are unused | `dividends()` fetches history only | Forward yield and cut-risk features cannot see an announced change | Medium |
| Special dividends and return-of-capital are not classified | `raw.dividend_data` stores amounts and reconciliation verdicts only | Payout and coverage treat specials as recurring | Medium |
| Reconciliation depends on optional providers | `DIVIDEND_PROVIDERS = ("fmp", "yfinance")`; Polygon needs a key | With one provider the amount verdict degrades silently | Medium |

### 2.4 Market data and macro

| Gap | Evidence | Impact | Priority |
| --- | --- | --- | --- |
| Only historical bars are ingested | No quote snapshot, batch quote, intraday, or market-hours feed | As-of pricing and liquidity checks rely on the last daily close | Medium |
| FRED is stored as a plain series | `raw.macro_series` has no vintage/revision column; ALFRED is unused | A revised macro print rewrites history, which leaks into backtests | High |
| Macro release calendar is unused | Not present | Event windows cannot be aligned to releases | Low |
| Sector performance snapshots and PE snapshots are unused | Only ETF sector weights are stored | Cross-sectional valuation context is thinner than available | Low |

### 2.5 Ownership, news and analyst data

| Gap | Evidence | Impact | Priority |
| --- | --- | --- | --- |
| 13F, insider, Senate/House trades are unused | No tables or clients | Ownership and governance signals absent | Low (product-dependent) |
| News, press releases, earnings transcripts are unused | No ingestion | No event text for cut/raise explanations | Low |
| Analyst estimates, ratings and price targets are unused | `/openbb/analysts` endpoint exists but no warehouse source | No consensus comparison | Low |

### 2.6 Serving and freshness

| Gap | Evidence | Impact | Priority |
| --- | --- | --- | --- |
| API reads bypass the warehouse | `api/main.py` calls `get_company_tickers`, `get_issuer_data`/`get_submissions`, `get_companyfacts` live for `/company`, `/filings`, `/facts` | Latency and availability are coupled to SEC; no write-through, no ETag cache | High |
| No conditional GET or ETag cache | `_SecSession.get` sets no `If-None-Match`/`If-Modified-Since` and stores no validators | Every refresh downloads full payloads | Medium |
| ~~No freshness SLA per source~~ | Resolved: `FRESHNESS_SOURCES` bounds every source and `audit.source_freshness` (V0102) records one row per source per verification | Stale inputs are noticed by their own check, with a history | Done |
| Lineage does not name the model/feature set | `audit.source_lineage.model_version`/`feature_set_hash` exist (V0095) but no writer populates them | A stored fact cannot be traced to the model that consumed it | Medium |

## 3. SEC EDGAR critique

What is done well:

- The fair-access User-Agent is required before any request (`settings.require_sec_user_agent`).
- Requests are throttled and retried with backoff (`Throttle`, `request_with_backoff`).
- Both `companyfacts` and per-concept `companyconcept` are available, so a missing
  fact can be fetched narrowly instead of re-downloading the whole company.
- Filing archives and instance XML are parsed for preferred terms and DEI titles.

What is weak:

- The integration is pull-per-company, not bulk-first. `companyfacts.zip` and
  `submissions.zip` exist precisely to avoid N requests; using them for a full
  rebuild and reserving per-CIK calls for deltas is the single biggest cost win.
- There is no HTTP cache. SEC responses are immutable for a given accession, and
  `submissions` changes slowly, yet both are refetched. Conditional GET plus a
  content hash would make refreshes cheap and auditable.
- The API serves SEC live instead of reading `raw.*`. A warehouse-first read with
  a live fallback (and write-through) removes SEC from the request path.
- Cross-sectional work is missing the Frames API, so "all filers, one concept,
  one period" is expressed as a loop.
- Dimensional facts are dropped, which is acceptable for consolidated factors but
  not for segment or share-class analysis.

## 4. Recipe (ordered)

Each step has an acceptance check so it can be verified, not just claimed.

1. **Persist corporate actions.** Add `raw.corporate_actions` (`security_id`,
   `action_type` in `split|symbol_change|merger|spinoff`, `effective_date`,
   `ratio`/`from_symbol`/`to_symbol`, `source`, `source_hash`). Load
   `stable/splits` and the symbol-change list into it. Replace the CSV read in
   `_price_basis_adjust` with a warehouse query. Check: rebuilding prices from
   the table reproduces the current adjusted series exactly.
2. **Bulk-first EDGAR ingestion.** Add a loader for `companyfacts.zip` and
   `submissions.zip` that diffs by accession and writes only changed rows.
   Schedule it weekly; keep per-CIK calls for targeted backfills. Check: a full
   rebuild issues no per-CIK `companyfacts` requests.
3. **Warehouse-first API.** Change `/company`, `/filings`, `/facts` to read
   `raw.sec_submissions`/`raw.companyfacts` first, fall back live, and write the
   fallback through. Check: with SEC blocked, all three endpoints still answer
   from stored data.
4. **HTTP caching.** Add ETag/Last-Modified storage per URL and send
   `If-None-Match`/`If-Modified-Since`; treat `304` as a hit. Check: a second
   refresh of an unchanged resource performs no body download.
5. **Identity mapping.** Add `reference.security_identifiers` (`security_id`,
   `id_type` in `cik|cusip|isin|ticker`, `id_value`, `valid_from`, `valid_to`)
   and backfill from CIK/CUSIP/ISIN search. Resolve the universe through it.
   Check: every active security has at least a CIK and one market identifier.
6. **Dividend calendar and flags.** Ingest the dividend calendar into
   `raw.dividend_calendar` and add `is_special`/`is_return_of_capital` to
   `raw.dividend_data`. Check: announced-but-unpaid dividends are visible to the
   forward-yield path.
7. **Macro vintages.** Add `vintage_date` to `raw.macro_series` and ingest
   ALFRED revisions. Check: a backtest as-of date sees only the vintage that was
   live on that date.
8. **Cross-sectional checks.** Use the Frames API to store a per-concept,
   per-period snapshot for factor sanity checks. Check: peer medians reproduce
   from the snapshot without per-company calls.
9. **Ownership and events (product-dependent).** Add 13F, insider, and 8-K item
   tables only if the dashboard needs them; do not ingest them speculatively.
10. **Freshness and lineage.** Add per-source freshness SLAs to the health report,
    and populate `audit.source_lineage.model_version`/`feature_set_hash` from the
    versioning constants. Check: every nightly row names its source, feature set
    and model version.

## 5. Shopping list

Verify each against the current FMP dashboard before purchase.

- **FMP plan features to confirm:** bulk endpoints (profiles, statements,
  scores, DCF), CIK/CUSIP/ISIN search, symbol changes, delisted companies, stock
  split details/calendar, dividend calendar, 13F and insider feeds. If the current
  tier does not include bulk and identifier search, those are the upgrades that
  unlock steps 1, 2 and 5.
- **Polygon key:** already optional for dividend reconciliation; a key upgrades
  the amount verdict from two-source to three-source agreement.
- **FRED API key:** required for `economy.fred_series`; ALFRED access comes with
  the same key.
- **SEC:** no purchase. Keep a real contact in the User-Agent; prefer bulk files.
- **Storage:** partition `raw.companyfacts` by CIK range or load date, and add
  indexes on `(security_id, effective_date)` for corporate actions.

## 6. Verification

After implementing the recipe, the repository gates are the acceptance test:

```bash
ruff check .
ruff format --check .
python -m pytest -m "not integration" -q
python -m scripts.migrate --check
python -m scripts.check_schema_drift --quiet
```

Add one test per new table/loader that asserts a row is written with its source
hash, and one API test per warehouse-first endpoint that asserts it answers with
the live client blocked.
