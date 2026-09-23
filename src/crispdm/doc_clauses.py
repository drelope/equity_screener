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

Every extractor returns the matched value together with the section heading
and a short evidence snippet, so the stored terms stay auditable.
"""
import re
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTH_JOIN = "|".join(sorted(MONTHS, key=len, reverse=True))

DOLLAR_RE = re.compile(r"\$([0-9][0-9,]*(?:\.[0-9]{1,4})?)")
BARE_PER_SHARE_RE = re.compile(
    r"(?<![A-Za-z0-9$.,])[0-9][0-9,]*(?:\.[0-9]{1,4})?\s+per\s+(?:depositary\s+)?share",
    re.IGNORECASE,
)
PER_SHARE_RE = re.compile(r"per\s+(?:depositary\s+)?share", re.IGNORECASE)
DATE_RE = re.compile(
    rf"\b({_MONTH_JOIN})\s+([0-9]{{1,2}}),?\s+([0-9]{{4}})\b", re.IGNORECASE
)
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
    per_share = PER_SHARE_RE.search(text, max(0, value_offset - 80),
                                    value_offset + 80)
    return per_share is not None


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
    candidates = [match for match in HEADING_RE.finditer(text)
                  if match.start() < position]
    if not candidates:
        return None
    heading = candidates[-1].group(0).strip(" .:;-")
    return heading[:160] or None


def _snippet(text, start, width=180):
    return text[max(0, start - width // 2):start + width].strip()


# --- clause extractors --------------------------------------------------------

LIQUIDATION_ANCHOR = re.compile(
    r"liquidation\s+(?:preference|preferences|rights?)?\s*", re.IGNORECASE
)


def _extract_liquidation_preference(text):
    """Whole-text per-share Liquidation Preference scan (internal helper)."""
    best = None
    for anchor in LIQUIDATION_ANCHOR.finditer(text):
        start = anchor.start()
        window_left = max(0, start - 500)
        window_right = min(len(text), start + 1500)
        window = text[window_left:window_right]
        near = start - window_left
        reference = text[max(0, start - 40):start]
        if "%" in reference or "percent" in reference:
            continue
        for offset, value, match in _dollar_values(window, near=near, span=1000):
            if not (MIN_PER_SHARE <= value <= MAX_PER_SHARE):
                continue
            per_share = _per_share_vicinity(window, offset)
            candidate = {
                "amount": value,
                "per_share": per_share,
                "distance": abs(offset - near),
                "confidence": 0.8 if per_share else 0.5,
                "match": match.group(0).strip(),
            }
            if (best is None
                    or (per_share and not best["per_share"])
                    or (per_share == best["per_share"]
                        and candidate["distance"] < best["distance"])):
                best = {
                    **candidate,
                    "heading": _heading_at(text, window_left + offset) or "Liquidation Preference",
                    "snippet": _snippet(text, window_left + offset),
                }
    if best is not None:
        best.pop("distance", None)
    return best


REDEMPTION_ANCHOR = re.compile(
    r"optional\s+redemption|redemption\s+at\s+the\s+option|"
    r"redeemable\s+at\s+(?:the\s+)?(?:option|(?:our|its|the\s+(?:company|issuer)(?:['\u2019]s)?)\s+option)"
    r"|(?:we|the\s+(?:company|issuer))\s+(?:may\s+)?redeem"
    r"|at\s+(?:our|its|the\s+(?:company|issuer)(?:['\u2019]s)?)\s+option\s*,?\s*(?:we|the\s+(?:company|issuer))?\s*(?:may\s+)?redeem",
    re.IGNORECASE,
)

OPTION_RE = re.compile(
    r"at\s+(?:the\s+)?(?:our|its|the\s+(?:company|issuer)(?:['\u2019]s)?)\s+option"
    r"|option\s+of\s+(?:the\s+)?(?:company|issuer|us)"
    r"|redeemable\s+at\s+(?:the\s+)?(?:option|(?:our|its)\s+option)"
    r"|option(?:al)?\s+to\s+redeem",
    re.IGNORECASE,
)


def _extract_redemption(text):
    """Whole-text optional/call-feature scan (internal helper)."""
    best = None
    for anchor in REDEMPTION_ANCHOR.finditer(text):
        start = anchor.start()
        window = text[start:min(len(text), start + 2200)]
        window_pre = text[max(0, start - 160):start]
        optional = (OPTION_RE.search(window) is not None
                    or OPTION_RE.search(window_pre) is not None)

        call_date = None
        call_match = ON_OR_AFTER_RE.search(window)
        if call_match:
            call_date = _month_day_year(call_match)

        call_price = None
        for offset, value, match in _dollar_values(window):
            if not (MIN_PER_SHARE <= value <= MAX_PER_SHARE):
                continue
            if _per_share_vicinity(window, offset):
                call_price = value
                break

        schedule = []
        for step in ON_OR_AFTER_RE.finditer(window):
            effective = _month_day_year(step)
            if not effective:
                continue
            after = window[step.end():step.end() + 260]
            for _offset, price, _m in _dollar_values(after):
                if MIN_PER_SHARE <= price <= MAX_PER_SHARE:
                    schedule.append({"effective_date": effective,
                                     "price": float(price)})
                    break
        if call_date:
            schedule = [entry for entry in schedule
                        if entry["effective_date"] >= call_date]

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

        if best is None and (candidate["call_price"] is not None
                             or candidate["first_call_date"] is not None):
            best = {
                **candidate,
                "heading": _heading_at(text, start) or "Redemption",
                "snippet": _snippet(text, start, width=220),
            }
        elif (candidate["call_price"] is not None
              and candidate["confidence"] > best["confidence"]):
            best = {
                **candidate,
                "heading": _heading_at(text, start) or "Redemption",
                "snippet": _snippet(text, start, width=220),
            }
    return best


# --- series-scoped extraction -------------------------------------------------

SERIES_WINDOW = 2800
SERIES_TOKEN_RE = re.compile(
    r"\bseries\s*[-.]?\s*[A-Za-z0-9]+\b", re.IGNORECASE
)


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


def extract_liquidation_preference(text, series_pattern=None):
    """Per-share Liquidation Preference; scoped to ``series_pattern`` when given."""
    if series_pattern is None:
        return _extract_liquidation_preference(text)
    best = None
    for start, end in _series_regions(text, series_pattern):
        best = _merge_best_clause(best, _extract_liquidation_preference(text[start:end]))
    return best


def extract_redemption(text, series_pattern=None):
    """Optional / call features; scoped to ``series_pattern`` when given."""
    if series_pattern is None:
        return _extract_redemption(text)
    best = None
    for start, end in _series_regions(text, series_pattern):
        best = _merge_best_clause(best, _extract_redemption(text[start:end]))
    return best
