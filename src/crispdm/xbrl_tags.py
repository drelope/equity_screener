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

#: How recent a positive dividend fact must be to justify ``dividend = TRUE``.
#:
#: XBRL Company Facts retain every fact an issuer has ever filed, including
#: comparative columns from long-past periods. A single stale positive fact is
#: therefore enough to keep a long-defunct or acquired issuer inside the
#: dividend universe forever. 548 days is the same horizon the preferred
#: dividend snapshot already uses to decide whether a declared dividend is
#: still live, so the reference universe and the per-instrument snapshot agree
#: on what "currently paying" means.
DIVIDEND_RECENCY_DAYS: int = 548

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
    # Gross profit is the top of the P&L ladder, above operating income, and is
    # reported as a single tag often enough to be worth carrying: it is the
    # denominator-free cost structure that separates a high-margin compounder
    # from a thin-margin distributor paying the same dividend yield. The direct
    # GrossProfit tag is preferred, but only 839 of 2,926 candidate filers tag
    # it, so ``extract_periodic_financials`` falls back to deriving
    # revenue - cost_of_revenue when the subtotal is not stated (see that
    # function for the measurement that makes the subtraction safe). Absence is
    # still recorded as coverage, never filled from a partial cost line.
    "gross_profit": ("GrossProfit",),
    # The cost line the gross-profit derivation subtracts from revenue. Only the
    # two *total* cost-of-revenue concepts are read: CostOfRevenue and
    # CostOfGoodsAndServicesSold both cover the whole cost of sales. The narrow
    # tags are deliberately excluded -- CostOfGoodsSold omits services cost and
    # CostOfServices omits goods cost, so subtracting either from total revenue
    # would overstate gross profit and, under the section 4.1 house standard, pay
    # a filer for what it did not disclose. The same reasoning that keeps
    # AssetsCurrent out of ``assets`` applies here.
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold"),
    "net_income": (
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ),
    "eps": (
        "EarningsPerShareBasic",
        "EarningsPerShareDiluted",
        "EarningsPerShareBasicAndDiluted",
    ),
    # Cash and marketable securities are stored as one liquidity numerator
    # because a quick ratio wants both, and the filers that report one almost
    # always report the other under a compound tag. They are NOT interchangeable
    # in the general case -- CashAndCashEquivalentsAtCarryingValue excludes
    # short-term investments entirely -- so the first tag below is the pure
    # cash line and the compound tags follow. A company reporting only
    # CashAndCashEquivalentsAtCarryingValue gets a numerator that understates
    # its real liquidity, which reads as slightly worse coverage rather than
    # better. That is the direction the section 4.1 house standard wants: a
    # gap in disclosure costs the filer, it does not pay it.
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashAndCashEquivalentsAndShortTermInvestments",
        "CashCashEquivalentsAndShortTermInvestments",
    ),
    "assets": (
        "Assets",
        # AssetsCurrent is NOT a fallback for Assets. They are different
        # quantities: total assets against current assets, and a balance sheet
        # reporting only the current subtotal is reporting less, not the same
        # thing under another name. Substituting one for the other made
        # `assets` mean whatever the filer happened to report first, which
        # broke the assets = liabilities + equity identity check on 44,630 of
        # 269,969 stored rows. The current-basis subtotals are now their own
        # metrics below, named for what they are.
    ),
    "current_assets": ("AssetsCurrent",),
    "liabilities": ("Liabilities",),
    "current_liabilities": ("LiabilitiesCurrent",),
    # The contractual debt maturity ladder, as reported in the debt footnote.
    #
    # The specification asserted twice that XBRL "does not expose" a maturity
    # schedule as a fact, and built C4's unsourced status on that claim. It is
    # false: 2,748 of 7,079 stored companyfacts carry the year-one bucket and
    # 2,680 carry both year one and year two. They are instant facts at the
    # fiscal year end, not duration facts, so they sit on the same vintage as
    # the balance sheet and need no separate aggregation.
    #
    # Year three is also a standard tag (LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree,
    # 2,655 companies) but is stored unconverted because C4 is an 18-month
    # test and year three falls outside it. Carrying it would invite someone to
    # use a figure the override does not ask for.
    "debt_maturing_12m": ("LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",),
    "debt_maturing_year_2": ("LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",),
    # Section 5.5 defines C4's reserves as Cash *plus Committed Undrawn
    # Facilities*. Committed undrawn capacity is a reported XBRL balance, and
    # 888 stored filers disclose it, so measuring reserves as cash alone
    # understated them on precisely the firms that hold a revolver alongside a
    # near-term maturity -- the firms C4 exists to catch.
    #
    # Coverage is genuinely partial, and the fallback is deliberate: a filer
    # that does not tag this is NOT assumed to have zero capacity, because
    # treating silence as zero is what the cash-only denominator did wrong.
    # The capacity simply stays out of the numerator, which keeps the measure
    # conservative in the direction that matters for a gate.
    "committed_undrawn_facility": (
        "LineOfCreditFacilityRemainingBorrowingCapacity",
        "LineOfCreditFacilityCurrentBorrowingCapacity",
    ),
    # Debt is assembled from components rather than taken as one concept. The
    # previous list was three *long-term* concepts, so a filer whose only
    # interest-bearing balance was current (LongTermDebtCurrent, DebtCurrent,
    # ShortTermBorrowings, NotesPayableCurrent, CommercialPaper) reported no
    # debt at all, and -- because ``debt IS NULL`` is what circuit breakers
    # C2 and C3 read to decide whether a firm has reportable debt instruments --
    # that filer was indistinguishable from a firm with genuinely none.
    #
    # They must also be summed, not priority-resolved. `_visible_as_of` returns
    # the first concept with a filing, so a filer reporting both a noncurrent
    # balance and a current portion kept only the noncurrent one. Understating
    # debt is the one direction of error a leverage gate cannot absorb.
    # ``fundamentals.extract_periodic_financials`` adds the parts together.
    "debt_noncurrent": (
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
        "LongTermDebtNoncurrent",
    ),
    "debt_current": (
        "LongTermDebtCurrent",
        "DebtCurrent",
        "ShortTermBorrowings",
        "NotesPayableCurrent",
        "CommercialPaper",
    ),
    # Finance leases are debt under GAAP and so are included in the total.
    # Operating leases are deliberately excluded: ASC 842 keeps them off the
    # balance sheet as borrowings, so counting them would change every leverage
    # ratio in the warehouse. That is a separate, deliberate decision rather
    # than an oversight -- 4,742 filers tag OperatingLeaseLiability.
    "finance_lease_debt": (
        "FinanceLeaseLiabilityNoncurrent",
        "FinanceLeaseLiabilityCurrent",
        "FinanceLeaseLiability",
    ),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    # Cash paid to repurchase the issuer's own shares -- the buyback leg of
    # capital returns. It is a cash-flow (duration) fact like capex, reported in
    # the financing section, and is the only share-repurchase quantity XBRL
    # records reliably: ~3,392 stored filers carry the common-stock tag and 480
    # the equity tag (which also covers repurchases of preferred). A filer that
    # does not tag it has an unknown buyback, not a zero one, so the column
    # stays NULL and is never coalesced to zero.
    "share_repurchases": (
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsForRepurchaseOfEquity",
    ),
    "capital_expenditures": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    # The next three exist because the ratio features that needed them were
    # retired as "not computable from this schema". That verdict was true of the
    # *materialised* columns but not of the data: raw.companyfacts keeps the
    # whole XBRL payload, and the concepts are present far more often than the
    # retired features' reasons claimed. Measured over 1,500 stored filings,
    # D&A resolves in 64% (72% including the split-tag fallbacks), interest
    # expense in 69%, and shares outstanding in 91%. They are populated so the
    # ratio features can be restored on evidence rather than on assumption; the
    # remaining sparsity is real and is reported as a coverage number, not
    # filled in.
    "depreciation_amortization": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationNonproduction",
        "OtherDepreciationAndAmortization",
    ),
    # Interest is reported either as a standalone expense or folded into a
    # combined "interest and debt expense" line, so both are tried.
    "interest_expense": (
        "InterestExpense",
        "InterestExpenseNonoperating",
        "InterestAndDebtExpense",
        "InterestExpenseDebt",
        "InterestExpenseNonoperatingNet",
    ),
    # dei:EntityCommonStockSharesOutstanding has the best coverage of any
    # shares concept but lives in the dei taxonomy, which this extractor does
    # not read (it is built on the us-gaap slice alone). Using the us-gaap
    # equivalents keeps the taxonomy plumbing untouched; the coverage cost is
    # recorded rather than worked around with a second code path.
    "shares_outstanding": (
        "CommonStockSharesOutstanding",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
}

#: All concepts needed to reconstruct the periodic financials table, used to
#: slice the stored companyfacts payload down to the tags the extractor reads.
PERIODIC_FINANCIAL_CONCEPTS: tuple[str, ...] = tuple(
    dict.fromkeys(
        concept for concepts in PERIODIC_FINANCIAL_CONCEPT_TAGS.values() for concept in concepts
    )
)
