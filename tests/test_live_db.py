"""Live monitor: simulator, windows, alert rules and cooldown."""

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app import live

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def clean_live(seeded_db):
    live.ensure_live_schema(seeded_db)

    with seeded_db.begin() as connection:
        connection.execute(text("TRUNCATE live.order_stream"))
        connection.execute(text("TRUNCATE app_meta.alerts"))

    return seeded_db


def _fill_baseline(db, per_minute=10, minutes=60, offset=5, seed=1):
    """Steady traffic for the hour before the 5-minute window."""

    rng = random.Random(seed)

    # Batches sit 30 s into each minute bucket, so the first baseline batch
    # (5 min 30 s ago) is just outside the 5-minute window.
    for minute in range(offset, offset + minutes):
        live.simulate_batch(
            per_minute,
            rng=rng,
            db_engine=db,
            created_at=NOW - timedelta(minutes=minute, seconds=30),
        )


def _fill_window(db, incident="none", per_minute=10, seed=2):
    rng = random.Random(seed)

    for minute in range(0, 5):
        live.simulate_batch(
            per_minute,
            incident=incident,
            rng=rng,
            db_engine=db,
            created_at=NOW - timedelta(minutes=minute, seconds=30),
        )


def _kinds(db):
    snapshot = live.live_snapshot(now=NOW, db_engine=db)

    return {alert.kind for alert in live.evaluate_alerts(snapshot)}


def test_simulator_writes_rows_and_rejects_unknown_incidents(clean_live):
    assert live.simulate_batch(7, db_engine=clean_live) == 7

    with clean_live.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM live.order_stream")
        ).scalar_one()

    assert count == 7

    with pytest.raises(ValueError):
        live.simulate_batch(1, incident="meteor", db_engine=clean_live)


def test_simulator_never_touches_the_real_tables(clean_live):
    with clean_live.connect() as connection:
        before = connection.execute(text("SELECT COUNT(*) FROM orders")).scalar_one()

    live.simulate_batch(50, db_engine=clean_live)

    with clean_live.connect() as connection:
        after = connection.execute(text("SELECT COUNT(*) FROM orders")).scalar_one()

    assert before == after


def test_steady_traffic_raises_no_alerts(clean_live):
    _fill_baseline(clean_live)
    _fill_window(clean_live)

    assert _kinds(clean_live) == set()


def test_cancel_spike_is_detected(clean_live):
    _fill_baseline(clean_live)
    _fill_window(clean_live, incident="cancel_spike")

    assert "cancel_spike" in _kinds(clean_live)


def test_delivery_delay_is_detected(clean_live):
    _fill_baseline(clean_live)
    _fill_window(clean_live, incident="delivery_delay")

    assert "delivery_delay" in _kinds(clean_live)


def test_traffic_drop_is_detected(clean_live):
    _fill_baseline(clean_live)
    _fill_window(clean_live, incident="traffic_drop")

    assert "traffic_drop" in _kinds(clean_live)


def test_no_alerts_without_enough_baseline(clean_live):
    _fill_window(clean_live, incident="cancel_spike")

    assert _kinds(clean_live) == set()


def test_snapshot_windows_do_not_overlap(clean_live):
    _fill_baseline(clean_live, per_minute=4)
    _fill_window(clean_live, per_minute=10)

    snapshot = live.live_snapshot(now=NOW, db_engine=clean_live)

    assert snapshot["window"]["orders"] == 50
    assert snapshot["baseline"]["orders"] == 240


def test_alerts_respect_the_cooldown(clean_live):
    sent_messages = []
    alert = live.Alert("cancel_spike", "high", "Cancel rate is 45%.")

    def sender(message):
        sent_messages.append(message)
        return "console"

    first = live.dispatch_alerts([alert], db_engine=clean_live, sender=sender)
    second = live.dispatch_alerts([alert], db_engine=clean_live, sender=sender)

    assert len(first) == 1 and second == []
    assert sent_messages == ["[HIGH] Cancel rate is 45%."]

    with clean_live.connect() as connection:
        stored = connection.execute(
            text("SELECT kind, channel FROM app_meta.alerts")
        ).all()

    assert stored == [("cancel_spike", "console")]


def test_different_alert_kinds_are_not_blocked_by_each_other(clean_live):
    sender = lambda message: "console"
    first = live.Alert("cancel_spike", "high", "a")
    second = live.Alert("traffic_drop", "high", "b")

    sent = live.dispatch_alerts([first, second], db_engine=clean_live, sender=sender)

    assert len(sent) == 2


def test_recent_orders_and_series(clean_live):
    live.simulate_batch(20, db_engine=clean_live)

    assert len(live.recent_orders(limit=5, db_engine=clean_live)) == 5

    series = live.per_minute_series(minutes=5, db_engine=clean_live)

    assert int(series["orders"].sum()) == 20
