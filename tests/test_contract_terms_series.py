"""Series scoping in the contract-terms miner."""

from scripts import populate_contract_terms as miner
from scripts.populate_contract_terms import series_pattern_from_security
from src.crispdm.doc_clauses import extract_liquidation_preference, extract_redemption

# Arbor Realty Trust 424B5 (0001104659-24-057042): the per-share preference is
# stated once for the three series jointly.
ABR_424B5 = (
    "Dividends on outstanding shares of Series D Preferred Stock are cumulative and are "
    "payable quarterly in arrears at the rate of 6.375% per annum of the $25.00 liquidation "
    "preference, or $1.59375 per annum per share. Dividends on outstanding shares of Series E "
    "Preferred Stock are cumulative and are payable quarterly in arrears at the rate of 6.25% "
    "per annum of the $25.00 liquidation preference, or $1.5625 per annum per share. Dividends "
    "on outstanding shares of Series F Preferred Stock are cumulative. " + "x " * 400 + "Each "
    "holder of shares of Series D/E/F Preferred Stock is entitled to receive a liquidation "
    "preference of $25.00 per share of Series D/E/F Preferred Stock, plus any accumulated and "
    "unpaid distributions thereon, before the holders of our common stock."
)


def _security(ticker, series):
    return {
        "ticker": ticker,
        "security_name": f"Preferred Stock, 6.25% Series {series} Cumulative Redeemable",
    }


def test_the_middle_series_of_a_joint_list_is_found():
    pattern = series_pattern_from_security(_security("ABR-PE", "E"))

    assert pattern.search("Series D/E/F Preferred Stock")
    assert pattern.search("the Series D, E and F Preferred Stock")
    assert not pattern.search("Series D/F Preferred Stock")
    assert extract_liquidation_preference(ABR_424B5, pattern)["amount"] == 25.0


def test_every_series_of_the_joint_list_gets_the_preference():
    for ticker, series in (("ABR-PD", "D"), ("ABR-PE", "E"), ("ABR-PF", "F")):
        pattern = series_pattern_from_security(_security(ticker, series))
        assert extract_liquidation_preference(ABR_424B5, pattern)["amount"] == 25.0, ticker


# CHS Inc. 424B3 (0001047469-17-002185) states the Series 2/3/4 preference only
# in an entitlement sentence where "liquidation" is followed by a comma.
CHS_424B3 = (
    "Class B Series 2 Preferred Stock On March 27, 2017, we had 16,800,000 shares of Class B "
    "Series 2 Preferred Stock outstanding. Holders of our Class B Series 2 Preferred Stock are "
    "entitled to receive cash dividends at the rate of $1.775 per share per year. In the event "
    "of our liquidation, holders of our Class B Series 2 Preferred Stock are entitled to receive "
    "$25.00 per share plus all 17 Table of Contents dividends accumulated and unpaid on such "
    "share to and including the date of liquidation."
)


def test_a_comma_form_entitlement_sentence_gives_the_preference():
    pattern = series_pattern_from_security(
        {
            "ticker": "CHSCN",
            "security_name": "Class B Reset Rate Cumulative Redeemable Preferred Stock, Series 2",
        }
    )

    result = extract_liquidation_preference(CHS_424B3, pattern)

    assert result["amount"] == 25
    assert result["per_share"] is True


def test_the_entitlement_fallback_ignores_an_annual_dividend_amount():
    text = (
        "In the event of any liquidation, the holders are entitled to receive $1.8125 per share "
        "per annum."
    )

    assert extract_liquidation_preference(text) is None


# Wording adapted from an issuer 424B2 for exchange-listed senior notes.
NOTES_REDEMPTION = (
    "Optional Redemption. We may redeem the notes, in whole or in part, at our option at any "
    "time on or after July 6, 2029, at a redemption price equal to 100% of the principal amount "
    "of the notes being redeemed plus accrued and unpaid interest."
)
PREFERRED_REDEMPTION = (
    "Optional Redemption. The Series B Preferred Stock is not redeemable prior to June 11, 2026. "
    "On or after June 11, 2026, we may, at our option, redeem the Series B Preferred Stock, in "
    "whole or in part, at a redemption price of $25.00 per share, plus accumulated dividends."
)


def test_a_notes_redemption_clause_gives_no_preferred_call_date():
    result = extract_redemption(NOTES_REDEMPTION)

    assert result is None or result.get("first_call_date") is None


def test_a_preferred_redemption_clause_still_gives_its_call_date():
    assert extract_redemption(PREFERRED_REDEMPTION)["first_call_date"] == "2026-06-11"


def test_the_dated_redemption_clause_wins_over_a_later_dateless_restatement():
    dateless = (
        "Optional Redemption. We may, at our option, redeem the Series B Preferred Stock at a "
        "redemption price of $25.00 per share, plus accumulated and unpaid dividends."
    )
    docs = [
        {
            "document_id": 1,
            "form_type": "424B5",
            "exhibit_type": None,
            "raw_text": PREFERRED_REDEMPTION,
        },
        {"document_id": 2, "form_type": "424B5", "exhibit_type": None, "raw_text": dateless},
    ]

    terms = miner.extract_from_documents(docs)

    assert terms["first_call_date"] == "2026-06-11"
    assert terms["call_price"] == 25


def _offering_security():
    return {
        "security_id": 1,
        "cik": "0000000001",
        "ticker": "XYZ-PB",
        "security_name": "7.625% Series B Cumulative Perpetual Preferred Stock",
        "raw_payload": {},
    }


