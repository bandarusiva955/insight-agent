"""Usage tab: how the system is performing, from the audit log."""

import streamlit as st

from app.usage import recent_alerts, recent_queries, usage_summary


def render():
    summary = usage_summary()

    if not summary["total"]:
        st.info("No questions logged yet. Ask something in the Ask tab.")
    else:
        a, b, c, d = st.columns(4)
        a.metric("Questions", summary["total"])
        rate = summary["success_rate"]
        b.metric("Answered", "n/a" if rate is None else f"{rate:.0%}",
                 f"{summary['corrected']} self-corrected", delta_color="off")
        avg = summary["avg_latency_ms"]
        c.metric("Avg latency", "n/a" if avg is None else f"{avg / 1000:.1f}s")
        p95 = summary["p95_latency_ms"]
        d.metric("p95 latency", "n/a" if p95 is None else f"{p95 / 1000:.1f}s")

        st.caption(
            "'Answered' means the query ran, not that it is semantically "
            "correct. Measured accuracy comes from the benchmark in "
            "evaluation/."
        )

        st.markdown("**Recent questions**")
        st.dataframe(recent_queries(), use_container_width=True, hide_index=True)

    st.markdown("**Recent alerts**")
    alerts = recent_alerts()
    if len(alerts):
        st.dataframe(alerts, use_container_width=True, hide_index=True)
    else:
        st.caption("No alerts yet.")
