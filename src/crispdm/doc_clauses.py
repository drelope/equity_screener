"""Mine preferred-stock contractual clauses from narrative SEC filings.

XBRL facts stop where the contract starts: liquidation preferences and call
prices are defined in the governing documents - the Certificate of Designation
(Form 8-K Exhibit 3.1/3.2) and the prospectus / prospectus supplement (424B5,
424B3, S-1/S-3). This module reads the flattened document text and pulls out
the dollar amounts next to the standard contractual phrases:

- ``liquidation preference`` -> the per-share Liquidation Preference
- ``optional redemption`` / ``redemption at the option of the Company`` ->
  the call price at the First Call Date, the First Call Date itself, and any
  redemption price schedule
- a fixed-to-floating / fixed-rate reset dividend clause -> the end of the
  fixed-rate period and the spread over the benchmark rate

Every extractor returns the matched value together with the section heading
and a short evidence snippet, so the stored terms stay auditable.
"""

import re
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_JOIN = "|".join(sorted(MONTHS, key=len, reverse=True))

DOLLAR_RE = re.compile(r"\$([0-9][0-9,]*(?:\.[0-9]{1,4})?)")
BARE_PER_SHARE_RE = re.compile(
    r"(?<![A-Za-z0-9$.,])([0-9][0-9,]*(?:\.[0-9]{1,4})?)\s+per\s+(?:depositary\s+)?share",
    re.IGNORECASE,
)
PER_SHARE_RE = re.compile(r"per\s+(?:depositary\s+)?share", re.IGNORECASE)
DATE_RE = re.compile(rf"\b({_MONTH_JOIN})\s+([0-9]{{1,2}}),?\s+([0-9]{{4}})\b", re.IGNORECASE)
ON_OR_AFTER_RE = re.compile(
    rf"(?:on\s+or\s+after|at\s+any\s+time\s+on\s+or\s+after|on\s+and\s+after|beginning\s*(?:on)?)\s+({_MONTH_JOIN})\s+([0-9]{{1,2}}),?\s+([0-9]{{4}})",
    re.IGNORECASE,
)

#: Reasonable per-share dollar range for listed preferreds. Filters out
#: aggregate offering amounts ("$1,500,000,000").
MIN_PER_SHARE = 1
MAX_PER_SHARE = 1_000_000

HEADING_RE = re.compile(
    r"(?:(?:Section|Clause|Item)\s+[0-9]+(?:\.|\)|[A-Za-z]?)\s*"
    r"|(?:\(?[a-z0-9]\)\s*)?)"
    r"\s*(liquidation\s+preference|optional\s+redemption|redemption(?:\s+at\s+the\s+option)?"
    r"|call\s+provisions?|summary\s+of\s+the\s+offering"
    r"|description\s+of\s+(?:the\s+)?(?:series\s+[A-Za-z0-9]+\s+)?preferred[^.\n]{0,60})"
    r"[\s:.-]*",
    re.IGNORECASE,
)


