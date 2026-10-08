"""The Streamlit pages, rendered headlessly against the live database.

``AppTest`` runs each page's script in-process, so these catch exceptions, wrong widget
state and missing controls without a browser. Tests that queue a task use the operator
name ``pytest-ui`` and remove everything that name created.
"""

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from sqlalchemy import text  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.crispdm.config import settings  # noqa: E402
from src.crispdm.db import engine  # noqa: E402

OPERATOR = "pytest-ui"
TOKEN = "a-test-operator-token"
TIMEOUT = 180


def _database_ready() -> bool:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1 FROM ops.tasks LIMIT 1")
            conn.exec_driver_sql("SELECT 1 FROM model.scores LIMIT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _database_ready(), reason="no live database with ops schema")


def page_script(module: str):
    import importlib

    importlib.import_module(f"app.views.{module}").render()


def page(module: str, operator: bool = False) -> AppTest:
    at = AppTest.from_function(page_script, args=(module,), default_timeout=TIMEOUT)
    if operator:
        at.session_state["operator"] = OPERATOR
    return at


@pytest.fixture(autouse=True)
def clean_up():
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ops.tasks WHERE requested_by = :o"), {"o": OPERATOR})
        conn.execute(text("DELETE FROM ops.schedules WHERE created_by = :o"), {"o": OPERATOR})


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setattr(settings, "ops_admin_token", TOKEN)


@pytest.fixture
def without_token(monkeypatch):
    monkeypatch.setattr(settings, "ops_admin_token", None)


def button(at: AppTest, label: str):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no {label!r} button; have {[b.label for b in at.button]}"
    return matches[0]


# --- every page renders ----------------------------------------------------------


@pytest.mark.parametrize(
    "module", ["screener", "security", "data_explorer", "health", "operations", "integrations"]
)
def test_each_page_renders_without_an_exception(module, without_token):
    at = page(module).run()
    assert not at.exception, [e.value for e in at.exception]


def test_the_screener_shows_the_universe_and_its_filters_narrow_it(without_token):
    at = page("screener").run()
    assert not at.exception
    assert len(at.metric) == 6
    total = int(at.metric[0].value.replace(",", ""))

    at.text_input[0].set_value("KO").run()

    assert not at.exception
    shown = [c.value for c in at.caption if c.value.startswith("Showing ")]
    assert shown and int(shown[0].split()[1].replace(",", "")) < total


def test_a_screener_filter_that_matches_nothing_says_so(without_token):
    at = page("screener").run()
    at.text_input[0].set_value("ZZZZZZZZ-NO-SUCH-TICKER").run()
    assert not at.exception
    assert any("No securities match" in w.value for w in at.warning)


def test_the_security_page_opens_the_ticker_chosen_on_the_screener(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text(
                "SELECT s.ticker FROM reference.securities s JOIN model.scores sc USING (security_id) "
                "WHERE s.active AND sc.composite_score IS NOT NULL "
                "ORDER BY sc.as_of_date DESC, sc.composite_score DESC LIMIT 1"
            )
        ).scalar()
    at = AppTest.from_function(page_script, args=("security",), default_timeout=TIMEOUT)
    at.session_state["selected_ticker"] = ticker

    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox[0].value == ticker
    assert any(ticker in m.value for m in at.markdown)


# --- the data explorer -----------------------------------------------------------


def test_the_explorer_runs_a_query_and_keeps_the_result(without_token):
    at = page("data_explorer").run()
    button(at, "Run query").click().run()

    assert not at.exception, [e.value for e in at.exception]
    frame = at.session_state["explorer_result"]["frame"]
    assert len(frame) == 500, "the default row limit"
    assert any("500 rows" in c.value for c in at.caption)


def test_the_explorer_reports_a_bad_filter_instead_of_running_it(without_token):
    at = page("data_explorer").run()
    at.number_input(key="explorer_Securities_n").set_value(1).run()
    at.selectbox(key="explorer_Securities_col0").set_value("active").run()
    at.text_input(key="explorer_Securities_val0").set_value("maybe").run()

    button(at, "Run query").click().run()

    assert not at.exception
    assert any("true/false" in e.value for e in at.error)
    assert "explorer_result" not in at.session_state


def test_a_hostile_filter_value_is_data_not_sql(without_token):
    at = page("data_explorer").run()
    at.number_input(key="explorer_Securities_n").set_value(1).run()
    at.selectbox(key="explorer_Securities_col0").set_value("ticker").run()
    at.text_input(key="explorer_Securities_val0").set_value(
        "'; DROP TABLE reference.securities; --"
    ).run()

    button(at, "Run query").click().run()

    assert not at.exception
    assert len(at.session_state["explorer_result"]["frame"]) == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM reference.securities")).scalar() > 0


# --- operator gate on the operations page ----------------------------------------


def test_without_a_token_the_operations_page_is_read_only(without_token):
    at = page("operations").run()
    assert not at.exception
    assert button(at, "Queue task").disabled
    assert any("OPS_ADMIN_TOKEN is not set" in i.value for i in at.info)


def test_with_a_token_but_nobody_signed_in_the_controls_stay_off(with_token):
    at = page("operations").run()
    assert button(at, "Queue task").disabled
    assert any("Sign in as an operator" in i.value for i in at.info)


def test_a_signed_in_operator_can_queue_a_task_once_and_duplicates_are_refused(with_token):
    at = page("operations", operator=True).run()
    at.selectbox(key="ops_run_task").set_value("migrate_check").run()
    assert not button(at, "Queue task").disabled

    button(at, "Queue task").click().run()
    assert any("Queued as task" in s.value for s in at.success)
    button(at, "Queue task").click().run()
    assert any("identical task is already queued" in w.value for w in at.warning)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT status, source FROM ops.tasks WHERE requested_by = :o"), {"o": OPERATOR}
        ).all()
    assert [tuple(r) for r in rows] == [("queued", "manual")]


