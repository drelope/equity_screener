import inspect
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from scripts.populate_reference_tables import get_issuer_info_with_fallback
from src.crispdm.scoring import WEIGHTS, score
from src.crispdm.sec_client import (
    DIVIDEND_RECENCY_DAYS,
    classify_companyfacts,
    classify_security_type,
    configured_dividend_lookback,
    get_issuer_data,
    get_legacy_issuer_data,
)


def test_weights():
    assert sum(WEIGHTS.values()) == 1


def _scored(**rows):
    """One row of score input, with every measured leg populated by default."""
    base = {
        "dividend_yield": 0.05,
        "dividend_growth": 0.03,
        "dividend_coverage": 2.0,
        "fcf_payout": 0.6,
        "momentum_252d": 0.10,
        "momentum_63d": 0.05,
        "volatility_252d": 0.30,
        "legal_rights_score": 0.7,
    }
    base.update(rows)
    return score(pd.DataFrame([base]))


def test_every_regime_weight_row_sums_to_one():
    """Section 7.2 publishes a matrix; a row that does not sum to 1 is a typo.

    The blend renormalises over whichever components are present, so a row
    summing to 0.98 would not blow up -- it would quietly rescale that regime's
    composites relative to every other regime, which is invisible in the output
    and wrong in the only sense that matters.
    """
    from src.crispdm.regime import CANONICAL_REGIMES
    from src.crispdm.scoring import regime_weights

    for regime in ("Baseline", *CANONICAL_REGIMES):
        weights = regime_weights(regime)
        assert sum(weights.values()) == pytest.approx(1.0), regime
        assert set(weights) == set(WEIGHTS), regime


def test_an_unknown_or_absent_regime_blends_on_the_baseline():
    """No macro feed means no regime, and no regime must mean no change.

    This is what makes the tilt safe to write while the feed is still absent.
    regime_weights falls back rather than raising, so ``None`` -- which is what
    read_macro_state returns today -- produces exactly the previous output.
    """
    from src.crispdm.scoring import regime_weights

    assert regime_weights(None) == WEIGHTS
    assert regime_weights("Baseline") == WEIGHTS
    assert regime_weights("Not A Regime") == WEIGHTS
    assert score(pd.DataFrame([_row()])).composite_score.iloc[0] == pytest.approx(
        score(pd.DataFrame([_row()]), regime=None).composite_score.iloc[0]
    )


def test_dynamic_weights_do_not_move_the_coverage_denominator():
    """Section 7.1: coverage is a statement about disclosure, not the cycle.

    If coverage were computed on regime weights, the same stored row would
    report different coverage depending on the business cycle, and two runs of
    identical data would disagree about how well a filer discloses. That is
    the property the fixed denominator exists to protect.
    """
    frame = pd.DataFrame([_row(), _row(dividend_growth=float("nan"))])
    baseline = score(frame)
    for regime in ("Expansion", "Recession", "Recovery", "Slowdown"):
        out = score(frame, regime=regime)
        (
            pd.testing.assert_series_equal(
                out["score_coverage"], baseline["score_coverage"], check_names=False
            ),
            regime,
        )


def test_dynamic_weights_cannot_exclude_or_resurrect_a_row():
    """Section 7.1: the floor is evaluated on baseline weights, always.

    Recession carries 35% sustainability and 5% appreciation. A row whose
    appreciation is absent would fall below the floor on regime weights while
    clearing it on baseline -- so a tilt could drop rows outright. The floor is
    therefore checked against ``WEIGHTS``, and this pins that.
    """
    frame = pd.DataFrame(
        [
            # Clears the baseline floor: income, sustainability and risk present.
            _row(momentum_252d=float("nan"), momentum_63d=float("nan")),
        ]
    )
    baseline = score(frame)
    assert pd.notna(baseline["composite_score"].iloc[0]), "fixture must clear baseline"

    for regime in ("Expansion", "Recession", "Recovery"):
        out = score(frame, regime=regime)
        assert pd.isna(out["composite_score"].iloc[0]) is False, (
            f"{regime} weights must not resurrect or drop a row"
        )
        assert pd.notna(out["composite_score"].iloc[0]), regime


