"""Usage statistics from the audit log, for the Usage tab."""

import pandas as pd
from sqlalchemy import text

from app.audit import ensure_audit_table
from app.db.connection import engine


def _frame(connection, sql: str, params: dict | None = None) -> pd.DataFrame:
    result = connection.execute(text(sql), params or {})

    return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def usage_summary(db_engine=None) -> dict:
    db_engine = db_engine or engine
    ensure_audit_table()

    with db_engine.connect() as connection:
        row = _frame(
            connection,
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'success') AS success,
                COUNT(*) FILTER (WHERE status = 'corrected') AS corrected,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                AVG(latency_ms) AS avg_latency_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                    AS p95_latency_ms,
                AVG(attempts) AS avg_attempts
            FROM app_meta.query_audit
            """,
        ).iloc[0]

    total = int(row["total"])

    def number(value):
        return None if pd.isna(value) else float(value)

    return {
        "total": total,
        "success": int(row["success"]),
        "corrected": int(row["corrected"]),
        "failed": int(row["failed"]),
        "success_rate": (
            (int(row["success"]) + int(row["corrected"])) / total if total else None
        ),
        "avg_latency_ms": number(row["avg_latency_ms"]),
        "p95_latency_ms": number(row["p95_latency_ms"]),
        "avg_attempts": number(row["avg_attempts"]),
    }


def recent_queries(limit: int = 20, db_engine=None) -> pd.DataFrame:
    db_engine = db_engine or engine
    ensure_audit_table()

    with db_engine.connect() as connection:
        return _frame(
            connection,
            """
            SELECT created_at, question, status, attempts, latency_ms,
                   row_count, error
            FROM app_meta.query_audit
            ORDER BY id DESC
            LIMIT :n
            """,
            {"n": int(limit)},
        )


def recent_alerts(limit: int = 20, db_engine=None) -> pd.DataFrame:
    db_engine = db_engine or engine

    from app.live import ensure_live_schema

    ensure_live_schema(db_engine)

    with db_engine.connect() as connection:
        return _frame(
            connection,
            "SELECT created_at, severity, kind, message, channel "
            "FROM app_meta.alerts ORDER BY id DESC LIMIT :n",
            {"n": int(limit)},
        )
