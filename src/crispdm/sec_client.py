import hashlib
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .http_retry import Throttle, request_with_backoff
from .xbrl_tags import (
    DIVIDEND_FACT_TERMS,
    DIVIDEND_RECENCY_DAYS,
    PREFERRED_COUPON_CONCEPTS,
    PREFERRED_LIQUIDATION_CONCEPTS,
    PREFERRED_PAR_VALUE_CONCEPTS,
    SECURITY_ATTRIBUTE_TAGS,
    SECURITY_FACT_RULES,
    normalize_security_type,
)

logger = logging.getLogger(__name__)

try:
    from .config import settings
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from src.crispdm.config import settings

HEADERS = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}


class SECDataUnavailableError(requests.exceptions.HTTPError):
    """Raised when SEC has no Company Facts dataset for an issuer CIK."""

    def __init__(self, cik, url, response=None):
        self.cik = str(cik).zfill(10)
        self.url = url
        super().__init__(
            f"SEC Company Facts unavailable for CIK {self.cik}: {url}", response=response
        )


SEC_MIN_INTERVAL = float(os.environ.get("SEC_MIN_INTERVAL", "0.15"))
SEC_THROTTLE = Throttle(SEC_MIN_INTERVAL)


class _SecSession(requests.Session):
    """SEC session that enforces the fair-access User-Agent before any request."""

    def get(self, url, **kwargs):
        settings.require_sec_user_agent()
        SEC_THROTTLE.wait()
        return request_with_backoff(self, "GET", url, **kwargs)


SEC_SESSION = _SecSession()
SEC_SESSION.headers.update(HEADERS)
SEC_SESSION.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=4,
            connect=4,
            read=4,
            backoff_factor=1.5,
            status_forcelist=(),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
    ),
)


def get_company_tickers():
    """
    Fetch all company tickers from the SEC's official company_tickers.json source.

    Returns:
        dict: A mapping of index to company info with keys:
            - cik_str: Central Index Key (integer)
            - ticker: Stock ticker symbol (string)
            - title: Company name (string)

    Example:
        >>> tickers = get_company_tickers()
        >>> aapl_entry = tickers["1"]  # Apple
        >>> print(aapl_entry['ticker'])  # 'AAPL'
        >>> print(aapl_entry['cik_str'])  # 320193
    """
    r = SEC_SESSION.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=HEADERS,
        timeout=(10, 30),
    )
    r.raise_for_status()
    return r.json()


def ticker_to_cik(ticker):
    """
    Look up CIK number by stock ticker symbol.

    Args:
        ticker (str): Stock ticker symbol (case-insensitive, e.g. "AAPL")

    Returns:
        int: Central Index Key, or None if ticker not found

    Example:
        >>> cik = ticker_to_cik("AAPL")
        >>> print(cik)  # 320193
    """
    ticker = ticker.upper().strip()
    try:
        tickers_data = get_company_tickers()
        for entry in tickers_data.values():
            if entry["ticker"] == ticker:
                return entry["cik_str"]
    except Exception as e:
        print(f"Error looking up ticker {ticker}: {e}")
    return None


def cik_to_ticker(cik):
    """
    Look up ticker symbol by CIK number.

    Args:
        cik (int): Central Index Key

    Returns:
        str: Stock ticker symbol, or None if CIK not found

    Example:
        >>> ticker = cik_to_ticker(320193)
        >>> print(ticker)  # 'AAPL'
    """
    cik = int(cik)
    try:
        tickers_data = get_company_tickers()
        for entry in tickers_data.values():
            if entry["cik_str"] == cik:
                return entry["ticker"]
    except Exception as e:
        print(f"Error looking up CIK {cik}: {e}")
    return None


def get_submissions(cik):
    r = SEC_SESSION.get(
        f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",
        headers=HEADERS,
        timeout=(10, 30),
    )
    r.raise_for_status()
    return r.json()


def get_exchange_list():
    """
    Return a standard list of major US stock exchanges.

    Returns:
        list: List of dicts with 'code' and 'name' keys
    """
    return [
        {"code": "NYSE", "name": "New York Stock Exchange"},
        {"code": "NASDAQ", "name": "NASDAQ Stock Market"},
        {"code": "AMEX", "name": "American Stock Exchange"},
        {"code": "ARCA", "name": "NYSE ARCA"},
        {"code": "BATS", "name": "BATS Global Markets"},
        {"code": "OTC", "name": "Over-The-Counter"},
        {"code": "PINK", "name": "OTC Pink Sheets"},
    ]


def get_issuer_data(cik):
    """
    Extract issuer information from SEC submissions API.

    Args:
        cik (int or str): Central Index Key

    Returns:
        dict: Issuer data with keys: cik, issuer_name, sic, fiscal_year_end
    """
    try:
        data = get_submissions(cik)

        # SEC submissions returns these issuer fields at the payload root.
        # Keep nested fallbacks for older cached/test payloads.
        entity_info = data.get("entityInformation", {}) or {}
        issuer_name = data.get("name") or entity_info.get("name") or ""
        sic = data.get("sic") or entity_info.get("sic") or ""
        fiscal_year_end = data.get("fiscalYearEnd") or entity_info.get("fiscalYearEnd")
        if fiscal_year_end and len(str(fiscal_year_end)) == 4:
            fiscal_year_end = f"{str(fiscal_year_end)[:2]}-{str(fiscal_year_end)[2:]}"

        return {
            "cik": str(int(cik)).zfill(10),
            "issuer_name": issuer_name,
            "sic": str(sic),
            "fiscal_year_end": fiscal_year_end,
        }
    except Exception as e:
        print(f"Error fetching issuer data for CIK {cik}: {e}")
        return None


def get_legacy_issuer_data(cik):
    """Read SEC company metadata for an optional repair pass."""
    try:
        response = SEC_SESSION.get(
            "https://www.sec.gov/cgi-bin/browse-edgar",
            params={
                "action": "getcompany",
                "CIK": str(int(cik)).zfill(10),
            },
            headers=HEADERS,
            timeout=(10, 30),
        )
        response.raise_for_status()
        page_text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)

        def field(pattern):
            match = re.search(pattern, page_text, flags=re.IGNORECASE)
            return match.group(1).strip() if match else None

        fiscal_year_end = field(r"Fiscal\s+Year\s+End\s*:\s*(\d{4})")
        if fiscal_year_end:
            fiscal_year_end = f"{fiscal_year_end[:2]}-{fiscal_year_end[2:]}"

        return {
            "cik": str(int(cik)).zfill(10),
            "issuer_name": field(r"Company\s+Name\s*:\s*(.+?)\s+(?=CIK\s*:)") or "",
            "sic": field(r"SIC\s+Code\s*:\s*(\d+)"),
            "fiscal_year_end": fiscal_year_end,
        }
    except Exception as exc:
        print(f"Legacy SEC lookup failed for CIK {cik}: {exc}")
        return None


def get_all_issuers_from_tickers(limit=None):
    """
    Fetch issuer information for all tickers in the SEC company_tickers.json.

    Args:
        limit (int): Maximum number of issuers to fetch (for testing)

    Returns:
        list: List of issuer dicts
    """
    tickers_data = get_company_tickers()
    issuers = []

    count = 0
    for entry in tickers_data.values():
        if limit and count >= limit:
            break

        cik = entry.get("cik_str")
        ticker = entry.get("ticker")
        title = entry.get("title", "")

        try:
            issuer_info = get_issuer_data(cik)
            if issuer_info:
                issuer_info["ticker"] = ticker
                issuer_info["company_title"] = title
                issuers.append(issuer_info)
                count += 1
                if count % 100 == 0:
                    print(f"Fetched {count} issuers...")
        except Exception as e:
            print(f"Skipping CIK {cik} ({ticker}): {e}")

    return issuers