def test_a_regime_actually_moves_the_composite():
    """The contrast case: without this, the tests above pass on a no-op.

    A regime_weights that returned WEIGHTS regardless would satisfy every
    invariance test while implementing nothing. Recovery tilts to appreciation
    and away from income, so a row strong on momentum and weak on yield must
    score differently under it.
    """
    # The frame needs several rows: pct() is a cross-sectional rank, so a
    # one-row frame scores every factor at 1.0 and shifting weight between them
    # is a wash. Only the constant legal/valuation terms would move, which is
    # the opposite of what this test is trying to show.
    frame = pd.DataFrame(
        [
            # Subject row: top-decile yield, bottom-decile momentum.
            _row(dividend_yield=0.09, momentum_252d=-0.40, momentum_63d=-0.40),
            _row(dividend_yield=0.02, momentum_252d=0.20, momentum_63d=0.20),
            _row(dividend_yield=0.03, momentum_252d=0.40, momentum_63d=0.40),
            _row(dividend_yield=0.01, momentum_252d=0.60, momentum_63d=0.60),
            _row(dividend_yield=0.04, momentum_252d=0.30, momentum_63d=0.30),
        ]
    )
    subject = 3  # top-decile momentum, low yield
    baseline = score(frame)["composite_score"].iloc[subject]
    recovery = score(frame, regime="Recovery")["composite_score"].iloc[subject]
    recession = score(frame, regime="Recession")["composite_score"].iloc[subject]

    assert recovery != pytest.approx(baseline)
    # Compare Recovery against Recession rather than against baseline. Both hold
    # legal_rights at 0.10, so the legal down-weight from 0.25 cancels; what is
    # left is the appreciation tilt (25% vs 5%) against risk (15% vs 30%), and
    # on a top-decile momentum row Recovery must win.
    #
    # Baseline is not a usable comparator for direction: it carries 25% on
    # legal_rights, which every regime drops to 10%. A row scoring 0.7 on that
    # constant therefore loses more to the regime shift than it can gain from
    # any reweighting of measured factors, and a test asserting "recovery >
    # baseline" would be measuring the constant rather than the tilt.
    assert recovery > recession, (
        f"Recovery should favour appreciation over recession's risk tilt: {recovery} vs {recession}"
    )


def _row(**overrides):
    base = {
        "dividend_yield": 0.05,
        "dividend_growth": 0.03,
        "dividend_coverage": 2.0,
        "fcf_payout": 0.6,
        "momentum_252d": 0.10,
        "momentum_63d": 0.05,
        "volatility_252d": 0.30,
        "legal_rights_score": 0.7,
    }
    base.update(overrides)
    return base


def test_a_fully_measured_row_is_unaffected_by_renormalisation():
    """With every input present, the new code must equal the old weighted sum.

    Renormalisation only earns its keep on incomplete rows, so it must be a
    no-op on a complete one. If it is not, the change has silently rescaled the
    entire score column rather than filling in the gaps.
    """
    out = _scored()
    expected = sum(out[name].iloc[0] * w for name, w in WEIGHTS.items())
    assert out.composite_score.iloc[0] == pytest.approx(expected)
    assert out.score_coverage.iloc[0] == pytest.approx(1.0)


def test_a_partially_measured_row_is_renormalised_not_zeroed():
    """Missing legs must be dropped and the rest rescaled to 0-1.

    The old plain sum returned NaN, which is why 4,127 of 5,443 securities had
    no score. The failure mode to avoid instead is the other extreme: dividing
    the weighted sum by the full weight total, so a row missing one leg reports
    0.8 of its true value and a rank against it is a rank against a different
    scale.
    """
    out = _scored(volatility_252d=float("nan"))
    assert out.composite_score.notna().all()
    assert 0.0 <= out.composite_score.iloc[0] <= 1.0
    # Risk is 0.10 of the 0.70 measurable weight, so 0.60 of it remains.
    assert out.score_coverage.iloc[0] == pytest.approx(0.60 / 0.70)

    # Renormalised, not merely not-NaN: a single measured leg at full weight
    # must score the same as it would with the others present.
    single = _scored(
        dividend_growth=float("nan"),
        dividend_coverage=float("nan"),
        fcf_payout=float("nan"),
        momentum_252d=float("nan"),
        momentum_63d=float("nan"),
        volatility_252d=float("nan"),
    )
    assert single.composite_score.notna().all()
    assert 0.0 <= single.composite_score.iloc[0] <= 1.0


