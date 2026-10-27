import uuid
from datetime import date

import pandas as pd
import pytest

from src.crispdm.fundamentals import extract_periodic_financials
from src.crispdm.scoring import predictions, rankings


def _scores_df():
    x = pd.DataFrame(
        {
            "security_id": ["a", "b", "c"],
            "as_of_date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-01"]),
            "composite_score": [0.9, 0.5, 0.2],
        }
    )
    return x


def test_fundamentals_extracts_canonical_metrics():
    facts = {
        "full_facts": {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {
                                    "val": 1000,
                                    "start": "2025-01-01",
                                    "end": "2025-12-31",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "filed": "2026-02-01",
                                },
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {
                                    "val": 120,
                                    "start": "2025-01-01",
                                    "end": "2025-12-31",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "filed": "2026-02-01",
                                },
                            ]
                        }
                    },
                    "NetCashProvidedByUsedInOperatingActivities": {
                        "units": {
                            "USD": [
                                {
                                    "val": 80,
                                    "start": "2025-01-01",
                                    "end": "2025-12-31",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "filed": "2026-02-01",
                                },
                            ]
                        }
                    },
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "units": {
                            "USD": [
                                {
                                    "val": 30,
                                    "start": "2025-01-01",
                                    "end": "2025-12-31",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "filed": "2026-02-01",
                                },
                            ]
                        }
                    },
                    "GrossProfit": {
                        "units": {
                            "USD": [
                                {
                                    "val": 400,
                                    "start": "2025-01-01",
                                    "end": "2025-12-31",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "filed": "2026-02-01",
                                },
                            ]
                        }
                    },
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "val": 5000,
                                    "end": "2025-12-31",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "filed": "2026-02-01",
                                },
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
    assert row["gross_profit"] == 400
    assert row["assets"] == 5000
    assert row["fiscal_period"] == "FY"
    assert row["source"] == "SEC_XBRL"


def test_gross_profit_is_tagged_or_derived_from_total_cost_only():
    """The direct GrossProfit subtotal wins; otherwise revenue - total cost.

    Only the two *total* cost-of-revenue concepts are subtracted. A filer whose
    only cost tag is narrow (CostOfServices / CostOfGoodsSold) keeps a NULL gross
    profit rather than an overstated one, and a cost line with no revenue derives
    nothing. Absence is recorded as coverage, not filled -- the same rule
    share_repurchases follows.
    """

    def concept(value):
        return {
            "units": {
                "USD": [
                    {
                        "val": value,
                        "start": "2025-01-01",
                        "end": "2025-12-31",
                        "fy": 2025,
                        "fp": "FY",
                        "filed": "2026-02-01",
                    }
                ]
            }
        }

    def extract(facts):
        return extract_periodic_financials({"full_facts": {"facts": {"us-gaap": facts}}})[0]

    revenue_tag = "RevenueFromContractWithCustomerExcludingAssessedTax"

    tagged = extract({"GrossProfit": concept(400)})
    assert tagged["gross_profit"] == 400

    derived = extract({revenue_tag: concept(1000), "CostOfRevenue": concept(600)})
    assert derived["gross_profit"] == 400
    assert derived["cost_of_revenue"] == 600

    broad = extract({revenue_tag: concept(1000), "CostOfGoodsAndServicesSold": concept(650)})
    assert broad["gross_profit"] == 350

    narrow = extract({revenue_tag: concept(1000), "CostOfServices": concept(600)})
    assert "gross_profit" not in narrow, "a partial cost line must not overstate gross"

    no_revenue = extract({"CostOfRevenue": concept(600)})
    assert "gross_profit" not in no_revenue

    direct_wins = extract(
        {"GrossProfit": concept(275), revenue_tag: concept(1000), "CostOfRevenue": concept(600)}
    )
    assert direct_wins["gross_profit"] == 275, "the filer's own subtotal wins over the derivation"


