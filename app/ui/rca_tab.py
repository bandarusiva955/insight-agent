"""Root-cause tab: why did revenue change between two months?"""

import streamlit as st

from app.analytics.kpi import KpiFilters
from app.analytics.rca import (
    explain_change,
    largest_monthly_changes,
    month_window,
    previous_month_window,
)
from app.llm.narrator import narrate_rca, narration_allowed
from app.ui import cache


def render():
    st.subheader("Why did revenue change?")
    st.caption(
        "Compares a month with the month before it and breaks the change down "
        "by category, state and operations. The findings are computed "
        "deterministically from your data; they show associations, not proof "
        "of cause."
    )

    trend = cache.monthly_trend(KpiFilters())

    if len(trend) < 3:
        st.info("Not enough monthly history for root-cause analysis.")
        return

    worst = largest_monthly_changes(trend, top=3)

    if len(worst):
        st.markdown("**Biggest month-over-month drops (suggested)**")
        for _, row in worst.iterrows():
            st.write(f"- {row['month']:%b %Y}: {row['change_pct']:+.1%}")

    months = [m for m in trend.sort_values("month")["month"]][1:]
    labels = {m: f"{m:%b %Y}" for m in months}
    default = worst.loc[0, "month"] if len(worst) else months[-1]

    options = cache.filter_options()
    left, middle, right = st.columns(3)
    month = left.selectbox(
        "Month to explain",
        months,
        index=months.index(default) if default in months else len(months) - 1,
        format_func=labels.get,
    )
    states = middle.multiselect("Limit to states", options["states"], key="rca_states")
    categories = right.multiselect(
        "Limit to categories", options["categories"], key="rca_categories"
    )

    current = month_window(month.year, month.month)
    baseline = previous_month_window(current)
    filters = KpiFilters(categories=tuple(categories), states=tuple(states))

    report = explain_change(current, baseline, filters)

    if report.change_pct is not None:
        st.metric(
            f"Revenue {current.label} vs {baseline.label}",
            f"R$ {report.current_kpis['revenue']:,.0f}",
            f"{report.change_pct:+.1%}",
        )

    for finding in report.findings:
        st.markdown(f"- {finding}")

    with st.expander("Driver tables"):
        st.markdown("**Categories**")
        st.dataframe(report.categories, use_container_width=True, hide_index=True)
        st.markdown("**States**")
        st.dataframe(report.states, use_container_width=True, hide_index=True)
        st.markdown("**Operations**")
        st.dataframe(report.operations, use_container_width=True, hide_index=True)

    if narration_allowed():
        if st.button("Explain in plain English (uses Gemini)"):
            with st.spinner("Writing summary..."):
                text, used_llm = narrate_rca(report)
            st.info(text)
            if not used_llm:
                st.caption("AI summary unavailable; showing the computed findings.")
    else:
        st.caption("AI narration is disabled (PRIVACY_MODE=strict).")
