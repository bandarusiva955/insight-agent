"""Cached wrappers so switching tabs or widgets does not re-run heavy queries."""

import streamlit as st

from app.analytics import kpi

TTL_SECONDS = 300


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def filter_options():
    return kpi.get_filter_options()


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def kpis_with_delta(filters):
    return kpi.get_kpis_with_delta(filters)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def monthly_trend(filters):
    return kpi.get_monthly_trend(filters)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def daily_metrics(filters):
    return kpi.get_daily_metrics(filters)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def top_categories(filters, limit=10):
    return kpi.get_top_categories(filters, limit)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def state_breakdown(filters):
    return kpi.get_state_breakdown(filters)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def payment_mix(filters):
    return kpi.get_payment_mix(filters)
