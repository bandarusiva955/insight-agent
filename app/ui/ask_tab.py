"""Ask tab: natural-language questions, SQL, results, chart and insights."""

import streamlit as st

from app.llm.narrator import narration_allowed, summarize_results
from app.metrics import METRIC_NOTE
from app.pipeline import run_pipeline_detailed
from app.ui.access import budget_for_session
from app.ui.errors import friendly_error
from app.ui.formatting import style_results

HISTORY_TURNS_SENT = 3


def render(workspace=None, state_key: str = "query_history", key_prefix: str = "") -> None:
    """Ask tab. With a workspace, questions run only on the uploaded data."""

    st.session_state.setdefault(state_key, [])

    st.markdown(
        '<h3 class="section-title">Ask your data a question</h3>',
        unsafe_allow_html=True,
    )

    question = st.text_area(
        "Enter your business question",
        placeholder=(
            "Example: Which region has the highest total amount?"
            if workspace is not None
            else "Example: Show me the top 10 product categories by delivered sales."
        ),
        height=110,
        key=f"{key_prefix}question",
    )

    use_context = st.toggle(
        "Use my previous questions as context (for follow-ups like "
        "\"now break that down by state\")",
        value=True,
        key=f"{key_prefix}use_context",
    )

    run_button = st.button(
        "🚀 Generate Analysis",
        type="primary",
        width="stretch",
        key=f"{key_prefix}run",
    )

    budget = budget_for_session()

    if run_button:

        if not question.strip():
            st.warning("Please enter a business question.")

        elif not budget.allow():
            st.error(
                f"This session has reached its limit of {budget.limit} "
                "questions. Reload the page to start a new session."
            )

        else:
            history = (
                [
                    {"question": turn["question"], "sql": turn["sql"]}
                    for turn in st.session_state[state_key][
                        -HISTORY_TURNS_SENT:
                    ]
                ]
                if use_context
                else []
            )

            with st.spinner(
                "Analyzing your question and generating SQL..."
            ):
                try:
                    result = run_pipeline_detailed(
                        question, history=history, workspace=workspace
                    )

                    st.session_state[state_key].append(
                        {
                            "question": question,
                            "sql": result.sql,
                            "results": result.dataframe,
                            "attempts": result.attempts,
                            "latency_ms": result.latency_ms,
                            "used_context": len(history),
                        }
                    )

                    st.success("Analysis completed successfully!")

                except Exception as error:
                    st.error(friendly_error(error))


    if st.session_state[state_key]:

        latest = st.session_state[state_key][-1]

        st.divider()
        st.markdown("### Generated SQL")

        st.code(latest["sql"], language="sql")

        if workspace is None:
            st.caption(METRIC_NOTE)

        if latest.get("attempts", 1) > 1:
            st.caption(
                f"The first SQL attempt failed, so the query was automatically "
                f"corrected (attempt {latest['attempts']})."
            )

        if latest.get("used_context"):
            st.caption(
                f"Used {latest['used_context']} earlier question(s) as context."
            )

        if latest.get("latency_ms") is not None:
            st.caption(f"Completed in {latest['latency_ms'] / 1000:.1f}s.")

        dataframe = latest["results"]

        st.markdown("### Query Results")

        if dataframe.empty:
            st.info("The query returned no records.")

        else:
            st.dataframe(
                style_results(dataframe, currency=workspace is None),
                width="stretch",
                hide_index=True,
            )

            if dataframe.attrs.get("truncated", False):
                st.warning(
                    "Results were limited to the first 1,000 rows."
                )

            if narration_allowed():
                with st.expander("AI summary (optional)"):
                    st.caption(
                        "Sends the first rows of this result to Gemini to "
                        "write a plain-English summary."
                    )

                    summary_key = f"summary::{latest['question']}::{len(dataframe)}"

                    if st.button("Write summary", key=f"{key_prefix}write_summary"):
                        with st.spinner("Summarising..."):
                            st.session_state[summary_key] = summarize_results(
                                latest["question"], dataframe
                            )

                    if summary_key in st.session_state:
                        text, used_llm = st.session_state[summary_key]
                        st.write(text)

                        if not used_llm:
                            st.caption("AI summary unavailable; showing basics.")

            st.markdown("### Automatic Visualization")

            import plotly.express as px
            import pandas as pd
            from decimal import Decimal
            from numbers import Number

            chart_data = dataframe.copy()

            # Detect Decimal and other numeric values returned by PostgreSQL.
            numeric_columns = []

            for column in chart_data.columns:
                values = chart_data[column].dropna()

                if len(values) > 0 and all(
                    isinstance(value, (Number, Decimal))
                    and not isinstance(value, bool)
                    for value in values
                ):
                    numeric_columns.append(column)
                    chart_data[column] = pd.to_numeric(
                        chart_data[column], errors="coerce"
                    )

            category_columns = [
                column for column in chart_data.columns
                if column not in numeric_columns
            ]

            question_lower = latest["question"].lower()

            date_columns = [
                column for column in category_columns
                if any(word in column.lower()
                       for word in ["date", "month", "year", "time"])
            ]

            if numeric_columns and category_columns:

                if (
                    any(word in question_lower
                        for word in ["relationship", "correlation"])
                    and len(numeric_columns) >= 2
                ):
                    suggested_chart = "Scatter"

                elif date_columns:
                    suggested_chart = "Line"

                elif any(word in question_lower for word in [
                    "distribution", "percentage", "proportion", "share"
                ]):
                    suggested_chart = "Pie"

                else:
                    suggested_chart = "Bar"

                selected_chart = st.selectbox(
                    "Chart type",
                    ["Automatic", "Bar", "Line", "Pie", "Scatter"],
                    key="chart_type"
                )

                chart_type = (
                    suggested_chart
                    if selected_chart == "Automatic"
                    else selected_chart
                )

                if chart_type == "Scatter" and len(numeric_columns) >= 2:

                    x_column = st.selectbox(
                        "X-axis",
                        numeric_columns,
                        key="scatter_x"
                    )

                    y_options = [
                        column for column in numeric_columns
                        if column != x_column
                    ]

                    y_column = st.selectbox(
                        "Y-axis",
                        y_options,
                        key="scatter_y"
                    )

                    figure = px.scatter(
                        chart_data,
                        x=x_column,
                        y=y_column,
                        title=f"{y_column} vs {x_column}",
                        template="plotly_dark"
                    )

                else:

                    x_options = date_columns + [
                        column for column in category_columns
                        if column not in date_columns
                    ]

                    x_column = st.selectbox(
                        "Category / X-axis",
                        x_options,
                        key="chart_category"
                    )

                    y_column = st.selectbox(
                        "Metric / Y-axis",
                        numeric_columns,
                        key="chart_metric"
                    )

                    if chart_type == "Pie":
                        figure = px.pie(
                            chart_data,
                            names=x_column,
                            values=y_column,
                            title=f"{y_column} distribution",
                            template="plotly_dark"
                        )

                    elif chart_type == "Line":
                        line_data = chart_data.copy()

                        if x_column in date_columns:
                            line_data[x_column] = pd.to_datetime(
                                line_data[x_column], errors="coerce"
                            )
                            line_data = line_data.sort_values(x_column)

                        figure = px.line(
                            line_data,
                            x=x_column,
                            y=y_column,
                            markers=True,
                            title=f"{y_column} over {x_column}",
                            template="plotly_dark"
                        )

                    else:
                        figure = px.bar(
                            chart_data,
                            x=x_column,
                            y=y_column,
                            title=f"{y_column} by {x_column}",
                            template="plotly_dark"
                        )

                figure.update_layout(
                    height=480,
                    margin=dict(l=20, r=20, t=60, b=40)
                )

                st.plotly_chart(
                    figure,
                    width="stretch"
                )

                # Deterministic business insights from returned query results.
                st.markdown("### Business Insights")

                if category_columns and numeric_columns:

                    insight_category = category_columns[0]
                    insight_metric = numeric_columns[0]

                    ranked = chart_data.dropna(
                        subset=[insight_category, insight_metric]
                    ).sort_values(
                        insight_metric, ascending=False
                    )

                    if not ranked.empty:

                        top_row = ranked.iloc[0]
                        top_name = str(top_row[insight_category])
                        top_value = float(top_row[insight_metric])

                        st.metric(
                            f"Highest {insight_metric}",
                            f"{top_value:,.2f}",
                            help=f"Category: {top_name}"
                        )

                        st.write(
                            f"**Top performer:** {top_name} "
                            f"has the highest {insight_metric} "
                            f"at {top_value:,.2f}."
                        )

                        total = chart_data[insight_metric].sum()

                        if total > 0:
                            share = (top_value / total) * 100

                            st.write(
                                f"**Share of displayed results:** "
                                f"{share:.2f}% comes from {top_name}."
                            )

                        if len(ranked) >= 2:
                            second_row = ranked.iloc[1]

                            st.write(
                                f"**Second highest:** "
                                f"{second_row[insight_category]} "
                                f"({float(second_row[insight_metric]):,.2f})."
                            )

                        st.caption(
                            "Insights describe the returned query results, "
                            "not necessarily the entire database."
                        )

            elif numeric_columns:
                st.info(
                    "Numeric results are available, but a category "
                    "column is needed for this visualization."
                )

            else:
                st.info(
                    "No numeric columns were detected in the query results."
                )

        with st.expander("Previous questions"):
            for index, item in enumerate(
                reversed(st.session_state[state_key]),
                start=1,
            ):
                st.markdown(f"**{index}. {item['question']}**")

            if st.button("Clear conversation", key=f"{key_prefix}clear_history"):
                st.session_state[state_key] = []
                st.rerun()


