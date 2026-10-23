"""The peer base rate: what the sample is, and what it is allowed to claim.

The base rate is the number the worksheet's step 15 reports, so the tests here are
about the decisions behind it: which peers are in the sample, which setups count as
similar, and what the caveats have to say. A rate that is statistically neat and
misleading is the failure mode, so the disclosure is tested as carefully as the
arithmetic.
"""

import pandas as pd
import pytest

from src.crispdm import analogs


def _frame(rows):
    return pd.DataFrame(rows)


def _sample_row(ticker, as_of_date, total_return, yield_=0.03, coverage=2.0, industry="Peers"):
    return {
        "as_of_date": as_of_date,
        "ticker": ticker,
        "industry": industry,
        "dividend_yield": yield_,
        "dividend_coverage": coverage,
        "total_return": total_return,
        "price_return": total_return - 0.02,
        "dividend_return": 0.02,
    }


def _query_with(rows, industry="Peers", current=(0.03, 2.0)):
    """A query callable that answers the three reads the engine makes.

    The sample query names every table the other two name, so it is matched
    first: the industry read and the sample read both mention
    ``clean.ticker_profile``.
    """
    calls = []

    def query(sql, params=None):
        calls.append(sql)
        params = params or {}
        if "model.forward_returns" in sql:
            return _frame(rows)
        if "clean.ticker_profile" in sql:
            return _frame([{"industry": industry}]) if industry else _frame([])
        if "model.features" in sql:
            if current is None:
                return _frame([])
            return _frame([{"dividend_yield": current[0], "dividend_coverage": current[1]}])
        return _frame(rows)

    query.calls = calls
    return query


def test_a_security_without_an_industry_gets_no_base_rate():
    base_rate = analogs.peer_base_rate(
        _query_with([], industry=None), "sid-1", "2026-10-20", ticker="TEST"
    )

    assert base_rate.industry is None
    assert base_rate.observations == 0
    assert base_rate.pct_positive is None
    assert base_rate.base_rate_text == ""
    assert "no peer sample" in base_rate.caveats[0]


def test_the_base_rate_is_the_share_of_positive_observations():
    rows = [_sample_row("A", "2020-01-02", 0.10), _sample_row("B", "2020-02-03", -0.05)]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert base_rate.observations == 2
    assert base_rate.pct_positive == pytest.approx(50.0)


def test_the_base_rate_field_holds_one_percentage():
    rows = [_sample_row("A", "2020-01-02", 0.10), _sample_row("B", "2020-02-03", -0.05)]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert base_rate.base_rate_text == "50%"


def test_the_sample_is_taken_monthly():
    query = _query_with([_sample_row("A", "2020-01-02", 0.10)])

    analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    sample_sql = next(sql for sql in query.calls if "model.forward_returns" in sql)
    assert "date_trunc('month', as_of_date)" in sample_sql
    assert "min(as_of_date) AS as_of_date" in sample_sql


def test_the_sample_excludes_rows_the_model_flagged_as_unusable():
    query = _query_with([_sample_row("A", "2020-01-02", 0.10)])

    analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    sample_sql = next(sql for sql in query.calls if "model.forward_returns" in sql)
    assert "ft.price_quality = :price_quality" in sample_sql
    assert "ft.current_price >= :min_price" in sample_sql


def test_the_sample_scores_each_peer_on_the_conditions_of_its_own_date():
    query = _query_with([_sample_row("A", "2020-01-02", 0.10)])

    analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    sample_sql = next(sql for sql in query.calls if "model.forward_returns" in sql)
    assert "ft.as_of_date = fr.as_of_date" in sample_sql


def test_only_peers_close_to_the_current_conditions_count_as_similar():
    rows = [
        _sample_row("CLOSE", "2020-01-02", 0.10, yield_=0.03, coverage=2.0),
        _sample_row("FAR", "2020-02-03", -0.20, yield_=0.10, coverage=2.0),
    ]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert [item.ticker for item in base_rate.similar] == ["CLOSE"]
    assert base_rate.observations == 1
    assert base_rate.pct_positive == pytest.approx(100.0)


def test_the_similarity_band_is_relative():
    # A target yield of 0.04 and a peer at 0.02 is within 50%; a peer at 0.08 is not.
    assert analogs._within(0.02, 0.04, 0.5) is True
    assert analogs._within(0.06, 0.04, 0.5) is True
    assert analogs._within(0.08, 0.04, 0.5) is False


def test_a_peer_with_an_unrecorded_condition_is_not_a_match():
    rows = [_sample_row("A", "2020-01-02", 0.10, yield_=None)]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert base_rate.similar == []
    assert base_rate.observations == 1


