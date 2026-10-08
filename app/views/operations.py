"""Operations: queue tasks, watch them run, and schedule them.

Streamlit reruns the script on every interaction and is not a place to run a six-hour job,
so this page only writes rows to ``ops.tasks`` and ``ops.schedules``. A separate worker
(``python -m scripts.ops_worker``) claims the rows and runs them. The worker rebuilds the
command from the allowlist in ``src.crispdm.ops.catalog``; nothing typed here is ever
executed as typed.

Everything that changes state needs a signed-in operator (see ``app.ui``).
"""

from __future__ import annotations

import json
from datetime import datetime, time
from zoneinfo import ZoneInfo, available_timezones

import pandas as pd
import streamlit as st

from app import ui
from src.crispdm.ops import catalog, schedule, store

STATUSES = ["queued", "running", "succeeded", "failed", "cancelled", "timed_out"]
RISK_TEXT = {
    "read": "Read-only.",
    "write": "Writes to the database.",
    "heavy": "Long-running and writes to the database.",
}
DEFAULT_TZ = "America/New_York"


def read(fn):
    with ui.engine.connect() as conn:
        return fn(conn)


def write(fn):
    with ui.engine.begin() as conn:
        return fn(conn)


def _json(value) -> str:
    return json.dumps(value, sort_keys=True) if value else "-"


# --- shared pieces ---------------------------------------------------------------


def task_picker(key: str):
    chosen = st.selectbox(
        "Task", list(catalog.CATALOG), format_func=lambda k: catalog.CATALOG[k].title, key=key
    )
    task = catalog.get_task(chosen)
    st.write(task.description)
    exclusive = (
        " Waits for the pipeline lock, so it never overlaps the nightly run."
        if task.exclusive
        else ""
    )
    st.caption(
        f"{RISK_TEXT[task.risk]} Stops after {task.timeout_seconds // 60} minutes.{exclusive}"
    )
    return task


def param_inputs(task, prefix: str) -> dict:
    """One input per allowlisted parameter; the values are validated before use."""
    values: dict = {}
    for param in task.params:
        key = f"{prefix}_{task.key}_{param.name}"
        if param.kind == "int":
            values[param.name] = st.number_input(
                param.label,
                min_value=param.minimum,
                max_value=param.maximum,
                value=param.default,
                step=1,
                help=param.help or None,
                key=key,
            )
        elif param.kind == "bool":
            values[param.name] = st.checkbox(
                param.label, value=bool(param.default), help=param.help or None, key=key
            )
        elif param.kind == "date":
            values[param.name] = st.date_input(
                param.label, value=None, help=param.help or None, key=key
            )
        else:
            values[param.name] = st.text_input(
                param.label, help=param.help or None, key=key, max_chars=1700
            )
    return values


def checked_params(task, raw: dict):
    """The canonical parameters, or None after showing why they are invalid.

    Shows the exact command the worker would run, rebuilt from the allowlist."""
    try:
        clean = catalog.validate_params(task.key, raw)
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.code(catalog.describe_command(task.key, clean), language="bash")
    return clean


def confirmed(task, key: str) -> bool:
    if task.risk != "heavy":
        return True
    return st.checkbox("I understand this can run for hours and changes data.", key=key)


# --- worker status ---------------------------------------------------------------


def worker_banner() -> None:
    try:
        workers = read(store.online_workers)
    except Exception as exc:  # the ops schema may be missing on an unmigrated database
        st.error(f"The task tables are unavailable ({type(exc).__name__}). Run the migrations.")
        st.stop()
    if workers:
        names = ", ".join(
            f"{w['worker']}"
            + (f" (running #{w['current_task_id']})" if w["current_task_id"] else "")
            for w in workers
        )
        st.success(f"Worker online: {names}")
    else:
        st.warning(
            "No worker is running, so queued tasks will wait. Start one with "
            "`python -m scripts.ops_worker` (the `worker` service in docker-compose)."
        )
    st.caption(
        "The nightly ETL is started by the host's systemd timer at 03:00 America/New_York, "
        "not from here. Tasks queued here can run beside it only when they take the same "
        "pipeline lock, which the exclusive ones do."
    )


