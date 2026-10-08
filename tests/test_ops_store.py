"""The task queue and schedules against the real ``ops`` schema.

Every test but one runs in a transaction that is rolled back, so the live tables are
untouched. The exception is the concurrency test, which has to commit to prove two
connections are handed different tasks; it removes its rows by a unique marker.
"""

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from src.crispdm.ops import store

UTC = timezone.utc
BY = "pytest"


def _live_engine():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1 FROM ops.tasks LIMIT 1")
        return engine
    except Exception:  # pragma: no cover - no database, or V0053 not applied
        return None


pytestmark = pytest.mark.skipif(_live_engine() is None, reason="no live database with ops schema")


@pytest.fixture
def conn():
    """A connection inside a transaction that is always rolled back."""
    with _live_engine().connect() as connection:
        outer = connection.begin()
        # Isolate from any real rows an operator may have queued.
        connection.execute(text("DELETE FROM ops.tasks"))
        connection.execute(text("DELETE FROM ops.schedules"))
        connection.execute(text("DELETE FROM ops.workers"))
        try:
            yield connection
        finally:
            outer.rollback()


def status(conn, task_id):
    return conn.execute(
        text("SELECT status FROM ops.tasks WHERE task_id = :i"), {"i": task_id}
    ).scalar()


# --- queueing --------------------------------------------------------------------


def test_a_task_is_queued_with_canonical_parameters(conn):
    task_id = store.enqueue(conn, "build_features", {"days": 120}, BY)

    row = store.get_task(conn, task_id)
    assert row["status"] == "queued" and row["source"] == "manual" and row["requested_by"] == BY
    assert row["params"] == {"days": 120}


def test_defaults_are_filled_in_and_stored(conn):
    task_id = store.enqueue(conn, "build_features", {}, BY)
    assert store.get_task(conn, task_id)["params"] == {"days": 400}


def test_an_invalid_task_writes_no_row(conn):
    for key, params in (("nope", {}), ("build_features", {"days": "x"}), ("score_rank", {"x": 1})):
        with pytest.raises(ValueError):
            store.enqueue(conn, key, params, BY)
    assert conn.execute(text("SELECT count(*) FROM ops.tasks")).scalar() == 0


def test_an_identical_open_task_is_refused_but_a_different_one_is_allowed(conn):
    first = store.enqueue(conn, "build_features", {"days": 120}, BY)

    with pytest.raises(store.DuplicateTask, match=f"#{first}"):
        store.enqueue(conn, "build_features", {"days": 120}, BY)
    store.enqueue(conn, "build_features", {"days": 130}, BY)  # different parameters: fine

    conn.execute(text("UPDATE ops.tasks SET status = 'succeeded' WHERE task_id = :i"), {"i": first})
    store.enqueue(conn, "build_features", {"days": 120}, BY)  # finished: may run again


# --- claiming --------------------------------------------------------------------


def test_the_oldest_due_task_is_claimed_first_and_marked_running(conn):
    a = store.enqueue(conn, "score_rank", {}, BY)
    b = store.enqueue(conn, "populate_audit", {}, BY)

    first = store.claim_next(conn, "w1")
    second = store.claim_next(conn, "w1")

    assert (first["task_id"], second["task_id"]) == (a, b)
    assert first["attempts"] == 1 and first["task_key"] == "score_rank"
    row = store.get_task(conn, a)
    assert row["status"] == "running" and row["worker"] == "w1" and row["started_at"] is not None
    assert store.claim_next(conn, "w1") is None


def test_a_task_scheduled_for_later_is_not_claimed_yet(conn):
    store.enqueue(conn, "score_rank", {}, BY, not_before=datetime.now(UTC) + timedelta(hours=1))
    assert store.claim_next(conn, "w1") is None


