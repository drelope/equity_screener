# L001 An issuer's stored titles must not classify its untitled tickers

- **Status:** guarded
- **Area:** stage 1 (populate_reference_tables)
- **Symptom:** Persisting 319 cover titles made stage 1 deactivate 250 genuine common stocks (MCHP, AFG, CMCSA; 5,973 scores) and mint derivative rows; TC Energy's OTC line TCANF was typed a derivative.
- **Root cause:** Stage 1 bound the issuer's whole stored title list to any ticker without its own title, though each stored title is another ticker's exact title. The result flipped as soon as one sibling's title was stored.
- **Detection:** A stage-1 dry run over the whole issuer (every ticker, not only the changed ones) showed active-flag changes and minted rows.
- **Guard:** `scripts/populate_reference_tables.py`, `tests/test_resolve_security_name.py`, `scripts/post_nightly_check.py`
- **Recurrence check:** `python -m pytest tests/test_resolve_security_name.py -q`; after any title load, run stage 1 for every ticker of the touched issuers and require 0 minted and 0 active-flag changes.
