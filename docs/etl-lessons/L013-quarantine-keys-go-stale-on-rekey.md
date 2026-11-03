# L013 Quarantine keys go stale when a security is re-keyed

- **Status:** guarded
- **Area:** quarantine registry (`audit.quarantined_values`) and security re-keying
- **Symptom:** `test_quarantined_fundamentals_values_are_left_in_place` failed with 22 "erased" values. Nothing had been erased: all 22 were still stored, unchanged, under successor security ids (AREB, UUU, PCTTU, SOUL, ALMU, CJMB, PW, ERNA, TDACU).
- **Root cause:** The registry keys a value by `security_id|period_end|fiscal_period|filed` and nothing updates that key when a security is re-keyed or merged. V0093 repaired this once after the V0092 merge; a later successor re-key reopened it.
- **Detection:** The registry-versus-reality test, then a join of each unmatched entry to the successor found by its recorded `(ticker, cik)`, comparing key and value: 22 of 22 matched.
- **Guard:** `tests/test_quarantine_registry.py`, `sql/migrations/V0105_quarantine_row_key_after_successor_rekey.sql`
- **Recurrence check:** Run `python -m pytest -q tests/test_quarantine_registry.py` after any re-key or merge of `reference.securities`. A failure means re-key the unresolved entries to the successor (as V0093 and V0105 do), and close, never delete, any that duplicate an entry the successor already holds.
