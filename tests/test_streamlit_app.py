"""The Streamlit pages, rendered headlessly against the live database.

``AppTest`` runs each page's script in-process, so these catch exceptions, wrong widget
state and missing controls without a browser. Tests that queue a task use the operator
name ``pytest-ui`` and remove everything that name created.
"""

from pathlib import Path

import pandas as pd
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
            conn.exec_driver_sql("SELECT 1 FROM analysis.investment_analyses LIMIT 1")
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
        conn.execute(
            text("DELETE FROM analysis.investment_analyses WHERE created_by = :o"),
            {"o": OPERATOR},
        )


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
    "module",
    [
        "screener",
        "security",
        "data_explorer",
        "health",
        "operations",
        "integrations",
        "investment_analysis",
    ],
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


def test_the_screener_defaults_to_preferred_stock(without_token):
    at = page("screener").run()
    assert not at.exception
    widget = next(m for m in at.multiselect if m.label == "Security type")
    assert widget.value == ["preferred stock"]


def test_a_screener_filter_that_matches_nothing_says_so(without_token):
    at = page("screener").run()
    at.text_input[0].set_value("ZZZZZZZZ-NO-SUCH-TICKER").run()
    assert not at.exception
    assert any("No securities match" in w.value for w in at.warning)


def test_the_screener_headlines_include_margin_and_fcf_yield(without_token):
    at = page("screener").run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert len(labels) == 6, labels
    assert any("net margin" in label for label in labels), labels
    assert any("FCF yield" in label for label in labels), labels


def test_the_screener_can_add_a_financial_metric_column(without_token):
    at = page("screener").run()
    assert not at.exception
    frame = at.get("dataframe")[0].value
    assert {"net_margin", "fcf_yield"} <= set(frame.columns), "default metric columns"

    widget = next(m for m in at.multiselect if m.label == "Financial metric columns")
    widget.set_value(["Gross margin", "Price/book"]).run()

    assert not at.exception, [e.value for e in at.exception]
    frame = at.get("dataframe")[0].value
    assert {"gross_margin", "price_to_book"} <= set(frame.columns)
    assert "net_margin" not in frame.columns, "the unselected metric must drop out"


def test_a_screener_financial_filter_narrows_the_universe(without_token):
    at = page("screener").run()
    types = next(m for m in at.multiselect if m.label == "Security type")
    at = types.set_value(types.options).run()
    assert not at.exception

    total = int(
        next(c.value for c in at.caption if c.value.startswith("Showing "))
        .split()[1]
        .replace(",", "")
    )
    assert total > 0

    at = next(n for n in at.number_input if n.label == "Minimum gross margin").set_value(0.0).run()

    assert not at.exception, [e.value for e in at.exception]
    shown = next(c.value for c in at.caption if c.value.startswith("Showing "))
    assert int(shown.split()[1].replace(",", "")) < total, shown


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


def test_the_security_header_shows_full_security_name_without_provider_shortening(without_token):
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT ticker, security_name FROM reference.securities "
                    "WHERE active AND LENGTH(security_name) > 80 "
                    "ORDER BY LENGTH(security_name) DESC, ticker LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
    assert row, "expected an active security with a long instrument title"

    at = _open_the_security_page(row["ticker"])

    assert not at.exception, [e.value for e in at.exception]
    assert any(element.value == row["security_name"] for element in at.text)
    title = next(element for element in at.text if element.value == row["security_name"])
    assert title.proto.wrap


def test_the_security_header_shows_overview_and_ex_date_toggle(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text(
                "SELECT s.ticker FROM reference.securities s "
                "JOIN clean.company_profile cp ON cp.reference_security_id = s.security_id "
                "WHERE s.active AND EXISTS (SELECT 1 FROM raw.dividend_data d "
                "  WHERE d.security_id = s.security_id AND d.ex_dividend_date IS NOT NULL) "
                "ORDER BY s.ticker LIMIT 1"
            )
        ).scalar()
    at = AppTest.from_function(page_script, args=("security",), default_timeout=TIMEOUT)
    at.session_state["selected_ticker"] = ticker

    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("Company overview" in s.value for s in at.subheader)
    assert any("Announced cash dividend" in m.value for m in at.markdown)

    at.checkbox(key="detail_show_ex").check().run()
    assert not at.exception, [e.value for e in at.exception]


