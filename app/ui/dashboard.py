import streamlit as st

from app.metrics import METRIC_NOTE
from app.pipeline import run_pipeline_detailed
from app.ui.formatting import style_results


st.set_page_config(
    page_title="InsightAgent | AI Data Analyst",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
    .stApp {
        background-color: #0b1120;
    }

    .main-title {
        font-size: 2.5rem;
        font-weight: 750;
        color: #f8fafc;
        margin-bottom: 0;
    }

    .subtitle {
        color: #94a3b8;
        font-size: 1rem;
        margin-top: 5px;
    }

    .section-title {
        color: #e2e8f0;
        font-weight: 650;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


if "query_history" not in st.session_state:
    st.session_state.query_history = []


with st.sidebar:
    st.title("📊 InsightAgent")
    st.caption("AI-powered data analysis")

    st.divider()

    st.subheader("About")
    st.write(
        "Ask business questions in plain English. "
        "InsightAgent converts them into SQL and analyzes your data."
    )

    st.divider()

    st.subheader("Example questions")

    examples = [
        "Show me the top 10 product categories by sales.",
        "What is the monthly order trend?",
        "What are the different order statuses?",
        "Which payment method is used most frequently?",
        "What is the average delivery time?",
    ]

    for example in examples:
        st.markdown(f"- {example}")

    st.divider()
    st.caption("Powered by Gemini + PostgreSQL + Streamlit")


st.markdown(
    '<p class="main-title">InsightAgent</p>',
    unsafe_allow_html=True,
)

st.markdown(
    '<p class="subtitle">Your AI-powered business data analyst</p>',
    unsafe_allow_html=True,
)

st.divider()

st.markdown(
    '<h3 class="section-title">Ask your data a question</h3>',
    unsafe_allow_html=True,
)

question = st.text_area(
    "Enter your business question",
    placeholder="Example: Show me the top 10 product categories by delivered sales.",
    height=110,
)

run_button = st.button(
    "🚀 Generate Analysis",
    type="primary",
    use_container_width=True,
)

if run_button:

    if not question.strip():
        st.warning("Please enter a business question.")

    else:
        with st.spinner(
            "Analyzing your question and generating SQL..."
        ):
            try:
                result = run_pipeline_detailed(question)

                st.session_state.query_history.append(
                    {
                        "question": question,
                        "sql": result.sql,
                        "results": result.dataframe,
                        "attempts": result.attempts,
                        "latency_ms": result.latency_ms,
                    }
                )

                st.success("Analysis completed successfully!")

            except Exception as error:
                st.error(f"Analysis failed: {error}")


if st.session_state.query_history:

    latest = st.session_state.query_history[-1]

    st.divider()
    st.markdown("### Generated SQL")

    st.code(latest["sql"], language="sql")

    st.caption(METRIC_NOTE)

    if latest.get("attempts", 1) > 1:
        st.caption(
            f"The first SQL attempt failed, so the query was automatically "
            f"corrected (attempt {latest['attempts']})."
        )

    if latest.get("latency_ms") is not None:
        st.caption(f"Completed in {latest['latency_ms'] / 1000:.1f}s.")

    dataframe = latest["results"]

    st.markdown("### Query Results")

    if dataframe.empty:
        st.info("The query returned no records.")

    else:
        st.dataframe(
            style_results(dataframe),
            use_container_width=True,
            hide_index=True,
        )

        if dataframe.attrs.get("truncated", False):
            st.warning(
                "Results were limited to the first 1,000 rows."
            )

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
                use_container_width=True
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
            reversed(st.session_state.query_history),
            start=1,
        ):
            st.markdown(f"**{index}. {item['question']}**")

