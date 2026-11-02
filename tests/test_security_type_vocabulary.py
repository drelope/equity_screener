"""Guard the canonical security_type vocabulary.

reference.securities.security_type is constrained by chk_securities_security_type
to SECURITY_TYPE_VOCABULARY. Every classifier that writes reference rows must
emit only members of that vocabulary, and sql/schema.sql + scripts/init_db.py
must keep their CHECK lists in sync with the tuple.
"""

from pathlib import Path

from src.crispdm.sec_client import (
    SymbolSuffix,
    classify_companyfacts,
    classify_instrument,
    classify_security_symbol,
    classify_security_type,
    match_security_title,
    parse_dei_instrument_titles,
    security_type_for_instrument,
    symbol_suffix_evidence,
)
from src.crispdm.xbrl_tags import (
    SECURITY_TYPE_ALIASES,
    SECURITY_TYPE_VOCABULARY,
    normalize_security_type,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _check_literal():
    sql_text = (PROJECT_ROOT / "sql" / "schema.sql").read_text()
    for line in sql_text.splitlines():
        if "CHECK (security_type IN (" in line:
            return line
    raise AssertionError("chk_securities_security_type not found in schema.sql")


def test_normalize_returns_canonical_members_only():
    samples = [
        "preferred stock",
        "Preferred Stock",
        "PreferredStock",
        "preferred",
        "common_stock",
        "Common Stock",
        "COMMON_STOCK",
        "government debt",
        "GovernmentDebt",
        "corporate bond",
        "debenture",
        "other_debt_and_equity",
        "other debt and equity",
        "other_debt",
        "option",
        "future",
        "derivative",
        "equity",
        "debt",
        "other_equity",
        "other",
        "Series C Preferred Stock (8.625% Fixed-to-Floating)",
        "",
        None,
    ]
    for sample in samples:
        assert normalize_security_type(sample) in SECURITY_TYPE_VOCABULARY, sample


def test_alias_targets_are_canonical():
    for alias, canonical in SECURITY_TYPE_ALIASES.items():
        assert canonical in SECURITY_TYPE_VOCABULARY, alias
        assert normalize_security_type(alias) == canonical


def test_classify_security_type_emits_canonical_only():
    titles = [
        "Apple Common Stock",
        "AT&T Preferred Shares",
        "Call Option",
        "Treasury Bill",
        "Series A Unit",
        "Loan Participation Certificate",
        "Warrant",
        "Bond",
        "Equity",
        "Unknown Instrument",
        "",
    ]
    for title in titles:
        result = classify_security_type(title)
        assert result in SECURITY_TYPE_VOCABULARY, (title, result)


def test_classify_companyfacts_emits_canonical_only():
    cases = [
        {
            "full_facts": {
                "us-gaap": {
                    "CommonStockSharesOutstanding": {
                        "units": {"shares": [{"val": 1, "end": "2026-01-01"}]}
                    }
                }
            }
        },
        {
            "full_facts": {
                "us-gaap": {
                    "PreferredStockSharesOutstanding": {
                        "units": {"shares": [{"val": 1, "end": "2026-01-01"}]}
                    }
                }
            }
        },
        {
            "full_facts": {
                "us-gaap": {
                    "WarrantsAndRightsOutstanding": {
                        "units": {"shares": [{"val": 1, "end": "2026-01-01"}]}
                    }
                }
            }
        },
        {"full_facts": {"us-gaap": {}}},
    ]
    for facts in cases:
        for security_type in classify_companyfacts(facts)["security_types"]:
            assert security_type in SECURITY_TYPE_VOCABULARY, security_type


def test_schema_check_list_matches_vocabulary():
    schema_text = (PROJECT_ROOT / "sql" / "schema.sql").read_text()
    start = schema_text.index("CHECK (security_type IN (")
    end = schema_text.index("))", start)
    block = schema_text[start + len("CHECK (security_type IN (") : end]
    schema_vocab = {" ".join(v.strip().strip("'").split()) for v in block.split(",") if v.strip()}
    assert schema_vocab == set(SECURITY_TYPE_VOCABULARY)


def test_init_db_check_list_matches_vocabulary():
    init_text = (PROJECT_ROOT / "scripts" / "init_db.py").read_text()
    start = init_text.index("CHECK (security_type IN (")
    end = init_text.index("))", start)
    block = init_text[start + len("CHECK (security_type IN (") : end]
    init_vocab = {" ".join(v.strip().strip("'").split()) for v in block.split(",") if v.strip()}
    assert init_vocab == set(SECURITY_TYPE_VOCABULARY)


#: The concept-bucket superset nearly every issuer reports, regardless of what
#: it actually lists. Used by the per-instrument resolution tests below.
SUPERSET_BAG = ["common_stock", "debt", "equity", "other", "preferred stock"]


def _classification(bag=SUPERSET_BAG, dividend_facts=None, security_titles=None):
    return {
        "security_types": list(bag),
        "security_titles": list(security_titles or []),
        "dividend_facts": [{"tag": tag} for tag in (dividend_facts or [])],
        "dividend": bool(dividend_facts),
        "status": "available",
    }


def test_classify_security_symbol_decodes_class_suffix():
    cases = {
        "ACR-PC": "preferred stock",
        "ACR-PD": "preferred stock",
        "JPM-PL": "preferred stock",
        "BRK-A": "common_stock",
        "BRK-B": "common_stock",
        "BF-B": "common_stock",
        "SHLD-W": "derivative",
        "BC-WS": "derivative",
        "ACR-U": "other_debt_and_equity",
        "ACR-R": "derivative",
        "AAPL": None,
        "ACR": None,
        "LFMDP": None,
    }
    for symbol, expected in cases.items():
        assert classify_security_symbol(symbol) == expected, symbol


def test_exact_cover_title_overrides_preferred_looking_debt_symbol():
    result = classify_instrument(
        "WRB-PE",
        _classification(),
        exact_dei_title="5.700% Subordinated Debentures due 2058",
    )
    assert result.security_type == "corporate bond"
    assert result.source == "dei_title"
    assert result.confidence == "high"
    assert result.conflicts == ["suffix:preferred stock overruled by exact title:corporate bond"]


def test_abbreviated_filed_preferred_title_is_recognized():
    title = (
        "Depositary Shrs, each representing 1/40th intrst in a shr "
        "of 5.875% Non-Cum. Perp Pref Stock, Srs E"
    )
    assert classify_security_type(title) == "preferred stock"
    assert (
        classify_security_type("Depository Shrs representing preferred equity") == "preferred stock"
    )
    assert classify_security_type("Series A Preference Units") == "preferred stock"
    assert classify_security_type("9% Series A Preferred Units") == "preferred stock"
    assert (
        classify_security_type(
            "Dep Shs, represent 1/1,000th interest in a share of 6.250% Noncum Pref Stk, Ser II"
        )
        == "preferred stock"
    )


def test_exact_common_title_beats_issuer_preferred_concept_bag():
    result = classify_instrument(
        "CMII",
        _classification(bag=["preferred stock"]),
        exact_dei_title="Class A Ordinary Shares, par value $0.0001 per share",
    )
    assert result.security_type == "common_stock"
    assert result.matched_title == "Class A Ordinary Shares, par value $0.0001 per share"


def test_unrecognized_exact_title_preserves_suffix_classification():
    result = classify_instrument("ACR-PD", _classification(), exact_dei_title="ACRES")
    assert result.security_type == "preferred stock"
    assert result.source == "symbol_suffix"


def test_security_type_for_instrument_suffix_wins_over_bag():
    assert (
        security_type_for_instrument("ACR-PC", "ACRES Commercial Realty Corp.", _classification())
        == "preferred stock"
    )
    assert (
        security_type_for_instrument("BRK-B", "BERKSHIRE HATHAWAY INC", _classification())
        == "common_stock"
    )


def test_security_type_for_instrument_title_beats_concept_bag():
    classification = _classification()
    assert (
        security_type_for_instrument("FOO", "Apple Inc. Common Stock", classification)
        == "common_stock"
    )
    assert (
        security_type_for_instrument("FOO", "Series A Preferred Stock", classification)
        == "preferred stock"
    )


def test_security_type_for_instrument_collapses_bag_to_single_type():
    classification = _classification()
    assert (
        security_type_for_instrument("AACG", "ATA Creativity Global", classification)
        == "common_stock"
    )
    result = security_type_for_instrument("FOO", "Some Issuer Inc.", _classification())
    assert result in SECURITY_TYPE_VOCABULARY
    assert result == "common_stock"


def test_security_type_for_instrument_dividend_evidence_discriminates():
    common_only = _classification(dividend_facts=["CommonStockDividendsPerShareDeclared"])
    preferred_only = _classification(dividend_facts=["PreferredStockDividendsPerShare"])
    assert (
        security_type_for_instrument("LFMDP", "Lazard Growth Acquisition Corp", common_only)
        == "common_stock"
    )
    assert (
        security_type_for_instrument("LFMDP", "Lazard Growth Acquisition Corp", preferred_only)
        == "preferred stock"
    )


def test_security_type_for_instrument_prefers_dei_titles():
    classification = _classification(
        security_titles=["Common Stock", "Series A Perpetual Preferred Stock"]
    )
    preferred = _classification(security_titles=["Series A Perpetual Preferred Stock"])
    assert (
        security_type_for_instrument("WCC-A", "WESCO International Inc", preferred)
        == "preferred stock"
    )
    assert security_type_for_instrument("FOO", "Some Issuer", classification) == "common_stock"


#: Parallel tickers[]/exchanges[] snapshot modeled on the SEC submissions payload.
ACRES_SUBMISSIONS = {
    "symbols": {"ACR", "ACR-PC", "ACR-PD"},
    "exchange_by_symbol": {"ACR": "nasdaq", "ACR-PC": "nasdaq", "ACR-PD": "nasdaq"},
    "order": ["ACR", "ACR-PC", "ACR-PD"],
}

ACRES_TITLES = [
    "Common Stock",
    "Series C Preferred Stock",
    "Series D Preferred Stock",
]


def _instrument(symbol, name, classification=None, dei=None, submissions=None):
    return classify_instrument(
        symbol,
        classification or _classification(),
        dei_titles=dei,
        submissions=submissions,
        issuer_name=name,
    )


def test_symbol_suffix_evidence_parses_series_letter():
    assert symbol_suffix_evidence("ACR-PC") == SymbolSuffix("preferred stock", "PC", "C")
    assert symbol_suffix_evidence("BRK-B") == SymbolSuffix("common_stock", "B", "B")
    assert symbol_suffix_evidence("SHLD-W").security_type == "derivative"
    assert symbol_suffix_evidence("ACR-U").security_type == "other_debt_and_equity"
    assert symbol_suffix_evidence("LFMDP") is None


def test_classify_instrument_acres_trio():
    assert (
        _instrument(
            "ACR-PC",
            "ACRES Commercial Realty Corp.",
            dei=ACRES_TITLES,
            submissions=ACRES_SUBMISSIONS,
        ).security_type
        == "preferred stock"
    )
    assert (
        _instrument(
            "ACR-PD",
            "ACRES Commercial Realty Corp.",
            dei=ACRES_TITLES,
            submissions=ACRES_SUBMISSIONS,
        ).security_type
        == "preferred stock"
    )
    decided = _instrument(
        "ACR", "ACRES Commercial Realty Corp.", dei=ACRES_TITLES, submissions=ACRES_SUBMISSIONS
    )
    assert decided.security_type == "common_stock"
    assert decided.source == "submissions_leading"


def test_classify_instrument_series_bound_title_overrides_dash_common():
    decided = _instrument(
        "WCC-A",
        "WESCO International Inc",
        dei=["Series A Perpetual Preferred Stock"],
    )
    assert decided.security_type == "preferred stock"
    assert decided.source == "dei_title"
    assert decided.confidence == "high"
    assert decided.matched_title == "Series A Perpetual Preferred Stock"


#: Real dei cover titles stored in raw.sec_instrument_titles for CIK 0001332551
#: (ACRES Commercial Realty). The preferred classes carry SEC cover symbols
#: ACRPRC/ACRPRD, so populate_reference_tables falls back to the CIK title list
#: and relies on series-letter binding to pick each class's own cover title.
ACRES_COVER_TITLES = [
    "Common Stock, $0.001 par value",
    "8.625% Fixed-to-Floating Series C Cumulative Redeemable Preferred Stock",
    "7.875% Series D Cumulative Redeemable Preferred Stock",
]


def test_classify_instrument_cover_titles_bind_preferred_series():
    decided_pc = _instrument("ACR-PC", "ACRES Commercial Realty Corp.", dei=ACRES_COVER_TITLES)
    decided_pd = _instrument("ACR-PD", "ACRES Commercial Realty Corp.", dei=ACRES_COVER_TITLES)
    assert decided_pc.security_type == "preferred stock"
    assert (
        decided_pc.matched_title
        == "8.625% Fixed-to-Floating Series C Cumulative Redeemable Preferred Stock"
    )
    assert decided_pd.security_type == "preferred stock"
    assert decided_pd.matched_title == "7.875% Series D Cumulative Redeemable Preferred Stock"
    bare_type_match = match_security_title(ACRES_COVER_TITLES, "preferred stock")
    assert bare_type_match is None
    assert decided_pd.matched_title not in (None, bare_type_match)


def test_match_security_title_returns_only_unambiguous_match():
    assert (
        match_security_title(
            ["Series D Preferred Stock", "Series E Preferred Stock"],
            "preferred stock",
        )
        is None
    )
    assert (
        match_security_title(["Common Stock", "Series D Preferred Stock"], "preferred stock")
        == "Series D Preferred Stock"
    )
    assert match_security_title(["Arbor Realty Trust, Inc."], "preferred stock") is None
    assert match_security_title(["Common Stock"], "other_equity") is None


def test_classify_instrument_brk_class_letter_binds_title():
    decided = _instrument(
        "BRK-B",
        "BERKSHIRE HATHAWAY INC",
        dei=["Class A", "Class B"],
        submissions={"order": ["BRK-A", "BRK-B"], "exchange_by_symbol": {}},
    )
    assert decided.security_type == "common_stock"
    assert decided.matched_title == "Class B"


def test_classify_instrument_submissions_mismatch_noted():
    decided = _instrument(
        "NOPE", "Some Issuer Inc", dei=["Common Stock"], submissions=ACRES_SUBMISSIONS
    )
    signals = [item["signal"] for item in decided.evidence]
    assert "submissions_mismatch" in signals
    assert decided.submissions["anchor_ok"] is True
    assert decided.submissions["in_tickers"] is False


def test_classify_instrument_dashless_preferred_via_dei_title():
    decided = _instrument(
        "LFMDP",
        "LifeMD, Inc.",
        dei=["Series A Cumulative Perpetual Preferred Stock"],
    )
    assert decided.security_type == "preferred stock"
    assert decided.source == "dei_title"


def test_classify_instrument_dividend_facts_preferred():
    classification = _classification(dividend_facts=["PreferredStockDividendsPerShare"])
    decided = _instrument("LFMDP", "Lazard Growth Acquisition Corp", classification=classification)
    assert decided.security_type == "preferred stock"
    assert decided.source == "dividend_facts"


def test_classify_instrument_primary_symbol_is_common_despite_preferred_dividends():
    classification = _classification(dividend_facts=["PreferredStockDividendsPerShare"])
    submissions = {"order": ["CNDT"], "exchange_by_symbol": {"CNDT": "nasdaq"}}
    decided = _instrument(
        "CNDT", "Conduent Inc", classification=classification, submissions=submissions
    )
    assert decided.security_type == "common_stock"
    assert decided.source == "submissions_primary"


def test_classify_instrument_non_primary_symbol_keeps_preferred_dividend_reading():
    classification = _classification(dividend_facts=["PreferredStockDividendsPerShare"])
    submissions = {"order": ["CHSCP", "CHSCL"], "exchange_by_symbol": {}}
    decided = _instrument(
        "CHSCL", "CHS Inc", classification=classification, submissions=submissions
    )
    assert decided.security_type == "preferred stock"
    assert decided.source == "dividend_facts"


def test_classify_instrument_primary_symbol_ignores_issuer_name_preferred_hint():
    """A "Preferred & Income Fund" name describes the issuer, not its common share."""
    submissions = {"order": ["JPC"], "exchange_by_symbol": {}}
    decided = _instrument(
        "JPC", "Nuveen Preferred & Income Opportunities Fund", submissions=submissions
    )
    assert decided.security_type == "common_stock"


def test_classify_instrument_primary_symbol_ignores_preferred_only_concept_bag():
    classification = _classification(bag=["preferred stock"])
    primary = _instrument(
        "JPC",
        "Nuveen Fund",
        classification=classification,
        submissions={"order": ["JPC"], "exchange_by_symbol": {}},
    )
    assert primary.security_type == "common_stock"
    assert primary.source == "submissions_primary"
    sibling = _instrument(
        "JPCX",
        "Nuveen Fund",
        classification=classification,
        submissions={"order": ["JPC", "JPCX"], "exchange_by_symbol": {}},
    )
    assert sibling.security_type == "preferred stock"
    assert sibling.source == "concept_bag"
    decided = _instrument("ZZZZ", "Nowhere Inc", classification={"status": "unavailable"})
    assert decided.security_type == "other"
    assert decided.source == "unavailable"


def test_classify_instrument_conflict_recorded():
    decided = _instrument(
        "XYZ-B",
        "Strange Issuer",
        dei=["Series A Perpetual Preferred Stock"],
    )
    assert decided.conflicts
    assert any("suffix" in conflict for conflict in decided.conflicts)


def test_classify_instrument_bag_fallback_common():
    decided = _instrument("AACG", "ATA Creativity Global")
    assert decided.security_type == "common_stock"
    assert decided.source == "concept_bag"


def test_classify_instrument_evidence_is_ordered():
    decided = _instrument(
        "ACR", "ACRES Commercial Realty Corp.", dei=ACRES_TITLES, submissions=ACRES_SUBMISSIONS
    )
    phases = [item["phase"] for item in decided.evidence]
    assert phases == sorted(phases)


# --- dei title ingestion from filing XBRL instances --------------------------


def _dei_instance_xml(pairs, period="2024-12-31"):
    """Build a minimal financial-report instance (*_htm.xml) snippet.

    Mirrors how SEC serializes the cover dei facts: each registered class gets
    a context (instant = cover date) and a contiguous block of
    ``dei:TradingSymbol`` + ``dei:Security12bTitle`` values.
    """
    contexts = []
    facts = []
    for index, (symbol, title) in enumerate(pairs, start=1):
        contexts.append(f"""    <xbrli:context id="c{index}">
      <xbrli:entity>
        <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000123</xbrli:identifier>
      </xbrli:entity>
      <xbrli:period><xbrli:instant>{period}</xbrli:instant></xbrli:period>
    </xbrli:context>""")
        facts.append(
            f'    <dei:TradingSymbol contextRef="c{index}">{symbol}</dei:TradingSymbol>\n'
            f'    <dei:Security12bTitle contextRef="c{index}">{title}</dei:Security12bTitle>'
        )
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        'xmlns:dei="http://xbrl.sec.gov/dei/2024Q1">\n'
    )
    return header + "\n".join(contexts) + "\n" + "\n".join(facts) + "\n</xbrli:xbrl>"


