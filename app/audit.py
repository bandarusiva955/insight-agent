"""
Audit log: one row per question asked, stored in the app_meta schema.

app_meta is separate from public, so the LLM never sees the audit table in
its schema prompt and the read-only query role has no access to it.
Logging is best effort: a logging failure must never break an analysis.
"""

from sqlalchemy import text

from app.db.connection import engine

_table_ready = False

CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS app_meta"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS app_meta.query_audit (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    question TEXT NOT NULL,
    generated_sql TEXT,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    latency_ms INTEGER,
    row_count INTEGER,
    error TEXT
)
"""

INSERT_ROW = """
INSERT INTO app_meta.query_audit
    (question, generated_sql, status, attempts, latency_ms, row_count, error)
VALUES
    (:question, :generated_sql, :status, :attempts, :latency_ms,
     :row_count, :error)
"""


def _ensure_table() -> None:
    global _table_ready

    if _table_ready:
        return

    with engine.begin() as connection:
        connection.execute(text(CREATE_SCHEMA))
        connection.execute(text(CREATE_TABLE))

    _table_ready = True


def ensure_audit_table() -> None:
    """Create app_meta.query_audit if needed (idempotent, cached per process)."""

    _ensure_table()


def log_query(
    question: str,
    generated_sql: str | None,
    status: str,
    attempts: int,
    latency_ms: int,
    row_count: int | None = None,
    error: str | None = None,
) -> None:
    """Record a question and its outcome. Never raises."""

    try:
        _ensure_table()

        with engine.begin() as connection:
            connection.execute(
                text(INSERT_ROW),
                {
                    "question": question,
                    "generated_sql": generated_sql,
                    "status": status,
                    "attempts": attempts,
                    "latency_ms": latency_ms,
                    "row_count": row_count,
                    "error": error,
                },
            )

    except Exception as logging_error:
        print(f"Audit logging skipped: {logging_error}", flush=True)
