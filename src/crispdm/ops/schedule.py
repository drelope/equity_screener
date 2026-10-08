"""When a schedule next fires. Pure arithmetic, no database, so the edge cases can be tested.

Three kinds:

``once``      fires at a fixed instant and then has nothing left to run.
``interval``  fires every N minutes, counted from the moment it last fired.
``daily``     fires at a wall-clock time in an IANA zone, every day.

A schedule that was missed (the worker was down) fires once, then continues from now.
It does not replay every slot it missed: replaying a day of hourly runs of a heavy task
on restart is the failure mode, not the recovery.

Daily times are read in the schedule's zone, so a 03:00 America/New_York job stays at
03:00 across daylight-saving changes. On the spring-forward day a wall-clock time that
does not exist (02:30) is read with the offset in force before the change and so fires
at 03:30 EDT; on the fall-back day an ambiguous time (01:30) fires on its first
occurrence, once.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc

MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 7 * 24 * 60


def check_timezone(name: str) -> ZoneInfo:
    """The zone for ``name``, or ValueError. Rejects anything that is not an IANA key."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError, OSError):
        raise ValueError(f"unknown time zone {name!r}") from None


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("datetimes must be timezone-aware")
    return moment.astimezone(UTC)


def next_daily(after: datetime, at: time, tz_name: str) -> datetime:
    """The first instant strictly after ``after`` whose local time in ``tz_name`` is ``at``."""
    zone = check_timezone(tz_name)
    after = _as_utc(after)
    local_date = after.astimezone(zone).date()
    wall = at.replace(tzinfo=None)
    # Today's slot may already have passed; tomorrow's cannot be earlier than ``after``.
    # Two extra days cover a slot that a DST gap pushes later than ``after``.
    for offset in range(0, 4):
        day = local_date + timedelta(days=offset)
        candidate = datetime.combine(day, wall, tzinfo=zone).astimezone(UTC)
        # A wall time inside a spring-forward gap is read with the offset in force before
        # the change (fold=0), which lands it an hour later in local time (02:30 -> 03:30).
        if candidate > after:
            return candidate
    raise RuntimeError("no daily slot found")  # pragma: no cover - unreachable


def first_run(
    kind: str,
    *,
    now: datetime,
    run_at: datetime | None = None,
    interval_minutes: int | None = None,
    daily_time: time | None = None,
    timezone_name: str = "America/New_York",
) -> datetime | None:
    """When a new schedule first fires. ``None`` means it never will."""
    now = _as_utc(now)
    if kind == "once":
        if run_at is None:
            raise ValueError("a once schedule needs run_at")
        run_at = _as_utc(run_at)
        return run_at if run_at > now else None
    if kind == "interval":
        minutes = _check_interval(interval_minutes)
        return now + timedelta(minutes=minutes)
    if kind == "daily":
        if daily_time is None:
            raise ValueError("a daily schedule needs daily_time")
        return next_daily(now, daily_time, timezone_name)
    raise ValueError(f"unknown schedule kind {kind!r}")


def next_after_fire(
    kind: str,
    *,
    fired_at: datetime,
    interval_minutes: int | None = None,
    daily_time: time | None = None,
    timezone_name: str = "America/New_York",
) -> datetime | None:
    """The slot after one that just fired at ``fired_at``; ``None`` for a once schedule."""
    fired_at = _as_utc(fired_at)
    if kind == "once":
        return None
    if kind == "interval":
        return fired_at + timedelta(minutes=_check_interval(interval_minutes))
    if kind == "daily":
        if daily_time is None:
            raise ValueError("a daily schedule needs daily_time")
        return next_daily(fired_at, daily_time, timezone_name)
    raise ValueError(f"unknown schedule kind {kind!r}")


def _check_interval(minutes: int | None) -> int:
    if (
        isinstance(minutes, bool)
        or not isinstance(minutes, int)
        or not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES
    ):
        raise ValueError(
            f"interval must be a whole number of minutes from {MIN_INTERVAL_MINUTES} "
            f"to {MAX_INTERVAL_MINUTES}"
        )
    return minutes


def describe(
    kind: str,
    *,
    run_at: datetime | None = None,
    interval_minutes: int | None = None,
    daily_time: time | None = None,
    timezone_name: str = "America/New_York",
) -> str:
    """A short human label for a schedule."""
    if kind == "once":
        return f"once at {run_at.astimezone(UTC):%Y-%m-%d %H:%M} UTC" if run_at else "once"
    if kind == "interval":
        minutes = interval_minutes or 0
        if minutes % 1440 == 0:
            return f"every {minutes // 1440} day(s)"
        if minutes % 60 == 0:
            return f"every {minutes // 60} hour(s)"
        return f"every {minutes} minutes"
    if kind == "daily":
        return f"daily at {daily_time:%H:%M} {timezone_name}" if daily_time else "daily"
    return kind
