"""Tests for the regime layer's pipeline wiring.

:mod:`src.crispdm.regime` holds the arithmetic and is tested in
``test_regime.py``. What is tested here is the adapter between that arithmetic
and a warehouse feature frame, plus the gate that keeps the layer from
rescaling live scores while its inputs do not exist.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from src.crispdm.regime import (
    MacroState,
    compute_cvs,
    credit_environment,
    determine_market_regime,
)
from src.crispdm.regime_pipeline import (
    CIRCUIT_BREAKER_SOURCES,
    CIRCUIT_BREAKER_THRESHOLDS,
    CVS_SOURCE_COLUMNS,
    GATE_BREAKERS_UNEVALUABLE,
    GATE_CVS_INCOMPLETE,
    GATE_MACRO_ABSENT,
    apply_regime_layer,
    compute_cvs_frame,
    evaluate_breakers,
    layer_readiness,
    macro_state_from_row,
)

MACRO_ABSENT = MacroState(None, None, None)


def _frame(**columns):
    """A minimal feature frame, long enough for the mask logic to be visible."""
    length = len(next(iter(columns.values()))) if columns else 5
    defaults = {
        "security_id": [f"s{i}" for i in range(length)],
        "composite_score": list(np.linspace(0.9, 0.1, length)),
    }
    defaults.update(columns)
    return pd.DataFrame(defaults)


def test_frame_matches_the_scalar_reference_row_for_row():
    """The vectorised path is an optimisation, not a second set of rules.

    It exists so the nightly run does not call the scalar version 5,443 times.
    If it ever disagrees with the scalar reference the layer has two
    definitions of the same score, which is the defect this whole layer exists
    to remove elsewhere.
    """
    # Raw observations, not bracket points: compute_cvs brackets them itself.
    # Rows span every branch of the tier logic -- pristine, mid-range, missing
    # leverage, missing coverage -- so a disagreement between the two
    # implementations has to show up somewhere on this grid.
    frame = _frame(
        debt_to_ebitda=[2.0, 3.0, np.nan, 5.0, 1.5],
        interest_coverage=[8.0, 3.0, 4.0, np.nan, 7.0],
        quick_liquidity=[2.0, 1.0, 0.8, 1.5, np.nan],
        refinancing_wall=[0.3, 0.6, 1.2, np.nan, 0.2],
        credit_rating=[1.0, 2.5, np.nan, 4.0, 3.0],
    )
    got = compute_cvs_frame(frame)

    for i in range(len(frame)):
        row = frame.iloc[i]
        expected = compute_cvs(
            {
                "net_debt_to_ebitda": row.get("debt_to_ebitda"),
                "interest_coverage": row.get("interest_coverage"),
                "quick_liquidity": row.get("quick_liquidity"),
                "refinancing_wall": row.get("refinancing_wall"),
                "credit_rating": row.get("credit_rating"),
            }
        )
        assert got["cvs_tier"].iloc[i] == expected.tier, i
        assert got["cvs_missing_core"].iloc[i] == ",".join(expected.missing_core), i
        if expected.cvs is None:
            assert pd.isna(got["cvs_score"].iloc[i]), i
            assert got["cvs_coverage"].iloc[i] == pytest.approx(0.0), i
        else:
            assert got["cvs_score"].iloc[i] == pytest.approx(expected.cvs), i
            assert got["cvs_coverage"].iloc[i] == pytest.approx(expected.coverage), i


def test_frame_agrees_on_the_unscorable_path():
    """No liquidity column means no row is scoreable, and that must be exact."""
    frame = _frame(debt_to_ebitda=[2.0, np.nan], interest_coverage=[8.0, 4.0])
    got = compute_cvs_frame(frame)
    assert list(got["cvs_tier"]) == ["unscorable", "unscorable"]
    assert got["cvs_score"].isna().all()
    assert got["cvs_coverage"].eq(0.0).all()


def test_frame_reports_the_actual_missing_leg_on_a_scoreable_row():
    """An unscorable row lists both core legs; a scored row lists only the gap.

    Reporting "both missing" for a row that is missing one leg is what the
    first version of this function did, and it makes the column useless for the
    only question it exists to answer.
    """
    frame = _frame(
        debt_to_ebitda=[2.0, np.nan],
        interest_coverage=[8.0, 4.0],
        quick_liquidity=[2.0, 1.0],
        refinancing_wall=[0.2, 0.2],
    )
    got = compute_cvs_frame(frame)
    assert got["cvs_tier"].iloc[0] == "strong"
    assert got["cvs_missing_core"].iloc[0] == ""
    # One core leg missing is enough to score, and enough to cost Strong: the
    # Strong gate requires a measured leg on each of the two.
    assert got["cvs_tier"].iloc[1] == "moderate"
    assert got["cvs_missing_core"].iloc[1] == "net_debt_to_ebitda"


def test_frame_handles_a_missing_leverage_column_entirely():
    """A column that does not exist is absent, not zero."""
    frame = _frame(interest_coverage=[8.0], quick_liquidity=[2.0], refinancing_wall=[0.2])
    got = compute_cvs_frame(frame)
    assert got["cvs_tier"].iloc[0] == "moderate"
    assert got["cvs_missing_core"].iloc[0] == "net_debt_to_ebitda"


# ---------------------------------------------------------------------------
# Macro state
# ---------------------------------------------------------------------------


def test_a_macro_row_with_a_value_but_no_vintage_is_absent():
    """Section 9 forbids the current vintage, so an undated row cannot score.

    Using it would be a look-ahead with no downstream way to detect it: the
    number would be right and the date wrong, and the date is the part that
    matters when reproducing a past run.
    """
    assert not macro_state_from_row({"c_level": -1.0, "c_delta": 0.5}).present
    assert not macro_state_from_row({"c_level": -1.0, "c_delta": 0.5, "vintage": None}).present
    assert not macro_state_from_row(
        {"c_level": None, "c_delta": 0.5, "vintage": "2026-09-01"}
    ).present
    assert macro_state_from_row({"c_level": -1.0, "c_delta": 0.5, "vintage": "2026-09-01"}).present


def test_macro_state_rejects_a_half_observation():
    """A level with no velocity is the reading section 2.1 exists to prevent."""
    assert not MacroState(-1.0, None, "2026-09-01").present
    assert not MacroState(None, 0.5, "2026-09-01").present
    assert MacroState(-1.0, 0.5, "2026-09-01").present


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_layer_does_not_touch_scores_by_default():
    frame = _frame(debt_to_ebitda=[2.0] * 5, interest_coverage=[8.0] * 5)
    out = apply_regime_layer(frame)
    pd.testing.assert_series_equal(out["composite_score"], frame["composite_score"])


def test_layer_publishes_every_v0015_column():
    frame = _frame(debt_to_ebitda=[2.0] * 5, interest_coverage=[8.0] * 5)
    out = apply_regime_layer(frame)
    for column in (
        "market_regime",
        "credit_environment",
        "credit_modifier",
        "override_flag",
        "score_cap",
        "cvs_score",
        "cvs_coverage",
        "cvs_tier",
        "cvs_missing_core",
        "macro_vintage",
    ):
        assert column in out.columns, column


def test_layer_names_every_reason_it_is_inert():
    """An inert layer and a broken layer must be distinguishable from the row."""
    frame = _frame(debt_to_ebitda=[2.0] * 5, interest_coverage=[8.0] * 5)
    out = apply_regime_layer(frame)
    reasons = out["regime_gate_reason"].iloc[0].split(",")
    assert reasons == [GATE_MACRO_ABSENT, GATE_CVS_INCOMPLETE, GATE_BREAKERS_UNEVALUABLE]
    assert layer_readiness(out, MACRO_ABSENT) == reasons


def test_layer_stays_gated_while_breakers_are_unsourced():
    """Full CVS and macro evidence is not enough on its own.

    The gate tracks every input the layer needs, and two circuit breakers still
    have no source. Opening the gate on "the CVS computes now" would be the
    same missing-data-is-a-signal mistake the macro baseline made: the state
    that falls back to knowing less is rewarded for it.
    """
    frame = _frame(
        debt_to_ebitda=[2.0] * 5,
        interest_coverage=[8.0] * 5,
        quick_liquidity=[2.0] * 5,
        refinancing_wall=[0.2] * 5,
    )
    macro = MacroState(-1.0, 0.5, "2026-09-29")
    out = apply_regime_layer(frame, macro)
    assert out["cvs_tier"].eq("strong").all()
    assert out["regime_gate_reason"].iloc[0] == GATE_BREAKERS_UNEVALUABLE
    assert layer_readiness(out, macro) == [GATE_BREAKERS_UNEVALUABLE]


def test_gate_opens_once_every_breaker_has_a_source():
    """Every one of the five levers present, then the gate reason is empty."""
    frame = _frame(
        debt_to_ebitda=[2.0] * 5,
        interest_coverage=[8.0] * 5,
        quick_liquidity=[2.0] * 5,
        refinancing_wall=[0.2] * 5,
        maturity_2y=[0.1] * 5,
        credit_rating=[20.0] * 5,
    )
    macro = MacroState(-1.0, 0.5, "2026-09-29")
    sources = {
        "C1": ("fcf_payout",),
        "C2": ("debt_to_ebitda",),
        "C3": ("interest_coverage",),
        "C4": ("maturity_2y",),
        "C5": ("credit_rating",),
    }
    frame["fcf_payout"] = 0.5
    frame["maturity_2y"] = 0.1
    frame["credit_rating"] = 20.0
    out = apply_regime_layer(frame, macro, breaker_sources=sources)
    assert out["breakers_unavailable"].iloc[0] is None
    assert out["regime_gate_reason"].iloc[0] is None
    assert layer_readiness(out, macro) == []


def test_unscorable_cvs_never_gets_a_clean_modifier():
    """Section 5.3: an unmeasured balance sheet is not a strong one."""
    frame = _frame(debt_to_ebitda=[2.0] * 5, interest_coverage=[8.0] * 5)
    out = apply_regime_layer(frame)
    assert out["cvs_tier"].eq("unscorable").all()
    assert out["credit_modifier"].max() < 1.00


def test_macro_absent_reads_normal_not_accommodative():
    """The fallback state must not be the best credit in the table."""
    frame = _frame(debt_to_ebitda=[2.0] * 5, interest_coverage=[8.0] * 5)
    out = apply_regime_layer(frame)
    assert out["credit_environment"].iloc[0] == "Normal"
    assert out["credit_environment"].iloc[0] == credit_environment(0.0, 0.0)
    assert out["market_regime"].iloc[0] == determine_market_regime(0.0, 0.0, 0.0, 0.0)


def test_unsourced_breakers_are_excluded_not_treated_as_breaches():
    """C4 and C5 have no source, which is our gap and not their insolvency.

    Failing closed on them would give every security two breaches, hence RED
    and a 0.20 cap, publishing 5,443 insolvency verdicts on the grounds that an
    integration was never built. The rule that unknown is breached applies to a
    company's unevaluated lever; a source that does not exist tells us nothing
    about any company and is excluded and reported instead.
    """
    frame = _frame(debt_to_ebitda=[2.0] * 5, interest_coverage=[8.0] * 5, fcf_payout=[0.5] * 5)
    out = apply_regime_layer(frame)
    assert out["breakers_unavailable"].iloc[0] == "C4,C5"
    assert out["override_flag"].eq("GREEN").all()
    assert out["score_cap"].eq(1.00).all()


def test_a_measurable_breach_still_fires_with_two_levers_unsourced():
    """Excluding the unsourced levers must not disarm the ones that work."""
    frame = _frame(
        debt=[500.0] * 5,
        debt_to_ebitda=[2.0, 2.0, 2.0, 2.0, 6.0],
        interest_coverage=[8.0] * 5,
        fcf_payout=[-0.2, 0.5, 0.5, 0.5, 0.5],
    )
    out = apply_regime_layer(frame)
    assert out["override_flag"].tolist() == ["YELLOW", "GREEN", "GREEN", "GREEN", "YELLOW"]
    assert out["override_flag"].iloc[0] == "YELLOW"  # negative FCF
    assert out["override_flag"].iloc[4] == "YELLOW"  # leverage above 5.0x


def test_two_measurable_breaches_still_reach_red():
    """RED needs two levers, and we have three that work."""
    frame = _frame(
        debt=[900.0] * 3,
        debt_to_ebitda=[6.0] * 3,
        interest_coverage=[1.0] * 3,
        fcf_payout=[-0.2] * 3,
    )
    out = apply_regime_layer(frame)
    assert out["override_flag"].eq("RED").all()
    assert out["score_cap"].eq(0.20).all()


def test_a_breaker_missing_for_one_row_fails_closed_for_that_row():
    """The per-company case the fail-closed rule was written for.

    ``C4``/``C5`` are excluded because they have no source. A row whose
    *measurable* lever is missing is a different situation: that one company's
    coverage is unknown, and unknown is not safe.
    """
    frame = _frame(
        debt=[500.0] * 3,
        debt_to_ebitda=[2.0, np.nan, 2.0],
        interest_coverage=[8.0] * 3,
        fcf_payout=[0.5] * 3,
    )
    out = apply_regime_layer(frame)
    assert out["override_flag"].iloc[0] == "GREEN"
    assert out["override_flag"].iloc[1] == "YELLOW"  # leverage unknown for this row


def test_apply_scores_rescales_and_keeps_the_original():
    frame = _frame(
        debt_to_ebitda=[2.0, 6.0, 2.0, 2.0, 2.0],
        interest_coverage=[8.0] * 5,
        fcf_payout=[0.5] * 5,
    )
    out = apply_regime_layer(frame, apply_scores=True)
    assert "composite_score_unadjusted" in out.columns
    pd.testing.assert_series_equal(
        out["composite_score_unadjusted"].rename("composite_score"),
        frame["composite_score"],
    )
    # Row 1 breaches C2, so its cap is 0.45 and its modifier the unscorable
    # 0.85: min(0.81 * 0.85, 0.45) = 0.45. The rest stay GREEN at 0.85.
    expected = [min(cs * 0.85, cap) for cs, cap in zip(frame["composite_score"], out["score_cap"])]
    assert out["composite_score"].tolist() == pytest.approx(expected)


def test_a_null_composite_stays_null_through_the_layer():
    """The coverage floor's rejection has to survive the whole layer."""
    frame = _frame(debt_to_ebitda=[2.0] * 5, interest_coverage=[8.0] * 5)
    frame["composite_score"] = [0.9, np.nan, 0.5, np.nan, 0.1]
    out = apply_regime_layer(frame, apply_scores=True)
    assert out["composite_score"].isna().tolist() == [False, True, False, True, False]


