import sys
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.crispdm.db import engine, read_df
from src.crispdm.feature_window import (
    carry_forward_days,
    feature_window_pit_metadata,
    scoring_features_sql,
)
from src.crispdm.features import db_value
from src.crispdm.ledger_opt_in import persist_run_if_opted_in
from src.crispdm.pit import normalize_as_of
from src.crispdm.regime import MacroState, determine_market_regime
from src.crispdm.regime_pipeline import apply_regime_layer, summarize
from src.crispdm.run_manifest import build_run_manifest, get_git_state, write_manifest_file
from src.crispdm.scoring import MIN_PRESENT_WEIGHT, predictions, rankings, score
from src.crispdm.versioning import DATA_VERSION, FEATURE_VERSION, MODEL_VERSION


def read_macro_state(features):
    """The macro observation to score against, for the features' as-of date.

    Returns ``MacroState(None, None, None)``, the section 5.4 neutral baseline,
    because the warehouse has no macro feed. That is the correct answer today,
    not a placeholder: with no vintage there is no observation to use, and
    inventing one would be a look-ahead with a date attached.

    The read belongs here rather than in the regime layer, so that the layer
    itself stays free of database access. When the feed lands it replaces this
    function, and it must join on the vintage published as of the features'
    ``as_of_date`` -- not on the current vintage, which is the failure mode
    section 9 exists to prevent.
    """
    return MacroState(None, None, None)


def prune_stale_run_rows(c, as_of, scored_sids):
    """Delete scores/rankings at ``as_of`` that this run does not rewrite.

    Both tables are keyed by (security_id, as_of_date) and carry no run_id, so the
    upsert that follows refreshes the rows it writes but silently leaves every
    other row at that date untouched. A security that fell out of the frame --
    deactivated, or it lost its features -- kept its old composite_score and still
    looked scoreable downstream.

    Only ``as_of`` is pruned. Earlier dates are point-in-time history: a re-run at
    the newest feature date must not reach back and delete the record of what a
    security scored at the date it actually scored.

    Called with the caller's open transaction so the surviving set is exactly what
    this run writes, and so a failure later in the run rolls the prune back with
    it rather than leaving the date half-deleted.

    Returns {table: rows_deleted}.
    """
    pruned = {}
    for table in ("scores", "rankings"):
        pruned[table] = c.execute(
            text(f"""
            DELETE FROM model.{table} t
            WHERE t.as_of_date = :d
              AND NOT EXISTS (
                SELECT 1 FROM unnest(CAST(:sids AS uuid[])) k(security_id)
                WHERE k.security_id = t.security_id
              )
            """),
            {"d": as_of, "sids": [str(s) for s in scored_sids]},
        ).rowcount
    return pruned


def parse_as_of(argv):
    """The ``--as-of`` date to re-score, or ``None`` for the nightly default.

    A scoring-policy change has to recompute every historical date, not just the
    latest one, so the run needs to pivot its feature window on a chosen past
    date. Accepts ``--as-of 2026-09-29`` and ``--as-of=2026-09-29``. A malformed
    value is a usage error rather than a silent fall-back to the nightly date:
    running the wrong date would overwrite the right one's scores.

    Kept separate from argparse because the rest of this script's switches are
    plain ``in sys.argv`` membership tests; a test can therefore exercise the
    parser without a live database.
    """
    for i, arg in enumerate(argv):
        value = None
        if arg == "--as-of":
            if i + 1 >= len(argv):
                raise SystemExit("--as-of needs a date (YYYY-MM-DD)")
            value = argv[i + 1]
        elif arg.startswith("--as-of="):
            value = arg.split("=", 1)[1]
        if value is not None:
            try:
                return date.fromisoformat(value)
            except ValueError:
                raise SystemExit(f"--as-of is not a date (YYYY-MM-DD): {value!r}") from None
    return None


def superseded_prune_decision(as_of_arg, argv):
    """Whether to drop superseded prediction runs at the scored date, and why.

    ``--prune-superseded`` is opt-in for the nightly, whose frame is stable from
    run to run: the stale runs agree with the current one on coverage, add
    nothing but history, and are kept as the audit trail.

    A replay is not stable. ``--as-of`` rebuilds the date's scores to whatever
    frame resolves *today*, and ``prune_stale_run_rows`` always drops the scores
    outside it -- but the superseded prediction runs cover the old, larger frame
    and would otherwise survive. ``model.current_predictions`` resolves to the
    newest run per security, so it would report the union of the old and new
    frames while ``model.scores`` holds only the new, and the two quietly
    disagree on how many securities the date scores. Replaying therefore prunes
    by default; ``--keep-superseded`` restores the nightly behaviour when the
    stale rows are genuinely wanted.

    Kept separate from ``main`` so the decision is reachable without a database.

    Returns ``(prune, reason)``; ``reason`` is a message to print, or ``None``.
    """
    if "--prune-superseded" in argv:
        return True, None
    if as_of_arg is not None and "--keep-superseded" not in argv:
        return (
            True,
            "pruning superseded prediction rows at the replayed date so "
            "current_predictions stays in step with scores; pass --keep-superseded to retain them",
        )
    return False, None


