# Dividend Adjustment Audit (Stage 1A)

| Field | Value |
|---|---|
| Stage | 1A — Price adjustment audit |
| ID prefix | PA- |
| Input | `docs/speckit-recovery/00-discovery/` |
| Method | Read-only static audit; targeted pytest run; read-only live DB checks from Stage 0 |
| Repo HEAD | `d748cea` (worktree has uncommitted `requirements.txt`, `opencode.json`) |
| Type key | V = Verified (read in code or ran test), I = Inferred, A = Assumption, U = Unknown |

## 1. Scope

Traced dividend ingestion, corporate-action ingestion, split handling, special dividends, adjustment-factor generation, adjusted price calculation, total return, benchmark construction, and normalization. Each claim is tied to a file and function. Numbers are taken only from code, tests, or Stage 0 live queries; none are invented.

## 2. Dividend Ingestion Path

| Stage | Function / file | What it does | Type |
|---|---|---|---|
| Ticker universe | `get_target_dividend_tickers` — `scripts/populate_dividend_data.py` | `active = TRUE AND dividend = TRUE` unless `--include-non-dividend` | V |
| Primary feed | `fetch_dividend_data` → `openbb_client.dividends` — `scripts/populate_dividend_data.py`, `src/crispdm/openbb_client.py` | OpenBB (FMP first if key loaded, else yfinance). Default start `settings.dividend_lookback_start` (2025-01-01); `--full-history` starts 1970-01-01 | V |
| SEC XBRL | `extract_sec_dividend_data`, `normalize_sec_dividend_rows` | Per-share concepts only. `ex_dividend_date = payment_date = period end` | V |
| Normalize OPENBB | `normalize_openbb_dividend_rows` | Amount fallback `amount | dividend_amount | cash_dividend | dividends`; ex-date fallback `ex_dividend_date | date | payment_date` | V |
| Reconcile | `reconcile_amounts` — `openbb_client.py` | FMP vs Yahoo vs Polygon verdict (`fmp | yfinance | unresolved`) | V |
| Dedupe | `_collapse_duplicate_payments` (OPENBB only); `merge_dividend_records` (all) | Declared-first preference; `merge_dividend_records` keeps larger amount on key collision | V |
| Write | `DIVIDEND_UPSERT` on `(security_id, ex_dividend_date, provider)` | Insert or update; `_drop_superseded_feed_rows` deletes stale OPENBB rows in same transaction | V |

## 3. Findings Register

Row format: ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type

| ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| PA-D01 | SEC dividend rows use fiscal period end as `ex_dividend_date`; `filed` is extracted then dropped | "ex_dividend_date": end; `filed` read at L335-337, not copied in normalize | `scripts/populate_dividend_data.py` | `extract_sec_dividend_data`, `normalize_sec_dividend_rows` | FR-DIV (TBD Stage 2) | Data Preparation | High | Store `filed`/`accn` in `raw.dividend_data`; use filing date as availability date | 0.75 | Verified (drop); leak Inferred |
| PA-D02 | Fundamentals-based dividend fallback can read a figure before its filing date | `features.d_declared` joins `ex_dividend_date <= observation_date`, where that date is period end | `src/crispdm/features.py` | `build_features` (`d_declared`, ~L774-781) | FR-DIV / NFR-PIT | Data Preparation | High | Add filing-date lag to `d_declared` and `d_annual` | 0.85 | Verified (SQL); impact Inferred |
| PA-D03 | SEC rows collapse on `(ticker, provider, ex, pay)`; all concepts and filings for one period end collapse to max amount | `merge_dividend_records` keys; pay = ex = period end | `scripts/populate_dividend_data.py` | `merge_dividend_records` (L485-503) | FR-DIV | Data Preparation | High | Add `filed`/`accn` tie-break or dedicated SEC key | 0.85 | Verified |
| PA-D04 | OPENBB ex-date falls back to payment date when ex-date is missing | `parse_date(ex or date or payment_date)` | `scripts/populate_dividend_data.py` | `normalize_openbb_dividend_rows` (L412-414) | FR-DIV | Data Preparation | High | Reject rows without ex-date, or quarantine them | 0.9 | Verified |
| PA-D05 | Leap-day bug in plausibility horizon | `today.replace(year=today.year + 2)` raises ValueError on 29 Feb; unguarded in normalize | `scripts/populate_dividend_data.py` | `plausible_dividend_date` (L236-252) | NFR-REL | Data Preparation | Med | Use `today + timedelta(days=730)`; add test on 29 Feb | 0.8 | Inferred (Python semantics) |
| PA-D06 | Upsert overwrites date fields with NULL when a later run lacks them | `DIVIDEND_UPSERT` SET uses EXCLUDED without COALESCE for declaration/record/payment dates | `scripts/populate_dividend_data.py` | `DIVIDEND_UPSERT` (L112-124) | FR-DIV / NFR-AUD | Data Preparation | High | Use `COALESCE(EXCLUDED.x, raw.dividend_data.x)` | 0.85 | Verified |
| PA-D07 | Main insert loop has no per-row error handling; one bad row aborts the batch transaction | `engine.begin()` around `conn.execute(DIVIDEND_UPSERT, insert_rows)`; `errors` counter not incremented here | `scripts/populate_dividend_data.py` | main insert (L1375-1431) | NFR-REL | Data Preparation | Med | Count and log per-row failures; add test | 0.9 | Verified |
| PA-D08 | Open question: whether a batch with two rows sharing a PK raises ON CONFLICT "cannot affect row a second time" | Not verified | `scripts/populate_dividend_data.py` | `DIVIDEND_UPSERT` | NFR-DET | Data Preparation | Med | Run an executemany test with duplicate keys | 0.5 | Unknown |
| PA-D09 | `frequency` is a security-level label recomputed every run, stamped on every row | `_cadence_by_security` then row stamping | `scripts/populate_dividend_data.py` | `cadence_from_events`, `_cadence_by_security` (L543-588, L1426-1428) | FR-DIV | Data Preparation | Low | Document as derived attribute, not per-event fact | 0.9 | Verified |
| PA-D10 | `CommonStockDividendsPerShareCashPaid` is treated as per-share in ingestion but excluded as an aggregate in preferred view and rate lookup | ingest passes `pershare` filter; `get_latest_dividend_rate` and V0081 exclude it | `scripts/populate_dividend_data.py`; `sql/migrations/V0081` | `SEC_DIVIDEND_CONCEPTS`, `get_latest_dividend_rate` | FR-DIV | Data Preparation | Med | Reconcile the two treatments and document | 0.7 | Verified (inconsistency) |
| PA-D11 | Special dividends are identified only by provider label | `is_special_dividend` matches "special" label only | `scripts/populate_dividend_data.py` | `is_special_dividend` (L129-135) | FR-DIV | Data Preparation | Low | Document; add tests for label variants | 0.9 | Verified |
| PA-D12 | OpenBB amounts above 1,000,000 per share are silently dropped at normalize, not quarantined in code | `if selected > MAX_OPENBB_PER_SHARE_DIVIDEND: continue` | `scripts/populate_dividend_data.py` | `normalize_openbb_dividend_rows` (L426-430) | NFR-AUD | Data Preparation | Med | Write dropped rows to `audit.quarantined_values` | 0.9 | Verified |
| PA-D13 | Quarantine rule `OPENBB_DIVIDEND_AMOUNT_ABSURD` is written only by migration V0104, not by code | grep finds it only in migration and post-nightly check | `sql/migrations/V0104_quarantine_openbb_dividend_outliers.sql` | — | NFR-AUD | Evaluation | Med | Add code path or document one-time nature | 0.9 | Verified |
| PA-D14 | Yahoo-only amounts are used unadjusted for splits; only FMP rows go through `_price_basis_adjust` | yfinance-only path returns before restatement | `src/crispdm/openbb_client.py` | `dividends` (L442-488) | FR-ADJ | Data Preparation | High | Confirm Yahoo amounts are already split-restated (asserted in comments only) | 0.7 | Verified (code); basis Assumption |
| PA-D15 | `answered` flag swallows a later-provider exception after an empty earlier result | `answered` set on FMP empty return; yfinance error then ignored | `src/crispdm/openbb_client.py` | `dividends` (L453-488) | NFR-REL | Data Preparation | High | Propagate error when no provider returned rows; test the case | 0.9 | Verified |
| PA-D16 | Polygon unavailable (no key) still yields `unresolved` verdicts, which are cached 7 days | `reconcile_amounts` writes verdict even when `polygon()` returns None | `src/crispdm/openbb_client.py`; `scripts/populate_dividend_data.py` | `reconcile_amounts` (L415-425); `_load_amount_checks` (L753-757) | NFR-DET | Data Preparation | Med | Distinguish "no evidence" from "disagree" | 0.85 | Verified (code); impact Inferred |
| PA-D17 | Amount reconciliation verdict is cached; re-derived after 7 days; same-amount reuse is a cache hit | `RECHECK_UNRESOLVED_DAYS = 7`; cache reuse when amounts agree | `scripts/populate_dividend_data.py` | `_load_amount_checks`, `_save_amount_checks` | NFR-DET | Data Preparation | Med | Document; add tests for cache expiry | 0.85 | Verified |
| PA-D18 | Dividend cap and recency rules: observed payments keep existing payers only; never create new ones | docstring rule in `observed_payer_keys` | `src/crispdm/dividend_universe.py` | `observed_payer_keys` (L23-41) | FR-UNI | Data Understanding | Low | Document; note non-reproducible default `today` | 0.9 | Verified |
| PA-D19 | `observed_payer_keys` defaults to `date.today()`, so a past-date reconstruction is not reproducible unless `today` is passed | `today=None` default | `src/crispdm/dividend_universe.py` | `observed_payer_keys` | NFR-REPRO | Deployment | Med | Require explicit `today` in reconstruction paths | 0.95 | Verified |
| PA-D20 | `raw.dividend_calendar` is never removed from; withdrawn events persist | No DELETE in calendar loaders | `scripts/load_dividend_calendar.py`; `scripts/load_split_calendar.py` | `main` | FR-DIV | Data Preparation | Med | Add reconciliation/tombstone rule | 0.9 | Verified (absence) |
| PA-D21 | `raw.upcoming_dividends` and `raw.dividend_calendar` have no Python consumer in `src/`, `app/`, `api/` | grep-verified (Stage 1A agent) | `sql/migrations/V0099_dividend_calendar.sql` | — | FR-DIV | Business Understanding | Low | Confirm intended consumer or remove | 0.85 | Verified (absence) |
| PA-D22 | Frequency buckets are fixed by gap median; irregular payers are labeled Irregular | `FREQUENCY_BUCKETS` | `scripts/populate_dividend_data.py` | `FREQUENCY_BUCKETS`, `_median` (L512-522) | FR-DIV | Data Preparation | Low | Document thresholds | 0.9 | Verified |