def test_enabling_the_layer_today_would_flatten_the_ranking():
    """The measurement behind the default, on a stand-in for the universe.

    Mirrors the real warehouse: with no liquidity or macro input, every row's
    CVS is unscoreable and so every row takes the same 0.85 provisional
    modifier. A uniform multiplier is rank-preserving, which is exactly why it
    is worth asserting -- the layer would not reorder anything, it would just
    move the whole distribution down by 15% and publish a number that looks
    adjusted while carrying no cross-sectional information.
    """
    scores = pd.Series(np.linspace(0.05, 0.99, 1000))
    frame = pd.DataFrame(
        {
            "composite_score": scores,
            "debt_to_ebitda": 2.0,
            "interest_coverage": 8.0,
            "fcf_payout": 0.5,
        }
    )
    adjusted = apply_regime_layer(frame, apply_scores=True)["composite_score"]

    before = scores.rank(ascending=False, method="first")
    after = adjusted.rank(ascending=False, method="first")
    assert (before == after).all(), "a uniform modifier must not reorder rows"
    assert adjusted.max() < scores.max()
    assert adjusted.min() == pytest.approx(0.05 * 0.85)


def _regime_migration_text():
    """Concatenate every migration that adds a column to model.scores.

    V0015 created the regime columns and V0019 added c4_audit_warning to them.
    Reading only V0015 made this test fail on a correct change -- and the
    failure mode is the dangerous direction: an author who wanted the suite
    green would be pushed toward dropping the new column or special-casing the
    test, rather than toward making the schema agree with the code.
    """
    root = Path(__file__).resolve().parents[1] / "sql" / "migrations"
    return "\n".join(
        path.read_text()
        for path in sorted(root.glob("V00*.sql"))
        if "model.scores" in path.read_text()
    )


