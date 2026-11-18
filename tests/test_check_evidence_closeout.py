import copy
import json

from scripts.check_evidence_closeout import DEFAULT_INDEX, check_index, main


def load_index():
    return json.loads(DEFAULT_INDEX.read_text(encoding="utf-8"))


def test_real_index_passes(capsys):
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "promotion_grade=false" in out
    assert "pass_draft_not_promotion_grade" in out


def test_index_rejects_promotion_claim(tmp_path):
    index = load_index()
    index["promotion_claim"] = True
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index), encoding="utf-8")
    rc = main(["--index", str(path)])
    assert rc == 1


def test_index_rejects_missing_artifact(tmp_path):
    index = load_index()
    index["artifacts"] = [a for a in index["artifacts"] if a["id"] != "status"]
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index), encoding="utf-8")
    rc = main(["--index", str(path)])
    assert rc == 1


def test_index_rejects_hash_mismatch(tmp_path):
    index = load_index()
    index["artifacts"][0] = copy.deepcopy(index["artifacts"][0])
    index["artifacts"][0]["sha256"] = "0" * 64
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index), encoding="utf-8")
    rc = main(["--index", str(path)])
    assert rc == 1


def test_index_rejects_approved_status(tmp_path):
    index = load_index()
    index["status"] = "promotion_grade"
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index), encoding="utf-8")
    rc = main(["--index", str(path)])
    assert rc == 1


def test_require_promotion_grade_always_fails(capsys):
    rc = main(["--require-promotion-grade"])
    assert rc == 1
    assert "promotion-grade closeout is not implemented" in capsys.readouterr().out


def test_check_index_rejects_absolute_path():
    index = load_index()
    index["artifacts"][0]["path"] = "/etc/passwd"
    errs = check_index(index, DEFAULT_INDEX.parents[2])
    assert any("must be a relative path" in err for err in errs)