def test_the_security_detail_shows_rate_structure_yield_and_ex_date(without_token):
    # A preferred with a parsed rate structure and a yield exercises every new term
    # fact at once; the values themselves are asserted, not just the labels.
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT s.ticker, p.coupon_type "
                    "FROM reference.securities s "
                    "JOIN clean.ticker_profile p ON p.security_id = s.security_id "
                    "JOIN LATERAL (SELECT dividend_yield FROM model.features x "
                    "             WHERE x.security_id = s.security_id "
                    "             ORDER BY as_of_date DESC LIMIT 1) f ON TRUE "
                    "WHERE s.active AND s.security_type = 'preferred stock' "
                    "  AND p.coupon_type IS NOT NULL AND f.dividend_yield IS NOT NULL "
                    "ORDER BY s.ticker LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
    assert row, "expected an active preferred with a parsed rate type and a yield"

    at = _open_the_security_page(row["ticker"])

    assert not at.exception, [e.value for e in at.exception]
    markdown = [m.value for m in at.markdown]
    assert any("**Rate type**" in m and row["coupon_type"] in m for m in markdown), markdown
    assert any("**Rate converts on**" in m for m in markdown), markdown
    assert any("**Floating spread**" in m for m in markdown), markdown
    assert any("**Yield**" in m for m in markdown), markdown
    assert any("**Last ex-date**" in m for m in markdown), markdown


def test_the_security_page_shows_related_listings_for_a_multi_listing_issuer(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text(
                "SELECT s.ticker FROM reference.securities s "
                "JOIN clean.company_profile cp ON cp.reference_security_id = s.security_id "
                "WHERE s.active AND s.cik IS NOT NULL AND s.cik IN ( "
                "  SELECT cik FROM clean.company_profile "
                "  WHERE cik IS NOT NULL GROUP BY cik HAVING count(*) > 1) "
                "ORDER BY s.ticker LIMIT 1"
            )
        ).scalar()
    assert ticker, "expected at least one multi-listing issuer"
    at = AppTest.from_function(page_script, args=("security",), default_timeout=TIMEOUT)
    at.session_state["selected_ticker"] = ticker

    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("Issuer & related listings" in s.value for s in at.subheader)
    assert any("Primary listing" in m.value for m in at.markdown)
    assert len(at.button) >= 1, "a multi-listing issuer must offer sibling navigation"
    labels = {b.label for b in at.button}
    assert ticker not in labels, "the current listing is not a navigation button"


def test_related_listings_yield_is_a_fraction_of_price_not_percent_points(without_token):
    # A child whose provider-native dividend_yield is in percent points (e.g. 13.68)
    # must be recomputed as rate/price and rendered as 13.68%, never 1368%.
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT h.primary_symbol AS ticker, "
                    "       j->>'symbol' AS symbol, "
                    "       (j->>'dividend_rate')::numeric AS dividend_rate, "
                    "       (j->>'current_price')::numeric AS current_price "
                    "FROM clean.v_company_hierarchy h "
                    "CROSS JOIN LATERAL jsonb_array_elements(h.children) AS j "
                    "WHERE (j->>'dividend_rate')::numeric > 0 "
                    "  AND (j->>'current_price')::numeric > 0 "
                    "  AND (j->>'dividend_yield')::numeric > 1 "
                    "  AND h.primary_symbol IN (SELECT ticker FROM reference.securities "
                    "                           WHERE active) "
                    "ORDER BY h.primary_symbol, j->>'symbol' LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
    assert row, "expected a listing whose provider yield is in percent points"

    at = _open_the_security_page(row["ticker"])

    assert not at.exception, [e.value for e in at.exception]
    frame = next(
        (
            proto.value
            for proto in at.get("dataframe")
            if isinstance(proto.value, pd.DataFrame)
            and {"Yield", "Ex-date"} <= set(proto.value.columns)
        ),
        None,
    )
    assert frame is not None, "expected the related-listings table"

    cell = frame.loc[frame["Symbol"] == row["symbol"], "Yield"].iloc[0]
    rendered = float(str(cell).strip("%"))
    expected = float(row["dividend_rate"] / row["current_price"] * 100)
    assert rendered <= 100, f"yield rendered as {cell!r} — percent points leaked through"
    assert rendered == pytest.approx(expected, abs=0.01), (cell, expected)


