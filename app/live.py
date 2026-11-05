"""Live order monitor: a simulated order stream plus alert rules.

The stream lives in its own schema (live.order_stream) so simulated orders
never mix with the real Olist tables. The monitor compares the most recent
window with the hour before it and raises an alert when order volume,
cancellations or delivery times move sharply.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import text

from app.alerts import send_alert
from app.db.connection import engine

DEFAULT_CATEGORIES = [
    "health_beauty", "watches_gifts", "bed_bath_table", "sports_leisure",
    "computers_accessories", "furniture_decor", "housewares", "toys",
]
DEFAULT_STATES = ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF"]

INCIDENTS = ("none", "cancel_spike", "delivery_delay", "traffic_drop")

CREATE_STATEMENTS = (
    "CREATE SCHEMA IF NOT EXISTS live",
    """
    CREATE TABLE IF NOT EXISTS live.order_stream (
        id BIGSERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        category TEXT NOT NULL,
        state TEXT NOT NULL,
        amount NUMERIC(12, 2) NOT NULL,
        status TEXT NOT NULL,
        delivery_days NUMERIC(6, 1)
    )
    """,
    "CREATE INDEX IF NOT EXISTS order_stream_created_idx "
    "ON live.order_stream (created_at)",
    "CREATE SCHEMA IF NOT EXISTS app_meta",
    """
    CREATE TABLE IF NOT EXISTS app_meta.alerts (
        id BIGSERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        kind TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        channel TEXT
    )
    """,
)


@dataclass
class Alert:
    kind: str
    severity: str
    message: str


def ensure_live_schema(db_engine=None) -> None:
    with (db_engine or engine).begin() as connection:
        for statement in CREATE_STATEMENTS:
            connection.execute(text(statement))


def _weighted_choices(db_engine) -> tuple:
    """Categories and states weighted by their share of real order items."""

    try:
        with db_engine.connect() as connection:
            categories = connection.execute(
                text(
                    """
                    SELECT COALESCE(ct.product_category_name_english,
                                    p.product_category_name) AS name,
                           COUNT(*) AS n
                    FROM order_items oi
                    JOIN products p ON p.product_id = oi.product_id
                    LEFT JOIN category_translation ct
                        ON ct.product_category_name = p.product_category_name
                    WHERE p.product_category_name IS NOT NULL
                    GROUP BY 1 ORDER BY n DESC LIMIT 15
                    """
                )
            ).all()
            states = connection.execute(
                text(
                    "SELECT customer_state, COUNT(*) FROM customers "
                    "WHERE customer_state IS NOT NULL "
                    "GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
                )
            ).all()

        if categories and states:
            return (
                [r[0] for r in categories], [int(r[1]) for r in categories],
                [r[0] for r in states], [int(r[1]) for r in states],
            )

    except Exception:
        pass

    return (
        DEFAULT_CATEGORIES, [1] * len(DEFAULT_CATEGORIES),
        DEFAULT_STATES, [1] * len(DEFAULT_STATES),
    )


def simulate_batch(
    count: int,
    incident: str = "none",
    rng: random.Random | None = None,
    db_engine=None,
    created_at: datetime | None = None,
) -> int:
    """Insert `count` simulated orders. Returns how many were written."""

    if incident not in INCIDENTS:
        raise ValueError(f"incident must be one of {INCIDENTS}")

    db_engine = db_engine or engine
    rng = rng or random.Random()
    ensure_live_schema(db_engine)

    categories, cat_weights, states, state_weights = _weighted_choices(db_engine)

    if incident == "traffic_drop":
        count = max(0, count // 5)

    rows = []

    for _ in range(count):
        cancel_probability = 0.04
        delivery_mean = 11.0

        if incident == "cancel_spike":
            cancel_probability = 0.45
        if incident == "delivery_delay":
            delivery_mean = 26.0

        roll = rng.random()

        if roll < cancel_probability:
            status, delivery_days = "canceled", None
        elif roll < cancel_probability + 0.35:
            status, delivery_days = "created", None
        else:
            status = "delivered"
            delivery_days = round(max(2.0, rng.gauss(delivery_mean, 2.5)), 1)

        rows.append(
            {
                "created_at": created_at or datetime.now(timezone.utc),
                "category": rng.choices(categories, cat_weights)[0],
                "state": rng.choices(states, state_weights)[0],
                "amount": round(min(900.0, max(8.0, rng.lognormvariate(4.3, 0.6))), 2),
                "status": status,
                "delivery_days": delivery_days,
            }
        )

    if rows:
        with db_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO live.order_stream "
                    "(created_at, category, state, amount, status, delivery_days) "
                    "VALUES (:created_at, :category, :state, :amount, :status, "
                    ":delivery_days)"
                ),
                rows,
            )

    return len(rows)


def seed_baseline(
    minutes: int = 60,
    per_minute: int = 8,
    now: datetime | None = None,
    db_engine=None,
    rng: random.Random | None = None,
) -> int:
    """
    Back-fill normal traffic for the hour before the live window, so the
    monitor has a baseline to compare against. Returns orders written.
    """

    now = now or datetime.now(timezone.utc)
    rng = rng or random.Random()
    written = 0

    # Batches sit 30 s into each minute bucket, just outside the 5-minute window.
    for minute in range(5, 5 + minutes):
        written += simulate_batch(
            per_minute,
            rng=rng,
            db_engine=db_engine,
            created_at=now - timedelta(minutes=minute, seconds=30),
        )

    return written


def _window_stats(db_engine, start: datetime, end: datetime) -> dict:
    with db_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    COUNT(*) AS orders,
                    COALESCE(SUM(amount) FILTER (WHERE status <> 'canceled'), 0)
                        AS revenue,
                    AVG((status = 'canceled')::int) AS cancel_rate,
                    AVG(delivery_days) AS avg_delivery_days
                FROM live.order_stream
                WHERE created_at >= :start AND created_at < :end
                """
            ),
            {"start": start, "end": end},
        ).mappings().one()

    return {
        "orders": int(row["orders"]),
        "revenue": float(row["revenue"]),
        "cancel_rate": None if row["cancel_rate"] is None else float(row["cancel_rate"]),
        "avg_delivery_days": (
            None if row["avg_delivery_days"] is None else float(row["avg_delivery_days"])
        ),
    }


