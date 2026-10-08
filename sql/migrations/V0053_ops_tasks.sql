-- V0053 ops: task queue, schedules and worker heartbeats for the web app
--
-- The Streamlit app can queue and schedule operational tasks, and a separate worker
-- process runs them. A web request cannot run a multi-hour job (Streamlit re-runs the
-- script on every interaction), and the nightly runs from the host's systemd timer, not
-- from the app container, so the app and the worker meet in the database.
--
-- Nothing here stores a command. A task row holds a catalog key and validated
-- parameters; the worker rebuilds the argv from the in-code allowlist
-- (src/crispdm/ops/catalog.py) and re-validates the parameters, so a row written by
-- anything other than the app cannot run anything outside the allowlist.
--
-- The host's nightly timer is deliberately NOT modelled as a schedule: the app cannot
-- manage a systemd unit, and a second 03:00 job in here would run the ETL twice.

CREATE SCHEMA IF NOT EXISTS ops;

COMMENT ON SCHEMA ops IS
    'Operational task queue, schedules and worker heartbeats for the Streamlit app';

CREATE TABLE IF NOT EXISTS ops.schedules (
    schedule_id      BIGSERIAL PRIMARY KEY,
    name             TEXT        NOT NULL,
    task_key         TEXT        NOT NULL,
    params           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    kind             TEXT        NOT NULL,
    run_at           TIMESTAMPTZ,
    interval_minutes INTEGER,
    daily_time       TIME,
    timezone         TEXT        NOT NULL DEFAULT 'America/New_York',
    enabled          BOOLEAN     NOT NULL DEFAULT TRUE,
    next_run_at      TIMESTAMPTZ,
    last_run_at      TIMESTAMPTZ,
    created_by       TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_schedules_kind CHECK (kind IN ('once', 'interval', 'daily')),
    CONSTRAINT chk_schedules_interval CHECK (
        interval_minutes IS NULL OR interval_minutes BETWEEN 5 AND 10080),
    CONSTRAINT chk_schedules_shape CHECK (
        (kind = 'once' AND run_at IS NOT NULL)
        OR (kind = 'interval' AND interval_minutes IS NOT NULL)
        OR (kind = 'daily' AND daily_time IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS ix_schedules_due ON ops.schedules (next_run_at) WHERE enabled;

CREATE TABLE IF NOT EXISTS ops.tasks (
    task_id          BIGSERIAL PRIMARY KEY,
    task_key         TEXT        NOT NULL,
    params           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status           TEXT        NOT NULL DEFAULT 'queued',
    source           TEXT        NOT NULL DEFAULT 'manual',
    schedule_id      BIGINT REFERENCES ops.schedules (schedule_id) ON DELETE SET NULL,
    requested_by     TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    not_before       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    heartbeat_at     TIMESTAMPTZ,
    worker           TEXT,
    attempts         INTEGER     NOT NULL DEFAULT 0,
    exit_code        INTEGER,
    cancel_requested BOOLEAN     NOT NULL DEFAULT FALSE,
    log_tail         TEXT        NOT NULL DEFAULT '',
    CONSTRAINT chk_tasks_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out')),
    CONSTRAINT chk_tasks_source CHECK (source IN ('manual', 'schedule'))
);

CREATE INDEX IF NOT EXISTS ix_tasks_queue ON ops.tasks (not_before, created_at)
    WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS ix_tasks_created ON ops.tasks (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_tasks_schedule ON ops.tasks (schedule_id);

-- A schedule never stacks runs: at most one of its tasks may be queued or running,
-- the same rule the host timer follows ("wait for it rather than run a concurrent ETL").
CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_one_open_per_schedule
    ON ops.tasks (schedule_id)
    WHERE schedule_id IS NOT NULL AND status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS ops.workers (
    worker          TEXT PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    current_task_id BIGINT
);

COMMENT ON TABLE ops.schedules IS
    'Recurring or one-off task schedules created in the app; the worker enqueues due ones';
COMMENT ON COLUMN ops.schedules.name IS 'Human label shown in the app';
COMMENT ON COLUMN ops.schedules.task_key IS 'Key into the in-code task catalog (src/crispdm/ops/catalog.py)';
COMMENT ON COLUMN ops.schedules.params IS 'Validated parameters passed to the task';
COMMENT ON COLUMN ops.schedules.kind IS 'once (run_at), interval (interval_minutes) or daily (daily_time in timezone)';
COMMENT ON COLUMN ops.schedules.run_at IS 'When a once schedule fires (UTC)';
COMMENT ON COLUMN ops.schedules.interval_minutes IS 'Minutes between runs for an interval schedule (5 to 10080)';
COMMENT ON COLUMN ops.schedules.daily_time IS 'Local wall-clock time of a daily schedule, in the timezone column';
COMMENT ON COLUMN ops.schedules.timezone IS 'IANA zone that daily_time is read in; DST-aware';
COMMENT ON COLUMN ops.schedules.enabled IS 'FALSE pauses the schedule; a fired once schedule disables itself';
COMMENT ON COLUMN ops.schedules.next_run_at IS 'Next due instant (UTC); NULL once nothing is left to run';
COMMENT ON COLUMN ops.schedules.last_run_at IS 'When the worker last enqueued a task for this schedule (UTC)';
COMMENT ON COLUMN ops.schedules.created_by IS 'Operator label recorded when the schedule was created';
COMMENT ON COLUMN ops.schedules.created_at IS 'When the schedule was created (UTC)';

COMMENT ON TABLE ops.tasks IS
    'Queue and audit trail of operational tasks; the worker runs them one at a time';
COMMENT ON COLUMN ops.tasks.task_key IS 'Key into the in-code task catalog; never a command';
COMMENT ON COLUMN ops.tasks.params IS 'Validated parameters; the worker re-validates them before running';
COMMENT ON COLUMN ops.tasks.status IS 'queued, running, succeeded, failed, cancelled or timed_out';
COMMENT ON COLUMN ops.tasks.source IS 'manual (queued from the app) or schedule (enqueued by the worker)';
COMMENT ON COLUMN ops.tasks.schedule_id IS 'Schedule that produced this task, if any';
COMMENT ON COLUMN ops.tasks.requested_by IS 'Operator label recorded when the task was queued';
COMMENT ON COLUMN ops.tasks.created_at IS 'When the task was queued (UTC)';
COMMENT ON COLUMN ops.tasks.not_before IS 'The worker does not start the task before this instant (UTC)';
COMMENT ON COLUMN ops.tasks.started_at IS 'When the worker started the task (UTC)';
COMMENT ON COLUMN ops.tasks.finished_at IS 'When the task reached a final status (UTC)';
COMMENT ON COLUMN ops.tasks.heartbeat_at IS 'Last heartbeat from the worker while running; a stale one marks a lost worker';
COMMENT ON COLUMN ops.tasks.worker IS 'Worker that claimed the task';
COMMENT ON COLUMN ops.tasks.attempts IS 'Times a worker claimed the task (a busy pipeline lock requeues it)';
COMMENT ON COLUMN ops.tasks.exit_code IS 'Process exit code once finished';
COMMENT ON COLUMN ops.tasks.cancel_requested IS 'TRUE when an operator asked for the running task to stop';
COMMENT ON COLUMN ops.tasks.log_tail IS 'Last part of the task output, bounded by the worker';

COMMENT ON TABLE ops.workers IS 'One row per worker process; last_seen tells the app whether tasks will be picked up';
COMMENT ON COLUMN ops.workers.worker IS 'host:pid of the worker process';
COMMENT ON COLUMN ops.workers.started_at IS 'When this worker process started (UTC)';
COMMENT ON COLUMN ops.workers.last_seen IS 'Last poll by this worker (UTC)';
COMMENT ON COLUMN ops.workers.current_task_id IS 'Task the worker is running now, if any';
