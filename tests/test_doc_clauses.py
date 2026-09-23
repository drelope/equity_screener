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
