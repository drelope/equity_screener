"""Investment analysis: the top-down workflow as a structured worksheet.

The 18 workflow steps and their fields come from ``app/analysis_schema`` (the single
source of truth, mirrored by ``docs/InvestmentAnalysisWorkflow.md``). The page prefills
a read-only context panel from the warehouse, tracks completion of the required fields,
validates on save, stores the worksheet as JSONB in ``analysis.investment_analyses`` and
exports Markdown/JSON. Nothing here calls a model: the report is written by the analyst,
optionally pasted into an external LLM afterwards in the exported Markdown form.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app import analysis_schema as schema
from app import ui
from app.views.screener import SELECTED_KEY
from app.views.security import feature_section, financials_section, profile, score_section
from src.crispdm.analysis import store

PENDING_KEY = "ia_pending"
TICKER_KEY = "ia_ticker"
ANALYSIS_KEY = "ia_analysis_id"
UPDATED_KEY = "ia_updated_at"
FLASH_KEY = "ia_flash"
STATUS_OPTIONS = ("Draft", "Final")

#: Shared with the ``st.Page`` registration in ``app/streamlit_app.py``: st.switch_page
#: matches a callable page by its source and url_path, so both definitions read these.
PAGE_TITLE = "Investment analysis"
PAGE_PATH = "analysis"


def go_to_analysis(ticker: str | None = None) -> None:
    """Hand the ticker over to the worksheet and switch to it."""
    if ticker:
        st.session_state[SELECTED_KEY] = ticker
    st.switch_page(st.Page(render, title=PAGE_TITLE, url_path=PAGE_PATH))


def _key(section: schema.Section, field: schema.Field) -> str:
    return f"ia__{section.id}__{field.id}"


def _clear_form() -> None:
    for section in schema.SECTIONS:
        for field in section.all_fields:
            st.session_state.pop(_key(section, field), None)


def _hydrate(payload: dict) -> None:
    """Copy a saved payload into the widget keys, before any widget is created."""
    sections = payload.get("sections", {})
    for section in schema.SECTIONS:
        values = sections.get(section.id, {})
        for field in section.all_fields:
            raw = values.get(field.id)
            if field.kind == "select":
                text = "" if raw is None else str(raw)
                widget = text if text in field.options else schema.PLACEHOLDER
            elif field.kind == "score":
                widget = int(raw) if isinstance(raw, int) and 1 <= raw <= 10 else None
            else:
                widget = "" if raw is None else str(raw)
            st.session_state[_key(section, field)] = widget


def _payload_from_state() -> dict:
    payload: dict = {"version": schema.SCHEMA_VERSION, "sections": {}}
    for section in schema.SECTIONS:
        values: dict = {}
        for field in section.all_fields:
            raw = st.session_state.get(_key(section, field))
            if field.kind == "select":
                values[field.id] = "" if raw in (None, schema.PLACEHOLDER) else str(raw)
            elif field.kind == "score":
                values[field.id] = int(raw) if isinstance(raw, (int, float)) else None
            else:
                values[field.id] = "" if raw is None else str(raw)
        payload["sections"][section.id] = values
    return payload


def _render_field(section: schema.Section, field: schema.Field) -> None:
    key = _key(section, field)
    help_text = field.help or None
    if field.kind == "text":
        st.text_input(field.label, key=key, help=help_text)
    elif field.kind == "textarea":
        st.text_area(field.label, key=key, help=help_text)
    elif field.kind == "select":
        st.selectbox(field.label, [schema.PLACEHOLDER, *field.options], key=key, help=help_text)
    else:
        st.number_input(
            field.label, min_value=1, max_value=10, step=1, value=None, key=key, help=help_text
        )


def _write(fn):
    with ui.engine.begin() as conn:
        return fn(conn)


def _read(fn):
    with ui.engine.connect() as conn:
        return fn(conn)


def _saved_rows(security_id: str) -> list[dict]:
    return _read(lambda conn: store.list_for_security(conn, security_id))


def _saved_label(row: dict) -> str:
    return (
        f"#{row['analysis_id']} · {row['status']} · {row['confidence'] or 'no confidence'}"
        f" · updated {ui.fmt_ts(row['updated_at'])}"
    )


def _sidebar(info: pd.Series) -> None:
    with st.sidebar:
        st.subheader("Worksheet")
        if st.button("New analysis", key="ia_new"):
            _clear_form()
            st.session_state.pop(ANALYSIS_KEY, None)
            st.session_state.pop(UPDATED_KEY, None)
            st.session_state.pop(FLASH_KEY, None)
            st.rerun()
        st.divider()
        st.caption("Saved analyses")
        rows = _saved_rows(info.security_id)
        if not rows:
            st.caption("None saved for this security yet.")
            return
        labels = [_saved_label(row) for row in rows]
        chosen = st.selectbox("Saved", labels, key="ia_pick")
        current = st.session_state.get(ANALYSIS_KEY)
        if st.button("Open", key="ia_open"):
            index = labels.index(chosen)
            row = rows[index]
            detail = _read(lambda conn: store.get(conn, row["analysis_id"]))
            if detail:
                st.session_state[PENDING_KEY] = {
                    "payload": detail["payload"],
                    "analysis_id": detail["analysis_id"],
                    "status": detail["status"],
                    "updated_at": detail["updated_at"],
                }
                st.rerun()
            else:
                st.warning(
                    f"Analysis #{row['analysis_id']} disappeared while this page was open; "
                    "the list refreshes on every rerun."
                )
        gated = not ui.controls_enabled()
        if st.button("Delete", key="ia_delete", disabled=gated):
            index = labels.index(chosen)
            target = rows[index]["analysis_id"]
            try:
                existed = _write(lambda conn: store.delete(conn, target))
            except SQLAlchemyError as exc:
                st.error(f"Delete failed ({type(exc).__name__}); the row is still there.")
            else:
                if current == target:
                    # The open worksheet is gone; keep the form from editing a ghost.
                    _clear_form()
                    st.session_state.pop(ANALYSIS_KEY, None)
                    st.session_state.pop(UPDATED_KEY, None)
                st.session_state[FLASH_KEY] = (
                    f"Deleted analysis #{target}."
                    if existed
                    else f"Analysis #{target} was already gone."
                )
                st.rerun()
        if gated:
            ui.require_controls_note()
        if current:
            st.caption(f"Editing saved analysis #{current}")


def _context(info: pd.Series) -> None:
    with st.expander("Warehouse context (prefill)", expanded=False):
        st.caption(
            "Read-only inputs for steps 9-13: engineered features, score history, "
            "point-in-time ratios and reported fundamentals."
        )
        tabs = st.tabs(["Features", "Scores", "Ratios"])
        with tabs[0]:
            feature_section(info.security_id)
        with tabs[1]:
            score_section(info.security_id)
        with tabs[2]:
            financials_section(info.security_id)


def _summary_row(payload: dict) -> tuple[int, int]:
    filled, total = schema.completion(payload)
    st.progress(
        filled / total if total else 0.0, text=f"Required fields: {filled}/{total} complete"
    )
    return filled, total


def _save_actions(info: pd.Series, payload: dict) -> None:
    a, b, c = st.columns([2, 2, 3])
    status_label = a.selectbox("Status", STATUS_OPTIONS, key="ia_status")
    save = b.button(
        "Save analysis", type="primary", key="ia_save", disabled=not ui.controls_enabled()
    )
    if not ui.controls_enabled():
        ui.require_controls_note()
    current = st.session_state.get(ANALYSIS_KEY)
    if current:
        c.caption(f"Saving updates analysis #{current}")
    if not save:
        return
    # A Draft may be partial; a Final must satisfy every rule, including the sequence gate.
    errors = schema.validate(payload) if status_label == "Final" else schema.validate_draft(payload)
    if errors:
        st.error(f"{len(errors)} field(s) need attention before this can be saved.")
        st.code("\n".join(errors[:20]), language="text")
        return
    if current:
        stored = _read(lambda conn: store.get(conn, current))
        if stored is None:
            # Deleted in another tab since this worksheet was opened: do not
            # claim a save that never happened, and stop targeting the ghost.
            st.session_state.pop(ANALYSIS_KEY, None)
            st.session_state.pop(UPDATED_KEY, None)
            st.error(
                f"Analysis #{current} no longer exists (deleted elsewhere?). "
                "Nothing was written; press Save again to store it as a new analysis."
            )
            return
        if str(stored["updated_at"]) != str(st.session_state.get(UPDATED_KEY)):
            # Someone saved this row since we loaded it; overwriting would lose their edit.
            st.error(
                f"Analysis #{current} changed in another tab since it was opened. "
                "Reopen it from the sidebar before saving so the newer version is not lost."
            )
            return
    summary = schema.final_summary(payload)
    args = {
        "payload": payload,
        "thesis": summary["thesis"],
        "recommendation": summary["recommendation"],
        "confidence": summary["confidence"],
        "overall_risk_score": summary["overall_risk_score"],
        "status": status_label.lower(),
    }
    operator = ui.operator() or "unknown"
    try:
        if current:
            existed = _write(lambda conn: store.update(conn, current, updated_by=operator, **args))
            if not existed:
                # Deleted between the existence check and the write.
                st.session_state.pop(ANALYSIS_KEY, None)
                st.session_state.pop(UPDATED_KEY, None)
                st.error(
                    f"Analysis #{current} no longer exists (deleted elsewhere?). "
                    "Nothing was written; press Save again to store it as a new analysis."
                )
                return
            saved_id = current
        else:
            saved_id = _write(
                lambda conn: store.create(
                    conn,
                    security_id=info.security_id,
                    ticker=info.ticker,
                    created_by=operator,
                    **args,
                )
            )
    except SQLAlchemyError as exc:
        st.error(f"Saving failed ({type(exc).__name__}); the warehouse refused the write.")
        return
    saved = _read(lambda conn: store.get(conn, saved_id))
    st.session_state[ANALYSIS_KEY] = saved_id
    st.session_state[UPDATED_KEY] = saved["updated_at"] if saved else None
    st.session_state[FLASH_KEY] = f"Saved analysis #{saved_id}."
    st.rerun()


def _exports(payload: dict, ticker: str) -> None:
    st.download_button(
        "Download Markdown",
        schema.to_markdown(payload, ticker).encode("utf-8"),
        file_name=f"investment_analysis_{ticker}.md",
        mime="text/markdown",
        key="ia_dl_md",
    )
    st.download_button(
        "Download JSON",
        schema.to_json(payload).encode("utf-8"),
        file_name=f"investment_analysis_{ticker}.json",
        mime="application/json",
        key="ia_dl_json",
    )


def render() -> None:
    st.title("Investment analysis")
    st.caption(
        "Structured worksheet for the top-down workflow "
        "(docs/InvestmentAnalysisWorkflow.md). Steps are sequential: do not reach a "
        "recommendation before steps 1-17 are complete."
    )

    pending = st.session_state.pop(PENDING_KEY, None)
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash)

    tickers = ui.query(
        "SELECT ticker FROM reference.securities WHERE active ORDER BY ticker"
    ).ticker.tolist()
    if not tickers:
        st.warning("No active securities. Run the reference-data load first.")
        return

    chosen = st.session_state.get(SELECTED_KEY)
    index = tickers.index(chosen) if chosen in tickers else 0
    ticker = st.selectbox("Ticker", tickers, index=index)
    st.session_state[SELECTED_KEY] = ticker

    found = profile(ticker)
    if found.empty:
        st.error(f"{ticker} is not an active security.")
        return
    info = found.iloc[0]

    if st.session_state.get(TICKER_KEY) != ticker:
        # Switching securities starts a blank worksheet; a loaded one is applied below.
        _clear_form()
        st.session_state[TICKER_KEY] = ticker
        st.session_state.pop(ANALYSIS_KEY, None)
        st.session_state.pop(UPDATED_KEY, None)
    if pending:
        _hydrate(pending["payload"])
        st.session_state[ANALYSIS_KEY] = pending["analysis_id"]
        st.session_state[UPDATED_KEY] = pending.get("updated_at")
        # Forced, not defaulted: opening another worksheet must adopt its status.
        st.session_state["ia_status"] = str(pending.get("status", "draft")).title()
        version = pending["payload"].get("version")
        if version != schema.SCHEMA_VERSION:
            st.warning(
                f"Analysis #{pending['analysis_id']} was written under schema version "
                f"{version or 'unknown'}; this app edits version {schema.SCHEMA_VERSION}. "
                "Fields the older version did not know start blank."
            )

    _sidebar(info)
    _context(info)

    payload = _payload_from_state()
    counts = schema.section_completion(payload)
    first_incomplete = next(
        (s.id for s in schema.SECTIONS if counts[s.id][0] < counts[s.id][1]), None
    )
    prior_ok = schema.prior_steps_complete(payload)
    for step, section in enumerate(schema.SECTIONS, start=1):
        filled, total = counts[section.id]
        label = f"{step}. {section.title}"
        if total:
            label += f" ({filled}/{total})"
        with st.expander(label, expanded=(section.id == first_incomplete)):
            if section.intro:
                st.caption(section.intro)
            if section.id == "final" and not prior_ok:
                st.warning(
                    "Steps 1-17 are incomplete; a recommendation cannot be saved until "
                    "their required fields are filled."
                )
            for field in section.all_fields:
                _render_field(section, field)

    _summary_row(payload)
    _save_actions(info, payload)
    _exports(payload, ticker)