def classify_security_type(title):
    """Infer a security type from the SEC company ticker title.

    SEC's ticker feed has no dedicated instrument-type field, so the title is
    the first SEC classification signal. Issuer SIC remains separate metadata.
    """
    normalized_title = (title or "").strip().lower()

    if any(term in normalized_title for term in ("option", "options")):
        return "option"

    if any(term in normalized_title for term in ("future", "futures")):
        return "future"

    if any(term in normalized_title for term in ("warrant", "right")):
        return "derivative"

    if any(
        term in normalized_title for term in ("preferred", "depositary share", "depositary receipt")
    ):
        return "preferred stock"

    if any(term in normalized_title for term in ("government bond", "treasury", "municipal bond")):
        return "government debt"

    if any(
        term in normalized_title
        for term in (
            "bond",
            "debenture",
            "corporate note",
            "senior debt",
            "subordinated debt",
            "due 20",
        )
    ):
        return "corporate bond"

    if any(term in normalized_title for term in ("unit", "units")):
        return "other_debt_and_equity"

    if any(
        term in normalized_title
        for term in (
            "certificate",
            "commercial paper",
            "asset-backed",
            "loan participation",
        )
    ):
        return "other_debt"

    if any(
        term in normalized_title
        for term in (
            "common stock",
            "common shares",
            "ordinary shares",
            "class a",
            "class b",
            "class c",
        )
    ):
        return "common_stock"

    if any(term in normalized_title for term in ("stock", "share", "equity")):
        return normalize_security_type("equity")

    return normalize_security_type("other")


#: Concept-bucket preference used only when no stronger per-instrument signal
#: (symbol suffix, title, dividend evidence) decided the type.
SECURITY_TYPE_FALLBACK_PRIORITY: tuple[str, ...] = (
    "common_stock",
    "preferred stock",
    "debt",
    "corporate bond",
    "government debt",
    "other_debt",
    "other_debt_and_equity",
    "option",
    "future",
    "derivative",
    "equity",
    "other_equity",
    "other",
)


@dataclass(frozen=True)
class SymbolSuffix:
    """Class evidence parsed from the trailing dash segment of an SEC symbol."""

    security_type: str
    raw_suffix: str
    series_letter: Optional[str] = None
    kind: str = "suffix"


def symbol_suffix_evidence(ticker):
    """Parse the class encoded in a symbol's trailing dash segment.

    SEC assigns one ticker symbol per registered class; the class sits after
    the final dash: ``ACR-PC`` is Series C preferred, ``BRK-B`` Class B common,
    ``-U`` a unit, ``-W/-WS/-WT`` a warrant and ``-R`` a right. Hyphenless
    series codes (``LFMDP``) deliberately return None here: without the dash the
    junk-vs-series ambiguity is resolved by dei titles / dividend evidence
    instead. Returns a SymbolSuffix, or None when no dash suffix exists.
    """
    symbol = str(ticker or "").strip().upper()
    match = re.match(r"^.+?-([A-Z][A-Z0-9]{0,3})$", symbol)
    if not match:
        return None
    suffix = match.group(1)
    if suffix.startswith("P"):
        letter = suffix[1:]
        return SymbolSuffix("preferred stock", suffix, letter or None)
    if suffix == "U":
        return SymbolSuffix("other_debt_and_equity", suffix)
    if suffix in ("W", "WS", "WT", "R"):
        return SymbolSuffix("derivative", suffix)
    return SymbolSuffix("common_stock", suffix, suffix)


def classify_security_symbol(ticker):
    """Infer the class of a listed series from its SEC ticker symbol.

    SEC assigns one ticker symbol per registered class, with the series encoded
    in the final dash segment: ``ACR-PC`` is Series C preferred, ``BRK-B`` is
    Class B common, trailing ``-U`` is a unit, ``-W``/``-WS`` a warrant and
    ``-R`` a right. Returns one member of ``SECURITY_TYPE_VOCABULARY`` or None
    when the symbol does not carry an identifiable class suffix.
    """
    suffix = symbol_suffix_evidence(ticker)
    return suffix.security_type if suffix is not None else None


def collapse_security_types(security_types, dividend_fact_tags=None):
    """Reduce a CIK-level concept-bucket set to one representative security_type.

    ``classify_companyfacts`` matches XBRL concept buckets, so nearly every
    issuer reports ``{common_stock, preferred stock, equity, debt, ...}``
    regardless of what it actually lists. The dividend-fact tags (which name
    ``Common`` or ``Preferred`` explicitly) are the strongest concept-level
    signal; when they are silent the fallback favours ``common_stock`` because
    the plain SEC symbol of a multi-class issuer is its common share.
    """
    facts = [str(f.get("tag", "")).lower() for f in (dividend_fact_tags or [])]
    has_common = any("common" in tag for tag in facts)
    has_preferred = any("preferred" in tag for tag in facts)

    if has_preferred and not has_common and "preferred stock" in security_types:
        return "preferred stock"
    if has_common and not has_preferred and "common_stock" in security_types:
        return "common_stock"

    for candidate in SECURITY_TYPE_FALLBACK_PRIORITY:
        if candidate in security_types:
            return candidate
    return "other"


@dataclass(frozen=True)
class BoundTitle:
    """A dei security title alongside how strongly it names one symbol."""

    title: str
    index: int
    security_type: str
    series_letter: Optional[str] = None
    strong: bool = False


def _extract_series_letter(title):
    """Pull the series tag from a security title, e.g. ``Series C`` -> ``C``."""
    text = str(title or "").strip()
    match = re.search(r"\bseries\s+([A-Za-z0-9]+)", text, re.IGNORECASE)
    if match:
        return match.group(1).upper(), True
    match = re.search(r"\bclass\s+([A-Za-z0-9]+)", text, re.IGNORECASE)
    if match:
        return match.group(1).upper(), True
    return None, False


def _symbol_series_letter(symbol):
    """Series letter embedded in the symbol's dash suffix (``ACR-PC`` -> ``C``)."""
    suffix = symbol_suffix_evidence(symbol)
    return suffix.series_letter if suffix is not None else None


def bind_dei_titles_to_symbol(titles, symbol=None):
    """Rank dei security titles by how strongly each one names ``symbol``.

    A title is ``strong`` for the instrument when its series tag matches the
    symbol's suffix letter (``Series C Preferred`` binds ``ACR-PC``), or when
    the issuer reports exactly one title (it can only name the single series).
    Titles are kept in their reported (recency) order.
    """
    stripped = []
    for item in titles or []:
        if not isinstance(item, str) or not item.strip():
            continue
        if item.strip() not in stripped:
            stripped.append(item.strip())
    symbol_series = _symbol_series_letter(symbol)
    bound = []
    for index, title in enumerate(stripped):
        series_letter, has_series = _extract_series_letter(title)
        strong = False
        if symbol_series is not None and has_series and series_letter == symbol_series:
            strong = True
        elif symbol_series is None and len(stripped) == 1:
            strong = True
        bound.append(
            BoundTitle(
                title=title,
                index=index,
                security_type=classify_security_type(title),
                series_letter=series_letter,
                strong=strong,
            )
        )
    return bound


