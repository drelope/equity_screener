"""Schedule arithmetic, auth, and the safe query builder: pure logic, no database."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.crispdm import explorer
from src.crispdm.ops import auth, schedule

UTC = timezone.utc
NY = ZoneInfo("America/New_York")


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def ny(*args):
    return datetime(*args, tzinfo=NY)


# --- schedules -------------------------------------------------------------------


def test_a_daily_schedule_fires_at_the_local_wall_time():
    nxt = schedule.next_daily(ny(2026, 10, 6, 13, 0), time(3, 0), "America/New_York")
    assert nxt.astimezone(NY) == ny(2026, 10, 7, 3, 0)


def test_a_daily_schedule_fires_today_if_the_slot_is_still_ahead():
    nxt = schedule.next_daily(ny(2026, 10, 6, 1, 0), time(3, 0), "America/New_York")
    assert nxt.astimezone(NY) == ny(2026, 10, 6, 3, 0)


def test_a_slot_that_has_just_fired_is_not_returned_again():
    """next is strictly after: firing at 03:00:00 must not schedule 03:00:00 again."""
    nxt = schedule.next_daily(ny(2026, 10, 6, 3, 0), time(3, 0), "America/New_York")
    assert nxt.astimezone(NY) == ny(2026, 10, 7, 3, 0)


def test_three_am_stays_three_am_across_the_spring_forward_change():
    # 2026-03-08 is the US spring-forward date (02:00 -> 03:00). The local 03:00 slot on
    # that day is already in EDT, so the UTC instant moves by an hour: 08:00Z before, 07:00Z
    # after. The invariant is the local hour, not a fixed UTC offset.
    before = schedule.next_daily(ny(2026, 3, 7, 2, 0), time(3, 0), "America/New_York")
    after = schedule.next_daily(before, time(3, 0), "America/New_York")
    assert before.astimezone(NY).hour == after.astimezone(NY).hour == 3
    assert (before.hour, after.hour) == (8, 7)  # UTC hour shifts
    assert after - before == timedelta(hours=23)


def test_three_am_stays_three_am_across_the_fall_back_change():
    # 2026-11-01 is the US fall-back date. The 03:00 slot on 10-31 is EDT (07:00Z) and on
    # 11-01 is EST (08:00Z); the day between them is 25 hours long.
    before = schedule.next_daily(ny(2026, 10, 30, 4, 0), time(3, 0), "America/New_York")
    after = schedule.next_daily(before, time(3, 0), "America/New_York")
    assert before.astimezone(NY).hour == after.astimezone(NY).hour == 3
    assert (before.hour, after.hour) == (7, 8)
    assert after - before == timedelta(hours=25)


def test_a_time_inside_the_spring_forward_gap_still_fires_once_that_day():
    # 02:30 does not exist on 2026-03-08 in New York.
    nxt = schedule.next_daily(ny(2026, 3, 8, 0, 0), time(2, 30), "America/New_York")
    assert nxt.astimezone(NY).date().isoformat() == "2026-03-08"
    following = schedule.next_daily(nxt, time(2, 30), "America/New_York")
    assert (following - nxt) > timedelta(hours=20)


def test_an_ambiguous_fall_back_time_fires_once_not_twice():
    # 01:30 happens twice on 2026-11-01; the next slot after the first is the next day.
    first = schedule.next_daily(ny(2026, 11, 1, 0, 0), time(1, 30), "America/New_York")
    second = schedule.next_daily(first, time(1, 30), "America/New_York")
    assert (second - first) > timedelta(hours=20)


def test_the_zone_is_honoured():
    # 09:00 in Tokyo (UTC+9, no DST) is 00:00 UTC, and the slot at 00:00 UTC is not after
    # "now" when now is exactly 00:00 UTC, so the next one is the following day.
    nxt = schedule.next_daily(utc(2026, 10, 6, 0, 0), time(9, 0), "Asia/Tokyo")
    assert nxt == utc(2026, 10, 7, 0, 0)
    assert nxt.astimezone(ZoneInfo("Asia/Tokyo")).hour == 9


@pytest.mark.parametrize("name", ["Mars/Base", "", "not a zone", "../../etc/passwd", None])
def test_an_unknown_time_zone_is_refused(name):
    with pytest.raises(ValueError, match="time zone"):
        schedule.check_timezone(name)


def test_an_interval_schedule_counts_from_when_it_last_fired():
    now = utc(2026, 10, 6, 12, 0)
    assert schedule.first_run("interval", now=now, interval_minutes=90) == now + timedelta(
        minutes=90
    )
    assert schedule.next_after_fire(
        "interval", fired_at=now, interval_minutes=90
    ) == now + timedelta(minutes=90)


@pytest.mark.parametrize("minutes", [0, 4, 10081, -5, 1.5, "30", True, None])
def test_an_interval_outside_five_minutes_to_a_week_is_refused(minutes):
    with pytest.raises(ValueError, match="interval"):
        schedule.first_run("interval", now=utc(2026, 1, 1), interval_minutes=minutes)


def test_a_once_schedule_in_the_past_never_fires_and_a_fired_one_has_no_next():
    now = utc(2026, 10, 6, 12, 0)
    assert schedule.first_run("once", now=now, run_at=now - timedelta(minutes=1)) is None
    assert schedule.first_run("once", now=now, run_at=now + timedelta(hours=1)) == now + timedelta(
        hours=1
    )
    assert schedule.next_after_fire("once", fired_at=now) is None


def test_a_missed_daily_schedule_continues_from_now_without_replaying():
    """The worker was down for three days; it fires once and resumes, not three times."""
    woke = ny(2026, 10, 9, 8, 0)
    nxt = schedule.next_after_fire("daily", fired_at=woke, daily_time=time(3, 0))
    assert nxt.astimezone(NY) == ny(2026, 10, 10, 3, 0)


def test_naive_datetimes_are_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        schedule.first_run("interval", now=datetime(2026, 1, 1), interval_minutes=30)


def test_unknown_kinds_are_refused():
    with pytest.raises(ValueError, match="unknown schedule kind"):
        schedule.first_run("cron", now=utc(2026, 1, 1))


def test_descriptions_read_naturally():
    assert schedule.describe("interval", interval_minutes=120) == "every 2 hour(s)"
    assert schedule.describe("interval", interval_minutes=45) == "every 45 minutes"
    assert schedule.describe("interval", interval_minutes=2880) == "every 2 day(s)"
    assert "03:00" in schedule.describe("daily", daily_time=time(3, 0))


# --- auth ------------------------------------------------------------------------


def test_no_token_means_controls_are_off():
    assert auth.configured_token(None) is None
    assert auth.configured_token("") is None
    assert auth.check_token("anything-at-all", None) is False


def test_a_short_token_is_treated_as_not_configured():
    assert auth.configured_token("short") is None
    assert auth.check_token("short", "short") is False
    assert auth.configured_token("a" * auth.MIN_TOKEN_LENGTH) is not None


def test_the_right_token_passes_and_a_wrong_one_does_not():
    token = "correct-horse-battery"
    assert auth.check_token(token, token) is True
    assert auth.check_token("wrong-horse-battery", token) is False
    assert auth.check_token("", token) is False
    assert auth.check_token(None, token) is False


def test_a_non_ascii_attempt_is_a_failed_login_not_an_exception():
    assert auth.check_token("pässwörd-länger-als-12", "correct-horse-battery") is False


def test_five_failures_lock_attempts_out_and_a_success_resets():
    throttle = auth.Throttle()
    for _ in range(auth.MAX_FAILURES - 1):
        throttle.record(False, now=100.0)
    assert throttle.remaining(now=100.0) == 0
    throttle.record(False, now=100.0)
    assert throttle.remaining(now=100.0) == auth.LOCKOUT_SECONDS
    assert throttle.remaining(now=100.0 + auth.LOCKOUT_SECONDS) == 0
    throttle.record(True, now=200.0)
    assert throttle.failures == 0


def test_operator_labels_are_bounded_and_printable():
    assert auth.clean_operator(None) == "operator"
    assert auth.clean_operator("  ") == "operator"
    assert auth.clean_operator("a\x00b\nc") == "abc"
    assert len(auth.clean_operator("x" * 500)) == 60


# --- explorer query builder ------------------------------------------------------

COLUMNS = {
    "ticker": "character varying",
    "dividend": "boolean",
    "close": "numeric",
    "as_of_date": "date",
    "created_at": "timestamp with time zone",
    "payload": "jsonb",
}
REL = "reference.securities"


def test_a_plain_browse_selects_quoted_columns_with_a_capped_limit():
    sql, params = explorer.build_query(REL, COLUMNS, select=["ticker", "close"], limit=10**9)
    assert (
        sql == f'SELECT "ticker", "close" FROM "reference"."securities" LIMIT {explorer.MAX_ROWS}'
    )
    assert params == {}


def test_filters_use_bound_parameters_never_inline_values():
    sql, params = explorer.build_query(
        REL,
        COLUMNS,
        filters=[
            {"column": "ticker", "op": "=", "value": "KO'; DROP TABLE x;--"},
            {"column": "close", "op": ">=", "value": "1,234.5"},
        ],
    )
    assert "DROP" not in sql and "KO" not in sql
    assert params == {"v0": "KO'; DROP TABLE x;--", "v1": 1234.5}
    assert '"ticker" = :v0' in sql and '"close" >= :v1' in sql


def test_a_relation_outside_the_allowlist_is_refused():
    for relation in (
        "pg_catalog.pg_shadow",
        "reference.securities; DROP TABLE x",
        "public.schema_migrations",
    ):
        with pytest.raises(ValueError, match="not an explorable dataset"):
            explorer.build_query(relation, COLUMNS)


@pytest.mark.parametrize(
    "bad",
    ['ticker"; DROP TABLE x;--', "nonexistent", "TICKER", "ticker, close", ""],
)
def test_a_column_that_is_not_in_the_reflected_set_is_refused_everywhere(bad):
    with pytest.raises(ValueError, match="unknown"):
        explorer.build_query(REL, COLUMNS, select=[bad])
    with pytest.raises(ValueError, match="unknown"):
        explorer.build_query(REL, COLUMNS, filters=[{"column": bad, "op": "=", "value": "1"}])
    with pytest.raises(ValueError, match="unknown"):
        explorer.build_query(REL, COLUMNS, order_by=bad)


@pytest.mark.parametrize("op", ["LIKE", "= 1 OR 1=1", "between", "", None, "in"])
def test_an_operator_outside_the_map_is_refused(op):
    with pytest.raises(ValueError, match="operator"):
        explorer.build_query(REL, COLUMNS, filters=[{"column": "ticker", "op": op, "value": "x"}])


def test_an_operator_must_suit_the_column_type():
    with pytest.raises(ValueError, match="cannot be used"):
        explorer.build_query(
            REL, COLUMNS, filters=[{"column": "close", "op": "contains", "value": "1"}]
        )
    with pytest.raises(ValueError, match="cannot be used"):
        explorer.build_query(
            REL, COLUMNS, filters=[{"column": "payload", "op": "=", "value": "{}"}]
        )


def test_values_are_coerced_to_the_column_type_before_binding():
    for value in ("abc", "nan", "inf", "1e999"):
        with pytest.raises(ValueError):
            explorer.build_query(
                REL, COLUMNS, filters=[{"column": "close", "op": ">", "value": value}]
            )
    with pytest.raises(ValueError, match="date"):
        explorer.build_query(
            REL, COLUMNS, filters=[{"column": "as_of_date", "op": ">", "value": "yesterday"}]
        )
    with pytest.raises(ValueError, match="true/false"):
        explorer.build_query(
            REL, COLUMNS, filters=[{"column": "dividend", "op": "=", "value": "maybe"}]
        )
    _sql, params = explorer.build_query(
        REL, COLUMNS, filters=[{"column": "dividend", "op": "=", "value": "Yes"}]
    )
    assert params == {"v0": True}


def test_contains_escapes_like_wildcards():
    _sql, params = explorer.build_query(
        REL, COLUMNS, filters=[{"column": "ticker", "op": "contains", "value": "50%_off\\"}]
    )
    assert params["v0"] == "%50\\%\\_off\\\\%"


def test_empty_and_not_empty_take_no_value_and_a_blank_value_is_refused():
    sql, params = explorer.build_query(
        REL,
        COLUMNS,
        filters=[{"column": "ticker", "op": "is empty"}, {"column": "close", "op": "is not empty"}],
    )
    assert '"ticker" IS NULL' in sql and '"close" IS NOT NULL' in sql and params == {}
    with pytest.raises(ValueError, match="needs a value"):
        explorer.build_query(REL, COLUMNS, filters=[{"column": "ticker", "op": "=", "value": "  "}])


def test_sorting_is_validated_and_directional():
    sql, _ = explorer.build_query(REL, COLUMNS, order_by="close", descending=True)
    assert 'ORDER BY "close" DESC NULLS LAST' in sql


def test_the_number_of_filters_is_capped():
    flt = {"column": "close", "op": ">", "value": "1"}
    with pytest.raises(ValueError, match="at most"):
        explorer.build_query(REL, COLUMNS, filters=[flt] * (explorer.MAX_FILTERS + 1))


def test_limit_must_be_an_integer():
    for bad in ("10", 1.5, True):
        with pytest.raises(ValueError, match="whole number"):
            explorer.build_query(REL, COLUMNS, limit=bad)


def test_every_dataset_relation_is_schema_qualified_and_lowercase():
    for ds in explorer.DATASETS.values():
        schema, _, table = ds.relation.partition(".")
        assert schema and table and ds.relation == ds.relation.lower()
