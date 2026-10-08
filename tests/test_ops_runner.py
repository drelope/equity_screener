"""The subprocess runner, tested with real processes.

The runner exists to make four things true about a long task, each tested here: its output
is bounded, it stops at a deadline, an operator can cancel it, and stopping it stops the
children it started, not just the parent.
"""

import os
import sys
import textwrap
import time

import pytest

from src.crispdm.ops import runner

PY = sys.executable


def run(code, **kwargs):
    kwargs.setdefault("timeout_seconds", 30)
    kwargs.setdefault("tick_seconds", 0.1)
    return runner.run([PY, "-c", textwrap.dedent(code)], **kwargs)


def test_a_zero_exit_succeeds_and_output_is_captured():
    result = run("print('hello'); print('world')")
    assert (result.status, result.exit_code) == ("succeeded", 0)
    assert result.output == "hello\nworld\n"


def test_a_nonzero_exit_fails_and_stderr_is_merged_into_the_output():
    result = run("import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)")
    assert (result.status, result.exit_code) == ("failed", 3)
    assert "out" in result.output and "err" in result.output


def test_output_is_bounded_to_the_tail_and_marked_as_truncated():
    result = run("for i in range(5000): print('line', i, 'x' * 40)", output_limit=4000)
    assert len(result.output.encode()) < 4000 + 200
    assert result.output.startswith("[earlier output dropped]")
    assert "line 4999" in result.output and "line 0 " not in result.output


def test_a_task_that_outlives_its_deadline_is_stopped():
    started = time.monotonic()
    result = run("import time; time.sleep(60)", timeout_seconds=1)
    assert result.status == "timed_out"
    assert time.monotonic() - started < 20
    assert "exceeded" in result.output


def test_an_operator_cancel_stops_the_task():
    calls = []

    def tick(output):
        calls.append(output)
        return len(calls) >= 3

    result = run("import time; print('started', flush=True); time.sleep(60)", tick=tick)
    assert result.status == "cancelled"
    assert "started" in result.output and "cancelled by an operator" in result.output


def test_the_tick_receives_the_output_so_far():
    seen = []

    def tick(output):
        seen.append(output)
        return False

    run("import time; print('a', flush=True); time.sleep(0.6); print('b', flush=True)", tick=tick)
    assert any(s.startswith("a") for s in seen)


def test_stopping_a_task_also_stops_the_processes_it_started(tmp_path):
    """The ETL spawns subprocesses; killing only the parent would leave them running."""
    marker = tmp_path / "child.pid"
    code = f"""
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open({str(marker)!r}, "w").write(str(child.pid))
        time.sleep(60)
    """
    result = run(code, timeout_seconds=2)
    assert result.status == "timed_out"
    pid = int(marker.read_text())
    deadline = time.monotonic() + 10
    alive = True
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            alive = False
            break
        time.sleep(0.1)
    assert not alive, "the child process survived its parent being stopped"


def test_the_command_is_never_run_through_a_shell(tmp_path):
    """A metacharacter in an argument is data, not syntax."""
    evidence = tmp_path / "pwned"
    result = runner.run(
        [PY, "-c", "import sys; print(sys.argv[1])", f"x; touch {evidence}"],
        timeout_seconds=10,
        tick_seconds=0.1,
    )
    assert result.status == "succeeded"
    assert not evidence.exists()
    assert "touch" in result.output


def test_stdin_is_closed_so_a_prompting_task_cannot_hang_forever():
    result = run("import sys; sys.exit(0 if sys.stdin.read() == '' else 9)")
    assert result.status == "succeeded"


def test_an_unstartable_command_raises_rather_than_returning_a_status():
    with pytest.raises(FileNotFoundError):
        runner.run(["/definitely/not/a/binary"], timeout_seconds=5)
