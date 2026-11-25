# Run-Keyed Output Store Draft (RM-05, non-applied)

Status: **draft scaffolding only**. This is not wired into the app or pipelines,
writes no database rows, and does not satisfy `AC-P0-08`.

## Purpose

`src/crispdm/output_store.py` gives scores, reports, and AI outputs a stable
run-keyed file location so a run does not overwrite prior artifacts. It is the
file-layer counterpart to the candidate `audit.run_outputs` refs in V0110.

## Storage contract

- Layout: `<root>/<run_id>/<output_kind>.json`.
- `run_id` and `output_kind` must be safe path components; traversal and `..` are rejected.
- Content identity: SHA-256 of canonical JSON, using `src.crispdm.run_manifest.sha256_hex`.
- Identical reruns are idempotent no-ops.
- A different payload for the same `run_id`/`output_kind` raises
  `OutputConflictError`; the existing file is never overwritten.
- Writes go through a `.tmp` file renamed into place.

## CLI

```bash
python3 scripts/persist_run_output.py \
  --payload payload.json --run-id run-1 --output-kind score \
  --root artifacts/run_outputs

python3 scripts/persist_run_output.py \
  --payload payload.json --run-id run-1 --output-kind score \
  --root artifacts/run_outputs --write --i-understand-run-output-write
```

Default is dry-run. `--write` requires the explicit acknowledgement flag.
Exit codes: 0 = dry-run/write succeeded; 1 = validation/conflict; 2 = usage.

## Ledger bridge

`build_ledger_output_ref()` converts a stored ref into the payload shape accepted
by `src.crispdm.manifest_store.build_output_rows()`. `register_output_ref(conn, ref)`
inserts that ref into the candidate ledger using the caller's transaction and the
existing append-only rules. Neither is called automatically.

## Explicit gaps

- No pipeline or Reports Center wiring.
- No historical as-of selection or UI provenance linkage.
- No database enforcement, retention, or role checks.
- No unique `run_id` governance across producers.
- No claim that mutable outputs are controlled or that `AC-P0-08` is verified.
