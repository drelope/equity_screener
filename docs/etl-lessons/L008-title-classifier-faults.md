# L008 Cover-title classifier faults surface only at full scale

- **Status:** guarded
- **Area:** title classifier (classify_security_type)
- **Symptom:** Loading every issuer's cover found ADS read as preferred, stray spacing dropping common stock to equity, SPAC units read as warrants (all fixed), and common shares with attached rights read as derivatives (TRP, poison-pill shares; fixed).
- **Root cause:** Substring matching on free text, tested on a few hundred titles.
- **Detection:** Measuring a classifier change against every stored title and name, listing each distinct change before shipping.
- **Guard:** `src/crispdm/sec_client.py`, `tests/test_security_type_vocabulary.py`
- **Recurrence check:** Diff old and new classifier over all stored titles; every changed class must be intended.
