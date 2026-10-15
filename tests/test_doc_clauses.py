"""Mine liquidation-preference and call-price clauses from narrative filings.

Fixtures mirror the real documents:

- 8-K Exhibit 3.1 Certificate of Designation (governing document), and
- 424B5 prospectus supplement "Summary of the Offering" / description sections.

Extractors must surface the *per-share* amount, never the aggregate offering
size ("$1,500,000,000").
"""

import re
from decimal import Decimal

from src.crispdm.doc_clauses import (
    extract_liquidation_preference,
    extract_redemption,
    html_to_text,
)

CERTIFICATE_HTML = """<html><head><title>EX-3.1</title></head><body>
<h2>Certificate of Designation of 7.875% Series D Cumulative Redeemable Preferred Stock</h2>
<p><b>Section 2.  Liquidation Preference.</b> Upon any voluntary or involuntary
liquidation, dissolution or winding up of the Company, the holders of shares of
Series D Cumulative Redeemable Preferred Stock shall be entitled to receive out
of the assets of the Company available for distribution to stockholders, before
any payment or distribution to the holders of any junior stock, an amount equal
to $25.00 per share (as adjusted for any stock dividends, combinations or
splits with respect to such shares) (the "Liquidation Preference"), plus all
accumulated and unpaid dividends to and including the date of distribution.</p>
<p>If, upon any such voluntary or involuntary liquidation, the assets of the
Company are insufficient to make payment in full of the Liquidation Preference
amounts, the holders shall share ratably.</p>
<p><b>Section 5.  Optional Redemption.</b> The shares of Series D Cumulative
Redeemable Preferred Stock shall be redeemable at the option of the Company, in
whole or from time to time in part, on or after June 30, 2027 (the "First
Redemption Date"), at a redemption price of $26.5625 per share (approximately
106.25% of the Liquidation Preference) plus all accumulated and unpaid
dividends. On or after June 30, 2028, the redemption price shall equal $25.00
per share plus all accumulated and unpaid dividends. The Company may not
redeem any shares prior to June 30, 2027, except in limited circumstances
relating to the preservation of the qualification of the Company as a REIT.
</p>
<p><b>Section 8.  Voting Rights.</b> Holders have no voting rights except as
provided by law or as set forth in the Certificate.</p>
</body></html>"""

PROSPECTUS_HTML = """<html><head><title>424B5</title></head><body>
<h1>Prospectus Supplement</h1>
<p><b>Summary of the Offering</b></p>
<table>
<tr><td>Issuer:</td><td>ACRES Commercial Realty Corp.</td></tr>
<tr><td>Securities:</td><td>8.50% Series C Cumulative Redeemable Preferred Stock</td></tr>
<tr><td>Liquidation Preference:</td><td>$25.00 per share</td></tr>
<tr><td>Term:</td><td>Perpetual</td></tr>
<tr><td>Optional Redemption:</td><td>We may redeem the shares on or after
June 30, 2027 at a redemption price of $25.00 per share plus accrued dividends.
On or after June 30, 2028 at $25.00 per share.</td></tr>
<tr><td>Use of Proceeds:</td><td>We expect to receive approximately
$1,500,000,000 from this offering.</td></tr>
</table>
<p><b>Description of the Series C Preferred Stock</b></p>
<p>The shares rank senior to common stock and equal to each other series of
preferred stock as to distributions and upon liquidation. The liquidation
preference of each share of Series C Preferred Stock will be $25.00.</p>
</body></html>"""


def _text(html):
    return html_to_text(html)


def test_certificate_liquidation_preference():
    result = extract_liquidation_preference(_text(CERTIFICATE_HTML))
    assert result is not None
    assert result["amount"] == Decimal("25.00")
    assert result["per_share"] is True
    assert result["confidence"] >= 0.8
    assert "liquidation preference" in result["heading"].lower()
    assert "$25.00 per share" in result["snippet"]


