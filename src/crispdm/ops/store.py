"""Queue, schedule and worker-heartbeat storage for operational tasks.

Every function takes an open SQLAlchemy connection and never commits, so the caller owns
the transaction: the app and worker wrap calls in ``engine.begin()``, and the tests wrap
them in a transaction they roll back.

Parameters are validated against the catalog on the way in, so no unvalidated row is
ever written by this module. The worker validates again on the way out.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timezone

from sqlalchemy import text

from . import catalog, schedule

#: The log is kept in the row so the app can show it without sharing a volume with the
#: worker. Only the tail is stored: a multi-hour ETL prints far more than a row should hold.
LOG_TAIL_BYTES = 64_000

#: A running task whose worker has not heartbeat for this long is declared lost.
STALE_HEARTBEAT_SECONDS = 180

#: A worker counts as online if it polled within this window.
WORKER_ONLINE_SECONDS = 30

FINAL_STATUSES = ("succeeded", "failed", "cancelled", "timed_out")
OPEN_STATUSES = ("queued", "running")


class DuplicateTask(ValueError):
    """An identical task is already queued or running."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rows(conn, sql, params=None):
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings().all()]


def trim_log(text_value: str, limit: int = LOG_TAIL_BYTES) -> str:
    """Keep the last ``limit`` bytes of ``text_value``, on a character boundary."""
    data = text_value.encode("utf-8", "replace")
    if len(data) <= limit:
        return text_value
    return data[-limit:].decode("utf-8", "ignore")


# --- tasks -----------------------------------------------------------------------


def enqueue(
    conn,
    task_key: str,
    params: dict | None,
    requested_by: str,
    *,
    source: str = "manual",
    schedule_id: int | None = None,
    not_before: datetime | None = None,
) -> int | None:
    """Queue a task and return its id.

    A manual task identical to one already open raises :class:`DuplicateTask`, which is
    what stops a double click from queueing a six-hour job twice. A scheduled task
    that finds its schedule already has one open returns ``None`` instead: the slot is
    skipped, never stacked.
    """
    clean = catalog.validate_params(task_key, params)
    payload = json.dumps(clean, sort_keys=True)

    if schedule_id is None:
        existing = conn.execute(
            text("""
            SELECT task_id FROM ops.tasks
            WHERE task_key = :k AND params = CAST(:p AS jsonb)
              AND status IN ('queued', 'running') AND schedule_id IS NULL
            ORDER BY task_id LIMIT 1
        """),
            {"k": task_key, "p": payload},
        ).scalar()
        if existing is not None:
            raise DuplicateTask(f"an identical task is already queued or running (#{existing})")

    row = conn.execute(
        text("""
        INSERT INTO ops.tasks (task_key, params, source, schedule_id, requested_by, not_before)
        VALUES (:k, CAST(:p AS jsonb), :source, :sid, :by, COALESCE(:nb, now()))
        ON CONFLICT (schedule_id) WHERE schedule_id IS NOT NULL
            AND status IN ('queued', 'running') DO NOTHING
        RETURNING task_id
    """),
        {
            "k": task_key,
            "p": payload,
            "source": source,
            "sid": schedule_id,
            "by": requested_by,
            "nb": not_before,
        },
    ).first()
    return row[0] if row else None