## 4. Worked Examples (from existing tests, not fabricated)

| Example | Source | Input | Expected | Type |
|---|---|---|---|---|
| FMP restated by Yahoo split | `tests/test_openbb_client.py` L102 | FMP amounts 0.46, 0.34; Yahoo split `{2026-02-27: 1.5}` | `adjusted_amount == [0.46/1.5, 0.34]`; `amount` kept | V (test pass) |
| Reverse split restatement | `tests/test_openbb_client.py` L124 | Yahoo split `{2026-10-06: 0.1}`; amount 0.05 | adjusted ≈ 0.5; `splits=None` keeps 0.05 | V (test pass) |
| Polygon confirms Yahoo | `tests/test_openbb_client.py` L166 | FMP 0.87, Yahoo 0.92, Polygon 0.92 | amount 0.92, `amount_feed = yfinance` | V (test pass) |
| Multi-part FMP payment left alone | `tests/test_openbb_client.py` L191 | FMP 0.44 and 0.20 consecutive | both kept; no Polygon call | V (test pass) |
| Absurd OPENBB tail dropped | `tests/test_populate_dividend_data.py` L531 | 226,799,993,000,000 and 2,100,000 | dropped; 96,000 and 16,911 kept | V (test pass) |
| Same-payment dedupe | `tests/test_populate_dividend_data.py` L702 | six rows, CAT/RYAAY/BCIC | kept [05-15, 05-18, 08-07, 10-19] | V (test pass) |

