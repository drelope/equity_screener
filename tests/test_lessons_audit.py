from pathlib import Path

from scripts import lessons_audit as la

GOOD = """# L001 example

- **Status:** guarded
- **Area:** stage 1
- **Symptom:** it broke
- **Root cause:** because
- **Detection:** how found
- **Guard:** `scripts/guard.py`, `tests/test_guard.py`
- **Recurrence check:** `python -m pytest tests/test_guard.py`
"""


def _setup(tmp_path: Path, body=GOOD, name="L001-example.md", index=True, guards=True):
    d = tmp_path / "docs" / "etl-lessons"
    d.mkdir(parents=True)
    (d / name).write_text(body, encoding="utf-8")
    if index:
        (d / "INDEX.md").write_text(f"- [L001]({name})\n", encoding="utf-8")
    if guards:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "scripts" / "guard.py").write_text("x", encoding="utf-8")
        (tmp_path / "tests" / "test_guard.py").write_text("x", encoding="utf-8")
    return d


def test_a_complete_lesson_with_existing_guards_passes(tmp_path):
    d = _setup(tmp_path)

    assert la.audit(d, tmp_path) == []


def test_a_guarded_lesson_whose_guard_is_missing_fails(tmp_path):
    d = _setup(tmp_path, guards=False)

    assert any("guard does not exist" in f.message for f in la.audit(d, tmp_path))


def test_a_guarded_lesson_must_name_a_guard(tmp_path):
    d = _setup(tmp_path, GOOD.replace("`scripts/guard.py`, `tests/test_guard.py`", "none"))

    assert any("must name its guard" in f.message for f in la.audit(d, tmp_path))


def test_an_open_lesson_needs_no_guard_but_still_needs_its_fields(tmp_path):
    body = GOOD.replace("guarded", "open").replace(
        "`scripts/guard.py`, `tests/test_guard.py`", "not yet"
    )
    d = _setup(tmp_path, body, guards=False)
    assert la.audit(d, tmp_path) == []

    d2 = _setup(tmp_path / "b", body.replace("- **Symptom:** it broke\n", ""), guards=False)
    assert any("missing field 'Symptom'" in f.message for f in la.audit(d2, tmp_path / "b"))


def test_an_unknown_status_and_a_bad_file_name_fail(tmp_path):
    d = _setup(tmp_path, GOOD.replace("guarded", "done"))
    assert any("Status must be one of" in f.message for f in la.audit(d, tmp_path))

    d2 = _setup(tmp_path / "c", name="Lesson-one.md")
    assert any("file name must look like" in f.message for f in la.audit(d2, tmp_path / "c"))


def test_the_index_must_match_the_files(tmp_path):
    d = _setup(tmp_path, index=False)
    assert any("missing index" in f.message for f in la.audit(d, tmp_path))

    (d / "INDEX.md").write_text("- [L009](L009-ghost.md)\n", encoding="utf-8")
    messages = [f.message for f in la.audit(d, tmp_path)]
    assert any("does not list L001-example.md" in m for m in messages)
    assert any("lists missing file L009-ghost.md" in m for m in messages)


def test_duplicate_ids_and_unresolved_markers_fail(tmp_path):
    d = _setup(tmp_path)
    (d / "L001-second.md").write_text(GOOD + "\nTODO fix\n", encoding="utf-8")

    messages = [f.message for f in la.audit(d, tmp_path)]
    assert any("duplicate lesson id" in m for m in messages)
    assert any("unresolved marker" in m for m in messages)


def test_the_real_ledger_is_consistent():
    assert la.audit() == []


def test_recall_matches_every_word_and_puts_unguarded_lessons_first(tmp_path):
    d = _setup(tmp_path)
    second = (
        GOOD.replace("L001", "L002")
        .replace("guarded", "open")
        .replace("`scripts/guard.py`, `tests/test_guard.py`", "not yet")
        .replace("stage 1", "stage 1 retype")
    )
    (d / "L002-second.md").write_text(second, encoding="utf-8")

    hits = la.recall(["STAGE"], d)

    assert [h["id"] for h in hits] == ["L002", "L001"]  # open before guarded
    assert hits[0]["recurrence_check"].startswith("`python")
    assert [h["id"] for h in la.recall(["stage", "retype"], d)] == ["L002"]
    assert la.recall(["nothing-like-this"], d) == []


def test_recall_on_the_real_ledger_finds_the_stage_one_lessons():
    ids = {h["id"] for h in la.recall(["stage 1"])}

    assert {"L001"} <= ids