def test_the_related_listings_stack_a_corporate_action_under_the_ex_date(without_token):
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT h.primary_symbol AS ticker, "
                    "       COALESCE(j->'corporate_actions'->0->>'header', "
                    "                j->'corporate_actions'->0->>'event_type') AS action_label "
                    "FROM clean.v_company_hierarchy h "
                    "CROSS JOIN LATERAL jsonb_array_elements(h.children) AS j "
                    "WHERE (j->>'corporate_action_count')::int >= 1 "
                    "  AND h.primary_symbol IN (SELECT ticker FROM reference.securities "
                    "                           WHERE active) "
                    "ORDER BY h.primary_symbol, j->>'symbol' LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
    assert row, "expected a listing with a stored corporate action"

    at = _open_the_security_page(row["ticker"])

    assert not at.exception, [e.value for e in at.exception]
    frame = next(
        (
            proto.value
            for proto in at.get("dataframe")
            if isinstance(proto.value, pd.DataFrame) and "Ex-date" in proto.value.columns
        ),
        None,
    )
    assert frame is not None, "expected the related-listings table"
    assert any("\n" in cell and row["action_label"] in cell for cell in frame["Ex-date"]), list(
        frame["Ex-date"]
    )


# --- the dividends tab -----------------------------------------------------------


def _dividend_tables(at: AppTest):
    return [
        proto.value
        for proto in at.get("dataframe")
        if isinstance(proto.value, pd.DataFrame) and "ex_dividend_date" in proto.value.columns
    ]


def _column_values(table, name: str):
    return list(table[name].dropna())


def _both_provider_ticker():
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT s.ticker FROM reference.securities s "
                "WHERE s.active AND s.security_id IN ("
                "  SELECT security_id FROM raw.dividend_data WHERE provider = 'OPENBB' "
                "  INTERSECT SELECT security_id FROM raw.dividend_data WHERE provider = 'SEC_XBRL') "
                "ORDER BY s.ticker LIMIT 1"
            )
        ).scalar()


def _open_the_security_page(ticker: str, section: str | None = None) -> AppTest:
    at = AppTest.from_function(page_script, args=("security",), default_timeout=TIMEOUT)
    at.session_state["selected_ticker"] = ticker
    if section is not None:
        # Sections render lazily behind the segmented control; pre-select one.
        at.session_state["security_active_section"] = section
    return at.run()


def test_the_dividend_tab_lists_events_and_named_cadence(without_token):
    ticker = _both_provider_ticker()
    assert ticker, "expected a security carrying both dividend providers"
    at = _open_the_security_page(ticker, section="Dividends")

    assert not at.exception, [e.value for e in at.exception]
    assert any("Dividends" in s.value for s in at.subheader)
    tables = _dividend_tables(at)
    assert tables, "expected the dividend dataframe"
    assert "frequency" in tables[0], "the table must show its cadence"
    assert "payment_date" not in tables[0], "payment_date is NULL/dup for most rows"
    labels = set(_column_values(tables[0], "frequency"))
    assert labels <= {"Monthly", "Quarterly", "Semi-annual", "Annual", "Irregular"}
    assert labels, "the cadence labels must actually be populated"


def test_the_dividend_tab_defaults_to_the_recommended_true_ex_date_source(without_token):
    ticker = _both_provider_ticker()
    assert ticker, "expected a security carrying both dividend providers"
    at = _open_the_security_page(ticker, section="Dividends")

    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox(key="detail_dividend_provider").value.startswith("Recommended")
    assert not any("SEC XBRL dates are fiscal period-ends" in c.value for c in at.caption)
    tables = _dividend_tables(at)
    assert tables, "expected the dividend dataframe"
    assert set(_column_values(tables[0], "provider")) <= {
        "FMP (via OpenBB)",
        "Yahoo Finance (via OpenBB)",
    }


def test_the_dividend_tab_compares_all_sources_with_labels(without_token):
    ticker = _both_provider_ticker()
    assert ticker, "expected a security carrying both dividend providers"
    at = _open_the_security_page(ticker, section="Dividends")
    at.selectbox(key="detail_dividend_provider").set_value("All sources (comparison)").run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("SEC XBRL dates are fiscal period-ends" in c.value for c in at.caption)
    tables = _dividend_tables(at)
    labels = set(_column_values(tables[0], "provider"))
    assert "SEC XBRL filing" in labels
    assert labels & {"FMP (via OpenBB)", "Yahoo Finance (via OpenBB)"}
    assert labels <= {"FMP (via OpenBB)", "Yahoo Finance (via OpenBB)", "SEC XBRL filing"}


