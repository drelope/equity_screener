import shutil
import subprocess

from scripts import check_line_endings as cle

SAMPLE = (
    "i/crlf  w/crlf  attr/                 \tapi/main.py\n"
    "i/crlf  w/lf    attr/                 \ttests/test_api.py\n"
    "i/lf    w/lf    attr/                 \tREADME.md\n"
    "i/lf    w/mixed attr/                 \tsrc/x.py\n"
    "i/none  w/none  attr/                 \tdata.bin\n"
)


def test_parse_reads_index_and_working_endings_and_the_path():
    rows = cle.parse_eol(SAMPLE)

    assert ("crlf", "lf", "tests/test_api.py") in rows and len(rows) == 5


def test_only_files_whose_endings_changed_are_flagged():
    bad = cle.flipped(cle.parse_eol(SAMPLE))

    assert [p for _, _, p in bad] == ["tests/test_api.py", "src/x.py"]


GIT = shutil.which("git") or "git"


def _git(repo, *args):
    return subprocess.run(  # noqa: S603 - fixed argument list in a temporary repository
        [GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def test_a_real_crlf_file_flips_through_python_text_mode_but_not_with_newline_empty(tmp_path):
    repo = tmp_path
    run = lambda *a: _git(repo, *a)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    run("config", "core.autocrlf", "false")
    (repo / "f.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    run("add", "f.py")
    run("commit", "-qm", "x")

    text = (repo / "f.py").read_text()  # universal newlines drop the CR
    (repo / "f.py").write_text(text.replace("2", "3"))
    out = _git(repo, "ls-files", "--eol", "f.py")
    assert [p for _, _, p in cle.flipped(cle.parse_eol(out))] == ["f.py"]

    (repo / "f.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    with open(repo / "f.py", newline="") as handle:
        kept = handle.read()
    with open(repo / "f.py", "w", newline="") as handle:
        handle.write(kept.replace("2", "3"))
    out = _git(repo, "ls-files", "--eol", "f.py")
    assert cle.flipped(cle.parse_eol(out)) == []