def test_certificate_optional_redemption_call_price_and_schedule():
    result = extract_redemption(_text(CERTIFICATE_HTML))
    assert result is not None
    assert result["first_call_date"] == "2027-06-30"
    assert result["call_price"] == Decimal("26.5625")
    assert result["optional"] is True
    dates = [entry["effective_date"] for entry in result["schedule"]]
    assert dates == ["2027-06-30", "2028-06-30"]
    prices = [entry["price"] for entry in result["schedule"]]
    assert prices == [26.5625, 25.0]
    assert result["confidence"] >= 0.95


def test_prospectus_summary_of_offering_liquidation():
    result = extract_liquidation_preference(_text(PROSPECTUS_HTML))
    assert result is not None
    assert result["amount"] == Decimal("25.00")
    assert "liquidation" in result["heading"].lower()


def test_prospectus_aggregate_amount_not_mistaken_for_per_share():
    text = _text(PROSPECTUS_HTML)
    liquidation = extract_liquidation_preference(text)
    assert liquidation["amount"] == Decimal("25.00")
    assert liquidation["amount"] != Decimal("1500000000")
    redemption = extract_redemption(text)
    assert redemption["call_price"] == Decimal("25.00")


def test_no_liquidation_clause_returns_none():
    assert extract_liquidation_preference("This filing contains no liquidation language.") is None


def test_no_redemption_clause_returns_none():
    assert (
        extract_redemption("No optional redemption features are described in this document.")
        is None
    )


def test_html_to_text_flattens_whitespace():
    text = _text("<html><p>Hello&nbsp;World</p><p>Second\tpara</p></html>")
    assert "Hello World" in text
    assert "Second para" in text


def test_liquidation_preference_defined_term_after_amount():
    document = (
        "An amount equal to $50.00 per share on any liquidation "
        "(" + 'the "Liquidation Preference"' + ")."
    )
    result = extract_liquidation_preference(document)
    assert result["amount"] == Decimal("50.00")


def test_call_price_with_premium_schedule():
    document = (
        "Optional Redemption. On or after March 1, 2028 the Company may redeem "
        "the shares at a redemption price of $27.50 per share. On or after "
        "March 1, 2029 at $25.50 per share. On or after March 1, 2030 at "
        "$25.00 per share."
    )
    result = extract_redemption(document)
    assert result["first_call_date"] == "2028-03-01"
    assert result["call_price"] == Decimal("27.50")
    assert [entry["price"] for entry in result["schedule"]] == [27.5, 25.5, 25.0]


def test_event_triggered_premium_is_not_the_call_price():
    # Real fixed-to-floating institutional preferreds: callable at par on the
    # first reset date, and at a premium only on a rating/regulatory event. The
    # premium is mentioned first, so it used to be stored as the call price.
    document = (
        "Optional Redemption. The Corporation, at its option, may redeem the "
        "Series A Preferred Stock: (i) in whole but not in part at any time "
        "within 90 days after the occurrence of a Rating Agency Event at a "
        "redemption price equal to $25,500 per share, or within 90 days after a "
        "Regulatory Capital Event at a redemption price equal to $25,000 per "
        "share; or (ii) in whole or in part, on or after June 30, 2027 at a "
        "redemption price equal to $25,000 per share, plus accrued dividends."
    )
    result = extract_redemption(document)
    assert result is not None
    assert result["call_price"] == Decimal("25000")
    assert result["first_call_date"] == "2027-06-30"


def test_event_only_prices_fall_back_to_the_first():
    # No scheduled price to prefer, so the event price is still surfaced rather
    # than dropping the redemption clause entirely.
    document = (
        "Special Event. The Company may redeem the Series B Preferred Stock "
        "within 90 days following a Change of Control at a redemption price "
        "equal to $25,500 per share."
    )
    result = extract_redemption(document)
    assert result is not None
    assert result["call_price"] == Decimal("25500")


def test_unadorned_per_share_amount_is_parsed():
    # Some filings omit the "$" sign. The number must still be read rather than
    # tripping the extractor: a missing capture group here silently aborted the
    # whole issuer (33 of them) instead of yielding a value.
    document = (
        "Liquidation Preference. In the event of any liquidation, dissolution "
        "or winding up, holders of Series A Preferred Stock shall receive 25.00 "
        "per share plus declared but unpaid dividends."
    )
    result = extract_liquidation_preference(document)
    assert result is not None
    assert result["amount"] == Decimal("25.00")


