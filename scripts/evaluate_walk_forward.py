"""
Run and record the walk-forward evaluation checkpoint for the ML target.

Pulls ``model.features`` rows that carry an offline label
(``target_sustainable_dividend`` not null), runs
``src.crispdm.model.walk_forward``, compares it against an explicit naive
baseline, persists the metrics to ``audit.model_runs``, and writes a
reviewable JSON snapshot under ``data/walk_forward_checkpoint.json``.

This command is the formal Go/No-Go record for the Azure pilot gate
("move to Azure only after ... walk-forward evaluation is passing"):

- no labeled rows / too few labels  -> informational, exit 0, no checkpoint
- placeholder/completeness failure -> exit 2, never a Go
- beats the naive baseline         -> PASS (exit 0)
- fails to beat the baseline       -> FAIL (exit 1)

**The gate is a comparison, not an absolute.** The label population is 93.6%
positive, so the "always predict sustainable" classifier scores recall 1.000
and PR-AUC 0.936. Gating on recall alone therefore cannot fail, which is what
the previous threshold did. The candidate must now clear the baseline on
balanced accuracy, minority-class recall, and PR-AUC lift.

Usage:
    python -m scripts.evaluate_walk_forward
    python -m scripts.evaluate_walk_forward --max-flag-rate 0.10
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
from src.crispdm.ledger_opt_in import persist_run_if_opted_in
from src.crispdm.model import (
    FEATURES,
    MIN_PR_AUC_LIFT,
    PLACEHOLDER_FEATURES,
    evaluate_gate,
    feature_completeness,
    implemented_features,
    minority_rate,
    naive_baseline,
    walk_forward,
    walk_forward_folds,
    walk_forward_pit_metadata,
)
from src.crispdm.run_manifest import build_run_manifest, get_git_state, write_manifest_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_PATH = PROJECT_ROOT / "data" / "walk_forward_checkpoint.json"
MIN_LABELED_ROWS = 10
MODEL_VERSION = "logistic_regression_walk_forward_v3"

#: The contract a checkpoint is evidence *under*. A checkpoint records the
#: version that produced it, and a checkpoint written under a different one is
#: not evidence for the current policy no matter what its ``gate_passed`` says.
#:
#: This exists because the acceptance policy changed twice in one session --
#: PR-AUC lift was added as a criterion and then removed as a criterion (not
#: relaxed) -- and the version strings on the checkpoint were literals nobody
#: bumped. A reader could not tell which rules produced a verdict, and
#: ``invalidate_stale_checkpoint`` only fired on a completeness failure, so a
#: passing artifact from the superseded policy stayed readable at the canonical
#: path. Bumping this is what makes the next policy change self-invalidating.
ACCEPTANCE_POLICY_VERSION = "balanced_acc_lift_and_negative_recall_v2"

#: Bumped when the feature SQL changes what a column means, not merely when it
#: is recomputed. v5 nulls a negative debt balance and computes dividend_growth
#: from the per-payment series only where its prior-year window is observed (a
#: stub first payment read as growth of thousands of percent). v4 makes
#: momentum_63d / momentum_252d total returns (price plus
#: dividends; v3 was price only) and stops a fundamentals vintage being visible
#: before its period has ended. v3 is the per-metric quarterly vintage chain: one
#: slot per fiscal quarter, and a filing label that omits a metric no longer masks
#: an already-published figure. v2 was period-end alignment, which fed the model a
#: quarter's earnings before it was filed.
FEATURE_VERSION = "features_v5"

#: Bumped when the stored inputs change meaning. v3 is filing-vintaged
#: fundamentals (V0009: one row per period *and* filing state, ``filed`` NOT
#: NULL in the primary key). v2 was the unversioned relation, which stored only
#: the latest value of each period and could not be queried point-in-time at all.
DATA_VERSION = "sec_xbrl_v3"

#: A declared feature below this non-null share is too sparse to carry signal
#: and must not be silently imputed into the model.
#:
#: The bar is set by what the imputer does to a sparse column, not by taste.
#: Below 20% coverage the median fills more than four fifths of the rows with
#: a single constant, which is arithmetically equivalent to a column of noise
#: for those rows while still earning a non-zero coefficient -- the worst of
#: both worlds, because the model reports a weight for a feature that mostly
#: does not exist. Above 20% the column carries real variation in a majority of
#: rows and imputation is a gap-filler rather than the feature itself.
#:
#: Sparsity here is expected and is not the same defect as a placeholder. A
#: placeholder has no source at all and is caught by PLACEHOLDER_FEATURES; a
#: sparse feature is computed correctly and is simply undefined for many
#: securities -- dividend_growth covers ~8.6% of rows because only 321k
#: security-days have payments in both the current and prior 365-day window.
#: The gate reports the two separately so a data gap is never mistaken for an
#: unimplemented feature, and it fails on both.
MIN_FEATURE_COVERAGE = 0.20


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


def audit_completeness(df, min_coverage=MIN_FEATURE_COVERAGE):
    """Describe how much of the declared feature set is real.

    Returns a dict with the per-feature coverage, which declared features are
    unimplemented placeholders, and whether the build may proceed. The gate
    fails when a required input is a placeholder, which is the condition that
    makes a result diagnostic rather than production evidence.
    """
    coverage = feature_completeness(df)
    # Audit the union of the declared list and whatever the frame actually
    # carries. Scanning only FEATURES would miss a retired name reintroduced as
    # a column, which is exactly the case the gate exists to catch.
    present = [f for f in df.columns if f in PLACEHOLDER_FEATURES]
    declared = [f for f in FEATURES if f in PLACEHOLDER_FEATURES]
    placeholders = sorted(set(declared) | set(present))
    empty = sorted(f for f, c in coverage.items() if c == 0.0 and f not in placeholders)
    sparse = sorted(
        f for f, c in coverage.items() if 0.0 < c < min_coverage and f not in placeholders
    )
    return {
        "declared_features": list(FEATURES),
        "implemented_features": implemented_features(),
        "placeholder_features": placeholders,
        "zero_coverage_non_placeholder": empty,
        "sparse_features": sparse,
        "min_required_coverage": float(min_coverage),
        "coverage": {k: round(v, 6) for k, v in coverage.items()},
        "completeness_ok": not placeholders and not empty and not sparse,
    }


def _checkpoint_scalar(key, value):
    """Coerce a metrics entry to something JSON can hold without lying about it.

    Metrics are mostly floats, but the embargo audit contributes a nested dict
    and date strings. Blindly calling float() on those raises; dropping them
    silently would hide the provenance of the run.
    """
    if isinstance(value, dict) or value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return float(value)
    return str(value)


def derive_prevalence_guardrail(fold_diagnostics):
    """Derive the minority-prevalence cutoff where PR-AUC stops being usable.

    The cutoff is measured, not chosen. For each fold we compute the maximum
    PR-AUC lift any model could achieve against the prevalence baseline,
    ``1 - baseline_pr_auc``. When that headroom falls below the reference
    margin the criterion is unattainable for *every* model at that prevalence,
    so the gate is measuring prevalence rather than discrimination. The
    guardrail is the highest minority rate at which that has already happened
    in the observed folds, and the evidence is returned alongside it so the
    number is auditable rather than asserted.
    """
    evidence = []
    for fold in fold_diagnostics:
        rate = minority_rate(fold["baseline"])
        headroom = 1.0 - float(fold["baseline"]["pr_auc"])
        evidence.append(
            {
                "fold": fold["fold"],
                "minority_rate": rate,
                "pr_auc_headroom": headroom,
                "pr_auc_lift": float(fold["metrics"]["pr_auc"] - fold["baseline"]["pr_auc"]),
                "headroom_below_reference": headroom < MIN_PR_AUC_LIFT,
            }
        )
    unattainable = [e["minority_rate"] for e in evidence if e["headroom_below_reference"]]
    usable = [e["minority_rate"] for e in evidence if not e["headroom_below_reference"]]
    cutoff = max(unattainable) if unattainable else 0.0
    return {
        "cutoff": cutoff,
        "method": (
            "highest observed minority rate whose PR-AUC headroom "
            "(1 - baseline_pr_auc) is below the reference margin "
            f"{MIN_PR_AUC_LIFT}; derived from the evaluated folds, not chosen"
        ),
        "reference_margin": float(MIN_PR_AUC_LIFT),
        "n_folds_used": len(evidence),
        "lowest_usable_minority_rate": min(usable) if usable else None,
        "highest_unusable_minority_rate": max(unattainable) if unattainable else None,
        "evidence": evidence,
    }


def evaluate_folds(df, n_folds, max_flag_rate):
    """Score the model across expanding-window folds and gate on all of them.

    A single 70/30 cut cannot distinguish a model that generalises from one that
    landed well, because the label's prevalence is not stationary: the negative
    rate falls from ~12% in 2019-2022 to ~2% in 2023-2025. Each fold trains
    only on purge-eligible rows that precede it, and a Go requires every
    requested fold to be evaluated and to clear both blocking checks. A fold
    that cannot be evaluated counts against the verdict rather than being
    dropped, since a skipped fold is a period with no evidence at all.

    Acceptance is on balanced-accuracy lift and minority-class recall. PR-AUC
    is carried as a diagnostic, and the prevalence guardrail is derived from
    these folds before any of them is gated, so the cutoff reflects the
    observed label rather than an assumption.
    """
    folds = walk_forward_folds(df, n_folds=n_folds, max_flag_rate=max_flag_rate)

    # Pass 1: score every fold and collect the prevalence/headroom evidence.
    staged = []
    for fold in folds:
        if fold["status"] != "ok":
            staged.append(
                {
                    "fold": fold["fold"],
                    "status": "skipped",
                    "test_start": str(fold["test_start"].date()),
                    "test_end": str(fold["test_end"].date()),
                    "reason": fold["reason"],
                }
            )
            continue
        metrics = fold["metrics"]
        test = fold["test"]
        baseline = naive_baseline(test.target_sustainable_dividend.astype(int))
        staged.append(
            {
                "fold": fold["fold"],
                "status": "ok",
                "test_start": str(fold["test_start"].date()),
                "test_end": str((fold["test_end"] - pd.Timedelta(days=1)).date()),
                "n_train": metrics["n_train"],
                "n_test": metrics["n_test"],
                "metrics": {k: v for k, v in metrics.items() if not isinstance(v, dict)},
                "baseline": baseline,
                "embargo": metrics["embargo"],
            }
        )

    scored = [r for r in staged if r["status"] == "ok"]
    guardrail = derive_prevalence_guardrail(scored)

    # Pass 2: gate, now that the guardrail is known.
    for record in scored:
        record["gate"] = evaluate_gate(
            record["metrics"], record["baseline"], prevalence_guardrail=guardrail["cutoff"]
        )
        record["gate_passed"] = record["gate"]["passed"]
        record["checks"] = record["gate"]["checks"]
        record["diagnostics"] = record["gate"]["diagnostics"]

    skipped = [r for r in staged if r["status"] != "ok"]
    return {
        "n_folds_requested": int(n_folds),
        "n_folds_evaluated": len(scored),
        "n_folds_skipped": len(skipped),
        "n_folds_passed": sum(1 for r in scored if r["gate_passed"]),
        "all_folds_passed": bool(scored) and not skipped and all(r["gate_passed"] for r in scored),
        "acceptance_policy": {
            "version": ACCEPTANCE_POLICY_VERSION,
            "blocking_checks": ["balanced_accuracy_lift", "negative_recall"],
            "diagnostics": ["pr_auc_lift"],
            "requires_all_folds": True,
            "skipped_folds_fail_closed": True,
        },
        "prevalence_guardrail": guardrail,
        "folds": staged,
    }


def make_checkpoint(
    run_id, max_flag_rate, metrics, dates, cut, n_rows, baseline, gate, completeness
):
    """Build the reviewable checkpoint dict (pure; kept separate for tests)."""
    n_train_dates = int(cut)
    n_test_dates = int(len(dates) - cut)
    return {
        "run_id": str(run_id),
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "data_version": DATA_VERSION,
        # The contract is the reader's first stop: it says which policy, which
        # features and which stored inputs produced gate_passed below. Kept as a
        # self-contained block so a reader never has to infer it from the
        # surrounding fields, which is what let a superseded verdict pass for a
        # current one.
        "contract": {
            "acceptance_policy_version": ACCEPTANCE_POLICY_VERSION,
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "data_version": DATA_VERSION,
            "blocking_checks": ["balanced_accuracy_lift", "negative_recall"],
            "diagnostics": ["pr_auc_lift"],
            "requires_all_folds": True,
            "skipped_folds_fail_closed": True,
        },
        "max_flag_rate": max_flag_rate,
        "training_start": str(dates[0]),
        "training_end": str(dates[cut - 1]),
        "test_start": str(dates[cut]),
        "test_end": str(dates[-1]),
        "n_feature_rows": int(n_rows),
        # These are counts of distinct as_of DATES, not rows. The row counts
        # are n_train_rows / n_test_rows; the date counts are named as such so
        # a reader cannot mistake 362 rows for the training set size.
        "n_train_dates": n_train_dates,
        "n_test_dates": n_test_dates,
        "n_train_rows": int(metrics.get("n_train", 0)),
        "n_test_rows": int(metrics.get("n_test", 0)),
        "features": FEATURES,
        "features_used": implemented_features(),
        "feature_completeness": completeness,
        # The embargo is a dict, not a scalar, so it is lifted out before the
        # numeric metrics are flattened; it is reported as its own block rather
        # than being squeezed into a float column.
        "label_embargo": metrics.get("embargo", {}),
        "baseline": baseline,
        "metrics": {k: _checkpoint_scalar(k, v) for k, v in metrics.items()},
        "gate": gate,
        "acceptance_policy": {
            "blocking_checks": ["balanced_accuracy_lift", "negative_recall"],
            "diagnostics": ["pr_auc_lift"],
            "pr_auc_lift_is_blocking": False,
            "rationale": (
                "PR-AUC lift is excluded from acceptance because its baseline is "
                "the positive rate: as negatives thin out the always-predict-"
                "sustainable baseline approaches PR-AUC 1.0, leaving less headroom "
                "than the required margin, so the criterion measures prevalence "
                "rather than discrimination. Balanced-accuracy lift and minority "
                "recall are ratios that do not saturate, so they retain meaning "
                "across the prevalence shift."
            ),
        },
        # A Go requires beating the baseline AND a complete feature set.
        "gate_passed": bool(gate["passed"] and completeness["completeness_ok"]),
        "readiness": "go" if gate["passed"] and completeness["completeness_ok"] else "no_go",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def persist(checkpoint):
    params = json.dumps(checkpoint["parameters"], default=str)
    metrics = checkpoint["metrics"]
    baseline = checkpoint["baseline"]
    with engine.begin() as c:
        c.execute(
            text(
                """
                INSERT INTO audit.model_runs
                  (run_id, model_version, feature_version, data_version,
                   training_start, training_end, test_start, test_end,
                   precision, recall, f1, pr_auc, roc_auc, accuracy, parameters,
                   balanced_accuracy, positive_precision, positive_recall,
                   negative_precision, negative_recall, negative_support,
                   positive_support, positive_rate, n_train_rows, n_test_rows,
                   n_feature_rows, baseline_balanced_accuracy, baseline_pr_auc,
                   gate_passed, readiness, feature_completeness, gate_detail)
                VALUES
                  (:run, :mv, :fv, :dv, :trs, :tre, :tes, :tee,
                   :precision, :recall, :f1, :prauc, :rocauc, :acc, :params,
                   :bal_acc, :pos_prec, :pos_rec, :neg_prec, :neg_rec,
                   :neg_support, :pos_support, :pos_rate,
                   :n_train_rows, :n_test_rows, :n_feature_rows,
                   :base_bal_acc, :base_prauc, :gate_passed, :readiness,
                   :feature_completeness, :gate_detail)
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
                "precision": metrics.get("precision"),
                "recall": metrics.get("recall"),
                "f1": metrics.get("f1"),
                "prauc": metrics.get("pr_auc"),
                "rocauc": metrics.get("roc_auc"),
                "acc": metrics.get("accuracy"),
                "params": params,
                "bal_acc": metrics.get("balanced_accuracy"),
                "pos_prec": metrics.get("positive_precision"),
                "pos_rec": metrics.get("positive_recall"),
                "neg_prec": metrics.get("negative_precision"),
                "neg_rec": metrics.get("negative_recall"),
                "neg_support": metrics.get("negative_support"),
                "pos_support": metrics.get("positive_support"),
                "pos_rate": baseline.get("positive_rate"),
                "n_train_rows": checkpoint.get("n_train_rows"),
                "n_test_rows": checkpoint.get("n_test_rows"),
                "n_feature_rows": checkpoint.get("n_feature_rows"),
                "base_bal_acc": baseline.get("balanced_accuracy"),
                "base_prauc": baseline.get("pr_auc"),
                "gate_passed": checkpoint.get("gate_passed"),
                "readiness": checkpoint.get("readiness"),
                "feature_completeness": json.dumps(
                    checkpoint.get("feature_completeness", {}), default=str
                ),
                "gate_detail": json.dumps(checkpoint.get("gate", {}), default=str),
            },
        )