def main():
    """Score the latest feature date into model.scores, predictions and rankings.

    Wrapped in a function rather than left as import-time code so the failure
    paths are reachable from a test. This stage is the last one in the nightly,
    and the defect it was written to catch -- a stage that reports success after
    writing nothing -- is invisible if the way it says "nothing to do" cannot
    be invoked without a live database.
    """
    # Superseded runs. Every invocation stamps a fresh run_id, so re-scoring a date
    # -- routine, because a scoring-policy change means every date has to be
    # recomputed -- leaves another complete set of rows behind for the same
    # (security_id, as_of_date). Five runs sat against 2026-09-29 during this work,
    # four of them written by superseded versions of this script, and nothing but
    # created_at distinguishes them: a query without an ORDER BY gets whichever the
    # planner returns, so "the" prediction for a security is arbitrary.
    #
    # For the nightly, pruning is opt-in rather than automatic. Its frame is
    # stable from run to run, so the stale runs add nothing but history and are
    # the audit trail of which model produced which number -- how long to keep it
    # is a retention decision, not an implementation detail. Pass
    # --prune-superseded to drop them for the date just scored.
    #
    # A historical replay must not be opt-in, though: its frame has changed, so
    # the stale runs disagree with the new scores on coverage. See
    # superseded_prune_decision.
    #
    # Each security's most recent feature row within the carry-forward window,
    # not one global as_of_date. See src/crispdm/feature_window.py for why.
    #
    # --as-of pivots the window on a past date so a scoring-policy change can be
    # replayed over history; the nightly passes None and pivots on the newest row.
    as_of_arg = parse_as_of(sys.argv)
    as_of_arg_iso = normalize_as_of(as_of_arg)
    args = type(
        "LedgerArgs",
        (),
        {
            "persist_ledger": "--persist-ledger" in sys.argv,
            "ledger_dsn": next(
                (
                    sys.argv[i + 1]
                    for i, a in enumerate(sys.argv)
                    if a == "--ledger-dsn" and i + 1 < len(sys.argv)
                ),
                None,
            ),
            "i_understand_ledger_write": "--i-understand-ledger-write" in sys.argv,
        },
    )()
    prune_superseded, prune_reason = superseded_prune_decision(as_of_arg, sys.argv)
    if prune_reason:
        print(f"{as_of_arg}: {prune_reason}")
    carry_days = carry_forward_days()
    include_historical = "--include-historical" in sys.argv
    df = read_df(
        scoring_features_sql(include_historical=include_historical),
        params={"carry_days": carry_days, "as_of": as_of_arg},
    )
    if not df.empty:
        carried = int((df["as_of_date"] < df["as_of_date"].max()).sum())
        if carried:
            print(
                f"Read {carried} securities from an earlier feature date "
                f"(tolerance {carry_days}d; latest {df['as_of_date'].max()})."
            )
    if df.empty:
        # Exit 1, not 0. An empty feature table is the same defect this script's
        # stage guard exists to catch, in the one place that could not see it: the
        # stage had no rows to score, reported success, and left whatever scores
        # were already in model.scores looking current. Reporting failure is what
        # makes "features are empty" visible on the nightly instead of three
        # dashboards later.
        print(
            "No model.features rows; run the ETL to produce market data first.",
            file=sys.stderr,
        )
        return 1
    macro = read_macro_state(df)

    # Dynamic factor weighting (spec section 7.2). Like the credit layer below,
    # this runs gated and publishes its verdict without acting on it, for the
    # same underlying reason: there is no macro feed, so read_macro_state
    # returns the absent baseline and regime_weights(None) is the production
    # baseline. Passing the regime through anyway means the tilt is exercised
    # and its effect is measurable the day a feed lands, rather than being
    # untested code written today and switched on later.
    #
    # The gate is recorded as a boolean rather than by falling back silently,
    # because a future reader needs to be able to tell the difference between
    # "dynamic weighting is off" and "dynamic weighting ran and found the
    # baseline". --apply-regime-weights is the switch.
    apply_weights = "--apply-regime-weights" in sys.argv
    # An absent macro means there is no regime to tilt on, so the flag alone is
    # not enough; both the switch and a real observation are required.
    #
    # The regime is classified here, before scoring, using the same credit-only
    # call apply_regime_layer makes -- 0.0 for the economic legs it does not
    # carry. Classifying once and using the result for both the weights and the
    # published market_regime is the point: if the two derived it separately they
    # could disagree, and a row could be scored under one regime and labelled
    # with another.
    dynamic_regime = (
        determine_market_regime(
            0.0,
            0.0,
            float(macro.c_level),
            float(macro.c_delta),
        )
        if macro.present
        else None
    )
    x = score(df, regime=dynamic_regime if apply_weights else None)

    # What the score would have been under the classified regime, computed and
    # discarded when the gate is closed. Publishing the difference is the only
    # way to size a tilt before trusting one.
    shadow_composite = None
    if not apply_weights and dynamic_regime is not None:
        shadow_composite = score(df, regime=dynamic_regime)["composite_score"]
    run_id = uuid.uuid4()

    # Regime layer, downstream of score() and upstream of predictions()/rankings().
    #
    # Order matters here. The layer reads composite_score, so it has to run after
    # the coverage floor has decided which rows are scoreable at all, and it has
    # to run before rankings() so the rank reflects whatever composite_score is
    # about to be published. Passing apply_scores=False means the layer computes
    # and publishes its diagnostics without touching the score; see
    # apply_regime_layer for why that is the default and what it costs to flip.
    x = apply_regime_layer(x, macro)

    pred = predictions(x, run_id, threshold=0.5)
    rank = rankings(x, pred)

    # The run is dated by the newest feature observation, not by whichever row
    # happens to come first: carry-forward means as_of_date is no longer
    # constant across the frame, so iloc[0] would date the whole run to one
    # security's (possibly stale) row.
    as_of = x["as_of_date"].max()

    # A requested --as-of must actually be the date the window resolved to.
    # Anchoring on a date with no observation at it (a weekend, or a date past
    # the newest feature) would leave the frame's newest row on some other day,
    # and the prune below would then delete the requested date's scores while
    # this run wrote nothing back to it. Refuse rather than score the wrong date.
    if as_of_arg is not None and as_of != as_of_arg:
        print(
            f"--as-of {as_of_arg} requested but the newest feature row within the "
            f"carry-forward window is {as_of}; refusing to re-score the wrong date.",
            file=sys.stderr,
        )
        return 2

    # Security ids this run writes a score for, at the run date only.
    scored_sids = x.loc[x["as_of_date"] == as_of, "security_id"].tolist()

    with engine.begin() as c:
        # Drop scores/rankings left at the run date by a previous run for
        # securities this run does not score.
        for table, pruned in prune_stale_run_rows(c, as_of, scored_sids).items():
            if pruned:
                print(f"Pruned {pruned} stale model.{table} rows at {as_of}")
        for _, r in x.iterrows():
            c.execute(
                text("""
            INSERT INTO model.scores
            (security_id,as_of_date,dividend_income_score,sustainability_score,legal_rights_score,
             appreciation_score,risk_score,valuation_score,composite_score,score_coverage,
             market_regime,credit_environment,credit_modifier,override_flag,score_cap,
             cvs_score,cvs_coverage,cvs_tier,cvs_missing_core,macro_vintage,
             breakers_unavailable,regime_gate_reason,c4_audit_warning,
             debt_exempt)
            VALUES(:sid,:dt,:di,:su,:lr,:ap,:ri,:va,:co,:cv,
                   :mr,:ce,:cm,:of,:sc,:cs,:cc,:ct,:cmc,:mv,:bu,:gr,:c4w,
                   :dx)
            ON CONFLICT(security_id,as_of_date) DO UPDATE SET
            dividend_income_score=EXCLUDED.dividend_income_score,
            sustainability_score=EXCLUDED.sustainability_score,
            legal_rights_score=EXCLUDED.legal_rights_score,
            appreciation_score=EXCLUDED.appreciation_score,
            risk_score=EXCLUDED.risk_score,
            valuation_score=EXCLUDED.valuation_score,
            composite_score=EXCLUDED.composite_score,
            score_coverage=EXCLUDED.score_coverage,
            market_regime=EXCLUDED.market_regime,
            credit_environment=EXCLUDED.credit_environment,
            credit_modifier=EXCLUDED.credit_modifier,
            override_flag=EXCLUDED.override_flag,
            score_cap=EXCLUDED.score_cap,
            cvs_score=EXCLUDED.cvs_score,
            cvs_coverage=EXCLUDED.cvs_coverage,
            cvs_tier=EXCLUDED.cvs_tier,
            cvs_missing_core=EXCLUDED.cvs_missing_core,
            macro_vintage=EXCLUDED.macro_vintage,
            breakers_unavailable=EXCLUDED.breakers_unavailable,
            regime_gate_reason=EXCLUDED.regime_gate_reason,
            c4_audit_warning=EXCLUDED.c4_audit_warning,
            debt_exempt=EXCLUDED.debt_exempt
            """),
                {
                    "sid": r.security_id,
                    "dt": r.as_of_date,
                    "di": db_value(r.dividend_income_score),
                    "su": db_value(r.sustainability_score),
                    "lr": db_value(r.legal_rights_score),
                    "ap": db_value(r.appreciation_score),
                    "ri": db_value(r.risk_score),
                    "va": db_value(r.valuation_score),
                    "co": db_value(r.composite_score),
                    "cv": db_value(r.score_coverage),
                    "mr": r.market_regime,
                    "ce": r.credit_environment,
                    "cm": db_value(r.credit_modifier),
                    "of": r.override_flag,
                    "sc": db_value(r.score_cap),
                    "cs": db_value(r.cvs_score),
                    "cc": db_value(r.cvs_coverage),
                    "ct": r.cvs_tier,
                    "cmc": r.cvs_missing_core,
                    "mv": None if pd.isna(r.macro_vintage) else r.macro_vintage,
                    "bu": r.breakers_unavailable,
                    "c4w": bool(r.c4_audit_warning),
                    "dx": bool(r.debt_exempt),
                    "gr": r.regime_gate_reason,
                },
            )
        for _, r in pred.iterrows():
            c.execute(
                text("""
            INSERT INTO model.predictions
            (run_id,security_id,as_of_date,probability,predicted_class,precision_threshold,
             model_version,feature_version,data_version,model_config_hash,training_run_id)
            VALUES(:run,:sid,:dt,:prob,:cls,:thr,:mv,:fv,:dv,:mch,:trid)
            ON CONFLICT(run_id,security_id,as_of_date) DO UPDATE SET
            probability=EXCLUDED.probability,
            predicted_class=EXCLUDED.predicted_class,
            precision_threshold=EXCLUDED.precision_threshold,
            model_config_hash=EXCLUDED.model_config_hash,
            training_run_id=EXCLUDED.training_run_id
            """),
                {
                    "run": str(run_id),
                    "sid": r.security_id,
                    "dt": r.as_of_date,
                    "prob": db_value(r.probability),
                    "cls": None if pd.isna(r.predicted_class) else int(r.predicted_class),
                    "thr": r.precision_threshold,
                    "mv": r.model_version,
                    "fv": r.feature_version,
                    "dv": r.data_version,
                    "mch": r.model_config_hash,
                    "trid": r.training_run_id,
                },
            )
        for _, r in rank.iterrows():
            c.execute(
                text("""
            INSERT INTO model.rankings
            (security_id,as_of_date,rank,composite_score,probability)
            VALUES(:sid,:dt,:rank,:cs,:prob)
            ON CONFLICT(security_id,as_of_date) DO UPDATE SET
            rank=EXCLUDED.rank,
            composite_score=EXCLUDED.composite_score,
            probability=EXCLUDED.probability
            """),
                {
                    "sid": r.security_id,
                    "dt": r.as_of_date,
                    # Bracket access, not r.rank: on a Series row the attribute
                    # resolves to the pandas .rank() method, not this column.
                    # NaN means "no score", which is NULL in the integer column;
                    # int(NaN) used to raise.
                    "rank": None if pd.isna(r["rank"]) else int(r["rank"]),
                    "cs": db_value(r.composite_score),
                    "prob": db_value(r.probability),
                },
            )
    # The run is dated by the newest feature observation, not by whichever row
    # happens to come first: carry-forward means as_of_date is no longer
    # constant across the frame, so iloc[0] would date the whole run to one
    # security's (possibly stale) row.
    if prune_superseded:
        with engine.begin() as c:
            deleted = c.execute(
                text("""
                DELETE FROM model.predictions
                WHERE as_of_date = :d AND run_id <> :run
                """),
                {"d": as_of, "run": str(run_id)},
            ).rowcount
        print(f"\nPruned {deleted} superseded prediction rows for {as_of}")
    else:
        with engine.begin() as c:
            superseded = c.execute(
                text("""
                SELECT count(DISTINCT run_id)
                FROM model.predictions
                WHERE as_of_date = :d AND run_id <> :run
                """),
                {"d": as_of, "run": str(run_id)},
            ).scalar_one()
        if superseded:
            print(
                f"\n⚠ {superseded} superseded run(s) still hold rows for {as_of}. A query "
                "without ORDER BY created_at will return an arbitrary one of them. "
                "Re-run with --prune-superseded to drop them."
            )

    # How much of the universe the composite can actually score. Since the
    # composite is renormalised over the inputs that are present, these are no
    # longer securities with a single missing input: they are the ones whose
    # present inputs fall below the coverage floor, and the shortfall is a property
    # of the inputs rather than of the scoring rule.
    unscorable = x["composite_score"].isna()
    print(
        f"\nScored {int((~unscorable).sum())} of {len(x)} securities at "
        f"{x['as_of_date'].max()} ({unscorable.mean():.1%} below the coverage floor)"
    )
    if "score_coverage" in x.columns:
        print(
            f"  Coverage: median {x['score_coverage'].median():.0%} of measurable "
            f"weight; floor {MIN_PRESENT_WEIGHT:.0%} of total weight"
        )
    print(summarize(x))
    if dynamic_regime is None:
        print("  Dynamic weights: not applied; no macro observation to classify a regime.")
    elif apply_weights:
        print(f"  Dynamic weights: applied, section 7.2 matrix for {dynamic_regime}.")
    else:
        moved = int((x["composite_score"] != shadow_composite).fillna(False).sum())
        print(
            f"  Dynamic weights: computed under {dynamic_regime}, not applied "
            f"(gate off). {moved} of {len(x)} rows would change."
        )
    if unscorable.any():
        from src.crispdm.model import FEATURES

        print("  Below the floor; the inputs they are missing:")
        for col in FEATURES:
            if col not in x.columns:
                continue
            n = int(x.loc[unscorable, col].isna().sum())
            if n:
                print(f"    {col:24} {n:5d} of {int(unscorable.sum())}")
        print(
            "  Left NULL rather than imputed. The score is published only where at\n"
            "  least half the *total* weight is present; a row that borrowed the\n"
            "  remainder from percentiles would be a rank against the peers who\n"
            "  happened to report, not against the company."
        )

    out = (
        x.loc[~unscorable, ["ticker", "security_type", "composite_score"]]
        .sort_values("composite_score", ascending=False)
        .head(20)
    )
    print(out.to_string(index=False))

    try:
        git_state = get_git_state(Path(__file__).resolve().parents[1])
        manifest = build_run_manifest(
            run_type="score_rank",
            run_id=str(run_id),
            code_sha=git_state.get("sha"),
            code_dirty=git_state.get("dirty"),
            config={
                "model_version": MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "data_version": DATA_VERSION,
                "threshold": 0.5,
            },
            parameters={
                "as_of_arg": as_of_arg_iso,
                "carry_days": carry_days,
                "include_historical": include_historical,
                "apply_regime_weights": apply_weights,
                "prune_superseded": prune_superseded,
            },
            inputs={
                "features_table": "model.features",
                "scored_rows": int(len(x)),
                "scorable_rows": int((~unscorable).sum()),
                "pit": feature_window_pit_metadata(
                    as_of=as_of,
                    include_historical=include_historical,
                    carry_days=carry_days,
                ),
            },
            outputs={
                "scores_table": "model.scores",
                "predictions_table": "model.predictions",
                "rankings_table": "model.rankings",
                "as_of_date": str(as_of),
            },
            resolved_as_of=str(as_of),
            environment={"script": "scripts.score_rank"},
            status="completed",
        )
        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "artifacts"
            / "runs"
            / str(run_id)
            / "manifest.json"
        )
        write_manifest_file(manifest, manifest_path)
        ledger_result = persist_run_if_opted_in(
            manifest=manifest,
            outputs=[
                {
                    "output_kind": "score_rank_manifest",
                    "storage_ref": str(manifest_path),
                    "content_hash": manifest["hashes"]["manifest_core_hash"],
                    "metadata": {"run_type": "score_rank"},
                }
            ],
            dsn=getattr(args, "ledger_dsn", None),
            enabled=getattr(args, "persist_ledger", False),
            acknowledge=getattr(args, "i_understand_ledger_write", False),
            recorded_by="scripts.score_rank",
        )
        if ledger_result is not None:
            print(f"Ledger: {ledger_result['run_id']} persisted={ledger_result['inserted']}")
        print(f"\nRun id: {run_id}")
        print(f"Manifest: {manifest_path}")
    except Exception as exc:
        print(f"\nRun id: {run_id}")
        print(f"Manifest write failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
