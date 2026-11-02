# L007 The formatter can flip a CRLF file to LF

- **Status:** open
- **Area:** repository hygiene
- **Symptom:** ruff format converted api/main.py and two test files from CRLF to LF, turning small edits into whole-file diffs.
- **Root cause:** The repository mixes line endings and has no .gitattributes policy.
- **Detection:** git ls-files --eol on every file a change touched, before committing.
- **Guard:** none yet; a .gitattributes policy or a pre-commit check is the fix.
- **Recurrence check:** `git ls-files --eol <changed files>` must show the same index and working endings.
