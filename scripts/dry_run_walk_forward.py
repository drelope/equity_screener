"""
Deterministic dry-run demonstration of a passing labeled walk-forward run.

No database, no network. Builds a small synthetic labeled sample in memory,
runs the *real* ``src.crispdm.model.walk_forward`` gate at ``MIN_RECALL``, and
writes the checkpoint JSON exactly like ``scripts.evaluate_walk_forward`` (the
production path used once ``raw.dividend_data`` has accrued).

Purpose: prove the Go/No-Go mechanism end-to-end today. It is a demonstration
only — the labels are invented here, which is why this never touches
``model.features`` / ``audit.model_runs``. With real accrued data the identical
path runs through:
    python -m scripts.label_targets
    python -m scripts.evaluate_walk_forward

Usage:
    python -m scripts.dry_run_walk_forward
    python -m scripts.dry_run_walk_forward --min-recall 0.30 --out /tmp/wf.json
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.evaluate_walk_forward import make_checkpoint, split_dates
from src.crispdm.config import settings
from src.crispdm.model import FEATURES, walk_forward


def synthetic_labeled_sample(n_days=540, per_snap=12, seed=7, start="2023-01-02"):
    """Seeded synthetic labeled features (separability => recall ~1.0).

    The span has to clear the label embargo. ``walk_forward`` only keeps
    training rows whose full 365-day window closes before the test period, and
    a 70/30 cut puts the test start at ~0.7 * n_days, so the sample needs
    ``0.7 * n_days > 365`` -- about 522 dates. A six-month fixture leaves
    nothing trainable and fails for the wrong reason.
    """
    rng = np.random.RandomState(seed)
    snapshots = []
    for day in range(n_days):
        as_of = pd.Timestamp(start) + pd.Timedelta(days=day)
        n = per_snap
        score = rng.rand(n)
        frame = {
            k: rng.rand(n) * (0.2 + score) + (0.4 * score)
            for k in FEATURES
            if k not in {"dividend_coverage", "dividend_yield"}
        }
        frame["dividend_coverage"] = score + rng.rand(n) * 0.05  # near-separable
        frame["dividend_yield"] = score * 0.03 + rng.rand(n) * 0.003
        frame["target_sustainable_dividend"] = (score > 0.5).astype(int)
        frame["security_id"] = [f"SYN-{day}-{j}" for j in range(n)]
        frame["as_of_date"] = as_of
        snapshots.append(pd.DataFrame(frame))
    return pd.concat(snapshots, ignore_index=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-recall",
        type=float,
        default=settings.min_recall,
        help="Minimum recall gate (default: MIN_RECALL from config / .env)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/walk_forward_dry_run.json"),
        help="Where to write the checkpoint JSON (default /tmp)",
    )
    args = parser.parse_args()

    df = synthetic_labeled_sample()
    dates, cut = split_dates(df["as_of_date"])
    model, metrics, test = walk_forward(df, min_recall=args.min_recall)
    checkpoint = make_checkpoint(uuid.uuid4(), args.min_recall, metrics, dates, cut, len(df))
    checkpoint["parameters"] = {
        "threshold": metrics["threshold"],
        "class_weight": "balanced",
        "scope": "dry-run (synthetic, in-memory; no DB writes)",
    }
    checkpoint["scope"] = "dry-run"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(checkpoint, indent=2, default=str) + "\n")

    recall = checkpoint["metrics"]["recall"]
    print(
        f"[dry-run] {checkpoint['run_id']} test {checkpoint['test_start']}..{checkpoint['test_end']} "
        f"recall={recall:.3f} (gate {args.min_recall}) "
        f"precision={checkpoint['metrics']['precision']:.3f} "
        f"pr_auc={checkpoint['metrics']['pr_auc']:.3f} "
        f"n_labeled={len(df)} -> {'PASS' if checkpoint['gate_passed'] else 'FAIL'}"
    )
    print(
        "[dry-run] In production the same gate runs with real accrued data via "
        "scripts.label_targets + scripts.evaluate_walk_forward."
    )
    print(f"[dry-run] written {args.out}")
    return 0 if checkpoint["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
