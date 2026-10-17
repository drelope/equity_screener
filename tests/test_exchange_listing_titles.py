from scripts import populate_exchange_listing_titles as stage
from scripts.populate_dividend_data import parse_percent
from src.crispdm.sec_client import classify_security_type


def test_directory_symbol_maps_preferred_suffix():
    assert stage.directory_symbol("AGM-PI") == "AGM$I"
    assert stage.directory_symbol("tfin-p") == "TFIN$"
    assert stage.directory_symbol("AAPL") == "AAPL"


def test_parse_directory_drops_trailer_and_flags():
    body = (
        "Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|"
        "Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares\n"
        "Y|AGM$I|Federal Agricultural Mortgage Corporation 4.875% Pfd Ser I|N| |N|100|N|"
        "|AGMpI|AGM-I|N\n"
        "Y|SPY|SPDR S&P 500 ETF Trust|P| |Y|100|N||SPY|SPY|N\n"
        "File Creation Time: 0101202600:00|||||||||||\n"
    )
    rows = stage.parse_directory(body)
    assert [row["symbol"] for row in rows] == ["AGM$I", "SPY"]
    assert rows[0]["listing_exchange"] == "N" and rows[0]["etf"] is False
    assert rows[1]["etf"] is True


def _row(ticker, title):
    return {"ticker": ticker, "title": title}


def test_plan_action_renames_preferred_with_coupon():
    action = stage.plan_action(
        _row(
            "SPG-PJ",
            "Simon Property Group, Inc. Simon Property Group 8 3/8% Series J "
            "Cumulative Redeemable Preferred Stock",
        )
    )
    assert action[0] == "rename" and action[1] == 8.375


def test_plan_action_reclassifies_notes_units_and_common():
    assert stage.plan_action(_row("BC-PC", "Brunswick Corporation 6.375% Notes due 2049")) == (
        "reclassify",
        "corporate bond",
    )
    assert stage.plan_action(_row("NEE-PV", "NextEra Energy, Inc. 7.375% Corporate Units")) == (
        "reclassify",
        "other_debt_and_equity",
    )
    # A fund named "... Preferred ..." whose listed security is its common stock.
    assert stage.plan_action(
        _row("DFP", "Flaherty & Crumrine Dynamic Preferred and Income Fund Inc. Common Stock")
    ) == ("reclassify", "common_stock")


def test_plan_action_skips_bare_fund_names():
    assert (
        stage.plan_action(_row("FFC", "Flaherty & Crumrine Preferred Securities Income Fund Inc."))
        is None
    )


class _FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, *args):
        self.calls.append(args)


def test_store_listings_keeps_snapshot_when_directory_is_short():
    conn = _FakeConn()
    assert stage.store_listings(conn, [{"symbol": "A"}], "x") == 0
    assert conn.calls == []


def test_parse_percent_reads_mixed_fractions():
    assert parse_percent("8 3/8% Series J Cumulative Redeemable Preferred") == 8.375
    assert parse_percent("6.625% Series A") == 6.625
    assert parse_percent("no rate") is None


def test_classifier_recognises_preference_securities_and_dated_notes():
    assert classify_security_type("7.5% Preference Securities") == "preferred stock"
    assert classify_security_type("4.875% Pfd Ser I") == "preferred stock"
    assert classify_security_type("6.200% Notes due June 1, 2059") == "corporate bond"


def test_bare_sec_label_is_not_decisive_and_supplies_missing_rate():
    row = {
        "ticker": "VNO-PL",
        "title": "Vornado Realty Trust Pfd Ser L %",
        "sec_titles": ["5.40% Series L"],
    }
    assert not stage.has_decisive_sec_title(row)
    assert stage.plan_action(row) == ("rename", 5.4, None)
    assert stage.has_decisive_sec_title({"sec_titles": ["6.200% Notes due June 1, 2059"]})