@dataclass(frozen=True)
class InstrumentClassification:
    """Per-instrument decision with its audit trail.

    ``source``/``confidence`` classify how the type was decided; ``evidence``
    is the ordered record of every signal examined; ``conflicts`` lists signals
    that pointed at different classes and were overruled. ``submissions`` is the
    anchor snapshot (membership/position/exchange) when available.
    """

    security_type: str
    source: str
    confidence: str
    matched_title: Optional[str] = None
    submissions: Optional[dict] = None
    evidence: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)


def _bound_details(bound):
    return [
        {
            "title": item.title,
            "security_type": item.security_type,
            "series_letter": item.series_letter,
            "strong": item.strong,
        }
        for item in bound
    ]


def classify_instrument(
    ticker, classification=None, *, dei_titles=None, submissions=None, issuer_name=None
):
    """Decide the single canonical security_type for one SEC-listed instrument.

    Combines, in priority order, the symbol's dash suffix (high), dei titles
    bound to the symbol by series letter (high), the issuer name keywords, the
    submissions ``tickers[]`` anchor / leading-position (medium), dividend-tag
    evidence (medium) and finally the CIK-level concept bag (low). Every
    decision carries the source, confidence and evidence array so the reference
    row's audit trail can explain itself.
    """
    classification = classification or {}
    symbol = str(ticker or "").strip().upper()
    titles = [
        title
        for title in (dei_titles or classification.get("security_titles") or [])
        if isinstance(title, str) and title.strip()
    ]
    titles = list(dict.fromkeys(titles))
    evidence = []
    conflicts = []

    # Phase 0: submissions tickers[] anchor.
    anchor = {
        "in_tickers": False,
        "position": None,
        "primary": False,
        "exchange": None,
        "anchor_ok": submissions is not None,
    }
    if submissions is not None:
        order = submissions.get("order") or []
        positions = {str(value).upper(): index for index, value in enumerate(order)}
        position = positions.get(symbol)
        anchor = {
            "in_tickers": position is not None,
            "position": position,
            "primary": position == 0,
            "exchange": (submissions.get("exchange_by_symbol") or {}).get(symbol),
            "anchor_ok": True,
        }
    evidence.append({"phase": 0, "signal": "submissions_tickers", "detail": anchor})
    if anchor["anchor_ok"] and not anchor["in_tickers"]:
        evidence.append(
            {"phase": 0, "signal": "submissions_mismatch", "detail": {"symbol": symbol}}
        )

    # Phase 1: symbol dash suffix (non-common classes decide immediately).
    suffix = symbol_suffix_evidence(symbol)
    if suffix is not None and suffix.security_type != "common_stock":
        evidence.append(
            {
                "phase": 1,
                "signal": "symbol_suffix",
                "detail": {
                    "type": suffix.security_type,
                    "raw_suffix": suffix.raw_suffix,
                    "series_letter": suffix.series_letter,
                },
            }
        )
        bound = bind_dei_titles_to_symbol(titles, symbol)
        strong = [item for item in bound if item.strong]
        if strong:
            title_types = {item.security_type for item in strong}
            title_types.discard("other")
            if len(title_types) == 1 and next(iter(title_types)) != suffix.security_type:
                conflicts.append(
                    f"suffix:{suffix.security_type} vs title:{next(iter(title_types))}"
                    f" ({strong[0].title})"
                )
        return InstrumentClassification(
            security_type=suffix.security_type,
            source="symbol_suffix",
            confidence="high",
            matched_title=strong[0].title if strong else None,
            submissions=anchor,
            evidence=evidence,
            conflicts=conflicts,
        )

    # Phase 2a: issuer-name keywords.
    if issuer_name:
        issuer_type = classify_security_type(issuer_name)
        if issuer_type != "other":
            evidence.append({"phase": 2, "signal": "issuer_title", "detail": {"type": issuer_type}})
            if suffix is None:
                return InstrumentClassification(
                    security_type=issuer_type,
                    source="issuer_title",
                    confidence="medium",
                    evidence=evidence,
                    conflicts=conflicts,
                    submissions=anchor,
                )

    # Phase 2b: dei titles bound to the symbol.
    bound = bind_dei_titles_to_symbol(titles, symbol)
    evidence.append({"phase": 2, "signal": "dei_titles", "detail": _bound_details(bound)})
    strong = [item for item in bound if item.strong]
    if strong:
        distinct = {item.security_type for item in strong}
        distinct.discard("other")
        if len(distinct) == 1:
            decided_type = next(iter(distinct))
            matched_title = strong[0].title
            if suffix is not None and suffix.security_type != decided_type:
                # A series-letter-bound dei title names this exact series, so
                # it overrides the generic dash-common default (e.g. WCC-A is
                # Series A *Preferred*). Record the overruled suffix signal.
                conflicts.append(f"suffix:{suffix.security_type} overruled by title:{decided_type}")
            return InstrumentClassification(
                security_type=decided_type,
                source="dei_title",
                confidence="high",
                matched_title=matched_title,
                evidence=evidence,
                conflicts=conflicts,
                submissions=anchor,
            )

    # Phase 2c: sole / unanimous dei titles (medium confidence). A unanimous
    # type may classify the instrument, but multiple titles cannot identify
    # which series name belongs to this ticker.
    typed_titles = [(title, classify_security_type(title)) for title in titles]
    title_types = {title_type for _title, title_type in typed_titles}
    title_types.discard("other")
    decided_title = None
    if len(titles) == 1 and len(title_types) == 1:
        decided_title = titles[0]
    elif len(title_types) == 1:
        matching_titles = [title for title, title_type in typed_titles if title_type != "other"]
        if len(matching_titles) == 1:
            decided_title = matching_titles[0]
    decided_type = next(iter(title_types)) if len(title_types) == 1 else None
    if decided_type is not None:
        if suffix is not None and suffix.security_type != decided_type:
            conflicts.append(f"suffix:{suffix.security_type} vs title:{decided_type}")
        if suffix is not None and decided_type != "common_stock":
            # Unbound titles are less specific than a dash suffix; keep the
            # symbol's reading but surface the disagreement.
            return InstrumentClassification(
                security_type="common_stock",
                source="symbol_suffix",
                confidence="high",
                matched_title=decided_title,
                evidence=evidence,
                conflicts=conflicts,
                submissions=anchor,
            )
        return InstrumentClassification(
            security_type=decided_type,
            source="dei_title",
            confidence="medium",
            matched_title=decided_title,
            evidence=evidence,
            conflicts=conflicts,
            submissions=anchor,
        )
    if len(title_types) > 1:
        evidence.append({"phase": 2, "signal": "titles_multi_class", "detail": sorted(title_types)})

    # Phase 3: submissions leading position declares the plain symbol common.
    if (
        suffix is None
        and anchor["anchor_ok"]
        and anchor["in_tickers"]
        and anchor["position"] == 0
        and len(title_types) > 1
        and "common_stock" in title_types
    ):
        evidence.append(
            {
                "phase": 3,
                "signal": "submissions_leading",
                "detail": {"position": anchor["position"]},
            }
        )
        common_titles = [title for title, title_type in typed_titles if title_type != "other"]
        common_title = common_titles[0] if len(common_titles) == 1 else None
        return InstrumentClassification(
            security_type="common_stock",
            source="submissions_leading",
            confidence="medium",
            matched_title=common_title,
            evidence=evidence,
            conflicts=conflicts,
            submissions=anchor,
        )

    # Phase 4: dividend-fact tags discriminate Common vs Preferred.
    bag = classification.get("security_types") or []
    facts = [str(f.get("tag", "")).lower() for f in (classification.get("dividend_facts") or [])]
    has_common = any("common" in tag for tag in facts)
    has_preferred = any("preferred" in tag for tag in facts)
    if has_preferred and not has_common and "preferred stock" in bag:
        evidence.append(
            {
                "phase": 4,
                "signal": "dividend_facts",
                "detail": {"preferred_tag": True, "common_tag": False},
            }
        )
        return InstrumentClassification(
            security_type="preferred stock",
            source="dividend_facts",
            confidence="medium",
            evidence=evidence,
            conflicts=conflicts,
            submissions=anchor,
        )
    if has_common and not has_preferred and "common_stock" in bag:
        evidence.append(
            {
                "phase": 4,
                "signal": "dividend_facts",
                "detail": {"preferred_tag": False, "common_tag": True},
            }
        )
        return InstrumentClassification(
            security_type="common_stock",
            source="dividend_facts",
            confidence="medium",
            evidence=evidence,
            conflicts=conflicts,
            submissions=anchor,
        )

    # Phase 5: fall back to the concept bag / unavailable marker.
    if suffix is not None:
        return InstrumentClassification(
            security_type="common_stock",
            source="symbol_suffix",
            confidence="high",
            evidence=evidence,
            conflicts=conflicts,
            submissions=anchor,
        )
    if not classification or classification.get("status") == "unavailable":
        return InstrumentClassification(
            security_type="other",
            source="unavailable",
            confidence="low",
            evidence=evidence,
            conflicts=conflicts,
            submissions=anchor,
        )
    decided_type = collapse_security_types(bag, classification.get("dividend_facts"))
    evidence.append({"phase": 5, "signal": "concept_bag", "detail": {"bag": bag}})
    return InstrumentClassification(
        security_type=decided_type,
        source="concept_bag",
        confidence="low",
        evidence=evidence,
        conflicts=conflicts,
        submissions=anchor,
    )


