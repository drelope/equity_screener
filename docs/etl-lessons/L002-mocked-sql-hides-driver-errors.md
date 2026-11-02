# L002 Mocked connections cannot see driver typing errors

- **Status:** guarded
- **Area:** SQL in stage writers
- **Symptom:** The 2026-11-01 nightly halted at populate_dividend_data with AmbiguousParameter after every unit test passed.
- **Root cause:** One bind parameter used twice under two inferred types (varchar column and a CAST). psycopg binds server-side, so only a real Postgres fails; mocked tests and a SELECT-only probe could not.
- **Detection:** Re-running the stage on three tickers reproduced it at once.
- **Guard:** `tests/test_populate_dividend_data.py`
- **Recurrence check:** Every new INSERT/UPDATE gets a test that executes the real statement in a rolled-back transaction; it must fail on the broken form.
