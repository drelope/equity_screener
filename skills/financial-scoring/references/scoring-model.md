# Scoring Model

Load when: implementing or reviewing a weight, component, coverage, regime or
prediction-threshold change.

## Ownership

`business-understanding` decides the universe rule, weights and acceptance
criteria in `docs/requirements.md`. `financial-scoring` implements the approved
decision, replays affected dates and reports the diff. It does not choose the
policy.

## Composite

The composite is the weighted mean of measured components, renormalised over
the available weight. `src/crispdm/scoring.py` is authoritative for the current
`WEIGHTS` and component formulas.

Current baseline weights:

| Component | Weight |
|---|---|
| `dividend_income_score` | 1/3 (33.33%) |
| `sustainability_score` | 4/15 (26.67%) |
| `appreciation_score` | 1/5 (20.00%) |
| `risk_score` | 2/15 (13.33%) |
| `valuation_score` | 1/15 (6.67%) |

`legal_rights_score` is retired from the composite; the column remains NULL.
The weights must sum to 1.

## Coverage

`score_coverage` is the measured share of baseline weight.
`MIN_PRESENT_WEIGHT` is 0.50: a security below the floor is not scored, not
silently scored as zero. A component that is all NULL is an upstream finding,
not a constant to impute.

## Regime layer

`src/crispdm/regime.py` and `src/crispdm/regime_pipeline.py` own the regime
weight matrix and its pipeline. `--apply-regime-weights` is used only when the
regime layer is the intended change. The regime blend cannot override the
baseline coverage floor.

## Predictions and rankings

`model.predictions` thresholds the composite. It is a relative rank, never a
calibrated probability or a forecast. `model.rankings` and `model.scores` must
describe the same scored date and agree on coverage.

## Definition of done

- The approved policy decision is linked.
- The smallest formula or threshold changed.
- Tests prove the weights, coverage floor and ranking contract.
- A historical replay reports the rank diff.
- No interpretation or recommendation is baked into the metric.