def test_a_busy_pipeline_puts_the_task_back_with_a_delay(conn):
    task_id = store.enqueue(conn, "score_rank", {}, BY)
    store.claim_next(conn, "w1")

    store.requeue_busy(conn, task_id, 60, "[waiting: busy]")

    row = store.get_task(conn, task_id)
    assert row["status"] == "queued" and row["worker"] is None and "waiting" in row["log_tail"]
    assert store.claim_next(conn, "w1") is None, "the delay must hold it back"


def test_two_workers_are_handed_different_tasks_at_the_same_time():
    """SKIP LOCKED: the second claimer must not block on, or duplicate, the first's row."""
    marker = f"pytest-{uuid.uuid4().hex[:8]}"
    engine = _live_engine()
    ids = []
    try:
        with engine.begin() as setup:
            setup.execute(text("DELETE FROM ops.tasks WHERE requested_by LIKE 'pytest-%'"))
            ids = [
                store.enqueue(setup, "score_rank", {}, marker),
                store.enqueue(setup, "populate_audit", {}, marker),
            ]
        with engine.connect() as one, engine.connect() as two:
            t1, t2 = one.begin(), two.begin()
            # Restrict the race to this test's rows so a real queued task cannot interfere.
            a = one.execute(
                text(
                    "SELECT task_id FROM ops.tasks WHERE requested_by = :m AND status = 'queued' "
                    "ORDER BY task_id LIMIT 1 FOR UPDATE SKIP LOCKED"
                ),
                {"m": marker},
            ).scalar()
            b = two.execute(
                text(
                    "SELECT task_id FROM ops.tasks WHERE requested_by = :m AND status = 'queued' "
                    "ORDER BY task_id LIMIT 1 FOR UPDATE SKIP LOCKED"
                ),
                {"m": marker},
            ).scalar()
            t1.rollback()
            t2.rollback()
        assert {a, b} == set(ids), f"expected two distinct tasks, got {a} and {b}"
    finally:
        with engine.begin() as cleanup:
            cleanup.execute(text("DELETE FROM ops.tasks WHERE requested_by = :m"), {"m": marker})


# --- progress, cancel, recovery --------------------------------------------------


def test_heartbeat_stores_the_log_and_reports_a_cancel_request(conn):
    task_id = store.enqueue(conn, "score_rank", {}, BY)
    store.claim_next(conn, "w1")

    assert store.heartbeat(conn, task_id, "line 1\n") is False
    assert store.request_cancel(conn, task_id) == "cancel_requested"
    assert store.heartbeat(conn, task_id, "line 1\nline 2\n") is True
    assert store.get_task(conn, task_id)["log_tail"] == "line 1\nline 2\n"


def test_cancelling_a_queued_task_cancels_it_immediately(conn):
    task_id = store.enqueue(conn, "score_rank", {}, BY)
    assert store.request_cancel(conn, task_id) == "cancelled"
    assert status(conn, task_id) == "cancelled"
    assert store.claim_next(conn, "w1") is None


def test_cancelling_a_finished_or_unknown_task_does_nothing(conn):
    task_id = store.enqueue(conn, "score_rank", {}, BY)
    store.claim_next(conn, "w1")
    store.finish(conn, task_id, "succeeded", 0, "done")
    assert store.request_cancel(conn, task_id) == "not_open"
    assert store.request_cancel(conn, 10**12) == "not_open"


def test_finish_records_the_outcome_only_from_running(conn):
    task_id = store.enqueue(conn, "score_rank", {}, BY)
    store.finish(conn, task_id, "failed", 1, "ignored: it was never running")
    assert status(conn, task_id) == "queued"

    store.claim_next(conn, "w1")
    store.finish(conn, task_id, "failed", 7, "boom")
    row = store.get_task(conn, task_id)
    assert (row["status"], row["exit_code"], row["log_tail"]) == ("failed", 7, "boom")
    assert row["finished_at"] is not None

    with pytest.raises(ValueError, match="final status"):
        store.finish(conn, task_id, "running", None, "")


