"""KPI queries checked against an independent pandas calculation."""

from datetime import date

import pandas as pd
import pytest

from app.analytics import kpi
from app.analytics.kpi import KpiFilters
from tests.support.synthetic_data import build_synthetic_dataset

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def data():
    return build_synthetic_dataset()


def _expected(data, filters: KpiFilters):
    """Recompute the KPI definitions with pandas from the raw frames."""

    orders = data["orders"].merge(data["customers"], on="customer_id")
    items = (
        data["order_items"]
        .merge(data["products"], on="product_id")
        .merge(data["category_translation"], on="product_category_name", how="left")
    )
    items["category"] = (
        items["product_category_name_english"]
        .fillna(items["product_category_name"])
        .fillna("unknown")
    )
    frame = items.merge(orders, on="order_id")

    if filters.date_from:
        frame = frame[frame.order_purchase_timestamp >= pd.Timestamp(filters.date_from)]
    if filters.date_to:
        frame = frame[
            frame.order_purchase_timestamp
            < pd.Timestamp(filters.date_to) + pd.Timedelta(days=1)
        ]
    if filters.categories:
        frame = frame[frame.category.isin(filters.categories)]
    if filters.states:
        frame = frame[frame.customer_state.isin(filters.states)]

    per_order = frame.groupby(
        [
            "order_id",
            "order_status",
            "order_purchase_timestamp",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
        dropna=False,
        as_index=False,
    ).agg(revenue=("price", "sum"))

    delivered = per_order[per_order.order_status == "delivered"]
    days = (
        delivered.order_delivered_customer_date - delivered.order_purchase_timestamp
    ).dt.total_seconds() / 86400

    return {
        "revenue": float(delivered.revenue.sum()),
        "orders": len(delivered),
        "avg_delivery_days": float(days.mean()),
        "on_time_rate": float(
            (
                delivered.order_delivered_customer_date
                <= delivered.order_estimated_delivery_date
            ).mean()
        ),
        "cancel_rate": float((per_order.order_status == "canceled").mean()),
    }


FILTER_CASES = [
    KpiFilters(),
    KpiFilters(date_from=date(2017, 6, 1), date_to=date(2017, 8, 31)),
    KpiFilters(states=("SP",)),
    KpiFilters(categories=("health_beauty", "toys")),
    KpiFilters(
        date_from=date(2018, 1, 1),
        date_to=date(2018, 4, 30),
        categories=("health_beauty",),
        states=("SP", "RJ"),
    ),
]


@pytest.mark.parametrize("filters", FILTER_CASES)
def test_kpis_match_pandas(seeded_db, data, filters):
    actual = kpi.get_kpis(filters)
    expected = _expected(data, filters)

    assert actual["orders"] == expected["orders"]
    assert actual["revenue"] == pytest.approx(expected["revenue"], rel=1e-9)
    assert actual["aov"] == pytest.approx(
        expected["revenue"] / expected["orders"], rel=1e-9
    )
    assert actual["avg_delivery_days"] == pytest.approx(
        expected["avg_delivery_days"], rel=1e-6
    )
    assert actual["on_time_rate"] == pytest.approx(expected["on_time_rate"])
    assert actual["cancel_rate"] == pytest.approx(expected["cancel_rate"])


def test_untranslated_category_is_kept(seeded_db, data):
    options = kpi.get_filter_options()

    assert "pet_shop_pt" in options["categories"]
    assert "health_beauty" in options["categories"]
    purchases = data["orders"].order_purchase_timestamp
    assert options["first_day"] == purchases.min().date()
    assert options["last_day"] == purchases.max().date()
    assert set(options["states"]) == {
        "SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF"
    }


def test_monthly_trend_sums_to_total(seeded_db):
    trend = kpi.get_monthly_trend(KpiFilters())
    total = kpi.get_kpis(KpiFilters())

    assert len(trend) == 20
    assert trend["revenue"].sum() == pytest.approx(total["revenue"])
    assert int(trend["orders"].sum()) == total["orders"]


def test_top_categories_are_sorted_and_limited(seeded_db):
    top = kpi.get_top_categories(KpiFilters(), limit=5)

    assert len(top) == 5
    assert top["revenue"].is_monotonic_decreasing


def test_state_breakdown_sums_to_total(seeded_db):
    states = kpi.get_state_breakdown(KpiFilters())
    total = kpi.get_kpis(KpiFilters())

    assert states["revenue"].sum() == pytest.approx(total["revenue"])


def test_previous_period_has_same_length():
    current = KpiFilters(date_from=date(2018, 3, 1), date_to=date(2018, 3, 31))
    previous = kpi.previous_period(current)

    assert previous.date_to == date(2018, 2, 28)
    assert previous.date_from == date(2018, 1, 29)
    assert (previous.date_to - previous.date_from).days == 30
    assert kpi.previous_period(KpiFilters()) is None


def test_delta_against_previous_period(seeded_db):
    filters = KpiFilters(date_from=date(2018, 3, 1), date_to=date(2018, 3, 31))
    result = kpi.get_kpis_with_delta(filters)

    expected = (
        result["current"]["revenue"] - result["previous"]["revenue"]
    ) / result["previous"]["revenue"]

    assert result["delta"]["revenue"] == pytest.approx(expected)


def test_filters_are_hashable_for_caching():
    assert hash(KpiFilters(states=("SP",))) == hash(KpiFilters(states=("SP",)))


def test_payment_mix(seeded_db):
    mix = kpi.get_payment_mix(KpiFilters())

    assert "credit_card" in set(mix["payment_type"])
    assert mix["orders"].is_monotonic_decreasing
