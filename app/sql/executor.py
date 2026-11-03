import pandas as pd
from sqlalchemy import text

from app.db.connection import engine
from app.sql.validator import validate_sql


MAX_ROWS = 1000


def execute_sql(sql: str) -> pd.DataFrame:
    """Validate and execute SQL using a read-only PostgreSQL transaction."""

    print("Validating SQL...", flush=True)

    is_valid, message = validate_sql(sql)

    if not is_valid:
        raise ValueError(f"SQL rejected: {message}")

    print("SQL validation successful.", flush=True)

    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '10s'"))
            connection.execute(text("SET LOCAL lock_timeout = '3s'"))

            print("Executing read-only query...", flush=True)

            result = None

            try:
                result = connection.execution_options(
                    stream_results=True
                ).execute(text(sql))

                columns = list(result.keys())
                rows = result.fetchmany(MAX_ROWS + 1)

                truncated = len(rows) > MAX_ROWS
                rows = rows[:MAX_ROWS]

                dataframe = pd.DataFrame(rows, columns=columns)
                dataframe.attrs["truncated"] = truncated

            finally:
                if result is not None:
                    result.close()

    print(f"Rows returned: {len(dataframe)}", flush=True)

    if truncated:
        print(f"Results limited to {MAX_ROWS} rows.")

    return dataframe


if __name__ == "__main__":
    test_query = """
    SELECT
        order_status,
        COUNT(*) AS total_orders
    FROM orders
    GROUP BY order_status
    ORDER BY total_orders DESC
    LIMIT 10;
    """

    try:
        result = execute_sql(test_query)
        print(result.to_string(index=False))
    except Exception as error:
        print(f"Execution failed: {error}")