Targeted run: `.venv/bin/python -m pytest -q` over 22 dividend/return/portfolio/feature/backtest test files — **398 passed, 0 failed, 0 skipped, 0 xfail**, exit 0 (agent-reported; live DB reachable, 323,632 rows in `raw.dividend_data`).

## 5. Rounding and Precision

- No `round`, `quantize`, or `numeric(p,s)` precision constraint on adjusted dividends in the audited code. Values are unbounded `NUMERIC` (schema L613-619). (V)
- Yahoo 3-decimal rounding is tolerated by `YAHOO_ROUNDING = 0.0005` in `_agree`; covered by `test_openbb_client.py` L234. (V)
- No test covers accumulated floating error in LN/EXP compounding. (V, absence)

## 6. Idempotency

| Operation | Key | Re-run behavior | Type |
|---|---|---|---|
| Dividend upsert | `(security_id, ex_dividend_date, provider)` | Updates in place; amounts and dates overwritten (see PA-D06) | V |
| Superseded-row delete | Same batch, same transaction | Deletes stored OPENBB rows in incoming range not in incoming dates | V |
| Corporate action (split) | `source_hash` | `ON CONFLICT DO NOTHING` (full loader) — no update on re-run | V |
| Split calendar | `source_hash` | `DO UPDATE SET retrieved_at = now()` only; values not refreshed | V |
| Dividend calendar | `(security_id, ex_dividend_date, provider)` | Updates amount/dates; `first_seen_at` preserved | V |
| Amount-check verdicts | `(ticker, ex_dividend_date)` | Re-derived; cached 7 days | V |

Not verified by execution: whether a full re-run of the total-return build produces identical rows (see Stage 1C). (U)

## 7. As-of Reconstruction

| Question | Answer | Type |
|---|---|---|
| Can a dividend be reconstructed as known at a past date? | Not reliably. `filed` is dropped (PA-D01); amounts are overwritten on re-run (PA-D06); `adjusted_amount` uses splits known at ingestion, including later ones (see FA-S03 in formula inventory) | V / Inferred |
| Can the active payer universe be reconstructed for a past date? | Only if `today` is passed explicitly (PA-D19) | V |
| Is there a point-in-time dividend history table? | No. `raw.dividend_data` is current-state with overwrite semantics | V |

## 8. Recommended Actions (priority order)

1. P0: Fix PA-D01 / PA-D02 (filing-date availability for SEC-derived dividends) — look-ahead.
2. P0: Fix PA-D06 (COALESCE on date upsert) — silent data loss on re-run.
3. P1: Fix PA-D15 (swallowed provider error) and PA-D04 (payment-date-as-ex-date fallback).
4. P1: Fix PA-D03 (SEC key collision) and PA-D16 (unresolved vs no-evidence).
5. P2: PA-D05 leap-day, PA-D07 per-row error counting, PA-D10 CashPaid inconsistency, PA-D12/D13 quarantine path.
6. Add a point-in-time dividend snapshot or `valid_from` history table before any historical reconstruction is claimed.
