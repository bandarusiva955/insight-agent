"""KPI queries for the dashboard.

Definitions (also shown in the UI):
* revenue = SUM(item price) of delivered orders, freight excluded
* orders = distinct delivered orders
* AOV = revenue / orders
* delivery days = purchase -> delivered to customer, delivered orders only
* on-time rate = share of delivered orders delivered on or before the estimate
* cancel rate = canceled orders / all orders in the selection
* review score = average review score of delivered orders
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta

import pandas as pd

from app.db.runner import run_query


@dataclass(frozen=True)
class KpiFilters:
    """Hashable, so dashboards can cache results per filter combination."""

    date_from: date | None = None
    date_to: date | None = None  # inclusive
    categories: tuple = ()
    states: tuple = ()


_RAW = """
raw AS (
    SELECT
        o.order_id,
        o.order_status,
        o.order_purchase_timestamp AS purchased_at,
        o.order_delivered_customer_date AS delivered_at,
        o.order_estimated_delivery_date AS estimated_at,
        c.customer_state AS state,
        COALESCE(
            ct.product_category_name_english,
            p.product_category_name,
            'unknown'
        ) AS category,
        oi.price,
        oi.freight_value
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    JOIN order_items oi ON oi.order_id = o.order_id
    JOIN products p ON p.product_id = oi.product_id
    LEFT JOIN category_translation ct
        ON ct.product_category_name = p.product_category_name
)
"""

_ORDER_LEVEL = """
order_level AS (
    SELECT
        order_id, order_status, purchased_at, delivered_at, estimated_at,
        state,
        SUM(price) AS revenue,
        SUM(freight_value) AS freight
    FROM item_base
    GROUP BY order_id, order_status, purchased_at, delivered_at,
             estimated_at, state
)
"""


def _with_clause(filters: KpiFilters):
    """Build the shared CTE chain and its bound parameters."""

    conditions = []
    params = {}
    expanding = []

    if filters.date_from is not None:
        conditions.append("purchased_at >= :date_from")
        params["date_from"] = filters.date_from

    if filters.date_to is not None:
        conditions.append("purchased_at < :date_to_exclusive")
        params["date_to_exclusive"] = filters.date_to + timedelta(days=1)

    if filters.categories:
        conditions.append("category IN :categories")
        params["categories"] = list(filters.categories)
        expanding.append("categories")

    if filters.states:
        conditions.append("state IN :states")
        params["states"] = list(filters.states)
        expanding.append("states")

    where = " AND ".join(conditions) if conditions else "TRUE"

    sql = (
        "WITH "
        + _RAW
        + f",\nitem_base AS (SELECT * FROM raw WHERE {where}),\n"
        + _ORDER_LEVEL
    )

    return sql, params, tuple(expanding)


def _query(filters: KpiFilters, body: str, extra_params: dict | None = None):
    cte, params, expanding = _with_clause(filters)

    params = {**params, **(extra_params or {})}

    return run_query(f"{cte}\n{body}", params, expanding)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def get_filter_options() -> dict:
    """Bounds and choices for the dashboard filters."""

    bounds = run_query(
        "SELECT MIN(order_purchase_timestamp)::date AS first_day, "
        "MAX(order_purchase_timestamp)::date AS last_day FROM orders"
    )
    categories = run_query(
        """
        SELECT DISTINCT COALESCE(
            ct.product_category_name_english,
            p.product_category_name,
            'unknown'
        ) AS category
        FROM products p
        LEFT JOIN category_translation ct
            ON ct.product_category_name = p.product_category_name
        ORDER BY 1
        """
    )
    states = run_query(
        "SELECT DISTINCT customer_state AS state FROM customers "
        "WHERE customer_state IS NOT NULL ORDER BY 1"
    )

    return {
        "first_day": bounds.loc[0, "first_day"],
        "last_day": bounds.loc[0, "last_day"],
        "categories": categories["category"].tolist(),
        "states": states["state"].tolist(),
    }


def get_kpis(filters: KpiFilters) -> dict:
    """Headline KPIs for the selection."""

    row = _query(
        filters,
        """
        SELECT
            COALESCE(SUM(revenue) FILTER (WHERE order_status = 'delivered'), 0)
                AS revenue,
            COUNT(*) FILTER (WHERE order_status = 'delivered') AS orders,
            COUNT(*) AS all_orders,
            AVG(EXTRACT(EPOCH FROM (delivered_at - purchased_at)) / 86400.0)
                FILTER (WHERE order_status = 'delivered'
                        AND delivered_at IS NOT NULL) AS avg_delivery_days,
            AVG((delivered_at <= estimated_at)::int)
                FILTER (WHERE order_status = 'delivered'
                        AND delivered_at IS NOT NULL
                        AND estimated_at IS NOT NULL) AS on_time_rate,
            AVG((order_status = 'canceled')::int) AS cancel_rate
        FROM order_level
        """,
    ).iloc[0]

    review = _query(
        filters,
        """
        SELECT AVG(r.review_score) AS avg_review_score
        FROM reviews r
        JOIN order_level ol ON ol.order_id = r.order_id
        WHERE ol.order_status = 'delivered'
        """,
    ).iloc[0]

    orders = int(row["orders"])
    revenue = float(row["revenue"])

    def number(value):
        return None if pd.isna(value) else float(value)

    return {
        "revenue": revenue,
        "orders": orders,
        "aov": revenue / orders if orders else None,
        "avg_delivery_days": number(row["avg_delivery_days"]),
        "on_time_rate": number(row["on_time_rate"]),
        "cancel_rate": number(row["cancel_rate"]),
        "avg_review_score": number(review["avg_review_score"]),
    }


def previous_period(filters: KpiFilters) -> KpiFilters | None:
    """Same-length window immediately before the selected dates."""

    if filters.date_from is None or filters.date_to is None:
        return None

    length = (filters.date_to - filters.date_from).days + 1
    previous_to = filters.date_from - timedelta(days=1)
    previous_from = previous_to - timedelta(days=length - 1)

    return replace(filters, date_from=previous_from, date_to=previous_to)


def get_kpis_with_delta(filters: KpiFilters) -> dict:
    """Current KPIs plus percentage change versus the previous period."""

    current = get_kpis(filters)
    previous_filters = previous_period(filters)

    if previous_filters is None:
        return {"current": current, "previous": None, "delta": {}}

    previous = get_kpis(previous_filters)
    delta = {}

    for key, value in current.items():
        old = previous.get(key)

        if value is None or old in (None, 0):
            delta[key] = None
        else:
            delta[key] = (value - old) / abs(old)

    return {"current": current, "previous": previous, "delta": delta}


def get_monthly_trend(filters: KpiFilters) -> pd.DataFrame:
    return _query(
        filters,
        """
        SELECT
            date_trunc('month', purchased_at)::date AS month,
            COALESCE(SUM(revenue) FILTER (WHERE order_status = 'delivered'), 0)
                AS revenue,
            COUNT(*) FILTER (WHERE order_status = 'delivered') AS orders
        FROM order_level
        GROUP BY 1
        ORDER BY 1
        """,
    )


def get_daily_metrics(filters: KpiFilters) -> pd.DataFrame:
    return _query(
        filters,
        """
        SELECT
            purchased_at::date AS day,
            COALESCE(SUM(revenue) FILTER (WHERE order_status = 'delivered'), 0)
                AS revenue,
            COUNT(*) FILTER (WHERE order_status = 'delivered') AS orders,
            COUNT(*) AS all_orders,
            AVG((order_status = 'canceled')::int) AS cancel_rate
        FROM order_level
        GROUP BY 1
        ORDER BY 1
        """,
    )


def get_top_categories(filters: KpiFilters, limit: int = 10) -> pd.DataFrame:
    return _query(
        filters,
        """
        SELECT
            category,
            SUM(price) AS revenue,
            COUNT(DISTINCT order_id) AS orders
        FROM item_base
        WHERE order_status = 'delivered'
        GROUP BY category
        ORDER BY revenue DESC
        LIMIT :limit
        """,
        {"limit": int(limit)},
    )


def get_state_breakdown(filters: KpiFilters) -> pd.DataFrame:
    return _query(
        filters,
        """
        SELECT
            state,
            COALESCE(SUM(revenue) FILTER (WHERE order_status = 'delivered'), 0)
                AS revenue,
            COUNT(*) FILTER (WHERE order_status = 'delivered') AS orders,
            AVG(EXTRACT(EPOCH FROM (delivered_at - purchased_at)) / 86400.0)
                FILTER (WHERE order_status = 'delivered'
                        AND delivered_at IS NOT NULL) AS avg_delivery_days,
            AVG((delivered_at <= estimated_at)::int)
                FILTER (WHERE order_status = 'delivered'
                        AND delivered_at IS NOT NULL
                        AND estimated_at IS NOT NULL) AS on_time_rate
        FROM order_level
        GROUP BY state
        ORDER BY revenue DESC
        """,
    )


def get_payment_mix(filters: KpiFilters) -> pd.DataFrame:
    return _query(
        filters,
        """
        SELECT
            pay.payment_type,
            COUNT(DISTINCT ol.order_id) AS orders,
            SUM(pay.payment_value) AS payment_value
        FROM payments pay
        JOIN order_level ol ON ol.order_id = pay.order_id
        WHERE ol.order_status = 'delivered'
        GROUP BY pay.payment_type
        ORDER BY orders DESC
        """,
    )
