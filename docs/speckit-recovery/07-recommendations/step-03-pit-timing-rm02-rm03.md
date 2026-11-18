# Step 3 — PIT Timing for Fundamentals and Dividends (RM-02/03) Design (Prepared)

| Field | Value |
|---|---|
| Recommendation | Persist/use availability/filing timestamps; separate dividend event semantics with known-as-of dates |
| Status | **Design prepared; pending decisions/implementation/verification** |
| Traceability | `RM-02`, `RM-03`, `NFR-PIT-01`, `FR-DIV-03`, `FR-FEAT-01`, `FR-DIV-04`, `FR-FEAT-02`, `RK-02`, `EX-003` |

## 1. Current evidence/gaps
- `FR-DIV-03` Missing: `filed_date` not persisted as dividend PIT availability field.
- `FR-FEAT-01` risk: feature timing uses `GREATEST(filed, period_end)` in current logic (can leak pre-filing/availability semantics depending on context).
- Dividend rows: 307,046 rows with >=1 null declaration/record/payment date (read-only DB evidence), so "known-as-of" cannot be inferred reliably without explicit contract.

## 2. Recommended target design
### 2.1 Fundamentals/features
- Persist source filing/acceptance/availability timestamps (SEC: filed/accepted as applicable) alongside period dates.
- Define `known_as_of` / `available_at` for each fundamental observation used in features: `available_at >= source availability timestamp` (never earlier than actual availability).
- Replace/guard `GREATEST(filed, period_end)` usage with explicit availability rule approved for PIT; document any lookahead-safe exceptions.
- Store `feature_as_of`, `input_available_at_max`, and source refs in feature manifests.

### 2.2 Dividends
- Persist and distinguish `declaration_date`, `ex_dividend_date`, `record_date`, `payment_date`, and `filed/available` timestamps where sourced.
- Define event usage by purpose: ex-date for price adjustment/entitlement timing, declaration/filing availability for "known" signals, payment for cashflow realization.
- Do not infer missing dates as known; expose null/unknown explicitly and handle in downstream logic with deterministic rules.

### 2.3 Date preservation
- On upsert/ingest, preserve existing non-NULL date fields when incoming is NULL unless explicit audited correction applies (see Step 5).

## 3. Verification plan
- Leak tests: for fixed `as_of`, no feature/dividend signal uses data with `available_at > as_of`.
- Golden cases for late filings, amended filings, and null-date records.
- Manifest/audit fields allow reconstruction of why a value was available.

## 4. Dependencies / blockers
- `EX-003` disposition and PIT policy approval.
- Source timestamp availability/quality (provider/SEC mapping) and schema/loader changes.
- Coordination with dividend evidence model (Step 5) and run manifests (Step 6).