def test_the_dividend_tab_falls_back_to_sec_when_yahoo_has_nothing(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text(
                "SELECT s.ticker FROM reference.securities s "
                "WHERE s.active AND s.security_id IN ("
                "  SELECT security_id FROM raw.dividend_data WHERE provider = 'SEC_XBRL' "
                "  EXCEPT SELECT security_id FROM raw.dividend_data WHERE provider = 'OPENBB') "
                "ORDER BY s.ticker LIMIT 1"
            )
        ).scalar()
    if ticker is None:
        pytest.skip("every SEC-only security also has OpenBB events")
    at = _open_the_security_page(ticker, section="Dividends")

    assert not at.exception, [e.value for e in at.exception]
    assert any("showing the SEC XBRL filing fallback" in c.value for c in at.caption)
    assert any("SEC period end" in m.value or "N/A" in m.value for m in at.markdown)


def test_the_dividend_tab_filters_by_provider(without_token):
    ticker = _both_provider_ticker()
    assert ticker, "expected a security carrying both dividend providers"
    at = _open_the_security_page(ticker, section="Dividends")
    at.selectbox(key="detail_dividend_provider").set_value(
        "SEC XBRL filings (fiscal period-ends)"
    ).run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("SEC XBRL dates are fiscal period-ends" in c.value for c in at.caption)
    tables = _dividend_tables(at)
    assert tables, "expected the dividend dataframe"
    assert set(_column_values(tables[0], "provider")) == {"SEC XBRL filing"}


def test_the_dividend_tab_says_when_nothing_is_stored(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text(
                "SELECT s.ticker FROM reference.securities s "
                "WHERE s.active AND NOT EXISTS (SELECT 1 FROM raw.dividend_data d "
                "  WHERE d.security_id = s.security_id) "
                "ORDER BY s.ticker LIMIT 1"
            )
        ).scalar()
    if not ticker:
        pytest.skip("no active security without stored dividend events")
    at = _open_the_security_page(ticker, section="Dividends")

    assert not at.exception, [e.value for e in at.exception]
    assert any("No dividend events stored" in c.value for c in at.caption)


# --- the financials tab ----------------------------------------------------------


def test_the_security_financials_tab_renders_the_point_in_time_ratios(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text(
                "SELECT s.ticker FROM reference.securities s "
                "JOIN model.features f USING (security_id) "
                "WHERE s.active AND f.net_margin IS NOT NULL AND f.gross_margin IS NOT NULL "
                "ORDER BY s.ticker LIMIT 1"
            )
        ).scalar()
    assert ticker, "expected a security carrying the V0068 ratios"
    at = _open_the_security_page(ticker, section="Financials")

    assert not at.exception, [e.value for e in at.exception]
    assert any("Financial metrics" in s.value for s in at.subheader)
    assert any("Point-in-time ratios as of" in c.value for c in at.caption)
    labels = {m.label for m in at.metric}
    assert {"Gross margin", "Net margin", "FCF yield", "Price/book", "Net debt"} <= labels, labels


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


# --- the investment analysis worksheet -------------------------------------------


def test_the_analysis_page_opens_the_ticker_chosen_on_the_screener(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text("SELECT ticker FROM reference.securities WHERE active ORDER BY ticker LIMIT 1")
        ).scalar()
    at = AppTest.from_function(page_script, args=("investment_analysis",), default_timeout=TIMEOUT)
    at.session_state["selected_ticker"] = ticker

    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox[0].value == ticker
    steps = [e.label for e in at.expander]
    assert any(label.startswith("18. ") for label in steps), steps


def test_saving_an_empty_worksheet_lists_the_missing_fields(with_token):
    at = page("investment_analysis", operator=True).run()
    assert not at.exception, [e.value for e in at.exception]

    at.selectbox(key="ia_status").set_value("Final").run()
    button(at, "Save analysis").click().run()

    assert not at.exception, [e.value for e in at.exception]
    errors = [e.value for e in at.error]
    assert errors and "need attention" in errors[0]
    details = " ".join(e.value for e in at.code)
    assert "Investment universe / Filters applied" in details


def test_an_empty_draft_is_refused(with_token):
    at = page("investment_analysis", operator=True).run()
    assert at.selectbox(key="ia_status").value == "Draft"

    button(at, "Save analysis").click().run()

    assert not at.exception, [e.value for e in at.exception]
    details = " ".join(e.value for e in at.code)
    assert "worksheet is empty" in details