def current_contract():
    """The contract this build of the evaluator would judge a Go under."""
    return {
        "acceptance_policy_version": ACCEPTANCE_POLICY_VERSION,
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "data_version": DATA_VERSION,
    }


def contract_drift(checkpoint):
    """The contract fields on which ``checkpoint`` disagrees with this build.

    A checkpoint that disagrees is not wrong, it is *about something else*: a
    different policy, a different feature definition, or a different stored
    input. Its ``gate_passed`` answers a question no longer being asked, so it
    must not be read as the answer to this one. Fields absent from an older
    checkpoint count as drift rather than as a match, because a file with no
    recorded policy cannot be shown to have been judged under this one.
    """
    if not isinstance(checkpoint, dict):
        return {k: None for k in current_contract()}
    recorded = checkpoint.get("contract")
    if not isinstance(recorded, dict):
        recorded = {
            "acceptance_policy_version": None,
            "model_version": checkpoint.get("model_version"),
            "feature_version": checkpoint.get("feature_version"),
            "data_version": checkpoint.get("data_version"),
        }
    drift = {}
    for field, wanted in current_contract().items():
        recorded_value = recorded.get(field)
        if recorded_value != wanted:
            drift[field] = (recorded_value, wanted)
    return drift


def read_checkpoint(path):
    """Load a checkpoint, returning ``None`` if absent or unreadable."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def invalidate_superseded_contract(path):
    """Quarantine a checkpoint written under a different contract.

    Called before a new run so that changing the policy, the feature definition
    or the stored inputs retires the previous verdict on its own. Without this
    the only way a stale ``gate_passed: true`` leaves the canonical path is a
    completeness failure, so a policy edit alone would leave a passing artifact
    for a policy that no longer exists sitting exactly where a reader looks.
    """
    path = Path(path)
    existing = read_checkpoint(path)
    if existing is None:
        return None
    drift = contract_drift(existing)
    if not drift:
        return None
    detail = ", ".join(f"{k}={recorded!r} -> {wanted!r}" for k, (recorded, wanted) in drift.items())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantined = path.with_name(f"{path.stem}.superseded-{stamp}{path.suffix}")
    path.replace(quarantined)
    print(
        f"[contract] existing checkpoint was written under a different contract "
        f"({detail}); moved to {quarantined.name}. It is not evidence under the "
        f"current policy."
    )
    return quarantined


def invalidate_stale_checkpoint(path, completeness, reason):
    """Neutralise a checkpoint from an earlier run so it cannot be misread.

    A failed completeness gate writes nothing, which leaves whatever the
    previous run left on disk in place. That file still says
    ``gate_passed: true`` under the old recall-only contract, so a reader
    opening ``data/walk_forward_checkpoint.json`` after a NO_GO run would find
    a passing artifact and no indication that it is obsolete. Renaming it with
    a ``.superseded`` suffix keeps the evidence for review while removing it
    from the path anything else reads.
    """
    path = Path(path)
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantined = path.with_name(f"{path.stem}.superseded-{stamp}{path.suffix}")
    path.replace(quarantined)
    print(
        f"[stale] previous checkpoint moved to {quarantined.name}; it reported a "
        f"result under an older gate contract and is not current evidence."
    )
    return quarantined


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--folds",
        type=int,
        default=0,
        help="Also score the model across N expanding-window walk-forward folds "
        "and require every fold to clear the gate before a Go is written.",
    )
    parser.add_argument(
        "--max-flag-rate",
        type=float,
        default=0.10,
        help="Threshold search budget: the highest flag rate the calibrated "
        "threshold may use on the training set. The Go/No-Go decision is the "
        "comparison against the naive baseline, not this absolute.",
    )
    parser.add_argument(
        "--out", type=Path, default=CHECKPOINT_PATH, help="Where to write the JSON checkpoint"
    )
    parser.add_argument("--persist-ledger", action="store_true")
    parser.add_argument("--ledger-dsn")
    parser.add_argument("--i-understand-ledger-write", action="store_true")
    args = parser.parse_args()

    df = load_labeled_features()
    if df.empty or len(df) < MIN_LABELED_ROWS:
        print(
            f"[info] {len(df)} labeled feature rows (< {MIN_LABELED_ROWS}); "
            "populate target_sustainable_dividend first "
            "(see docs/model-labeling-plan.md). No checkpoint written, exiting 0."
        )
        return 0

    # Retire any verdict written under a different contract before doing the
    # work, so a policy edit cannot leave a passing artifact from the superseded
    # policy at the canonical path even if this run goes on to fail.
    invalidate_superseded_contract(args.out)

    completeness = audit_completeness(df)
    if not completeness["completeness_ok"]:
        # Fail the build before training: a checkpoint written on top of
        # placeholder inputs would be read as production evidence.
        if completeness["placeholder_features"]:
            print(
                f"[completeness] FAIL: {len(completeness['placeholder_features'])}/"
                f"{len(completeness['declared_features'])} declared features are "
                f"unimplemented placeholders: "
                f"{', '.join(completeness['placeholder_features'])}"
            )
        if completeness["zero_coverage_non_placeholder"]:
            print(
                "[completeness] zero-coverage implemented features: "
                f"{', '.join(completeness['zero_coverage_non_placeholder'])}"
            )
        if completeness["sparse_features"]:
            print(
                f"[completeness] FAIL: features below the "
                f"{completeness['min_required_coverage']:.0%} coverage floor: "
                + ", ".join(
                    f"{f} ({completeness['coverage'][f]:.1%})"
                    for f in completeness["sparse_features"]
                )
            )
        invalidate_stale_checkpoint(
            args.out,
            completeness,
            reason="feature completeness gate failed",
        )
        print(
            "[completeness] no checkpoint written and no Go is possible; the "
            "result would be diagnostic only. Exit 2."
        )
        return 2

    dates, cut = split_dates(df["as_of_date"])
    model, metrics, test = walk_forward(df, max_flag_rate=args.max_flag_rate)
    baseline = naive_baseline(test.target_sustainable_dividend.astype(int))
    gate = evaluate_gate(metrics, baseline)
    checkpoint = make_checkpoint(
        uuid.uuid4(),
        args.max_flag_rate,
        metrics,
        dates,
        cut,
        len(df),
        baseline,
        gate,
        completeness,
    )
    checkpoint["parameters"] = {
        "threshold": metrics["threshold"],
        "max_flag_rate": args.max_flag_rate,
        "features_used": implemented_features(),
    }
    if args.folds:
        rolling = evaluate_folds(df, args.folds, args.max_flag_rate)
        checkpoint["rolling_folds"] = rolling
        # A Go now has to survive every fold, not just the single cut.
        checkpoint["gate_passed"] = bool(checkpoint["gate_passed"]) and rolling["all_folds_passed"]
        for r in rolling["folds"]:
            if r["status"] != "ok":
                print(f"[fold {r['fold']}] skipped: {r['reason']}")
                continue
            fails = [n for n, c in r["checks"].items() if not c["passed"]]
            d = r["diagnostics"]
            # PR-AUC is reported with the prevalence that makes it meaningful,
            # and marked when prevalence has eaten its headroom.
            reliability = "" if d["reliable"] else f" UNRELIABLE ({d['unreliable_reason']})"
            print(
                f"[fold {r['fold']}] {r['test_start']}..{r['test_end']} "
                f"train={r['n_train']:,} test={r['n_test']:,} "
                f"bal_acc={r['metrics']['balanced_accuracy']:.3f} "
                f"neg_recall={r['metrics']['negative_recall']:.3f} "
                f"| diagnostic pr_auc={r['metrics']['pr_auc']:.4f} "
                f"lift={d['pr_auc_lift']:+.4f} headroom={d['pr_auc_headroom']:.4f} "
                f"minority={d['minority_rate']:.2%}"
                f"{reliability} "
                f"(neg {r['embargo']['train_negative_rate']:.2%}->"
                f"{r['embargo']['test_negative_rate']:.2%}) "
                + ("pass" if r["gate_passed"] else f"FAIL {','.join(fails)}")
            )
        print(
            f"[folds] {rolling['n_folds_passed']}/{rolling['n_folds_evaluated']} "
            f"folds cleared the gate"
            + (
                f"; {rolling['n_folds_skipped']} skipped (no evidence, counts against the verdict)"
                if rolling["n_folds_skipped"]
                else ""
            )
        )
        guard = rolling["prevalence_guardrail"]
        print(
            f"[guardrail] PR-AUC lift is not an acceptance criterion. It is flagged "
            f"unreliable at or below a {guard['cutoff']:.2%} minority rate, derived "
            f"from {guard['n_folds_used']} folds: {guard['method']}"
        )
        for e in guard["evidence"]:
            print(
                f"  fold {e['fold']}: minority={e['minority_rate']:.2%} "
                f"headroom={e['pr_auc_headroom']:.4f} lift={e['pr_auc_lift']:+.4f} "
                f"{'unattainable' if e['headroom_below_reference'] else 'usable'}"
            )

    git_state = get_git_state(PROJECT_ROOT)
    manifest = build_run_manifest(
        run_type="evaluate_walk_forward",
        code_sha=git_state.get("sha"),
        code_dirty=git_state.get("dirty"),
        parameters={
            "folds": args.folds,
            "max_flag_rate": args.max_flag_rate,
            "out": str(args.out),
        },
        inputs={
            "feature_table": "model.features",
            "label_column": "target_sustainable_dividend",
            "pit": walk_forward_pit_metadata(
                embargo_days=settings.label_horizon_days,
                test_start=checkpoint.get("test_end"),
            ),
        },
        outputs={"checkpoint": str(args.out), "readiness": checkpoint.get("readiness")},
        environment={"script": "scripts.evaluate_walk_forward"},
        status="completed" if checkpoint.get("gate_passed") else "failed",
        acceptance_policy_id=checkpoint.get("contract", {}).get("acceptance_policy_version"),
        acceptance_policy_version=checkpoint.get("contract", {}).get("acceptance_policy_version"),
    )
    manifest_path = args.out.parent / f"walk_forward_manifest_{checkpoint['run_id']}.json"
    try:
        write_manifest_file(manifest, manifest_path)
        checkpoint["manifest"] = {
            "run_id": manifest["run_id"],
            "path": str(manifest_path),
            "hash": manifest["hashes"]["manifest_core_hash"],
        }
    except Exception as exc:
        print(f"Manifest write failed: {exc}")
    ledger_result = persist_run_if_opted_in(
        manifest=manifest,
        outputs=[
            {
                "output_kind": "walk_forward_checkpoint",
                "storage_ref": str(args.out),
                "content_hash": manifest["hashes"]["manifest_core_hash"],
                "metadata": {"readiness": checkpoint.get("readiness")},
            }
        ],
        dsn=args.ledger_dsn,
        enabled=args.persist_ledger,
        acknowledge=args.i_understand_ledger_write,
        recorded_by="scripts.evaluate_walk_forward",
    )
    if ledger_result is not None:
        print(f"Ledger: {ledger_result['run_id']} persisted={ledger_result['inserted']}")

    persist(checkpoint)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(checkpoint, indent=2, default=str) + "\n")

    m = checkpoint["metrics"]
    print(
        f"[baseline] always-predict-sustainable: balanced_acc="
        f"{baseline['balanced_accuracy']:.3f} recall={baseline['recall']:.3f} "
        f"pr_auc={baseline['pr_auc']:.3f} (positive rate "
        f"{baseline['positive_rate']:.3f})"
    )
    print(
        f"[model] balanced_acc={m['balanced_accuracy']:.3f} "
        f"recall={m['recall']:.3f} precision={m['precision']:.3f} "
        f"f1={m['f1']:.3f} pr_auc={m['pr_auc']:.3f} "
        f"negative_recall={m['negative_recall']:.3f} "
        f"(n_neg={m['negative_support']})"
    )
    emb = checkpoint.get("label_embargo") or {}
    if emb:
        print(
            f"[embargo] {emb['horizon_days']}d label horizon, test starts "
            f"{emb['test_start']}: train rows {emb['rows_before_embargo']} -> "
            f"{emb['rows_retained']} ({emb['retained_share']:.1%}), dropped "
            f"{emb['rows_dropped_as_leaky']} whose label window reached into "
            f"the test period; last train date {emb['last_train_date']}"
        )
    for name, check in gate["checks"].items():
        status = "pass" if check["passed"] else "FAIL"
        print(f"[gate] {name}: {check['actual']:+.4f} (need {check['required']:+.4f}) {status}")
    verdict = "GO" if checkpoint["gate_passed"] else "NO-GO"
    print(
        f"[checkpoint] {checkpoint['run_id']} test {checkpoint['test_start']}.."
        f"{checkpoint['test_end']} -> {verdict}"
    )
    print(f"[checkpoint] written {args.out}")
    return 0 if checkpoint["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
