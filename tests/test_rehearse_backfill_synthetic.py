from scripts.rehearse_backfill_synthetic import FIXTURE, main


def test_fixture_exists_and_is_synthetic():
    assert FIXTURE.exists()
    text = FIXTURE.read_text(encoding="utf-8")
    assert "SYNTHETIC BACKFILL FIXTURE" in text
    assert "NOT APPROVED" in text


def test_refuses_shared_db_before_loading_fixture(capsys, tmp_path):
    rc = main(
        ["--dsn", "postgresql://u:p@localhost:5432/dividend", "--out", str(tmp_path / "x.json")]
    )
    assert rc == 2
    assert "shared/production-like" in capsys.readouterr().err


def test_requires_disposable_confirmation(capsys, tmp_path):
    rc = main(
        ["--dsn", "postgresql://u:p@localhost:55448/rehearsal", "--out", str(tmp_path / "x.json")]
    )
    assert rc == 2
    assert "--i-understand-disposable-target" in capsys.readouterr().err