def security_type_for_instrument(ticker, title, classification, dei_titles=None, submissions=None):
    """Return the single canonical security_type for one listed instrument.

    ``reference.securities`` keeps one row per SEC-listed instrument (each
    symbol in company_tickers.json or the submissions ``tickers[]`` names one
    series), so the CIK-level concept set from ``classify_companyfacts`` must
    never fan out into several rows. Delegates to :func:`classify_instrument`,
    which combines the symbol suffix, dei titles bound by series letter, the
    submissions anchor and dividend evidence into one audited decision.
    """
    return classify_instrument(
        ticker,
        classification,
        dei_titles=dei_titles,
        submissions=submissions,
        issuer_name=title,
    ).security_type


def get_security_data_from_tickers():
    """
    Convert SEC company_tickers.json into security reference data.

    Returns:
        list: List of security dicts with: ticker, issuer_name, security_name, security_type
    """
    tickers_data = get_company_tickers()
    securities = []

    for entry in tickers_data.values():
        security = {
            "ticker": entry.get("ticker"),
            "cik": entry.get("cik_str"),
            "issuer_name": entry.get("title", "").strip(),
            "security_name": entry.get("title", "").strip(),
            "security_type": classify_security_type(entry.get("title")),
            "currency": "USD",
            "active": True,
        }
        securities.append(security)

    return securities


def get_companyfacts(cik):
    normalized_cik = str(int(cik)).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{normalized_cik}.json"
    r = SEC_SESSION.get(
        url,
        headers=HEADERS,
        timeout=(10, 30),
    )
    if r.status_code == 404:
        raise SECDataUnavailableError(normalized_cik, url, response=r)
    r.raise_for_status()
    return r.json()


def get_companyconcept(cik, taxonomy, concept):
    """Fetch the XBRL Data API facts for a single company concept.

    The ``companyconcept`` endpoint returns the facts one company reported for
    a specific concept within a taxonomy (``us-gaap``, ``ifrs-full``, ``dei``,
    ``srt``, ...). It is far smaller than the full ``companyfacts`` payload and
    lets callers target preferred-stock concepts without pulling every tag the
    issuer has ever filed. Raises ``requests.HTTPError`` with status 404 when
    the issuer did not report the concept.
    """
    r = SEC_SESSION.get(
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK{int(cik):010d}/{taxonomy}/{concept}.json",
        headers=HEADERS,
        timeout=(10, 30),
    )
    r.raise_for_status()
    return r.json()


def _companyfacts_taxonomies(payload):
    """Return the taxonomy map (e.g. ``us-gaap``) from an SEC companyfacts payload.

    The live SEC endpoint nests taxonomies under ``facts``; older cached/test
    payloads keep them at the root. Accept both shapes.
    """
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("facts")
    return nested if isinstance(nested, dict) else payload


# Backward-compatible aliases: the canonical tag map lives in
# ``src.crispdm.xbrl_tags`` (see XBRL_TAGS table in the registry docstring).
SECURITY_FACT_RULES = SECURITY_FACT_RULES
DIVIDEND_FACT_TERMS = DIVIDEND_FACT_TERMS
DIVIDEND_RECENCY_DAYS = DIVIDEND_RECENCY_DAYS
PREFERRED_COUPON_CONCEPTS = PREFERRED_COUPON_CONCEPTS
PREFERRED_LIQUIDATION_CONCEPTS = PREFERRED_LIQUIDATION_CONCEPTS
PREFERRED_PAR_VALUE_CONCEPTS = PREFERRED_PAR_VALUE_CONCEPTS


def build_companyfacts_concept_groups(facts):
    """Group the us-gaap concepts of a companyfacts payload into families.

    Pure function over an already-fetched payload, so callers can produce the
    ``concept_groups`` column of ``raw.companyfacts`` without a second SEC
    request. Returns the per-family concept lists; the caller keeps the outer
    ``cik``/``company``/``full_facts`` envelope.
    """
    us_gaap = _companyfacts_taxonomies(facts).get("us-gaap", {})
    concept_names = sorted(us_gaap)
    groups = {
        "dividends": [],
        "earnings": [],
        "cash_flow": [],
        "balance_sheet": [],
        "debt": [],
        "tax": [],
        "share_counts": [],
    }

    for concept_name in concept_names:
        name_lower = concept_name.lower()
        if "dividend" in name_lower:
            groups["dividends"].append(concept_name)
        if any(token in name_lower for token in ("earnings", "income", "eps", "profit", "margin")):
            groups["earnings"].append(concept_name)
        if any(
            token in name_lower
            for token in ("cashflow", "cash_flow", "operatingcashflow", "freecashflow", "fcf")
        ):
            groups["cash_flow"].append(concept_name)
        if any(
            token in name_lower
            for token in ("asset", "liability", "equity", "balance", "shareholder")
        ):
            groups["balance_sheet"].append(concept_name)
        if any(
            token in name_lower
            for token in ("debt", "borrow", "liability", "notespayable", "longtermdebt")
        ):
            groups["debt"].append(concept_name)
        if "tax" in name_lower:
            groups["tax"].append(concept_name)
        if any(
            token in name_lower
            for token in ("share", "shares", "stock", "commonstock", "treasurystock")
        ):
            groups["share_counts"].append(concept_name)

    return {
        "all_concepts": concept_names,
        "concept_groups": groups,
    }


