# UNK-001 / UNK-002 Basis Analysis (Read-only)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Scope | Read-only DB queries and repo inspection; no writes, no source/test/config changes |
| Status | **Evidence gathered; canonical basis decisions pending** |
| Related | `UNK-001`, `UNK-002`, `FR-ADJ-01`, `FR-DIV-08`, `FA-U01`, `FA-U03`, `RK-05`, `RK-10`, `TSK-019/021` |

## UNK-001 — Raw market close / adjusted_close basis

### Evidence
- `raw.market_data`: **9,823,774** rows, **0** rows with non-null `adjusted_close`.
- Sampled split events (`raw.corporate_actions`, 2024-2025 window) and surrounding closes:
  - `RPT` (`c70f9ab4...`, 2025-12-31, ratio `6`): closes 15.90→16.58 (2025-12-24..31) then 16.42→16.03 (2026-01-02..07), all `adjusted_close=NULL`, provider `OPENBB`.
  - `BCHT` (`64ec6776...`, 2025-12-31, ratio `5`): closes 4.00→3.75 then 4.13→4.30, all `adjusted_close=NULL`.
- Observed close series do **not** show a ratio-consistent discontinuity at the recorded split effective date in these samples, while no separate adjusted series is populated.

### Assessment
- Evidence indicates stored `close` values are not accompanied by a populated adjusted-close field and, in sampled split cases, are not obviously split-adjusted at the event boundary. This supports risk that downstream logic assuming adjusted/unadjusted semantics may be inconsistent (`PA-P01/02`, `FA-U01`).
- **Canonical basis remains unresolved** pending broader sample/provider confirmation and explicit contract decision for `FR-ADJ-01` (e.g. store raw unadjusted + computed/ingested adjusted, document provider basis, and align consumers).

### Recommended next actions
1. Expand read-only sample across providers/securities and compare to approved external/provider basis references.
2. Specify canonical storage/compute contract and consumer expectations in M2 P0 (`TSK-021`).
3. Add verification cases for split-adjusted continuity and total-return correctness.

## UNK-002 — Dividend amount / adjusted_amount basis

### Evidence
- Provider/feed distribution and adjustment fields (`raw.dividend_data`):
  - `OPENBB` / `yfinance`: **176,396** rows, `adjusted_amount` non-null **0**.
  - `OPENBB` / `fmp`: **20,783** rows, `adjusted_amount` non-null **20,783**, `amount<>adjusted_amount` **268**.
  - `SEC_XBRL` / `NULL`: **126,453** rows, `adjusted_amount` non-null **0**.
- Sample FMP rows where `amount<>adjusted_amount` (OPENBB/fmp): e.g. `AMCCF` 2025 dates show `amount=0.1275`, `adjusted_amount=0.6375` (and `0.13`/`0.65`), indicating provider-supplied adjusted values differ from stored amount in some cases.
- Sample same `(security_id, ex_dividend_date)` multi-provider rows show cross-provider differences (e.g. OPENBB/fmp `amount=1.79, adjusted=1.79, feed=fmp` vs SEC_XBRL `amount=1.79, adjusted=NULL`; OPENBB/yfinance `amount=0.382813, adjusted=NULL` vs SEC_XBRL `amount=2.08, adjusted=NULL`).
- **307,046** rows have >=1 null declaration/record/payment date (prior validation).

### Assessment
- Dividend amount semantics are **heterogeneous by provider/feed**: yfinance/SEC_XBRL carry no adjusted amount, FMP carries adjusted amount (mostly equal, some different), and cross-provider amounts can differ materially for the same event date.
- Current schema/loader behavior (provider-scoped PK omitting feed, unconditional upsert overwrite, no in-batch dedupe evidence in code) increases risk of ambiguous canonicalization and evidence loss (`FR-DIV-01/04/05/08`, `RK-10`).
- **Canonical per-provider/feed basis and consumer contract remain unresolved**.

### Recommended next actions
1. Build provider/feed basis matrix (raw vs split-adjusted, currency/unit conventions, event identity) from approved sources and targeted samples.
2. Approve dividend key/evidence/date-preservation contract (`dividend-batch-key-contract-draft.md`, `TSK-019`).
3. Define canonical amount field(s) for total return/features and add reconciliation/regression tests (`TSK-019/021`).

## Constraints / caveats
- Samples are illustrative, not exhaustive; conclusions are evidence-based but not definitive.
- No external provider documentation was fetched as authoritative in this pass; decisions require stakeholder/provider-term review (`DEC-001`).
- No data corrections or code changes performed.