ACRES_INSTANCE = _dei_instance_xml(
    [
        ("ACR", "Common Stock, par value $0.01 per share"),
        (
            "ACR-PC",
            "8.50% Series C Cumulative Redeemable Preferred Stock, par value $0.01 per share",
        ),
        (
            "ACR-PD",
            "8.25% Series D Cumulative Redeemable Preferred Stock, par value $0.01 per share",
        ),
    ]
)

AAPL_INSTANCE = _dei_instance_xml([("AAPL", "Common Stock, $0.00001 par value per share")])


def test_parse_dei_instrument_titles_pairs_multi_class():
    pairs, titles = parse_dei_instrument_titles(ACRES_INSTANCE)
    assert pairs == [
        ("ACR", "Common Stock, par value $0.01 per share"),
        (
            "ACR-PC",
            "8.50% Series C Cumulative Redeemable Preferred Stock, par value $0.01 per share",
        ),
        (
            "ACR-PD",
            "8.25% Series D Cumulative Redeemable Preferred Stock, par value $0.01 per share",
        ),
    ]
    assert "Common Stock, par value $0.01 per share" in titles
    assert len(titles) == 3


def test_parse_dei_instrument_titles_single_class_pairs():
    pairs, titles = parse_dei_instrument_titles(AAPL_INSTANCE)
    assert pairs == [("AAPL", "Common Stock, $0.00001 par value per share")]
    assert titles == ["Common Stock, $0.00001 par value per share"]