def test_the_wider_peer_group_is_reported_alongside_the_matched_sample():
    rows = [
        _sample_row("CLOSE", "2020-01-02", 0.10),
        _sample_row("FAR", "2020-02-03", -0.20, yield_=0.10),
    ]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert base_rate.peer.observations == 2
    assert base_rate.peer.pct_positive == pytest.approx(50.0)
    assert base_rate.observations == 1


def test_the_derived_metrics_describe_the_similar_sample():
    # A fixed set of returns, so the count, rate, average, median and tails are
    # all pinned to numbers rather than "not None".
    rows = [
        _sample_row("A", "2020-01-02", -0.20),
        _sample_row("B", "2020-02-03", -0.05),
        _sample_row("C", "2020-03-04", 0.0),
        _sample_row("D", "2020-04-02", 0.10),
        _sample_row("E", "2020-05-04", 0.30),
    ]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert base_rate.observations == 5
    assert base_rate.pct_positive == pytest.approx(40.0)
    assert base_rate.avg_return == pytest.approx(0.03)
    assert base_rate.median_return == pytest.approx(0.0)
    assert base_rate.p05_return == pytest.approx(-0.17)
    assert base_rate.p95_return == pytest.approx(0.26)


def test_the_derived_metrics_of_the_wider_peer_group_cover_every_setup():
    # The two FAR rows are outside the similarity band, so they move the peer
    # group's distribution without touching the headline similar sample.
    rows = [
        _sample_row("CLOSE", "2020-01-02", 0.10),
        _sample_row("CLOSE", "2020-02-03", -0.05),
        _sample_row("FAR", "2020-03-04", -0.20, yield_=0.10),
        _sample_row("FAR", "2020-04-02", 0.30, yield_=0.10),
    ]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert base_rate.observations == 2
    assert base_rate.peer.observations == 4
    assert base_rate.peer.pct_positive == pytest.approx(50.0)
    assert base_rate.peer.avg_return == pytest.approx(0.0375)
    assert base_rate.peer.median_return == pytest.approx(0.025)
    assert base_rate.peer.p05_return == pytest.approx(-0.1775)
    assert base_rate.peer.p95_return == pytest.approx(0.27)


def test_a_flat_return_is_not_counted_as_positive():
    rows = [
        _sample_row("FLAT", "2020-01-02", 0.0),
        _sample_row("UP", "2020-02-03", 0.10),
    ]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert base_rate.pct_positive == pytest.approx(50.0)
    assert [item.outcome for item in base_rate.similar] == ["Negative", "Positive"]


def test_the_base_rate_text_rounds_to_a_whole_percent():
    rows = [
        _sample_row("A", "2020-01-02", 0.10),
        _sample_row("B", "2020-02-03", -0.05),
        _sample_row("C", "2020-03-04", -0.02),
    ]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert base_rate.pct_positive == pytest.approx(100 / 3)
    assert base_rate.base_rate_text == "33%"


def test_the_caveats_say_what_the_number_cannot_be_used_for():
    query = _query_with([_sample_row("A", "2020-01-02", 0.10)])

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    joined = " ".join(base_rate.caveats)
    assert "current snapshot" in joined
    assert "not a validated forecast" in joined
    assert "252 trading days" in joined


def test_a_target_without_conditions_falls_back_to_the_whole_peer_group():
    rows = [_sample_row("A", "2020-01-02", 0.10, yield_=0.10)]
    query = _query_with(rows, current=None)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")

    assert base_rate.observations == 1
    assert base_rate.similar == []
    assert any("unavailable" in caveat for caveat in base_rate.caveats)


def test_the_similar_setups_table_carries_the_worksheet_columns():
    rows = [
        _sample_row("A", "2020-01-02", 0.10),
        _sample_row("B", "2020-02-03", -0.05),
        _sample_row("C", "2020-03-04", 0.02),
    ]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")
    table = analogs.similar_setups_table(base_rate)

    assert table.splitlines()[0] == "| Date | Conditions | Forward 12M total return | Outcome |"
    assert "Positive" in table
    assert "Negative" in table


def test_the_table_spreads_its_rows_across_the_sample():
    rows = [_sample_row(f"T{index}", f"2020-{index % 12 + 1:02d}-02", 0.10) for index in range(24)]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")
    table = analogs.similar_setups_table(base_rate, rows=6)

    body = [line for line in table.splitlines()[2:] if line.startswith("|")]
    assert len(body) == 6
    dates = [line.split("|")[1].strip() for line in body]
    assert dates == sorted(dates)


def test_the_table_says_so_when_there_is_no_sample():
    query = _query_with([])

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")
    table = analogs.similar_setups_table(base_rate)

    assert "not available" in table
    assert "N/A" in table


