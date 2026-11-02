# L007 Editing a CRLF file through Python text mode rewrites it as LF

- **Status:** guarded
- **Area:** repository hygiene
- **Symptom:** api/main.py and two test files showed whole-file diffs after a two-line edit. 56 tracked files are CRLF and the rest are LF.
- **Root cause:** Python's text mode converts CRLF to LF on read, so `open(p).read()` followed by `open(p, "w").write(...)` strips every CR. This was first blamed on `ruff format`, which a direct test showed preserves a file's endings (615 CR lines before and after); the diagnosis was wrong until measured.
- **Detection:** `git ls-files --eol` on every changed file before committing: index and working endings must match.
- **Guard:** `scripts/check_line_endings.py`, `tests/test_check_line_endings.py`
- **Recurrence check:** `python -m scripts.check_line_endings` must pass before a commit. Edit CRLF files with `newline=""` on both the read and the write, or with an editor that preserves endings.
