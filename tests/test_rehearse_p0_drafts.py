from scripts.rehearse_p0_drafts import DEFAULT_DRAFTS, discover_drafts, safety_check_dsn


def test_discover_default_drafts():
    drafts = discover_drafts()
    assert [p.name for p in drafts] == DEFAULT_DRAFTS
    assert all(p.exists() for p in drafts)


def test_safety_check_dsn_rejects_shared_local_dividend():
    issues = safety_check_dsn(
        "postgresql+psycopg://dividend:dividend@localhost:5432/dividend", False
    )
    assert any("shared/production-like" in i for i in issues)


def test_safety_check_dsn_allows_local_disposable_name():
    issues = safety_check_dsn("postgresql+psycopg://postgres:test@localhost:55432/rehearsal", False)
    assert issues == []
