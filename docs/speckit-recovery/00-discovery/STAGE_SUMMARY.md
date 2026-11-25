# Stage 0 — Discovery: Stage Summary

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-11-15 |
| Repo HEAD | `d748cea` |
| Scope | Factual map of the existing equity research platform; no source/test/config modifications |
| Output | This directory (`docs/speckit-recovery/00-discovery/`) |

## 1. What Was Done

- Created the discovery output directory and nine registers.
- Ran four independent read-only explore passes:
  1. Architecture and services.
  2. Data sources, providers, and storage (including read-only live PostgreSQL queries).
  3. Analytics, screening, ranking, backtesting, reporting, and AI.
  4. Tests, CI, scheduling, deployment, and dependencies.
- Cross-checked material points of disagreement with direct commands and live queries.
- Every finding carries evidence, file path, function/class, CRISP-DM phase, risk, recommended action, confidence, and type.
- No source code, tests, or configs were modified.

## 2. Files Produced

| File | Contents |
|---|---|
| `system-context-map.md` | Actors (ACT-), external systems (EXT-), context diagram, findings |
| `component-catalog.md` | Components (CMP-01…CMP-20), interaction diagram, findings |
| `service-inventory.md` | Services (SVC-01…SVC-11), runtime topology, current operating state, findings |
| `data-flow-inventory.md` | Sources, flows (DF-01…DF-20), warehouse inventory with live row counts, data-quality findings |
| `dependency-graph.md` | Internal Mermaid dependency graph, pinned third-party versions, dependency findings |
| `entry-points.md` | UI workflows, API endpoints, CLIs, jobs/schedulers (EP-01…EP-24), findings |
| `capability-inventory.md` | 25 capabilities marked Present/Partial/Absent with evidence, findings |
| `tech-stack.md` | Stack table, observed decisions, absent technologies, findings |
| `repo-map.md` | Directory tree, directory roles, key module map, findings |

## 3. Cross-Checked Facts

| Fact | Independent checks | Result |
|---|---|---|
| Test module count | Explore pass said 107 (architecture), 108 (analytics); direct `ls tests/test_*.py \| wc -l` | **107** |
| Root scripts with `__main__` | Direct `grep -rl '^if __name__' scripts/*.py \| wc -l` | **56** |
| Migration files vs applied | `ls sql/migrations/V*.sql \| wc -l` vs `schema_migrations.max(version)` | **104 files, max 106, 105 ledger rows** |
| Skills directories | `ls -d skills/*/ \| wc -l` | **23 = 22 skills + `_template`** |
| `requirements.txt` pinning | `grep -c '=='` in worktree vs `git show HEAD:requirements.txt` | **0 pins in worktree; 20 pins at HEAD (uncommitted change)** |
| `raw.market_data.adjusted_close` | Live query | **0 non-null of 9,823,774 (100% NULL)** |
| `dividends` schema | Live `information_schema.tables` | **0 tables** |
| Nightly runs | Live `audit.nightly_runs` | **53 rows; last success run 56 on 2026-11-09; runs 57-60 failed** |
| Analytics agent reported 108 test modules | Cross-check | Disagreement resolved to **107** |
| Architecture agent reported 104 migrations | Cross-check | **104 files**, ledger max version **106**; noted in CMP-F13 |

## 4. Top Findings for Later Stages

1. **Price adjustment is implicit and unverified.** `adjusted_close` is 100% NULL; split events live in `raw.corporate_actions`; dividend amounts are restated to split basis in code. This is the highest-priority focus for Stage 1A and 1C. `[V 1.0]`
2. **The warehouse is stale.** Four consecutive nightly failures (runs 57-60); last market data 2026-11-09. `[V 1.0]`
3. **Dependency reproducibility is broken in the worktree.** `requirements.txt` has zero pins; no lockfile; Python version drift across README/Docker/local. `[V 1.0]`
4. **Production scoring is rule-based, ML is gated.** ML pipeline and walk-forward gate exist but are not the production ranker; several model features are placeholders. `[V 0.95]`
5. **Watchlist and alerts are absent.** `[V 0.95]`
6. **AI summarization is absent;** only optional local LLM worksheet drafting exists. `[V 0.95]`
7. **Backtest caveats are material:** survivor-only history, no trading costs, identity fragmentation. `[V 0.95]`
8. **Governance is a strength:** lineage, data quality, quarantine, freshness, run history, ops allowlist. `[V 0.98]`

## 5. Open Questions

1. What is the intended canonical price-adjustment policy (split basis, dividend reinvestment, provider precedence)? Stage 1A must answer from code.
2. Should the uncommitted `requirements.txt` change (unpinned) be reverted or adopted with a lock strategy?
3. Are watchlist/alerts and AI summarization in scope? They are currently absent.
4. Is the ML path intended for production adoption, or permanent research?
5. Why did runs 57-60 fail? `audit.nightly_runs` stores stage names but not root-cause detail; logs are needed.
6. Should `dividends` schema, `market.*` intraday tables, `sql/silver_schema.sql`, and `reference.v_us_instruments` be removed or adopted?
7. Is Azure deployment in scope for this recovery, or documentation-only future state?

## 6. Point-in-Time Caveats for This Stage

- Findings reflect HEAD `d748cea` plus an uncommitted `requirements.txt` change and untracked recovery files.
- Live DB queries reflect the warehouse as of 2026-11-15; it is stale relative to the calendar.
- No ETL, tests, backtest, API, or containers were executed by the architecture/data/analytics passes; the test pass collected 1,929 tests and ran targeted subsets only. Full-suite status is unknown; `.pytest_cache/v/cache/lastfailed` has 25 stale failed node IDs.
- "Absent" findings are based on repository-wide search and are marked Inferred where a runtime-only capability could exist.

## 7. Handoff Inputs

- Stage 1A (price adjustment audit): `data-flow-inventory.md` DF-06, DF-07, DF-10, DF-F01…DF-F09; `component-catalog.md` CMP-03, CMP-07; `capability-inventory.md` CAP-08.
- Stage 1B (bias/temporal integrity): `component-catalog.md` CMP-F07, CMP-F09; `data-flow-inventory.md` DF-11, DF-16; `capability-inventory.md` CAP-17.
- Stage 1C (testing): `tech-stack.md` TS-F08; `service-inventory.md` SVC-F07; test inventory from the tests pass (107 modules, ~1,929 tests, no coverage config).
- Stage 1D (determinism/auditability): `dependency-graph.md` DEP-F01…DEP-F10; `tech-stack.md` TS-F01…TS-F05; `component-catalog.md` CMP-F02, CMP-F12.
- Stage 2 (requirements/RTM): all registers above; especially capability status and the top findings.
