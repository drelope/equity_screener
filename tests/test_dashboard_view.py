"""The 7-tab dashboard, its limits and its deterministic report drafts."""

from __future__ import annotations

import pandas as pd
import pytest

from app.views.dashboard import TAB_NAMES, _limit_table, _ratio, _reports
from src.crispdm.portfolio import BASE_NAV

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.crispdm.db import engine  # noqa: E402


def test_the_dashboard_exposes_the_seven_required_tabs():
    assert TAB_NAMES == (
        "Portfolio Dashboard",
        "Performance Analytics",
        "Risk Monitor",
        "Position Book",
        "Factor Attribution",
        "Research Pipeline",
        "Reports Center",
    )


def test_ratio_formats_missing_and_infinite_values_as_not_available():
    assert _ratio(float("nan")) == "n/a"
    assert _ratio(float("inf")) == "n/a"
    assert _ratio(0.5) == "0.50"


def test_limit_table_marks_a_single_name_breach():
    book = pd.DataFrame(
        {
            "security_id": ["s1", "s2"],
            "weight": [0.20, -0.05],
            "sector": ["Technology", "Financials"],
        }
    )

    limits = _limit_table(book).set_index("limit")

    assert limits.loc["Largest single name", "status"] == "Breach"
    assert limits.loc["Gross exposure", "status"] == "Within limit"
    assert limits.loc["Largest sector", "status"] == "Within limit"


def test_reports_are_five_markdown_drafts_with_the_simulation_caveat():
    index = pd.to_datetime(["2026-10-01", "2026-10-02"])
    path = pd.DataFrame(
        {
            "return": [0.01, -0.005],
            "nav": [BASE_NAV * 1.01, BASE_NAV * 1.01 * 0.995],
            "drawdown": [0.0, -0.005],
        },
        index=index,
    )
    table = pd.DataFrame(
        {
            "security_id": ["s1", "s2"],
            "ticker": ["T1", "T2"],
            "side": ["Long", "Short"],
            "pnl": [1000.0, -500.0],
        }
    )
    risk = {
        "components": pd.DataFrame({"security_id": ["s1", "s2"], "component_var": [0.01, -0.005]}),
        "historical_var": 0.02,
        "historical_var_amount": 2_000_000.0,
        "expected_shortfall": 0.03,
        "parametric_var": 0.025,
    }
    performance = {
        "cumulative_return": 0.005,
        "annual_return": 0.10,
        "annual_volatility": 0.20,
        "sharpe": 0.50,
        "sortino": 0.60,
        "max_drawdown": -0.01,
        "calmar": 10.0,
        "omega": 1.20,
    }
    analyses = pd.DataFrame(
        columns=[
            "ticker",
            "status",
            "recommendation",
            "confidence",
            "overall_risk_score",
            "created_at",
            "updated_at",
        ]
    )

    reports = _reports(
        {
            "path": path,
            "table": table,
            "risk": risk,
            "performance": performance,
            "analyses": analyses,
        }
    )

    assert set(reports) == {
        "Morning note",
        "Performance report",
        "Risk report",
        "IC memo",
        "Research note",
    }
    assert all("Simulated model portfolio" in report for report in reports.values())
    assert "No Final investment-analysis worksheet" in reports["IC memo"]


def _database_ready() -> bool:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT count(*) FROM model.scores LIMIT 1")
            conn.exec_driver_sql("SELECT count(*) FROM raw.market_data LIMIT 1")
        return True
    except Exception:
        return False


def page_script():
    from app.views import dashboard

    dashboard.render()


@pytest.mark.skipif(not _database_ready(), reason="no live database with scores and prices")
def test_dashboard_renders_with_the_simulated_label():
    at = AppTest.from_function(page_script, default_timeout=180).run()

    assert not at.exception, [error.value for error in at.exception]
    assert tuple(tab.label for tab in at.tabs) == TAB_NAMES
    captions = [caption.value for caption in at.caption]
    assert any("Simulated 15 long / 8 short" in caption for caption in captions)
    subheaders = [subheader.value for subheader in at.subheader]
    assert "Walk-forward backtest" in subheaders


def test_the_backtest_loader_takes_the_newest_run_with_all_outputs(tmp_path):
    import json

    from app.views.dashboard import _load_latest_backtest

    index = pd.bdate_range("2026-01-05", periods=3)
    daily = pd.DataFrame(
        {"return": [0.01, -0.02, 0.0], "benchmark": [0.0, 0.0, 0.0], "nav": [1.0, 0.98, 0.98]},
        index=index,
    )
    periods = pd.DataFrame(
        {
            "formation": [index[0]],
            "end": [index[-1]],
            "status": ["held"],
            "long_names": [15],
            "short_names": [8],
            "period_return": [-0.02],
            "benchmark_return": [0.0],
            "turnover": [0.5],
            "missing_days": [0],
        }
    )
    for stamp in ("20260101_0000", "20260102_0000"):
        (tmp_path / f"metrics_{stamp}.json").write_text(
            json.dumps({"held_periods": 1, "cash_periods": 0}), encoding="utf-8"
        )
    # Only the older run has its CSV outputs; the newer one is incomplete.
    daily.to_csv(tmp_path / "daily_20260101_0000.csv")
    periods.to_csv(tmp_path / "periods_20260101_0000.csv", index=False)

    run = _load_latest_backtest(str(tmp_path))

    assert run["stamp"] == "20260101_0000"
    assert run["metrics"]["held_periods"] == 1
    assert list(run["daily"].columns) == ["return", "benchmark", "nav"]


def test_the_backtest_loader_reports_no_run_when_the_directory_is_empty(tmp_path):
    from app.views.dashboard import _load_latest_backtest

    assert _load_latest_backtest(str(tmp_path)) is None