def test_parse_dei_instrument_titles_contexts_disambiguate_identical_titles():
    xml = _dei_instance_xml(
        [
            ("AA", "Common Stock"),
            ("AA-B", "Common Stock"),
        ]
    )
    pairs, titles = parse_dei_instrument_titles(xml)
    assert pairs == [("AA", "Common Stock"), ("AA-B", "Common Stock")]
    assert titles == ["Common Stock"]


def test_parse_dei_instrument_titles_unparseable():
    assert parse_dei_instrument_titles("<not-xml") == ([], [])
    assert parse_dei_instrument_titles("") == ([], [])


def test_parse_dei_instrument_titles_known_symbols_fallback():
    xml = _dei_instance_xml([("ACR", "Common Stock, $0.01 par value")])
    pairs, titles = parse_dei_instrument_titles(xml, known_symbols=["ACR", "ACR-PC"])
    assert pairs == [("ACR", "Common Stock, $0.01 par value")]
    assert titles == ["Common Stock, $0.01 par value"]


def test_classify_instrument_exact_dei_title_hits_common():
    decided = _instrument(
        "AAPL",
        "APPLE INC",
        classification=_classification(dividend_facts=["CommonStockDividendsPerShareDeclared"]),
        dei=["Common Stock, $0.00001 par value per share"],
        submissions={"order": ["AAPL"], "exchange_by_symbol": {"AAPL": "Nasdaq"}},
    )
    assert decided.security_type == "common_stock"
    assert decided.source == "dei_title"
    assert decided.confidence == "high"
    assert decided.matched_title == "Common Stock, $0.00001 par value per share"


