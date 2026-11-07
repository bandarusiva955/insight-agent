"""KPI dashboard tab: filters, metric cards, trend and breakdowns."""

import plotly.express as px
import streamlit as st

from app.analytics.kpi import KpiFilters
from app.metrics import METRIC_NOTE
from app.ui import cache


def _money(value):
    return "n/a" if value is None else f"R$ {value:,.0f}"


def _pct(value):
    return "n/a" if value is None else f"{value:.1%}"


def _delta(delta, key, invert=False):
    value = delta.get(key)

    if value is None:
        return None, "off"

    return f"{value:+.1%}", ("inverse" if invert else "normal")


def render():
    options = cache.filter_options()

    first, last = options["first_day"], options["last_day"]

    with st.expander("Filters", expanded=True):
        left, middle, right = st.columns([2, 3, 3])
        picked = left.date_input(
            "Date range", value=(first, last), min_value=first, max_value=last
        )
        categories = middle.multiselect("Categories", options["categories"])
        states = right.multiselect("States", options["states"])

    if not isinstance(picked, tuple) or len(picked) != 2:
        st.info("Pick both a start and an end date.")
        return

    filters = KpiFilters(
        date_from=picked[0],
        date_to=picked[1],
        categories=tuple(categories),
        states=tuple(states),
    )

    result = cache.kpis_with_delta(filters)
    current, delta = result["current"], result["delta"]

    if not current["orders"]:
        st.warning("No delivered orders match these filters.")
        return

    st.caption(
        "Deltas compare with the previous period of the same length. "
        + METRIC_NOTE
    )

    cards = st.columns(6)
    spec = [
        ("Revenue", _money(current["revenue"]), "revenue", False),
        ("Orders", f"{current['orders']:,}", "orders", False),
        ("Avg order value", _money(current["aov"]), "aov", False),
        (
            "Avg delivery (days)",
            "n/a" if current["avg_delivery_days"] is None
            else f"{current['avg_delivery_days']:.1f}",
            "avg_delivery_days",
            True,
        ),
        ("On-time rate", _pct(current["on_time_rate"]), "on_time_rate", False),
        ("Cancel rate", _pct(current["cancel_rate"]), "cancel_rate", True),
    ]

    for column, (label, value, key, invert) in zip(cards, spec):
        change, color = _delta(delta, key, invert)
        column.metric(label, value, change, delta_color=color)

    trend = cache.monthly_trend(filters)

    if len(trend):
        figure = px.line(trend, x="month", y="revenue", markers=True,
                         title="Monthly revenue (R$)")
        st.plotly_chart(figure, width="stretch")

    left, right = st.columns(2)

    categories_frame = cache.top_categories(filters, 10)
    if len(categories_frame):
        figure = px.bar(
            categories_frame.sort_values("revenue"),
            x="revenue", y="category", orientation="h",
            title="Top categories by revenue (R$)",
        )
        left.plotly_chart(figure, width="stretch")

    states_frame = cache.state_breakdown(filters)
    if len(states_frame):
        figure = px.bar(
            states_frame.sort_values("revenue", ascending=False).head(10),
            x="state", y="revenue", title="Top states by revenue (R$)",
        )
        right.plotly_chart(figure, width="stretch")

    payments = cache.payment_mix(filters)
    if len(payments):
        figure = px.pie(payments, names=payments.columns[0],
                        values="payment_value", title="Payment mix")
        st.plotly_chart(figure, width="stretch")
