import sys
from pathlib import Path

# Lets `streamlit run app/ui/dashboard.py` import the app package from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app.ui import (  # noqa: E402
    ask_tab, forecast_tab, kpi_tab, live_tab, rca_tab, usage_tab, workspace_tab,
)
from app.ui.access import require_access  # noqa: E402

st.set_page_config(
    page_title="InsightAgent | AI Data Analyst",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-title { font-size: 2.2rem; font-weight: 750; margin-bottom: 0; }
    .subtitle { color: #94a3b8; font-size: 1rem; margin-top: 4px; }
    </style>
    """,
    unsafe_allow_html=True,
)

require_access()

if "query_history" not in st.session_state:
    st.session_state.query_history = []

with st.sidebar:
    st.title("📊 InsightAgent")
    st.caption("AI-powered data analysis")
    st.divider()
    st.write(
        "Ask business questions in plain English, explore KPIs, find out why "
        "revenue changed, spot anomalies and monitor a live order stream."
    )
    st.divider()
    st.subheader("Example questions")
    for example in [
        "Show me the top 10 product categories by delivered sales.",
        "Now break that down by state.",
        "What is the monthly order trend?",
        "Which payment method is used most frequently?",
        "What is the average delivery time by state?",
    ]:
        st.markdown(f"- {example}")
    st.divider()
    st.caption("Gemini + PostgreSQL + Streamlit. Read-only, audited queries.")

st.markdown('<p class="main-title">📊 InsightAgent</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">AI data analyst: questions, KPIs, root causes, '
    "forecasts and live alerts</p>",
    unsafe_allow_html=True,
)

tabs = st.tabs(
    ["💬 Ask", "📁 My data", "📈 KPI dashboard", "🔎 Root cause", "🔮 Forecast & anomalies",
     "🚨 Live monitor", "🧾 Usage"]
)

for tab, module in zip(
    tabs,
    [ask_tab, workspace_tab, kpi_tab, rca_tab, forecast_tab, live_tab, usage_tab],
):
    with tab:
        module.render()
