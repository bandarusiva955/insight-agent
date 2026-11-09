"""
Per-session workspaces: each upload gets its own PostgreSQL schema.

Generated SQL runs with search_path set to that schema and the validator
rejects every schema qualifier, so a workspace query can never see the Olist
tables, the audit log, or another workspace. Schemas are dropped when the
user clears them and swept after WORKSPACE_TTL_HOURS.
"""

import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import text

from app.db.connection import engine
from app.sql.validator import validate_sql
from app.workspace.profile import profile_frame, schema_text

SCHEMA_PREFIX = "ws_"
WORKSPACE_TTL_HOURS = int(os.getenv("WORKSPACE_TTL_HOURS", "6"))
MAX_ROWS = 1000
STATEMENT_TIMEOUT = "10s"
_SCHEMA_RE = re.compile(r"^ws_[0-9a-f]{12}$")


@dataclass
class Workspace:
    schema: str
    tables: dict = field(default_factory=dict)  # name -> list[ColumnProfile]

    def table_names(self) -> frozenset:
        return frozenset(self.tables)

    def schema_context(self, include_examples: bool = True) -> str:
        return "\n\n".join(
            schema_text(name, profiles, include_examples)
            for name, profiles in self.tables.items()
        )


def _quote(identifier: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", identifier):
        raise ValueError(f"Unsafe identifier: {identifier!r}")

    return f'"{identifier}"'


def _copy_insert(table, connection, keys, data_iter):
    """pandas ``to_sql`` method that bulk-loads rows with PostgreSQL COPY."""

    columns = ", ".join(_quote_column(key) for key in keys)
    target = f"{_quote(table.schema)}.{_quote(table.name)}"

    with connection.connection.cursor() as cursor:
        with cursor.copy(f"COPY {target} ({columns}) FROM STDIN") as copy:
            for row in data_iter:
                copy.write_row(row)


def _quote_column(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def create_workspace(frames: dict, db_engine=None) -> Workspace:
    """Load cleaned DataFrames into a new private schema."""

    db_engine = db_engine or engine
    schema = SCHEMA_PREFIX + secrets.token_hex(6)
    workspace = Workspace(schema=schema)
    stamp = datetime.now(timezone.utc).isoformat()

    with db_engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {_quote(schema)}"))
        connection.execute(text(f"COMMENT ON SCHEMA {_quote(schema)} IS '{stamp}'"))

        for name, frame in frames.items():
            frame.to_sql(
                name, connection, schema=schema, index=False, method=_copy_insert,
                chunksize=20000,
            )
            workspace.tables[name] = profile_frame(frame)

        readonly_user = os.getenv("POSTGRES_READONLY_USER")

        if readonly_user and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", readonly_user):
            role_exists = connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": readonly_user}
            ).scalar()

            if role_exists:
                connection.execute(
                    text(f'GRANT USAGE ON SCHEMA {_quote(schema)} TO "{readonly_user}"')
                )
                connection.execute(
                    text(f'GRANT SELECT ON ALL TABLES IN SCHEMA {_quote(schema)} '
                         f'TO "{readonly_user}"')
                )

    return workspace


def drop_workspace(schema: str, db_engine=None) -> None:
    if not _SCHEMA_RE.match(schema):
        raise ValueError("Not a workspace schema.")

    with (db_engine or engine).begin() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {_quote(schema)} CASCADE"))


def drop_expired(db_engine=None, ttl_hours: int = WORKSPACE_TTL_HOURS) -> int:
    """Remove workspace schemas older than the TTL. Returns how many."""

    db_engine = db_engine or engine
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    dropped = 0

    with db_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT n.nspname, d.description FROM pg_namespace n "
                "LEFT JOIN pg_description d ON d.objoid = n.oid "
                "WHERE n.nspname LIKE 'ws\\_%'"
            )
        ).fetchall()

    for schema, comment in rows:
        if not _SCHEMA_RE.match(schema):
            continue

        try:
            created = datetime.fromisoformat(comment) if comment else None
        except ValueError:
            created = None

        if created is None or created < cutoff:
            drop_workspace(schema, db_engine)
            dropped += 1

    return dropped


def execute_workspace_sql(workspace: Workspace, sql: str, db_engine=None) -> pd.DataFrame:
    """Validate and run SQL inside one workspace only, read-only."""

    from app.db.connection import query_engine

    ok, message = validate_sql(
        sql, allowed_tables=workspace.table_names(), allowed_schemas={""}
    )

    if not ok:
        raise ValueError(f"SQL rejected: {message}")

    with (db_engine or query_engine).connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
            connection.execute(text("SET LOCAL lock_timeout = '3s'"))
            connection.execute(text(f"SET LOCAL search_path = {_quote(workspace.schema)}"))

            result = connection.execution_options(stream_results=True).execute(text(sql))

            try:
                columns = list(result.keys())
                rows = result.fetchmany(MAX_ROWS + 1)
            finally:
                result.close()

    truncated = len(rows) > MAX_ROWS
    frame = pd.DataFrame(rows[:MAX_ROWS], columns=columns)
    frame.attrs["truncated"] = truncated

    return frame
