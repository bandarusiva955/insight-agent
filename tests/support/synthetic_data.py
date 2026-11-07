"""
Deterministic, Olist-shaped synthetic data for tests.

This is NOT the real Olist dataset. It follows the same schema (app/db/schema.sql)
and contains two planted events so analytics code can be tested against a known
ground truth:

* 2018-03: order volume dips 25%, health_beauty sales collapse and deliveries
  to SP are much slower (used by the root-cause analysis tests).
* 2018-05-15: a one-day spike of extra orders (used by the anomaly tests).
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

CATEGORIES = {
    "beleza_saude": "health_beauty",
    "relogios_presentes": "watches_gifts",
    "cama_mesa_banho": "bed_bath_table",
    "esporte_lazer": "sports_leisure",
    "informatica_acessorios": "computers_accessories",
    "moveis_decoracao": "furniture_decor",
    "utilidades_domesticas": "housewares",
    "brinquedos": "toys",
    "automotivo": "auto",
    "perfumaria": "perfumery",
}
UNTRANSLATED_CATEGORY = "pet_shop_pt"  # present in products, absent from translation

STATES = ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF"]
STATE_WEIGHTS = np.array([45, 15, 12, 7, 7, 5, 5, 4], dtype=float)

PLANTED_DROP_MONTH = "2018-03"
PLANTED_SPIKE_DAY = "2018-05-15"
SPIKE_EXTRA_ORDERS = 40


def _months():
    return pd.period_range("2017-01", "2018-08", freq="M")


def build_synthetic_dataset(seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)

    # ---- dimensions -----------------------------------------------------
    customers = pd.DataFrame(
        {
            "customer_id": [f"c{i:05d}" for i in range(400)],
            "customer_unique_id": [f"u{i:05d}" for i in range(400)],
            "customer_zip_code_prefix": rng.integers(1000, 99999, 400),
            "customer_city": "city",
            "customer_state": rng.choice(
                STATES, 400, p=STATE_WEIGHTS / STATE_WEIGHTS.sum()
            ),
        }
    )

    sellers = pd.DataFrame(
        {
            "seller_id": [f"s{i:04d}" for i in range(30)],
            "seller_zip_code_prefix": rng.integers(1000, 99999, 30),
            "seller_city": "city",
            "seller_state": rng.choice(STATES, 30),
        }
    )

    category_names = list(CATEGORIES) + [UNTRANSLATED_CATEGORY]
    product_rows = []
    for i in range(110):
        product_rows.append(
            {
                "product_id": f"p{i:05d}",
                "product_category_name": category_names[i % len(category_names)],
                "product_name_lenght": 40,
                "product_description_lenght": 300,
                "product_photos_qty": 2,
                "product_weight_g": 500.0,
                "product_length_cm": 20.0,
                "product_height_cm": 10.0,
                "product_width_cm": 15.0,
            }
        )
    products = pd.DataFrame(product_rows)

    category_translation = pd.DataFrame(
        {
            "product_category_name": list(CATEGORIES),
            "product_category_name_english": list(CATEGORIES.values()),
        }
    )

    products_by_category = {
        name: products.loc[
            products.product_category_name == name, "product_id"
        ].tolist()
        for name in category_names
    }
    customers_by_state = {
        state: customers.loc[customers.customer_state == state, "customer_id"].tolist()
        for state in STATES
    }
    state_of_customer = dict(
        zip(customers.customer_id, customers.customer_state)
    )

    base_popularity = np.array(
        [14, 10, 12, 9, 8, 8, 7, 5, 4, 4, 2], dtype=float
    )  # last entry = untranslated category

    # ---- orders ---------------------------------------------------------
    orders, items, payments, reviews = [], [], [], []
    order_counter = 0

    def make_order(purchase_ts, month_key):
        nonlocal order_counter
        order_counter += 1
        order_id = f"o{order_counter:06d}"

        state = rng.choice(STATES, p=STATE_WEIGHTS / STATE_WEIGHTS.sum())
        customer_id = rng.choice(customers_by_state[state])

        roll = rng.random()
        status = "delivered" if roll < 0.965 else "canceled" if roll < 0.985 else "shipped"

        delivery_mean = 12.0
        if month_key == PLANTED_DROP_MONTH and state == "SP":
            delivery_mean = 24.0
        delivery_days = max(2.0, rng.normal(delivery_mean, 3.0))
        estimated = purchase_ts + timedelta(days=20)
        delivered_at = (
            purchase_ts + timedelta(days=float(delivery_days))
            if status == "delivered"
            else None
        )

        orders.append(
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "order_status": status,
                "order_purchase_timestamp": purchase_ts,
                "order_approved_at": purchase_ts + timedelta(hours=2),
                "order_delivered_carrier_date": purchase_ts + timedelta(days=2),
                "order_delivered_customer_date": delivered_at,
                "order_estimated_delivery_date": estimated,
            }
        )

        popularity = base_popularity.copy()
        if month_key == PLANTED_DROP_MONTH:
            popularity[0] *= 0.15  # health_beauty collapses
        probs = popularity / popularity.sum()

        total_value = 0.0
        for item_no in range(1, int(rng.integers(1, 4)) + 1):
            category = rng.choice(category_names, p=probs)
            product_id = rng.choice(products_by_category[category])
            price = round(float(np.clip(rng.lognormal(4.3, 0.6), 8, 900)), 2)
            freight = round(float(rng.uniform(8, 35)), 2)
            total_value += price + freight
            items.append(
                {
                    "order_id": order_id,
                    "order_item_id": item_no,
                    "product_id": product_id,
                    "seller_id": rng.choice(sellers.seller_id),
                    "shipping_limit_date": purchase_ts + timedelta(days=3),
                    "price": price,
                    "freight_value": freight,
                }
            )

        pay_roll = rng.random()
        pay_type = (
            "credit_card"
            if pay_roll < 0.74
            else "boleto"
            if pay_roll < 0.94
            else "voucher"
            if pay_roll < 0.98
            else "debit_card"
        )
        payments.append(
            {
                "order_id": order_id,
                "payment_sequential": 1,
                "payment_type": pay_type,
                "payment_installments": int(rng.integers(1, 7)),
                "payment_value": round(total_value, 2),
            }
        )

        if status == "delivered":
            late = delivered_at > estimated
            score = int(
                rng.choice([1, 2, 3], p=[0.5, 0.3, 0.2])
                if late
                else rng.choice([3, 4, 5], p=[0.1, 0.3, 0.6])
            )
            reviews.append(
                {
                    "review_id": f"r{order_counter:06d}",
                    "order_id": order_id,
                    "review_score": score,
                    "review_comment_title": None,
                    "review_comment_message": None,
                    "review_creation_date": delivered_at,
                    "review_answer_timestamp": delivered_at + timedelta(days=1),
                }
            )

    for index, month in enumerate(_months()):
        month_key = str(month)
        order_count = 60 + 8 * index
        if month_key == PLANTED_DROP_MONTH:
            order_count = int(order_count * 0.75)  # volume dip in the planted month
        days_in_month = month.days_in_month
        for _ in range(order_count):
            day = int(rng.integers(1, days_in_month + 1))
            purchase_ts = datetime(
                month.year, month.month, day, int(rng.integers(0, 24)),
                int(rng.integers(0, 60)),
            )
            make_order(purchase_ts, month_key)

        if month_key == PLANTED_SPIKE_DAY[:7]:
            spike_day = datetime.fromisoformat(PLANTED_SPIKE_DAY)
            for _ in range(SPIKE_EXTRA_ORDERS):
                make_order(
                    spike_day + timedelta(
                        hours=int(rng.integers(0, 24)),
                        minutes=int(rng.integers(0, 60)),
                    ),
                    month_key,
                )

    return {
        "customers": customers,
        "products": products,
        "sellers": sellers,
        "category_translation": category_translation,
        "orders": pd.DataFrame(orders),
        "order_items": pd.DataFrame(items),
        "payments": pd.DataFrame(payments),
        "reviews": pd.DataFrame(reviews),
    }


# Parent tables first, so foreign keys are satisfied.
LOAD_ORDER = [
    "customers",
    "products",
    "sellers",
    "category_translation",
    "orders",
    "order_items",
    "payments",
    "reviews",
]
