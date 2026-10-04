import sys
import uuid

import pandas as pd
from sqlalchemy import text

from src.crispdm.db import engine, read_df
from src.crispdm.features import db_value
from src.crispdm.regime import MacroState, determine_market_regime
from src.crispdm.regime_pipeline import apply_regime_layer, summarize
from src.crispdm.scoring import MIN_PRESENT_WEIGHT, predictions, rankings, score


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
    # Pruning is opt-in rather than automatic. These rows are the audit trail of
    # which model produced which number, and how long to keep it is a retention
    # decision rather than an implementation detail, so the default is to add to the
    # history and report on it. Pass --prune-superseded to drop the superseded runs
    # for the date just scored, keeping the one just written.
    prune_superseded = "--prune-superseded" in sys.argv

    df = read_df("""
    SELECT f.*,s.ticker,s.security_type
    FROM model.features f JOIN reference.securities s ON s.security_id=f.security_id
    WHERE f.as_of_date=(SELECT MAX(as_of_date) FROM model.features)
      AND s.active = TRUE
    """)
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

    with engine.begin() as c:
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
             model_version,feature_version,data_version)
            VALUES(:run,:sid,:dt,:prob,:cls,:thr,:mv,:fv,:dv)
            ON CONFLICT(run_id,security_id,as_of_date) DO UPDATE SET
            probability=EXCLUDED.probability,
            predicted_class=EXCLUDED.predicted_class,
            precision_threshold=EXCLUDED.precision_threshold
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
    as_of = x["as_of_date"].iloc[0]
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
        f"{x['as_of_date'].iloc[0]} ({unscorable.mean():.1%} below the coverage floor)"
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
            "  least half the measurable weight is present; a row that borrowed the\n"
            "  remaining half from percentiles would be a rank against the peers who\n"
            "  happened to report, not against the company."
        )

    out = (
        x.loc[~unscorable, ["ticker", "security_type", "composite_score"]]
        .sort_values("composite_score", ascending=False)
        .head(20)
    )
    print(out.to_string(index=False))
    print(f"\nRun id: {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
