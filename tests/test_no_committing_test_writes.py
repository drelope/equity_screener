"""No test may commit a write to the live warehouse.

Context: `tests/test_score_pruning.py` once called `prune_stale_run_runs()` --
which issues a real `DELETE` -- inside `engine.begin()`. That context manager
commits on normal exit, the assertions passed, and a green test run destroyed
5,617 `model.scores` rows and 5,617 `model.rankings` rows at the run date. There
was no backup and the run was not reproducible.

So the rule is narrow and mechanical: a test may *write* freely as long as the
transaction is rolled back. Two shapes are acceptable:

* an explicit transaction with `rollback()` in a `finally`
  (`test_regime_pipeline.py` does this), or
* `CREATE TEMP TABLE` fixtures, which are session-scoped and touch no permanent
  table, so committing them changes nothing.

What is not acceptable is a committing context wrapping a write to a real schema.

This is enforced by parsing each test with `ast` rather than by grepping. The
first version stripped triple-quoted blocks to avoid matching prose, which
silently deleted the very thing under test: test SQL is passed as a
triple-quoted string to `text()`, so the write disappeared along with the
docstring and the guard passed on a file that committed a real INSERT. Going
through the tree lets the docstring be excluded exactly -- it is the
module/function's first statement -- while a SQL literal elsewhere in the
function is still seen.

A runtime check is not an option: a test that damages the warehouse has, by
construction, already passed by the time anything could notice at teardown.
"""

import ast
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SELF = Path(__file__).name

#: Schemas a test must never write to. TEMP is absent deliberately: temp tables
#: live in the session and are dropped with it, so they are not warehouse writes.
LIVE_SCHEMAS = (
    "model",
    "reference",
    "raw",
    "clean",
    "audit",
    "preferred",
    "fundamentals",
    "dividends",
    "market",
    "public",
)

WRITE_TO_LIVE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE)\s+(?:ONLY\s+)?("
    + "|".join(LIVE_SCHEMAS)
    + r")\.",
    re.I,
)

#: Calls that end in a commit rather than a rollback.
COMMITTING_ATTRS = {"commit"}


def _python_sources():
    return sorted(p for p in TESTS.glob("test_*.py") if p.name != SELF)


def _docstring_nodes(tree):
    """The Constant nodes that are docstrings, which are prose, not code."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def _is_begin_call(node):
    func = node.func if isinstance(node, ast.Call) else None
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "begin"
        or isinstance(func, ast.Name)
        and func.id == "begin"
    )


def _strings_and_commits(body):
    """Yield (kind, text, lineno) for live writes and for committing contexts.

    A committing context is either an explicit ``.commit()`` or a ``with`` block
    opened on ``.begin()``. A bare ``conn.begin()`` assigned to a variable is
    *not* one of those: `test_regime_pipeline.py` uses that shape and pairs it
    with `rollback()` in a `finally`, which is the pattern this whole file exists
    to recommend. Only the `with` form commits implicitly on normal exit.
    """
    docstrings = _docstring_nodes(ast.Module(body=body, type_ignores=[]))
    module = ast.Module(body=body, type_ignores=[])
    for node in ast.walk(module):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            for m in WRITE_TO_LIVE.finditer(node.value):
                yield ("write", m.group(0), node.lineno)
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in COMMITTING_ATTRS:
                yield ("commit", f".{name}()", node.lineno)
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if _is_begin_call(item.context_expr):
                    yield ("commit", "with .begin()", node.lineno)


def _scopes(path):
    """(label, body) for each function plus module level, for one file."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node.body
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f"{node.name}.{sub.name}", sub.body
    yield (
        "<module level>",
        [
            n
            for n in tree.body
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ],
    )


@pytest.mark.parametrize("path", _python_sources(), ids=lambda p: p.name)
def test_no_test_commits_a_write_to_a_live_table(path):
    offenders = []
    for label, body in _scopes(path):
        found = list(_strings_and_commits(body))
        writes = [f for f in found if f[0] == "write"]
        commits = [f for f in found if f[0] == "commit"]
        if writes and commits:
            for w in writes:
                for c in commits:
                    offenders.append(f"{label}: {w[1]!r} (line {w[2]}) with {c[1]!r} (line {c[2]})")
    assert not offenders, (
        f"{path.name} commits a write to a live table:\n  "
        + "\n  ".join(offenders)
        + "\nUse an explicit transaction with rollback() in a finally, or "
        "CREATE TEMP TABLE fixtures."
    )


def test_the_guard_actually_detects_the_bug_it_exists_for():
    """A guard that cannot fail is worse than no guard.

    Reproduces the original incident's shape -- a live INSERT inside
    `engine.begin()` -- in a string, and asserts it is reported.
    """
    bad = ast.parse(
        """
def test_example():
    with engine.begin() as conn:
        conn.execute(text(\"\"\"
            INSERT INTO model.scores (security_id) VALUES (:sid)
        \"\"\"))
        conn.commit()
"""
    )
    found = list(_strings_and_commits(bad.body[0].body))
    assert any(f[0] == "write" for f in found), "guard missed the live INSERT"
    assert any(f[0] == "commit" for f in found), "guard missed the commit"


def test_the_guard_ignores_docstring_prose():
    """The first version's failure mode: prose and SQL share a quote style."""
    src = ast.parse(
        '''
def test_example():
    """This docstring mentions engine.begin() and DELETE FROM model.scores.

    It is prose describing an incident, not a statement, so it must not count.
    """
    conn.execute(text("SELECT 1"))
    conn.rollback()
'''
    )
    assert not list(_strings_and_commits(src.body[0].body))


def test_every_live_write_in_the_suite_is_covered_by_the_guard():
    """Coverage may exceed use; it must never fall short of it."""
    referenced = set()
    for path in _python_sources():
        for label, body in _scopes(path):
            for kind, text, _ in _strings_and_commits(body):
                if kind == "write":
                    referenced.update(WRITE_TO_LIVE.findall(text))
    uncovered = referenced - set(LIVE_SCHEMAS)
    assert not uncovered, (
        f"the suite writes to {sorted(uncovered)}, which LIVE_SCHEMAS does not "
        "cover; add it so the guard keeps protecting it"
    )