def html_to_text(html):
    """Flatten HTML into normalized single-spaced text for clause scanning."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["p", "div", "tr", "li", "td", "h1", "h2", "h3", "h4", "br"]):
        tag.append(" ")
    text = soup.get_text(" ")
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_money(raw):
    cleaned = raw.replace(",", "").strip("$ ")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _dollar_values(text, near=None, span=0):
    """All money values in ``text`` with their character offsets.

    Only truly monetary tokens are yielded: values prefixed with ``$``, plus
    bare numbers that carry the "per share" unit. Bare digit runs (years,
    counts) are ignored.
    """
    out = []
    seen_starts = set()
    for pattern in (DOLLAR_RE, BARE_PER_SHARE_RE):
        for match in pattern.finditer(text):
            start = match.start()
            if start in seen_starts:
                continue
            seen_starts.add(start)
            raw = match.group(1)
            value = _parse_money(raw)
            if value is None:
                continue
            if near is not None and abs(start - near) > span:
                continue
            out.append((start, value, match))
    out.sort(key=lambda item: item[0])
    return out


def _per_share_vicinity(text, value_offset):
    """True when a per-share term sits within 80 chars of the money value."""
    per_share = PER_SHARE_RE.search(text, max(0, value_offset - 80), value_offset + 80)
    return per_share is not None


#: Depositary fraction in a security name: "1/40th", "1/1,000th", "(1/10)". The
#: denominator is how many depositary shares represent one preferred share, so a
#: per-share amount is divided by it to reach the per-depositary figure.
DEPOSITARY_RATIO_RE = re.compile(r"1\s*/\s*([0-9][0-9,]*)")
#: "one one-thousandth of a share" / "a one-fortieth interest".
_WORD_FRACTIONS = {
    "tenth": 10,
    "twentieth": 20,
    "twenty-fifth": 25,
    "fortieth": 40,
    "hundredth": 100,
    "four-hundredth": 400,
    "thousandth": 1000,
    "four-thousandth": 4000,
    "ten-thousandth": 10000,
}
DEPOSITARY_WORD_RATIO_RE = re.compile(
    r"\bone[\s-]+(" + "|".join(sorted(_WORD_FRACTIONS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_DEPOSITARY_NAME_RE = re.compile(r"deposit[ao]r|\bdep\.?\s+shs?\b", re.IGNORECASE)
#: A figure followed by this is already stated per depositary share.
PER_DEPOSITARY_RE = re.compile(r"per\s+depositary\s+share", re.IGNORECASE)
#: The first "per [depositary ]share" unit after a money value; group 1 captures
#: "depositary " only when present, which is what marks a per-depositary figure.
_SHARE_UNIT_RE = re.compile(r"per\s+(depositary\s+)?share", re.IGNORECASE)
#: "..is $25,000.00 per share (equivalent to $25.00 per depositary share)" gives
#: the per-depositary value directly, so it beats dividing the share figure.
DEPOSITARY_EQUIVALENT_RE = re.compile(
    r"equivalent\s+to\s+(?:a\s+)?\$([0-9][0-9,]*(?:\.[0-9]+)?)[^.$]{0,48}?"
    r"per\s+depositary\s+share",
    re.IGNORECASE,
)


def depositary_ratio(name):
    """The depositary fraction denominator in ``name`` (1/N -> N), else None.

    ``None`` means either not a depositary or a single-share American depositary
    receipt (ratio 1), both of which need no scaling. The "depositary" guard
    keeps the 1/N pattern from latching onto rights and warrants, which are also
    described as fractions ("each right entitling the holder to one-tenth (1/10)
    of a share") but are not preferred shares and must not be divided.
    """
    if not name or not _DEPOSITARY_NAME_RE.search(name):
        return None
    match = DEPOSITARY_RATIO_RE.search(name)
    if not match:
        word = DEPOSITARY_WORD_RATIO_RE.search(name)
        return _WORD_FRACTIONS[word.group(1).lower()] if word else None
    try:
        ratio = int(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return ratio if ratio > 1 else None


def _is_per_depositary(text, offset):
    """True when the amount at ``offset`` is itself stated per depositary share.

    Only the amount's *own* unit decides: the first "per ... share" after it. A
    later parenthetical ("... per share (equivalent to $25.00 per depositary
    share)") belongs to the per-depositary equivalent, not to this figure, so it
    must not be mistaken for the figure's unit.
    """
    match = _SHARE_UNIT_RE.search(text, offset, offset + 60)
    return match is not None and match.group(1) is not None


def _depositary_equivalent(text, offset):
    """The per-depositary equivalent of the amount at ``offset``, if stated nearby.

    The search stops at the first sentence break so an "equivalent to ... per
    depositary share" further down the paragraph (e.g. next to the dividend
    rate) cannot stand in for this amount's own equivalent.
    """
    tail = text[offset : offset + 200]
    stop = next((m.start() for m in re.finditer(r"\.\s", tail)), len(tail))
    match = DEPOSITARY_EQUIVALENT_RE.search(tail[:stop])
    if not match:
        return None
    return _parse_money(match.group(1))


def _scale_for_depositary(text, offset, value, ratio):
    """Convert a per-share amount to its per-depositary value.

    Order matters: a figure already given per depositary share is left alone; a
    per-depositary equivalent the document states outright wins; otherwise the
    known 1/N fraction is applied. A result below 1 is not a plausible
    per-depositary preferred figure -- it means the matched number was not the
    underlying par -- so it is refused rather than stored as a wrongly precise
    value.
    """
    if _is_per_depositary(text, offset):
        return value
    equivalent = _depositary_equivalent(text, offset)
    if equivalent is not None:
        return equivalent
    if ratio and ratio > 1:
        scaled = value / ratio
        return scaled if scaled >= 1 else None
    return value


def _all_dates(text):
    return [(match.start(), _month_day_year(match)) for match in DATE_RE.finditer(text)]


def _month_day_year(match):
    month = MONTHS[match.group(1).lower()]
    day = int(match.group(2))
    year = int(match.group(3))
    if day < 1 or day > 31 or year < 1900:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _heading_at(text, position):
    """Best-effort section heading appearing right before ``position``."""
    candidates = [match for match in HEADING_RE.finditer(text) if match.start() < position]
    if not candidates:
        return None
    heading = candidates[-1].group(0).strip(" .:;-")
    return heading[:160] or None


def _snippet(text, start, width=180):
    return text[max(0, start - width // 2) : start + width].strip()


# --- clause extractors --------------------------------------------------------

LIQUIDATION_ANCHOR = re.compile(
    r"liquidation\s+(?:preference|preferences|rights?)?\s*", re.IGNORECASE
)

_PAR_VALUE_PREFIX_RE = re.compile(r"\bpar\s+value(?:\s+of)?\s*[:(]?\s*$", re.IGNORECASE)

#: The plain-English entitlement sentence ("In the event of our liquidation,
#: holders of ... are entitled to receive $25.00 per share plus ..."). The
#: anchor above needs whitespace after "liquidation", so this comma form is
#: missed; it is only consulted when the anchored scan finds nothing.
LIQUIDATION_ENTITLEMENT_RE = re.compile(
    r"in\s+the\s+event\s+of\s+(?:our|any|the|a)?\s*(?:voluntary\s+or\s+involuntary\s+)?"
    r"liquidation\b[^.$]{0,250}?\bholders\b[^.$]{0,200}?\bentitled\s+to\s+receive\s+"
    r"(\$\s?\d[\d,]*(?:\.\d+)?)\s+per\s+(?:depositary\s+)?(?:share|unit)\b",
    re.IGNORECASE,
)


def _extract_liquidation_entitlement(text, depositary_ratio=None):
    for match in LIQUIDATION_ENTITLEMENT_RE.finditer(text):
        value = _parse_money(match.group(1))
        if value is None or not (MIN_PER_SHARE <= value <= MAX_PER_SHARE):
            continue
        offset = match.start(1)
        if re.match(r"\s*(?:per\s+annum|per\s+year|each\s+year|annually)", text[match.end() :]):
            continue
        amount = _scale_for_depositary(text, offset, value, depositary_ratio)
        if amount is None:
            continue
        return {
            "amount": amount,
            "per_share": True,
            "confidence": 0.7,
            "match": match.group(1).strip(),
            "heading": _heading_at(text, offset) or "Liquidation Preference",
            "snippet": _snippet(text, offset),
        }
    return None


def _extract_liquidation_preference(text, depositary_ratio=None):
    """Whole-text per-share Liquidation Preference scan (internal helper)."""
    best = None
    for anchor in LIQUIDATION_ANCHOR.finditer(text):
        start = anchor.start()
        if _in_spac_narrative(text, start):
            continue
        window_left = max(0, start - 500)
        window_right = min(len(text), start + 1500)
        window = text[window_left:window_right]
        near = start - window_left
        reference = text[max(0, start - 40) : start]
        if "%" in reference or "percent" in reference:
            continue
        for offset, value, match in _dollar_values(window, near=near, span=1000):
            if not (MIN_PER_SHARE <= value <= MAX_PER_SHARE):
                continue
            if _in_spac_narrative(window, offset):
                continue
            absolute = window_left + offset
            amount = _scale_for_depositary(window, offset, value, depositary_ratio)
            if amount is None:
                # Not a plausible per-depositary figure (e.g. the underlying par
                # divided by the fraction); prefer another candidate, if any.
                continue
            per_share = _per_share_vicinity(window, offset)
            if not per_share and not _looks_like_preference_clause(window, offset):
                # A figure with no "per share" unit is only a liquidation
                # preference when its clause says so; otherwise it is an
                # aggregate or unrelated amount that happened to sit near a
                # stray "liquidation" mention.
                continue
            if _looks_like_aggregate_amount(window, offset, match, per_share):
                continue
            if _looks_like_warrant_clause(window, offset):
                continue
            if not per_share and _IN_EXCESS_OF_RE.search(_clause_prefix(window, offset)):
                continue
            if _negates_liquidation_rights(window, offset):
                continue
            if _PAR_VALUE_PREFIX_RE.search(window[max(0, offset - 30) : offset]):
                # "(par value $1.00 per share) (Liquidation Preference as
                # specified below)": the nearest per-share figure is the par.
                continue
            candidate = {
                "amount": amount,
                "per_share": per_share,
                "distance": abs(offset - near),
                "confidence": 0.8 if per_share else 0.5,
                "match": match.group(0).strip(),
            }
            if (
                best is None
                or (per_share and not best["per_share"])
                or (per_share == best["per_share"] and candidate["distance"] < best["distance"])
            ):
                best = {
                    **candidate,
                    "heading": _heading_at(text, absolute) or "Liquidation Preference",
                    "snippet": _snippet(text, absolute),
                }
    if best is not None:
        best.pop("distance", None)
        return best
    return _extract_liquidation_entitlement(text, depositary_ratio)


REDEMPTION_ANCHOR = re.compile(
    r"optional\s+redemption|redemption\s+at\s+the\s+option|"
    r"redeemable\s+at\s+(?:the\s+)?(?:option|(?:our|its|the\s+(?:company|issuer)(?:['\u2019]s)?)\s+option)"
    # Excluding the past participle keeps "the Company redeemed ... for
    # $2,000,000" out: a sentence narrating a completed redemption is not a call
    # provision, and reading its aggregate payment as a call price is how an
    # aggregate became a per-share figure. Present-tense "redeems" still counts.
    r"|(?:we|the\s+(?:company|issuer))\s+(?:may\s+)?redeem(?!ed\b)"
    r"|at\s+(?:our|its|the\s+(?:company|issuer)(?:['\u2019]s)?)\s+option\s*,?\s*(?:we|the\s+(?:company|issuer))?\s*(?:may\s+)?redeem(?!ed\b)",
    re.IGNORECASE,
)

OPTION_RE = re.compile(
    r"at\s+(?:the\s+)?(?:our|its|the\s+(?:company|issuer)(?:['\u2019]s)?)\s+option"
    r"|option\s+of\s+(?:the\s+)?(?:company|issuer|us)"
    r"|redeemable\s+at\s+(?:the\s+)?(?:option|(?:our|its)\s+option)"
    r"|option(?:al)?\s+to\s+redeem",
    re.IGNORECASE,
)

#: Event-triggered redemption clauses (ratings downgrade, regulatory capital
#: event, change of control, tax event, make-whole) carry a *premium* over the
#: standing optional-redemption price. A dollar amount read from one of these
#: must not be mistaken for the scheduled call price: a $25,000-par series that
#: is callable at par on its first reset date also redeems at $25,500 on a
#: rating event, and the premium often appears first in the text.
EVENT_REDEMPTION_RE = re.compile(
    r"ratings?\s+event|rating\s+agency\s+event|regulatory\s+capital\s+event"
    r"|change\s+of\s+control|special\s+event|tax\s+event|make[-\s]?whole"
    r"|delisting\s+event|capital\s+event"
    r"|following\s+the\s+occurrence\s+of",
    re.IGNORECASE,
)
#: How far back of a dollar amount to look for the clause that introduces it.
EVENT_CONTEXT_CHARS = 200
#: A clause ends at a semicolon, a numbered/lettered sub-clause marker, or a
#: sentence boundary. The trigger phrase lives in the same sub-clause as the
#: amount it introduces, so cutting at the previous break keeps a schedule's
#: preceding event clause from tainting a later scheduled price.
_CLAUSE_BREAK_RE = re.compile(r";|\.\s|\(\w{1,3}\)")


def _in_event_clause(window, offset):
    """True when the text introducing ``offset`` describes an event redemption.

    Only the prefix back to the previous clause break is inspected: the trigger
    phrase ("within 90 days after a Ratings Event at a redemption price of ...")
    precedes the amount, whereas a scheduled price is introduced by "on or after
    <date> at ...". Looking past the amount would let an event clause later in
    the paragraph taint the scheduled price it follows.
    """
    tail = window[max(0, offset - EVENT_CONTEXT_CHARS) : offset]
    cut = 0
    for match in _CLAUSE_BREAK_RE.finditer(tail):
        cut = match.end()
    return EVENT_REDEMPTION_RE.search(tail[cut:]) is not None


#: Blank-check (SPAC) trust language is not a preferred clause: "we redeem the
#: public shares for the funds held in the Trust Account" and "public
#: shareholders may receive ... $10.00 per share on the liquidation of our trust
#: account" describe returning trust money to public holders, not a preferred
#: call or liquidation preference.
_SPAC_NARRATIVE_RE = re.compile(
    r"trust\s+account|public\s+shares|public\s+stockholders|public\s+shareholders"
    r"|founder\s+shares|initial\s+business\s+combination|\bsponsor\b",
    re.IGNORECASE,
)
#: A definition of a stated/par/conversion value is not a redemption price:
#: "... (mm) "Stated Value" shall mean $10,000 per share" and "... "Conversion
#: Price" means $23.25 per share" define a value, not the price at which shares
#: are called. A mere use ("at a price equal to the stated value of $1,000") is
#: left alone -- there the stated value *is* the redemption price.
_VALUE_DEFINITION_RE = re.compile(
    r"(?:stated|par|initial|conversion|exercise)\s+(?:value|amount|price)"
    r"[^.;]{0,40}?(?:shall\s+mean|means?|has\s+the\s+meaning)",
    re.IGNORECASE,
)
#: "110% of the Stated Value" prices the call as a fraction of a defined value,
#: so the value being defined nearby must not be read as the call price.
_PERCENT_OF_VALUE_RE = re.compile(
    r"\d{1,3}(?:\.\d+)?\s*%\s*of\s+the\s+(?:stated|par|initial)\s+value",
    re.IGNORECASE,
)
_STATED_VALUE_RE = re.compile(r"(?:stated|par|initial)\s+value", re.IGNORECASE)


def _in_spac_narrative(text, position):
    """True when ``position`` sits inside blank-check (SPAC) trust language."""
    return _SPAC_NARRATIVE_RE.search(text[max(0, position - 200) : position + 200]) is not None


def _clause_prefix(window, offset, back=EVENT_CONTEXT_CHARS):
    """Text introducing ``offset`` since the previous clause break."""
    tail = window[max(0, offset - back) : offset]
    cut = 0
    for match in _CLAUSE_BREAK_RE.finditer(tail):
        cut = match.end()
    return tail[cut:]


def _looks_like_value_definition(window, offset, percentage_priced=False):
    """True when the amount at ``offset`` defines a value rather than a price."""
    clause = _clause_prefix(window, offset)
    if _VALUE_DEFINITION_RE.search(clause):
        return True
    return percentage_priced and _STATED_VALUE_RE.search(clause) is not None


#: A non-per-share liquidation figure is only trusted when its own clause names
#: a preference ("liquidation preference of $...", "Series A Liquidation
#: Preference means $...", "an amount equal to the Stated Value"). Without this,
#: a stray "liquidation" mention pulls in a nearby aggregate indebtedness
#: covenant ("an aggregate of $400,000 of Indebtedness"), a lease payment or a
#: listing-fee figure and stores it as a preferred liquidation value.
_PREFERENCE_CLAUSE_RE = re.compile(
    r"preference|liquidation\s+(?:value|price|amount)|stated\s+value"
    r"|liquidating\s+distribution",
    re.IGNORECASE,
)


def _looks_like_preference_clause(window, offset):
    return _PREFERENCE_CLAUSE_RE.search(_clause_prefix(window, offset)) is not None


#: "purchase price ... for the issuance and sale of" is the price of a new
#: offering, not a redemption price. Reads like BTCY's Series A, whose redemption
#: pays "an amount equal to the aggregate purchase price paid" with no fixed
#: per-share figure, would otherwise adopt the Series B issue price ($9,091).
_ISSUANCE_CONTEXT_RE = re.compile(
    r"issuance|gross\s+proceeds|securities\s+purchase\s+agreement|\boffering\b|sale\s+of",
    re.IGNORECASE,
)


def _looks_like_issuance_price(window, offset):
    clause = _clause_prefix(window, offset)
    return "purchase price" in clause.lower() and _ISSUANCE_CONTEXT_RE.search(clause) is not None


#: A warrant/right figure ("exercise price that is $6.36 per share", "we may
#: redeem the public warrants ... at $0.01 per warrant", the "$18.00" price
#: trigger for warrant redemption) is neither a preferred call nor a liquidation
#: preference. SPAC warrants are routinely mis-classified as preferred stock, so
#: this also neutralises those.
_WARRANT_CLAUSE_RE = re.compile(r"\bwarrants?\b|exercise\s+price|\bper\s+warrant\b", re.IGNORECASE)
#: "an aggregate Liquidation Preference in excess of $1,000,000" is a funding
#: threshold, not the per-unit preference.
_IN_EXCESS_OF_RE = re.compile(r"in\s+excess\s+of", re.IGNORECASE)


def _looks_like_warrant_clause(window, offset):
    # A wider window than the clause prefix: bulleted warrant-redemption terms
    # put "per warrant" before a ";", so the trigger price in a later bullet
    # ("... equals or exceeds $18.00 per share") has no warrant in its own clause.
    return _WARRANT_CLAUSE_RE.search(window[max(0, offset - 200) : offset + 200]) is not None


#: An aggregate expressed in millions/billions ("an aggregate liquidation
#: preference of $300.0 million", "$1 28 million") is a balance-sheet total, not
#: a per-unit value.
_VALUE_SCALE_RE = re.compile(r"\s*\d{0,3}\s*(?:million|billion)\b", re.IGNORECASE)
#: A clause that says the stock has *no* liquidation rights is not stating a
#: liquidation preference, however many per-share figures sit nearby.
_NEGATED_PREFERENCE_RE = re.compile(
    r"does\s+not\s+have[^.;]{0,48}?liquidation\s+(?:rights|preference|value)",
    re.IGNORECASE,
)


def _looks_like_aggregate_amount(window, offset, match, per_share):
    """True when a figure is an aggregate/total, not a unit value."""
    # A figure scaled by "million"/"billion" is a total regardless of any nearby
    # "per share" (e.g. "$300.0 million ... each share receives $25.00").
    if _VALUE_SCALE_RE.match(window[match.end() : match.end() + 18]):
        return True
    if per_share:
        return False
    # Comparative balance-sheet total: "$544,800 and $247,200" (prior year), on
    # either side of the figure.
    after = window[match.end() : match.end() + 16]
    before = window[max(0, offset - 16) : offset]
    return (
        re.match(r"\s*(?:and\s+)?\$", after) is not None
        or re.search(r"\$\s*[0-9][0-9,]*\s*(?:and\s+)?$", before) is not None
    )


def _negates_liquidation_rights(window, offset):
    return _NEGATED_PREFERENCE_RE.search(window[max(0, offset - 40) : offset + 240]) is not None


#: "The notes may be redeemed ..." / "we may redeem ... the notes": a debt
#: redemption clause (a notes prospectus filed by a preferred issuer), not the
#: preferred's call feature.
_DEBT_REDEMPTION_RE = re.compile(
    r"\b(?:the|our|such|of)\s+(?:[\w-]+\s+){0,3}?(?:notes|debentures|debt\s+securities)\b",
    re.IGNORECASE,
)
_EQUITY_SUBJECT_RE = re.compile(
    r"\bpreferred\b|\bpreference\b|\bshares?\b|\bunits?\b", re.IGNORECASE
)


def _is_debt_redemption(window_pre, window):
    clause = window_pre[-60:] + window[:160]
    return _DEBT_REDEMPTION_RE.search(clause) is not None and not _EQUITY_SUBJECT_RE.search(clause)


def _extract_redemption(text, depositary_ratio=None):
    """Whole-text optional/call-feature scan (internal helper)."""
    percentage_priced = _PERCENT_OF_VALUE_RE.search(text) is not None
    best = None
    for anchor in REDEMPTION_ANCHOR.finditer(text):
        start = anchor.start()
        if _in_spac_narrative(text, start):
            continue
        window = text[start : min(len(text), start + 2200)]
        window_pre = text[max(0, start - 160) : start]
        if _is_debt_redemption(window_pre, window):
            continue
        optional = OPTION_RE.search(window) is not None or OPTION_RE.search(window_pre) is not None

        call_date = None
        call_match = ON_OR_AFTER_RE.search(window)
        if call_match:
            call_date = _month_day_year(call_match)

        # The standing call price is the first per-share amount introduced by a
        # scheduled (non-event) redemption clause. An event-triggered premium
        # that appears earlier in the window is skipped; if every per-share
        # amount sits in an event clause the first one is kept as a fallback.
        call_price = None
        call_offset = None
        event_fallback = None
        event_offset = None
        for offset, value, _match in _dollar_values(window):
            if not (MIN_PER_SHARE <= value <= MAX_PER_SHARE):
                continue
            if not _per_share_vicinity(window, offset):
                continue
            if _in_event_clause(window, offset):
                if event_fallback is None:
                    event_fallback = value
                    event_offset = offset
                continue
            if _looks_like_value_definition(window, offset, percentage_priced):
                continue
            if _looks_like_issuance_price(window, offset):
                continue
            if _looks_like_warrant_clause(window, offset):
                continue
            call_price = value
            call_offset = offset
            break
        if call_price is None:
            call_price = event_fallback
            call_offset = event_offset
        if call_price is not None:
            call_price = _scale_for_depositary(window, call_offset, call_price, depositary_ratio)

        schedule = []
        for step in ON_OR_AFTER_RE.finditer(window):
            effective = _month_day_year(step)
            if not effective:
                continue
            after = window[step.end() : step.end() + 260]
            picked = None
            for offset, price, _m in _dollar_values(after):
                if MIN_PER_SHARE <= price <= MAX_PER_SHARE and not _in_event_clause(after, offset):
                    picked = (offset, price)
                    break
            if picked is None:
                # Every per-share value in the step sits in an event clause;
                # fall back to the first so the step is not silently dropped.
                for offset, price, _m in _dollar_values(after):
                    if MIN_PER_SHARE <= price <= MAX_PER_SHARE:
                        picked = (offset, price)
                        break
            if picked is None:
                continue
            # A schedule states per-share prices like the call price, so the
            # depositary fraction (or a stated equivalent) applies here too.
            offset, price = picked
            scaled = _scale_for_depositary(after, offset, price, depositary_ratio)
            if scaled is not None:
                schedule.append({"effective_date": effective, "price": float(scaled)})
        if call_date:
            schedule = [entry for entry in schedule if entry["effective_date"] >= call_date]

        candidate = {
            "call_price": call_price,
            "first_call_date": call_date,
            "schedule": schedule,
            "optional": optional,
            "match": window[:200].strip(),
        }
        confidence = 0.0
        if call_date is not None:
            confidence += 0.35
        if call_price is not None:
            confidence += 0.45
        if optional:
            confidence += 0.2
        candidate["confidence"] = round(confidence, 2)

        if best is None and (
            candidate["call_price"] is not None or candidate["first_call_date"] is not None
        ):
            best = {
                **candidate,
                "heading": _heading_at(text, start) or "Redemption",
                "snippet": _snippet(text, start, width=220),
            }
        elif candidate["call_price"] is not None and candidate["confidence"] > best["confidence"]:
            best = {
                **candidate,
                "heading": _heading_at(text, start) or "Redemption",
                "snippet": _snippet(text, start, width=220),
            }
    return best


# --- series-scoped extraction -------------------------------------------------

SERIES_WINDOW = 2800
SERIES_TOKEN_RE = re.compile(r"\bseries\s*[-.]?\s*[A-Za-z0-9]+\b", re.IGNORECASE)


def _series_regions(text, series_pattern):
    """Text regions describing THE given series, boundaries at other series.

    The document is partitioned by every "Series X" mention (all series take
    the token positions). Each target-series token gets the block it begins --
    from just before itself to the next mention of a *different* series -- so a
    combined prospectus keeps each series' terms in its own region instead of
    bleeding into the neighbours.
    """
    targets = [match.start() for match in series_pattern.finditer(text)]
    if not targets:
        return []
    other_starts = [match.start() for match in SERIES_TOKEN_RE.finditer(text)]
    others = [pos for pos in other_starts if pos not in set(targets)]

    regions = []
    for position in targets:
        next_marker = next((p for p in others if p > position), len(text))
        if next_marker == len(text):
            end = min(len(text), position + SERIES_WINDOW)
        else:
            end = next_marker
        regions.append((max(0, position - 120), end))

    merged = []
    for start, end in sorted(regions):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _merge_best_clause(current, candidate):
    if candidate is None:
        return current
    if current is None:
        return candidate
    priority = 0
    if candidate.get("per_share") is True and current.get("per_share") is not True:
        priority += 1
    if candidate.get("optional") is True and current.get("optional") is not True:
        priority += 1
    if candidate.get("first_call_date") and not current.get("first_call_date"):
        priority += 1
    if candidate.get("confidence", 0) > current.get("confidence", 0) + 0.1:
        priority += 1
    return candidate if priority else current


_ANY_SERIES_RE = re.compile(r"\b[Ss]eries\s+(?:[A-Z]{1,2}|\d{1,2})\b")


def _names_only_this_series(text, series_pattern):
    """True when every "Series X" in ``text`` is this series, so scoping cannot
    pick up another series' terms (a single-series certificate that otherwise
    says just "the Convertible Preferred Stock")."""
    return all(series_pattern.search(m.group(0)) for m in _ANY_SERIES_RE.finditer(text))


def extract_liquidation_preference(text, series_pattern=None, depositary_ratio=None):
    """Per-share Liquidation Preference; scoped to ``series_pattern`` when given."""
    if series_pattern is None:
        return _extract_liquidation_preference(text, depositary_ratio)
    best = None
    for start, end in _series_regions(text, series_pattern):
        best = _merge_best_clause(
            best, _extract_liquidation_preference(text[start:end], depositary_ratio)
        )
    if best is None and _names_only_this_series(text, series_pattern):
        best = _extract_liquidation_preference(text, depositary_ratio)
    return best


def extract_redemption(text, series_pattern=None, depositary_ratio=None):
    """Optional / call features; scoped to ``series_pattern`` when given."""
    if series_pattern is None:
        return _extract_redemption(text, depositary_ratio)
    best = None
    for start, end in _series_regions(text, series_pattern):
        best = _merge_best_clause(best, _extract_redemption(text[start:end], depositary_ratio))
    return best


# A fixed-to-floating (or fixed-rate reset) dividend sentence names both terms
# together: "... to, but excluding, October 30, 2026 at a fixed rate equal to
# 6.25% ... and (ii) from and including October 30, 2026 at a floating rate equal
# to ... Three-Month Term SOFR plus a spread of 5.442% per annum". Requiring the
# fixed-period end and the benchmark spread in one clause keeps a credit
# facility's "SOFR plus 1.30%" or a note's "Treasury Rate plus 25 basis points"
# from being read as a preferred's floating terms.
FLOATING_CLAUSE_RE = re.compile(
    r"to,?\s+but\s+(?:excluding|not\s+including),?\s+(?:the\s+)?"
    rf"(?P<month>{_MONTH_JOIN})\s+(?P<day>[0-9]{{1,2}}),?\s+(?P<year>[0-9]{{4}})"
    r"(?P<mid>.{0,700}?)"
    r"(?P<benchmark>SOFR|LIBOR|benchmark(?:\s+rate)?|treasury\s+rate|reference\s+rate|treasury)"
    r"[^.;]{0,220}?\bplus\s+(?:a\s+spread\s+of\s+)?(?P<spread>[0-9]{1,2}(?:\.[0-9]{1,4})?)\s*%",
    re.IGNORECASE | re.DOTALL,
)
_FIXED_RATE_RE = re.compile(r"\bfixed\b", re.IGNORECASE)
_FLOATING_CONTEXT_RE = re.compile(
    r"floating|\breset\b|benchmark|\bSOFR\b|\bLIBOR\b|treasury", re.IGNORECASE
)
MIN_FLOATING_SPREAD = Decimal("0.1")
MAX_FLOATING_SPREAD = Decimal("15")


def _extract_floating_terms(text):
    for match in FLOATING_CLAUSE_RE.finditer(text):
        if not _FIXED_RATE_RE.search(text[max(0, match.start() - 250) : match.start() + 400]):
            continue
        if not _FLOATING_CONTEXT_RE.search(match.group("mid") + match.group("benchmark")):
            continue
        spread = Decimal(match.group("spread"))
        if not MIN_FLOATING_SPREAD <= spread <= MAX_FLOATING_SPREAD:
            continue
        end = _month_day_year(match)
        if end is None:
            continue
        return {
            "fixed_period_end": end,
            "floating_spread": spread,
            "benchmark": " ".join(match.group("benchmark").split()),
            "heading": _heading_at(text, match.start()),
            "snippet": _snippet(text, match.start(), width=400),
            "match": " ".join(match.group(0).split())[:400],
        }
    return None


def extract_floating_terms(text, series_pattern=None):
    """Fixed-period end date + floating/reset spread over the benchmark (percent).

    Scoped to ``series_pattern`` when given; returns the first series region
    whose dividend clause states both terms, or None.
    """
    if series_pattern is None:
        return _extract_floating_terms(text)
    for start, end in _series_regions(text, series_pattern):
        found = _extract_floating_terms(text[start:end])
        if found:
            return found
    return None