def live_snapshot(
    window_minutes: int = 5,
    baseline_minutes: int = 60,
    now: datetime | None = None,
    db_engine=None,
) -> dict:
    """Recent window versus the baseline hour before it."""

    db_engine = db_engine or engine
    ensure_live_schema(db_engine)
    now = now or datetime.now(timezone.utc)

    window_start = now - timedelta(minutes=window_minutes)
    baseline_start = window_start - timedelta(minutes=baseline_minutes)

    window = _window_stats(db_engine, window_start, now + timedelta(seconds=1))
    baseline = _window_stats(db_engine, baseline_start, window_start)

    window["orders_per_min"] = window["orders"] / window_minutes
    baseline["orders_per_min"] = baseline["orders"] / baseline_minutes

    return {
        "window": window,
        "baseline": baseline,
        "window_minutes": window_minutes,
        "baseline_minutes": baseline_minutes,
    }


def evaluate_alerts(snapshot: dict) -> list:
    """Alert rules. Needs enough baseline data to avoid noisy alerts."""

    window, baseline = snapshot["window"], snapshot["baseline"]
    alerts = []

    if baseline["orders"] < 30:
        return alerts

    base_rate = baseline["orders_per_min"]

    if window["orders_per_min"] < 0.4 * base_rate:
        alerts.append(
            Alert(
                "traffic_drop",
                "high",
                f"Order volume dropped to {window['orders_per_min']:.1f}/min "
                f"vs {base_rate:.1f}/min over the previous hour.",
            )
        )
    elif window["orders_per_min"] > 2.5 * base_rate:
        alerts.append(
            Alert(
                "traffic_spike",
                "medium",
                f"Order volume spiked to {window['orders_per_min']:.1f}/min "
                f"vs {base_rate:.1f}/min over the previous hour.",
            )
        )

    if window["orders"] >= 10 and window["cancel_rate"] is not None:
        base_cancel = baseline["cancel_rate"] or 0.0

        if window["cancel_rate"] >= max(0.15, 3 * base_cancel):
            alerts.append(
                Alert(
                    "cancel_spike",
                    "high",
                    f"Cancel rate is {window['cancel_rate']:.0%} vs "
                    f"{base_cancel:.0%} over the previous hour.",
                )
            )

    if (
        window["avg_delivery_days"] is not None
        and baseline["avg_delivery_days"]
        and window["avg_delivery_days"] >= 1.5 * baseline["avg_delivery_days"]
    ):
        alerts.append(
            Alert(
                "delivery_delay",
                "medium",
                f"Average delivery time is {window['avg_delivery_days']:.1f} days "
                f"vs {baseline['avg_delivery_days']:.1f} days over the previous hour.",
            )
        )

    return alerts


def dispatch_alerts(
    alerts: list,
    cooldown_minutes: int = 10,
    db_engine=None,
    sender=send_alert,
) -> list:
    """Send alerts that have not fired recently. Returns the ones sent."""

    db_engine = db_engine or engine
    sent = []

    for alert in alerts:
        with db_engine.begin() as connection:
            recent = connection.execute(
                text(
                    "SELECT 1 FROM app_meta.alerts WHERE kind = :kind "
                    "AND created_at > now() - make_interval(mins => :mins) LIMIT 1"
                ),
                {"kind": alert.kind, "mins": cooldown_minutes},
            ).first()

            if recent:
                continue

            channel = sender(f"[{alert.severity.upper()}] {alert.message}")

            connection.execute(
                text(
                    "INSERT INTO app_meta.alerts (kind, severity, message, channel) "
                    "VALUES (:kind, :severity, :message, :channel)"
                ),
                {
                    "kind": alert.kind,
                    "severity": alert.severity,
                    "message": alert.message,
                    "channel": channel,
                },
            )

        sent.append(alert)

    return sent


def recent_orders(limit: int = 15, db_engine=None) -> pd.DataFrame:
    db_engine = db_engine or engine
    ensure_live_schema(db_engine)

    with db_engine.connect() as connection:
        result = connection.execute(
            text(
                "SELECT created_at, category, state, amount, status, delivery_days "
                "FROM live.order_stream ORDER BY id DESC LIMIT :n"
            ),
            {"n": limit},
        )

        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def per_minute_series(minutes: int = 30, db_engine=None) -> pd.DataFrame:
    db_engine = db_engine or engine
    ensure_live_schema(db_engine)

    with db_engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT date_trunc('minute', created_at) AS minute,
                       COUNT(*) AS orders,
                       COALESCE(SUM(amount) FILTER (WHERE status <> 'canceled'), 0)
                           AS revenue
                FROM live.order_stream
                WHERE created_at > now() - make_interval(mins => :mins)
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"mins": minutes},
        )
        frame = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    frame["revenue"] = pd.to_numeric(frame["revenue"].astype(float))

    return frame
