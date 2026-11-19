"""Walk-forward backtest of the model portfolio over the stored month-end scores.

Read-only against the warehouse. Writes the daily series, the per-period table,
metrics, and a run manifest to ``artifacts/backtests/`` (gitignored) and prints
the metrics. The dashboard reads the newest complete run from that directory.

    python -m scripts.backtest
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.crispdm.backtest import run_from_warehouse
from src.crispdm.ledger_opt_in import persist_run_if_opted_in
from src.crispdm.pit import pit_manifest_metadata
from src.crispdm.run_manifest import build_run_manifest, get_git_state, write_manifest_file

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "backtests"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persist-ledger", action="store_true")
    parser.add_argument("--ledger-dsn")
    parser.add_argument("--i-understand-ledger-write", action="store_true")
    args = parser.parse_args()
    result = run_from_warehouse()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    daily_path = OUTPUT_DIR / f"daily_{stamp}.csv"
    periods_path = OUTPUT_DIR / f"periods_{stamp}.csv"
    metrics_path = OUTPUT_DIR / f"metrics_{stamp}.json"
    manifest_path = OUTPUT_DIR / f"manifest_{stamp}.json"
    result.daily.to_csv(daily_path)
    result.periods.to_csv(periods_path, index=False)
    git_state = get_git_state(Path(__file__).resolve().parents[1])
    resolved_as_of = None
    if not result.daily.empty:
        resolved_as_of = pd.Timestamp(result.daily.index.max()).date().isoformat()
    manifest = build_run_manifest(
        run_type="backtest",
        code_sha=git_state.get("sha"),
        code_dirty=git_state.get("dirty"),
        parameters={"stamp": stamp},
        inputs={
            "source": "warehouse",
            "function": "src.crispdm.backtest.run_from_warehouse",
            "pit": pit_manifest_metadata(
                as_of=resolved_as_of,
                universe_mode="stored_scores_and_prices_draft",
                feature_timing_mode="backtest_rebalance_and_return_windows_draft",
                notes="Draft PIT metadata: backtest consumes stored scores/prices; formation-available/PIT eligibility and leakage controls not fully implemented/verified.",
            ),
        },
        outputs={
            "daily_csv": str(daily_path),
            "periods_csv": str(periods_path),
            "metrics_json": str(metrics_path),
        },
        resolved_as_of=resolved_as_of,
        environment={"script": "scripts.backtest"},
        notes="Walk-forward backtest artifact set (metrics/daily/periods/manifest).",
    )
    metrics_payload = dict(result.metrics)
    metrics_payload["run_id"] = manifest["run_id"]
    metrics_payload["manifest_path"] = str(manifest_path)
    # RM-07 draft placeholders only (DEC-002/004/005 pending): no cost/exposure
    # economics applied and no promotion-grade claim implied.
    metrics_payload["cost_model"] = {
        "status": "draft_pending_dec_004",
        "applied": False,
        "assumptions": None,
    }
    metrics_payload["exposure_matched_benchmark"] = {
        "status": "draft_pending_dec_004",
        "applied": False,
        "definition": None,
    }
    metrics_payload["net_metrics_status"] = "not_computed_draft"
    metrics_payload["promotion_evidence_status"] = "draft_scaffolding_only"
    metrics_path.write_text(json.dumps(metrics_payload, indent=2, sort_keys=True), encoding="utf-8")
    write_manifest_file(manifest, manifest_path)
    ledger_result = persist_run_if_opted_in(
        manifest=manifest,
        outputs=[
            {
                "output_kind": "backtest_manifest",
                "storage_ref": str(manifest_path),
                "content_hash": manifest["hashes"]["manifest_core_hash"],
                "metadata": {"run_type": "backtest"},
            }
        ],
        dsn=args.ledger_dsn,
        enabled=args.persist_ledger,
        acknowledge=args.i_understand_ledger_write,
        recorded_by="scripts.backtest",
    )
    if ledger_result is not None:
        print(f"Ledger: {ledger_result['run_id']} persisted={ledger_result['inserted']}")

    print(
        f"periods: {len(result.periods)} (held {result.metrics['held_periods']}, "
        f"cash {result.metrics['cash_periods']})"
    )
    print(f"daily observations: {len(result.daily)}")
    for key in sorted(result.metrics):
        value = result.metrics[key]
        text = f"{value:.4f}" if isinstance(value, float) else str(value)
        print(f"  {key}: {text}")
    print(f"run_id: {manifest['run_id']}")
    print(
        f"wrote {daily_path.name}, {periods_path.name}, {metrics_path.name} and {manifest_path.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