def test_a_task_whose_worker_went_silent_is_failed_and_a_live_one_is_not(conn):
    stale = store.enqueue(conn, "score_rank", {}, BY)
    live = store.enqueue(conn, "populate_audit", {}, BY)
    store.claim_next(conn, "w1")
    store.claim_next(conn, "w2")
    conn.execute(
        text("UPDATE ops.tasks SET heartbeat_at = now() - interval '1 hour' WHERE task_id = :i"),
        {"i": stale},
    )

    assert store.recover_orphans(conn) == [stale]
    assert (
        status(conn, stale) == "failed" and "worker lost" in store.get_task(conn, stale)["log_tail"]
    )
    assert status(conn, live) == "running"


def test_the_stored_log_keeps_the_tail_on_a_character_boundary():
    text_value = "é" * 40_000 + "TAIL"
    trimmed = store.trim_log(text_value, 1000)
    assert trimmed.endswith("TAIL") and len(trimmed.encode()) <= 1000
    assert store.trim_log("short") == "short"


def test_the_task_list_is_newest_first_and_filterable(conn):
    a = store.enqueue(conn, "score_rank", {}, BY)
    b = store.enqueue(conn, "populate_audit", {}, BY)
    store.claim_next(conn, "w1")

    assert [t["task_id"] for t in store.list_tasks(conn)] == [b, a]
    assert [t["task_id"] for t in store.list_tasks(conn, status="running")] == [a]
    assert len(store.list_tasks(conn, limit=1)) == 1


# --- workers ---------------------------------------------------------------------


def test_a_worker_is_online_only_while_it_keeps_polling(conn):
    store.touch_worker(conn, "w1")
    store.touch_worker(conn, "w2", current_task_id=5)
    conn.execute(
        text("UPDATE ops.workers SET last_seen = now() - interval '5 minutes' WHERE worker = 'w2'")
    )

    assert [w["worker"] for w in store.online_workers(conn)] == ["w1"]


# --- schedules -------------------------------------------------------------------

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def make(conn, kind="interval", **kw):
    kw.setdefault("now", NOW)
    if kind == "interval":
        kw.setdefault("interval_minutes", 60)
    if kind == "daily":
        kw.setdefault("daily_time", time(3, 0))
    return store.create_schedule(conn, "nightly audit", "populate_audit", {}, kind, BY, **kw)


def schedule_row(conn, schedule_id):
    return next(s for s in store.list_schedules(conn) if s["schedule_id"] == schedule_id)


def test_schedules_of_each_kind_are_created_with_their_first_slot(conn):
    interval = schedule_row(conn, make(conn, "interval", interval_minutes=90))
    daily = schedule_row(conn, make(conn, "daily"))
    once = schedule_row(conn, make(conn, "once", run_at=NOW + timedelta(hours=2)))

    assert interval["next_run_at"] == NOW + timedelta(minutes=90)
    assert daily["next_run_at"].astimezone(timezone(timedelta(hours=-4))).hour == 3
    assert once["next_run_at"] == NOW + timedelta(hours=2) and once["run_at"] == once["next_run_at"]


def test_a_bad_schedule_is_refused_and_writes_nothing(conn):
    bad = [
        dict(name="", kind="interval", interval_minutes=60),
        dict(name="x" * 81, kind="interval", interval_minutes=60),
        dict(name="n", kind="interval", interval_minutes=1),
        dict(name="n", kind="once", run_at=NOW - timedelta(minutes=1)),
        dict(name="n", kind="interval", interval_minutes=60, timezone_name="Mars/Base"),
        dict(name="n", kind="weekly"),
    ]
    for case in bad:
        name, kind = case.pop("name"), case.pop("kind")
        with pytest.raises(ValueError):
            store.create_schedule(conn, name, "populate_audit", {}, kind, BY, now=NOW, **case)
    with pytest.raises(ValueError, match="unknown task"):
        store.create_schedule(conn, "n", "nope", {}, "interval", BY, interval_minutes=60, now=NOW)
    assert conn.execute(text("SELECT count(*) FROM ops.schedules")).scalar() == 0


