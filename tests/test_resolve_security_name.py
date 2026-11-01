"""Pure tests for how a security's name is chosen (scripts.populate_reference_tables).

Kept out of tests/test_populate_reference_tables.py on purpose: that module defines
``_live_engine``, so conftest tags all of it ``integration`` and the fast lane would skip
these, although none of them needs a database.
"""

SERIES_C = "6.900% Series C Fixed-to-Floating Rate Cumulative Redeemable Preferred Stock"
SERIES_D = "9.375% Series D Fixed-Rate Cumulative Redeemable Preferred Stock"
COMMON = "Common Stock, par value $0.01 per share"


def _resolve(**overrides):
    from scripts.populate_reference_tables import resolve_security_name

    args = {
        "exact_title": None,
        "instrument_matched_title": None,
        "cik_titles": [COMMON, SERIES_C],
        "security_type": "preferred stock",
        "claimed": set(),
        "existing_name": None,
        "issuer_title": "DYNEX CAPITAL INC",
    }
    args.update(overrides)
    return resolve_security_name(**args)


def test_a_sibling_series_does_not_inherit_the_only_preferred_title_on_file():
    """The DX-PD bug: Series D had no cover title, Series C did, and 'one preferred title
    on file' was read as 'this ticker's title', so both carried the Series C name."""
    name, source = _resolve(claimed={SERIES_C.lower()})

    assert name == "DYNEX CAPITAL INC" and source == "issuer_fallback_unresolved"


def test_the_unique_title_is_still_used_when_no_sibling_holds_it():
    name, source = _resolve()

    assert (name, source) == (SERIES_C, "unique_sec_title")


def test_an_exact_title_always_wins_even_if_a_sibling_has_the_same_text():
    name, source = _resolve(exact_title=SERIES_D, claimed={SERIES_D.lower()})

    assert (name, source) == (SERIES_D, "sec_instrument_title")


def test_the_classifier_bound_title_still_outranks_the_unique_title():
    name, source = _resolve(instrument_matched_title=SERIES_D)

    assert (name, source) == (SERIES_D, "sec_companyfacts_title")


def test_a_name_retained_from_an_earlier_run_is_dropped_when_it_is_a_siblings_exact_title():
    name, source = _resolve(cik_titles=[COMMON], existing_name=SERIES_C, claimed={SERIES_C.lower()})

    assert (name, source) == ("DYNEX CAPITAL INC", "issuer_fallback_unresolved")


def test_a_retained_name_that_is_not_a_siblings_title_is_kept():
    name, source = _resolve(cik_titles=[COMMON], existing_name="Some earlier title")

    assert (name, source) == ("Some earlier title", "retained_existing_unverified")


def test_an_issuer_with_no_titles_keeps_the_issuer_name():
    assert _resolve(cik_titles=[]) == ("DYNEX CAPITAL INC", "issuer_fallback_unresolved")


def test_claimed_titles_exclude_the_tickers_own_spellings_and_are_case_insensitive():
    from scripts.populate_reference_tables import titles_claimed_by_others

    titles = {"DX-PC": SERIES_C, "DXPC": SERIES_C, "DX-PD": SERIES_D, "DXPD": SERIES_D}

    assert titles_claimed_by_others(titles, "DX-PD") == {SERIES_C.lower()}
    assert titles_claimed_by_others(titles, "DX-PX") == {SERIES_C.lower(), SERIES_D.lower()}
    assert titles_claimed_by_others(None, "DX-PD") == set()
