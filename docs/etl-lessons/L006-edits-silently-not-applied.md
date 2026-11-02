# L006 A scripted edit can silently not apply

- **Status:** monitored
- **Area:** change process
- **Symptom:** A guard meant to cover loose-bucket rows did not apply because the formatter had rewrapped the target line. The repair would have retired 80 placeholders, leaving their tickers with no active row.
- **Root cause:** A string replace that matches nothing succeeds without error.
- **Detection:** The dry run of the repair, which was run before applying and showed 'retired duplicate' lines.
- **Guard:** `tests/test_repair_security_classification.py`
- **Recurrence check:** Assert every scripted replace matched, and run the dry run of any data-changing script before applying it, reading the whole list.
