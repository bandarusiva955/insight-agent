"""Run trusted, parameterised analytics queries inside a read-only transaction.

AI-generated SQL goes through app.sql.executor (validator + allow-list). The
fixed queries in app.analytics are written by us, use bound parameters, and
come here instead.
"""

from decimal import Decimal

import pandas as pd
from sqlalchemy import bindparam, text

from app.db.connection import query_engine

STATEMENT_TIMEOUT = "20s"


def _decimals_to_float(frame: pd.DataFrame) -> pd.DataFrame:
    for column in frame.columns:
        series = frame[column]

        if series.dtype == object:
            values = series.dropna()

            if len(values) and all(isinstance(v, Decimal) for v in values):
                frame[column] = pd.to_numeric(series.astype(float))

    return frame


def run_query(
    sql: str,
    params: dict | None = None,
    expanding: tuple = (),
    engine=None,
) -> pd.DataFrame:
    """Execute sql with bound params and return a DataFrame (Decimals -> float)."""

    statement = text(sql)

    if expanding:
        statement = statement.bindparams(
            *[bindparam(name, expanding=True) for name in expanding]
        )

    with (engine or query_engine).connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(
                text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
            )
            result = connection.execute(statement, params or {})
            frame = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    return _decimals_to_float(frame)