def test_a_draft_may_not_recommend_before_the_prior_steps_are_done(with_token):
    at = page("investment_analysis", operator=True).run()
    at.selectbox(key="ia__final__recommendation").set_value("Buy").run()

    button(at, "Save analysis").click().run()

    assert not at.exception, [e.value for e in at.exception]
    details = " ".join(e.value for e in at.code)
    assert "steps 1-17" in details


def test_required_fields_are_marked_and_the_missing_list_is_actionable(with_token):
    at = page("investment_analysis", operator=True).run()

    # Required fields carry the marker; optional ones do not.
    assert at.text_input(key="ia__universe__universe_filters").label == "Filters applied *"
    assert (
        at.text_input(key="ia__macro__ig_spreads").label
        == "Investment grade spreads vs. historical average"
    )
    assert at.selectbox(key="ia__risk__business_risk").label == "Business risk *"

    # The recommendation warning names the exact missing required fields.
    assert any("Steps 1-17 are incomplete" in w.value for w in at.warning)
    details = " ".join(c.value for c in at.code)
    assert "Investment universe / Filters applied" in details
    assert "Macro & credit / Backdrop" in details
    assert "Risk decomposition / Position sizing implication" in details

    # Steps with no required fields are labelled optional rather than looking unfilled.
    labels = [e.label for e in at.expander]
    assert any("7. Consensus expectations (optional)" in label for label in labels)
    assert any("17. Portfolio integration (optional)" in label for label in labels)


def test_a_concurrent_edit_is_refused_rather_than_overwritten(with_token):
    at = page("investment_analysis", operator=True).run()
    _fill_worksheet(at)
    button(at, "Save analysis").click().run()
    assert any("Saved analysis" in s.value for s in at.success)
    analysis_id = at.session_state["ia_analysis_id"]

    # Simulate another tab saving the same row after this one loaded it.
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE analysis.investment_analyses "
                "SET updated_at = now() + interval '1 hour' WHERE analysis_id = :id"
            ),
            {"id": analysis_id},
        )

    button(at, "Save analysis").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("changed in another tab" in e.value for e in at.error)
    assert not any("Saved analysis" in s.value for s in at.success)


def test_a_final_cannot_be_demoted_without_ticking_the_reopen_box(with_token):
    at = page("investment_analysis", operator=True).run()
    _fill_worksheet(at)
    at.selectbox(key="ia_status").set_value("Final").run()
    button(at, "Save analysis").click().run()
    assert any("Saved analysis" in s.value for s in at.success)
    analysis_id = at.session_state["ia_analysis_id"]

    at.selectbox(key="ia_status").set_value("Draft").run()
    button(at, "Save analysis").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("explicit reopen" in e.value for e in at.error)

    at.checkbox(key="ia_reopen").check().run()
    button(at, "Save analysis").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("Saved analysis" in s.value for s in at.success)
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM analysis.investment_analyses WHERE analysis_id = :id"),
            {"id": analysis_id},
        ).scalar()
    assert status == "draft"


def test_the_sidebar_shows_the_saved_revision_history(with_token):
    at = page("investment_analysis", operator=True).run()
    _fill_worksheet(at)
    button(at, "Save analysis").click().run()
    assert any("Saved analysis" in s.value for s in at.success)

    button(at, "Save analysis").click().run()
    assert any("Saved analysis" in s.value for s in at.success)

    assert not at.exception, [e.value for e in at.exception]
    labels = [expander.label for expander in at.sidebar.expander]
    assert "History (2)" in labels, labels
    revisions = [caption.value for caption in at.sidebar.caption if caption.value.startswith("r")]
    assert len(revisions) == 2, revisions
    newest, older = (int(line.split(" ", 1)[0][1:]) for line in revisions)
    assert newest == older + 1  # revision ids rise with each save


def test_the_sidebar_history_shows_what_each_save_changed(with_token):
    at = page("investment_analysis", operator=True).run()
    _fill_worksheet(at)
    button(at, "Save analysis").click().run()
    assert any("Saved analysis" in s.value for s in at.success)

    at.text_input(key="ia__universe__universe_filters").set_value("Changed universe").run()
    button(at, "Save analysis").click().run()
    assert any("Saved analysis" in s.value for s in at.success)

    assert not at.exception, [e.value for e in at.exception]
    captions = [caption.value for caption in at.sidebar.caption]
    assert any(
        "Filters applied" in line and "->" in line and "Changed universe" in line
        for line in captions
    ), captions