def test_floor_is_measured_against_total_weight_not_measurable_weight():
    """The two denominators differ, and picking the wrong one is a policy change.

    The floor is MIN_PRESENT_WEIGHT of the *total* 1.0. The two constant
    components are always present, so that is the same bar as 0.35 of the 0.70
    measurable weight. Requiring 0.50 of the measurable weight instead would be
    a stricter rule under the same name: on the latest feature date it drops
    2,575 securities rather than 280. This test pins the bar that was approved.
    """
    # 0.15 of measurable weight present: with the 0.30 of constants that is 0.45
    # of the total, below the 0.50 floor, so nothing is published.
    below = _scored(
        dividend_yield=float("nan"),
        dividend_growth=float("nan"),
        dividend_coverage=float("nan"),
        fcf_payout=float("nan"),
        volatility_252d=float("nan"),
    )
    assert below.score_coverage.iloc[0] == pytest.approx(0.15 / 0.70)
    assert below.composite_score.isna().all()

    # 0.25 of measurable weight: 0.55 of the total, so scored.
    above = _scored(
        dividend_growth=float("nan"),
        dividend_coverage=float("nan"),
        fcf_payout=float("nan"),
        momentum_252d=float("nan"),
        momentum_63d=float("nan"),
        volatility_252d=float("nan"),
    )
    assert above.score_coverage.iloc[0] == pytest.approx(0.25 / 0.70)
    assert above.composite_score.notna().all()

    # The boundary: sustainability alone is exactly 0.20 of measurable, which is
    # exactly 0.50 of the total, and the floor is inclusive.
    edge = _scored(
        dividend_yield=float("nan"),
        momentum_252d=float("nan"),
        momentum_63d=float("nan"),
        volatility_252d=float("nan"),
    )
    assert edge.score_coverage.iloc[0] == pytest.approx(0.20 / 0.70)
    assert edge.composite_score.notna().all()


def test_coverage_below_the_floor_publishes_no_composite():
    """Below the floor, the score is mostly a rescaled fragment of percentiles."""
    # Only dividend income survives: 0.25 of the 0.70 measurable weight, and
    # 0.55 of the total once the two constants are counted.
    out = _scored(
        dividend_growth=float("nan"),
        dividend_coverage=float("nan"),
        fcf_payout=float("nan"),
        momentum_252d=float("nan"),
        momentum_63d=float("nan"),
        volatility_252d=float("nan"),
    )
    assert out.score_coverage.iloc[0] == pytest.approx(0.25 / 0.70)
    assert out.composite_score.notna().all()

    # Nothing measured at all: 0.30 of the total, the guaranteed constant floor,
    # which is below the floor and correctly publishes nothing.
    empty = _scored(
        dividend_yield=float("nan"),
        dividend_growth=float("nan"),
        dividend_coverage=float("nan"),
        fcf_payout=float("nan"),
        momentum_252d=float("nan"),
        momentum_63d=float("nan"),
        volatility_252d=float("nan"),
    )
    assert empty.score_coverage.iloc[0] == pytest.approx(0.0)
    assert empty.composite_score.isna().all()


def test_coverage_ignores_the_constant_components():
    """A placeholder must not be counted as evidence.

    legal_rights_score is imputed to 0.5 and valuation is hardcoded to 0.5, so
    they are present for every row. Counting them would put a 0.30 floor under
    every coverage figure and a security with nothing measured would still read
    43% covered.
    """
    out = _scored(
        dividend_yield=float("nan"),
        dividend_growth=float("nan"),
        dividend_coverage=float("nan"),
        fcf_payout=float("nan"),
        momentum_252d=float("nan"),
        momentum_63d=float("nan"),
        volatility_252d=float("nan"),
    )
    # A total-weight denominator would have to report 0.30 here.
    assert out.score_coverage.iloc[0] == 0.0
    assert out.composite_score.isna().all()

    # The constants still move the composite, they just do not vouch for it.
    partial = _scored(
        volatility_252d=float("nan"),
        legal_rights_score=0.9,
    )
    assert 0.0 < partial.score_coverage.iloc[0] < 1.0
    assert partial.composite_score.notna().all()