TWO_SERIES_PROSPECTUS = (
    "PROSPECTUS SUPPLEMENT. Up to 1,000,000 Shares of Series A Preferred Stock."
    " We may, at our option, redeem the Series A Preferred Stock at any time by "
    "paying $25.00 per share. LIQUIDATION PREFERENCE: $25.00 per share of "
    "Series A Preferred Stock. "
    "The Series A Preferred Stock has no maturity date and we are not required "
    "to redeem it. "
    "Up to 500,000 Shares of Series B Preferred Stock. We may, at our option, "
    "redeem the Series B Preferred Stock on or after June 30, 2029 at a "
    "redemption price of $26.5625 per share, and on or after June 30, 2030 the "
    "redemption price shall equal $25.00 per share. LIQUIDATION PREFERENCE: "
    "$25.00 per share of Series B Preferred Stock. Additional terms follow."
)


def test_series_scoped_liquidation_picks_own_series():
    each = (
        extract_liquidation_preference(
            TWO_SERIES_PROSPECTUS, re.compile(r"\bseries\s*[-.]?\s*A\b", re.I)
        ),
        extract_liquidation_preference(
            TWO_SERIES_PROSPECTUS, re.compile(r"\bseries\s*[-.]?\s*B\b", re.I)
        ),
    )
    assert each[0] is not None and each[1] is not None
    assert each[0]["amount"] == each[1]["amount"] == Decimal("25.00")
    assert "Series A" in each[0]["snippet"]
    assert "Series B" in each[1]["snippet"]


def test_series_scoped_redemption_picks_own_series():
    series_a = extract_redemption(
        TWO_SERIES_PROSPECTUS, re.compile(r"\bseries\s*[-.]?\s*A\b", re.I)
    )
    series_b = extract_redemption(
        TWO_SERIES_PROSPECTUS, re.compile(r"\bseries\s*[-.]?\s*B\b", re.I)
    )
    assert series_a is not None and series_b is not None
    assert series_a["call_price"] == Decimal("25.00")
    assert series_a["first_call_date"] is None
    assert series_b["call_price"] == Decimal("26.5625")
    assert series_b["first_call_date"] == "2029-06-30"
    assert series_b["optional"] is True
    assert "Series B" in series_b["snippet"]


def test_depositary_ratio_from_security_name():
    from src.crispdm.doc_clauses import depositary_ratio

    assert (
        depositary_ratio(
            "Depositary Shares, each representing a 1/1,000th interest in a share "
            "of 5.00% Series A Preferred Stock"
        )
        == 1000
    )
    assert (
        depositary_ratio(
            "Depositary Shares, each representing a 1/40th interest in a share of "
            "6.875% Series E Non-Cumulative Perpetual Preferred Stock"
        )
        == 40
    )
    assert depositary_ratio("4.75% Series A Cumulative Preferred Stock") is None
    assert depositary_ratio("Common Stock, par value $0.001") is None
    # Rights/warrants are also written as fractions but are not depositaries.
    assert (
        depositary_ratio(
            "Rights, each entitling the holder to receive one-tenth (1/10) of a share"
        )
        is None
    )


DEPOSITARY_DOCUMENT = (
    "Description of the Series E Preferred Stock. We may, at our option, redeem "
    "the Series E Preferred Stock on or after June 30, 2025, in whole or in part, "
    "at a redemption price of $1,000.00 per share (equivalent to $25.00 per "
    "depositary share), plus any accrued and unpaid dividends. On or after "
    "June 30, 2026 the redemption price will be $1,000.00 per share. "
    "Liquidation Preference. In the event of any liquidation, holders of the "
    "Series E Preferred Stock shall receive $1,000.00 per share plus accumulated "
    "dividends."
)


def test_depositary_call_price_is_scaled_to_the_depositary_figure():
    result = extract_redemption(_text(DEPOSITARY_DOCUMENT), depositary_ratio=40)
    assert result is not None
    assert result["call_price"] == Decimal("25.00")
    assert result["first_call_date"] == "2025-06-30"
    assert [entry["price"] for entry in result["schedule"]] == [25.0, 25.0]


