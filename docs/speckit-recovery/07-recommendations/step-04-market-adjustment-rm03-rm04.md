# Step 4 — Market Adjustment Integrity (RM-03/04) Recommended Contract (Prepared)

| Field | Value |
|---|---|
| Recommendation | Canonical raw/adjusted price series with explicit basis, metadata, and consumer alignment |
| Status | **Prepared; canonical decision and implementation pending** |
| Traceability | `RM-03`, `RM-04`, `FR-ADJ-01`, `FR-DIV-07`, `FA-U01`, `NFR-PIT-03`, `RK-05`, `UNK-001`, `TSK-021` |
| Evidence | `../06-execution-prep/unk001-unk002-basis-analysis-2026-11-15.md`, `../06-execution-prep/repo-validations-2026-11-15.md` |

## 1. Evidence summary (read-only)
- `raw.market_data`: 9,823,774 rows, `adjusted_close` non-null **0**.
- Split-adjacent samples (e.g. RPT 2025-12-31 ratio 6: 15.90→16.58 pre, 16.42→16.03 post; BCHT 2025-12-31 ratio 5: 4.00→3.75 pre, 4.13→4.30 post) show no ratio-consistent break at effective date with `adjusted_close` NULL — consistent with unadjusted/ambiguous close storage, pending broader confirmation.
- Corporate actions exist in `raw.corporate_actions`; adjustment application/consumer alignment must be explicit.

## 2. Recommended solution
### 2.1 Canonical representation
- Store **explicit basis** per observation: e.g. `close_raw` (provider as-received/raw), `close_adjusted` (split/dividend-adjusted per approved policy), or equivalent columns/views; do not leave adjusted series undefined/null by default.
- Persist metadata: `price_basis`/`adjustment_basis`, provider, retrieval time/version, adjustment policy version, and corporate-action source/version used for computed adjustments.

### 2.2 Adjustment policy
- Define and approve policy for splits, cash dividends, special dividends, and reversals/corrections (`FR-DIV-07` currently Missing).
- If provider-adjusted values are used, validate against corporate actions/sample recomputation; if computed in-house, make computation deterministic and versioned.

### 2.3 Consumer alignment
- All returns, total-return series, performance, risk, and features must consume the same documented series for a given use case.
- Historical backtests/reports must record which series/policy/manifest was used (`as_of`, policy version).

## 3. Implementation/verification checklist (post-approval)
- [ ] Approve canonical basis and schema/view contract.
- [ ] Backfill/populate adjusted series with deterministic, auditable method.
- [ ] Add split-continuity and total-return regression tests (golden cases).
- [ ] Reconcile sampled events across providers/corporate actions.
- [ ] Update manifests/RTM and relabel/caveat affected historical outputs until verified.

## 4. Interim control
- Treat adjustment-dependent outputs as caveated/non-decision-grade until canonical basis and verification evidence exist (`EX-002` draft recommendation).