def claim_next(conn, worker: str) -> dict | None:
    """Atomically take the oldest due queued task, or None. Safe with several workers."""
    row = (
        conn.execute(
            text("""
        UPDATE ops.tasks t
        SET status = 'running', started_at = now(), heartbeat_at = now(),
            worker = :w, attempts = t.attempts + 1, cancel_requested = FALSE
        WHERE t.task_id = (
            SELECT task_id FROM ops.tasks
            WHERE status = 'queued' AND not_before <= now()
            ORDER BY created_at, task_id
            LIMIT 1
            FOR UPDATE SKIP LOCKED)
        RETURNING t.task_id, t.task_key, t.params, t.attempts, t.requested_by
    """),
            {"w": worker},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def requeue_busy(conn, task_id: int, delay_seconds: int, note: str) -> None:
    """Put a claimed task back because the pipeline lock is busy."""
    conn.execute(
        text("""
        UPDATE ops.tasks
        SET status = 'queued', started_at = NULL, heartbeat_at = NULL, worker = NULL,
            not_before = now() + make_interval(secs => :d), log_tail = :note
        WHERE task_id = :id AND status = 'running'
    """),
        {"id": task_id, "d": delay_seconds, "note": trim_log(note)},
    )


def heartbeat(conn, task_id: int, log_tail: str) -> bool:
    """Record liveness and the log tail; return True when an operator asked to cancel."""
    return bool(
        conn.execute(
            text("""
        UPDATE ops.tasks SET heartbeat_at = now(), log_tail = :log
        WHERE task_id = :id AND status = 'running'
        RETURNING cancel_requested
    """),
            {"id": task_id, "log": trim_log(log_tail)},
        ).scalar()
    )


def finish(conn, task_id: int, status: str, exit_code: int | None, log_tail: str) -> None:
    if status not in FINAL_STATUSES:
        raise ValueError(f"{status!r} is not a final status")
    conn.execute(
        text("""
        UPDATE ops.tasks
        SET status = :s, exit_code = :c, finished_at = now(), log_tail = :log
        WHERE task_id = :id AND status = 'running'
    """),
        {"id": task_id, "s": status, "c": exit_code, "log": trim_log(log_tail)},
    )


def request_cancel(conn, task_id: int) -> str:
    """Cancel a queued task now, or ask the worker to stop a running one.

    Returns ``cancelled``, ``cancel_requested`` or ``not_open``.
    """
    queued = conn.execute(
        text("""
        UPDATE ops.tasks SET status = 'cancelled', finished_at = now()
        WHERE task_id = :id AND status = 'queued' RETURNING task_id
    """),
        {"id": task_id},
    ).first()
    if queued:
        return "cancelled"
    running = conn.execute(
        text("""
        UPDATE ops.tasks SET cancel_requested = TRUE
        WHERE task_id = :id AND status = 'running' RETURNING task_id
    """),
        {"id": task_id},
    ).first()
    return "cancel_requested" if running else "not_open"


def recover_orphans(conn, stale_seconds: int = STALE_HEARTBEAT_SECONDS) -> list[int]:
    """Fail running tasks whose worker stopped heartbeating (it crashed or was killed)."""
    rows = conn.execute(
        text("""
        UPDATE ops.tasks
        SET status = 'failed', finished_at = now(),
            log_tail = right(log_tail, :keep) || E'\\n[worker lost: no heartbeat]'
        WHERE status = 'running'
          AND heartbeat_at < now() - make_interval(secs => :s)
        RETURNING task_id
    """),
        {"s": stale_seconds, "keep": LOG_TAIL_BYTES // 2},
    ).all()
    return [r[0] for r in rows]


def get_task(conn, task_id: int) -> dict | None:
    rows = _rows(conn, "SELECT * FROM ops.tasks WHERE task_id = :id", {"id": task_id})
    return rows[0] if rows else None


def list_tasks(conn, *, status: str | None = None, limit: int = 200) -> list[dict]:
    limit = max(1, min(int(limit), 1000))
    where = "WHERE status = :s" if status else ""
    return _rows(
        conn,
        f"""
        SELECT task_id, task_key, params, status, source, schedule_id, requested_by,
               created_at, started_at, finished_at, exit_code, attempts, worker
        FROM ops.tasks {where} ORDER BY task_id DESC LIMIT :n
        """,
        {"n": limit, **({"s": status} if status else {})},
    )


# --- workers ---------------------------------------------------------------------


def touch_worker(conn, worker: str, current_task_id: int | None = None) -> None:
    conn.execute(
        text("""
        INSERT INTO ops.workers (worker, current_task_id) VALUES (:w, :t)
        ON CONFLICT (worker) DO UPDATE SET last_seen = now(), current_task_id = :t
    """),
        {"w": worker, "t": current_task_id},
    )
    # Keep the table to live and recent processes: one row per restart would grow forever.
    conn.execute(text("DELETE FROM ops.workers WHERE last_seen < now() - interval '2 days'"))


def online_workers(conn, within_seconds: int = WORKER_ONLINE_SECONDS) -> list[dict]:
    return _rows(
        conn,
        """
        SELECT worker, started_at, last_seen, current_task_id FROM ops.workers
        WHERE last_seen >= now() - make_interval(secs => :s) ORDER BY started_at
        """,
        {"s": within_seconds},
    )


# --- schedules -------------------------------------------------------------------


def create_schedule(
    conn,
    name: str,
    task_key: str,
    params: dict | None,
    kind: str,
    created_by: str,
    *,
    run_at: datetime | None = None,
    interval_minutes: int | None = None,
    daily_time: time | None = None,
    timezone_name: str = "America/New_York",
    now: datetime | None = None,
) -> int:
    name = (name or "").strip()
    if not 1 <= len(name) <= 80:
        raise ValueError("a schedule name must be 1 to 80 characters")
    clean = catalog.validate_params(task_key, params)
    schedule.check_timezone(timezone_name)
    now = now or _utc_now()
    first = schedule.first_run(
        kind,
        now=now,
        run_at=run_at,
        interval_minutes=interval_minutes,
        daily_time=daily_time,
        timezone_name=timezone_name,
    )
    if first is None:
        raise ValueError("the run time is in the past")
    return conn.execute(
        text("""
        INSERT INTO ops.schedules
            (name, task_key, params, kind, run_at, interval_minutes, daily_time, timezone,
             next_run_at, created_by)
        VALUES (:name, :k, CAST(:p AS jsonb), :kind, :run_at, :iv, :dt, :tz, :next, :by)
        RETURNING schedule_id
    """),
        {
            "name": name,
            "k": task_key,
            "p": json.dumps(clean, sort_keys=True),
            "kind": kind,
            "run_at": run_at if kind == "once" else None,
            "iv": interval_minutes if kind == "interval" else None,
            "dt": daily_time if kind == "daily" else None,
            "tz": timezone_name,
            "next": first,
            "by": created_by,
        },
    ).scalar()


def list_schedules(conn) -> list[dict]:
    return _rows(
        conn,
        """
        SELECT schedule_id, name, task_key, params, kind, run_at, interval_minutes, daily_time,
               timezone, enabled, next_run_at, last_run_at, created_by, created_at
        FROM ops.schedules ORDER BY enabled DESC, next_run_at NULLS LAST, schedule_id
        """,
    )


def set_schedule_enabled(conn, schedule_id: int, enabled: bool, *, now: datetime | None = None):
    """Pause or resume a schedule. Resuming recomputes the next slot from now."""
    now = now or _utc_now()
    row = (
        conn.execute(
            text(
                "SELECT kind, run_at, interval_minutes, daily_time, timezone "
                "FROM ops.schedules WHERE schedule_id = :id FOR UPDATE"
            ),
            {"id": schedule_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ValueError("no such schedule")
    if not enabled:
        conn.execute(
            text("UPDATE ops.schedules SET enabled = FALSE WHERE schedule_id = :id"),
            {"id": schedule_id},
        )
        return
    nxt = schedule.first_run(
        row["kind"],
        now=now,
        run_at=row["run_at"],
        interval_minutes=row["interval_minutes"],
        daily_time=row["daily_time"],
        timezone_name=row["timezone"],
    )
    if nxt is None:
        raise ValueError("this schedule has nothing left to run (its time has passed)")
    conn.execute(
        text("UPDATE ops.schedules SET enabled = TRUE, next_run_at = :n WHERE schedule_id = :id"),
        {"id": schedule_id, "n": nxt},
    )


def delete_schedule(conn, schedule_id: int) -> bool:
    return bool(
        conn.execute(
            text("DELETE FROM ops.schedules WHERE schedule_id = :id RETURNING schedule_id"),
            {"id": schedule_id},
        ).first()
    )


def enqueue_due(conn, *, now: datetime | None = None) -> list[int]:
    """Queue a task for every due schedule and advance each to its next slot.

    A schedule whose previous task is still open skips this slot rather than stacking.
    A missed schedule fires once and continues from ``now``; it does not replay.
    """
    now = now or _utc_now()
    due = (
        conn.execute(
            text("""
        SELECT schedule_id, task_key, params, kind, interval_minutes, daily_time, timezone,
               created_by
        FROM ops.schedules
        WHERE enabled AND next_run_at IS NOT NULL AND next_run_at <= :now
        ORDER BY next_run_at, schedule_id
        FOR UPDATE SKIP LOCKED
    """),
            {"now": now},
        )
        .mappings()
        .all()
    )
    queued: list[int] = []
    for row in due:
        task_id = None
        try:
            task_id = enqueue(
                conn,
                row["task_key"],
                row["params"],
                f"schedule #{row['schedule_id']}",
                source="schedule",
                schedule_id=row["schedule_id"],
            )
        except ValueError:
            # The catalog changed under a stored schedule; leave it unqueued and visible.
            task_id = None
        nxt = schedule.next_after_fire(
            row["kind"],
            fired_at=now,
            interval_minutes=row["interval_minutes"],
            daily_time=row["daily_time"],
            timezone_name=row["timezone"],
        )
        conn.execute(
            text("""
            UPDATE ops.schedules
            SET next_run_at = :n, enabled = :en,
                last_run_at = CASE WHEN :queued THEN :now ELSE last_run_at END
            WHERE schedule_id = :id
        """),
            {
                "id": row["schedule_id"],
                "n": nxt,
                "en": nxt is not None,
                "queued": task_id is not None,
                "now": now,
            },
        )
        if task_id is not None:
            queued.append(task_id)
    return queued