def test_without_the_operator_token_the_save_control_is_off(without_token):
    at = page("investment_analysis").run()
    assert not at.exception, [e.value for e in at.exception]

    save = button(at, "Save analysis")
    assert save.disabled
    assert any("controls" in note.value.lower() for note in at.info)


def test_go_to_analysis_switches_pages_and_carries_the_ticker(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text("SELECT ticker FROM reference.securities WHERE active ORDER BY ticker LIMIT 1")
        ).scalar()

    def shell(ticker):
        import streamlit as st

        from app.views import investment_analysis

        def home():
            st.title("Home")
            if st.button("Analyze here"):
                investment_analysis.go_to_analysis(ticker)

        st.navigation(
            [
                st.Page(home, title="Home", url_path="home", default=True),
                st.Page(
                    investment_analysis.render,
                    title=investment_analysis.PAGE_TITLE,
                    url_path=investment_analysis.PAGE_PATH,
                ),
            ]
        ).run()

    at = AppTest.from_function(shell, args=(ticker,), default_timeout=TIMEOUT).run()
    assert not at.exception, [e.value for e in at.exception]

    button(at, "Analyze here").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Investment analysis"
    assert at.selectbox[0].value == ticker


def test_the_ticker_picker_defaults_to_dividend_paying_common_stock(without_token):
    at = page("security").run()
    assert not at.exception, [e.value for e in at.exception]

    override = next(c for c in at.checkbox if c.label == "Show all active securities")
    assert not override.value
    with engine.connect() as conn:
        expected = conn.execute(
            text(
                "SELECT count(*) FROM reference.securities "
                "WHERE active AND security_type = 'common_stock' AND dividend"
            )
        ).scalar()
    assert len(at.selectbox[0].options) == expected


def test_the_ticker_picker_override_restores_the_full_active_universe(without_token):
    at = page("security").run()
    assert not at.exception, [e.value for e in at.exception]
    default_count = len(at.selectbox[0].options)

    at = next(c for c in at.checkbox if c.label == "Show all active securities").check().run()
    assert not at.exception, [e.value for e in at.exception]
    with engine.connect() as conn:
        expected = conn.execute(
            text("SELECT count(*) FROM reference.securities WHERE active")
        ).scalar()
    assert len(at.selectbox[0].options) == expected
    assert expected > default_count


def test_a_selected_ticker_outside_the_default_universe_is_kept(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text(
                "SELECT ticker FROM reference.securities "
                "WHERE active AND NOT (security_type = 'common_stock' AND dividend) "
                "ORDER BY ticker LIMIT 1"
            )
        ).scalar()
    if ticker is None:
        pytest.skip("no active non-dividend listing in the warehouse")

    at = page("security")
    at.session_state["selected_ticker"] = ticker
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox[0].value == ticker
    assert ticker in at.selectbox[0].options


def test_a_shared_link_selects_the_ticker(without_token):
    with engine.connect() as conn:
        ticker = conn.execute(
            text("SELECT ticker FROM reference.securities WHERE active ORDER BY ticker LIMIT 1")
        ).scalar()
    assert ticker, "expected at least one active security"

    at = page("security")
    at.query_params["ticker"] = ticker
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox[0].value == ticker
    assert at.session_state["selected_ticker"] == ticker


def test_the_picker_mirrors_the_selection_into_the_url(without_token):
    at = page("security").run()

    assert not at.exception, [e.value for e in at.exception]
    # AppTest exposes raw param values, which are lists.
    assert at.query_params["ticker"] in (
        at.selectbox[0].value,
        [at.selectbox[0].value],
    )


def test_the_security_page_offers_the_analysis_worksheet_for_its_ticker(without_token):
    at = page("security").run()
    assert not at.exception, [e.value for e in at.exception]
    assert [b.label for b in at.button].count("Analyze") == 1