def test_depositary_liquidation_preference_is_scaled():
    result = extract_liquidation_preference(_text(DEPOSITARY_DOCUMENT), depositary_ratio=40)
    assert result is not None
    assert result["amount"] == Decimal("25.00")


def test_depositary_equivalent_stated_in_document_beats_the_fraction():
    # The security name carries no 1/N token (depositary_ratio is None), but the
    # certificate states the per-depositary equivalent outright.
    document = (
        "Optional Redemption. The Corporation may redeem the Series A Preferred "
        "Stock on or after December 23, 2026 at a redemption price of $25,000.00 "
        "per share (equivalent to $25.00 per depositary share), plus accrued "
        "dividends. Liquidation Preference. Each share has a liquidation "
        "preference of $25.00 per depositary share."
    )
    redemption = extract_redemption(_text(document), depositary_ratio=None)
    assert redemption["call_price"] == Decimal("25.00")
    liquidation = extract_liquidation_preference(_text(document), depositary_ratio=None)
    assert liquidation["amount"] == Decimal("25.00")


def test_implausible_scaled_depositary_amount_is_refused():
    # $1.00 par divided by 1,000 is 0.001, not a plausible per-depositary figure:
    # the matched number was the underlying par, not the redeemable amount.
    document = (
        "Liquidation Preference. The Series A Preferred Stock has a liquidation "
        "preference of $1.00 per share."
    )
    assert extract_liquidation_preference(document, depositary_ratio=1000) is None


def test_past_tense_narrative_is_not_a_call_provision():
    # "The Company redeemed ..." narrates a completed redemption. Treating it as
    # a call clause let the aggregate payment ($2,000,000) be read as a price.
    document = (
        "The Company redeemed the Series B Preferred Stock on March 1, 2023 for "
        "an aggregate amount of $2,000,000."
    )
    assert extract_redemption(document) is None


def test_spac_trust_redemption_is_not_a_preferred_call():
    # "we redeem the public shares ... Trust Account" is a blank-check trust
    # redemption; the nearby per-share figure is the sponsor's founder-share
    # purchase price, not a call price.
    document = (
        "If we are unable to complete an initial business combination within the "
        "required period, we redeem the public shares for the funds held in the "
        "Trust Account. On December 12, 2025, our sponsor paid $12,750, or "
        "approximately $0.004 per share, to cover certain of our offering costs."
    )
    assert extract_redemption(document) is None
    assert extract_redemption(_text(document)) is None


def test_stated_value_definition_is_not_a_call_price():
    # The instrument redeems at a percentage of the stated value, so the stated
    # value itself must not be stored as the call price; the real call price
    # later in the same description should be found instead.
    document = (
        'Optional Redemption. "Stated Value" shall mean $10,000 per share. The '
        "Corporation may redeem the shares at a redemption price of $11,000 per "
        "share on or after June 30, 2030."
    )
    result = extract_redemption(document)
    assert result is not None
    assert result["call_price"] == Decimal("11000")


def test_conversion_price_definition_is_not_a_call_price():
    document = (
        'Optional Redemption. "Conversion Price" means $23.25 per share. The '
        "Corporation may redeem the stock at $25.00 per share."
    )
    result = extract_redemption(document)
    assert result is not None
    assert result["call_price"] == Decimal("25.00")


def test_stated_value_used_as_redemption_price_is_kept():
    # A mere *use* of the stated value as the price ("at a price equal to the
    # stated value of $1,000") is not a definition; $1,000 is the call price.
    document = (
        "Optional Redemption. The Corporation may redeem the Series C Preferred "
        "Stock at a price equal to the stated value of $1,000 per share."
    )
    result = extract_redemption(document)
    assert result is not None
    assert result["call_price"] == Decimal("1000")


