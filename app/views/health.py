"""Health: the morning verification, run history and data freshness.

The checks come from ``scripts.verify_nightly_run`` (the same ``fetch_findings`` and
``assess`` the command-line check uses, with its default thresholds), so this page and
the morning check cannot disagree. Nothing here is written to the database; recording a
verification is still ``python -m scripts.verify_nightly_run``.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from app import ui
from scripts import verify_nightly_run as verify
from src.crispdm.config import settings

THRESHOLDS = {
    "min_quality_score": 0.50,
    "min_good_share": 0.80,
    "min_coverage": 0.95,
    "max_age_hours": 26.0,
}


@st.cache_data(ttl=120, show_spinner=False)
def verification(run_date) -> dict:
    with ui.engine.connect() as conn:
        findings = verify.fetch_findings(conn, run_date, settings.dividend_lookback_start)
    result = verify.assess(findings, **THRESHOLDS)
    return {"findings": findings, "result": result}


def checks_section(result: dict) -> None:
    # Text, not st.metric: a metric truncates a word like "ATTENTION" in a narrow column.
    st.markdown(f"### Overall: {ui.status_label(result['status'])}")
    counts = pd.Series([c["status"] for c in result["checks"]]).value_counts()
    st.caption(
        ", ".join(f"{n} {name}" for name, n in counts.items()) + " (thresholds as in the CLI check)"
    )
    for check in result["checks"]:
        st.markdown(f"{ui.status_label(check['status'])} **{check['name']}**: {check['detail']}")


def freshness_section(findings: dict) -> None:
    freshness = findings.get("freshness")
    if not freshness:
        return
    rows = []
    for source, age in (freshness.get("sources") or {}).items():
        sla = (freshness.get("sla_hours") or {}).get(source)
        if age is not None and sla:
            rows.append({"source": source, "age_hours": age, "sla_hours": sla, "of_sla": age / sla})
    if not rows:
        return
    frame = pd.DataFrame(rows)
    st.subheader("Data freshness")
    fig = px.bar(
        frame,
        x="of_sla",
        y="source",
        orientation="h",
        labels={"of_sla": "Age as a share of its SLA (1.0 = at the limit)"},
        color=frame.of_sla > 1,
        color_discrete_map={True: "#d62728", False: "#2ca02c"},
    )
    fig.add_vline(x=1.0, line_dash="dash")
    fig.update_layout(showlegend=False, margin={"t": 10})
    st.plotly_chart(fig, width="stretch")
    st.dataframe(frame.round(2), hide_index=True, width="stretch")


def runs_section() -> None:
    st.subheader("Recent nightly runs")
    runs = ui.query(
        """
        SELECT run_id, run_date, trigger, status, exit_code, started_at, finished_at, stages,
               row_counts
        FROM audit.nightly_runs ORDER BY run_id DESC LIMIT 14
        """
    )
    if runs.empty:
        st.caption("No nightly runs recorded yet.")
        return
    shown = runs.assign(
        duration=[ui.fmt_duration(s, f) for s, f in zip(runs.started_at, runs.finished_at)],
        failed_stages=[
            ", ".join(k for k, v in (s or {}).items() if v == "failed") or "-" for s in runs.stages
        ],
    )[["run_id", "run_date", "trigger", "status", "exit_code", "duration", "failed_stages"]]
    st.dataframe(shown, hide_index=True, width="stretch")

    pick = st.selectbox("Inspect a run", runs.run_id.tolist(), key="health_run")
    row = runs[runs.run_id == pick].iloc[0]
    left, right = st.columns(2)
    left.markdown("**Stages**")
    left.dataframe(
        pd.DataFrame(sorted((row.stages or {}).items()), columns=["stage", "result"]),
        hide_index=True,
        width="stretch",
    )
    right.markdown("**Row counts at the end of the run**")
    counts = row.row_counts or {}
    if counts:
        right.dataframe(
            pd.DataFrame(sorted(counts.items()), columns=["table", "rows"]),
            hide_index=True,
            width="stretch",
        )
    else:
        right.caption("Not recorded for this run.")


def render() -> None:
    st.title("Health")
    st.caption(
        "The nightly ETL runs from the host's systemd timer at 03:00 America/New_York. "
        "This page reads its results and does not control it."
    )
    ui.refresh_button("health_refresh")
    run_date = st.date_input("Run date", value=verify.target_run_date(), key="health_date")
    try:
        bundle = verification(run_date)
    except Exception as exc:  # the check touches many tables; show what failed, not a trace
        st.error(f"The verification could not run ({type(exc).__name__}: {exc}).")
        return
    checks_section(bundle["result"])
    freshness_section(bundle["findings"])
    runs_section()
