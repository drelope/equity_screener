# L013 Quarantine keys go stale when a security identity is deleted or merged

- **Status:** guarded
- **Area:** quarantine registry (`audit.quarantined_values`) and twin-identity merges
- **Symptom:** `test_quarantined_fundamentals_values_are_left_in_place` failed with 22 "erased" values. Nothing had been erased: all 22 were still stored, unchanged, under successor security ids (AREB, UUU, PCTTU, SOUL, ALMU, CJMB, PW, ERNA, TDACU).
- **Root cause:** The registry keys a value by `security_id|period_end|fiscal_period|filed`, and `merge_duplicate_identities` deleted the twin's `security_id` without touching the registry. (`rekey_security_successor` keeps the same `security_id`, so it is not a cause; an earlier note blaming it was wrong.) V0093 repaired this once after the V0092 merge; a later merge reopened it.
- **Detection:** The registry-versus-reality test, then a join of each unmatched entry to the successor found by its recorded `(ticker, cik)`, comparing key and value: 22 of 22 matched.
- **Guard:** `tests/test_quarantine_registry.py`, `scripts/merge_duplicate_identities.py`, `tests/test_merge_duplicate_identities.py`, `scripts/post_nightly_check.py`, `tests/test_post_nightly_check.py`, `sql/migrations/V0105_quarantine_row_key_after_successor_rekey.sql`
- **Recurrence check:** Run `python -m pytest -q tests/test_quarantine_registry.py` after any merge of `reference.securities`. `merge_twins` and `delete_twins` now carry the entries to the active identity themselves (closing, never deleting, any that duplicate an entry it already holds); a failure means another path deleted an id, so repair it as V0093 and V0105 do.