# --- run tab ---------------------------------------------------------------------


def run_tab() -> None:
    task = task_picker("ops_run_task")
    params = param_inputs(task, "run")
    clean = checked_params(task, params)
    ok = confirmed(task, f"ops_confirm_{task.key}")
    ui.require_controls_note()
    disabled = clean is None or not ok or not ui.controls_enabled()
    if st.button("Queue task", type="primary", disabled=disabled, key="ops_queue"):
        try:
            task_id = write(lambda c: store.enqueue(c, task.key, clean, ui.operator()))
        except store.DuplicateTask as exc:
            st.warning(str(exc))
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(f"Queued as task #{task_id}. Follow it under Queue and history.")


# --- queue tab -------------------------------------------------------------------


def task_detail(task_id: int) -> None:
    row = read(lambda c: store.get_task(c, task_id))
    if row is None:
        st.caption("That task no longer exists.")
        return
    title = (
        catalog.CATALOG[row["task_key"]].title
        if row["task_key"] in catalog.CATALOG
        else row["task_key"]
    )
    st.markdown(f"**#{row['task_id']} {title}** {ui.status_label(row['status'])}")
    try:
        st.code(catalog.describe_command(row["task_key"], row["params"]), language="bash")
    except ValueError:
        st.caption("This task's definition is no longer in the catalog.")
    cells = st.columns(4)
    cells[0].metric("Exit code", "-" if row["exit_code"] is None else row["exit_code"])
    cells[1].metric(
        "Duration", ui.fmt_duration(row["started_at"], row["finished_at"] or ui.now_utc())
    )
    cells[2].metric("Attempts", row["attempts"])
    cells[3].metric("Worker", row["worker"] or "-")
    if row["cancel_requested"] and row["status"] == "running":
        st.warning("Cancel requested; waiting for the worker to stop the process.")
    st.code(row["log_tail"] or "(no output yet)", language=None)

    open_task = row["status"] in store.OPEN_STATUSES
    if ui.controls_enabled():
        if open_task and st.button("Cancel task", key=f"ops_cancel_{task_id}"):
            outcome = write(lambda c: store.request_cancel(c, task_id))
            st.toast(f"Task #{task_id}: {outcome.replace('_', ' ')}")
        if not open_task and st.button("Run again", key=f"ops_again_{task_id}"):
            try:
                new_id = write(
                    lambda c: store.enqueue(c, row["task_key"], row["params"], ui.operator())
                )
                st.toast(f"Queued as task #{new_id}")
            except (store.DuplicateTask, ValueError) as exc:
                st.warning(str(exc))
    else:
        ui.require_controls_note()


