"""Access control, usage statistics, baseline seeding, RCA suggestions."""

import random
from datetime import datetime, timezone

import pandas as pd
import pytest
from sqlalchemy import text

from app import live, usage
from app.analytics.rca import largest_monthly_changes
from app.ui.access import QuestionBudget, verify_password


def test_verify_password():
    assert verify_password("secret", "secret")
    assert not verify_password("secre", "secret")
    assert not verify_password("", "secret")


def test_question_budget_caps_at_limit():
    budget = QuestionBudget(2)

    assert budget.allow() and budget.allow()
    assert not budget.allow()
    assert budget.used == 2


def test_suggestions_ignore_partial_edge_months():
    trend = pd.DataFrame(
        {
            "month": pd.to_datetime(
                ["2018-01-01", "2018-02-01", "2018-03-01", "2018-04-01", "2018-05-01"]
            ),
            "revenue": [100.0, 10_000.0, 7_000.0, 9_000.0, 50.0],
        }
    )

    result = largest_monthly_changes(trend, top=3)

    assert result.iloc[0]["month"] == pd.Timestamp("2018-03-01")
    assert pd.Timestamp("2018-05-01") not in set(result["month"])
    assert pd.Timestamp("2018-02-01") not in set(result["month"])


@pytest.mark.db
def test_seed_baseline_gives_alert_baseline(seeded_db):
    live.ensure_live_schema(seeded_db)

    with seeded_db.begin() as connection:
        connection.execute(text("TRUNCATE live.order_stream"))

    now = datetime.now(timezone.utc)
    written = live.seed_baseline(
        minutes=60, per_minute=5, now=now, db_engine=seeded_db, rng=random.Random(3)
    )
    snapshot = live.live_snapshot(now=now, db_engine=seeded_db)

    assert written == 300
    assert snapshot["baseline"]["orders"] == 300
    assert snapshot["window"]["orders"] == 0


@pytest.mark.db
def test_usage_summary_and_recent(seeded_db):
    from app.audit import ensure_audit_table

    ensure_audit_table()

    with seeded_db.begin() as connection:
        connection.execute(text("TRUNCATE app_meta.query_audit"))
        for status, latency in [("success", 1000), ("corrected", 3000), ("failed", 2000)]:
            connection.execute(
                text(
                    "INSERT INTO app_meta.query_audit "
                    "(question, status, attempts, latency_ms) "
                    "VALUES ('q', :s, 1, :l)"
                ),
                {"s": status, "l": latency},
            )

    summary = usage.usage_summary(seeded_db)

    assert summary["total"] == 3
    assert summary["failed"] == 1
    assert summary["success_rate"] == pytest.approx(2 / 3)
    assert summary["avg_latency_ms"] == pytest.approx(2000)
    assert len(usage.recent_queries(10, seeded_db)) == 3


@pytest.mark.db
def test_usage_summary_empty(seeded_db):
    with seeded_db.begin() as connection:
        connection.execute(text("TRUNCATE app_meta.query_audit"))

    summary = usage.usage_summary(seeded_db)

    assert summary["total"] == 0
    assert summary["success_rate"] is None
