# UNK-005 Actual `DIVIDEND_UPSERT` Isolated Test (2026-11-15)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Scope | Controlled test in disposable Docker Postgres (`postgres:17-alpine`) using actual `scripts.populate_dividend_data.DIVIDEND_UPSERT` SQL text against a mirrored `raw.dividend_data` table schema/PK |
| Status | **Evidence gathered (isolated); shared DB untouched** |
| Related | `UNK-005`, `DA-21`, `FR-DIV-01`, `FR-DIV-04`, `FR-DIV-05`, `RK-10`, `scripts/populate_dividend_data.py:99-126` |

## Safety
- Temporary container created, tested, and destroyed in-run. No connections/writes to shared `dividend` DB. No source/test/config changes.

## Observed results

| Case | Setup/result |
|---|---|
| Seed row | `(provider='OPENBB', feed='yfinance', declaration_date='2023-12-20', amount=1.00, ex_dividend_date=2024-01-15)` inserted |
| Sequential NULL overwrite | Upsert with `declaration_date=NULL` (same key/provider) → stored row became `declaration_date=NULL, amount=1.00, feed='yfinance'` (**confirms unconditional overwrite can drop known non-NULL date**, `FR-DIV-04`) |
| Multi-values same-key single statement | Single INSERT of two rows for same `(security_id, ex_dividend_date, provider)` with `ON CONFLICT DO UPDATE` → `CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row a second time` |
| Feed collision at PK | Upsert same `(security_id, ex_dividend_date, provider)` with different `feed` (`fmp`) and amount → 1 row retained with `feed='fmp', amount='1.05'` (**provider-scoped PK omits `feed`; later write supersedes**) |
| Deterministic pre-dedupe (keep last) | Batch `[NULL-decl/yfinance, dated/fmp]` deduped by conflict key before `executemany` → stored `declaration_date='2023-12-21', amount='1.05', feed='fmp'` |

## Implications
- Confirms project upsert semantics (not only synthetic): unconditional `EXCLUDED.*` assignment, PK/feed collision behavior, and single-statement duplicate-key failure.
- Strengthens need for approved contract: deterministic in-batch pre-dedupe precedence, date-preservation (`COALESCE`/versioned correction), and feed-evidence retention strategy/key redesign or append-only evidence.

## Limitations
- Mirrored schema in disposable DB; not executed via project loader runtime/batching/transaction code paths or against production schema migrations beyond modeled columns/PK.
- No concurrency testing. Shared/project database untouched.
