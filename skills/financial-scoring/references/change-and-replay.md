# Change and Replay

Load when: replaying scores for a historical date, pruning superseded rows,
applying regime weights or reviewing a historical rank diff.

## Command

```bash
python -m scripts.score_rank --as-of YYYY-MM-DD --prune-superseded
```

The nightly passes `--prune-superseded`; a replay defaults to it unless
`--keep-superseded` is given. Use `--apply-regime-weights` only when the regime
layer is the intended change.

## Replay rules

1. A policy change requires a replay of every affected historical date, not
   only the newest date. Older dates are point-in-time history.
2. Prune only the scored date. Never prune rows from an older date.
3. Compare the new rankings with the prior rankings and report the diff:
   - tickers entering or leaving;
   - rank moves beyond a stated threshold;
   - coverage changes;
   - any security that crossed `MIN_PRESENT_WEIGHT`.
4. Confirm the diff is the intended policy effect. An unexpected diff is a
   stop condition, not a success.
5. Keep `model.predictions` and `model.scores` aligned for the scored date.
6. Do not bundle data, feature, schema or UI changes into the scoring run.

## Verification commands

```bash
python -m scripts.score_rank --as-of YYYY-MM-DD --prune-superseded
python -m pytest -q tests/test_scoring.py tests/test_score_pruning.py \
  tests/test_regime.py tests/test_regime_pipeline.py
```

## Failure handling

- Pending migration: stop; route schema work to `data-storage-schema`.
- Missing or stale features: stop; route to `data-transformation` or
  `data-acquisition`.
- Rank diff is larger than the intended policy change: stop and report.
- A security disappears because its coverage fell below the floor: report it
  explicitly; do not score it as zero.
- Pruning targets an older date: stop.