def test_every_persisted_column_matches_the_v0015_schema():
    """The INSERT in score_rank.py and the migrations must agree.

    These are separate files that name the same columns, and nothing in either
    checks the other -- a column added to one and not the other is an error at
    the first nightly run, in production, against a table with 5,163 existing
    rows. Asserting the contract here is cheaper than finding out there.
    """
    migration = _regime_migration_text()
    script = (Path(__file__).resolve().parents[1] / "scripts" / "score_rank.py").read_text()

    frame = _frame(debt_to_ebitda=[2.0] * 5, interest_coverage=[8.0] * 5)
    out = apply_regime_layer(frame)

    # Columns the layer reads rather than writes. These live in
    # model.features already; everything else on the frame is either a regime
    # column or a pre-existing model.scores column.
    inputs = {"security_id", "composite_score", *CVS_SOURCE_COLUMNS.values()}
    for column in out.columns:
        if column in inputs:
            continue
        assert f"ADD COLUMN IF NOT EXISTS {column} " in migration, column
        assert column in script, column


def test_the_tier_vocabulary_in_the_migration_covers_every_tier_the_code_emits():
    """An unscorable row is the common case, so the CHECK has to allow it."""
    migration = (
        Path(__file__).resolve().parents[1] / "sql" / "migrations" / "V0015_regime_layer.sql"
    ).read_text()

    frame = _frame(debt_to_ebitda=[2.0] * 5, interest_coverage=[8.0] * 5)
    tiers = set(apply_regime_layer(frame)["cvs_tier"])

    complete = _frame(
        debt_to_ebitda=[1.0, 4.0, 9.0],
        interest_coverage=[9.0, 2.0, 1.0],
        quick_liquidity=[3.0, 1.0, 0.5],
        refinancing_wall=[0.1, 0.6, 0.9],
    )
    tiers |= set(apply_regime_layer(complete)["cvs_tier"])

    check = [line for line in migration.splitlines() if "cvs_tier IN (" in line][0]
    for tier in tiers:
        assert tier in check, f"{tier} is emitted but not allowed by the CHECK"


