import uuid
import pandas as pd

from src.crispdm.fundamentals import extract_periodic_financials
from src.crispdm.scoring import score, predictions, rankings


def _scores_df():
    x = pd.DataFrame({
        "security_id": ["a", "b", "c"],
        "as_of_date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-01"]),
        "composite_score": [0.9, 0.5, 0.2],
    })
    return x


def test_fundamentals_extracts_canonical_metrics():
    facts = {
        "full_facts": {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {"val": 1000, "start": "2025-01-01",
                                 "end": "2025-12-31", "fy": 2025, "fp": "FY",
                                 "filed": "2026-02-01"},
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {"val": 120, "start": "2025-01-01",
                                 "end": "2025-12-31", "fy": 2025, "fp": "FY",
                                 "filed": "2026-02-01"},
                            ]
                        }
                    },
                    "NetCashProvidedByUsedInOperatingActivities": {
                        "units": {
                            "USD": [
                                {"val": 80, "start": "2025-01-01",
                                 "end": "2025-12-31", "fy": 2025, "fp": "FY",
                                 "filed": "2026-02-01"},
                            ]
                        }
                    },
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "units": {
                            "USD": [
                                {"val": 30, "start": "2025-01-01",
                                 "end": "2025-12-31", "fy": 2025, "fp": "FY",
                                 "filed": "2026-02-01"},
                            ]
                        }
                    },
                    "Assets": {
                        "units": {
                            "USD": [
                                {"val": 5000, "end": "2025-12-31",
                                 "fy": 2025, "fp": "FY", "filed": "2026-02-01"},
                            ]
                        }
                    },
                }
            }
        }
    }

    rows = extract_periodic_financials(facts)
    assert len(rows) == 1
    row = rows[0]
    assert row["revenue"] == 1000
    assert row["net_income"] == 120
    assert row["operating_cash_flow"] == 80
    assert row["capital_expenditures"] == 30
    assert row["free_cash_flow"] == 50
    assert row["assets"] == 5000
    assert row["fiscal_period"] == "FY"
    assert row["source"] == "SEC_XBRL"


def test_fundamentals_prefers_canonical_concept_over_fallback():
    facts = {
        "full_facts": {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {"USD": [{"val": 100, "end": "2025-12-31",
                                           "fy": 2025, "fp": "FY",
                                           "filed": "2026-02-01"}]}
                    },
                    "SalesRevenueNet": {
                        "units": {"USD": [{"val": 999, "end": "2025-12-31",
                                           "fy": 2025, "fp": "FY",
                                           "filed": "2026-02-01"}]}
                    },
                }
            }
        }
    }
    rows = extract_periodic_financials(facts)
    assert rows[0]["revenue"] == 100


def test_predictions_classify_on_threshold():
    x = predictions(_scores_df(), uuid.uuid4(), threshold=0.5)
    assert x.loc[x.security_id == "a", "predicted_class"].iloc[0] == 1
    assert x.loc[x.security_id == "c", "predicted_class"].iloc[0] == 0
    assert "run_id" in x.columns
    assert (x.probability == x.composite_score).all()


def test_rankings_ordered_by_composite():
    x = rankings(_scores_df())
    assert x.loc[x.security_id == "a", "rank"].iloc[0] == 1
    assert x.loc[x.security_id == "b", "rank"].iloc[0] == 2
    assert x.loc[x.security_id == "c", "rank"].iloc[0] == 3