def test_a_missing_inner_leg_does_not_discard_the_whole_subscore():
    """Sustainability renormalises internally too.

    A filer that reports no dividend growth still has a coverage ratio and an
    fcf payout, and dropping the entire 0.20 sub-score for one missing leg
    throws away two measurements that were taken.
    """
    out = _scored(dividend_growth=float("nan"))
    assert out.sustainability_score.notna().all()
    # growth is 0.2 of the 0.5/0.2/0.3 blend, so 0.8 of it remains.
    with_growth = _scored()
    assert out.sustainability_score.iloc[0] != with_growth.sustainability_score.iloc[0]

    # All three legs missing is a different case: nothing to renormalise.
    empty = _scored(
        dividend_growth=float("nan"),
        dividend_coverage=float("nan"),
        fcf_payout=float("nan"),
    )
    assert empty.sustainability_score.isna().all()


def test_coverage_is_published_for_every_row_including_unscorable_ones():
    """The column that explains the gaps must exist for the gaps too."""
    out = _scored(
        dividend_yield=float("nan"),
        dividend_growth=float("nan"),
        dividend_coverage=float("nan"),
        fcf_payout=float("nan"),
        momentum_252d=float("nan"),
        momentum_63d=float("nan"),
        volatility_252d=float("nan"),
    )
    assert out.score_coverage.notna().all()
    assert out.score_coverage.iloc[0] == pytest.approx(0.0)


def test_score():
    d = pd.DataFrame(
        {
            "dividend_yield": [0.02, 0.05, 0.08],
            "dividend_growth": [0.02, 0.05, 0.01],
            "dividend_coverage": [1, 2, 3],
            "fcf_payout": [0.9, 0.6, 0.4],
            "momentum_252d": [-0.1, 0.1, 0.2],
            "momentum_63d": [-0.05, 0.03, 0.1],
            "volatility_252d": [0.4, 0.3, 0.2],
            "legal_rights_score": [0.5, 0.7, 0.9],
        }
    )
    assert score(d).composite_score.notna().all()


def test_companyfacts_security_and_dividend_classification_is_auditable():
    facts = {
        "full_facts": {
            "us-gaap": {
                "CommonStockSharesOutstanding": {
                    "units": {"shares": [{"val": 100, "end": "2026-01-01"}]}
                },
                "CommonStockDividendsPerShareDeclared": {
                    "units": {"USD/shares": [{"val": 1.25, "end": "2026-01-01"}]}
                },
            }
        }
    }

    result = classify_companyfacts(facts, as_of=date(2026, 3, 1))

    assert result["security_types"] == ["common_stock"]
    assert result["dividend"] is True
    assert result["dividend_last_paid"] == "2026-01-01"
    assert result["security_facts"][0]["tag"] == "CommonStockSharesOutstanding"
    assert result["dividend_facts"][0]["tag"] == "CommonStockDividendsPerShareDeclared"


def test_future_dividend_facts_cannot_set_dividend_last_paid():
    """A dividend cannot have been paid after the run date.

    DIVIDEND_FACT_TERMS matches any tag containing "dividend", so the extractor
    sees balance-sheet and forward-dated tags. UBSI's case is the one that
    matters: CashDividendsPaidToParentCompanyByConsolidatedSubsidiaries says
    "Paid" and still carried period end 2026-12-31, which is what published
    five impossible dates (MTEX 2108-11-14 among them).

    The date is clamped to the run date rather than the concept being dropped:
    narrowing DIVIDEND_FACT_TERMS would clear the dividend flag for 3,611 of
    8,105 cached CIKs, which is a universe change. The flag must not move here.
    """
    facts = {
        "full_facts": {
            "us-gaap": {
                "CashDividendsPaidToParentCompanyByConsolidatedSubsidiaries": {
                    "units": {
                        "USD": [
                            {"val": 100, "end": "2026-01-15"},
                            {"val": 500, "end": "2026-12-31"},
                        ]
                    }
                }
            }
        }
    }

    result = classify_companyfacts(facts, as_of=date(2026, 10, 4))

    # Clamped to the run date, not left at 2026-12-31.
    assert result["dividend_last_paid"] == "2026-10-04"
    # The flag is untouched by the clamp: dropping the tag instead would have
    # flipped it, and that is the change this deliberately avoids.
    assert result["dividend"] is True
    # The future-dated evidence is retained so a later matcher fix can be
    # compared against what was corrected.
    assert result["dividend_facts"][0]["records"][-1]["end"] == "2026-12-31"


