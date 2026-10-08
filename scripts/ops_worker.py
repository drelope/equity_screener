"""Run queued operational tasks and enqueue due schedules.

One worker process, one task at a time. Each loop it records that it is alive, fails any
task whose worker vanished, queues due schedules, and runs the oldest due task.

Safety properties:

* The command is built here from ``src/crispdm/ops/catalog.py`` and the validated
  parameters. The stored row is never trusted to say what to run: a row naming an
  unknown task, or carrying parameters that fail validation, is failed without running.
* Tasks marked ``exclusive`` hold the same pipeline advisory lock as ``run_full_etl``,
  so they cannot overlap a nightly or each other. If the lock is busy the task goes back
  on the queue with a delay rather than failing.
* A stopping worker terminates its running task's process group and marks it failed,
  rather than leaving a heartbeat-less row for the recovery sweep to find.

Usage:
    python -m scripts.ops_worker
    python -m scripts.ops_worker --once      # run at most one task, then exit
"""

import argparse
import os
import signal
import socket
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine
from src.crispdm.ops import catalog, runner, store
from src.crispdm.ops.store import trim_log

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLL_SECONDS = 5.0
LOCK_RETRY_SECONDS = 60

_stop_requested = False


def _on_signal(signum, _frame):
    global _stop_requested
    _stop_requested = True


def worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _acquire_pipeline_lock():
    # Imported here: run_full_etl is a heavy module and only exclusive tasks need it.
    from scripts.run_full_etl import PipelineAlreadyRunning, _acquire_run_lock

    try:
        return _acquire_run_lock(), None
    except PipelineAlreadyRunning as exc:
        return None, str(exc)


def _release_pipeline_lock(handle):
    if handle is not None:
        from scripts.run_full_etl import _release_run_lock

        _release_run_lock(handle)


def execute(task: dict, worker: str) -> str:
    """Run one claimed task to a final status (or back onto the queue). Returns the status."""
    task_id = task["task_id"]
    try:
        definition = catalog.get_task(task["task_key"])
        argv = catalog.build_argv(task["task_key"], task["params"])
    except ValueError as exc:
        with engine.begin() as conn:
            store.finish(conn, task_id, "failed", None, f"[rejected: {exc}]\n")
        return "failed"

    lock = None
    if definition.exclusive:
        lock, busy = _acquire_pipeline_lock()
        if lock is None:
            with engine.begin() as conn:
                store.requeue_busy(
                    conn,
                    task_id,
                    LOCK_RETRY_SECONDS,
                    f"[waiting: {busy}]\n[retrying in {LOCK_RETRY_SECONDS}s]\n",
                )
            return "queued"

    def tick(output: str) -> bool:
        if _stop_requested:
            return True
        with engine.begin() as conn:
            requested = store.heartbeat(conn, task_id, output)
            store.touch_worker(conn, worker, task_id)
        return requested

    env = dict(os.environ, PYTHONUNBUFFERED="1")
    header = f"$ {' '.join(argv)}\n"
    try:
        result = runner.run(
            argv,
            timeout_seconds=definition.timeout_seconds,
            tick=tick,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
    except Exception as exc:  # noqa: BLE001 - e.g. the interpreter could not start
        with engine.begin() as conn:
            store.finish(conn, task_id, "failed", None, f"{header}[could not start: {exc}]\n")
        return "failed"
    finally:
        _release_pipeline_lock(lock)

    status = result.status
    if status == "failed" and result.exit_code in definition.ok_exit_codes:
        status = "succeeded"
    if _stop_requested and status == "cancelled":
        status = "failed"
        result.output += "[worker stopped while the task was running]\n"
    with engine.begin() as conn:
        store.finish(conn, task_id, status, result.exit_code, trim_log(header + result.output))
    return status


def loop_once(worker: str) -> bool:
    """One iteration. Returns True if a task was run."""
    with engine.begin() as conn:
        store.touch_worker(conn, worker)
        store.recover_orphans(conn)
        store.enqueue_due(conn)
        task = store.claim_next(conn, worker)
    if task is None:
        return False
    print(f"[ops_worker] running task #{task['task_id']} {task['task_key']}", flush=True)
    status = execute(task, worker)
    print(f"[ops_worker] task #{task['task_id']} -> {status}", flush=True)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run at most one task, then exit")
    parser.add_argument("--poll-seconds", type=float, default=POLL_SECONDS)
    args = parser.parse_args(argv)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    worker = worker_name()
    print(f"[ops_worker] {worker} started", flush=True)

    while not _stop_requested:
        try:
            ran = loop_once(worker)
        except Exception as exc:  # noqa: BLE001 - a database blip must not kill the worker
            print(
                f"[ops_worker] loop error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True
            )
            ran = False
        if args.once:
            break
        if not ran:
            time.sleep(args.poll_seconds)
    print("[ops_worker] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
