from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.crispdm import features


def test_db_value_maps_missing_numbers_to_null():
    assert features.db_value(np.nan) is None
    assert features.db_value(float("nan")) is None
    assert features.db_value(np.inf) is None
    assert features.db_value(-np.inf) is None
    assert features.db_value(pd.NaT) is None
    assert features.db_value(None) is None


def test_db_value_keeps_real_values():
    assert features.db_value(0.1553) == pytest.approx(0.1553)
    assert features.db_value(np.float64(2.5)) == 2.5
    assert features.db_value(np.int64(3)) == 3
    assert isinstance(features.db_value(np.int64(3)), int)


def test_feature_payload_nulls_the_integer_label_column():
    frame = pd.DataFrame(
        [
            {
                "security_id": "sid-1",
                "as_of_date": pd.Timestamp("2026-09-25").date(),
                "current_price": 531.0,
                "annual_dividend": 82.5,
                "dividend_yield": 0.155,
                "momentum_252d": np.nan,
                "target_sustainable_dividend": np.nan,
            }
        ]
    )

    payload = features.feature_payload(frame)

    assert len(payload) == 1
    assert payload[0]["target_sustainable_dividend"] is None
    assert payload[0]["momentum_252d"] is None
    assert payload[0]["current_price"] == 531.0
    # columns absent from the frame still bind, as NULL
    assert payload[0]["dividend_growth"] is None
    assert payload[0]["yield_exclusion_reason"] is None


class _FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, payload=None):
        self.calls.append(payload)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeEngine:
    def __init__(self):
        self.conn = _FakeConnection()

    def begin(self):
        return self.conn


def test_persist_features_batches_rows(monkeypatch):
    frame = pd.DataFrame(
        [
            {
                "security_id": f"sid-{i}",
                "as_of_date": pd.Timestamp("2026-09-25").date(),
                "current_price": float(i),
                "target_sustainable_dividend": np.nan,
            }
            for i in range(5)
        ]
    )
    engine = _FakeEngine()
    monkeypatch.setattr(features, "engine", engine)

    features.persist_features(frame, chunk_size=2)

    assert [len(call) for call in engine.conn.calls] == [2, 2, 1]
    assert all(
        row["target_sustainable_dividend"] is None for call in engine.conn.calls for row in call
    )