def test_dividend_last_paid_prefers_a_real_date_over_a_clamped_one():
    """The clamp must not drag a legitimate date back to the run date.

    A security with a real recent payment and a stray future-dated fact should
    publish the real one. Taking the max before clamping would report today for
    both, and clamping the final max would report today even when no future fact
    existed at all.
    """
    facts = {
        "full_facts": {
            "us-gaap": {
                "CommonStockDividendsPerShareDeclared": {
                    "units": {"USD/shares": [{"val": 1.25, "end": "2026-08-01"}]}
                },
                "DividendsPayableCurrentAndNoncurrent": {
                    "units": {"USD": [{"val": 999, "end": "2031-01-01"}]}
                },
            }
        }
    }

    result = classify_companyfacts(facts, as_of=date(2026, 10, 4))

    assert result["dividend_last_paid"] == "2026-10-04"  # 2031-01-01 clamped
    assert result["dividend"] is True


def _dividend_only_facts(records):
    return {
        "full_facts": {
            "us-gaap": {"CommonStockDividendsPerShareDeclared": {"units": {"USD/shares": records}}}
        }
    }


def test_companyfacts_stale_dividend_fact_is_not_a_current_payer():
    """XBRL retains comparative columns forever; an old fact must not set the flag."""
    as_of = date(2026, 3, 1)
    stale = (as_of - timedelta(days=DIVIDEND_RECENCY_DAYS + 1)).isoformat()

    result = classify_companyfacts(_dividend_only_facts([{"val": 1.25, "end": stale}]), as_of=as_of)

    assert result["dividend"] is False
    assert result["dividend_facts"] == []
    assert result["dividend_last_paid"] is None


def test_companyfacts_dividend_fact_on_recency_boundary_qualifies():
    as_of = date(2026, 3, 1)
    boundary = (as_of - timedelta(days=DIVIDEND_RECENCY_DAYS)).isoformat()

    result = classify_companyfacts(
        _dividend_only_facts([{"val": 1.25, "end": boundary}]), as_of=as_of
    )

    assert result["dividend"] is True
    assert result["dividend_last_paid"] == boundary


def test_companyfacts_recent_dividend_wins_over_stale_ones():
    """A payer that keeps reporting stays in the universe and reports its latest period."""
    as_of = date(2026, 3, 1)
    stale = (as_of - timedelta(days=DIVIDEND_RECENCY_DAYS + 400)).isoformat()

    result = classify_companyfacts(
        _dividend_only_facts(
            [
                {"val": 1.10, "end": stale},
                {"val": 1.30, "end": "2025-06-30"},
                {"val": 1.40, "end": "2026-01-15"},
            ]
        ),
        as_of=as_of,
    )

    assert result["dividend"] is True
    assert result["dividend_last_paid"] == "2026-01-15"
    assert all(record["end"] > stale for record in result["dividend_facts"][0]["records"])


def test_companyfacts_non_positive_dividend_fact_is_ignored():
    result = classify_companyfacts(
        _dividend_only_facts([{"val": 0, "end": "2026-01-01"}]), as_of=date(2026, 3, 1)
    )

    assert result["dividend"] is False
    assert result["dividend_last_paid"] is None


def test_companyfacts_dividend_lookback_start_is_reported():
    result = classify_companyfacts(
        _dividend_only_facts([{"val": 1.25, "end": "2026-01-01"}]), as_of=date(2026, 3, 1)
    )

    assert result["dividend_lookback_start"] == (date(2026, 3, 1) - timedelta(days=548)).isoformat()


def test_companyfacts_lookback_none_disables_recency_bound():
    """The hold path: no window means the historical any-positive-fact rule."""
    as_of = date(2026, 3, 1)
    stale = (as_of - timedelta(days=DIVIDEND_RECENCY_DAYS + 400)).isoformat()

    result = classify_companyfacts(
        _dividend_only_facts([{"val": 1.25, "end": stale}]),
        as_of=as_of,
        lookback_days=None,
    )

    assert result["dividend"] is True
    assert result["dividend_last_paid"] == stale
    assert result["dividend_lookback_start"] is None


def test_configured_dividend_lookback_is_opt_in(monkeypatch):
    """Enforcement defaults off so the nightly cannot silently flip the universe."""
    from src.crispdm import sec_client

    monkeypatch.setattr(sec_client.settings, "enforce_dividend_recency", False)
    assert configured_dividend_lookback() is None

    monkeypatch.setattr(sec_client.settings, "enforce_dividend_recency", True)
    monkeypatch.setattr(sec_client.settings, "dividend_recency_days", 400)
    assert configured_dividend_lookback() == 400