def test_a_due_schedule_queues_one_task_and_moves_to_its_next_slot(conn):
    sid = make(conn, "interval", interval_minutes=60)
    later = NOW + timedelta(minutes=61)

    queued = store.enqueue_due(conn, now=later)

    assert len(queued) == 1
    task = store.get_task(conn, queued[0])
    assert (task["source"], task["schedule_id"], task["task_key"]) == (
        "schedule",
        sid,
        "populate_audit",
    )
    assert task["requested_by"] == f"schedule #{sid}"
    row = schedule_row(conn, sid)
    assert row["next_run_at"] == later + timedelta(minutes=60) and row["last_run_at"] == later


def test_a_schedule_that_is_not_due_queues_nothing(conn):
    make(conn, "interval", interval_minutes=60)
    assert store.enqueue_due(conn, now=NOW + timedelta(minutes=30)) == []


def test_a_schedule_never_stacks_runs(conn):
    sid = make(conn, "interval", interval_minutes=10)
    first = store.enqueue_due(conn, now=NOW + timedelta(minutes=11))
    assert len(first) == 1

    second = store.enqueue_due(conn, now=NOW + timedelta(minutes=22))  # first still open

    assert second == []
    assert (
        conn.execute(
            text("SELECT count(*) FROM ops.tasks WHERE schedule_id = :i"), {"i": sid}
        ).scalar()
        == 1
    )
    assert schedule_row(conn, sid)["next_run_at"] == NOW + timedelta(minutes=32), (
        "the slot is skipped, not queued"
    )


def test_a_missed_schedule_fires_once_then_continues_from_now(conn):
    sid = make(conn, "interval", interval_minutes=60)
    woke = NOW + timedelta(days=3)

    assert len(store.enqueue_due(conn, now=woke)) == 1  # not 72

    assert schedule_row(conn, sid)["next_run_at"] == woke + timedelta(minutes=60)


def test_a_once_schedule_fires_and_then_disables_itself(conn):
    sid = make(conn, "once", run_at=NOW + timedelta(hours=1))

    assert len(store.enqueue_due(conn, now=NOW + timedelta(hours=2))) == 1

    row = schedule_row(conn, sid)
    assert row["enabled"] is False and row["next_run_at"] is None
    assert store.enqueue_due(conn, now=NOW + timedelta(hours=9)) == []


def test_a_paused_schedule_does_not_fire_and_resuming_recomputes_the_slot(conn):
    sid = make(conn, "interval", interval_minutes=60)
    store.set_schedule_enabled(conn, sid, False)
    assert store.enqueue_due(conn, now=NOW + timedelta(days=1)) == []

    resumed_at = NOW + timedelta(days=1)
    store.set_schedule_enabled(conn, sid, True, now=resumed_at)

    row = schedule_row(conn, sid)
    assert row["enabled"] is True and row["next_run_at"] == resumed_at + timedelta(minutes=60)


def test_a_once_schedule_whose_time_has_passed_cannot_be_resumed(conn):
    sid = make(conn, "once", run_at=NOW + timedelta(hours=1))
    store.enqueue_due(conn, now=NOW + timedelta(hours=2))
    with pytest.raises(ValueError, match="nothing left"):
        store.set_schedule_enabled(conn, sid, True, now=NOW + timedelta(hours=3))


def test_deleting_a_schedule_keeps_the_tasks_it_produced(conn):
    sid = make(conn, "interval", interval_minutes=10)
    (task_id,) = store.enqueue_due(conn, now=NOW + timedelta(minutes=11))

    assert store.delete_schedule(conn, sid) is True

    kept = store.get_task(conn, task_id)
    assert kept is not None and kept["schedule_id"] is None
    assert store.delete_schedule(conn, sid) is False


def test_resuming_an_unknown_schedule_is_refused(conn):
    with pytest.raises(ValueError, match="no such schedule"):
        store.set_schedule_enabled(conn, 10**12, True)