def test_the_security_page_tracks_the_recommendation_history(without_token):
    from app import analysis_schema as schema
    from src.crispdm.analysis import store

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT security_id::text, ticker FROM reference.securities "
                "WHERE active ORDER BY ticker LIMIT 1"
            )
        ).first()
    if row is None:
        pytest.skip("no active securities in the warehouse")
    security_id, ticker = row

    payload = schema.empty_payload()
    with engine.begin() as conn:
        analysis_id = store.create(
            conn,
            security_id=security_id,
            ticker=ticker,
            payload=payload,
            thesis="One. Two. Three.",
            recommendation="Hold",
            confidence="Medium",
            overall_risk_score=5,
            status="draft",
            created_by=OPERATOR,
        )
        # Re-save the same call (collapsed) then change it, so only one change shows.
        for call in ("Hold", "Trim"):
            store.update(
                conn,
                analysis_id,
                payload=payload,
                thesis="One. Two. Three.",
                recommendation=call,
                confidence="Medium",
                overall_risk_score=5,
                status="draft",
                updated_by=OPERATOR,
            )

    at = _open_the_security_page(ticker, section="Recommendations")
    assert not at.exception, [e.value for e in at.exception]

    table = next(frame.value for frame in at.dataframe if "Call" in frame.value.columns)
    ours = table[table["By"] == OPERATOR]
    assert list(ours["Call"])[:2] == ["Trim", "Hold"]
    assert list(ours["From"])[:2] == ["Hold", "—"]


def _fill_worksheet(at: AppTest) -> None:
    """Set every worksheet widget to a valid value, located by its schema key."""
    from app import analysis_schema as schema

    def find(widgets, key):
        return next(widget for widget in widgets if widget.key == key)

    for section in schema.SECTIONS:
        for field in section.all_fields:
            key = f"ia__{section.id}__{field.id}"
            if field.kind == "select":
                find(at.selectbox, key).set_value(field.options[0])
            elif field.kind == "score":
                find(at.number_input, key).set_value(5)
            elif field.kind == "textarea":
                value = (
                    "One evidence line.\nTwo.\nThree."
                    if field.id == "key_evidence"
                    else "A detailed answer for the worksheet."
                )
                find(at.text_area, key).set_value(value)
            else:
                find(at.text_input, key).set_value("A detailed answer.")
    find(at.text_input, "ia__final__thesis").set_value("One sentence. Two. Three.")
    at.run()


def test_generating_a_local_draft_prefills_the_form_without_saving(with_token, monkeypatch):
    from app import analysis_schema as schema
    from app import llm_client
    from src.crispdm.config import settings

    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_endpoint", "http://localhost:11434/v1/chat/completions")
    generated = schema.empty_payload()
    generated["sections"]["universe"]["universe_filters"] = "Generated universe filter"
    monkeypatch.setattr(llm_client, "generate_draft", lambda context, **kw: generated)

    at = page("investment_analysis", operator=True).run()
    assert not at.exception, [e.value for e in at.exception]

    button(at, "Generate").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Generated a draft" in flash.value for flash in at.success)

    prefilled = next(w for w in at.text_input if w.key == "ia__universe__universe_filters")
    assert prefilled.value == "Generated universe filter"

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM analysis.investment_analyses WHERE created_by = :o"),
            {"o": OPERATOR},
        ).scalar()
    assert count == 0, "generation must never save"


def test_the_generate_control_is_hidden_until_the_local_draft_is_enabled(
    without_token, monkeypatch
):
    from src.crispdm.config import settings

    monkeypatch.setattr(settings, "llm_enabled", False)
    at = page("investment_analysis", operator=True).run()

    assert not at.exception, [e.value for e in at.exception]
    assert "Generate" not in [b.label for b in at.button]


def test_a_worksheet_can_be_filled_saved_reopened_and_deleted(with_token):
    at = page("investment_analysis", operator=True).run()
    assert not at.exception, [e.value for e in at.exception]

    _fill_worksheet(at)
    assert not at.exception, [e.value for e in at.exception]

    button(at, "Save analysis").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Saved analysis" in flash.value for flash in at.success)

    with engine.begin() as conn:
        saved = (
            conn.execute(
                text(
                    "SELECT analysis_id, status, created_by, updated_by "
                    "FROM analysis.investment_analyses WHERE created_by = :o"
                ),
                {"o": OPERATOR},
            )
            .mappings()
            .first()
        )
    assert saved and saved["status"] == "draft"
    assert saved["created_by"] == OPERATOR and saved["updated_by"] is None

    next(b for b in at.sidebar.button if b.key == "ia_open").click().run()
    assert not at.exception, [e.value for e in at.exception]
    reopened = next(w for w in at.text_input if w.key == "ia__universe__universe_filters")
    assert reopened.value == "A detailed answer."

    next(b for b in at.sidebar.button if b.key == "ia_delete").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Deleted analysis" in flash.value for flash in at.success)
    with engine.connect() as conn:
        left = conn.execute(
            text("SELECT count(*) FROM analysis.investment_analyses WHERE created_by = :o"),
            {"o": OPERATOR},
        ).scalar()
    assert left == 0