def test_classify_instrument_exact_dei_title_series_binds_suffix():
    decided = _instrument(
        "ACR-PC",
        "ACRES Commercial Realty Corp.",
        dei=["8.50% Series C Cumulative Redeemable Preferred Stock, par value $0.01 per share"],
    )
    assert decided.security_type == "preferred stock"
    # Phase 1 (suffix) still decides, but the exact cover title is attached.
    assert decided.source == "symbol_suffix"
    assert decided.matched_title == (
        "8.50% Series C Cumulative Redeemable Preferred Stock, par value $0.01 per share"
    )


def test_subordinated_notes_without_a_maturity_are_bonds_not_other():
    """Prudential's 4.125% Junior Subordinated Notes (PFH) carry no 'due' date, so they fell
    through to 'other' and the issuer's common-stock tag typed the ticker common."""
    from src.crispdm.sec_client import classify_security_type

    for title in (
        "4.125% Junior Subordinated Notes",
        "4.625% Perpetual Subordinated Notes",
        "9.000% Subordinated Notes, par value $25.00",
        "Senior Notes",
        "6.75% Notes",
    ):
        assert classify_security_type(title) == "corporate bond", title


def test_the_notes_pattern_does_not_capture_equity_or_other_instruments():
    from src.crispdm.sec_client import classify_security_type

    assert classify_security_type("Common Stock, par value $0.01 per share") == "common_stock"
    assert classify_security_type("6.25% Series A Cumulative Preferred Stock") == "preferred stock"
    assert classify_security_type("Notes receivable") == "other"  # no ranking word or coupon
    assert classify_security_type("Class A common stock; footnotes") == "common_stock"
    assert classify_security_type("Warrants to purchase subordinated notes") == "derivative"
    assert classify_security_type("Depositary Shares each representing a subordinated note") == (
        "preferred stock"
    )


