# L005 Duplicate identities hold history; merge, do not delete

- **Status:** guarded
- **Area:** reference.securities twins
- **Symptom:** 160 securities had an inactive twin; the stage-2 and stage-3 loaders had filled prices, dividends and fundamentals on both, and only the active row held scores.
- **Root cause:** A ticker typed two ways keeps both rows, and the loaders populate each.
- **Detection:** A content comparison of every dependent table, ignoring ids and load timestamps. 60 twins were fully redundant, 100 held history the active row lacked, and 19 of those had a price series on a different adjustment basis (TORO, factor 1.443, unexplained).
- **Guard:** `scripts/merge_duplicate_identities.py`, `tests/test_merge_duplicate_identities.py`
- **Recurrence check:** `python -m scripts.merge_duplicate_identities --ticker T` reports redundancy; a refusal is a finding to decide, never to override.