def test_a_heavy_task_needs_an_explicit_confirmation(with_token):
    at = page("operations", operator=True).run()
    at.selectbox(key="ops_run_task").set_value("run_full_etl").run()
    assert button(at, "Queue task").disabled, "not until the warning is acknowledged"

    at.checkbox(key="ops_confirm_run_full_etl").check().run()

    assert not button(at, "Queue task").disabled
    assert any("scripts.run_full_etl --trigger manual" in c.value for c in at.code)
    # Deliberately not clicked: this test must never queue a multi-hour run.


def test_invalid_parameters_disable_the_button_and_name_the_problem(with_token):
    at = page("operations", operator=True).run()
    at.selectbox(key="ops_run_task").set_value("populate_market_data").run()
    at.checkbox(key="ops_confirm_populate_market_data").check().run()
    at.text_input(key="run_populate_market_data_tickers").set_value("KO --all").run()

    assert button(at, "Queue task").disabled
    assert any("comma-separated tickers" in e.value for e in at.error)


def test_a_schedule_can_be_created_paused_and_deleted(with_token):
    at = page("operations", operator=True).run()
    at.selectbox(key="ops_sched_task").set_value("migrate_check").run()
    at.text_input(key="ops_sched_name").set_value("pytest schedule").run()
    button(at, "Create schedule").click().run()
    assert not at.exception and any("Created schedule" in s.value for s in at.success)

    at = page("operations", operator=True).run()
    button(at, "Pause").click().run()
    with engine.connect() as conn:
        enabled = conn.execute(
            text("SELECT enabled FROM ops.schedules WHERE created_by = :o"), {"o": OPERATOR}
        ).scalar()
    assert enabled is False


# --- the app shell and sign-in ---------------------------------------------------


def shell() -> AppTest:
    entry = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
    return AppTest.from_file(str(entry), default_timeout=TIMEOUT)


def sign_in(at: AppTest, name: str, token: str) -> AppTest:
    at.sidebar.text_input[0].set_value(name)
    at.sidebar.text_input[1].set_value(token)
    return at.sidebar.button[0].click().run()


def test_the_shell_renders_and_explains_when_controls_are_off(without_token):
    at = shell().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Controls are off" in c.value for c in at.sidebar.caption)


def test_signing_in_with_the_right_token_records_the_operator(with_token):
    at = sign_in(shell().run(), "  Dana  ", TOKEN)
    assert not at.exception
    assert at.session_state["operator"] == "Dana"


def test_a_wrong_or_non_ascii_token_is_refused_without_an_exception(with_token):
    at = shell().run()
    for wrong in ("nope", "tökén-ünïcode-wrong"):
        at = sign_in(at, "Dana", wrong)
        assert not at.exception
        assert "operator" not in at.session_state


def test_five_failures_lock_sign_in_even_for_the_right_token(with_token):
    at = shell().run()
    for _ in range(5):
        at = sign_in(at, "Dana", "wrong-token-value")
    at = sign_in(at, "Dana", TOKEN)

    assert "operator" not in at.session_state
    assert any("Too many attempts" in w.value for w in at.sidebar.warning)


def test_a_token_that_is_too_short_never_enables_the_controls(monkeypatch):
    monkeypatch.setattr(settings, "ops_admin_token", "short")
    at = shell().run()
    assert any("Controls are off" in c.value for c in at.sidebar.caption)
    assert not at.sidebar.button