def test_a_measurable_override_does_reorder():
    """The contrast case: once the levers work, the layer actually ranks.

    Without this the previous test could pass for the wrong reason -- a layer
    that changed nothing at all would also preserve the ranking.
    """
    frame = pd.DataFrame(
        {
            "composite_score": np.linspace(0.90, 0.60, 40),
            "debt_to_ebitda": 2.0,
            "interest_coverage": 8.0,
            "fcf_payout": 0.5,
        }
    )
    # Make the top of the distribution the ones that breach.
    frame.loc[frame.index[:10], "fcf_payout"] = -0.5
    before = frame["composite_score"].rank(ascending=False, method="first")
    adjusted = apply_regime_layer(frame, apply_scores=True)["composite_score"]
    after = adjusted.rank(ascending=False, method="first")
    assert (before != after).sum() >= 10


def test_c4_breaches_when_maturities_exceed_cash_not_at_half():
    """The threshold was a CVS bracket midpoint, not the condition.

    C4's stated condition is maturities exceeding available reserves, which for
    a ratio is 1.0. The first implementation used 0.5, so a company holding
    cash twice the size of everything falling due inside 18 months was flagged
    as sitting on a maturity cliff. That is not a conservative direction -- it
    is simply a different claim, and it fired on healthy balance sheets.
    """
    frame = pd.DataFrame(
        {
            "composite_score": [0.8] * 4,
            "debt_to_ebitda": [2.0] * 4,
            "interest_coverage": [8.0] * 4,
            # 0.4 and 0.9 are covered comfortably; 1.01 and 3.0 are not.
            "refinancing_wall": [0.4, 0.9, 1.01, 3.0],
        }
    )
    flags, caps, _, _, _ = evaluate_breakers(frame, pd.Series([50.0] * 4), MACRO_ABSENT)

    assert list(flags) == ["GREEN", "GREEN", "YELLOW", "YELLOW"], (
        "C4 must fire only when the cliff exceeds the reserves"
    )
    # A lone C4 breach is YELLOW, not RED: section 6.5 reserves RED for two or
    # more breaches, or C1 together with C4. The distinction matters here --
    # calling a single maturity cliff RED would overstate the finding.
    assert float(caps[0]) == 1.0 and float(caps[1]) == 1.0
    assert 0.20 < float(caps[2]) < 1.0