def get_companyfacts_concepts(cik):
    """Fetch company facts and group SEC XBRL concepts for ingestion."""
    facts = get_companyfacts(cik)
    grouped = build_companyfacts_concept_groups(facts)
    return {
        "cik": str(int(cik)).zfill(10),
        "company": facts.get("entityName") if isinstance(facts, dict) else None,
        **grouped,
        "full_facts": facts,
    }


SECURITY_FACT_RULES = SECURITY_FACT_RULES


def _fact_values(concept):
    for unit, records in (concept.get("units") or {}).items():
        if not isinstance(records, list):
            records = [records]
        for record in records:
            if isinstance(record, dict):
                yield unit, record


def extract_security_titles(companyfacts):
    """Return the distinct registered security titles from a companyfacts payload.

    SEC's ``dei`` taxonomy reports one ``SecurityTitle`` / ``Security12bTitle``
    value per registered class, so a single issuer payload often lists several
    titles (common stock plus each preferred series). Values are read in the
    canonical tag order (``dei:SecurityTitle``, then ``dei:Security12bTitle``,
    see ``xbrl_tags.SECURITY_ATTRIBUTE_TAGS['security_name']``) and, within a
    tag, favour the most recently filed title, de-duplicated across tags.
    """
    payload = companyfacts.get("full_facts", companyfacts)
    dei = _companyfacts_taxonomies(payload).get("dei", {})
    titles = []
    seen = set()
    for concept_name in SECURITY_ATTRIBUTE_TAGS["security_name"]:
        taxonomy, _, tag = concept_name.partition(":")
        if taxonomy != "dei":
            continue
        concept = dei.get(tag)
        if not isinstance(concept, dict):
            continue
        records = []
        for _unit, record in _fact_values(concept):
            title = record.get("val")
            if isinstance(title, str) and title.strip():
                records.append((str(record.get("filed") or record.get("end") or ""), title.strip()))
        records.sort(key=lambda item: item[0], reverse=True)
        for _filed, title in records:
            if title not in seen:
                seen.add(title)
                titles.append(title)
    return titles


def _xml_localname(tag):
    """Return the local name of an XML tag, ignoring the namespace."""
    if isinstance(tag, str) and tag:
        return tag.rsplit("}", 1)[-1]
    return str(tag or "")


def parse_dei_instrument_titles(instance_xml, known_symbols=None):
    """Parse dei security titles out of a filing XBRL instance document.

    SEC's companyfacts JSON never carries ``dei:SecurityTitle`` /
    ``dei:Security12bTitle`` (only an allowlist of dei concepts), so the
    cover-page titles have to be read from the filing's financial-report
    instance (``*_htm.xml``). There each registered class reports, within the
    same period context, a ``dei:TradingSymbol`` and a dei security-title
    concept side by side, in document order:

    Returns:
        tuple: ``(pairs, titles)`` where ``pairs`` is a list of
        ``(symbol, title)`` tuples zipped by period (positional within the
        period, matching how SEC enumerated the classes on the cover) and
        ``titles`` is the flat list of every distinct title read (recency-
        ordered, canonical tag order), even when pairing was ambiguous.
    """
    pairs = []
    titles = []
    try:
        root = ET.fromstring(instance_xml or "")
    except ET.ParseError:
        return pairs, titles

    title_localnames = {name.partition(":")[2] for name in SECURITY_ATTRIBUTE_TAGS["security_name"]}

    end_dates = {}
    for context in root.iter():
        if _xml_localname(context.tag) != "context":
            continue
        context_id = context.get("id")
        if not context_id:
            continue
        for element in context.iter():
            # Cover dei facts sit under an *instant* context (the cover date);
            # duration facts would use endDate.
            if (
                _xml_localname(element.tag) in ("endDate", "instant")
                and element.text
                and element.text.strip()
            ):
                end_dates[context_id] = element.text.strip()
                break

    symbol_rows = []
    title_rows = []
    for element in root.iter():
        localname = _xml_localname(element.tag)
        if not isinstance(element.tag, str) or not element.tag.startswith("{"):
            continue
        value = (element.text or "").strip()
        if not value:
            continue
        end_date = end_dates.get(element.get("contextRef") or "")
        if localname == "TradingSymbol":
            symbol_rows.append((end_date, value))
        elif localname in title_localnames:
            title_rows.append((localname, end_date, value))

    seen_titles = set()
    for _localname, _end_date, value in title_rows:
        if value not in seen_titles:
            seen_titles.add(value)
            titles.append(value)

    # Pair TradingSymbol <-> security title per period context (both are
    # declared per registered class on the cover, in the same document order).
    all_periods = {end_date for end_date, _value in symbol_rows if end_date} | {
        end_date for _localname, end_date, _value in title_rows if end_date
    }
    for period_end in sorted(all_periods, key=str, reverse=True):
        period_symbols = [value for end_date, value in symbol_rows if end_date == period_end]
        period_titles = [
            value
            for localname, end_date, value in title_rows
            if end_date == period_end and localname in title_localnames
        ]
        clean_symbols = list(dict.fromkeys(period_symbols))
        clean_titles = list(dict.fromkeys(period_titles))
        if clean_symbols and len(clean_symbols) == len(clean_titles):
            for symbol, title in zip(clean_symbols, clean_titles):
                candidate = (str(symbol).upper(), title)
                if candidate not in pairs:
                    pairs.append(candidate)

    # Single-class fallback: one symbol and one title under one issuer.
    if not pairs and len(titles) == 1 and len(symbol_rows) >= 1:
        if known_symbols is not None:
            matched = [
                str(symbol).upper()
                for _end_date, symbol in symbol_rows
                if str(symbol).upper() in {str(s).upper() for s in known_symbols}
            ]
        else:
            matched = [str(symbol).upper() for _end_date, symbol in symbol_rows]
        if len(set(matched)) == 1:
            pairs.append((matched[0], titles[0]))

    return pairs, titles


def match_security_title(titles, security_type, fallback=None):
    """Pick the ``dei`` security title that belongs to a security row.

    ``classify_security_type`` infers a class from a title string, so a row of
    type ``preferred stock`` is matched to titles such as ``Series C Preferred
    Stock`` while a ``common_stock`` row is matched to ``Common Stock``. Returns
    a title only when exactly one candidate matches; otherwise returns
    ``fallback`` rather than attributing another series title to this security.
    """
    candidates = [title for title in titles if title and title.strip()]
    if not candidates:
        return fallback
    normalized_type = normalize_security_type(security_type)
    matched = [title for title in candidates if classify_security_type(title) == normalized_type]
    if len(matched) == 1:
        return matched[0].strip()
    return fallback


