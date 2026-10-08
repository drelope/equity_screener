"""The worker's decisions, with the database and the subprocess replaced by fakes.

What is under test is the logic around a task: what it refuses to run, when it waits for
the pipeline lock, how an exit code becomes a status, and that the lock is always
released. The queue SQL is covered against the real schema in ``test_ops_store.py`` and
the subprocess handling in ``test_ops_runner.py``.
"""

import contextlib

import pytest

from scripts import ops_worker
from src.crispdm.ops import runner, store


class Recorder:
    """Stands in for the store functions the worker calls and remembers each call."""

    def __init__(self):
        self.finished = []
        self.requeued = []
        self.heartbeats = []
        self.touched = []
        self.cancel_requested = False

    def install(self, monkeypatch):
        class FakeEngine:
            def begin(self):
                return contextlib.nullcontext("conn")

        monkeypatch.setattr(ops_worker, "engine", FakeEngine())
        monkeypatch.setattr(
            store, "finish", lambda c, i, s, code, log: self.finished.append((i, s, code, log))
        )
        monkeypatch.setattr(
            store, "requeue_busy", lambda c, i, d, note: self.requeued.append((i, d, note))
        )

        def heartbeat(conn, task_id, output):
            self.heartbeats.append((task_id, output))
            return self.cancel_requested

        monkeypatch.setattr(store, "heartbeat", heartbeat)
        monkeypatch.setattr(store, "touch_worker", lambda c, w, t=None: self.touched.append((w, t)))
        monkeypatch.setattr(ops_worker, "_stop_requested", False)


@pytest.fixture
def rec(monkeypatch):
    recorder = Recorder()
    recorder.install(monkeypatch)
    return recorder


def task(key, params=None, task_id=7):
    return {"task_id": task_id, "task_key": key, "params": params or {}, "attempts": 1}


def fake_run(monkeypatch, result=None, raises=None, capture=None):
    def _run(argv, **kwargs):
        if capture is not None:
            capture["argv"], capture["kwargs"] = argv, kwargs
        if raises:
            raise raises
        return result

    monkeypatch.setattr(runner, "run", _run)


def fake_lock(monkeypatch, *, busy=None):
    state = {"released": [], "acquired": 0}

    def acquire():
        state["acquired"] += 1
        return (None, busy) if busy else ("handle", None)

    monkeypatch.setattr(ops_worker, "_acquire_pipeline_lock", acquire)
    monkeypatch.setattr(ops_worker, "_release_pipeline_lock", lambda h: state["released"].append(h))
    return state


# --- what it refuses to run ------------------------------------------------------


@pytest.mark.parametrize(
    "key, params",
    [
        ("rm_rf", {}),
        ("", {}),
        ("build_features", {"days": "400; rm -rf /"}),
        ("score_rank", {"--evil": "1"}),
        ("populate_market_data", {"tickers": "KO --all"}),
    ],
)
def test_a_row_that_fails_the_allowlist_is_failed_and_never_run(monkeypatch, rec, key, params):
    fake_run(monkeypatch, raises=AssertionError("must not run"))
    lock = fake_lock(monkeypatch)

    assert ops_worker.execute(task(key, params), "w") == "failed"

    (_, status, code, log) = rec.finished[0]
    assert status == "failed" and code is None and "rejected" in log
    assert lock["acquired"] == 0


# --- exit codes and statuses -----------------------------------------------------


def test_a_clean_run_is_recorded_with_the_command_that_ran(monkeypatch, rec):
    seen = {}
    fake_run(monkeypatch, runner.RunResult("succeeded", 0, "all good\n"), capture=seen)
    fake_lock(monkeypatch)

    assert ops_worker.execute(task("score_rank"), "w") == "succeeded"

    assert seen["argv"][1:] == ["-m", "scripts.score_rank"]
    assert seen["kwargs"]["timeout_seconds"] == 3600
    _, status, code, log = rec.finished[0]
    assert (status, code) == ("succeeded", 0)
    assert log.startswith("$ ") and "scripts.score_rank" in log and log.endswith("all good\n")


def test_an_exit_code_the_task_defines_as_a_finding_is_a_success(monkeypatch, rec):
    fake_lock(monkeypatch)
    fake_run(monkeypatch, runner.RunResult("failed", 1, "attention needed\n"))
    assert ops_worker.execute(task("verify_nightly"), "w") == "succeeded"

    fake_run(monkeypatch, runner.RunResult("failed", 2, "crashed\n"))
    assert ops_worker.execute(task("verify_nightly"), "w") == "failed"
    assert [f[1] for f in rec.finished] == ["succeeded", "failed"]


def test_an_exit_code_one_is_still_a_failure_for_a_task_that_does_not_allow_it(monkeypatch, rec):
    fake_lock(monkeypatch)
    fake_run(monkeypatch, runner.RunResult("failed", 1, "boom\n"))
    assert ops_worker.execute(task("score_rank"), "w") == "failed"


def test_a_cancelled_and_a_timed_out_task_keep_their_status(monkeypatch, rec):
    fake_lock(monkeypatch)
    for status in ("cancelled", "timed_out"):
        fake_run(monkeypatch, runner.RunResult(status, -15, ""))
        assert ops_worker.execute(task("score_rank"), "w") == status