def test_c4_reads_the_derived_ratio_column():
    """The first implementation named a column that never existed.

    ``refinancing_wall_2y`` was neither in model.features nor produced by the
    extractor, so C4 could never have fired even if a maturity schedule had been
    present. The threshold map and the source map are now checked against the
    real feature column set.
    """
    from src.crispdm.features import FEATURE_COLUMNS

    assert "refinancing_wall_2y" not in CIRCUIT_BREAKER_SOURCES["C4"]
    assert "refinancing_wall" in FEATURE_COLUMNS
    for breaker, (column, _) in CIRCUIT_BREAKER_THRESHOLDS.items():
        assert column == CIRCUIT_BREAKER_SOURCES[breaker][0], breaker


def test_shadow_mode_publishes_a_cap_it_did_not_enforce():
    """The row shape that broke score_rank under V0015.

    Shadow mode leaves composite_score alone and still publishes the cap it
    computed. Every override row is therefore composite_score > score_cap --
    the pre-layer score above the ceiling that was withheld. That is the
    intended reading of a gated layer, not a contradiction, and it is the exact
    shape V0015's chk_scores_final_score_invariant rejected, which would have
    dropped the penalised companies from model.scores while the GREEN rows
    wrote cleanly. V0017 retracts the constraint; this pins the row shape so
    the two stay in agreement.
    """
    frame = pd.DataFrame(
        {
            "composite_score": np.linspace(0.90, 0.60, 40),
            "debt_to_ebitda": 2.0,
            "interest_coverage": 8.0,
            "fcf_payout": 0.5,
        }
    )
    frame.loc[frame.index[:10], "fcf_payout"] = -0.5

    out = apply_regime_layer(frame, apply_scores=False)

    capped = out[out["score_cap"] < 1.0]
    assert not capped.empty, "no override rows produced, so nothing is pinned"
    assert (capped["composite_score"] > capped["score_cap"]).all()
    # And the score itself is untouched, which is the other half of the claim.
    assert out["composite_score"].equals(frame["composite_score"])
    # The withheld cap still has to be recorded, or a reader cannot tell an
    # enforced ceiling from an absent one.
    assert capped["regime_gate_reason"].notna().all() or capped["override_flag"].ne("GREEN").all()


