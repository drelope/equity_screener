"""Data explorer: browse an allowlisted table with filters, sorting and a quick chart.

The SQL is built by ``src.crispdm.explorer`` from the reflected column list, so a column
or operator that is not in that list can never reach the statement, and values travel as
bound parameters. The query runs in a read-only transaction with a statement timeout.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app import column_docs, ui
from src.crispdm import explorer

RESULT_KEY = "explorer_result"
NO_SORT = "(none)"
ROW_LIMITS = [100, 500, 1000, explorer.MAX_ROWS]


@st.cache_data(ttl=300, show_spinner="Reflecting the database schema")
def columns_of(relation: str) -> dict[str, str]:
    with ui.engine.connect() as conn:
        return explorer.reflect_columns(conn, relation)


def filter_rows(columns: dict[str, str], prefix: str) -> list[dict]:
    """Render the filter controls and return the filters as the explorer expects them."""
    count = st.number_input(
        "Filters", min_value=0, max_value=explorer.MAX_FILTERS, value=0, key=f"{prefix}_n"
    )
    filters = []
    for i in range(int(count)):
        a, b, c = st.columns([3, 2, 3])
        column = a.selectbox("Column", list(columns), key=f"{prefix}_col{i}")
        kind = explorer.kind_of(columns[column])
        op = b.selectbox("Operator", explorer.OPERATORS_BY_KIND[kind], key=f"{prefix}_op{i}")
        value = None
        if op not in ("is empty", "is not empty"):
            hint = {"date": "YYYY-MM-DD", "bool": "true / false", "number": "a number"}.get(kind)
            value = c.text_input("Value", key=f"{prefix}_val{i}", placeholder=hint, max_chars=200)
        filters.append({"column": column, "op": op, "value": value})
    return filters


def run(relation: str, columns: dict, select, filters, order_by, descending, limit) -> None:
    try:
        sql, params = explorer.build_query(
            relation,
            columns,
            select=select,
            filters=filters,
            order_by=order_by,
            descending=descending,
            limit=limit,
        )
    except ValueError as exc:
        st.session_state.pop(RESULT_KEY, None)
        st.error(str(exc))
        return
    try:
        with st.spinner("Running query"):
            frame = explorer.run_query(ui.engine, sql, params)
    except SQLAlchemyError as exc:
        st.session_state.pop(RESULT_KEY, None)
        st.error(f"The query failed or timed out ({type(exc).__name__}). Narrow the filters.")
        return
    st.session_state[RESULT_KEY] = {"frame": frame, "sql": sql, "params": params, "limit": limit}


def show_result(label: str) -> None:
    result = st.session_state.get(RESULT_KEY)
    if not result:
        st.caption("Choose columns and filters, then run the query.")
        return
    frame: pd.DataFrame = result["frame"]
    st.caption(f"{len(frame):,} rows")
    if len(frame) >= result["limit"]:
        st.warning(f"Showing the first {result['limit']:,} rows; add filters to narrow the result.")
    spec = explorer.dataset(label)
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config=column_docs.config_for(spec.relation, frame.columns),
    )
    st.download_button(
        "Download as CSV",
        frame.to_csv(index=False).encode("utf-8"),
        file_name=f"{label.lower().replace(' ', '_')}.csv",
        mime="text/csv",
    )
    with st.expander("Query"):
        st.code(result["sql"], language="sql")
        st.json({k: str(v) for k, v in result["params"].items()})
    chart(frame)


def _is_date_like(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    first = series.dropna().head(1)
    return len(first) == 1 and hasattr(first.iloc[0], "isoformat")


def chart(frame: pd.DataFrame) -> None:
    numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    if frame.empty or not numeric:
        return
    dated = [c for c in frame.columns if _is_date_like(frame[c])]
    with st.expander("Chart"):
        a, b, c = st.columns(3)
        kind = a.selectbox("Type", ["line", "bar", "scatter"])
        x = b.selectbox("X", list(dict.fromkeys(dated + list(frame.columns))))
        y = c.selectbox("Y", numeric)
        plot = frame.dropna(subset=[y])
        try:
            plot = plot.sort_values(x)
        except TypeError:
            pass  # mixed types in the X column: plot in query order
        make = {"line": px.line, "bar": px.bar, "scatter": px.scatter}[kind]
        st.plotly_chart(make(plot, x=x, y=y), width="stretch")


def render() -> None:
    st.title("Data explorer")
    label = st.selectbox("Dataset", list(explorer.DATASETS))
    spec = explorer.dataset(label)
    st.caption(f"{spec.description}  Source: `{spec.relation}`")

    columns = columns_of(spec.relation)
    if not columns:
        st.error(f"{spec.relation} has no columns here; has the schema been migrated?")
        return
    prefix = f"explorer_{label}"

    names = list(columns)
    select = st.multiselect("Columns", names, default=names[:12], key=f"{prefix}_select")
    with st.expander("Filters", expanded=False):
        filters = filter_rows(columns, prefix)
    a, b, c = st.columns([3, 2, 2])
    sort_options = [NO_SORT, *names]
    default = sort_options.index(spec.default_order) if spec.default_order in names else 0
    order = a.selectbox("Sort by", sort_options, index=default, key=f"{prefix}_order")
    # Newest first for dates and ids; A to Z for a text key such as the ticker.
    newest_first = (
        spec.default_order in columns and explorer.kind_of(columns[spec.default_order]) != "text"
    )
    descending = b.checkbox("Descending", value=newest_first, key=f"{prefix}_desc")
    limit = c.selectbox("Row limit", ROW_LIMITS, index=1, key=f"{prefix}_limit")

    if st.button("Run query", type="primary", key=f"{prefix}_run"):
        run(
            spec.relation,
            columns,
            select,
            filters,
            None if order == NO_SORT else order,
            descending,
            limit,
        )
    show_result(label)
