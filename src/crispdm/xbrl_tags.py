"""Canonical SEC XBRL / Inline XBRL (iXBRL) tag registry for the dividend pipeline.

Every attribute stored in the dividend tables (raw.dividend_data,
raw.ticker_profile, preferred.security_terms, preferred.dividend_snapshot and
the raw issuer-payload tables) maps to one or more SEC XBRL / Inline XBRL
filing tags.  Keeping that map in a single module lets the database schema
comments, the ETL extractors, the fact classifiers, and the taxonomy loaders
stay in sync, so the same normalized economic fact is never re-loaded under a
different name or a different table.

Tag prefixes
------------
- ``dei``      : Document and Entity Information taxonomy (issuer metadata).
- ``us-gaap``  : US GAAP taxonomy (facts, including dividend concepts).
- ``srt``      : Standard registrant taxonomy (e.g. security CUSIP).
- ``ifrs-full``: IFRS taxonomy (supported, no preferred-stock concepts).

The registry records the *canonical* tag for each fact.  SEC exposes the same
economic amount under several near-equivalent tags (e.g.
``PreferredStockLiquidationPreference`` vs
``PreferredStockLiquidationPreferenceValue``); the first tag in each tuple is
the preferred one and the remaining tags are fallbacks tried in order.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Security / issuer-reference attributes (reference.securities, reference.issuers)
# --------------------------------------------------------------------------

#: Column name -> ordered XBRL / iXBRL tags that carry the fact. ``issuer_name``
#: lives on reference.issuers (dei:EntityRegistrantName); the rest are
#: reference.securities columns.
SECURITY_ATTRIBUTE_TAGS: dict[str, tuple[str, ...]] = {
    "ticker": ("dei:TradingSymbol",),
    "cik": ("dei:EntityCentralIndexKey",),
    "issuer_name": ("dei:EntityRegistrantName",),
    "security_name": ("dei:SecurityTitle", "dei:Security12bTitle"),
    "cusip": ("us-gaap:CUSIP", "us-gaap:DebtInstrumentCusip"),
    "isin": ("us-gaap:ISIN", "srt:ISIN"),
    "coupon_rate": (
        "us-gaap:PreferredStockDividendRatePercentage",
        "us-gaap:PreferredStockDividendRatePerAnnum",
    ),
    "liquidation_preference": (
        "us-gaap:PreferredStockLiquidationPreferenceValue",
        "us-gaap:PreferredStockLiquidationPreference",
        "us-gaap:TemporaryEquityLiquidationPreferenceValue",
        "us-gaap:TemporaryEquityLiquidationPreference",
    ),
}

#: Canonical security_type vocabulary shared by reference.securities and every
#: classifier in the pipeline. The ``chk_securities_security_type`` CHECK in
#: sql/schema.sql and scripts/init_db.py must stay exactly in sync with this
#: tuple (a pytest guards the match). Free-text series labels (e.g. ``Series C
#: Preferred Stock (8.625% Fixed-to-Floating)``) are allowed in
#: ``raw.ticker_profile.security_type`` and are reported by
#: ``extract_security_series``; they are NOT a member of this vocabulary.
SECURITY_TYPE_VOCABULARY: tuple[str, ...] = (
    "common_stock",
    "preferred stock",
    "debt",
    "equity",
    "other_equity",
    "other_debt",
    "option",
    "future",
    "derivative",
    "government debt",
    "corporate bond",
    "other_debt_and_equity",
    "other",
)

#: Aliases -> canonical security_type used by :func:`normalize_security_type`
#: so renamed or loosely-tagged values never leak into reference.securities
#: (whose CHECK only accepts members of :data:`SECURITY_TYPE_VOCABULARY`).
SECURITY_TYPE_ALIASES: dict[str, str] = {
    "preferred": "preferred stock",
    "preferred_stock": "preferred stock",
    "preferred_share": "preferred stock",
    "common": "common_stock",
    "common_stock": "common_stock",
    "common_stock_equity": "common_stock",
    "equity_common": "common_stock",
    "debenture": "corporate bond",
    "corporate": "corporate bond",
    "govt_debt": "government debt",
}


def normalize_security_type(value) -> str:
    """Return the canonical security_type for ``value``.

    Falls back to ``"other"`` for unrecognized free text, so a classifier or
    writer can always safely feed the result into ``reference.securities``.
    """
    if value is None:
        return "other"
    normalized = str(value).strip().lower().replace("-", " ").replace("_", " ")
    normalized = " ".join(normalized.split())
    if not normalized:
        return "other"
    for alias, canonical in SECURITY_TYPE_ALIASES.items():
        alias_key = alias.replace("_", " ").replace("-", " ")
        if normalized == alias_key:
            return canonical
    if "preferred" in normalized:
        return "preferred stock"
    if "common share" in normalized or "ordinary share" in normalized:
        return "common_stock"
    if normalized in SECURITY_TYPE_VOCABULARY:
        return normalized
    return "other"


#: Tags used to infer the security class from an issuer's XBRL facts.
SECURITY_FACT_RULES: dict[str, tuple[str, ...]] = {
    "common_stock": ("commonstock", "commonshares", "commonstockvalue"),
    "preferred stock": ("preferredstock", "preferredshares"),
    "debt": ("debt", "borrowings", "notespayable", "debenture", "bond"),
    "equity": ("stockholdersequity", "shareholdersequity", "equity"),
    "other_equity": ("warrant", "right", "unit"),
    "other_debt": ("commercialpaper", "assetbacked", "loanparticipation"),
}

#: Substrings that, when present in a normalized us-gaap concept name, prove a
#: security pays a dividend / owner distribution.
DIVIDEND_FACT_TERMS: tuple[str, ...] = (
    "dividend",
    "distributionstoowners",
)

# --------------------------------------------------------------------------
# Dividend event attributes (raw.dividend_data)
# --------------------------------------------------------------------------

#: Column name -> the dividend concept unit and the canonical per-share tags.
#: ``*DividendsPerShare*`` facts are the canonical per-share dividend amounts.
DIVIDEND_EVENT_ATTRIBUTE_TAGS: dict[str, tuple[str, ...]] = {
    "amount": (
        "us-gaap:CommonStockDividendsPerShareDeclared",
        "us-gaap:CommonStockDividendsPerShareCashPaid",
        "us-gaap:PreferredStockDividendsPerShare",
        # Aggregate fallbacks (dollars, not per-share) kept only for
        # instruments that never report a per-share declaration.
        "us-gaap:DividendsCommonStockCash",
        "us-gaap:PaymentsOfDividendsCommonStock",
        "us-gaap:PaymentsOfDividendsPreferredStock",
        "us-gaap:DividendsPreferredStockCash",
        "us-gaap:PaymentsOfDividends",
        "us-gaap:Dividends",
    ),
    # XBRL does not carry ex/record/payment dates as separate facts; iXBRL
    # filing narrative supplies them. `period_end` (fact.end) is the proxy
    # used for the dividend period. document_context tags document the source.
    "ex_dividend_date": ("xbrl:periodEnd", "xbrl:contextPeriod"),
    "declaration_date": ("ix:declarationDate",),
    "record_date": ("ix:recordDate",),
    "payment_date": ("ix:paymentDate",),
}

#: Concept names extracted from companyfacts for raw.dividend_data.
SEC_DIVIDEND_CONCEPTS: tuple[str, ...] = (
    "CommonStockDividendsPerShareDeclared",
    "CommonStockDividendsPerShareCashPaid",
    "PreferredStockDividendsPerShare",
    "DividendsCommonStockCash",
    "PaymentsOfDividendsCommonStock",
    "PaymentsOfDividendsPreferredStock",
    "DividendsPreferredStockCash",
    "PaymentsOfDividends",
    "Dividends",
)

#: Security owner implied by each dividend tag (used by sec_xbrl_dividend_tags).
DIVIDEND_TAGS: dict[str, str] = {
    "us-gaap:CommonStockDividendsPerShareDeclared": "Common Stock",
    "us-gaap:CommonStockDividendsPerShareCashPaid": "Common Stock",
    "us-gaap:DividendsCommonStockCash": "Common Stock",
    "us-gaap:PaymentsOfDividendsCommonStock": "Common Stock",
    "us-gaap:PreferredStockDividendsPerShare": "Preferred Stock",
    "us-gaap:DividendsPreferredStockCash": "Preferred Stock",
    "us-gaap:PaymentsOfDividendsPreferredStock": "Preferred Stock",
    "us-gaap:PaymentsOfDividendsPreferredStockAndPreferenceStock": "Preferred Stock",
    "us-gaap:DividendsPreferredStock": "Preferred Stock",
    "us-gaap:PreferredStockDividendsAndOtherAdjustments": "Preferred Stock",
    "us-gaap:PaymentsOfDividends": "Unknown",
    "us-gaap:Dividends": "Unknown",
}

# --------------------------------------------------------------------------
# Preferred-stock terms (raw.ticker_profile, preferred.security_terms,
# preferred.dividend_snapshot) — coupon, liquidation, par, redemption
# --------------------------------------------------------------------------

PREFERRED_COUPON_CONCEPTS: tuple[str, ...] = (
    "PreferredStockDividendRatePercentage",
    "PreferredStockDividendRatePerAnnum",
)

PREFERRED_LIQUIDATION_CONCEPTS: tuple[str, ...] = (
    "PreferredStockLiquidationPreferenceValue",
    "PreferredStockLiquidationPreference",
    "TemporaryEquityLiquidationPreferenceValue",
    "TemporaryEquityLiquidationPreference",
)

PREFERRED_PAR_VALUE_CONCEPTS: tuple[str, ...] = (
    "PreferredStockParOrStatedValuePerShare",
    "TemporaryEquityParOrStatedValuePerShare",
)

PREFERRED_REDEMPTION_CONCEPTS: tuple[str, ...] = (
    "PreferredStockRedemptionPricePerShare",
    "PreferredStockRedemptionPremium",
    "PreferredStockRedemptionDiscount",
)

#: Attribute name -> ordered concept names for the preferred-stock terms.
PREFERRED_TERM_CONCEPT_TAGS: dict[str, tuple[str, ...]] = {
    "coupon_rate": PREFERRED_COUPON_CONCEPTS,
    "liquidation_preference": PREFERRED_LIQUIDATION_CONCEPTS,
    "par_value": PREFERRED_PAR_VALUE_CONCEPTS,
}

#: Full preferred-stock concept set used by populate_preferred_profiles to
#: slice the stored companyfacts payload down to the tags it consumes.
PREFERRED_CONCEPTS: tuple[str, ...] = tuple(
    dict.fromkeys(
        PREFERRED_COUPON_CONCEPTS
        + PREFERRED_LIQUIDATION_CONCEPTS
        + PREFERRED_PAR_VALUE_CONCEPTS
        + PREFERRED_REDEMPTION_CONCEPTS
    )
)

#: Preferred-stock us-gaap concepts fetched via the SEC XBRL Data API
#: ``companyconcept`` endpoint (used by populate_companyfacts).
PREFERRED_STOCK_TAXONOMY_CONCEPTS: tuple[str, ...] = (
    "ConvertiblePreferredStockSharesIssuedUponConversion",
    "DividendsPreferredStock",
    "DividendsPreferredStockCash",
    "PaymentsForRepurchaseOfPreferredStockAndPreferenceStock",
    "PaymentsForRepurchaseOfRedeemablePreferredStock",
    "PaymentsOfDividendsPreferredStockAndPreferenceStock",
    "PreferredStockDividendRatePercentage",
    "PreferredStockDividendsAndOtherAdjustments",
    "PreferredStockLiquidationPreference",
    "PreferredStockLiquidationPreferenceValue",
    "PreferredStockParOrStatedValuePerShare",
    "PreferredStockRedemptionDiscount",
    "PreferredStockRedemptionPremium",
    "PreferredStockRedemptionPricePerShare",
    "PreferredStockSharesAuthorized",
    "PreferredStockSharesIssued",
    "PreferredStockSharesOutstanding",
    "PreferredStockSharesSubscribedButUnissuedSubscriptionsReceivable",
    "PreferredStockValue",
    "ProceedsFromIssuanceOfPreferredStockAndPreferenceStock",
)

#: DEI concepts fetched for the taxonomy-scoped run.
DEI_TAXONOMY_CONCEPTS: tuple[str, ...] = (
    "EntityCommonStockSharesOutstanding",
    "EntityPublicFloat",
)

# --------------------------------------------------------------------------
# Periodic financials (fundamentals.periodic_financials)
# --------------------------------------------------------------------------

#: Metric -> ordered us-gaap concepts for the normalised financial statements.
#: The flow concepts carry YTD/duration amounts over a fiscal period; the
#: instant concepts are point-in-time balance-sheet amounts. The first tag of
#: each tuple is preferred; the rest are fallbacks tried in order to cover the
#: concept naming drift across filers.
PERIODIC_FINANCIAL_CONCEPT_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "operating_income": (
        "OperatingIncomeLoss",
        "OperatingIncome",
    ),
    "net_income": (
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ),
    "eps": (
        "EarningsPerShareBasic",
        "EarningsPerShareDiluted",
        "EarningsPerShareBasicAndDiluted",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashAndCashEquivalentsAndShortTermInvestments",
        "CashCashEquivalentsAndShortTermInvestments",
    ),
    "assets": (
        "Assets",
        "AssetsCurrent",
    ),
    "liabilities": (
        "Liabilities",
        "LiabilitiesCurrent",
    ),
    "debt": (
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
        "LongTermDebtNoncurrent",
    ),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capital_expenditures": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
}

#: All concepts needed to reconstruct the periodic financials table, used to
#: slice the stored companyfacts payload down to the tags the extractor reads.
PERIODIC_FINANCIAL_CONCEPTS: tuple[str, ...] = tuple(
    dict.fromkeys(
        concept for concepts in PERIODIC_FINANCIAL_CONCEPT_TAGS.values() for concept in concepts
    )
)
