"""
Run and record the walk-forward evaluation checkpoint for the ML target.

Pulls ``model.features`` rows that carry an offline label
(``target_sustainable_dividend`` not null), runs
``src.crispdm.model.walk_forward`` at the configured ``MIN_RECALL``, persists
the metrics to ``audit.model_runs``, and writes a reviewable JSON snapshot
under ``data/walk_forward_checkpoint.json``.

This command is the formal Go/No-Go record for the Azure pilot gate
("move to Azure only after ... walk-forward evaluation is passing"):

- no labeled rows / too few labels  -> informational, exit 0, no checkpoint
- recall >= MIN_RECALL              -> PASS (exit 0)
- recall <  MIN_RECALL              -> FAIL (exit 1)

Usage:
    python -m scripts.evaluate_walk_forward
    python -m scripts.evaluate_walk_forward --min-recall 0.30
    python -m scripts.evaluate_walk_forward --out /tmp/checkpoint.json
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.crispdm.config import settings
from src.crispdm.db import engine, read_df
from src.crispdm.model import FEATURES, walk_forward

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_PATH = PROJECT_ROOT / "data" / "walk_forward_checkpoint.json"
MIN_LABELED_ROWS = 10
MODEL_VERSION = "logistic_regression_walk_forward_v1"


def load_labeled_features():
    """Feature rows that have an offline label, for the walk-forward split."""
    columns = ", ".join(FEATURES)
    return read_df(
        f"""
        SELECT security_id, as_of_date, target_sustainable_dividend, {columns}
        FROM model.features
        WHERE target_sustainable_dividend IS NOT NULL
        """
    )


def split_dates(as_of):
    dates = sorted(pd.to_datetime(as_of).drop_duplicates())
    cut = max(1, int(len(dates) * 0.70))
    return [d.date().isoformat() for d in dates], cut


def make_checkpoint(run_id, min_recall, metrics, dates, cut, n_rows):
    """Build the reviewable checkpoint dict (pure; kept separate for tests)."""
    return {
        "run_id": str(run_id),
        "model_version": MODEL_VERSION,
        "feature_version": "features_v1",
        "data_version": "sec_xbrl_v1",
        "min_recall": min_recall,
        "training_start": str(dates[0]),
        "training_end": str(dates[cut - 1]),
        "test_start": str(dates[cut]),
        "test_end": str(dates[-1]),
        "n_feature_rows": int(n_rows),
        "n_train": int(cut),
        "n_test": int(len(dates) - cut),
        "features": FEATURES,
        "metrics": {k: (float(v) if v is not None else None) for k, v in metrics.items()},
        "gate_passed": bool(metrics["recall"] >= min_recall),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def persist(checkpoint):
    params = json.dumps(checkpoint["parameters"], default=str)
    with engine.begin() as c:
        c.execute(
            text(
                """
                INSERT INTO audit.model_runs
                  (run_id, model_version, feature_version, data_version,
                   training_start, training_end, test_start, test_end,
                   precision, recall, f1, pr_auc, roc_auc, accuracy, parameters)
                VALUES
                  (:run, :mv, :fv, :dv, :trs, :tre, :tes, :tee,
                   :precision, :recall, :f1, :prauc, :rocauc, :acc, :params)
                """
            ),
            {
                "run": checkpoint["run_id"],
                "mv": checkpoint["model_version"],
                "fv": checkpoint["feature_version"],
                "dv": checkpoint["data_version"],
                "trs": checkpoint["training_start"],
                "tre": checkpoint["training_end"],
                "tes": checkpoint["test_start"],
                "tee": checkpoint["test_end"],
                "precision": checkpoint["metrics"].get("precision"),
                "recall": checkpoint["metrics"].get("recall"),
                "f1": checkpoint["metrics"].get("f1"),
                "prauc": checkpoint["metrics"].get("pr_auc"),
                "rocauc": checkpoint["metrics"].get("roc_auc"),
                "acc": checkpoint["metrics"].get("accuracy"),
                "params": params,
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-recall",
        type=float,
        default=settings.min_recall,
        help="Minimum recall gate (default: MIN_RECALL from config / .env)",
    )
    parser.add_argument(
        "--out", type=Path, default=CHECKPOINT_PATH, help="Where to write the JSON checkpoint"
    )
    args = parser.parse_args()

    df = load_labeled_features()
    if df.empty or len(df) < MIN_LABELED_ROWS:
        print(
            f"[info] {len(df)} labeled feature rows (< {MIN_LABELED_ROWS}); "
            "populate target_sustainable_dividend first "
            "(see docs/model-labeling-plan.md). No checkpoint written, exiting 0."
        )
        return 0

    dates, cut = split_dates(df["as_of_date"])
    model, metrics, test = walk_forward(df, min_recall=args.min_recall)
    checkpoint = make_checkpoint(uuid.uuid4(), args.min_recall, metrics, dates, cut, len(df))
    checkpoint["parameters"] = {"threshold": metrics["threshold"], "class_weight": "balanced"}
    persist(checkpoint)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(checkpoint, indent=2, default=str) + "\n")

    recall = checkpoint["metrics"]["recall"]
    print(
        f"[checkpoint] {checkpoint['run_id']} test {checkpoint['test_start']}..{checkpoint['test_end']} "
        f"recall={recall:.3f} (gate {args.min_recall}) "
        f"precision={checkpoint['metrics']['precision']:.3f} "
        f"pr_auc={checkpoint['metrics']['pr_auc']:.3f} "
        f"-> {'PASS' if checkpoint['gate_passed'] else 'FAIL'}"
    )
    print(f"[checkpoint] written {args.out}")
    return 0 if checkpoint["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
