"""Headless run of the full tabbed dashboard against the synthetic database."""

from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.db

DASHBOARD = str(Path(__file__).resolve().parents[1] / "app" / "ui" / "dashboard.py")


def _app():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(DASHBOARD, default_timeout=60)


def test_dashboard_renders_all_tabs_without_errors(seeded_db):
    at = _app().run()

    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 7
    # KPI cards rendered from the synthetic data
    labels = [m.label for m in at.metric]
    assert "Revenue" in labels and "On-time rate" in labels


def test_ask_flow_with_mocked_pipeline(seeded_db, monkeypatch):
    from app import pipeline
    from app.pipeline import PipelineResult
    import app.ui.ask_tab as ask_tab

    def fake(question, max_attempts=3, history=None, audit=True, workspace=None):
        return PipelineResult(
            sql="SELECT 1 AS n", dataframe=pd.DataFrame({"n": [1]}), attempts=1
        )

    monkeypatch.setattr(ask_tab, "run_pipeline_detailed", fake)
    monkeypatch.setattr(pipeline, "run_pipeline_detailed", fake)

    at = _app().run()
    at.text_area[0].set_value("how many things?")
    button = next(b for b in at.button if "Analy" in b.label or "Run" in b.label or "Ask" in b.label)
    button.click().run()

    assert not at.exception, [e.value for e in at.exception]
    assert any("SELECT 1" in c.value for c in at.code), "generated SQL not shown"
    assert len(at.session_state.query_history) == 1


def test_password_gate(seeded_db, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "letmein")

    at = _app().run()

    assert not at.exception
    assert len(at.tabs) == 0
    assert at.text_input[0].label == "Password"

    at.text_input[0].set_value("wrong")
    at.button[0].click().run()
    assert len(at.tabs) == 0

    at.text_input[0].set_value("letmein")
    at.button[0].click().run()
    assert not at.exception
    assert len(at.tabs) == 7


def _upload_script():
    import streamlit as st

    from tests.support.messy_data import messy_sales_csv

    data = messy_sales_csv()

    class FakeUpload:
        name = "sales.csv"
        size = len(data)

        def getvalue(self):
            return data

    st.file_uploader = lambda *args, **kwargs: [FakeUpload()]

    from app.ui import workspace_tab

    workspace_tab.render()


def test_my_data_tab_upload_flow(seeded_db):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_upload_script, default_timeout=60).run()

    assert not at.exception, [e.value for e in at.exception]
    labels = [m.label for m in at.metric]
    assert "Rows" in labels and "Total amount" in labels
    assert next(m.value for m in at.metric if m.label == "Rows") == "240"
    assert any("duplicate" in m.value for m in at.markdown)

    # clean up the workspace schema this test created
    from app.workspace import store

    store.drop_workspace(at.session_state["ws_state"]["workspace"].schema, seeded_db)
