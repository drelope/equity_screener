from datetime import date

from scripts import build_features as bf


def _run(monkeypatch, argv, first=date(2019, 1, 2), last=date(2026, 10, 30)):
    built = []
    monkeypatch.setattr(bf, "observation_date_range", lambda: (first, last))
    monkeypatch.setattr(
        bf,
        "build_features",
        lambda date_from, date_to: (
            built.append((date_from, date_to)) or __import__("pandas").DataFrame()
        ),
    )
    monkeypatch.setattr(bf, "persist_features", lambda df: None)
    monkeypatch.setattr(bf, "feature_completeness", lambda df: {})
    monkeypatch.setattr("sys.argv", ["build_features", *argv])
    return bf.main(), built


def test_date_flags_bound_the_rebuild(monkeypatch):
    code, built = _run(monkeypatch, ["--date-from", "2021-10-18", "--date-to", "2022-10-18"])

    assert code == 0
    assert built[0][0] == date(2021, 10, 18)
    assert built[-1][1] == date(2022, 10, 19)  # window end is exclusive


def test_an_empty_range_builds_nothing(monkeypatch):
    code, built = _run(monkeypatch, ["--date-from", "2027-01-01"])

    assert code == 1 and built == []
