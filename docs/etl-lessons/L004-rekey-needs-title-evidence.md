# L004 A re-keyed security needs classification evidence for the new CIK

- **Status:** guarded
- **Area:** successor re-key
- **Symptom:** After NAVI moved to its successor CIK, stage 1 deactivated it and minted an 'other' row; its 1,969 prices and 117 scores sat on an inactive row.
- **Root cause:** The successor files no cover XBRL and has no company facts, so stage 1 fell to its weakest signal.
- **Detection:** Running stage 1 for the ticker straight after the re-key.
- **Guard:** `scripts/rekey_security_successor.py`, `tests/test_rekey_security_successor.py`
- **Recurrence check:** After any re-key run stage 1 for the ticker and confirm the same security_id is active.
