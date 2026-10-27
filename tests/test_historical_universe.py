from scripts.build_historical_universe import candidate_filings, parse_company_index


def _index_row(name, form, cik, filed, filename="edgar/data/x.txt"):
    return f"{name:<62}{form:<12}{cik:>11}     {filed}  {filename}"


def test_parse_company_index_reads_operating_filings():
    raw = "\n".join(
        [
            "Description:           Master Index",
            "",
            "",
            "",
            "Company Name                                                  Form Type   CIK         Date Filed  File Name",
            "------------------------------------------------------------------------------------------------------------------------",
            _index_row("10x Genomics, Inc.", "10-K", "1770787", "2024-02-15"),
            _index_row("FIRST REPUBLIC BANK", "SC 13G", "1132979", "2023-01-31"),
            _index_row(
                "A Very Long Company Name That Still Fits In The Field",
                "10-Q",
                "123456",
                "2024-05-01",
            ),
        ]
    )

    rows = parse_company_index(raw)

    assert rows[0] == ("10x Genomics, Inc.", "10-K", "1770787", "2024-02-15", "edgar/data/x.txt")
    assert rows[1][1] == "SC 13G"
    assert rows[2][0] == "A Very Long Company Name That Still Fits In The Field"
    assert len(rows) == 3


def test_candidate_filings_prefers_annual_reports_then_recency():
    filings = [
        {"form": "10-Q", "filing_date": "2023-04-28"},
        {"form": "10-K", "filing_date": "2023-02-15"},
        {"form": "8-K", "filing_date": "2023-05-01"},
        {"form": "10-K", "filing_date": "2022-02-15"},
    ]

    ordered = candidate_filings(filings)

    assert [row["form"] for row in ordered] == ["10-K", "10-K", "10-Q"]
    assert ordered[0]["filing_date"] == "2023-02-15"


def test_candidate_filings_returns_empty_without_cover_forms():
    assert candidate_filings([{"form": "8-K", "filing_date": "2023-05-01"}]) == []