def test_share_repurchases_are_extracted_with_a_fallback_and_never_zero_filled():
    def period(concept, value):
        return {
            "full_facts": {
                "facts": {
                    "us-gaap": {
                        concept: {
                            "units": {
                                "USD": [
                                    {
                                        "val": value,
                                        "start": "2025-01-01",
                                        "end": "2025-12-31",
                                        "fy": 2025,
                                        "fp": "FY",
                                        "filed": "2026-02-01",
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }

    assert (
        extract_periodic_financials(period("PaymentsForRepurchaseOfCommonStock", 250))[0][
            "share_repurchases"
        ]
        == 250
    )
    # The equity tag also covers preferred repurchases, so it is the fallback.
    assert (
        extract_periodic_financials(period("PaymentsForRepurchaseOfEquity", 99))[0][
            "share_repurchases"
        ]
        == 99
    )

    # A filer that reports a period but never tagged a repurchase has an unknown
    # buyback, not a zero one: the metric is absent, not 0.
    revenue_only = extract_periodic_financials(
        {
            "full_facts": {
                "facts": {
                    "us-gaap": {
                        "RevenueFromContractWithCustomerExcludingAssessedTax": {
                            "units": {
                                "USD": [
                                    {
                                        "val": 1000,
                                        "start": "2025-01-01",
                                        "end": "2025-12-31",
                                        "fy": 2025,
                                        "fp": "FY",
                                        "filed": "2026-02-01",
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
    )
    assert "share_repurchases" not in revenue_only[0]


def test_fundamentals_prefers_canonical_concept_over_fallback():
    facts = {
        "full_facts": {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {
                                    "val": 100,
                                    "end": "2025-12-31",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "filed": "2026-02-01",
                                }
                            ]
                        }
                    },
                    "SalesRevenueNet": {
                        "units": {
                            "USD": [
                                {
                                    "val": 999,
                                    "end": "2025-12-31",
                                    "fy": 2025,
                                    "fp": "FY",
                                    "filed": "2026-02-01",
                                }
                            ]
                        }
                    },
                }
            }
        }
    }
    rows = extract_periodic_financials(facts)
    assert rows[0]["revenue"] == 100


def test_current_subtotals_are_not_fallbacks_for_the_totals():
    """AssetsCurrent is not a synonym for Assets, and the code used to treat it as one.

    `assets` accepted AssetsCurrent as a fallback and `liabilities` accepted
    LiabilitiesCurrent. Both are different quantities -- total against
    current-only -- so a filer reporting just the subtotal was recorded as
    though it had reported the whole balance sheet. The measured cost in the
    warehouse was 44,630 rows failing assets = liabilities + equity and 29,120
    with liabilities above assets.

    V0016 splits them. This pins both halves: the total-basis column no longer
    accepts the subtotal, and the current-basis value lands in its own column.
    """
    facts = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "val": 1000,
                                "end": "2025-12-31",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                },
                "AssetsCurrent": {
                    "units": {
                        "USD": [
                            {
                                "val": 400,
                                "end": "2025-12-31",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                },
                "Liabilities": {
                    "units": {
                        "USD": [
                            {
                                "val": 600,
                                "end": "2025-12-31",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                },
                "LiabilitiesCurrent": {
                    "units": {
                        "USD": [
                            {
                                "val": 250,
                                "end": "2025-12-31",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                },
                "CashAndCashEquivalentsAtCarryingValue": {
                    "units": {
                        "USD": [
                            {
                                "val": 120,
                                "end": "2025-12-31",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                },
            }
        }
    }
    row = extract_periodic_financials(facts)[0]
    assert row["assets"] == 1000
    assert row["liabilities"] == 600
    assert row["current_assets"] == 400
    assert row["current_liabilities"] == 250
    assert row["cash"] == 120


def test_a_filer_reporting_only_the_current_subtotal_leaves_the_total_null():
    """The half that matters most: absence must stay absence.

    A subtotal-only filer is common, and under the old fallback mapping it was
    silently recorded as a total. Now it produces NULL in `liabilities` -- which
    reads as "not measured" rather than "measured, and this is the number".
    That is the reading the balance-sheet identity check depends on.
    """
    facts = {
        "facts": {
            "us-gaap": {
                "AssetsCurrent": {
                    "units": {
                        "USD": [
                            {
                                "val": 400,
                                "end": "2025-12-31",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                },
                "LiabilitiesCurrent": {
                    "units": {
                        "USD": [
                            {
                                "val": 250,
                                "end": "2025-12-31",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                },
            }
        }
    }
    # extract_periodic_financials omits absent metrics entirely rather than
    # writing a None, and populate_fundamentals reads them with .get(), so the
    # absence surfaces as a missing key. Either way the SQL bind receives NULL.
    row = extract_periodic_financials(facts)[0]
    assert row["current_assets"] == 400
    assert row["current_liabilities"] == 250
    assert row.get("assets") is None
    assert row.get("liabilities") is None


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


def _companyfacts_with_long_history(n_periods=60):
    """A filer with ``n_periods`` annual periods, newest last."""
    units = {
        "USD/shares": [
            {
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "val": 1.0 + year / 100,
                "fy": year,
                "fp": "FY",
                "form": "10-K",
                "filed": f"{year + 1}-02-01",
            }
            for year in range(2000, 2000 + n_periods)
        ]
    }
    return {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": units}}}}


def test_extraction_keeps_history_older_than_a_decade():
    # max_periods keeps the MOST RECENT N periods, so a small bound silently
    # drops everything older. At the old default of 24 this payload yielded
    # only the last 24 years, which is why the 2019-2022 fundamentals the
    # 365-day label embargo needs never reached the feature table.
    payload = _companyfacts_with_long_history(n_periods=40)

    rows = extract_periodic_financials(payload)

    years = {pd.Timestamp(row["period_end"]).year for row in rows}
    assert min(years) == 2000, "the oldest periods must survive extraction"
    assert len(years) == 40


def test_max_periods_still_bounds_the_result():
    payload = _companyfacts_with_long_history(n_periods=40)

    rows = extract_periodic_financials(payload, max_periods=5)

    years = sorted({pd.Timestamp(row["period_end"]).year for row in rows})
    assert years == [2035, 2036, 2037, 2038, 2039]


def _eps_facts(records):
    """Wrap bare EPS fact dicts in a companyfacts payload."""
    return {
        "facts": {
            "us-gaap": {
                "EarningsPerShareDiluted": {"units": {"USD/shares": records}},
            }
        }
    }


def test_filing_date_is_recorded_on_every_row():
    """Availability must be knowable, so the filing date has to survive."""
    payload = _eps_facts(
        [
            {
                "val": 1.0,
                "start": "2024-01-01",
                "end": "2024-03-31",
                "fy": 2024,
                "fp": "Q1",
                "filed": "2024-05-10",
            }
        ]
    )

    rows = extract_periodic_financials(payload)

    assert len(rows) == 1
    assert rows[0]["filed"] == date(2024, 5, 10)
    assert rows[0]["period_end"] == date(2024, 3, 31)


def test_a_period_is_only_visible_from_its_filing_date():
    """A quarter is not available when it ends -- median lag is 224 days."""
    payload = _eps_facts(
        [
            {
                "val": 1.0,
                "start": "2024-01-01",
                "end": "2024-03-31",
                "fy": 2024,
                "fp": "Q1",
                "filed": "2024-05-10",
            }
        ]
    )

    rows = extract_periodic_financials(payload)
    filed = rows[0]["filed"]

    # A consumer joining on filed <= as_of sees nothing before the filing date.
    assert not (date(2024, 3, 31) >= filed), "period_end alignment would leak this"
    assert date(2024, 5, 10) >= filed


def test_restatement_keeps_both_vintages_rather_than_only_the_latest():
    """A restated period is two observations, not one overwritten value.

    Collapsing to the latest filing makes the period invisible until the
    restatement and shows the restated figure to anyone joining on period_end,
    which is wrong in both directions. Both vintages must be recoverable.
    """
    payload = _eps_facts(
        [
            {
                "val": 1.0,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "fy": 2023,
                "fp": "FY",
                "filed": "2024-02-15",
            },
            {
                "val": 0.8,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "fy": 2023,
                "fp": "FY",
                "filed": "2025-03-01",
            },
        ]
    )

    rows = extract_periodic_financials(payload)

    by_filed = {row["filed"]: row for row in rows}
    assert set(by_filed) == {date(2024, 2, 15), date(2025, 3, 1)}
    # Each vintage carries the value as it stood at that filing.
    assert by_filed[date(2024, 2, 15)]["eps"] == 1.0
    assert by_filed[date(2025, 3, 1)]["eps"] == 0.8
    assert all(row["period_end"] == date(2023, 12, 31) for row in rows)


def test_a_vintage_repeats_unchanged_metrics_from_earlier_filings():
    """When one metric is restated, the others stay as last reported.

    A vintage is a snapshot of the whole period, so a metric that was not
    restated must still carry its previously filed value. Leaving it out would
    make the row look like the metric had no value at all.
    """
    payload = {
        "facts": {
            "us-gaap": {
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {
                                "val": 1.0,
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "fy": 2023,
                                "fp": "FY",
                                "filed": "2024-02-15",
                            },
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "val": 5000,
                                "end": "2023-12-31",
                                "fy": 2023,
                                "fp": "FY",
                                "filed": "2024-02-15",
                            },
                            {
                                "val": 4800,
                                "end": "2023-12-31",
                                "fy": 2023,
                                "fp": "FY",
                                "filed": "2025-03-01",
                            },
                        ]
                    }
                },
            }
        }
    }

    rows = extract_periodic_financials(payload)
    by_filed = {row["filed"]: row for row in rows}

    assert by_filed[date(2024, 2, 15)]["assets"] == 5000
    assert by_filed[date(2024, 2, 15)]["eps"] == 1.0
    # The 2025 vintage restates assets but has no new EPS, so EPS carries
    # forward rather than disappearing.
    assert by_filed[date(2025, 3, 1)]["assets"] == 4800
    assert by_filed[date(2025, 3, 1)]["eps"] == 1.0


def test_canonical_concept_still_wins_within_each_vintage():
    """Priority is resolved per vintage, not just for the latest filing.

    The canonical EPS concept is ``EarningsPerShareBasic``; the diluted variant
    is the fallback. If the fallback filed first, a flattened date map would let
    it keep supplying the value even after the canonical concept reported.
    """
    payload = {
        "facts": {
            "us-gaap": {
                # Fallback concept, filed early.
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {
                                "val": 1.0,
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "fy": 2023,
                                "fp": "FY",
                                "filed": "2024-02-15",
                            },
                        ]
                    }
                },
                # Canonical concept, filed later.
                "EarningsPerShareBasic": {
                    "units": {
                        "USD/shares": [
                            {
                                "val": 0.95,
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "fy": 2023,
                                "fp": "FY",
                                "filed": "2024-06-01",
                            },
                        ]
                    }
                },
            }
        }
    }

    rows = extract_periodic_financials(payload)
    by_filed = {row["filed"]: row for row in rows}

    # Before the canonical concept has filed, the fallback supplies the value.
    assert by_filed[date(2024, 2, 15)]["eps"] == 1.0
    # Once it has, priority takes over -- and keeps winning thereafter.
    assert by_filed[date(2024, 6, 1)]["eps"] == 0.95


def test_facts_without_a_filing_date_are_dropped_rather_than_assumed_available():
    """No filing date means no knowable availability, so the fact is dropped."""
    payload = _eps_facts(
        [
            {
                "val": 1.0,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "fy": 2023,
                "fp": "FY",
                "filed": "2024-02-15",
            },
            {"val": 99.0, "start": "2022-01-01", "end": "2022-12-31", "fy": 2022, "fp": "FY"},
        ]
    )

    rows = extract_periodic_financials(payload)

    assert [row["period_end"] for row in rows] == [date(2023, 12, 31)]
    assert all(row.get("eps") != 99.0 for row in rows)


def test_a_period_ending_after_the_run_date_is_dropped():
    """A period that has not ended cannot have been reported.

    Left unbounded, a forward-dated XBRL context reaches the stored table and a
    reader ordering by period_end alone (the financials API, the Fundamentals
    tab) shows a 2039 period as the latest. The extractor's ``as_of`` is the
    ceiling; the writer passes the run date.
    """
    payload = _eps_facts(
        [
            {
                "val": 1.0,
                "start": "2023-01-01",
                "end": "2023-12-31",
                "fy": 2023,
                "fp": "FY",
                "filed": "2024-02-15",
            },
            {
                # Impossible: period ends 2039, "filed" 2024.
                "val": 9.0,
                "start": "2039-01-01",
                "end": "2039-12-31",
                "fy": 2039,
                "fp": "FY",
                "filed": "2024-02-15",
            },
        ]
    )

    bounded = extract_periodic_financials(payload, as_of=date(2026, 10, 15))
    assert [row["period_end"] for row in bounded] == [date(2023, 12, 31)]

    # A period ending exactly on the run date is real (filed the same day), so
    # the bound is strict-greater, not >=.
    same_day = extract_periodic_financials(payload, as_of=date(2039, 12, 31))
    assert date(2039, 12, 31) in {row["period_end"] for row in same_day}

    # as_of=None stays a pure payload transform, which is what keeps the
    # max_periods recency tests (periods years in the future) meaningful.
    unbounded = extract_periodic_financials(payload)
    assert date(2039, 12, 31) in {row["period_end"] for row in unbounded}


def test_feature_sql_joins_on_filing_date_not_period_end():
    """Guard the join predicate itself against regressing to period alignment."""
    import inspect

    from src.crispdm import features

    sql = inspect.getsource(features)
    assert "pf.filed <= f.observation_date" not in sql
    assert "pf.period_end <= f.observation_date" not in sql, (
        "period-end alignment leaks a quarter's earnings before it is filed"
    )
    # Availability is a half-open interval per vintage, so exactly one vintage
    # of a period matches any given observation date. A plain filed <= join
    # would match every restatement of the period at once, double counting a
    # restated quarter in the trailing-twelve-month sum.
    assert "LEAD(GREATEST(pf.filed, pf.period_end)) OVER" in sql
    assert "f.observation_date >= v.filed" in sql
    assert "f.observation_date < v.filed_next" in sql
    assert "ORDER BY pf.filed DESC) vr" not in sql, (
        "resolving vintages with a window over the market-history join sorts "
        "~250M rows and exhausts memory during the feature build"
    )
    # The vintage chain has to be keyed on the metric, not only on the period's
    # fiscal_period label. A chain per label lets one quarter match an
    # observation date twice and be summed twice; a chain per period lets a
    # label that omits the metric mask a figure that was already published.
    assert "PARTITION BY pf.security_id, pf.period_end, pf.fiscal_period" not in sql
    assert "PARTITION BY security_id, period_end, metric" in sql
    assert "q_streams AS (" in sql, (
        "each metric needs its own vintage chain so a label that does not "
        "report it cannot terminate the interval and read as NULL"
    )


def test_financials_readers_bound_period_end_to_the_run_date():
    """The two readers that order by period_end alone must not serve a future one.

    features.py is safe via GREATEST(filed, period_end), but the API endpoint
    and the Streamlit Fundamentals tab select straight out of the table ordered
    by period_end, so a 2039 XBRL context wins the sort. V0078 removes the rows
    and the extractor no longer writes them; these bounds are the backstop.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    api = (root / "api" / "main.py").read_text()
    assert "f.period_end <= CURRENT_DATE" in api
    assert "f.period_end <= CAST(:as_of AS date)" in api
    view = (root / "app" / "views" / "security.py").read_text()
    assert "period_end <= CURRENT_DATE" in view


def _production_quarterly_ctes():
    """The quarterly CTEs of the real feature query, verbatim.

    Extracted from the query source rather than restated here so that these
    tests exercise the SQL that actually builds the features. A restatement
    would let the query regress while the test kept passing, which is how a
    fiscal_period-keyed vintage chain survived review.
    """
    import inspect

    from src.crispdm import features

    src = inspect.getsource(features.build_features)
    block = src[src.index("    q_quarterly AS (") : src.index("    fy_vintages AS (")]
    block = "\n".join(line[4:] if line.startswith("    ") else line for line in block.splitlines())
    return "WITH " + block.rstrip().rstrip(",").rstrip() + "\n"


def _live_connection():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return engine
    except Exception:  # pragma: no cover - environments without a database
        return None


def test_ttm_chain_is_per_metric_so_a_missing_label_cannot_mask_a_published_value():
    """One fiscal quarter must occupy one slot, and each metric needs its own chain.

    Two independent defects lived in the same three lines of SQL, and both were
    invisible to the string guards that covered this query:

    * Chaining vintages per (security, period_end, fiscal_period) gave every
      label its own interval, so a period carrying two quarterly labels matched
      twice on one observation date and both copies were ranked into the
      four-quarter window -- one quarter summed twice, with an unstable
      tie-break deciding which copy survived.
    * Merging the labels back into a single chain per period then let a label
      that omitted a metric terminate the interval, so a figure that had been
      published read as NULL from that date onward. Over one quarter of
      observation dates that discarded 61% of the quarterly EPS in the table.

    Both are asserted here against the real query text.
    """
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    cte = (
        _production_quarterly_ctes()
        .replace("fundamentals.periodic_financials pf", "tmp_pf pf")
        .replace("raw.market_data", "tmp_mkt")
    )
    # The build query is windowed by observation date so its peak memory can be
    # bounded; the extracted CTEs carry those binds and need the same values.
    params = {"date_from": date(2000, 1, 1), "date_to": date(2100, 1, 1)}
    ddl = """
    DROP TABLE IF EXISTS tmp_pf, tmp_mkt;
    -- operating_income / depreciation_amortization / interest_expense are the
    -- V0011 leverage inputs the feature query now reads, so the fixture carries
    -- them. Named-column inserts below leave them NULL, which is also the
    -- right default for a fixture about the EPS and FCF chains.
    -- revenue is not a feature; the feature query reads it only as the scale the
    -- interest materiality floor is judged against, so the fixture carries it.
    CREATE TEMP TABLE tmp_pf (security_id int, period_end date, fiscal_period text,
                              filed date, eps numeric, free_cash_flow numeric,
                              operating_income numeric, depreciation_amortization numeric,
                              interest_expense numeric, revenue numeric,
                              gross_profit numeric, cost_of_revenue numeric, net_income numeric,
                              operating_cash_flow numeric, capital_expenditures numeric);
    CREATE TEMP TABLE tmp_mkt (security_id int, observation_date date, close numeric);
    -- Security 1: the quarter ending 2021-03-31 is filed twice under two
    -- quarterly labels, and the later filing restates EPS upward. A third
    -- label files later still but reports no EPS at all.
    INSERT INTO tmp_pf (security_id, period_end, fiscal_period, filed,
                           eps, free_cash_flow) VALUES
     (1,'2021-03-31','Q1','2021-05-01',1.00,10),
     (1,'2021-03-31','Q3','2021-05-02',1.50,10),
     (1,'2021-03-31','Q4','2021-06-01',NULL,10),
     (1,'2020-12-31','Q4','2021-02-01',1.00,10),
     (1,'2020-09-30','Q3','2020-11-01',1.00,10),
     (1,'2020-06-30','Q2','2020-08-01',1.00,10),
     (2,'2021-03-31','Q1','2021-05-01',2.00,20),
     (2,'2020-12-31','Q4','2021-02-01',2.00,20);
    INSERT INTO tmp_mkt VALUES (1,'2021-06-01',10),(2,'2021-06-01',10);
    """
    slots = (
        cte
        + """
    SELECT count(*) n, count(DISTINCT v.period_end) d,
           count(*) FILTER (WHERE v.value IS NULL) nulls
    FROM tmp_mkt f JOIN q_vintages v ON v.security_id=f.security_id
         AND f.observation_date>=v.filed
         AND (v.filed_next IS NULL OR f.observation_date<v.filed_next)
    WHERE v.metric='eps' AND f.security_id=1"""
    )
    ttm = (
        cte
        + """
    SELECT coalesce(eps_ttm::text,'NULL'), coalesce(fcf_ttm::text,'NULL')
    FROM q WHERE security_id={s}"""
    )

    with engine.connect() as conn:
        conn.execute(text(ddl))
        n, distinct_periods, nulls = conn.execute(text(slots), params).fetchone()
        eps1, fcf1 = conn.execute(text(ttm.format(s=1)), params).fetchone()
        eps2, fcf2 = conn.execute(text(ttm.format(s=2)), params).fetchone()

    # Four distinct quarters, each occupying exactly one slot, none masked by the
    # label that reported the period without a value.
    assert n == 4 and distinct_periods == 4
    assert nulls == 0
    # 1.50 (the later filing) + 1.00 + 1.00 + 1.00. Reading 4.25 or 5.50 would
    # mean a quarter was counted twice; 3.50 would mean the restatement was lost.
    assert eps1 == "4.50", f"quarter double counted or restatement lost: {eps1}"
    assert fcf1 == "40"
    # A filer with fewer than four reported quarters sums what it has.
    assert eps2 == "4.00" and fcf2 == "40"


def test_a_vintage_is_not_visible_before_its_period_has_ended():
    """A filed date earlier than period_end is a bad date, not an early filing.

    966 stored rows are filed before the period they report ends, 612 of them by
    more than a year. Taking filed at face value shows the figures to observation
    dates before the period existed, which is look-ahead into the future of the
    issuer. The vintage has to wait for period_end.
    """
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    cte = (
        _production_quarterly_ctes()
        .replace("fundamentals.periodic_financials pf", "tmp_pf pf")
        .replace("raw.market_data", "tmp_mkt")
    )
    params = {"date_from": date(2000, 1, 1), "date_to": date(2100, 1, 1)}
    ddl = """
    DROP TABLE IF EXISTS tmp_pf, tmp_mkt;
    CREATE TEMP TABLE tmp_pf (security_id int, period_end date, fiscal_period text,
                              filed date, eps numeric, free_cash_flow numeric,
                              operating_income numeric, depreciation_amortization numeric,
                              interest_expense numeric, revenue numeric,
                              gross_profit numeric, cost_of_revenue numeric, net_income numeric,
                              operating_cash_flow numeric, capital_expenditures numeric);
    CREATE TEMP TABLE tmp_mkt (security_id int, observation_date date, close numeric);
    -- Filed 75 days before its own period ends. Visible from 2021-03-31, not 2021-01-15.
    INSERT INTO tmp_pf (security_id, period_end, fiscal_period, filed, eps) VALUES
     (1,'2021-03-31','Q1','2021-01-15',1.00);
    INSERT INTO tmp_mkt VALUES (1,'2021-02-01',10),(1,'2021-04-01',10);
    """
    query = (
        cte
        + """
    SELECT observation_date::text, coalesce(eps_ttm::text,'NULL') FROM q
    ORDER BY observation_date"""
    )

    with engine.connect() as conn:
        conn.execute(text(ddl))
        rows = dict(conn.execute(text(query), params).fetchall())

    assert rows.get("2021-02-01", "NULL") == "NULL", (
        "a quarter filed before it ended was visible while the period was still open"
    )
    assert rows["2021-04-01"] == "1.00"


def _production_return_ctes():
    """The dividend, return and trailing-window CTEs of the real feature query.

    Extracted rather than restated, for the reason _production_quarterly_ctes is.
    """
    import inspect

    from src.crispdm import features

    src = inspect.getsource(features.build_features)
    block = src[
        src.index("    WITH d AS (") : src.index(
            "    -- One annual dividend per (security, as_of_date)"
        )
    ]
    block = "\n".join(line[4:] if line.startswith("    ") else line for line in block.splitlines())
    return block.rstrip().rstrip(",").rstrip() + "\n"


def test_momentum_is_total_return_and_ignores_impossible_payments():
    """Price momentum undercounts a payer by exactly the income it paid.

    The series below are flat at 100 for 40 days, then 98. A 2.00 dividend goes
    ex on the day the price drops, so a holder lost nothing: total return is 0
    where price return is -2%. The same data with no dividend must stay at -2%
    (no dividend is not a reason to invent one), and a 1,000,000 per-share
    "dividend" -- the stored data has one -- must be ignored rather than turn the
    return into a number nobody earned.
    """
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    cte = (
        _production_return_ctes()
        .replace("raw.market_data", "tmp_mkt")
        .replace("raw.dividend_data", "tmp_div")
    )
    ddl = """
    DROP TABLE IF EXISTS tmp_mkt, tmp_div;
    CREATE TEMP TABLE tmp_mkt (security_id int, observation_date date, close numeric);
    CREATE TEMP TABLE tmp_div (security_id int, ex_dividend_date date, amount numeric,
                               provider text, frequency text, concept text,
                               adjusted_amount numeric);
    -- 71 daily rows per security: price 100 through day 39, 98 from day 40.
    INSERT INTO tmp_mkt
    SELECT s, DATE '2021-01-01' + n, CASE WHEN n < 40 THEN 100 ELSE 98 END
    FROM generate_series(1, 4) s, generate_series(0, 70) n;
    -- Security 4 has no price row on the ex-date itself (a gap in the stored history).
    DELETE FROM tmp_mkt WHERE security_id = 4 AND observation_date = DATE '2021-01-01' + 40;
    INSERT INTO tmp_div VALUES
      (1, DATE '2021-01-01' + 40, 2, 'OPENBB', 'Annual', NULL, NULL),
      (4, DATE '2021-01-01' + 40, 2, 'OPENBB', 'Annual', NULL, NULL),
      (3, DATE '2021-01-01' + 40, 1000000, 'OPENBB', 'Annual', NULL, NULL);
    UPDATE tmp_mkt SET close = 100 WHERE security_id = 3;
    """
    query = (
        cte
        + """
    SELECT security_id, EXP(tr_sum_63) - 1 AS tr63, tr_samples_63
    FROM p WHERE observation_date = DATE '2021-01-01' + 70 ORDER BY security_id"""
    )

    with engine.connect() as conn:
        conn.execute(text(ddl))
        rows = {
            r[0]: (float(r[1]), r[2])
            for r in conn.execute(text(query), {"max_payment_ratio": 1.0}).fetchall()
        }

    assert rows[1][1] == 63 and rows[2][1] == 63
    # Dividend credited on the day the price fell by it: nothing lost.
    assert abs(rows[1][0]) < 1e-9, f"dividend not credited: {rows[1][0]}"
    # Security 2 pays nothing, so total return is the price return.
    assert abs(rows[2][0] - (98 / 100 - 1)) < 1e-9, f"invented a dividend: {rows[2][0]}"
    # The impossible payment is ignored, not compounded.
    assert abs(rows[3][0]) < 1e-9, f"impossible dividend reached the return: {rows[3][0]}"
    # An ex-date with no price row is booked to the next observation, not dropped.
    assert abs(rows[4][0]) < 1e-9, f"dividend on a non-trading day was lost: {rows[4][0]}"


def _fact(concept, value, *, end="2025-12-31", filed="2026-02-01", fp="FY", fy=2025):
    """One us-gaap fact record in the companyfacts payload shape."""
    return {"units": {"USD": [{"val": value, "end": end, "fy": fy, "fp": fp, "filed": filed}]}}


def extract_periodic_fundamentals_fallback(payload):
    """Extract the single row from a one-concept payload."""
    rows = extract_periodic_financials(payload)
    assert len(rows) == 1
    return (
        rows[0]["depreciation_amortization"]
        if "DepreciationAndAmortization" in str(payload["facts"]["us-gaap"])
        else rows[0]["interest_expense"]
    )


def test_new_leverage_concepts_are_extracted():
    """V0011's three inputs have to reach the table for the ratios to exist.

    They were retired as "no D&A/EBITDA in schema" and "no interest expense
    line in any table". Both reasons described the materialised columns and not
    the payload, so the extractor now has to actually pull these concepts out.
    """
    from src.crispdm.xbrl_tags import PERIODIC_FINANCIAL_CONCEPTS

    for concept in (
        "DepreciationDepletionAndAmortization",
        "InterestExpense",
        "CommonStockSharesOutstanding",
    ):
        assert concept in PERIODIC_FINANCIAL_CONCEPTS, concept

    facts = {
        "facts": {
            "us-gaap": {
                "OperatingIncomeLoss": _fact("OperatingIncomeLoss", 400),
                "DepreciationDepletionAndAmortization": _fact(
                    "DepreciationDepletionAndAmortization", 100
                ),
                "InterestExpense": _fact("InterestExpense", 40),
                "CommonStockSharesOutstanding": _fact("CommonStockSharesOutstanding", 1000),
                "LongTermDebt": _fact("LongTermDebt", 2500),
            }
        }
    }
    row = extract_periodic_financials(facts)[0]
    assert row["depreciation_amortization"] == 100
    assert row["interest_expense"] == 40
    assert row["shares_outstanding"] == 1000
    assert row["operating_income"] == 400
    assert row["debt"] == 2500


def test_leverage_concepts_fall_back_and_prefer_the_canonical_tag():
    """Filers name the same fact differently, and sometimes report it twice.

    A filer that tags both the canonical and the variant must not have the two
    summed; the canonical tag wins. One that reports only the variant must still
    be captured, because leaving it NULL would be indistinguishable from the
    filer not disclosing D&A at all.
    """
    facts = {
        "facts": {
            "us-gaap": {
                "DepreciationDepletionAndAmortization": _fact(
                    "DepreciationDepletionAndAmortization", 100
                ),
                "DepreciationAndAmortization": _fact("DepreciationAndAmortization", 999),
            }
        }
    }
    assert extract_periodic_financials(facts)[0]["depreciation_amortization"] == 100

    variant_only = {
        "facts": {
            "us-gaap": {"DepreciationAndAmortization": _fact("DepreciationAndAmortization", 75)}
        }
    }
    assert extract_periodic_fundamentals_fallback(variant_only) == 75


def test_interest_expense_prefers_the_standalone_line_over_the_combined_one():
    """InterestAndDebtExpense mixes in debt principal; it is a last resort."""
    both = {
        "facts": {
            "us-gaap": {
                "InterestExpense": _fact("InterestExpense", 40),
                "InterestAndDebtExpense": _fact("InterestAndDebtExpense", 500),
            }
        }
    }
    assert extract_periodic_financials(both)[0]["interest_expense"] == 40

    combined_only = {
        "facts": {"us-gaap": {"InterestAndDebtExpense": _fact("InterestAndDebtExpense", 500)}}
    }
    assert extract_periodic_fundamentals_fallback(combined_only) == 500


def test_dei_shares_concept_is_deliberately_not_used():
    """dei:EntityCommonStockSharesOutstanding has the best coverage but is in
    another taxonomy, and this extractor reads the us-gaap slice alone.

    Asserted so the omission is a recorded decision: if a future change reads
    dei, this test says to revisit the coverage claim in V0011's comment rather
    than leaving the comment quietly wrong.
    """
    from src.crispdm.xbrl_tags import PERIODIC_FINANCIAL_CONCEPT_TAGS, PERIODIC_FINANCIAL_CONCEPTS

    shares = PERIODIC_FINANCIAL_CONCEPT_TAGS["shares_outstanding"]
    assert "EntityCommonStockSharesOutstanding" not in shares
    assert all(not c.startswith("dei:") for c in shares)
    assert "EntityCommonStockSharesOutstanding" not in PERIODIC_FINANCIAL_CONCEPTS


def test_leverage_metrics_join_the_per_metric_chain_not_a_shared_one():
    """Each of the three new metrics must be ranked on its own four periods.

    They were added as UNION ALL branches of q_streams, which is what buys them
    the per-metric vintage chain. If they were ever collapsed onto a shared
    period set they would inherit the masking defect documented above: a filer
    that discloses D&A in three of four quarters would have the quarter
    without it terminate the interval, and the trailing figure would read NULL
    from that date on -- which is indistinguishable from a filer that discloses
    no D&A at all, and would be indistinguishable here.
    """
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    cte = (
        _production_quarterly_ctes()
        .replace("fundamentals.periodic_financials pf", "tmp_pf pf")
        .replace("raw.market_data", "tmp_mkt")
    )
    params = {"date_from": date(2000, 1, 1), "date_to": date(2100, 1, 1)}
    ddl = """
    DROP TABLE IF EXISTS tmp_pf, tmp_mkt;
    -- revenue is not a feature; the feature query reads it only as the scale the
    -- interest materiality floor is judged against, so the fixture carries it.
    CREATE TEMP TABLE tmp_pf (security_id int, period_end date, fiscal_period text,
                              filed date, eps numeric, free_cash_flow numeric,
                              operating_income numeric, depreciation_amortization numeric,
                              interest_expense numeric, revenue numeric,
                              gross_profit numeric, cost_of_revenue numeric, net_income numeric,
                              operating_cash_flow numeric, capital_expenditures numeric);
    CREATE TEMP TABLE tmp_mkt (security_id int, observation_date date, close numeric);
    -- Four quarters. D&A is disclosed in the first three and omitted from the
    -- fourth; every quarter still reports EPS and operating income.
    -- Revenue is populated so the interest materiality floor is actually
    -- exercised end to end: 5 of interest against 1,000 of revenue lands
    -- exactly on the floor, so the ratio must survive. A fixture that left
    -- revenue NULL would take the keep-unknown-revenue branch instead and
    -- prove nothing about the threshold.
    INSERT INTO tmp_pf (security_id, period_end, fiscal_period, filed,
                        eps, free_cash_flow, operating_income,
                        depreciation_amortization, interest_expense, revenue) VALUES
     (1,'2021-03-31','Q1','2021-05-01',1.00,10,100,25,5,250),
     (1,'2020-12-31','Q4','2021-02-01',1.00,10,100,25,5,250),
     (1,'2020-09-30','Q3','2020-11-01',1.00,10,100,25,5,250),
     (1,'2020-06-30','Q2','2020-08-01',1.00,10,100,NULL,5,250);
    INSERT INTO tmp_mkt VALUES (1,'2021-06-01',10);
    """
    totals = (
        cte
        + """
    -- `q` has already collapsed each metric to its trailing sum, so the
    -- assertion is on the per-metric totals it resolved, not on the raw
    -- stream: a shared period set would show da_ttm NULL here.
    SELECT eps_ttm, oi_ttm, da_ttm, int_ttm, rev_ttm
    FROM q
    WHERE q.security_id=1
    """
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(ddl)
        row = conn.execute(text(totals), params).mappings().one()
    # EPS and operating income have all four quarters; D&A has three and must
    # sum those three rather than being nulled by the quarter that omitted it.
    assert row["eps_ttm"] == 4.0
    # revenue rides the same per-metric chain, which is what lets the interest
    # materiality floor be evaluated in Python rather than being blind to scale
    assert row["rev_ttm"] == 1000.0
    assert row["oi_ttm"] == 400
    assert row["da_ttm"] == 75
    assert row["int_ttm"] == 20


def _production_fy_ctes():
    """The annual-fallback CTEs of the real feature query, verbatim.

    Same contract as :func:`_production_quarterly_ctes` and for the same
    reason, and it exists because the quarterly slice stops where the annual
    path begins. The V0011 leverage inputs are read on both paths: the
    quarterly path when four quarters are available, and this one as the
    fallback for filers that do not break out quarters, plus `debt`, which is a
    balance and is only ever read from here.
    """
    import inspect

    from src.crispdm import features

    src = inspect.getsource(features.build_features)
    # rindex, not index: the final projection is the last ``SELECT p.security_id,``
    # in the source, and the price CTEs above carry the same prefix four times.
    block = src[src.index("    fy_vintages AS (") : src.rindex("    SELECT p.security_id,")]
    block = "\n".join(line[4:] if line.startswith("    ") else line for line in block.splitlines())
    return "WITH " + block.rstrip().rstrip(",").rstrip() + "\n"


def test_annual_fallback_carries_the_leverage_inputs_and_debt():
    """A filer that reports only annual figures must still yield both ratios.

    Debt is a balance, so it is never summed across quarters and exists only on
    this path. The assertion that matters most is the last one: the latest fiscal
    period that was public on the observation date wins, and an earlier vintage
    must not overwrite it, or every ratio would be computed against a stale
    balance sheet.
    """
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    cte = _production_fy_ctes().replace("raw.market_data", "tmp_mkt")
    params = {"date_from": date(2000, 1, 1), "date_to": date(2100, 1, 1)}
    ddl = """
    DROP TABLE IF EXISTS tmp_mkt;
    CREATE TEMP TABLE tmp_mkt (security_id int, observation_date date, close numeric);
    -- Two annual periods, the later one restating a lower debt. Both were
    -- public before the observation date, so the later one must win.
    CREATE TEMP TABLE fy_pf (security_id int, period_end date, fiscal_period text,
                             filed date, eps numeric, free_cash_flow numeric,
                             operating_income numeric, depreciation_amortization numeric,
                             interest_expense numeric, debt numeric, revenue numeric,
                             cash numeric, current_liabilities numeric,
                             debt_maturing_12m numeric, debt_maturing_year_2 numeric,
                             committed_undrawn_facility numeric,
                             -- V0068: the FY fallback flows and the balance-sheet
                             -- levels the new ratios read on this path.
                             gross_profit numeric, cost_of_revenue numeric, net_income numeric,
                             operating_cash_flow numeric, capital_expenditures numeric,
                             equity numeric, current_assets numeric,
                             shares_outstanding numeric);
    INSERT INTO fy_pf
        (security_id, period_end, fiscal_period, filed, eps, free_cash_flow,
         operating_income, depreciation_amortization, interest_expense, debt,
         revenue, cash, current_liabilities, debt_maturing_12m, debt_maturing_year_2)
    VALUES
     (1,'2020-12-31','FY','2021-02-01',1.00,10,100,20,10,3000,5000,900,400,300,700),
     (1,'2021-12-31','FY','2022-02-01',1.20,12,150,30,15,2400,6000,1200,500,450,650);
    INSERT INTO tmp_mkt VALUES (1,'2022-06-01',10);
    """
    # The CTE reads fundamentals.periodic_financials by name; point it at the
    # fixture the same way the quarterly test does.
    cte = cte.replace("fundamentals.periodic_financials pf", "fy_pf pf")
    query = cte + "SELECT * FROM fy WHERE security_id=1"
    with engine.begin() as conn:
        conn.exec_driver_sql(ddl)
        row = conn.execute(text(query), params).mappings().one()
    assert row["period_end"] == date(2021, 12, 31)
    assert row["oi_fy"] == 150
    assert row["da_fy"] == 30
    assert row["int_fy"] == 15
    assert row["debt_fy"] == 2400
    # V0016 liquidity legs, resolved on the same vintage discipline: the later
    # filing wins, so the restating period's figures are the ones carried.
    assert row["cash_fy"] == 1200
    assert row["current_liabilities_fy"] == 500
    # V0018 maturity ladder, same vintage discipline: the restating 2021
    # filing carries the figures, not the 2020 ones.
    assert row["debt_maturing_12m_fy"] == 450
    assert row["debt_maturing_year_2_fy"] == 650


def test_main_fails_when_the_stage_writes_nothing(monkeypatch, capsys):
    """A stage that processed candidates and wrote nothing must exit non-zero.

    This is the hole that let a 6-hour nightly report success while writing
    nothing: main() discarded the return value and returned 0 unconditionally,
    so a missing migration surfaced as exit 0, a success tick, and an audit row
    saying the run was ok. 8,350 errors and 0 rows were logged as a clean run.
    """
    from scripts import populate_fundamentals as pf

    monkeypatch.setattr(
        pf,
        "populate_fundamentals",
        lambda **kw: pf.FundamentalsResult(candidates=8350, securities=0, periods=0, errors=8350),
    )
    monkeypatch.setattr("sys.argv", ["populate_fundamentals"])
    assert pf.main() == 1


def test_main_succeeds_when_rows_were_written(monkeypatch):
    """The guard must not fire on a healthy run that has a few bad tickers."""
    from scripts import populate_fundamentals as pf

    monkeypatch.setattr(
        pf,
        "populate_fundamentals",
        lambda **kw: pf.FundamentalsResult(candidates=100, securities=98, periods=4000, errors=2),
    )
    monkeypatch.setattr("sys.argv", ["populate_fundamentals"])
    assert pf.main() == 0


def test_a_failing_issuer_does_not_abort_the_remaining_ones(monkeypatch):
    """One bad statement must not turn into one error per remaining candidate.

    The whole stage runs in a single transaction for throughput, so without a
    per-issuer savepoint the first failing statement aborts it and every later
    statement then fails with InFailedSqlTransaction. That is how a single
    UndefinedColumn surfaced as 8,350 errors, each pointing at a different
    innocent ticker.

    The failure here has to be a *real* SQL error. A Python exception raised
    before any statement is executed does not abort the transaction, so a
    stubbed upsert would pass with or without the savepoint and prove nothing --
    which is exactly what the first version of this test did.
    """
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text as sql_text

    from scripts import populate_fundamentals as pf

    candidates = [
        {"security_id": 1, "ticker": "BAD", "us_gaap": {}},
        {"security_id": 2, "ticker": "GOOD", "us_gaap": {}},
    ]
    survived = []

    def fake_extract(payload, **kwargs):
        return [{"period_end": date(2024, 12, 31), "fiscal_year": 2024, "eps": 1.0}]

    def fake_upsert(conn, security_id, rows):
        if security_id == 1:
            # The real failure mode: a statement the server rejects. The
            # transaction is now aborted until something rolls it back.
            conn.execute(sql_text("SELECT no_such_column_in_this_schema FROM (SELECT 1) t"))
        conn.execute(sql_text("SELECT 1"))
        survived.append(security_id)
        return len(rows)

    monkeypatch.setattr(pf, "count_candidates", lambda *a, **k: len(candidates))
    monkeypatch.setattr(pf, "load_candidates", lambda *a, **k: candidates)
    monkeypatch.setattr(pf, "extract_periodic_financials", fake_extract)
    monkeypatch.setattr(pf, "upsert_periodic_financials", fake_upsert)

    result = pf.populate_fundamentals()
    assert result.candidates == 2
    # Exactly one error, not two. Amplification to one-per-candidate is the
    # defect this pins.
    assert result.errors == 1, f"expected 1 error, got {result.errors}: transaction was poisoned"
    assert survived == [2]
    assert result.periods == 1


class _CandidateResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar_one(self):
        return 0


class _CandidateConnection:
    def __init__(self):
        self.statements = []
        self.params = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        return _CandidateResult([])


def test_load_candidates_scopes_to_active_dividend_securities():
    """The CIK fan-out must not write fundamentals for deactivated or
    non-dividend siblings sharing the issuer's CIK."""
    from scripts import populate_fundamentals as pf

    conn = _CandidateConnection()

    pf.load_candidates(conn)

    sql = conn.statements[0]
    assert "s.active = TRUE" in sql
    assert "s.dividend = TRUE" in sql


def test_load_candidates_advances_the_keyset_cursor():
    """A batch must resume strictly after the previous batch's last row."""
    from scripts import populate_fundamentals as pf

    conn = _CandidateConnection()
    pf.load_candidates(conn, after_security_id="cursor-uuid")

    assert "s.security_id > :after_security_id" in conn.statements[0]
    assert conn.params[0]["after_security_id"] == "cursor-uuid"
    # Without a cursor the filter must not appear (first page).
    conn2 = _CandidateConnection()
    pf.load_candidates(conn2)
    assert "s.security_id >" not in conn2.statements[0]


def test_count_candidates_uses_the_same_universe_filter():
    """count(*) drives the batching loop, so it must agree with the load."""
    from scripts import populate_fundamentals as pf

    conn = _CandidateConnection()
    pf.count_candidates(conn, tickers=["aapl"])

    sql = conn.statements[0]
    assert "s.active = TRUE" in sql
    assert "s.dividend = TRUE" in sql
    assert "UPPER(s.ticker) = ANY(:tickers)" in sql
    assert conn.params[0]["tickers"] == ["AAPL"]


class _FakeNested:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def begin_nested(self):
        return _FakeNested()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    """Enough of src.crispdm.db.engine for the batching loop."""

    def __init__(self):
        self.begins = 0

    def connect(self):
        return _FakeConn()

    def begin(self):
        self.begins += 1
        return _FakeConn()


def test_populate_fundamentals_paginates_in_batches(monkeypatch, capsys):
    """The stage must page the universe with a keyset, one transaction per batch.

    The stage used to materialize every issuer payload with .all() before
    processing any of them; the full universe is gigabytes of jsonb, which
    pinned the process against the unit's MemoryMax and left it thrashing in
    reclaim for hours with a transaction open the whole time. Each batch must
    start after the previous batch's last security_id, and each batch must run
    in its own transaction so the stage commits progress incrementally.
    """
    from scripts import populate_fundamentals as pf

    universe = [
        {"security_id": i, "ticker": f"T{i}", "cik": f"{i:010d}", "us_gaap": {}}
        for i in range(1, 6)
    ]
    engine = _FakeEngine()
    loads = []
    upserted = []

    def fake_load(
        conn,
        tickers=None,
        limit=None,
        after_security_id=None,
        include_historical=False,
        historical_only=False,
    ):
        loads.append((after_security_id, limit))
        rows = [
            c for c in universe if after_security_id is None or c["security_id"] > after_security_id
        ]
        return rows[:limit]

    monkeypatch.setattr(pf, "engine", engine)
    monkeypatch.setattr(pf, "count_candidates", lambda *a, **k: len(universe))
    monkeypatch.setattr(pf, "load_candidates", fake_load)
    monkeypatch.setattr(
        pf,
        "extract_periodic_financials",
        lambda payload, **kwargs: [{"period_end": None, "eps": 1.0}],
    )
    monkeypatch.setattr(
        pf,
        "upsert_periodic_financials",
        lambda conn, security_id, rows: (upserted.append(security_id), len(rows))[1],
    )

    result = pf.populate_fundamentals(batch_size=2)

    # Keyset chain: first page from the start, each later page resumes strictly
    # after the previous page's last row, and the limit shrinks with the tail.
    assert loads == [(None, 2), (2, 2), (4, 1)]
    # One transaction per batch, not one for the whole stage.
    assert engine.begins == 3
    # Every candidate processed exactly once, in security_id order.
    assert upserted == [1, 2, 3, 4, 5]
    assert result.candidates == 5
    assert result.securities == 5
    assert result.periods == 5
    assert result.errors == 0
    out = capsys.readouterr().out
    assert "2/5 candidates processed" in out
    assert "5/5 candidates processed" in out


def test_empty_universe_short_circuits_without_loading(monkeypatch):
    """count(*) = 0 must not open a batch transaction or call load at all."""
    from scripts import populate_fundamentals as pf

    engine = _FakeEngine()

    def fail_load(*a, **k):
        raise AssertionError("load_candidates must not run for an empty universe")

    monkeypatch.setattr(pf, "engine", engine)
    monkeypatch.setattr(pf, "count_candidates", lambda *a, **k: 0)
    monkeypatch.setattr(pf, "load_candidates", fail_load)

    result = pf.populate_fundamentals()

    assert result.candidates == 0
    assert result.periods == 0
    assert engine.begins == 0


def test_a_count_overestimate_terminates_instead_of_looping(monkeypatch):
    """If count is stale and the keyset runs dry, the loop must stop.

    Without the empty-batch break the stage would spin forever re-asking for
    rows that no longer exist.
    """
    from scripts import populate_fundamentals as pf

    universe = [
        {"security_id": i, "ticker": f"T{i}", "cik": f"{i:010d}", "us_gaap": {}} for i in (1, 2)
    ]
    engine = _FakeEngine()
    loads = []

    def fake_load(
        conn,
        tickers=None,
        limit=None,
        after_security_id=None,
        include_historical=False,
        historical_only=False,
    ):
        loads.append(after_security_id)
        rows = [
            c for c in universe if after_security_id is None or c["security_id"] > after_security_id
        ]
        return rows[:limit]

    monkeypatch.setattr(pf, "engine", engine)
    monkeypatch.setattr(pf, "count_candidates", lambda *a, **k: 5)  # stale: universe has 2
    monkeypatch.setattr(pf, "load_candidates", fake_load)
    monkeypatch.setattr(pf, "extract_periodic_financials", lambda payload, **kwargs: [{"eps": 1.0}])
    monkeypatch.setattr(pf, "upsert_periodic_financials", lambda *a: 1)

    result = pf.populate_fundamentals(batch_size=2)

    assert loads == [None, 2]  # second page came back empty and stopped the loop
    assert result.candidates == 5  # reported count is what count(*) claimed
    assert result.periods == 2  # only real rows were processed