def test_a_shadow_row_with_a_cap_really_persists():
    """Write the row shape V0015 rejected, then roll it back.

    The two tests above this one are satisfied by reading schema: the
    constraint is absent, and the row shape is what we say it is. Neither
    actually inserts. So neither proves the insert is *accepted*, which is the
    only thing that matters -- a constraint can be absent and the write can
    still fail on a CHECK the migration added, on a NOT NULL, or on the
    vocabulary CHECKs.

    This is the write V0015 would have rejected: composite_score above
    score_cap, which is what shadow mode publishes on every override row. A
    green schema test that had never inserted a row is how V0015 shipped.
    """
    engine = None
    try:
        from src.crispdm.db import engine as db_engine

        with db_engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        engine = db_engine
    except Exception:  # pragma: no cover - environments without a database
        pytest.skip("no database available")

    frame = pd.DataFrame(
        {
            "composite_score": [0.72],
            "debt_to_ebitda": [2.0],
            "interest_coverage": [8.0],
            "fcf_payout": [-0.5],
        }
    )
    row = apply_regime_layer(frame).iloc[0]

    # Confirm the fixture is really the shape under test before asserting on it.
    assert pd.notna(row["score_cap"]) and row["score_cap"] < row["composite_score"], (
        f"expected composite > cap, got {row['composite_score']} / {row['score_cap']}"
    )

    with engine.connect() as conn:
        # Borrowing a real security_id avoids the reference.securities FK chain
        # (securities -> raw.company_ticker), and an as_of_date no run will ever
        # reach keeps the probe out of the way. The transaction is rolled back
        # rather than deleted, so a failure mid-test cannot leave a row behind.
        sid = conn.exec_driver_sql("SELECT security_id FROM reference.securities LIMIT 1").scalar()
        if sid is None:
            pytest.skip("no securities to borrow a security_id from")

        tx = conn.get_transaction() or conn.begin()
        try:
            # exec_driver_sql passes SQL through untouched, so the :binds need
            # text() to be substituted at all.
            conn.execute(
                text("""
                INSERT INTO model.scores
                    (security_id, as_of_date, composite_score, credit_modifier,
                     score_cap, override_flag, market_regime, cvs_tier)
                VALUES (:sid, DATE '2099-12-31', :co, 0.85, :sc, :of, :mr, :ct)
                """),
                {
                    "sid": sid,
                    "co": row["composite_score"],
                    "sc": row["score_cap"],
                    "of": row["override_flag"],
                    "mr": row["market_regime"],
                    "ct": row["cvs_tier"],
                },
            )
            stored = conn.execute(
                text("""
                SELECT composite_score, score_cap FROM model.scores
                WHERE security_id = :sid AND as_of_date = DATE '2099-12-31'
                """),
                {"sid": sid},
            ).one()
            assert float(stored[0]) > float(stored[1]), (
                "the row did not round-trip as the shadow shape it claims to be"
            )
        finally:
            tx.rollback()


