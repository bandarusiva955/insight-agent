"""Streamlit panel: RFM customer segments and cohort retention."""

import plotly.express as px
import streamlit as st

from app.workspace import customers

SEGMENT_HELP = {
    "Champions": "Bought recently and often. Reward and keep them.",
    "Loyal": "Buy often. Offer loyalty perks and upsells.",
    "New": "Recent but few orders. Help them place a second order.",
    "Needs attention": "Middling recency and frequency. Remind them with an offer.",
    "At risk": "Used to buy often but have gone quiet. Win them back now.",
    "Lost": "Long silent and low activity. Cheap re-engagement only.",
}


@st.cache_data(show_spinner=False, max_entries=8)
def _analyse(key, _frame, _profiles):
    columns = customers.detect_columns(_frame, _profiles)

    if columns is None:
        return None

    table, summary = customers.rfm(_frame, columns)

    if table is None:
        return None

    return columns, table, summary, customers.cohort_retention(_frame, columns)


def render(name, source, result, profiles):
    frame = result.frame
    analysis = _analyse(f"{source}:{name}:{len(frame)}", frame, profiles)

    if analysis is None:
        st.info(
            "Customer analytics needs a customer ID column, a date column and either an "
            "amount column or price (and quantity) columns, with at least 20 customers. "
            "Upload related files (orders + customers + products) to get a 'combined' table."
        )
        return

    columns, table, summary, retention = analysis
    st.caption(
        f"Customer = {columns.customer}, date = {columns.date}, value = {columns.amount_name}. "
        f"{len(table):,} customers."
    )

    for line in customers.headline(table, summary):
        st.markdown(f"- {line}")

    st.markdown("**Customer segments (RFM)**")
    st.caption(
        "Each customer is scored 1-5 on Recency (how recently they bought), Frequency (how many "
        "orders) and Monetary value (total spend), then grouped into segments."
    )
    chart = summary.melt(
        id_vars="segment", value_vars=["customer_share", "revenue_share"],
        var_name="measure", value_name="share",
    ).replace({"customer_share": "Share of customers", "revenue_share": "Share of revenue"})
    figure = px.bar(chart, x="segment", y="share", color="measure", barmode="group",
                    category_orders={"segment": list(summary["segment"])})
    figure.update_yaxes(tickformat=".0%", title=None)
    figure.update_xaxes(title=None)
    figure.update_layout(legend_title=None, margin=dict(t=10, b=10))
    st.plotly_chart(figure, width="stretch")

    display = summary.rename(columns={
        "segment": "Segment", "customers": "Customers", "revenue": "Revenue",
        "avg_orders": "Avg orders", "avg_days_since_last": "Avg days since last order",
        "customer_share": "% customers", "revenue_share": "% revenue",
    })
    st.dataframe(
        display, width="stretch", hide_index=True,
        column_config={
            "Revenue": st.column_config.NumberColumn(format="%.0f"),
            "Avg orders": st.column_config.NumberColumn(format="%.1f"),
            "Avg days since last order": st.column_config.NumberColumn(format="%.0f"),
            "% customers": st.column_config.NumberColumn(format="percent"),
            "% revenue": st.column_config.NumberColumn(format="percent"),
        },
    )

    with st.expander("What each segment means and what to do"):
        for segment in summary["segment"]:
            st.markdown(f"- **{segment}:** {SEGMENT_HELP[segment]}")

    pick = st.selectbox("Download a segment's customer list", ["All"] + list(summary["segment"]),
                        key=f"{name}_segment_pick")
    export = table if pick == "All" else table[table["segment"] == pick]
    st.download_button(
        f"Download {pick.lower()} customers (CSV)",
        export.rename(columns={"customer": columns.customer}).to_csv(index=False).encode(),
        file_name=f"customers_{pick.lower().replace(' ', '_')}.csv", mime="text/csv",
        key=f"{name}_segment_dl",
    )

    st.markdown("---")
    st.markdown("**Cohort retention**")

    if retention is None:
        st.caption("Not enough months of data with 20+ new customers to show cohorts.")
        return

    st.caption(
        "Each row is the group of customers who first bought in that month. Each column shows "
        "the share of them who bought again N months later."
    )
    heat = retention.drop(columns="customers")
    heat.columns = [f"Month {c}" for c in heat.columns]
    figure = px.imshow(heat, text_auto=".0%", aspect="auto", color_continuous_scale="Blues", zmin=0, zmax=1)
    figure.update_layout(coloraxis_showscale=False, margin=dict(t=10, b=10))
    st.plotly_chart(figure, width="stretch")
