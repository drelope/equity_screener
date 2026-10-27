import uuid

from scripts.load_historical_securities import read_candidates, security_id_for


def test_read_candidates_keeps_only_recovered_common_stocks(tmp_path):
    path = tmp_path / "universe.csv"
    path.write_text(
        "cik,company_name,ticker,title,security_type,source,last_filing,sic\n"
        "0001418091,Twitter Inc.,TWTR,Common Stock,common_stock,sec_cover_page,2022-02-16,7370\n"
        "0001418091,Twitter Inc.,TWTR,Common Stock,common_stock,sec_cover_page,2022-02-16,7370\n"
        "0001132979,First Republic Bank,FRC-PC,Preferred,preferred stock,sec_cover_page,2023-01-01,6022\n"
        "0000320193,Apple,AAPL,Common Stock,common_stock,warehouse,2024-01-01,3571\n",
        encoding="utf-8",
    )

    rows = read_candidates(path)

    assert [(row["cik"], row["ticker"]) for row in rows] == [("0001418091", "TWTR")]
    assert rows[0]["company_name"] == "Twitter Inc."


def test_security_id_matches_the_warehouse_convention():
    expected = uuid.uuid5(uuid.NAMESPACE_URL, "dividend-equity:TWTR:0001418091:common_stock")
    assert security_id_for("twtr", "1418091", "common_stock") == expected
