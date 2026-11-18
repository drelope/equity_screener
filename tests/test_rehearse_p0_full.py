from scripts.rehearse_p0_full import (
    DEFAULT_DRAFTS,
    discover_drafts,
    discover_rollbacks,
    init_db_inline_migrations,
    safety_check_dsn,
    split_statements,
)


def test_split_statements_handles_dollar_and_comments():
    sql = """
    DO $$ BEGIN RAISE NOTICE 'x; y'; END $$; -- comment; with semicolon
    SELECT 1;
    /* block; comment */
    SELECT 'a; b';
    """
    stmts = split_statements(sql)
    assert len(stmts) == 3
    assert stmts[0].startswith("DO $$")
    assert stmts[1] == "SELECT 1"
    assert stmts[2] == "SELECT 'a; b'"


def test_init_db_inline_migrations_loaded():
    migs = init_db_inline_migrations()
    assert isinstance(migs, list)
    assert len(migs) >= 1
    assert all(isinstance(m, str) and m.strip() for m in migs)


def test_discover_default_drafts():
    drafts = discover_drafts()
    assert [p.name for p in drafts] == DEFAULT_DRAFTS


def test_safety_check_dsn_blocks_shared_name_and_allows_disposable():
    assert safety_check_dsn("postgresql://u:p@localhost:5432/dividend", False, False)
    assert safety_check_dsn("postgresql://u:p@localhost:55435/rehearsal", False, False) == []


def test_discover_rollbacks_maps_numbered_candidates(tmp_path):
    drafts_dir = tmp_path / "sql-candidates"
    rollback_dir = drafts_dir / "rollback"
    rollback_dir.mkdir(parents=True)
    for version in (107, 108):
        (drafts_dir / f"V{version:04d}_test.sql").write_text("-- draft\n", encoding="utf-8")
        (rollback_dir / f"V{version:04d}_rollback.sql").write_text(
            "-- rollback\n", encoding="utf-8"
        )
    drafts = discover_drafts(["V0107_test.sql", "V0108_test.sql"], drafts_dir)
    rollbacks = discover_rollbacks(drafts)
    assert [p.name for p in rollbacks] == ["V0107_rollback.sql", "V0108_rollback.sql"]


def test_discover_rollbacks_rejects_unversioned_draft(tmp_path):
    drafts_dir = tmp_path / "sql-candidates"
    drafts_dir.mkdir()
    (drafts_dir / "rm01_draft.sql").write_text("-- draft\n", encoding="utf-8")
    drafts = discover_drafts(["rm01_draft.sql"], drafts_dir)
    try:
        discover_rollbacks(drafts, tmp_path)
    except FileNotFoundError as exc:
        assert "cannot derive rollback version" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")
