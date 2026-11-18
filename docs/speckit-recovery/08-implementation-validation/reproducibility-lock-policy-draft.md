# Reproducibility / Lock Policy Draft (RM-06, DEC-008 scaffolding)

| Field | Value |
|---|---|
| Date | 2026-11-16 |
| Status | **Draft/scaffolding only** — `DEC-008` pending approval |
| Scope | Dependency/runtime lock artifacts, CI hooks, manifest linkage |

## Current artifacts
- `requirements.txt`, `requirements-dev.txt`: human-maintained dependency intent (current install inputs; dev pins `pytest`, `ruff`, `pip-audit`).
- `requirements.lock.txt`: generated from local `.venv` (`pip freeze`) on 2026-11-16; **draft snapshot**, not ratified as cross-platform/runtime lock.
- `requirements-dev.lock.txt`: draft dev snapshot (currently same generated environment).
- `scripts/check_reproducibility_locks.py`: validates lock file presence and pinned-entry parseability (scaffolding check).
- `.github/workflows/ci.yml`: added non-blocking `reproducibility` job to run lock check and dry-run lock resolution.

## Known gaps / decisions required (DEC-008)
- Choose authoritative lock tool/format (e.g. `pip-tools`/`uv`/hash-pinned requirements/constraints), target platforms, and runtime vs dev lock separation.
- Define hash policy (`--require-hashes`) and trusted index/mirror behavior.
- Enforce locked installs in CI, Docker build/runtime, and local/dev workflows (currently **not enforced**).
- Capture lock hash/version and environment identifiers in immutable run manifests/DB run ledger.
- Reconcile `requirements.txt` (largely unpinned) and large environment freeze (includes platform/CUDA-specific packages) with deployable runtime images.

## Enforcement gap checker (2026-11-16)

`scripts/check_reproducibility_enforcement.py` is a read-only draft reporter. It checks that lock files parse, that CI/Docker do not install from unpinned `requirements*.txt`, that `--require-hashes` is present, that the manifest code captures lock hashes, that the Compose Postgres image is digest-pinned, and that this policy remains a DEC-008 draft.

```bash
python3 scripts/check_reproducibility_enforcement.py
python3 scripts/check_reproducibility_enforcement.py --json
python3 scripts/check_reproducibility_enforcement.py --require-enforced  # fails by design
```

Current repo result: `pass_draft_gap_report` with gaps for CI lock install/hash policy, Dockerfile lock install/hash policy, unpinned `requirements.txt`, and the unpinned pillow override. `enforcement_claim=false`; no AC-P0-09 verification is implied.

## Non-claims
- No reproducible runtime guarantee, no CI/Docker lock enforcement, and no AC-P0-09 verification is claimed from this draft.
