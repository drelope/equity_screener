"""Run one task as a subprocess: bounded output, a deadline, cancellation.

Independent of the database and of the catalog, so it is tested with ordinary commands.
The caller supplies the argv (built from the allowlist) and a ``tick`` callback that is
invoked about once a second with the output tail so far; the callback persists a
heartbeat and returns True when an operator asked to cancel.

The whole process group is signalled, not just the child: the ETL starts its own
subprocesses, and killing only the parent would leave them running against the warehouse
with nobody watching.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

#: Bytes of output kept in memory. The store keeps a smaller tail still.
OUTPUT_LIMIT_BYTES = 256_000
TERM_GRACE_SECONDS = 15
TICK_SECONDS = 1.0


@dataclass
class RunResult:
    status: str  # succeeded | failed | cancelled | timed_out
    exit_code: int | None
    output: str


class _Tail:
    """The last ``limit`` bytes of a stream, kept as whole lines."""

    def __init__(self, limit: int):
        self.limit = limit
        self.lines: deque[str] = deque()
        self.size = 0
        self.dropped = False
        self.lock = threading.Lock()

    def add(self, line: str) -> None:
        with self.lock:
            self.lines.append(line)
            self.size += len(line.encode("utf-8", "replace"))
            while self.size > self.limit and len(self.lines) > 1:
                gone = self.lines.popleft()
                self.size -= len(gone.encode("utf-8", "replace"))
                self.dropped = True

    def text(self) -> str:
        with self.lock:
            body = "".join(self.lines)
            return ("[earlier output dropped]\n" + body) if self.dropped else body


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError):
        pass


def _stop(proc: subprocess.Popen) -> None:
    """SIGTERM the group, give it a grace period, then SIGKILL."""
    _signal_group(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _signal_group(proc, signal.SIGKILL)
        proc.wait()


def run(
    argv: list[str],
    *,
    timeout_seconds: float,
    tick: Callable[[str], bool] | None = None,
    cwd: str | None = None,
    env: dict | None = None,
    tick_seconds: float = TICK_SECONDS,
    output_limit: int = OUTPUT_LIMIT_BYTES,
) -> RunResult:
    """Run ``argv`` (never through a shell) and return how it ended."""
    tail = _Tail(output_limit)
    proc = subprocess.Popen(  # noqa: S603 - argv is built from the allowlist by the caller
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )

    def pump():
        assert proc.stdout is not None
        for line in proc.stdout:
            tail.add(line)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout_seconds
    outcome = None
    try:
        while True:
            try:
                proc.wait(timeout=tick_seconds)
                break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() >= deadline:
                outcome = "timed_out"
                break
            if tick is not None and tick(tail.text()):
                outcome = "cancelled"
                break
    finally:
        if proc.poll() is None:
            _stop(proc)
        reader.join(timeout=5)

    output = tail.text()
    if outcome == "timed_out":
        output += f"\n[stopped: exceeded the {int(timeout_seconds)}s limit]\n"
    elif outcome == "cancelled":
        output += "\n[stopped: cancelled by an operator]\n"
    code = proc.returncode
    if outcome:
        return RunResult(outcome, code, output)
    return RunResult("succeeded" if code == 0 else "failed", code, output)
