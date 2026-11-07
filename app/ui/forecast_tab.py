"""Anomaly detection and forecasting tab."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.analytics.anomaly import describe_anomalies, detect_anomalies
from app.analytics.forecast import forecast_series, trim_partial_months
from app.analytics.kpi import KpiFilters
from app.ui import cache


def _anomalies():
    st.subheader("Anomaly detection")

    metric = st.selectbox(
        "Metric",
        ["revenue", "orders", "cancel_rate"],
        format_func=lambda m: {
            "revenue": "Daily revenue",
            "orders": "Daily delivered orders",
            "cancel_rate": "Daily cancel rate",
        }[m],
    )
    threshold = st.slider("Sensitivity threshold (higher = fewer alerts)", 3.0, 8.0, 4.5, 0.5)

    daily = cache.daily_metrics(KpiFilters())
    daily = daily.dropna(subset=[metric])

    if len(daily) < 14:
        st.info("Not enough daily history.")
        return

    flagged = detect_anomalies(daily, metric, "day", threshold=threshold)
    hits = flagged[flagged["is_anomaly"]]

    figure = go.Figure()
    figure.add_scatter(x=flagged["day"], y=flagged[metric], mode="lines", name=metric)
    figure.add_scatter(x=flagged["day"], y=flagged["baseline"], mode="lines",
                       name="rolling baseline", line=dict(dash="dot"))
    figure.add_scatter(x=hits["day"], y=hits[metric], mode="markers",
                       name="anomaly", marker=dict(size=10, color="red"))
    st.plotly_chart(figure, width="stretch")

    lines = describe_anomalies(flagged, metric, metric.replace("_", " "))

    if lines:
        for line in lines:
            st.markdown(f"- {line}")
    else:
        st.success("No anomalies at this sensitivity.")


def _forecast():
    st.subheader("Revenue forecast")

    trend = cache.monthly_trend(KpiFilters())
    series = pd.Series(
        trend["revenue"].astype(float).to_numpy(),
        index=pd.to_datetime(trend["month"]),
    )
    series = trim_partial_months(series)

    periods = st.slider("Months ahead", 1, 6, 3)

    try:
        result = forecast_series(series, periods=periods)
    except ValueError as error:
        st.info(str(error))
        return

    figure = go.Figure()
    figure.add_scatter(x=result.history.index, y=result.history.values,
                       mode="lines+markers", name="actual")
    forecast = result.forecast
    figure.add_scatter(x=forecast["month"], y=forecast["upper"], mode="lines",
                       line=dict(width=0), showlegend=False)
    figure.add_scatter(x=forecast["month"], y=forecast["lower"], mode="lines",
                       line=dict(width=0), fill="tonexty", name="range")
    figure.add_scatter(x=forecast["month"], y=forecast["forecast"],
                       mode="lines+markers", name="forecast", line=dict(dash="dash"))
    st.plotly_chart(figure, width="stretch")

    st.caption(result.note)

    if result.beats_naive is False:
        st.warning(
            "In backtesting this model did not beat a simple 'same as last "
            "month' baseline, so treat the forecast with caution."
        )


def render():
    _anomalies()
    st.divider()
    _forecast()
