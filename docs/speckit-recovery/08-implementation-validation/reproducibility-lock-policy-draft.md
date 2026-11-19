# Reproducibility / Lock Policy Draft (RM-06, DEC-008 scaffolding)

| Field | Value |
|---|---|
| Date | 2026-11-16 |
| Status | **Ratified 2026-11-18** — exact pins plus lock-file SHA-256 (`DEC-008`) |
| Scope | Dependency/runtime lock artifacts, CI hooks, manifest linkage |

## Current artifacts
- `requirements.txt`, `requirements-dev.txt`: human-maintained dependency intent (current install inputs; dev pins `pytest`, `ruff`, `pip-audit`).
- `requirements.lock.txt`: ratified exact-pin runtime lock; identity is the file SHA-256 plus exact package pins. No per-package hashes are used.
- `requirements-dev.lock.txt`: ratified exact-pin development/CI lock; identity is the file SHA-256.
- `scripts/check_reproducibility_locks.py`: validates lock file presence and pinned-entry parseability (scaffolding check).
- `.github/workflows/ci.yml`: added non-blocking `reproducibility` job to run lock check and dry-run lock resolution.

## Known gaps / decisions required (DEC-008)
- Ratified format: plain pinned requirements files with SHA-256 identity and separate runtime/dev locks.
- Hash policy: no per-package hashes; verify lock file SHA-256 and record it in manifests.
- Enforce locked installs in CI and Docker; local/dev workflow must use the same lock files.
- Capture lock hashes, strategy version, Python version, OS, and machine identity in run manifests.
- Reconcile `requirements.txt` (largely unpinned) and large environment freeze (includes platform/CUDA-specific packages) with deployable runtime images.

## Enforcement gap checker (2026-11-16)

`scripts/check_reproducibility_enforcement.py` is a read-only draft reporter. It checks that lock files parse, that CI/Docker do not install from unpinned `requirements*.txt`, that `--require-hashes` is present, that the manifest code captures lock hashes, that the Compose Postgres image is digest-pinned, and that this policy remains a DEC-008 draft.

```bash
python3 scripts/check_reproducibility_enforcement.py
python3 scripts/check_reproducibility_enforcement.py --json
python3 scripts/check_reproducibility_enforcement.py --require-enforced  # fails by design
```

After US4 enforcement, CI and Docker install from lock files. `scripts/check_reproducibility_enforcement.py` still tracks residual parity evidence; `enforcement_claim=false` remains until clean-environment parity is verified.

## Non-claims
- No cross-platform guarantee or AC-P0-09 closure is claimed. Clean-environment parity evidence remains required.
