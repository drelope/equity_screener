"""Cross-page navigation helpers."""

from streamlit.testing.v1 import AppTest


def _flow():
    import streamlit as st

    from app import nav

    st.session_state[nav.ORDER_KEY] = ["AAA", "BBB", "CCC"]
    st.session_state.setdefault(nav.SELECTED_KEY, "BBB")
    st.session_state.setdefault(nav.RETURN_KEY, nav.SCREENER)
    nav.render_flow_bar(nav.SECURITY)


def test_flow_bar_has_back_prev_next():
    at = AppTest.from_function(_flow).run(timeout=30)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Back to screener" in labels
    assert "Prev" in labels and "Next" in labels


def test_next_steps_selected_ticker():
    at = AppTest.from_function(_flow).run(timeout=30)
    next(b for b in at.button if b.label == "Next").click()
    at.run(timeout=30)
    assert at.session_state["selected_ticker"] == "CCC"


def test_siblings_edges():
    def script():
        import streamlit as st

        from app import nav

        st.session_state[nav.ORDER_KEY] = ["AAA", "BBB"]
        st.write(nav.siblings("AAA"))
        st.write(nav.siblings("ZZZ"))

    at = AppTest.from_function(script).run(timeout=30)
    assert not at.exception


def test_open_page_without_registry_sets_ticker():
    def script():
        from app import nav

        nav.open_page(nav.SECURITY, "XYZ", origin=nav.SCREENER)

    at = AppTest.from_function(script).run(timeout=30)
    assert at.session_state["selected_ticker"] == "XYZ"
    assert at.session_state["return_route"] == "screener"


def test_seed_from_url_adopts_ticker_once():
    def script():
        import streamlit as st

        from app import nav

        nav.seed_from_url()
        st.write(st.session_state.get(nav.SELECTED_KEY))

    at = AppTest.from_function(script)
    at.query_params["ticker"] = "URL1"
    at.run(timeout=30)
    assert at.session_state["selected_ticker"] == "URL1"
    at.session_state["selected_ticker"] = "OTHER"
    at.run(timeout=30)
    assert at.session_state["selected_ticker"] == "OTHER"


def test_selectable_table_renders_without_selection():
    def script():
        import pandas as pd

        from app import nav

        nav.selectable_table(
            pd.DataFrame({"ticker": ["AAA", "BBB"], "side": ["Long", "Short"]}),
            key="t",
            origin=nav.DASHBOARD,
        )

    at = AppTest.from_function(script).run(timeout=30)
    assert not at.exception
    assert not at.button


def test_flow_bar_without_return_route_has_no_back():
    def script():
        from app import nav

        nav.render_flow_bar(nav.ANALYSIS, "AAA")

    at = AppTest.from_function(script).run(timeout=30)
    assert "Back to screener" not in [b.label for b in at.button]
