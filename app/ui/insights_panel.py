"""Streamlit panel: automatic findings and a small statistical test runner."""

import streamlit as st

from app.workspace import insights
from app.workspace.profile import by_role


@st.cache_data(show_spinner=False, max_entries=8)
def _findings(key, _frame, _profiles):
    return insights.find_insights(_frame, _profiles)


def _show(result):
    if result is None:
        st.warning("Not enough data in these columns to run this test.")
        return

    (st.success if result.significant else st.info)(result.verdict)

    for note in result.notes:
        st.caption(note)


def _test_runner(name, frame, profiles):
    numeric = [c for c in by_role(profiles, "numeric") if frame[c].nunique() > 2]
    categories = [c for c in by_role(profiles, "category") if 2 <= frame[c].nunique() <= 50]
    kinds = []

    if numeric and categories:
        kinds += ["Compare groups", "A/B test (two groups)"]
    if len(numeric) >= 2:
        kinds.append("Correlation")
    if len(categories) >= 2:
        kinds.append("Association (two categories)")

    if not kinds:
        st.caption("This file needs numeric and category columns for statistical tests.")
        return

    kind = st.selectbox("Test", kinds, key=f"{name}_test_kind")
    key = f"{name}_{kind}"

    if kind == "Compare groups":
        measure = st.selectbox("Measure (number)", numeric, key=f"{key}_m")
        group = st.selectbox("Grouped by", categories, key=f"{key}_g")
        st.caption("Does the average of the measure differ between groups? (t-test or ANOVA)")

        if st.button("Run test", key=f"{key}_run"):
            _show(insights.compare_groups(frame, measure, group))

    elif kind == "A/B test (two groups)":
        group = st.selectbox("Group column", categories, key=f"{key}_g")
        metric = st.selectbox("Metric (number)", numeric, key=f"{key}_m")
        values = sorted(frame[group].dropna().astype(str).unique())
        first, second = st.columns(2)
        a = first.selectbox("Control (A)", values, key=f"{key}_a")
        b = second.selectbox("Variant (B)", values, index=min(1, len(values) - 1), key=f"{key}_b")

        if st.button("Run test", key=f"{key}_run"):
            if a == b:
                st.warning("Pick two different groups.")
            else:
                column = frame[group].astype(str)
                _show(insights.ab_test(frame.assign(**{group: column}), group, metric, a, b))

    elif kind == "Correlation":
        first = st.selectbox("First number", numeric, key=f"{key}_a")
        second = st.selectbox("Second number", numeric, index=min(1, len(numeric) - 1), key=f"{key}_b")

        if st.button("Run test", key=f"{key}_run"):
            if first == second:
                st.warning("Pick two different columns.")
            else:
                _show(insights.correlate(frame, first, second))

    else:
        first = st.selectbox("First category", categories, key=f"{key}_a")
        second = st.selectbox("Second category", categories, index=min(1, len(categories) - 1), key=f"{key}_b")

        if st.button("Run test", key=f"{key}_run"):
            if first == second:
                st.warning("Pick two different columns.")
            else:
                _show(insights.association(frame, first, second))


def render(name, source, result, profiles):
    frame = result.frame
    st.markdown("**Automatic findings**")
    st.caption(
        "Found by statistical checks on your data, not written by an AI model, "
        "so every number can be verified. Small or trivial differences are left out."
    )

    found = _findings(f"{source}:{name}:{len(frame)}", frame, profiles)

    if not found:
        st.info("No strong pattern stood out. Try a statistical test below.")

    for item in found:
        st.markdown(f"- **{item.title}.** {item.detail}")

    st.markdown("---")
    st.markdown("**Run a statistical test**")
    _test_runner(name, frame, profiles)