@st.fragment(run_every="10s")
def queue_view() -> None:
    status = st.selectbox("Status", ["all", *STATUSES], key="ops_status_filter")
    tasks = read(
        lambda c: store.list_tasks(c, status=None if status == "all" else status, limit=100)
    )
    if not tasks:
        st.caption("No tasks.")
        return
    frame = pd.DataFrame(
        [
            {
                "id": t["task_id"],
                "task": t["task_key"],
                "parameters": _json(t["params"]),
                "status": t["status"],
                "source": t["source"],
                "requested by": t["requested_by"],
                "created": ui.fmt_ts(t["created_at"]),
                "duration": ui.fmt_duration(t["started_at"], t["finished_at"]),
                "exit": t["exit_code"],
            }
            for t in tasks
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")
    st.caption("Times are UTC.")
    picked = st.selectbox("Inspect a task", [t["task_id"] for t in tasks], key="ops_inspect")
    task_detail(picked)


# --- schedules tab ---------------------------------------------------------------


def schedule_table(rows: list[dict]) -> None:
    frame = pd.DataFrame(
        [
            {
                "id": s["schedule_id"],
                "name": s["name"],
                "task": s["task_key"],
                "parameters": _json(s["params"]),
                "when": schedule.describe(
                    s["kind"],
                    run_at=s["run_at"],
                    interval_minutes=s["interval_minutes"],
                    daily_time=s["daily_time"],
                    timezone_name=s["timezone"],
                ),
                "state": "active" if s["enabled"] else "paused",
                "next run": ui.fmt_ts(s["next_run_at"]),
                "last run": ui.fmt_ts(s["last_run_at"]),
            }
            for s in rows
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")
    st.caption(
        "Times are UTC. A schedule never stacks: if its last task is still open, that slot is skipped."
    )


def manage_schedule(rows: list[dict]) -> None:
    if not ui.controls_enabled():
        ui.require_controls_note()
        return
    by_id = {s["schedule_id"]: s for s in rows}
    chosen = st.selectbox(
        "Manage a schedule",
        list(by_id),
        format_func=lambda i: f"#{i} {by_id[i]['name']}",
        key="ops_manage",
    )
    current = by_id[chosen]
    a, b, c = st.columns(3)
    label = "Pause" if current["enabled"] else "Resume"
    if a.button(label, key="ops_toggle"):
        try:
            write(lambda conn: store.set_schedule_enabled(conn, chosen, not current["enabled"]))
        except ValueError as exc:
            st.warning(str(exc))
        else:
            st.rerun()
    sure = b.checkbox("Confirm delete", key=f"ops_del_ok_{chosen}")
    if c.button("Delete", disabled=not sure, key="ops_delete"):
        write(lambda conn: store.delete_schedule(conn, chosen))
        st.rerun()


def new_schedule() -> None:
    task = task_picker("ops_sched_task")
    params = param_inputs(task, "sched")
    clean = checked_params(task, params)
    ok = confirmed(task, f"ops_sched_confirm_{task.key}")

    name = st.text_input("Schedule name", max_chars=80, key="ops_sched_name")
    kind = st.radio("Repeat", ["interval", "daily", "once"], horizontal=True, key="ops_sched_kind")
    zones = sorted(available_timezones())
    tz = st.selectbox("Time zone", zones, index=zones.index(DEFAULT_TZ), key="ops_sched_tz")

    extra: dict = {}
    if kind == "interval":
        extra["interval_minutes"] = int(
            st.number_input(
                "Every N minutes",
                min_value=schedule.MIN_INTERVAL_MINUTES,
                max_value=schedule.MAX_INTERVAL_MINUTES,
                value=1440,
                step=5,
                key="ops_sched_minutes",
            )
        )
    elif kind == "daily":
        extra["daily_time"] = st.time_input("Time of day", value=time(6, 0), key="ops_sched_time")
    else:
        day = st.date_input("Date", key="ops_sched_day")
        at = st.time_input("Time", value=time(6, 0), key="ops_sched_at")
        extra["run_at"] = datetime.combine(day, at).replace(tzinfo=ZoneInfo(tz))

    ui.require_controls_note()
    disabled = clean is None or not ok or not name.strip() or not ui.controls_enabled()
    if st.button("Create schedule", type="primary", disabled=disabled, key="ops_sched_create"):
        try:
            sid = write(
                lambda c: store.create_schedule(
                    c, name, task.key, clean, kind, ui.operator(), timezone_name=tz, **extra
                )
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(f"Created schedule #{sid}.")


def schedules_tab() -> None:
    rows = read(store.list_schedules)
    if rows:
        schedule_table(rows)
        manage_schedule(rows)
    else:
        st.caption("No schedules yet.")
    with st.expander("New schedule", expanded=not rows):
        new_schedule()


def render() -> None:
    st.title("Operations")
    worker_banner()
    run, queue, schedules = st.tabs(["Run a task", "Queue and history", "Schedules"])
    with run:
        run_tab()
    with queue:
        queue_view()
    with schedules:
        schedules_tab()
