"""My data tab: upload -> auto-clean -> dashboard -> ask -> report."""

import os

import streamlit as st

from app.ui import ask_tab, insights_panel
from app.ui.access import budget_for_session  # noqa: F401  (shared session budget)
from app.workspace import ingest, relations, store
from app.workspace.cleaning import CleanResult, clean_dataframe
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


MAX_FILES = 5


def _unique_name(name, taken):
    candidate, number = name, 2

    while candidate in taken:
        candidate = f"{name[:36]}_{number}"
        number += 1

    return candidate


def _load(uploads):
    if len(uploads) > MAX_FILES:
        raise ingest.UploadError(f"Upload at most {MAX_FILES} files at a time.")

    cleaned = {}

    for uploaded in uploads:
        raw = ingest.read_upload(uploaded.name, uploaded.getvalue())

        for name, frame in raw.items():
            result = clean_dataframe(frame)

            if not result.frame.empty:
                cleaned[_unique_name(name, cleaned)] = result

    if not cleaned:
        raise ingest.UploadError(
            "No usable data was left after cleaning (the file has no filled-in rows)."
        )

    frames = {name: result.frame for name, result in cleaned.items()}
    relationships = relations.find_relationships(frames) if len(frames) > 1 else []
    combined, fact = relations.combine(frames, relationships)

    if combined is not None:
        name = _unique_name(relations.COMBINED_NAME, cleaned)
        joined = CleanResult(frame=combined, rows_before=len(combined), rows_after=len(combined))
        joined.add(
            "join",
            f"Joined {len(relationships)} related table(s) onto '{fact}' with LEFT joins "
            "(no rows added or removed).",
            len(combined),
        )
        cleaned = {name: joined, **cleaned}
        frames = {name: combined, **frames}

    try:
        store.drop_expired()
    except Exception as error:
        print(f"Expiry sweep skipped: {error}", flush=True)

    workspace = store.create_workspace(frames, relationships=relationships)

    st.session_state[STATE] = {
        "file": ", ".join(u.name for u in uploads),
        "file_id": "|".join(f"{u.name}:{u.size}" for u in uploads),
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
    uploads = st.file_uploader(
        "Upload CSV or Excel (you can select several related files)",
        type=["csv", "tsv", "txt", "xlsx"], accept_multiple_files=True, key=uploader_key,
    )
    file_id = "|".join(f"{u.name}:{u.size}" for u in uploads)

    state = st.session_state.get(STATE)

    if uploads and (state is None or state["file_id"] != file_id):
        _reset()

        with st.spinner("Reading and cleaning your file(s)..."):
            try:
                _load(uploads)
            except ingest.UploadError as error:
                st.error(str(error))
                return
            except Exception as error:
                st.error(f"Could not process this file: {error}")
                return

        state = st.session_state[STATE]

    if not uploads and state is not None:
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

    if workspace.relationships:
        with st.expander(f"🔗 {len(workspace.relationships)} relationship(s) detected between your files"):
            for rel in workspace.relationships:
                st.markdown(f"- {rel.describe()}")

                if rel.orphan_rows:
                    st.caption(
                        f"  {rel.orphan_rows:,} row(s) in {rel.many_table} have a "
                        f"{rel.many_column} that does not exist in {rel.key_table}."
                    )

            st.caption("The 'combined' table joins everything onto the largest table. Questions can use any table.")

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