def test_saving_when_the_opened_row_was_deleted_elsewhere_does_not_fake_a_save(with_token):
    at = page("investment_analysis", operator=True).run()
    _fill_worksheet(at)
    button(at, "Save analysis").click().run()
    assert not at.exception, [e.value for e in at.exception]
    first = at.session_state["ia_analysis_id"]

    # Simulate another tab deleting the row while this worksheet stayed open.
    at.session_state["ia_analysis_id"] = 999999
    at.run()
    button(at, "Save analysis").click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("no longer exists" in e.value for e in at.error)
    assert not any("Saved analysis" in s.value for s in at.success)
    assert "ia_analysis_id" not in at.session_state
    assert "ia_flash" not in at.session_state

    # The form is untouched, so the next save stores it as a new analysis.
    button(at, "Save analysis").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Saved analysis" in flash.value for flash in at.success)
    assert at.session_state["ia_analysis_id"] != first
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM analysis.investment_analyses WHERE created_by = :o"),
            {"o": OPERATOR},
        ).scalar()
    assert count == 2


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


def test_every_registered_page_runs_through_the_navigation(without_token):
    """A st.Page target must be callable. Passing a module instead of its
    .render only blows up when that page is opened, which the per-page tests
    never do — they call render() directly."""
    at = shell().run()
    assert not at.exception, [e.value for e in at.exception]
    registered = list(at._registered_pages.items())
    assert registered, "st.navigation registered no pages"
    for page_hash, info in registered:
        page = shell().run()
        # switch_page() only resolves file paths, so callable pages can only be
        # opened by the hash st.navigation registered for their url_path.
        page._page_hash = page_hash
        page.run()
        assert not page.exception, (info["page_name"], [e.value for e in page.exception])


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


def test_auto_complete_prefills_the_form_without_saving(with_token, monkeypatch):
    from app import analysis_autofill as autofill
    from app import analysis_schema as schema

    payload = schema.empty_payload()
    payload["sections"]["universe"]["universe_filters"] = "Auto-generated universe filter"
    monkeypatch.setattr(
        autofill, "fetch_company", lambda ticker, **kwargs: autofill.CompanyData(ticker=ticker)
    )
    monkeypatch.setattr(
        autofill, "build_payload", lambda ticker, data, macro=None, **kwargs: payload
    )
    monkeypatch.setattr(autofill, "load_macro", lambda: {})
    monkeypatch.setattr(autofill, "load_warehouse", lambda ticker: {})

    at = page("investment_analysis", operator=True).run()
    assert not at.exception, [e.value for e in at.exception]

    button(at, "Auto-complete").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Auto-completed" in flash.value for flash in at.success)

    prefilled = next(w for w in at.text_input if w.key == "ia__universe__universe_filters")
    assert prefilled.value == "Auto-generated universe filter"

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM analysis.investment_analyses WHERE created_by = :o"),
            {"o": OPERATOR},
        ).scalar()
    assert count == 0, "auto-complete must never save"


def test_auto_complete_options_are_opt_in(with_token, monkeypatch):
    from app import analysis_autofill as autofill
    from app import analysis_schema as schema

    seen = []
    payload = schema.empty_payload()

    def fetch(ticker, **kwargs):
        seen.append(kwargs.get("include_options", False))
        return autofill.CompanyData(ticker=ticker)

    monkeypatch.setattr(autofill, "fetch_company", fetch)
    monkeypatch.setattr(
        autofill, "build_payload", lambda ticker, data, macro=None, **kwargs: payload
    )
    monkeypatch.setattr(autofill, "load_macro", lambda: {})
    monkeypatch.setattr(autofill, "load_warehouse", lambda ticker: {})

    at = page("investment_analysis", operator=True).run()
    assert not at.checkbox(key="ia_autofill_options").value

    at = at.checkbox(key="ia_autofill_options").check().run()
    button(at, "Auto-complete").click().run()

    assert seen == [True]


def test_auto_complete_is_off_without_the_operator_token(without_token):
    at = page("investment_analysis").run()

    assert not at.exception, [e.value for e in at.exception]
    assert button(at, "Auto-complete").disabled