def test_no_constraint_on_model_scores_rejects_the_shadow_row():
    """Check the live schema, not the migration text.

    V0015 shipped an unsatisfiable constraint and the whole suite passed,
    because every test in this file asserts against the SQL source as a string.
    Reading a string cannot tell you whether the constraint survives in the
    warehouse, whether a later migration retracted it, or whether the numbers
    being written satisfy it. This asks the database.
    """
    engine = None
    try:
        from src.crispdm.db import engine as db_engine

        with db_engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        engine = db_engine
    except Exception:  # pragma: no cover - environments without a database
        pytest.skip("no database available")

    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'model.scores'::regclass AND contype = 'c'
            """
        ).fetchall()
    names = {r[0] for r in rows}

    # Not present, or retracted: either way the shadow-mode row shape above is
    # writable. Asserting absence is the point -- a constraint that forbids a
    # legitimate published state is worse than no constraint.
    assert "chk_scores_final_score_invariant" not in names

    # The constraints that CAN hold are still there. Retracting an impossible
    # invariant must not take the vocabulary and range checks with it.
    assert "chk_scores_score_cap_range" in names
    assert "chk_scores_cvs_tier" in names


def test_a_missing_maturity_ladder_is_an_audit_warning_not_a_breach():
    """Section 5.5's fallback, and the single most consequential branch here.

    "This condition evaluates to Safe (False) only if Quick Liquidity >= 1.20x
    and Net Debt / EBITDA <= 2.0x; otherwise, it flags an audit warning."

    An audit warning is a data-quality statement, not a solvency verdict. The
    failure mode this pins is concrete: 3,915 of 4,907 securities disclose no
    maturity ladder, so failing C4 closed on absent footnote data marked every
    one of them C4-true and pushed 90% of the universe to RED.
    """
    frame = _frame(
        refinancing_wall=[float("nan"), 1.5, float("nan")],
        quick_liquidity=[2.0, 2.0, 0.5],
        debt_to_ebitda=[1.0, 1.0, 4.0],
    )
    flags, caps, _unavailable, warnings, _exempt = evaluate_breakers(
        frame, pd.Series([20.0, 20.0, 20.0]), MacroState(None, None, None)
    )

    # Row 0: no ladder, but the proxies clear -> Safe, not an audit warning.
    assert flags[0] == "GREEN"
    # Row 1: a real ladder above 1.0 -> a genuine breach.
    assert flags[1] == "YELLOW"
    # Row 2: no ladder and the proxies fail -> still an audit warning, not RED.
    assert flags[2] == "GREEN"
    assert warnings == 1, "weak proxies leave C4 unverifiable, so warn on it"


def test_c4_is_unverifiable_and_flagged_when_both_ladder_and_proxies_are_absent():
    """The case worth counting: nothing to evaluate C4 on, at all.

    This row must be distinguishable from one that passed. Without the flag,
    "C4 did not fire" and "C4 could not run" are the same observation, which is
    how a missing integration hides behind a clean-looking column.
    """
    frame = _frame(
        refinancing_wall=[float("nan")],
        quick_liquidity=[float("nan")],
        debt_to_ebitda=[1.0],
    )
    flags, _caps, _unavailable, warnings, _exempt = evaluate_breakers(
        frame, pd.Series([20.0]), MacroState(None, None, None)
    )
    assert flags == ["GREEN"]
    assert warnings == 1

    out = apply_regime_layer(frame, MacroState(None, None, None))
    assert list(out["c4_audit_warning"]) == [True]


def test_the_fallback_never_overrides_a_disclosed_maturity_ladder():
    """The proxies are a fallback, not a second opinion.

    A filer that discloses its schedule has answered the question; the proxies
    must not overrule a schedule that clears C4. If they did, healthy companies
    with real disclosure would be flagged on the strength of a ratio.
    """
    # Weak proxies, but deliberately not so weak that C2 fires independently:
    # 4.5x leverage is inside C2's 5.0x threshold, so the only lever in play
    # is C4 and a YELLOW here would mean the proxies had overruled the ladder.
    frame = _frame(
        refinancing_wall=[0.2],
        quick_liquidity=[0.4],
        debt_to_ebitda=[4.5],
    )
    flags, _caps, _unavailable, warnings, _exempt = evaluate_breakers(
        frame, pd.Series([20.0]), MacroState(None, None, None)
    )
    assert flags == ["GREEN"], "a disclosed, healthy ladder wins over the proxies"
    assert warnings == 0


def test_a_firm_with_no_debt_instruments_is_exempt_not_failed():
    """The precondition: no interest-bearing debt means no leverage ratio exists.

    Net Debt / EBITDA and Interest Coverage are undefined for an unlevered
    filer. Failing them closed says "we could not evaluate this firm's solvency"
    about a firm with nothing to repay -- it penalises a clean balance sheet as
    though it were a disclosure gap.
    """
    frame = _frame(
        debt=[None, 0.0],
        debt_to_ebitda=[np.nan, np.nan],
        interest_coverage=[np.nan, np.nan],
        fcf_payout=[0.5, 0.5],
    )
    out = apply_regime_layer(frame, MacroState(None, None, None))
    assert out["override_flag"].tolist() == ["GREEN", "GREEN"]
    assert out["score_cap"].tolist() == [1.0, 1.0]
    assert list(out["debt_exempt"]) == [True, True]


def test_fail_closed_survives_where_it_belongs():
    """Debt present, ratio absent: a real gap, still a breach.

    The precondition keys on debt *presence*, never on the ratio being missing.
    A firm with $500m of debt and no leverage ratio has withheld something; a
    firm with no debt has withheld nothing. Collapsing those two cases is the
    mistake this pair of tests exists to prevent.
    """
    frame = _frame(
        debt=[500.0],
        debt_to_ebitda=[np.nan],
        interest_coverage=[8.0],
        fcf_payout=[0.5],
    )
    out = apply_regime_layer(frame, MacroState(None, None, None))
    assert out["override_flag"].iloc[0] == "YELLOW", "must still fail closed"
    assert list(out["debt_exempt"]) == [False]


def test_a_levered_firm_is_still_evaluated_against_its_threshold():
    """EXEMPT must not leak into firms that do have debt.

    An exemption that triggered on anything other than the absence of debt
    would silently switch off the leverage gate for exactly the firms it exists
    to police.
    """
    frame = _frame(
        debt=[900.0],
        debt_to_ebitda=[6.0],
        interest_coverage=[8.0],
        fcf_payout=[0.5],
    )
    out = apply_regime_layer(frame, MacroState(None, None, None))
    assert out["override_flag"].iloc[0] == "YELLOW", "6.0x leverage breaches C2"
    assert list(out["debt_exempt"]) == [False]


def test_no_debt_column_means_nobody_is_exempted():
    """The guard against exempting the whole universe by accident.

    If the precondition cannot be evaluated it must not be assumed satisfied.
    A build that dropped the `debt` column would otherwise report every row as
    unlevered and hand back a clean sheet.
    """
    frame = _frame(
        debt_to_ebitda=[np.nan] * 3,
        interest_coverage=[np.nan] * 3,
        fcf_payout=[0.5] * 3,
    )
    out = apply_regime_layer(frame, MacroState(None, None, None))
    assert not out["debt_exempt"].any()
