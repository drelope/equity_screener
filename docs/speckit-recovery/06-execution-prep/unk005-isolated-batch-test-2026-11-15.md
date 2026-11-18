# UNK-005 Isolated Duplicate-Key / Date-Preservation Test (2026-11-15)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Scope | Controlled test in disposable Docker Postgres container (`postgres:17-alpine`), created and destroyed during this run |
| Status | **Evidence gathered (isolated); shared DB untouched** |
| Related | `UNK-005`, `DA-21`, `FR-DIV-01`, `FR-DIV-04`, `RK-10`, `scripts/populate_dividend_data.py`, `dividend-batch-key-contract-draft.md` |

## Environment and safety
- Used local Docker to start a temporary container with ephemeral credentials/DB; executed minimal SQL via `psycopg`; removed container after test.
- No connections to or writes against `dividend`/shared project DB. No source/test/config changes.

## Test setup
Table modeled on dividend conflict key/fields:
```sql
CREATE TABLE t(
  security_id int,
  ex_dividend_date date,
  provider text,
  declaration_date date,
  amount numeric,
  PRIMARY KEY(security_id, ex_dividend_date, provider)
);
```
Upsert modeled on `DIVIDEND_UPSERT` behavior (unconditional assignment from `EXCLUDED`):
```sql
INSERT INTO t(security_id, ex_dividend_date, provider, declaration_date, amount)
VALUES (...)
ON CONFLICT (security_id, ex_dividend_date, provider) DO UPDATE SET
  declaration_date = EXCLUDED.declaration_date,
  amount = EXCLUDED.amount;
```

## Results

| Case | Input | Observed result | Implication |
|---|---|---|---|
| 1. `executemany` with two same-key rows | `[(1,'2024-01-01','OPENBB',NULL,1.0),(1,'2024-01-01','OPENBB','2023-12-01',2.0)]` | **Succeeded**; final row `declaration_date='2023-12-01', amount='2'` | Driver executed statements sequentially/effectively applied later row; behavior depends on execution strategy and is not an explicit in-DB single-statement conflict in this form. Not a safe substitute for deterministic contract. |
| 2. Sequential upsert, NULL after non-NULL | first insert `declaration_date='2023-12-01', amount=1.0`; second upsert `declaration_date=NULL, amount=1.5` | Final row `declaration_date=NULL, amount='1.5'` | Confirms unconditional `EXCLUDED` assignment can overwrite known non-NULL date with NULL (`FR-DIV-04` risk). |
| 3. Multi-values single INSERT with duplicate conflict target | one statement inserting same key twice with `ON CONFLICT DO UPDATE` | **Error:** `CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row a second time` | Confirms PostgreSQL rejects duplicate conflict targets within a single command; loaders must pre-dedupe batches for this execution shape. |
| 4. Deterministic pre-dedup (simulation) | pre-deduped batch keeping last row per key, then `executemany` | **Succeeded**; final row `declaration_date='2023-12-01', amount='2'` | Deterministic in-batch dedupe avoids single-statement cardinality error and makes precedence explicit (precedence rule must be specified). |

## Assessment
- **Batch duplicate-key contract (`DA-21`):** behavior is execution-shape dependent. Multi-row single-statement upsert fails on same-key duplicates; row-wise execution may mask duplicates but leaves outcome dependent on order/driver semantics. Contract should require deterministic in-loader pre-deduplication by conflict key with documented precedence.
- **Date preservation (`FR-DIV-04`):** unconditional overwrite from `EXCLUDED` loses existing non-NULL dates when incoming value is NULL; `COALESCE`/explicit correction-versioning semantics needed per approved contract.
- **Feed/key (`FR-DIV-01`):** test confirms conflict behavior at modeled key; combined with schema/DB evidence (PK omits `feed`), feed-level evidence retention requires key redesign or append-only evidence model (decision pending).

## Limitations
- Synthetic minimal table; does not execute project `DIVIDEND_UPSERT` text or production driver/batch path directly.
- Does not test concurrency, transaction boundaries, or all psycopg execute modes used in production.
- Shared/project database was not tested or modified.

## Recommended follow-up
1. Approve `dividend-batch-key-contract-draft.md` precedence and date-preservation rules.
2. Add project-level tests in isolated test DB covering actual loader batch construction/execution path.
3. Record decision in M2 P0 spec/plan/tasks (`P0-TSK-002`, `TSK-019`).
