# Dividend Equity Screener — Requirements

This is the light requirements artifact for the Dividend Equity Screener. It
records the business objectives, the screening rules, and the acceptance
criteria so they survive knowledge loss. It deliberately stays one page; the
authoritative technical design remains `../README.md`. Values below are drawn
from the code (`src/crispdm/scoring.py`, `src/crispdm/config.py`,
`scripts/populate_reference_tables.py`) and are the source of truth for the
web UI caption in `app/views/screener.py`.

## 1. Business objectives

1. Identify US-listed equities that pay an **income** today and are likely to
   keep paying it **sustainably**, with strong **legal / economic rights**.
2. Rank and screen the universe rather than score a hand-picked watchlist.
3. Stay audit-friendly: every raw SEC/OpenBB payload and every derived fact is
   traceable to provenance (`audit.source_lineage`, content hashes, provider
   tags).
4. Run **locally first**, then move to Azure only after the local MVP is
   reproducible and walk-forward evaluation is passing (`azure/README.md`).

## 2. Screening universe

- **Membership rule:** a security is screened only when
  `reference.securities.dividend = TRUE AND active = TRUE`. This defines the
  dividend universe gating every ETL stage
  (`ix_securities_dividend_active` partial index).
- `dividend = TRUE` only when a positive dividend or owner-distribution fact
  is reported by SEC Company Facts.
- Sources: SEC EDGAR/XBRL (facts, submissions, documents, taxonomy concepts)
  and OpenBB (historical prices, dividends, ticker profiles).

## 3. Scoring weights (composite score)

The composite is the weighted sum of six factor sub-scores; each sub-score is a
percentile rank of the factor across the current feature date
(`src/crispdm/scoring.py`, `WEIGHTS` must sum to 1 — enforced by tests):

| Factor | Weight | Basis |
|---|---|---|
| dividend_income_score | **25%** | percentile of dividend yield |
| sustainability_score | **20%** | 0.5·coverage + 0.2·growth + 0.3·payout (inverted) |
| legal_rights_score | **25%** | preferred-stock legal terms / security-terms lookup |
| appreciation_score | **15%** | 0.6·252d momentum + 0.4·63d momentum |
| risk_score | **10%** | inverted percentile of 252d realized volatility |
| valuation_score | **5%** | 0.4·earnings yield + 0.4·fcf yield + 0.2·price/book (inverted) |

`model.predictions` thresholds the composite against `precision_threshold`
(0.5 by default). That is a relative rank, not a calibrated probability.

## 4. Learning goals (ML layer)

**Decision, 2026-10-06: the ML model is not adopted; the rule-based composite is the
product.** The walk-forward evaluation has returned NO-GO under every feature version
(v3, v4, v5): the label is 99.6% positive, so the model predicts "sustainable" for
everything (balanced accuracy 0.500, negative recall 0.000). The evaluation, labelling
and checkpoint code are kept as diagnostics and for any future revisit; nothing in
scoring or the nightly depends on them.

- ML targets are **offline labels only** — `model.features.target_sustainable_dividend`
  is never fabricated; it must be populated from future dividend events and
  financial coverage (see `model-labeling-plan.md`).
- The walk-forward logistic regression (`src/crispdm/model.py:walk_forward`, trained on
  70% of feature dates and evaluated on the remaining 30%) is the evaluated candidate,
  not the production scorer.

## 5. Acceptance criteria

| Criterion | Gate | Evidence |
|---|---|---|
| Reproducible local MVP | installs from pinned `requirements.txt`; pipeline stages run from repo root | CI + `docker compose up -d postgres` + `python -m scripts.run_full_etl` |
| Data lineage | every raw row keeps `raw_payload`, `content_hash`, `provider`; `audit.*` populated | `scripts.populate_audit`, schema comments |
| Preference screening recall | *Not applicable while the ML model is not adopted* (decision 2026-10-06). If it is revisited: walk-forward `recall >= MIN_RECALL` (default **0.30**) | `python -m scripts.evaluate_walk_forward` (checkpoint in `audit.model_runs`) |
| API security | `/health` public; all other routes require `X-API-Key`; 503 when key unconfigured | `api/main.py` |
| SEC compliance | `SEC_USER_AGENT` must be a real contact string before any SEC request | enforced in `src/crispdm/sec_client.py` |
| Quality gate | `ruff check .`, `ruff format --check .`, `pytest` all green in CI | `.github/workflows/ci.yml` |

## 6. Out of scope (for the local MVP)

- Intraday/real-time data; the pipeline is nightly-batch.
- Broker integration or live order execution.
- Non-US / dual-listed universes beyond what SEC company tickers provide.
- Multi-user SSO; access is single-key.

## 7. Priority order (when in doubt)

1. Correctness and auditability of the ETL/ingestion.
2. Rule-based score quality (coverage, point-in-time correctness of every input).
3. Reproducibility (pinned deps, digests) before any Azure migration.
4. Feature depth (more/richer factors) over cosmetic UI.