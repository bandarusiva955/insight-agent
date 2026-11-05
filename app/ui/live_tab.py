"""Live monitor tab: simulated order stream with threshold alerts."""

import random

import plotly.express as px
import streamlit as st

from app.live import (
    INCIDENTS,
    dispatch_alerts,
    evaluate_alerts,
    live_snapshot,
    per_minute_series,
    recent_orders,
    seed_baseline,
    simulate_batch,
)

REFRESH_SECONDS = 5


def _controls():
    st.caption(
        "A simulated order stream (clearly separate from the real dataset) "
        "feeds this monitor. Seed a baseline, add traffic, then trigger an "
        "incident to watch the alerts fire."
    )

    first, second, third = st.columns(3)

    if first.button("1. Seed 1h baseline"):
        written = seed_baseline()
        st.toast(f"Seeded {written} baseline orders")

    if second.button("2. Add normal traffic (+40)"):
        simulate_batch(40, rng=random.Random())

    incident = third.selectbox("Incident", [i for i in INCIDENTS if i != "none"])

    if third.button("3. Trigger incident (+60)"):
        simulate_batch(60, incident=incident, rng=random.Random())


@st.fragment(run_every=REFRESH_SECONDS)
def _monitor():
    snapshot = live_snapshot()
    window, baseline = snapshot["window"], snapshot["baseline"]

    a, b, c, d = st.columns(4)
    a.metric("Orders / min (last 5 min)", f"{window['orders_per_min']:.1f}",
             f"baseline {baseline['orders_per_min']:.1f}", delta_color="off")
    b.metric("Revenue (last 5 min)", f"R$ {window['revenue']:,.0f}")
    cancel = window["cancel_rate"]
    c.metric("Cancel rate", "n/a" if cancel is None else f"{cancel:.1%}")
    delivery = window["avg_delivery_days"]
    d.metric("Avg delivery days", "n/a" if delivery is None else f"{delivery:.1f}")

    alerts = evaluate_alerts(snapshot)

    if alerts:
        for alert in alerts:
            st.error(f"**{alert.severity.upper()}**: {alert.message}")

        if st.session_state.get("live_alerts_on", True):
            dispatch_alerts(alerts)
    else:
        st.success("All metrics within normal range.")

    series = per_minute_series()
    if len(series):
        st.plotly_chart(px.bar(series, x="minute", y="orders",
                               title="Orders per minute"),
                        use_container_width=True)

    st.markdown("**Latest orders**")
    st.dataframe(recent_orders(), use_container_width=True, hide_index=True)


def render():
    _controls()
    st.toggle(
        "Send alerts (Telegram if configured, otherwise console)",
        value=True,
        key="live_alerts_on",
    )
    _monitor()
