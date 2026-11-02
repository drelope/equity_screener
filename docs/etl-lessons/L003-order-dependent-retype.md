# L003 Retype in place before stage 1 sees the evidence

- **Status:** guarded
- **Area:** classification repair and stage 1
- **Symptom:** Loading cover titles made stage 1 retype securities by inserting a new identity and deactivating the old one, stranding prices and scores.
- **Root cause:** reference.securities is unique on (cik, ticker, type, dividend). A changed type is a new key, so stage 1 mints. Only the repair updates in place, and it must run first; it must not retire the only active row when the twin is inactive, and it must consider every stored type: 28 securities stored as debt, future, option or corporate bond were minted by stage 1 (1,806 scores) because the repair did not list those types.
- **Detection:** Row counts before and after a stage-1 run on the affected tickers: total and active must not grow.
- **Guard:** `scripts/repair_security_classification.py`, `tests/test_repair_security_classification.py`
- **Recurrence check:** `python -m scripts.repair_security_classification --dry-run` must list the intended changes only, with no retired duplicates; then stage 1 for those tickers must leave total and active counts unchanged.