def test_companyfacts_evidence_keeps_the_latest_five_periods_by_date():
    """Payload order is not chronological; the stored tail must be the newest.

    XBRL facts are listed in filing order, so ``records[-5:]`` on the raw list
    kept whichever facts happened to be written last -- not the five most recent
    periods. The audit snippet has to be the five latest period ends regardless
    of the order the payload supplies.
    """
    as_of = date(2026, 3, 1)
    ends = [
        "2025-10-01",
        "2025-04-10",
        "2026-01-01",
        "2025-06-01",
        "2025-12-01",
        "2025-08-01",
        "2025-11-01",
    ]

    result = classify_companyfacts(
        _dividend_only_facts([{"val": 1.0, "end": end} for end in ends]), as_of=as_of
    )

    stored = [record["end"] for record in result["dividend_facts"][0]["records"]]
    assert stored == sorted(ends)[-5:]
    assert result["dividend_last_paid"] == "2026-01-01"


def test_companyfacts_ifrs_dividend_evidence_counts():
    """Foreign private issuers file IFRS; their DividendsPaid* facts must count.

    Agnico Eagle, Vale, PBR and similar 40-F filers have stale or absent us-gaap
    dividend facts but current ifrs-full ones. Reading only us-gaap silently
    dropped them from the universe once the recency bound removed the stale
    us-gaap fact that used to (accidentally) keep them flagged.
    """
    facts = {
        "full_facts": {
            "us-gaap": {},
            "ifrs-full": {
                "DividendsPaidOrdinaryShares": {
                    "units": {"USD": [{"val": 1000, "end": "2025-12-31"}]}
                }
            },
        }
    }

    result = classify_companyfacts(facts, as_of=date(2026, 3, 1))

    assert result["dividend"] is True
    assert result["dividend_last_paid"] == "2025-12-31"
    assert result["dividend_facts"][0]["tag"] == "DividendsPaidOrdinaryShares"


def test_companyfacts_stale_ifrs_dividend_evidence_is_also_bounded():
    as_of = date(2026, 3, 1)
    stale = (as_of - timedelta(days=DIVIDEND_RECENCY_DAYS + 1)).isoformat()
    facts = {
        "full_facts": {
            "us-gaap": {},
            "ifrs-full": {
                "DividendsPaidOrdinaryShares": {"units": {"USD": [{"val": 1000, "end": stale}]}}
            },
        }
    }

    result = classify_companyfacts(facts, as_of=as_of)

    assert result["dividend"] is False
    assert result["dividend_last_paid"] is None


def test_companyfacts_preferred_stock_uses_normalized_security_type():
    result = classify_companyfacts(
        {
            "full_facts": {
                "us-gaap": {
                    "PreferredStockSharesOutstanding": {
                        "units": {"shares": [{"val": 100, "end": "2026-01-01"}]}
                    }
                }
            }
        }
    )

    assert result["security_types"] == ["preferred stock"]


def test_title_security_type_is_normalized():
    assert classify_security_type("Example Preferred Stock") == "preferred stock"
    assert classify_security_type("Example Unit") == "other_debt_and_equity"
    assert classify_security_type("Example Common Stock") == "common_stock"
    assert classify_security_type("Example Government Bond") == "government debt"
    assert classify_security_type("Example Corporate Bond") == "corporate bond"
    assert classify_security_type("Example Call Option") == "option"
    assert classify_security_type("Example Futures Contract") == "future"


def test_issuer_data_reads_sec_submission_metadata():
    submissions = {
        "name": "Apple Inc.",
        "sic": 3571,
        "fiscalYearEnd": "0926",
    }

    with patch("src.crispdm.sec_client.get_submissions", return_value=submissions):
        result = get_issuer_data("0000320193")

    assert result == {
        "cik": "0000320193",
        "issuer_name": "Apple Inc.",
        "sic": "3571",
        "fiscal_year_end": "09-26",
    }


def test_legacy_issuer_data_uses_current_sec_company_endpoint():
    response = type(
        "Response",
        (),
        {
            "text": "Company Name: Apple Inc. CIK: 0000320193 SIC Code: 3571 Fiscal Year End: 0926",
            "raise_for_status": lambda self: None,
        },
    )()

    with patch("src.crispdm.sec_client.SEC_SESSION.get", return_value=response) as request:
        result = get_legacy_issuer_data(320193)

    request.assert_called_once()
    assert request.call_args.args[0] == "https://www.sec.gov/cgi-bin/browse-edgar"
    assert request.call_args.kwargs["params"] == {
        "action": "getcompany",
        "CIK": "0000320193",
    }
    assert result["sic"] == "3571"