def _patch_offerings(monkeypatch, texts):
    filings = [
        {"form": "424B5", "accessionNumber": f"0000000001-21-00000{i}", "primaryDocument": "d.htm"}
        for i in range(len(texts))
    ]
    pages = iter(texts)
    stored = []
    monkeypatch.setattr(miner, "REQUEST_DELAY", 0)
    monkeypatch.setattr(miner, "_filings", lambda payload, forms: filings)
    monkeypatch.setattr(miner, "fetch_filing", lambda url: (next(pages), "hash"))
    monkeypatch.setattr(miner, "html_to_text", lambda raw: raw)
    monkeypatch.setattr(
        miner, "_store_document", lambda conn, *args: (stored.append(args) or 99, True)
    )
    return stored


def test_an_offering_supplement_needs_the_securitys_own_coupon(monkeypatch):
    other_coupon = PREFERRED_REDEMPTION.replace("Optional", "The 6.50% Series B. Optional")
    stored = _patch_offerings(monkeypatch, [other_coupon])

    assert miner.fetch_offering_supplement(None, _offering_security()) is None
    assert stored == []


def test_the_first_offering_supplement_with_coupon_and_call_date_is_stored(monkeypatch):
    own = PREFERRED_REDEMPTION.replace("Optional", "The 7.625% Series B. Optional")
    stored = _patch_offerings(monkeypatch, ["7.625% Series B, no redemption terms here.", own])

    doc = miner.fetch_offering_supplement(None, _offering_security())

    assert doc["document_id"] == 99
    assert len(stored) == 1
    assert miner.extract_from_documents([doc])["first_call_date"] == "2026-06-11"


def test_a_security_without_a_coupon_in_its_name_is_not_scanned(monkeypatch):
    stored = _patch_offerings(monkeypatch, [PREFERRED_REDEMPTION])
    security = {**_offering_security(), "security_name": "Series B Preferred Stock"}

    assert miner.fetch_offering_supplement(None, security) is None
    assert stored == []


def test_online_mining_keeps_stored_offering_supplements(monkeypatch):
    stored = [
        {"document_id": 1, "form_type": "8-K", "exhibit_type": "EX-3.1", "raw_text": "cert"},
        {"document_id": 7, "form_type": "424B5", "exhibit_type": None, "raw_text": "supplement"},
    ]
    monkeypatch.setattr(miner, "load_stored_documents", lambda conn, sid: stored)
    fetched = [{"document_id": 1, "form_type": "8-K", "exhibit_type": "EX-3.1", "raw_text": "cert"}]

    docs = miner.with_stored_documents(None, 5, fetched)

    assert [doc["document_id"] for doc in docs] == [1, 7]


COVER_PADDING = " Risk factors and use of proceeds." * 120


def test_a_later_series_offering_cannot_donate_its_call_date(monkeypatch):
    later_series = (
        "Prospectus Supplement. 20,000,000 Depositary Shares Each Representing a 1/40th Interest "
        "in a Share of 6.95% Non-Cumulative Perpetual Preferred Stock, Series C."
        + COVER_PADDING
        + " Our outstanding 7.625% Series B remains listed. "
        + PREFERRED_REDEMPTION
    )
    stored = _patch_offerings(monkeypatch, [later_series])

    assert miner.fetch_offering_supplement(None, _offering_security()) is None
    assert stored == []


def test_a_notes_offering_counts_only_a_clause_naming_the_series(monkeypatch):
    notes_cover = "Prospectus Supplement. $50,000,000 7.75% Convertible Senior Notes due 2027."
    notes_only = (
        notes_cover
        + COVER_PADDING
        + " Our 7.625% Series B Preferred Stock is listed on the NYSE."
        + " Terms apply." * 40
        + " Optional redemption. On or after June 16, 2025, we may, at our option, redeem all or "
        "any portion, in whole or in part, at a redemption price of $25.00 per share, plus "
        "accrued interest."
    )
    names_series = notes_cover + COVER_PADDING + " Our 7.625% Series B. " + PREFERRED_REDEMPTION

    stored = _patch_offerings(monkeypatch, [notes_only, names_series])
    doc = miner.fetch_offering_supplement(None, _offering_security())

    assert len(stored) == 1
    assert miner.extract_from_documents([doc])["first_call_date"] == "2026-06-11"


def test_the_coupon_matches_only_as_a_whole_number():
    coupon_re = miner.coupon_regex("10%")

    assert coupon_re.search("a 10% coupon")
    assert not coupon_re.search("redeemed at 110% of par")
    assert not coupon_re.search("a 7.10% rate")


def test_floating_terms_are_mined_only_for_a_floating_structure():
    clause = (
        "Dividends accrue from and including the original issue date to, but excluding, "
        "October 30, 2026 at a fixed rate of 6.25%, and thereafter at a floating rate equal to "
        "Three-Month Term SOFR plus a spread of 5.442% per annum."
    )
    docs = [{"document_id": 1, "form_type": "424B5", "exhibit_type": None, "raw_text": clause}]

    floating = miner.extract_from_documents(docs, floating=True)
    fixed = miner.extract_from_documents(docs)

    assert floating["fixed_period_end"] == "2026-10-30"
    assert str(floating["floating_spread"]) == "5.442"
    assert floating["floating_benchmark"] == "SOFR"
    assert any(section["clause"] == "floating_rate" for section in floating["sections"])
    assert fixed["fixed_period_end"] is None and fixed["floating_spread"] is None


def test_floating_structure_comes_from_the_name_or_coupon_type():
    assert miner.has_floating_structure({"security_name": "6.25% Series F Fixed-to-Floating Rate"})
    assert miner.has_floating_structure({"security_name": "8.750% Series F Fixed-Rate Reset"})
    assert miner.has_floating_structure(
        {"security_name": "Depositary Shares", "coupon_type": "fixed-to-floating"}
    )
    assert not miner.has_floating_structure({"security_name": "6.375% Series D Cumulative"})