def test_stray_spacing_in_a_cover_title_does_not_defeat_the_phrase_match():
    """XBRL cover titles arrive as "Common     Stock"; the substring match for 'common stock'
    failed and a common stock dropped to a generic equity."""
    from src.crispdm.sec_client import classify_security_type

    assert classify_security_type("Common     Stock, par value $0.01 per share") == "common_stock"
    assert classify_security_type("Common\u00a0Shares of Beneficial Interest") == "common_stock"
    assert classify_security_type("Class A\n  common stock") == "common_stock"


def test_a_spac_unit_is_a_unit_not_a_warrant():
    from src.crispdm.sec_client import classify_security_type

    for title in (
        "Units, each consisting of one Class A ordinary share and one redeemable warrant",
        "Units,     each consisting of one Class A ordinary share and one right",
        "Units, each comprised of one share of common stock and one-half of one warrant",
    ):
        assert classify_security_type(title) == "other_debt_and_equity", title
    # a bare warrant or right is still a derivative
    assert classify_security_type("Redeemable warrants, each exercisable for one share") == (
        "derivative"
    )
    assert classify_security_type("Rights to receive one-tenth of one share") == "derivative"


def test_american_depositary_shares_are_common_receipts_not_preferred():
    from src.crispdm.sec_client import classify_security_type

    for title in (
        "American Depositary Shares",
        "American Depositary Shares, each representing two ordinary shares",
        "Depositary shares, each representing one share of common stock",
        "Petrobras American Depositary Shares, or ADSs",
        "Class A Ordinary Shares represented by American Depositary Shares",
    ):
        assert classify_security_type(title) == "common_stock", title


def test_preferred_depositary_shares_are_still_preferred():
    from src.crispdm.sec_client import classify_security_type

    for title in (
        "Depositary Shares, each representing a 1/1,000th interest in a share of Series A "
        "Non-Cumulative Preferred Stock",
        "American Depositary Shares each representing one Series B Preferred Share",
        "Depositary Shares each representing 1/40th of a share of Fixed-Rate Preferred Stock",
        "Depositary shrs, each representing a fractional interest",
    ):
        assert classify_security_type(title) == "preferred stock", title