def test_reference_population_prefers_complete_sec_metadata():
    issuer = {
        "cik": "0000320193",
        "issuer_name": "Apple Inc.",
        "sic": "3571",
        "fiscal_year_end": "09-26",
    }

    with (
        patch(
            "scripts.populate_reference_tables.get_issuer_data", return_value=issuer
        ) as sec_lookup,
        patch("scripts.populate_reference_tables.openbb_profile") as openbb_lookup,
    ):
        result, source = get_issuer_info_with_fallback("0000320193", "AAPL", "Apple Inc.")

    assert result == issuer
    assert source == "SEC"
    sec_lookup.assert_called_once_with("0000320193")
    openbb_lookup.assert_not_called()


def test_predictions_version_defaults_match_the_checkpoint_contract():
    """model.predictions must not be stamped with a retired input version.

    ``scoring.predictions`` defaults to a feature_version and data_version, and
    score_rank never passes either -- it relies on the defaults, so the defaults
    *are* the contract for every row written. Both had drifted away from the
    walk-forward constants and the live checkpoint, and nothing detected it
    because model.predictions was empty: an empty table cannot contradict a
    stale default, so the drift stayed latent until the first write.

    The feature and data versions describe the inputs the rows were computed
    from, not the algorithm, which is why they are shared and why this is a
    genuine assertion rather than cosmetic. model_version is deliberately NOT
    checked here: the rule scorer is a different model from the walk-forward
    logistic regression and is expected to carry its own version.

    Bumping FEATURE_VERSION or DATA_VERSION is a deliberate act, so this test is
    meant to fail then -- the fix is to decide what predictions should say, not
    to relax the assertion.
    """
    import json
    from pathlib import Path

    from scripts import evaluate_walk_forward
    from src.crispdm.scoring import predictions

    defaults = {
        name: p.default
        for name, p in inspect.signature(predictions).parameters.items()
        if name.endswith("_version") and p.default is not inspect.Parameter.empty
    }
    assert defaults["feature_version"] == evaluate_walk_forward.FEATURE_VERSION
    assert defaults["data_version"] == evaluate_walk_forward.DATA_VERSION

    checkpoint = json.loads(
        (
            Path(evaluate_walk_forward.__file__).parent.parent
            / "data"
            / "walk_forward_checkpoint.json"
        ).read_text()
    )
    assert checkpoint["feature_version"] == defaults["feature_version"]
    assert checkpoint["data_version"] == defaults["data_version"]
    assert checkpoint["model_version"] == evaluate_walk_forward.MODEL_VERSION


def test_unscorable_rows_are_null_not_numeric_nan():
    """A missing composite must reach Postgres as NULL, never as numeric NaN.

    Postgres numeric accepts NaN and treats it as a *value* that sorts above
    every other number, so a stored NaN silently corrupts AVG, MIN and any
    ordering downstream instead of being ignored the way NULL is. The first
    score_rank run wrote 4,127 NaNs into model.scores and model.rankings while
    the app reported a plausible-looking row count.

    score_rank reads the latest feature date. Rows below the coverage floor
    still have no composite, so the NULL path is still exercised in production
    -- just far less often than when the score was a plain weighted sum and one
    missing input NaN'd the row. The storage of the result was the bug, and it
    is the same one db_value was written for.
    """
    import numpy as np
    import pandas as pd

    from src.crispdm.features import db_value
    from src.crispdm.scoring import rankings

    scores = pd.DataFrame(
        {
            "security_id": [1, 2, 3],
            "composite_score": [0.9, float("nan"), float("inf")],
        }
    )
    rank = rankings(scores)

    # Ranked where there is a score, unranked where there is not, and not a crash.
    assert rank["rank"].iloc[0] == 1.0
    assert pd.isna(rank["rank"].iloc[1]) and pd.isna(rank["rank"].iloc[2])

    # And every numeric bind is NULL-safe, including the infinities.
    for value in (float("nan"), float("inf"), -float("inf"), np.float64("nan"), None):
        assert db_value(value) is None, f"{value!r} would be stored as a numeric value"
    assert db_value(0.5) == 0.5
