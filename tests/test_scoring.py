import pandas as pd
from unittest.mock import patch
from scripts.populate_reference_tables import get_issuer_info_with_fallback
from src.crispdm.scoring import score,WEIGHTS
from src.crispdm.sec_client import (
    classify_companyfacts,
    classify_security_type,
    get_issuer_data,
    get_legacy_issuer_data,
)

def test_weights():
    assert sum(WEIGHTS.values())==1

def test_score():
    d=pd.DataFrame({
      "dividend_yield":[.02,.05,.08],"dividend_growth":[.02,.05,.01],
      "dividend_coverage":[1,2,3],"fcf_payout":[.9,.6,.4],
      "momentum_252d":[-.1,.1,.2],"momentum_63d":[-.05,.03,.1],
      "volatility_252d":[.4,.3,.2],"legal_rights_score":[.5,.7,.9]
    })
    assert score(d).composite_score.notna().all()


def test_companyfacts_security_and_dividend_classification_is_auditable():
    facts = {
        "full_facts": {
            "us-gaap": {
                "CommonStockSharesOutstanding": {
                    "units": {"shares": [{"val": 100, "end": "2026-01-01"}]}
                },
                "CommonStockDividendsPerShareDeclared": {
                    "units": {"USD/shares": [{"val": 1.25, "end": "2026-01-01"}]}
                },
            }
        }
    }

    result = classify_companyfacts(facts)

    assert result["security_types"] == ["common_stock"]
    assert result["dividend"] is True
    assert result["security_facts"][0]["tag"] == "CommonStockSharesOutstanding"
    assert result["dividend_facts"][0]["tag"] == "CommonStockDividendsPerShareDeclared"


def test_companyfacts_preferred_stock_uses_normalized_security_type():
    result = classify_companyfacts({
        "full_facts": {
            "us-gaap": {
                "PreferredStockSharesOutstanding": {
                    "units": {"shares": [{"val": 100, "end": "2026-01-01"}]}
                }
            }
        }
    })

    assert result["security_types"] == ["preferred stock"]


def test_title_security_type_is_normalized():
    assert classify_security_type("Example Preferred Stock") == "preferred stock"
    assert classify_security_type("Example Unit") == "other_debt_and_equity"
    assert classify_security_type("Example Common Stock") == "common_stock"
    assert classify_security_type("Example Government Bond") == "government debt"
    assert classify_security_type("Example Corporate Bond") == "corporate bond"
    assert classify_security_type("Example Call Option") == "option"
    assert classify_security_type("Example Futures Contract") == "future"


def test_issuer_data_reads_sec_submission_metadata():
    submissions = {
        "name": "Apple Inc.",
        "sic": 3571,
        "fiscalYearEnd": "0926",
    }

    with patch("src.crispdm.sec_client.get_submissions", return_value=submissions):
        result = get_issuer_data("0000320193")

    assert result == {
        "cik": "0000320193",
        "issuer_name": "Apple Inc.",
        "sic": "3571",
        "fiscal_year_end": "09-26",
    }


def test_legacy_issuer_data_uses_current_sec_company_endpoint():
    response = type("Response", (), {
        "text": "Company Name: Apple Inc. CIK: 0000320193 SIC Code: 3571 Fiscal Year End: 0926",
        "raise_for_status": lambda self: None,
    })()

    with patch("src.crispdm.sec_client.SEC_SESSION.get", return_value=response) as request:
        result = get_legacy_issuer_data(320193)

    request.assert_called_once()
    assert request.call_args.args[0] == "https://www.sec.gov/cgi-bin/browse-edgar"
    assert request.call_args.kwargs["params"] == {
        "action": "getcompany",
        "CIK": "0000320193",
    }
    assert result["sic"] == "3571"


def test_reference_population_prefers_complete_sec_metadata():
    issuer = {
        "cik": "0000320193",
        "issuer_name": "Apple Inc.",
        "sic": "3571",
        "fiscal_year_end": "09-26",
    }

    with patch("scripts.populate_reference_tables.get_issuer_data", return_value=issuer) as sec_lookup, \
            patch("scripts.populate_reference_tables.openbb_profile") as openbb_lookup:
        result, source = get_issuer_info_with_fallback("0000320193", "AAPL", "Apple Inc.")

    assert result == issuer
    assert source == "SEC"
    sec_lookup.assert_called_once_with("0000320193")
    openbb_lookup.assert_not_called()
