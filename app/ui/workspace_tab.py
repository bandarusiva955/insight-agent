"""My data tab: upload -> auto-clean -> dashboard -> ask -> report."""

import os

import streamlit as st

from app.ui import ask_tab, insights_panel
from app.ui.access import budget_for_session  # noqa: F401  (shared session budget)
from app.workspace import ingest, store
from app.workspace.cleaning import clean_dataframe
from app.workspace.dashboard import build_dashboard
from app.workspace.profile import profile_frame
from app.workspace.report import build_report

STATE = "ws_state"
HISTORY = "ws_history"


def _reset():
    state = st.session_state.pop(STATE, None)
    st.session_state.pop(HISTORY, None)

    if state:
        try:
            store.drop_workspace(state["workspace"].schema)
        except Exception as error:  # best effort; the TTL sweep removes leftovers
            print(f"Workspace cleanup skipped: {error}", flush=True)


def _load(uploaded):
    raw = ingest.read_upload(uploaded.name, uploaded.getvalue())
    cleaned = {name: clean_dataframe(frame) for name, frame in raw.items()}
    cleaned = {n: r for n, r in cleaned.items() if not r.frame.empty}

    if not cleaned:
        raise ingest.UploadError(
            "No usable data was left after cleaning (the file has no filled-in rows)."
        )

    frames = {name: result.frame for name, result in cleaned.items()}

    try:
        store.drop_expired()
    except Exception as error:
        print(f"Expiry sweep skipped: {error}", flush=True)

    workspace = store.create_workspace(frames)

    st.session_state[STATE] = {
        "file": uploaded.name,
        "file_id": f"{uploaded.name}:{uploaded.size}",
        "cleaned": cleaned,
        "workspace": workspace,
    }
    st.session_state[HISTORY] = []


def _render_cleaning(result):
    st.caption(
        f"{result.rows_before:,} rows in → {result.rows_after:,} rows out. "
        "Your original file is never changed. Outliers and missing values are "
        "only flagged, never deleted or filled in."
    )

    for step in result.steps:
        prefix = f"**{step.column}**: " if step.column else ""
        st.markdown(f"- {prefix}{step.detail}")


def _render_dashboard(name, result, profiles, source):
    frame = result.frame
    board = build_dashboard(frame, profiles)

    columns = st.columns(len(board.kpis))
    for column, (label, value) in zip(columns, board.kpis):
        column.metric(label, value)

    if board.findings:
        st.markdown("**Key findings**")
        for finding in board.findings:
            st.markdown(f"- {finding}")

    pairs = st.columns(2)
    for index, (_, figure) in enumerate(board.charts):
        pairs[index % 2].plotly_chart(figure, width="stretch", key=f"{name}_chart_{index}")

    st.markdown("**Cleaned data**")
    st.dataframe(frame.head(200), width="stretch", hide_index=True)

    left, right = st.columns(2)
    left.download_button(
        "⬇️ Download cleaned CSV",
        frame.to_csv(index=False).encode("utf-8"),
        file_name=f"{name}_cleaned.csv",
        mime="text/csv",
        key=f"{name}_csv",
    )
    right.download_button(
        "📄 Download analyst report (HTML)",
        build_report(f"{name.replace('_', ' ').title()} analysis", source, result, board, profiles),
        file_name=f"{name}_report.html",
        mime="text/html",
        key=f"{name}_report",
    )


def render():
    st.subheader("Analyse your own data")
    st.caption(
        "Upload a CSV or Excel file. It is cleaned automatically (with a full "
        "change log), turned into a dashboard, and you can ask questions about "
        "it. Your file is stored in a private temporary workspace for "
        f"{store.WORKSPACE_TTL_HOURS} hours at most, separate from the sample data."
    )

    if os.getenv("PRIVACY_MODE", "").strip().lower() != "strict":
        st.caption(
            "Privacy: when you ask a question, column names and a few example "
            "category values are sent to Gemini to write the SQL. Do not upload "
            "data you are not allowed to share with a cloud AI service."
        )

    uploader_key = f"ws_upload_{st.session_state.get('ws_upload_n', 0)}"
    uploaded = st.file_uploader(
        "Upload CSV or Excel", type=["csv", "tsv", "txt", "xlsx"], key=uploader_key
    )

    state = st.session_state.get(STATE)

    if uploaded is not None and (
        state is None or state["file_id"] != f"{uploaded.name}:{uploaded.size}"
    ):
        _reset()

        with st.spinner("Reading and cleaning your file..."):
            try:
                _load(uploaded)
            except ingest.UploadError as error:
                st.error(str(error))
                return
            except Exception as error:
                st.error(f"Could not process this file: {error}")
                return

        state = st.session_state[STATE]

    if uploaded is None and state is not None:
        _reset()
        state = None

    if state is None:
        st.info("Upload a file to start.")
        return

    workspace = state["workspace"]
    names = list(state["cleaned"])
    name = names[0] if len(names) == 1 else st.selectbox("Table / sheet", names)
    result = state["cleaned"][name]
    profiles = workspace.tables[name]

    dash, found, clean, ask = st.tabs(
        ["📊 Dashboard", "🔎 Insights & tests", "🧹 Cleaning report", "💬 Ask"]
    )

    with dash:
        _render_dashboard(name, result, profiles, state["file"])

    with found:
        insights_panel.render(name, state["file"], result, profiles)

    with clean:
        _render_cleaning(result)

        with st.expander("Detected columns"):
            st.dataframe(
                [{"column": p.name, "type": p.role, "distinct": p.nunique,
                  "missing": f"{p.missing_share:.0%}"} for p in profiles],
                width="stretch", hide_index=True,
            )

    with ask:
        st.caption("Tables you can ask about: " + ", ".join(names))
        ask_tab.render(workspace=workspace, state_key=HISTORY, key_prefix="ws_")

    st.divider()
    if st.button("🗑️ Delete my data now"):
        _reset()
        st.session_state["ws_upload_n"] = st.session_state.get("ws_upload_n", 0) + 1
        st.rerun()