def classify_companyfacts(companyfacts, *, as_of=None, lookback_days=DIVIDEND_RECENCY_DAYS):
    """Classify an issuer from SEC XBRL tags and positive reported values.

    A concept only proves a *current* dividend payer when its positive records
    are recent. ``lookback_days`` (default ``DIVIDEND_RECENCY_DAYS``) bounds the
    evidence: facts whose period ``end`` falls on or after
    ``as_of - lookback_days`` are considered live, and anything older is
    ignored. Pass ``as_of`` to make the cut deterministic in tests and replays;
    pass ``lookback_days=None`` to disable the bound entirely (any positive
    fact counts), which is what ``configured_dividend_lookback`` returns when
    enforcement is switched off.

    Dividend evidence is read from both the ``us-gaap`` and ``ifrs-full``
    taxonomies: foreign private issuers file IFRS, and their ``DividendsPaid*``
    concepts would otherwise be missed. Security-type classification stays on
    ``us-gaap`` only, because the IFRS concept vocabulary is not mapped into
    ``SECURITY_FACT_RULES``.

    Returns normalized security types, dividend status, the most recent
    qualifying dividend period end, de-registered security titles, and compact
    audit evidence suitable for storing in ``reference.securities``.
    """
    cutoff = (
        None if lookback_days is None else (as_of or date.today()) - timedelta(days=lookback_days)
    )
    cutoff_iso = cutoff.isoformat() if cutoff is not None else None
    # Upper bound for a *paid* dividend: the run date. cutoff_iso is the lower
    # bound (the lookback floor) and must not be used as the ceiling.
    today_iso = (as_of or date.today()).isoformat()
    payload = companyfacts.get("full_facts", companyfacts)
    taxonomies = _companyfacts_taxonomies(payload)
    us_gaap = taxonomies.get("us-gaap", {})
    # Foreign private issuers file IFRS, not us-gaap, and their dividends live
    # under ifrs-full concepts (DividendsPaidOrdinaryShares, ...). Scanning only
    # us-gaap made those issuers invisible unless a long-past us-gaap fact
    # happened to keep them flagged; with the recency bound that stale crutch is
    # gone, so the live IFRS evidence has to be read directly.
    dividend_taxonomies = [us_gaap]
    ifrs = taxonomies.get("ifrs-full")
    if ifrs:
        dividend_taxonomies.append(ifrs)
    security_types = set()
    security_facts = []
    dividend_facts = []
    dividend_last_paid = None

    for concept_name, concept in us_gaap.items():
        normalized_name = "".join(
            character for character in concept_name.lower() if character.isalnum()
        )
        matching_types = [
            security_type
            for security_type, terms in SECURITY_FACT_RULES.items()
            if any(term in normalized_name for term in terms)
        ]
        for security_type in matching_types:
            security_types.add(security_type)
            security_facts.append({"tag": concept_name, "security_type": security_type})

    for taxonomy in dividend_taxonomies:
        for concept_name, concept in taxonomy.items():
            normalized_name = "".join(
                character for character in concept_name.lower() if character.isalnum()
            )
            if not any(term in normalized_name for term in DIVIDEND_FACT_TERMS):
                continue
            positive_records = []
            for unit, record in _fact_values(concept):
                try:
                    is_positive = float(record.get("val", 0)) > 0
                except (TypeError, ValueError):
                    is_positive = False
                end = record.get("end")
                if not is_positive or not end or (cutoff_iso and str(end) < cutoff_iso):
                    continue
                positive_records.append(
                    {
                        "unit": unit,
                        "val": record.get("val"),
                        "end": end,
                        "filed": record.get("filed"),
                    }
                )
            if positive_records:
                # XBRL facts arrive in filing/payload order, not chronological
                # order, so the tail of the raw list was whichever five facts
                # happened to be listed last -- not the five most recent periods.
                # Sort by period end so the stored evidence is the latest window
                # and the audit trail agrees with dividend_last_paid.
                recent = sorted(positive_records, key=lambda record: str(record["end"]))
                dividend_facts.append({"tag": concept_name, "records": recent[-5:]})
                # A dividend cannot have been *paid* after today. The concept
                # list is deliberately broad (any us-gaap tag mentioning
                # "dividend"), so it picks up balance-sheet and forward-looking
                # tags whose period end is in the future --
                # DividendsPayableCurrentAndNoncurrent, and even
                # CashDividendsPaidToParentCompanyByConsolidatedSubsidiaries
                # filed against a future fiscal year end. Taking the raw maximum
                # published a paid date of 2108-11-14 (MTEX) and 2026-12-31.
                #
                # Excluding those tags instead is not a safe local fix: dropping
                # the payable/receivable/declared families flips the dividend
                # flag off for 3,611 of 8,105 cached CIKs, which is a universe
                # change requiring a reference-stage rebuild. Clamping the date
                # to today fixes the anomaly without moving the flag, and the
                # future-dated evidence stays in dividend_facts for an auditor.
                latest = str(recent[-1]["end"])
                if latest > today_iso:
                    latest = today_iso
                if dividend_last_paid is None or latest > dividend_last_paid:
                    dividend_last_paid = latest

    if "other_equity" in security_types and "other_debt" in security_types:
        security_types.discard("other_equity")
        security_types.discard("other_debt")
        security_types.add("other_debt_and_equity")
    if not security_types:
        security_types.add("other")

    return {
        "security_types": sorted(normalize_security_type(t) for t in security_types),
        "dividend": bool(dividend_facts),
        "dividend_last_paid": dividend_last_paid,
        "dividend_lookback_start": cutoff_iso,
        "security_titles": extract_security_titles(companyfacts),
        "security_facts": security_facts,
        "dividend_facts": dividend_facts,
        "status": "available",
    }


def configured_dividend_lookback():
    """Dividend recency window from settings, or ``None`` when not enforced.

    Enforcement is opt-in via ``ENFORCE_DIVIDEND_RECENCY`` so an unattended
    nightly ETL cannot silently change the dividend universe. Production
    classification callers pass this to ``classify_companyfacts``; direct
    callers keep the bounded ``DIVIDEND_RECENCY_DAYS`` default.
    """
    if not settings.enforce_dividend_recency:
        return None
    return settings.dividend_recency_days


def _latest_positive_fact(us_gaap, concept_names):
    """Return the most recent positive-valued record across candidate XBRL concepts.

    SEC XBRL exposes the same economic fact under several near-equivalent
    tags (e.g. ``...LiquidationPreference`` vs ``...LiquidationPreferenceValue``),
    and companies restate values across filing periods, so concepts are tried
    in priority order and the record with the latest ``end`` date wins.
    """
    best = None
    for concept_name in concept_names:
        concept = us_gaap.get(concept_name) if isinstance(us_gaap, dict) else None
        if not isinstance(concept, dict):
            continue
        for _unit, record in _fact_values(concept):
            try:
                value = float(record.get("val"))
            except (TypeError, ValueError):
                continue
            if value <= 0:
                continue
            end = record.get("end") or ""
            if best is None or end > best[0]:
                best = (end, value)
        if best is not None:
            break
    return best[1] if best else None