def test_percentage_of_stated_value_is_not_a_call_price():
    # "107% of the Stated Value" prices the call as a fraction of a defined
    # value; the $10,000 value must not be read as the call price.
    document = (
        "Each share has an initial Stated Value of $10,000 per share. On or "
        "after June 30, 2027 the Corporation may redeem the shares at 107% of "
        "the Stated Value."
    )
    assert extract_redemption(document) is None


def test_spac_trust_liquidation_is_not_a_preference():
    # "public shareholders ... $10.00 per share on the liquidation of our trust
    # account" is a blank-check trust liquidation, not a preferred preference.
    document = (
        "If we do not complete our initial business combination, our public "
        "shareholders may receive only approximately $10.00 per share on the "
        "liquidation of our trust account."
    )
    assert extract_liquidation_preference(document) is None


def test_aggregate_indebtedness_is_not_a_liquidation_preference():
    # A stray "liquidation" mention pulls in a nearby debt covenant; the
    # $400,000 aggregate is not a preferred per-share preference.
    document = (
        "The occurrence of a default under, redemption of or acceleration prior "
        "to maturity of at least an aggregate of $400,000 of Indebtedness; or "
        "bankruptcy, insolvency or liquidation proceedings instituted against "
        "the Company."
    )
    assert extract_liquidation_preference(document) is None


def test_liquidation_preference_without_per_share_is_kept():
    # A clause that names the preference is kept even without a "per share"
    # unit ("liquidation preference of $1,000").
    document = (
        "Upon any liquidation, each holder shall be entitled to a liquidation "
        "preference of $1,000 before any distribution to common holders."
    )
    result = extract_liquidation_preference(document)
    assert result is not None
    assert result["amount"] == Decimal("1000")


def test_aggregate_liquidation_total_is_not_a_preference():
    # "$300.0 million" is a balance-sheet total, not a per-unit preference.
    document = (
        "The Company has 300,000 shares of 5.75% Preferred, having an aggregate "
        "liquidation preference of $300.0 million. Upon any liquidation each "
        "share receives $25.00 per share."
    )
    result = extract_liquidation_preference(document)
    assert result is not None
    assert result["amount"] == Decimal("25.00")


def test_liquidation_distribution_without_the_word_preference_is_kept():
    # Real certificates say "upon winding up ... receive $X per share" without
    # the literal word "preference".
    document = (
        "Upon any liquidation or winding up the holders of Series C "
        "preferred shares shall be entitled to receive $25,000 per share."
    )
    result = extract_liquidation_preference(document)
    assert result is not None
    assert result["amount"] == Decimal("25000")


def test_warrant_exercise_price_is_not_a_liquidation_preference():
    document = (
        "Upon a liquidation the warrant exercise price that is $6.36 per share "
        "shall apply to any unexercised warrants."
    )
    assert extract_liquidation_preference(document) is None


def test_warrant_redemption_is_not_a_call_price():
    # SPAC warrant documents are commonly mis-typed as preferred stock; the
    # "$18.00" is a share-price trigger for redeeming warrants, not a call price.
    document = (
        "Once the warrants become exercisable, we may redeem the outstanding "
        "warrants at a price of $0.01 per warrant when the price per share of "
        "Class A ordinary shares equals or exceeds $18.00."
    )
    result = extract_redemption(document)
    assert result is None or result["call_price"] != Decimal("18.00")


def test_aggregate_liquidation_threshold_is_not_a_preference():
    # "in excess of $1,000,000" is a registration-rights trigger, not a unit value.
    document = (
        "If the Company has an aggregate Liquidation Preference in excess of "
        "$1,000,000, the Company shall file a registration statement."
    )
    assert extract_liquidation_preference(document) is None


def test_issuance_purchase_price_is_not_a_call_price():
    # The redemption pays "an amount equal to the aggregate purchase price
    # paid" with no fixed figure; the only per-share amount nearby is the
    # issuance price of a different series.
    document = (
        "Company Redemption. The Company may redeem the Series A Preferred "
        "Stock by paying an amount equal to the aggregate purchase price paid. "
        "We entered into a securities purchase agreement for the issuance and "
        "sale of 220 shares of Series B Preferred Stock at a purchase price of "
        "$9,091 per share."
    )
    assert extract_redemption(document) is None