def test_persist_features_skips_empty_frames(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(features, "engine", engine)

    features.persist_features(pd.DataFrame())

    assert engine.conn.calls == []


def _yields(rows):
    return pd.DataFrame(
        [
            {
                "security_id": f"sid-{i}",
                "current_price": px,
                "annual_dividend": div,
                "dividend_yield": y,
            }
            for i, (px, div, y) in enumerate(rows)
        ]
    )


def test_null_implausible_yields_keeps_the_row_and_the_other_features():
    frame = _yields([(0.0005, 30.0, 59999.997)])
    frame["volatility_252d"] = 0.42

    out = features.null_implausible_yields(frame)

    assert len(out) == 1, "the row must survive so price/volatility stay usable"
    assert pd.isna(out.loc[0, "dividend_yield"])
    assert pd.isna(out.loc[0, "annual_dividend"]), "the unit error is in the amount"
    assert out.loc[0, "volatility_252d"] == 0.42
    assert out.loc[0, "current_price"] == 0.0005


def test_null_implausible_yields_nulls_the_reverse_split_tail():
    # WHLR: a $1.44 dividend against a $250bn unadjusted pre-split price.
    frame = _yields([(250430750720.0, 1.44, 5.75e-12)])

    out = features.null_implausible_yields(frame)

    assert pd.isna(out.loc[0, "dividend_yield"])
    assert pd.isna(out.loc[0, "annual_dividend"])


def test_null_implausible_yields_keeps_real_payers():
    # 25% is exactly where the $1.00 SPACs sit and must survive: the cap is
    # inclusive, and AQN/BRBS/COHN legitimately trade there.
    frame = _yields(
        [
            (1.0, 0.25, 0.25),
            (7.63, 0.065, 0.0085),
            (32.39, 0.25, 0.0077),
            (2.0, 0.00001, 5e-06),
        ]
    )

    out = features.null_implausible_yields(frame)

    assert out["dividend_yield"].notna().all()
    assert out["annual_dividend"].notna().all()


def test_null_implausible_yields_leaves_a_missing_yield_alone():
    frame = _yields([(5.71, np.nan, np.nan)])

    out = features.null_implausible_yields(frame)

    assert pd.isna(out.loc[0, "dividend_yield"]), "absent is missing, not impossible"
    assert pd.isna(out.loc[0, "annual_dividend"])


def test_null_implausible_yields_does_not_mutate_its_input():
    frame = _yields([(0.0005, 30.0, 59999.997)])

    features.null_implausible_yields(frame)

    assert frame.loc[0, "dividend_yield"] == 59999.997


def test_null_implausible_yields_tolerates_frames_without_the_column():
    empty = features.null_implausible_yields(pd.DataFrame())
    assert empty.empty

    # A frame that has rows but no dividend_yield must pass through untouched
    # rather than raise on the missing key.
    without = pd.DataFrame({"security_id": ["sid-1"], "volatility_252d": [0.2]})
    assert features.null_implausible_yields(without).equals(without)


def _priced(rows):
    # NB: the in-memory column is the SQL alias ``annual_dividend``; the
    # database column it binds to is ``annualized_dividend``.
    return pd.DataFrame(
        [
            {
                "security_id": f"sid-{i}",
                "current_price": px,
                "annual_dividend": div,
                "dividend_yield": y,
                "price_median": med,
            }
            for i, (px, div, y, med) in enumerate(rows)
        ]
    )


def test_price_quality_flags_a_reverse_split_artifact():
    # BINI: a $1.02tn unadjusted pre-split row against a $1.50 own median.
    out = features.classify_price_quality(_priced([(1020000010240.0, 0.02, 2e-14, 1.5)]))

    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_SPLIT_ARTIFACT
    assert out.loc[0, "price_quality_rule"] == features.RULE_SPLIT_ARTIFACT


def test_price_quality_keeps_a_genuinely_expensive_share():
    # BRK-A really does trade near $809,000. A global dollar ceiling would
    # wrongly exclude it; the own-median test must not.
    out = features.classify_price_quality(_priced([(809350.0, None, None, 712000.0)]))

    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_OK


def test_price_quality_flags_the_sub_penny_shell():
    # GNOLF: a real $0.00004 close where one tick is 1000% of the price.
    out = features.classify_price_quality(_priced([(0.00004, 30.0, 750000.0, 0.00004)]))

    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_SUB_PENNY
    assert out.loc[0, "price_quality_rule"] == features.RULE_SUB_PENNY


def test_price_quality_keeps_a_sub_floor_price_that_is_its_own_median():
    # The floor is on the absolute price, not on consistency: a shell quoted
    # at $0.014 against its own $0.014 median is perfectly self-consistent and
    # still an unusable denominator.
    out = features.classify_price_quality(_priced([(0.014, 0.05, 3.57, 0.014)]))

    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_SUB_PENNY


def test_price_quality_keeps_a_price_just_above_the_floor():
    # $0.10 exactly: one tick is 0.1% of the price, so it is still usable.
    out = features.classify_price_quality(_priced([(0.10, 0.003, 0.03, 0.10)]))

    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_OK


def test_capture_raw_observations_preserves_the_unfiltered_inputs():
    frame = _priced([(1020000010240.0, 0.02, 2e-14, 1.5)])

    out = features.capture_raw_observations(frame)

    assert out.loc[0, "raw_current_price"] == 1020000010240.0
    assert out.loc[0, "raw_dividend_yield"] == 2e-14, "the pre-filter ratio must survive"
    assert out.loc[0, "raw_annual_dividend"] == 0.02
    assert out.loc[0, "dividend_yield"] == 2e-14, "capture must not modify anything"


def test_raw_audit_survives_a_filter_that_runs_after_capture():
    # The ordering in build_features is the point: capture first, then void the
    # ratio. A reversed order silently destroys the only record of the value
    # that was rejected, so this asserts the two steps compose.
    frame = _priced([(0.00004, 30.0, 750000.0, 0.00004)])

    out = features.apply_price_quality(
        features.null_implausible_yields(features.capture_raw_observations(frame))
    )

    assert pd.isna(out.loc[0, "dividend_yield"]), "an unusable denominator voids the ratio"
    assert pd.isna(out.loc[0, "annual_dividend"])
    assert out.loc[0, "raw_dividend_yield"] == 750000.0, "the audit trail must remain"
    assert out.loc[0, "raw_annual_dividend"] == 30.0
    assert out.loc[0, "raw_current_price"] == 0.00004


def test_yield_bounds_record_their_own_reason_not_a_price_verdict():
    # CDZI's $560/share is a numerator unit error on a good price. Attributing
    # it to the price would mislabel a dividend defect as a data-quality one.
    frame = _priced([(18.20, 560.0, 30769.0, 18.20)])

    out = features.null_implausible_yields(features.capture_raw_observations(frame))

    assert out.loc[0, "yield_exclusion_reason"] == features.RULE_YIELD_ABOVE_MAX
    assert pd.isna(out.loc[0, "dividend_yield"])
    assert out.loc[0, "raw_dividend_yield"] == 30769.0

    # The price is fine, so price quality must remain ok once it is judged.
    judged = features.apply_price_quality(out)
    assert judged.loc[0, "price_quality"] == features.PRICE_QUALITY_OK
    assert pd.isna(judged.loc[0, "price_quality_rule"])


def test_a_cheap_denominator_is_excluded_by_price_not_by_the_yield_bound():
    # GTCH's shape: a real penny-scale dividend on a $0.014 shell gives a yield
    # of 0.7%, comfortably inside the band. Only the price is unusable, so the
    # exclusion must be attributed to the price and nothing else. The two
    # reasons are independent columns precisely so this is not confused with a
    # dividend that genuinely collapsed.
    frame = _priced([(0.014, 0.0001, 0.00714, 0.014)])

    out = features.apply_price_quality(
        features.null_implausible_yields(features.capture_raw_observations(frame))
    )

    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_SUB_PENNY
    assert out.loc[0, "price_quality_rule"] == features.RULE_SUB_PENNY
    assert pd.isna(out.loc[0, "yield_exclusion_reason"]), "the yield itself was in range"
    assert pd.isna(out.loc[0, "dividend_yield"]), "but the ratio is still voided"


def test_apply_price_quality_voids_the_ratio_but_keeps_the_evidence():
    out = features.apply_price_quality(
        features.capture_raw_observations(_priced([(0.00004, 30.0, 750000.0, 0.00004)]))
    )

    assert pd.isna(out.loc[0, "dividend_yield"]), "an unusable denominator voids the ratio"
    assert pd.isna(out.loc[0, "annual_dividend"])
    assert out.loc[0, "raw_dividend_yield"] == 750000.0, "the audit trail must remain"
    assert out.loc[0, "raw_current_price"] == 0.00004


def test_price_quality_leaves_a_missing_price_alone():
    # No usable denominator is missing data, not a bad one: a NULL price cannot
    # produce a ratio, so flagging it would mislabel absent data as a defect.
    out = features.classify_price_quality(_priced([(None, None, None, 1.5)]))

    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_OK


def test_price_quality_leaves_a_missing_median_alone():
    # Too little history to judge is not evidence of a split.
    out = features.classify_price_quality(_priced([(500000.0, None, None, None)]))

    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_OK


def test_price_quality_prefers_sub_penny_when_both_rules_fire():
    out = features.classify_price_quality(_priced([(0.00004, 1.0, 25000.0, 90000.0)]))

    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_SUB_PENNY


def test_apply_price_quality_leaves_usable_rows_intact():
    out = features.apply_price_quality(
        features.capture_raw_observations(_priced([(1.0, 0.25, 0.25, 1.0)]))
    )

    assert out.loc[0, "dividend_yield"] == 0.25
    assert out.loc[0, "price_quality"] == features.PRICE_QUALITY_OK


def _feature_sql(monkeypatch):
    """Capture the SQL build_features would run, without touching a database."""
    captured = {}

    def fake_read_df(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        # build_features() derives eps_ttm_growth from a prior-year earnings
        # column, so the stand-in frame has to carry it. It was missing here and
        # the four SQL-capture tests below failed with a KeyError raised from
        # build_features rather than from the query they were written to check.
        return pd.DataFrame(
            columns=list(features.FEATURE_COLUMNS) + ["eps_ttm", "eps_ttm_prior", "fcf_ttm"]
        )

    monkeypatch.setattr(features, "read_df", fake_read_df)
    features.build_features()
    return captured["sql"]


def test_momentum_is_total_return_not_price_return(monkeypatch):
    """momentum_63d / momentum_252d are meant to be total return.

    close / LAG(close, n) - 1 ignores every dividend, which for a dividend
    screener undercounts exactly the securities it ranks. The window is a sum of
    daily log returns that credit the dividend on its ex-date, and it must still
    require a full window, as volatility_252d does.
    """
    sql = _feature_sql(monkeypatch)

    assert "p.close/p.p252-1" not in sql and "p.close/p.p63-1" not in sql
    assert "p.tr_samples_252 >= 252 THEN EXP(p.tr_sum_252) - 1" in sql
    assert "p.tr_samples_63 >= 63 THEN EXP(p.tr_sum_63) - 1" in sql
    assert "daily_total_return" in sql


def test_the_payment_sanity_bound_is_passed_to_the_query(monkeypatch):
    captured = {}

    def fake_read_df(sql, params=None):
        captured["params"] = params
        return pd.DataFrame(
            columns=list(features.FEATURE_COLUMNS) + ["eps_ttm", "eps_ttm_prior", "fcf_ttm"]
        )

    monkeypatch.setattr(features, "read_df", fake_read_df)
    features.build_features()

    assert captured["params"]["max_payment_ratio"] == features.MAX_SINGLE_PAYMENT_RATIO


def test_volatility_252d_requires_a_full_window_of_returns(monkeypatch):
    # STDDEV_SAMP returns a value from two samples, so an unguarded
    # ROWS BETWEEN 251 PRECEDING AND CURRENT ROW published a "252-day"
    # volatility after three price observations.
    sql = _feature_sql(monkeypatch)

    assert "vol_samples" in sql
    assert "COUNT(daily_return) OVER" in sql
    assert "p.vol_samples >= 252" in sql
    unguarded = "p.daily_vol*sqrt(252) volatility_252d"
    assert unguarded not in sql, "volatility must be gated on the sample count"


def test_quick_liquidity_is_cash_over_current_liabilities(monkeypatch):
    """The CVS liquidity leg, and the denominator it needed V0016 to obtain.

    Dividing by `liabilities` would have mixed two accounting bases -- total
    obligations against the portion due within a year -- and produced a ratio
    that reads as comfortable coverage for a company carrying long-dated debt.
    """
    sql = _feature_sql(monkeypatch)

    assert "fy.cash_fy / fy.current_liabilities_fy" in sql
    assert "fy.cash_fy / fy.debt_fy" not in sql


def test_quick_liquidity_refuses_a_nonpositive_denominator(monkeypatch):
    """A zero or negative current-liabilities figure divides into infinity.

    Either a missing tag landing as 0 or a subtotal that does not reconcile. A
    guard that only tested for NULL would publish +inf for the first case, and
    inf is a truthy float that would sail through a coverage check.
    """
    sql = _feature_sql(monkeypatch)

    assert "fy.current_liabilities_fy > 0" in sql


def test_quick_liquidity_reads_both_legs_from_the_same_fy_vintage(monkeypatch):
    """Cash and the denominator must come from the same balance sheet.

    Taking cash from one period and current liabilities from another would mix
    a numerator and denominator across filings and quietly invent a ratio no
    balance sheet states. The fy path is the point-in-time-joined one; a
    quarterly or undated leg would break the vintage discipline the rest of the
    feature SQL is built on.
    """
    sql = _feature_sql(monkeypatch)

    fy_cte = sql.split("fy_vintages AS (")[1].split("    fy AS (")[0]
    assert "pf.cash" in fy_cte
    assert "pf.current_liabilities" in fy_cte
    # Both legs ride the one FY join, not a separate lookup that could resolve
    # to a different filing.
    assert fy_cte.count("FROM fundamentals.periodic_financials pf") == 1


def test_refinancing_wall_interpolates_the_eighteen_month_window(monkeypatch):
    """C4 asks about 18 months; XBRL publishes year one and months 13-24.

    The half-year coefficient is the only estimate in the column, and it is a
    deliberate one. Truncating to year one instead would understate the cliff
    for every company repaying on a schedule rather than a bullet, which is the
    commoner shape and the more dangerous one to miss.
    """
    sql = _feature_sql(monkeypatch)

    assert "fy.debt_maturing_12m_fy + 0.5 * fy.debt_maturing_year_2_fy" in sql
    # Section 5.5's reserves are Cash *plus* committed undrawn facilities.
    assert "fy.cash_fy + COALESCE(fy.committed_undrawn_fy, 0)" in sql
    assert "/ fy.cash_fy" not in sql, "cash alone overstates the cliff"


def test_an_undisclosed_facility_is_omitted_not_assumed_to_be_zero(monkeypatch):
    """Absence of a tag is not an absence of capacity.

    Coalescing the facility to zero on every row is arithmetically identical to
    the cash-only measure V0018 shipped, and it would hide the difference
    between a filer that disclosed a full revolver and one that disclosed
    nothing. COALESCE appears only inside the addition, so an untagged filer
    keeps the cash-only reading while a tagged one gets its capacity counted.
    """
    sql = _feature_sql(monkeypatch)
    assert "COALESCE(fy.committed_undrawn_fy, 0)" in sql
    assert "COALESCE(fy.committed_undrawn_fy, 0) > 0" not in sql


def test_refinancing_wall_requires_both_years(monkeypatch):
    """A year-one-only filer gets NULL, not a cliff of 0.0.

    2,748 companies disclose year one and stop. Coalescing the missing year two
    to zero would hand every one of them a perfect score on a 25%-weight metric
    -- the best possible reading of a maturity schedule that was never reported.
    """
    sql = _feature_sql(monkeypatch)

    assert "fy.debt_maturing_12m_fy IS NOT NULL" in sql
    assert "fy.debt_maturing_year_2_fy IS NOT NULL" in sql
    assert "COALESCE(fy.debt_maturing_year_2_fy, 0)" not in sql


def test_refinancing_wall_excludes_undrawn_facilities_from_the_denominator(monkeypatch):
    """Section 6.2 says cash + undrawn facilities. This deliberately is not that.

    Only 888 of 7,079 filers report a remaining borrowing capacity, and an
    undrawn revolver is a commitment rather than a reserve -- it can be
    cancelled or covenant-triggered. Adding it would understate the cliff for
    exactly the companies most likely to draw on it. Cash-only makes the ratio
    an upper bound on distress, never a lower one, which is the direction
    section 4.1's house standard requires.
    """
    sql = _feature_sql(monkeypatch)

    assert "LineOfCredit" not in sql
    assert "RemainingBorrowingCapacity" not in sql


def test_dividend_growth_annual_fallback_divides_latest_by_prior(monkeypatch):
    # ann.current is the newest ex-dividend year (rn=1) and ann.prior the one
    # before it (rn=2), so growth is current/prior - 1. The inverted form
    # turned every dividend rise into a fall and vice versa.
    sql = _feature_sql(monkeypatch)

    assert "ann.current / ann.prior - 1" in sql
    assert "ann.prior / ann.current - 1" not in sql
    assert "ann.current > 0 AND ann.prior > 0" in sql, "both sides need a positive base"


def test_dividend_growth_never_keys_on_the_cadence_column(monkeypatch):
    """raw.dividend_data.frequency is an informational cadence label.

    Every row once read 'Annual' regardless of the true payment interval, so a
    filter on it silently picked the two most recent SEC facts regardless of
    cadence. Now that the column is truthful, the build must not key on it at
    all -- the growth branches select on provider, concept and date only.
    """
    sql = _feature_sql(monkeypatch)

    annual = sql.split("d_annual AS (")[1].split("),\n    ann AS (")[0]
    annual = annual.split("SELECT p.security_id", 1)[1]
    assert "frequency" not in annual
    assert "d.frequency" not in sql


def _leverage_frame(**rows):
    base = {"oi_ttm": 100.0, "da_ttm": 20.0, "int_ttm": 10.0, "debt": 240.0}
    base.update(rows)
    return pd.DataFrame([base])


def test_dividend_growth_needs_an_observed_prior_year_window(monkeypatch):
    """A stub first payment against a full year is not growth.

    PHXE-P's first payment was 0.11111 and its next 0.625, which the prior-window
    comparison read as +2,150%. The per-payment series is only trusted for a prior
    year that starts at or after the security's first stored payment; the XBRL
    annual path, which spans its own history, is unaffected and still applies.
    """
    sql = _feature_sql(monkeypatch)

    assert "LEFT JOIN d_first ON d_first.security_id=p.security_id" in sql
    growth = sql.split("END dividend_growth")[0].split("CASE WHEN d_prior_paid")[1]
    openbb_branch, annual_branch = growth.split("WHEN ann.current")
    assert "d_first.first_ex <= p.observation_date - INTERVAL '730 days'" in openbb_branch
    assert "d_first" not in annual_branch, "the guard belongs to the per-payment branch only"


def test_a_negative_debt_balance_is_not_read_as_unlevered():
    """214 stored fundamentals rows carry debt below zero (V0050).

    A negative balance divided by positive EBITDA is a negative ratio, which the
    percentile rank files as the *least* levered company in the universe.
    """
    out = features.leverage_ratios(_leverage_frame(debt=-240.0))
    assert pd.isna(out.debt.iloc[0])
    assert pd.isna(out.debt_to_ebitda.iloc[0])

    # Zero is a real answer, a filer with no debt, and must survive.
    debt_free = features.leverage_ratios(_leverage_frame(debt=0.0))
    assert debt_free.debt.iloc[0] == 0.0
    assert debt_free.debt_to_ebitda.iloc[0] == 0.0


def test_the_debt_guard_does_not_touch_interest_coverage():
    out = features.leverage_ratios(_leverage_frame(debt=-240.0))
    assert out.interest_coverage.iloc[0] == pytest.approx(10.0)


def test_debt_to_ebitda_is_debt_over_operating_income_plus_da():
    """EBITDA is derived, not reported: EBIT + D&A, and nothing else.

    Using operating income alone would be EBIT, a different ratio under the same
    name, which is the substitution the original retirement note refused to make.
    """
    out = features.leverage_ratios(_leverage_frame())
    assert out.debt_to_ebitda.iloc[0] == pytest.approx(240 / 120)


def test_interest_coverage_is_ebit_over_interest():
    out = features.leverage_ratios(_leverage_frame())
    assert out.interest_coverage.iloc[0] == pytest.approx(10.0)


def test_leverage_ratios_are_null_rather_than_collapsed_at_the_extremes():
    """Three ways to get a denominator that is not a number.

    Each has a real adverse reading behind it, and each would be actively
    misleading as a finite figure: negative EBITDA filed as huge leverage, and
    undisclosed interest filed as infinite coverage, which is the most
    favourable value the column can hold and would be awarded for missing data.
    """
    negative = features.leverage_ratios(_leverage_frame(oi_ttm=-50.0, da_ttm=20.0, int_ttm=10.0))
    assert pd.isna(negative.debt_to_ebitda.iloc[0])
    # Interest coverage is the asymmetric case: negative EBIT does not make the
    # quotient undefined, it makes it negative, and -5x is a definite answer to
    # "does operating income service interest" -- no, and by how much. Keeping it
    # stops the most distressed issuers from being exactly the ones with no data.
    assert negative.interest_coverage.iloc[0] == pytest.approx(-5.0)

    undisclosed = features.leverage_ratios(_leverage_frame(int_ttm=np.nan))
    assert pd.isna(undisclosed.interest_coverage.iloc[0])
    assert undisclosed.debt_to_ebitda.iloc[0] == pytest.approx(2.0)

    # EBITDA exactly zero: not a ratio, and not a division by zero either.
    zero = features.leverage_ratios(_leverage_frame(oi_ttm=-20.0, da_ttm=20.0))
    assert pd.isna(zero.debt_to_ebitda.iloc[0])

    no_debt = features.leverage_ratios(_leverage_frame(debt=np.nan))
    assert pd.isna(no_debt.debt_to_ebitda.iloc[0])

    # Net interest *income* rather than expense: there is no coverage ratio, and
    # a negative denominator must not be allowed to flip the sign into a
    # favourable-looking number.
    interest_income = features.leverage_ratios(_leverage_frame(int_ttm=-10.0))
    assert pd.isna(interest_income.interest_coverage.iloc[0])


def test_interest_coverage_rejects_a_denominator_immaterial_against_revenue():
    """A netted residual is not an interest expense.

    Investment companies report interest netted against interest income, so the
    line lands as a small number rather than a real cost. EBIT over that residual
    is arithmetic, not economics: the latest date carried 11.4% of coverage
    ratios whose denominator was under $100k, with a maximum of 40,225x.
    """
    # 10 of interest against revenue of 1,000 is 1% of revenue: material, and the
    # ratio stands at the plain 100/10.
    material = features.leverage_ratios(_leverage_frame(rev_ttm=1_000.0))
    assert material.interest_coverage.iloc[0] == pytest.approx(10.0)

    # 10 of interest against revenue of 100,000 is 0.01%: a residual. The same
    # EBIT, the same reported interest, but now there is no cost to service.
    immaterial = features.leverage_ratios(_leverage_frame(rev_ttm=100_000.0))
    assert pd.isna(immaterial.interest_coverage.iloc[0])

    # Exactly at the floor is kept: the test rejects below, not at.
    at_floor = features.leverage_ratios(_leverage_frame(int_ttm=5.0, rev_ttm=1_000.0))
    assert at_floor.interest_coverage.iloc[0] == pytest.approx(20.0)


def test_interest_coverage_floor_does_not_touch_the_other_ratio():
    """The floor is a test on interest, so it must not disturb leverage.

    Dropping interest coverage for an immaterial residual leaves the company
    exactly as levered as it was; ``debt_to_ebitda`` shares the input frame and
    would be easy to gate on the same condition by accident.
    """
    out = features.leverage_ratios(_leverage_frame(rev_ttm=100_000.0))
    assert out.debt_to_ebitda.iloc[0] == pytest.approx(2.0)


def test_interest_coverage_floor_keeps_negative_results_and_unknown_revenue():
    """Two things the floor must not do.

    It must not drop negative coverage: negative EBIT servicing a material
    interest line is a definite adverse answer, not a missing measurement, and
    the material-interest case is exactly where those companies sit. And a
    filer that reports no revenue has no scale to be immaterial *relative to*, so
    gating it would discard a usable ratio for the absence of a denominator that
    is only being used as a threshold.
    """
    negative = features.leverage_ratios(
        _leverage_frame(oi_ttm=-50.0, int_ttm=10.0, rev_ttm=1_000.0)
    )
    assert negative.interest_coverage.iloc[0] == pytest.approx(-5.0)

    no_revenue = features.leverage_ratios(_leverage_frame(rev_ttm=np.nan))
    assert no_revenue.interest_coverage.iloc[0] == pytest.approx(10.0)


def test_leverage_ratios_do_not_mutate_their_input():
    df = _leverage_frame()
    before = df.copy()
    features.leverage_ratios(df)
    pd.testing.assert_frame_equal(df, before)


def test_restored_features_are_declared_and_persisted():
    """The two columns must be both computed and written.

    They were declared on model.features since V0003 and selected by the app,
    but INSERT_FEATURE omitted them, so they were NULL for every equity
    regardless of the data. A computed-but-unwritten column reproduces the
    original empty-column bug in a new place.
    """
    sql = str(features.INSERT_FEATURE)
    for column in ("debt_to_ebitda", "interest_coverage"):
        assert column in features.FEATURE_COLUMNS
        assert f":{column}" in sql
        assert f"{column}=EXCLUDED.{column}" in sql


def test_feature_payload_keys_match_the_insert_bind_names():
    """FEATURE_COLUMNS and INSERT_FEATURE must describe the same 21 columns.

    SQLAlchemy binds executemany by parameter *name*, so a name present in one
    and not the other is not a schema error and not caught by any count: the
    build query and the table stayed the same size while the statement died at
    execution with "a value is required for bind parameter". The one divergence
    that existed was annual_dividend (frame) vs annualized_dividend (column),
    which is bridged by FEATURE_COLUMN_ALIASES.
    """
    import re

    from src.crispdm.features import (
        FEATURE_COLUMN_ALIASES,
        FEATURE_COLUMNS,
        INSERT_FEATURE,
        feature_payload,
    )

    stmt = INSERT_FEATURE.text
    insert_cols = [
        c.strip()
        for c in re.search(
            r"INSERT INTO model\.features(?:\s+AS\s+\w+)?\s*\(([^)]*?)\)\s*VALUES", stmt, re.S
        )
        .group(1)
        .replace("\n", " ")
        .split(",")
        if c.strip()
    ]
    binds = re.findall(r":(\w+)", stmt)
    assert sorted(binds) == sorted(insert_cols), "VALUES list and column list disagree"

    # The frame names, once aliased, must be exactly the stored columns.
    written = [FEATURE_COLUMN_ALIASES.get(c, c) for c in FEATURE_COLUMNS]
    assert sorted(written) == sorted(insert_cols)
    assert len(FEATURE_COLUMNS) == len(insert_cols)

    # And the payload actually produced must bind, not merely line up on paper.
    frame = pd.DataFrame([{c: 1.0 for c in FEATURE_COLUMNS}])
    payload = feature_payload(frame)
    assert len(payload) == 1
    assert sorted(payload[0]) == sorted(insert_cols)
    assert all(v is not None for v in payload[0].values())


def test_every_feature_column_exists_in_the_warehouse():
    """The test above checks Python against Python. This checks it against the table.

    Three tests in this file line FEATURE_COLUMNS up against INSERT_FEATURE, and
    all three pass when a column exists in the Python and not in the database.
    That is exactly how `quick_liquidity` reached a complete-looking
    implementation: it was in FEATURE_COLUMNS, in INSERT_FEATURE, in
    sql/schema.sql, and had tests asserting its derivation -- and the column did
    not exist in model.features, so the 07:00 nightly died at stage 7 on
    "column quick_liquidity does not exist".

    sql/schema.sql is not a substitute for a migration. V0001 is a baseline
    marker rather than replayed DDL: migrate.py records the state that
    schema.sql + init_db.py produced and never re-runs it, so schema.sql only
    reaches a brand-new database. An established warehouse takes its columns
    from migrations alone. A fresh developer database would have had the column
    and this defect would have been invisible to them.

    So this asks information_schema, which is the only thing that knows.
    """
    engine = None
    try:
        from src.crispdm.db import engine as db_engine

        with db_engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        engine = db_engine
    except Exception:  # pragma: no cover - environments without a database
        pytest.skip("no database available")

    from src.crispdm.features import FEATURE_COLUMN_ALIASES, FEATURE_COLUMNS

    with engine.connect() as conn:
        present = {
            r[0]
            for r in conn.exec_driver_sql(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'model' AND table_name = 'features'
                """
            ).fetchall()
        }

    stored = [FEATURE_COLUMN_ALIASES.get(c, c) for c in FEATURE_COLUMNS]
    missing = [c for c in stored if c not in present]
    assert not missing, (
        f"model.features is missing {missing}. Add them to a migration "
        f"(sql/migrations/), not to sql/schema.sql -- the baseline marker means "
        f"schema.sql only reaches brand-new databases."
    )


def test_earnings_trajectory_is_computed():
    """eps_ttm_growth should be present in the feature frame."""
    from src.crispdm.features import build_features

    df = build_features(date_from=date(2024, 1, 1), date_to=date(2024, 1, 2))
    assert "eps_ttm_growth" in df.columns


def test_earnings_trajectory_is_persisted():
    """eps_ttm_growth should be written to model.features."""
    sql = str(features.INSERT_FEATURE)
    assert "eps_ttm_growth" in sql
    assert "eps_ttm_growth=EXCLUDED.eps_ttm_growth" in sql


def test_earnings_trajectory_handles_negative_prior():
    """A negative prior TTM base should not produce a misleading ratio.

    `5.0 / -3.0 - 1` is `-2.67`, which reads as deep deterioration. The company
    actually turned profitable; the sign flip is the hazard, so the cell stays
    NULL rather than claiming a direction.
    """
    df = pd.DataFrame([{"eps_ttm": 5.0, "eps_ttm_prior": -3.0}])
    out = features.earnings_growth(df)
    assert pd.isna(out["eps_ttm_growth"].iloc[0])


def test_earnings_trajectory_handles_zero_prior():
    """A zero base is not a division, and not an infinite growth rate either."""
    df = pd.DataFrame([{"eps_ttm": 5.0, "eps_ttm_prior": 0.0}])
    out = features.earnings_growth(df)
    assert pd.isna(out["eps_ttm_growth"].iloc[0])


def test_earnings_trajectory_treats_a_missing_column_as_absent():
    df = pd.DataFrame([{"eps_ttm": 5.0}])
    out = features.earnings_growth(df)
    assert pd.isna(out["eps_ttm_growth"].iloc[0])


def test_earnings_trajectory_computes_correctly():
    """Positive growth: current TTM > prior TTM."""
    df = pd.DataFrame([{"eps_ttm": 6.0, "eps_ttm_prior": 4.0}])
    out = features.earnings_growth(df)
    assert out["eps_ttm_growth"].iloc[0] == pytest.approx(0.5)


def test_earnings_trajectory_reports_a_deterioration_as_negative():
    """The other direction, so the guard is not just refusing to compute."""
    df = pd.DataFrame([{"eps_ttm": 4.0, "eps_ttm_prior": 5.0}])
    out = features.earnings_growth(df)
    assert out["eps_ttm_growth"].iloc[0] == pytest.approx(-0.2)


def _financial_frame(**overrides):
    base = {
        "current_price": 100.0,
        "eps_ttm": 5.0,
        "rev_ttm": 1_000.0,
        "oi_ttm": 150.0,
        "ni_ttm": 100.0,
        "gross_profit_ttm": 400.0,
        "ocf_ttm": 120.0,
        "fcf_ttm": 80.0,
        "capex_ttm": 40.0,
        "fcf_ttm_prior": 64.0,
        "da_ttm": 50.0,
        "debt": 300.0,
        "cash": 100.0,
        "current_assets": 500.0,
        "current_liabilities": 250.0,
        "equity": 400.0,
        "shares_outstanding": 20.0,
    }
    base.update(overrides)
    return pd.DataFrame([base])


def test_financial_metrics_computes_the_margins_over_positive_revenue():
    out = features.financial_metrics(_financial_frame())
    assert out.gross_margin.iloc[0] == pytest.approx(400 / 1000)
    assert out.operating_margin.iloc[0] == pytest.approx(150 / 1000)
    assert out.net_margin.iloc[0] == pytest.approx(100 / 1000)
    assert out.fcf_margin.iloc[0] == pytest.approx(80 / 1000)
    assert out.ocf_margin.iloc[0] == pytest.approx(120 / 1000)


def test_financial_metrics_keeps_a_negative_net_margin():
    """A loss is a real adverse signal, not an undefined ratio.

    The denominator guard disqualifies a ratio; the numerator may legitimately
    be negative. Suppressing a loss would remove exactly the distress the
    screener is looking for.
    """
    out = features.financial_metrics(_financial_frame(ni_ttm=-100.0))
    assert out.net_margin.iloc[0] == pytest.approx(-0.1)


def test_margins_are_null_when_revenue_is_absent_or_nonpositive():
    absent = features.financial_metrics(_financial_frame(rev_ttm=np.nan))
    for column in ("gross_margin", "operating_margin", "net_margin", "fcf_margin", "ocf_margin"):
        assert pd.isna(absent[column].iloc[0]), f"{column} must not divide by a missing revenue"

    zero = features.financial_metrics(_financial_frame(rev_ttm=0.0))
    assert pd.isna(zero.gross_margin.iloc[0])

    negative = features.financial_metrics(_financial_frame(rev_ttm=-1_000.0))
    assert pd.isna(negative.operating_margin.iloc[0]), "a negative revenue flips every margin"


def test_cash_conversion_needs_positive_earnings():
    out = features.financial_metrics(_financial_frame())
    assert out.cash_conversion.iloc[0] == pytest.approx(120 / 100)

    loss = features.financial_metrics(_financial_frame(ni_ttm=-100.0))
    assert pd.isna(loss.cash_conversion.iloc[0]), "no conversion rate against a loss"


def test_capex_intensity_is_capex_over_revenue():
    out = features.financial_metrics(_financial_frame())
    assert out.capex_intensity.iloc[0] == pytest.approx(40 / 1000)


def test_fcf_growth_needs_a_positive_prior_base():
    out = features.financial_metrics(_financial_frame())
    assert out.fcf_growth.iloc[0] == pytest.approx(80 / 64 - 1)

    # 5 / -3 - 1 is -2.67: a recovery would read as a collapse.
    negative = features.financial_metrics(_financial_frame(fcf_ttm_prior=-64.0))
    assert pd.isna(negative.fcf_growth.iloc[0])

    zero = features.financial_metrics(_financial_frame(fcf_ttm_prior=0.0))
    assert pd.isna(zero.fcf_growth.iloc[0])


def test_net_debt_requires_both_legs():
    out = features.financial_metrics(_financial_frame())
    assert out.net_debt.iloc[0] == pytest.approx(200.0)

    # A missing cash balance treated as zero would inflate net debt to 300.
    no_cash = features.financial_metrics(_financial_frame(cash=np.nan))
    assert pd.isna(no_cash.net_debt.iloc[0])

    # A missing debt balance treated as zero would fabricate 100 of net cash.
    no_debt = features.financial_metrics(_financial_frame(debt=np.nan))
    assert pd.isna(no_debt.net_debt.iloc[0])

    # A reported zero debt is real and yields genuine net cash.
    debt_free = features.financial_metrics(_financial_frame(debt=0.0))
    assert debt_free.net_debt.iloc[0] == pytest.approx(-100.0)


def test_net_debt_to_ebitda_uses_operating_income_plus_da():
    out = features.financial_metrics(_financial_frame())
    # EBITDA = 150 + 50 = 200, net debt = 300 - 100 = 200.
    assert out.net_debt_to_ebitda.iloc[0] == pytest.approx(1.0)

    negative_ebitda = features.financial_metrics(_financial_frame(oi_ttm=-100.0))
    assert pd.isna(negative_ebitda.net_debt_to_ebitda.iloc[0])


def test_current_ratio_needs_positive_current_liabilities():
    out = features.financial_metrics(_financial_frame())
    assert out.current_ratio.iloc[0] == pytest.approx(2.0)

    zero = features.financial_metrics(_financial_frame(current_liabilities=0.0))
    assert pd.isna(zero.current_ratio.iloc[0])


def test_debt_to_equity_needs_positive_equity():
    out = features.financial_metrics(_financial_frame())
    assert out.debt_to_equity.iloc[0] == pytest.approx(300 / 400)

    negative = features.financial_metrics(_financial_frame(equity=-400.0))
    assert pd.isna(negative.debt_to_equity.iloc[0])


def test_pe_and_earnings_yield_are_reciprocals_and_need_positive_eps():
    out = features.financial_metrics(_financial_frame())
    assert out.pe_ratio.iloc[0] == pytest.approx(20.0)
    assert out.earnings_yield.iloc[0] == pytest.approx(0.05)
    assert out.pe_ratio.iloc[0] * out.earnings_yield.iloc[0] == pytest.approx(1.0)

    # price / -2.00 is negative, and a screener sorting ascending would file the
    # deepest loss-maker as the cheapest company in the universe.
    loss = features.financial_metrics(_financial_frame(eps_ttm=-2.0))
    assert pd.isna(loss.pe_ratio.iloc[0])
    assert pd.isna(loss.earnings_yield.iloc[0])


def test_fcf_yield_and_price_to_book_use_market_cap():
    out = features.financial_metrics(_financial_frame())
    # market cap = 100 * 20 = 2,000
    assert out.fcf_yield.iloc[0] == pytest.approx(80 / 2_000)
    assert out.price_to_book.iloc[0] == pytest.approx(2_000 / 400)

    no_shares = features.financial_metrics(_financial_frame(shares_outstanding=0.0))
    assert pd.isna(no_shares.fcf_yield.iloc[0])
    assert pd.isna(no_shares.price_to_book.iloc[0])

    negative_equity = features.financial_metrics(_financial_frame(equity=-400.0))
    assert pd.isna(negative_equity.price_to_book.iloc[0])


def test_financial_metrics_treats_a_missing_column_as_absent():
    """A ratio over a column that does not exist is not computable, not an error.

    The same contract leverage_ratios documents: "no such input" and "the input
    is NULL" mean the same thing.
    """
    out = features.financial_metrics(pd.DataFrame([{"current_price": 100.0, "eps_ttm": 5.0}]))
    assert out.pe_ratio.iloc[0] == pytest.approx(20.0)
    assert pd.isna(out.gross_margin.iloc[0])


def test_financial_metrics_do_not_mutate_their_input():
    df = _financial_frame()
    before = df.copy()
    features.financial_metrics(df)
    pd.testing.assert_frame_equal(df, before)


def test_new_financial_columns_are_declared_and_persisted():
    """Each V0068 column must be both computed and written.

    A column that exists in FEATURE_COLUMNS but not in INSERT_FEATURE is NULL
    for every equity regardless of the data -- the empty-column bug the
    quick_liquidity incident records.
    """
    sql = str(features.INSERT_FEATURE)
    for column in (
        "gross_margin",
        "operating_margin",
        "net_margin",
        "fcf_margin",
        "ocf_margin",
        "cash_conversion",
        "capex_intensity",
        "fcf_growth",
        "net_debt",
        "net_debt_to_ebitda",
        "current_ratio",
        "debt_to_equity",
        "pe_ratio",
        "earnings_yield",
        "fcf_yield",
        "price_to_book",
    ):
        assert column in features.FEATURE_COLUMNS
        assert f":{column}" in sql
        assert f"{column}=EXCLUDED.{column}" in sql


def test_insert_feature_skips_an_unchanged_row():
    """A no-op re-upsert must not rewrite the row.

    ``model.features`` is upserted on every window rebuild; without a guard the
    whole row is rewritten even when every feature value is identical, which is
    what left ~1.4M dead tuples on a 9.7M-row table. The ``WHERE`` clause makes
    the write a no-op when the stored row already equals the proposed one, so a
    re-run of the same window costs no heap or index churn.
    """
    sql = str(features.INSERT_FEATURE)
    assert "INSERT INTO model.features AS current_features" in sql
    assert sql.rstrip().endswith("WHERE current_features IS DISTINCT FROM EXCLUDED")


def test_new_financial_inputs_ride_the_vintage_chains(monkeypatch):
    """The new flows are summed quarters with an FY fallback, the balances are FY.

    A quarterly-only flow with no FY fallback would be NULL for every filer that
    reports annually, and a quarterly-summed balance would double-count a
    balance-sheet level across four filings.
    """
    sql = _feature_sql(monkeypatch)

    assert "COALESCE(q.ni_ttm, fy.ni_fy)" in sql
    assert "fy.gross_profit_fy" in sql
    assert "COALESCE(q.ocf_ttm, fy.ocf_fy)" in sql
    assert "COALESCE(q.capex_ttm, fy.capex_fy)" in sql
    assert "q.fcf_ttm_prior" in sql
    # Balances come only from the FY path.
    for column in ("fy.equity_fy equity", "fy.current_assets_fy current_assets"):
        assert column in sql
    assert "fy.shares_outstanding_fy shares_outstanding" in sql


def test_fcf_prior_ttm_is_four_quarters_before_the_current_four(monkeypatch):
    sql = _feature_sql(monkeypatch)
    assert "sum(value) FILTER (WHERE metric = 'fcf' AND rn > 4 AND rn <= 8) fcf_ttm_prior" in sql


def test_new_inputs_are_not_features_by_accident():
    """The intermediate inputs are selected but not declared model inputs.

    A raw TTM dollar amount in FEATURE_COLUMNS would train the model on scale
    (bigger companies look bigger) and inflate the declared feature count. Only
    the derived ratios are features.
    """
    for column in (
        "ni_ttm",
        "gp_ttm",
        "gross_profit_ttm",
        "ocf_ttm",
        "capex_ttm",
        "fcf_ttm_prior",
        "equity",
        "current_assets",
        "shares_outstanding",
    ):
        assert column not in features.FEATURE_COLUMNS


def test_no_look_ahead_the_new_metrics_never_read_the_provider_snapshot(monkeypatch):
    """Point-in-time discipline: the feature SQL must not touch clean.company_profile.

    That table is a single current snapshot (source_retrieved_at fixed at the
    run date), so any join would put today's P/E into a historical row. The same
    reasoning retired data_quality_score. Every value is derived from the
    vintaged fundamentals.periodic_financials rows keyed by `filed`.
    """
    sql = _feature_sql(monkeypatch)
    assert "company_profile" not in sql
    assert "clean." not in sql