def extract_preferred_terms_from_companyfacts(companyfacts):
    """Extract preferred-stock terms directly from SEC Company Facts XBRL tags.

    Complements ``classify_companyfacts`` (which only flags dividend/security
    type) by reading numeric coupon and liquidation-preference facts, so
    ``raw.ticker_profile`` can be populated from the authoritative SEC source
    instead of relying solely on Yahoo/OpenBB or name-based text parsing.

    Returns a dict with ``coupon_rate`` and ``liquidation_preference`` keys,
    either of which may be ``None`` if the issuer never reported the concept.
    """
    payload = companyfacts.get("full_facts", companyfacts)
    us_gaap = _companyfacts_taxonomies(payload).get("us-gaap", {})

    coupon_rate = _latest_positive_fact(us_gaap, PREFERRED_COUPON_CONCEPTS)
    if coupon_rate is not None and coupon_rate < 1:
        # XBRL percentItemType values are reported as decimals (e.g. 0.08625).
        coupon_rate *= 100

    liquidation_preference = _latest_positive_fact(us_gaap, PREFERRED_LIQUIDATION_CONCEPTS)
    if liquidation_preference is None:
        liquidation_preference = _latest_positive_fact(us_gaap, PREFERRED_PAR_VALUE_CONCEPTS)

    return {
        "coupon_rate": coupon_rate,
        "liquidation_preference": liquidation_preference,
    }


def filing_url(cik, accession_no, primary_document):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no.replace('-', '')}/{primary_document}"


def fetch_filing(url):
    r = SEC_SESSION.get(
        url,
        headers=HEADERS,
        timeout=(10, 30),
    )
    r.raise_for_status()
    text = BeautifulSoup(r.text, "lxml").get_text(" ", strip=True)
    return text, hashlib.sha256(text.encode()).hexdigest()


def fetch_filing_xml(url):
    """Fetch a filing document as raw text (kept intact for XBRL parsing).

    Unlike :func:`fetch_filing`, this never HTML-strips the body, because dei
    security titles have to be read from the raw XML of a financial-report
    instance (``*_htm.xml``).
    """
    r = SEC_SESSION.get(url, headers=HEADERS, timeout=(20, 60))
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    raw = r.text
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_archive_index_html(html):
    """Parse a SEC filing index page (``<accession>-index.htm``) into document rows.

    Returns a list of ``(description, name, type)`` tuples from the "Document
    Format Files" table. Rows without a real file name (headers, section
    separators, the "Complete submission text file" row) are skipped.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
            if len(cells) < 4:
                continue
            description, name, item_type = cells[-4], cells[-3], cells[-2]
            if "/" in name or "." not in name:
                continue
            items.append((description, name, item_type))
    return items


def _parse_archive_directory_html(html):
    """Parse the plain EDGAR archive directory listing into document rows."""
    soup = BeautifulSoup(html, "lxml")
    items = []
    for link in soup.find_all("a", href=True):
        name = (link.get("href") or "").split("/")[-1]
        if name in ("", ".", "..") or "/" in name or "." not in name:
            continue
        if link.get_text(" ", strip=True) not in (".", ".."):
            items.append((link.get_text(" ", strip=True), name, "file"))
    return items


def fetch_archive_index(cik, accession_no):
    """List the documents in a filing's archive data directory.

    SEC no longer generates ``index.json`` for every filing (it 404s), so the
    filing index page (``<accession>-index.htm``) is the primary source; the
    plain directory listing is the fallback and the legacy ``index.json`` the
    last resort. Returns ``[(description, name, type), ...]`` or ``[]``.
    """
    archive = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no.replace('-', '')}"

    for url in (f"{archive}/{accession_no}-index.htm", f"{archive}/"):
        try:
            response = SEC_SESSION.get(url, headers=HEADERS, timeout=(10, 30))
            response.raise_for_status()
            items = (
                _parse_archive_index_html(response.text)
                if "index." in url
                else _parse_archive_directory_html(response.text)
            )
            if items:
                return items
        except requests.HTTPError:
            continue
        except Exception:
            continue

    try:
        index_response = SEC_SESSION.get(f"{archive}/index.json", headers=HEADERS, timeout=(10, 30))
        index_response.raise_for_status()
        files = index_response.json() or {}
        return [
            (
                str(item.get("description") or ""),
                str(item.get("name") or ""),
                str(item.get("type") or ""),
            )
            for item in files.get("directory", {}).get("item", []) or []
        ]
    except (requests.HTTPError, ValueError):
        return []


def filing_instance_url(cik, accession_no, primary_document):
    """URL of the XBRL financial-report instance for a filing.

    SEC names the live XBRL instance ``<stem>_htm.xml`` next to the primary
    HTML document (``<stem>.htm``). While most filers follow exactly that
    convention, the name can vary, so a failed guess falls back to scanning the
    filing's archive for an ``*_htm.xml`` / ``*.instance.xml`` file.
    """
    primary = (primary_document or "").strip()
    stem = primary
    for extension in (".htm", ".xml", ".html"):
        if stem.lower().endswith(extension):
            stem = stem[: -len(extension)]
            break
    if stem.lower().endswith("_htm"):
        stem = stem[:-4]
    candidate = f"{stem}_htm.xml"

    archive = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no.replace('-', '')}"
    url = f"{archive}/{candidate}"
    try:
        raw, _hash = fetch_filing_xml(url)
        return url, raw, _hash
    except requests.HTTPError:
        pass

    for _description, name, _item_type in fetch_archive_index(cik, accession_no):
        if (name.endswith("_htm.xml") or name.endswith(".instance.xml")) and "/" not in name:
            url = f"{archive}/{name}"
            try:
                raw, _hash = fetch_filing_xml(url)
                return url, raw, _hash
            except requests.HTTPError:
                continue

    return None, None, None


# def get_dividend_facts(cik):
#    """
#    Fetch dividend-related facts from SEC XBRL company facts API.

#    Args:
#        cik (int or str): Central Index Key

#    Returns:
#        dict: Company facts JSON with all reported values
#
#    Example:
#        >>> facts = get_dividend_facts(320193)  # Apple
#        >>> dividend_concepts = {k: v for k, v in facts.get('us-gaap', {}).items()
#        ...                     if 'dividend' in k.lower()}
#    """
#    return get_companyfacts(cik)


# def get_companyfacts_concepts(cik):
#   """
#   Fetch the full SEC XBRL companyfacts payload and return all concept families for a company.

#   This separates the raw SEC fetch from the normalized dividend loader and keeps the
#   full company facts available for later use in earnings, cash-flow, balance-sheet,
#   debt, tax, and share-count feature pipelines.
#   """
#   facts = get_companyfacts(cik)
#   if not isinstance(facts, dict):
#       return {
#           "cik": str(int(cik)).zfill(10),
#           "company": None,
#           "all_concepts": [],
#           "concept_groups": {
#               "dividends": [],
#               "earnings": [],
#               "cash_flow": [],
#               "balance_sheet": [],
#               "debt": [],
#               "tax": [],
#               "share_counts": [],
#           },
#           "full_facts": facts,
#       }

#   us_gaap = facts.get("us-gaap", {})
#   concept_names = sorted(us_gaap.keys())

#    groups = {
#        "dividends": [],
#        "earnings": [],
#        "cash_flow": [],
#        "balance_sheet": [],
#        "debt": [],
#        "tax": [],
#        "share_counts": [],
#   }

#   for concept_name in concept_names:
#        name_lower = concept_name.lower()