def test_the_payload_carries_the_rate_the_count_and_the_caveats():
    rows = [_sample_row("A", "2020-01-02", 0.10), _sample_row("B", "2020-02-03", -0.05)]
    query = _query_with(rows)

    base_rate = analogs.peer_base_rate(query, "sid-1", "2026-10-20", ticker="TEST")
    payload = analogs.base_rate_payload(base_rate)

    assert payload["base_rate"] == "50%"
    assert payload["observations"] == 2
    assert payload["pct_positive"] == pytest.approx(50.0)
    assert payload["avg_return"] == pytest.approx(0.025)
    assert payload["median_return"] == pytest.approx(0.025)
    assert payload["p05_return"] == pytest.approx(-0.0425)
    assert payload["p95_return"] == pytest.approx(0.0925)
    assert payload["peer_observations"] == 2
    assert payload["peer_pct_positive"] == pytest.approx(50.0)
    assert payload["peer_median_return"] == pytest.approx(0.025)
    assert payload["caveats"]
    assert payload["similar_table"].startswith("| Date |")


def test_the_ticker_lookup_finds_the_security():
    def query(sql, params=None):
        # The ticker lookup filters on the ticker; the industry read joins
        # reference.securities but filters on the security id.
        if "WHERE ticker = :t" in sql:
            return _frame([{"security_id": "sid-common"}])
        return _frame([])

    base_rate = analogs.peer_base_rate_for_ticker(query, "TEST", "2026-10-20")

    assert base_rate.industry is None
    assert base_rate.ticker == "TEST"


def test_an_unknown_ticker_gets_an_empty_result():
    def query(sql, params=None):
        return _frame([])

    base_rate = analogs.peer_base_rate_for_ticker(query, "NOPE", "2026-10-20")

    assert base_rate.observations == 0
    assert base_rate.base_rate_text == ""


def test_the_median_of_an_even_sample_is_the_mean_of_the_middle_two():
    assert analogs._median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)
    assert analogs._median([1.0, 2.0, 3.0]) == pytest.approx(2.0)
    assert analogs._median([]) is None


def test_the_percentile_interpolates_like_percentile_cont():
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert analogs._percentile(values, 0.0) == pytest.approx(0.0)
    assert analogs._percentile(values, 0.5) == pytest.approx(2.0)
    assert analogs._percentile(values, 1.0) == pytest.approx(4.0)
    assert analogs._percentile([], 0.5) is None


def test_an_empty_peer_group_reports_nothing():
    peer = analogs._peer_group([])

    assert peer.observations == 0
    assert peer.pct_positive is None
    assert peer.avg_return is None
    assert peer.median_return is None
    assert peer.p05_return is None
    assert peer.p95_return is None


def test_the_own_windows_do_not_overlap():
    # Consecutive daily windows share 251 of their 252 observations, so three
    # windows a day apart are one observation seen three times.
    rows = [
        {
            "as_of_date": as_of,
            "forward_date": f"{as_of[:4]}-12-31",
            "window_days": 252,
            "total_return": 0.10,
            "price_return": 0.08,
            "dividend_return": 0.02,
        }
        for as_of in ("2026-01-01", "2026-01-02", "2026-01-03", "2025-01-02")
    ]

    def query(sql, params=None):
        return _frame(rows)

    picked = analogs.own_forward_returns(query, "sid-1", rows=3)

    # The three adjacent days collapse to one, and the year-older one is kept.
    assert [row["as_of_date"] for row in picked] == ["2025-01-02", "2026-01-01"]


def test_the_own_windows_are_oldest_first():
    rows = [
        {
            "as_of_date": "2026-06-01",
            "forward_date": "2027-06-01",
            "window_days": 252,
            "total_return": 0.10,
            "price_return": 0.08,
            "dividend_return": 0.02,
        },
        {
            "as_of_date": "2025-06-01",
            "forward_date": "2026-06-01",
            "window_days": 252,
            "total_return": -0.05,
            "price_return": -0.07,
            "dividend_return": 0.02,
        },
    ]

    def query(sql, params=None):
        return _frame(rows)

    picked = analogs.own_forward_returns(query, "sid-1")

    assert [row["as_of_date"] for row in picked] == ["2025-06-01", "2026-06-01"]


def test_the_own_history_table_carries_the_worksheet_columns():
    rows = [
        {
            "as_of_date": "2025-06-01",
            "forward_date": "2026-06-01",
            "window_days": 252,
            "total_return": -0.05,
            "price_return": -0.07,
            "dividend_return": 0.02,
        }
    ]

    table = analogs.own_history_table(rows)

    assert table.splitlines()[0] == "| Period | Conditions | Forward 12M total return | Outcome |"
    assert "2025-06-01 to 2026-06-01" in table
    assert "Negative" in table


def test_the_own_history_table_says_so_when_there_is_nothing():
    table = analogs.own_history_table([])

    assert "not available" in table
    assert "N/A" in table