def test_a_process_that_cannot_start_is_failed_with_the_reason(monkeypatch, rec):
    fake_lock(monkeypatch)
    fake_run(monkeypatch, raises=FileNotFoundError("no interpreter"))

    assert ops_worker.execute(task("score_rank"), "w") == "failed"

    assert "could not start" in rec.finished[0][3] and "no interpreter" in rec.finished[0][3]


def test_a_task_interrupted_by_a_stopping_worker_is_failed_not_cancelled(monkeypatch, rec):
    fake_lock(monkeypatch)

    def stopping(argv, **kwargs):
        monkeypatch.setattr(ops_worker, "_stop_requested", True)
        return runner.RunResult("cancelled", -15, "partial\n")

    monkeypatch.setattr(runner, "run", stopping)

    assert ops_worker.execute(task("score_rank"), "w") == "failed"
    assert "worker stopped" in rec.finished[0][3]


# --- the pipeline lock -----------------------------------------------------------


def test_an_exclusive_task_waits_for_a_busy_pipeline_instead_of_failing(monkeypatch, rec):
    lock = fake_lock(monkeypatch, busy="a run is in flight")
    fake_run(monkeypatch, raises=AssertionError("must not run while the lock is busy"))

    assert ops_worker.execute(task("score_rank"), "w") == "queued"

    assert rec.finished == []
    ((task_id, delay, note),) = rec.requeued
    assert task_id == 7 and delay == ops_worker.LOCK_RETRY_SECONDS and "a run is in flight" in note
    assert lock["released"] == []


def test_the_lock_is_released_after_a_run_and_after_a_crash(monkeypatch, rec):
    lock = fake_lock(monkeypatch)
    fake_run(monkeypatch, runner.RunResult("succeeded", 0, ""))
    ops_worker.execute(task("score_rank"), "w")
    fake_run(monkeypatch, raises=OSError("disk gone"))
    ops_worker.execute(task("score_rank"), "w")

    assert lock["acquired"] == 2 and lock["released"] == ["handle", "handle"]


def test_a_task_that_manages_its_own_lock_does_not_take_one_here(monkeypatch, rec):
    # run_full_etl takes the pipeline lock itself; taking it here as well would make it
    # refuse to start. verify_nightly is read-only and needs none.
    lock = fake_lock(monkeypatch)
    fake_run(monkeypatch, runner.RunResult("succeeded", 0, ""))

    ops_worker.execute(task("run_full_etl"), "w")
    ops_worker.execute(task("verify_nightly"), "w")

    assert lock["acquired"] == 0


# --- heartbeat and cancel --------------------------------------------------------


def test_the_heartbeat_stores_output_and_passes_a_cancel_request_back(monkeypatch, rec):
    fake_lock(monkeypatch)
    seen = {}
    fake_run(monkeypatch, runner.RunResult("succeeded", 0, ""), capture=seen)
    ops_worker.execute(task("score_rank"), "w1")
    tick = seen["kwargs"]["tick"]

    assert tick("line\n") is False
    rec.cancel_requested = True
    assert tick("line\nmore\n") is True

    assert rec.heartbeats[-1] == (7, "line\nmore\n")
    assert rec.touched[-1] == ("w1", 7)


def test_the_task_is_told_to_stop_when_the_worker_is_stopping(monkeypatch, rec):
    fake_lock(monkeypatch)
    seen = {}
    fake_run(monkeypatch, runner.RunResult("succeeded", 0, ""), capture=seen)
    ops_worker.execute(task("score_rank"), "w")

    monkeypatch.setattr(ops_worker, "_stop_requested", True)

    assert seen["kwargs"]["tick"]("x") is True


def test_the_child_inherits_unbuffered_output_so_the_log_is_live(monkeypatch, rec):
    fake_lock(monkeypatch)
    seen = {}
    fake_run(monkeypatch, runner.RunResult("succeeded", 0, ""), capture=seen)
    ops_worker.execute(task("score_rank"), "w")
    assert seen["kwargs"]["env"]["PYTHONUNBUFFERED"] == "1"


# --- the loop --------------------------------------------------------------------


def test_one_loop_sweeps_queues_due_schedules_and_runs_the_claimed_task(monkeypatch, rec):
    calls = []
    monkeypatch.setattr(store, "recover_orphans", lambda c: calls.append("recover") or [])
    monkeypatch.setattr(store, "enqueue_due", lambda c: calls.append("due") or [])
    monkeypatch.setattr(
        store, "claim_next", lambda c, w: calls.append("claim") or task("score_rank")
    )
    monkeypatch.setattr(ops_worker, "execute", lambda t, w: calls.append("execute") or "succeeded")

    assert ops_worker.loop_once("w") is True

    assert calls == ["recover", "due", "claim", "execute"]
    assert rec.touched == [("w", None)]


def test_an_idle_loop_runs_nothing(monkeypatch, rec):
    monkeypatch.setattr(store, "recover_orphans", lambda c: [])
    monkeypatch.setattr(store, "enqueue_due", lambda c: [])
    monkeypatch.setattr(store, "claim_next", lambda c, w: None)
    monkeypatch.setattr(ops_worker, "execute", lambda t, w: pytest.fail("nothing to run"))

    assert ops_worker.loop_once("w") is False