#       if "dividend" in name_lower:
#            groups["dividends"].append(concept_name)
#        if any(token in name_lower for token in ["earnings", "income", "eps", "profit", "margin"]):
#            groups["earnings"].append(concept_name)
#        if any(token in name_lower for token in ["cashflow", "cash_flow", "operatingcashflow", "freecashflow", "fcf"]):
#            groups["cash_flow"].append(concept_name)
#        if any(token in name_lower for token in ["asset", "liability", "equity", "balance", "shareholder"]):
#            groups["balance_sheet"].append(concept_name)
#        if any(token in name_lower for token in ["debt", "borrow", "liability", "notespayable", "longtermdebt"]):
#            groups["debt"].append(concept_name)
#        if "tax" in name_lower:
#           groups["tax"].append(concept_name)
#        if any(token in name_lower for token in ["share", "shares", "stock", "commonstock", "treasurystock"]):
#            groups["share_counts"].append(concept_name)

#    return {
#        "cik": str(int(cik)).zfill(10),
#        "company": facts.get("entityName"),
#        "all_concepts": concept_names,
#        "concept_groups": groups,
#        "full_facts": facts,
#    }


# def get_companyfacts_for_dividend_securities(tickers=None, limit=None):
#    """
#    Fetch the full SEC XBRL payload for securities that have dividend-related concepts.

#    This is the dedicated upstream process used before inserting into raw.dividend_data.
#    It returns a list of company fact payloads for securities with dividend concepts,
#    including all concept families for the company.
#    """
#    if tickers:
#        target_tickers = [t.strip().upper() for t in tickers if t and t.strip()]
#    else:
#       tickers_data = get_company_tickers()
#        target_tickers = [entry.get("ticker") for entry in tickers_data.values() if entry.get("ticker")]
#        if limit:
#            target_tickers = target_tickers[:limit]

#    results = []
#    for ticker in target_tickers:
#        cik = ticker_to_cik(ticker)
#        if cik is None:
#            continue

#        companyfacts = get_companyfacts_concepts(cik)
#        dividend_concepts = companyfacts["concept_groups"]["dividends"]
#        if dividend_concepts:
#            results.append({
#                "ticker": ticker,
#                "cik": cik,
#                "company": companyfacts["company"],
#                "dividend_concepts": dividend_concepts,
#                "concept_groups": companyfacts["concept_groups"],
#                "all_concepts": companyfacts["all_concepts"],
#                "full_facts": companyfacts["full_facts"],
#            })

#    return results


# def get_companyfacts_flow(cik):
#    """
#    Fetch the full SEC companyfacts payload for one company and summarize all concepts.

#    This is the authoritative SEC XBRL endpoint used before normalizing into
#    raw.dividend_data. It returns both the full concept map and the subset matching
#    dividend-related labels.
#    """
#    facts = get_companyfacts(cik)
#    us_gaap = facts.get("us-gaap", {}) if isinstance(facts, dict) else {}
#    concept_names = sorted(us_gaap.keys())
#   dividend_concepts = [
#        name for name in concept_names if "dividend" in name.lower()
#    ]
#
#    return {
#        "cik": str(int(cik)).zfill(10),
#        "entity_name": facts.get("entityName") if isinstance(facts, dict) else None,
#        "all_concepts": concept_names,
#        "dividend_concepts": dividend_concepts,
#        "full_facts": facts,
#        "dividend_rows": extract_dividend_data(cik, facts_json=facts),
#    }

#
# def companyfacts_flow_for_ticker(ticker):
#    """Resolve a ticker to CIK and inspect the SEC companyfacts payload for dividend concepts."""
#    cik = ticker_to_cik(ticker)
#    if cik is None:
#        return {"ticker": ticker.upper(), "cik": None, "error": "ticker_not_found"}
#    return get_companyfacts_flow(cik)
#
#
# def extract_dividend_data(cik, facts_json=None):
#    """
#    Extract dividend payments and declarations from XBRL company facts.
#
#    Args:
#        cik (int or str): Central Index Key
#        facts_json (dict): Pre-fetched company facts (optional, will fetch if not provided)
#
#    Returns:
#        list: List of dividend records with keys:
#            - ex_dividend_date, declaration_date, record_date, payment_date
#            - amount, frequency, currency
#
#    Searches for concepts:
#        - CommonStockDividendsPaid
#        - CommonStockDividendsPerShareDeclared
#        - PreferredStockDividendsPaid
#        - DividendsCashPaid
#    """
#    if facts_json is None:
#        try:
#            facts_json = get_dividend_facts(cik)
#        except Exception as e:
#            print(f"Error fetching facts for CIK {cik}: {e}")
#            return []
#
#    dividends = []
#    us_gaap = facts_json.get("us-gaap", {})
#
#    # Key dividend concepts to extract
#    dividend_concepts = [
#        "CommonStockDividendsPaid",
#        "CommonStockDividendsPerShareDeclared",
#        "PreferredStockDividendsPaid",
#        "DividendsCashPaid",
#        "DividendsCommonStockCash",
#        "StockIssuedDuringPeriodValueCommonStockDividends",
#    ]
#
#    for concept_name in dividend_concepts:
#        if concept_name not in us_gaap:
#            continue
#
#        concept_data = us_gaap[concept_name]
#        units = concept_data.get("units", {})
#
#        # Extract values from each unit (typically USD or shares)
#        for unit_type, unit_values in units.items():
#            if not isinstance(unit_values, list):
#                unit_values = [unit_values]
#
#            for record in unit_values:
#                if not isinstance(record, dict):
#                    continue
#
#                # Parse the record
#                dividend_record = {
#                    "cik": str(int(cik)).zfill(10),
#                    "concept": concept_name,
#                    "ex_dividend_date": record.get("end"),  # Filing end date as proxy
#                    "declaration_date": None,
#                    "record_date": None,
#                    "payment_date": record.get("end"),
#                    "amount": float(record.get("val", 0)),
#                    "frequency": "Annual",  # Default, could be enhanced
#                    "currency": "USD" if "USD" in unit_type else unit_type,
#                    "filed_date": record.get("filed"),
#                    "form": record.get("form", ""),
#                    "accn": record.get("accn", ""),
#                }
#
#                # Only include records with positive amounts
#                if dividend_record["amount"] > 0:
#                    dividends.append(dividend_record)
#
#    return dividends
#
# def get_all_dividend_data(limit=None, sample_tickers=None):
#    """
#    Fetch dividend data for companies from SEC XBRL API.
#
#    Args:
#        limit (int): Maximum number of companies to process (for testing)
#        sample_tickers (list): List of specific tickers to fetch (e.g., ['AAPL', 'MSFT'])
#
#    Returns:
#        list: Flattened list of all dividend records from all companies
#    """
#    if sample_tickers:
#        # Convert specific tickers to CIKs
#        ciks = []
#        for ticker in sample_tickers:
#            cik = ticker_to_cik(ticker)
#            if cik:
#                ciks.append(cik)
#    else:
#        # Get all tickers
#        tickers_data = get_company_tickers()
#        ciks = [entry.get("cik_str") for entry in tickers_data.values()]
#        if limit:
#            ciks = ciks[:limit]
#
#    all_dividends = []
#    errors = 0
#
#    for idx, cik in enumerate(ciks):
#        try:
#            dividends = extract_dividend_data(cik)
#            all_dividends.extend(dividends)
#
#            if (idx + 1) % 100 == 0:
#                print(f"Fetched dividend data for {idx + 1} companies ({len(all_dividends)} records)...")
#
#        except Exception as e:
#            errors += 1
#            if errors <= 5:
#                print(f"Error fetching dividends for CIK {cik}: {e}")
#            if errors > 10:
#                print("Too many errors, stopping dividend fetch.")
#                break
#
#    return all_dividends
#
