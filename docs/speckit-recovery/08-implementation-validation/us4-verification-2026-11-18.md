# US4 Verification: Reproducible Runtime and Blocking Gates

**Feature**: `specs/001-p0-recovery/spec.md`

**Scope**: T030–T035 (P2)

**Status**: Local lock enforcement and regression gates verified; AC-P0-09 remains externally unproven

## T030 — DEC-008 ratification

`decision-unknown-tracker.md` records DEC-008 as ratified: exact pins plus lock-file SHA-256, with separate runtime/dev locks. Per-package hashes are not used because the ratified lock files contain exact pins but no hash column.

## T031 — Locked installs

- `.github/workflows/ci.yml` installs `requirements-dev.lock.txt` in lint, test, security, and reproducibility jobs; `pip-audit` uses `requirements.lock.txt`.
- `Dockerfile` copies and installs `requirements.lock.txt`; the unpinned pillow override was removed.
- Lock files parse with 220 pinned entries each.

## T032 — Dependency identity

`src/crispdm/run_manifest.py` records lock-file SHA-256 values, `lock_strategy=exact_pins_plus_lock_sha256`, `lock_strategy_version=1.0.0`, Python version, OS, and machine identity.

## T033 — Blocking regression gates

A `p0-regression-gates` CI job runs PIT/determinism guards, artifact-contract/promotion-gap guards, advertised dry-run guards, and clean-environment lock parity. These are blocking CI gates.

## T034 — Enforcement reporting

`scripts/check_reproducibility_enforcement.py` now reports `pass_local_enforcement` when the ratified CI/Docker/manifest/policy checks pass. `--require-enforced` still fails until clean-environment parity evidence is recorded.

## T035 — Clean-environment parity

`scripts/check_clean_environment_parity.py` verifies both lock files parse, have matching pin sets (220 each), and produce stable lock identity metadata. Local result: `pass_local_parity`.

## US4 checkpoint

Local runtime identity and blocking gates are verified. Cross-platform clean-build parity, CI execution, and AC-P0-09 closure remain external evidence requirements.
