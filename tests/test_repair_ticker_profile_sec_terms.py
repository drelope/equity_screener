from scripts import repair_ticker_profile_sec_terms as repair


def _stored(**overrides):
    row = {
        "security_id": "sid",
        "ticker": "ACR-PD",
        "provider": "SEC_XBRL+OPENBB_YFINANCE",
        "security_name": "ACRES Commercial Realty Corp. 7.875% Series D Preferred Stock",
        "reference_security_type": "preferred stock",
        "openbb": {"short_name": "ACRES Commercial Realty Corp."},
        "active": True,
        "security_type": None,
        "coupon_type": None,
        "coupon_rate": None,
        "fixed_period_end": None,
        "floating_spread": None,
        "tax_status": None,
        "call_date": None,
        "liquidation_preference": None,
    }
    row.update(overrides)
    return row


def test_sec_par_value_in_liquidation_preference_is_flagged_for_clearing():
    row = _stored(
        ticker="AAA",
        security_name="Acme Corp",
        reference_security_type="common stock",
        openbb={},
        security_type="common stock",
        liquidation_preference=0.01,
        sec_xbrl={"liquidation_preference": 0.01},
    )

    parsed = repair.reparse_row(row)

    assert parsed["liquidation_preference"] is None
    assert "liquidation_preference" in repair.changed_columns(row, parsed)


def test_a_row_matching_its_own_title_parse_is_left_alone():
    row = _stored()
    parsed = repair.reparse_row(row)
    row.update(parsed)

    assert repair.changed_columns(row, parsed) == []


def test_numeric_comparison_ignores_representation():
    assert repair._same(7.875, __import__("decimal").Decimal("7.875"))
    assert not repair._same(None, 0)


def test_reference_repair_only_touches_sec_valued_unbacked_terms():
    sql = repair.REFERENCE_REPAIR_SQL
    assert "s.coupon_rate = sec.sec_coupon" in sql
    assert "IS DISTINCT FROM sec.parsed_coupon" in sql
    assert "IS DISTINCT FROM sec.contract_liquidation" in sql


def test_values_not_equal_to_the_sec_fact_are_never_repaired():
    # A prospectus-sourced liquidation preference differs from the title parse
    # but is not the SEC leak, so it must survive.
    row = _stored(liquidation_preference=25.0, sec_xbrl={"liquidation_preference": 0.01})

    assert repair.changed_columns(row, repair.reparse_row(row)) == []


def test_series_label_is_out_of_scope():
    row = _stored(security_type="preferred stock", sec_xbrl={})

    assert repair.changed_columns(row, repair.reparse_row(row)) == []


def test_repaired_coupon_also_rederives_coupon_type():
    row = _stored(
        security_name="Acme Corp Depositary Shares",
        openbb={},
        coupon_rate=8.5,
        coupon_type="fixed",
        sec_xbrl={"coupon_rate": 8.5},
    )
    parsed = repair.reparse_row(row)

    assert parsed["coupon_rate"] is None
    changed = repair.changed_columns(row, parsed)
    assert "coupon_rate" in changed
    assert ("coupon_type" in changed) == (parsed["coupon_type"] != "fixed")


def test_nominal_par_value_is_repaired_even_without_a_sec_fact():
    row = _stored(
        ticker="AAA",
        security_name="Class A common stock, par value $0.0001",
        reference_security_type="common stock",
        openbb={},
        liquidation_preference=0.0001,
        sec_xbrl={},
    )

    parsed = repair.reparse_row(row)

    assert parsed["liquidation_preference"] is None
    assert repair.changed_columns(row, parsed) == ["liquidation_preference"]


def test_a_lone_preferred_allocates_its_issuer_level_coupon():
    # The name is the issuer, so the title parse finds no coupon; with only one
    # active preferred for the CIK the SEC fact is unambiguous.
    row = _stored(
        security_name="FEDERAL REALTY INVESTMENT TRUST",
        openbb={},
        coupon_rate=None,
        sec_xbrl={"coupon_rate": 5.0},
    )

    assert repair.allocation_columns(row, singleton=True) == {
        "coupon_rate": 5.0,
        "coupon_type": "fixed",
    }


def test_allocation_needs_a_singleton_preferred():
    row = _stored(
        security_name="FEDERAL REALTY INVESTMENT TRUST",
        openbb={},
        coupon_rate=None,
        sec_xbrl={"coupon_rate": 5.0},
    )

    assert repair.allocation_columns(row, singleton=False) == {}


def test_allocation_never_overwrites_a_parsed_coupon():
    row = _stored(
        security_name="ACRES Commercial Realty Corp. 7.875% Series D Preferred Stock",
        openbb={},
        coupon_rate=7.875,
        sec_xbrl={"coupon_rate": 7.875},
    )

    assert repair.allocation_columns(row, singleton=True) == {}


def test_allocation_skips_common_stock_and_missing_facts():
    base = {"openbb": {}, "coupon_rate": None, "sec_xbrl": {"coupon_rate": 5.0}}
    common = _stored(security_name="Acme Corp", reference_security_type="common stock", **base)
    no_fact = _stored(
        security_name="Acme Corp",
        reference_security_type="preferred stock",
        openbb={},
        coupon_rate=None,
        sec_xbrl={},
    )

    assert repair.allocation_columns(common, singleton=True) == {}
    assert repair.allocation_columns(no_fact, singleton=True) == {}


def test_allocation_never_touches_an_inactive_preferred():
    row = _stored(
        security_name="FEDERAL REALTY INVESTMENT TRUST",
        openbb={},
        coupon_rate=None,
        active=False,
        sec_xbrl={"coupon_rate": 5.0},
    )

    assert repair.allocation_columns(row, singleton=True) == {}


def test_a_lone_preferred_coupon_is_not_treated_as_a_leak():
    # After allocation the coupon equals the SEC fact with no title-parse
    # backing; the leak repair must leave it, or it clears and re-allocates
    # on every run.
    row = _stored(
        security_name="FEDERAL REALTY INVESTMENT TRUST",
        openbb={},
        coupon_rate=5.0,
        sec_xbrl={"coupon_rate": 5.0},
    )
    parsed = repair.reparse_row(row)

    assert parsed["coupon_rate"] is None
    assert "coupon_rate" not in repair.changed_columns(row, parsed, lone_preferred=True)
    # ... but a multi-preferred issuer's leaked coupon is still cleared.
    assert "coupon_rate" in repair.changed_columns(row, parsed, lone_preferred=False)
