import sqlglot
from sqlglot import exp


ALLOWED_STATEMENTS = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)

PROHIBITED_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Command,
    exp.Into,
    exp.Lock,
)

# Functions that should not be available to AI-generated queries.
BLOCKED_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_write_file",
    "pg_ls_dir",
    "pg_stat_file",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "pg_log_backend_memory_contexts",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
}


def validate_sql(sql: str) -> tuple[bool, str]:
    """
    Validate PostgreSQL SQL.
    Only one read-only SELECT-style statement is allowed.
    """

    if not sql or not sql.strip():
        return False, "SQL query cannot be empty."

    try:
        statements = [
            statement
            for statement in sqlglot.parse(sql, read="postgres")
            if statement is not None
        ]

        if len(statements) != 1:
            return False, "Only one SQL statement is allowed."

        statement = statements[0]

        if not isinstance(statement, ALLOWED_STATEMENTS):
            return False, "Only SELECT and read-only CTE queries are allowed."

        # Check the complete query tree, not just the outer statement.
        for node_type in PROHIBITED_NODES:
            if statement.find(node_type):
                return False, (
                    f"Prohibited SQL operation detected: "
                    f"{node_type.__name__}"
                )

        # Block known risky PostgreSQL function calls.
        for function in statement.find_all(exp.Anonymous):
            function_name = function.name.lower()

            if function_name in BLOCKED_FUNCTIONS:
                return False, (
                    f"Prohibited function detected: {function_name}"
                )

        return True, "SQL validation successful."

    except sqlglot.errors.ParseError as error:
        return False, f"Invalid SQL syntax: {error}"

    except Exception as error:
        return False, f"SQL validation failed: {error}"


if __name__ == "__main__":

    test_queries = {
        "Valid SELECT": (
            "SELECT customer_id FROM customers LIMIT 5;"
        ),
        "Valid CTE": (
            "WITH recent_orders AS "
            "(SELECT * FROM orders) "
            "SELECT * FROM recent_orders;"
        ),
        "Valid JOIN": (
            "SELECT o.order_id FROM orders o "
            "JOIN customers c ON o.customer_id = c.customer_id;"
        ),
        "Invalid DELETE": (
            "DELETE FROM customers;"
        ),
        "Invalid DROP": (
            "DROP TABLE customers;"
        ),
        "Multiple statements": (
            "SELECT * FROM customers; DELETE FROM customers;"
        ),
        "Invalid syntax": (
            "SELEC name FROM customers;"
        ),
        "Blocked function": (
            "SELECT pg_sleep(5);"
        ),
        "Nested DELETE": (
            "WITH removed AS (DELETE FROM customers RETURNING *) "
            "SELECT * FROM removed;"
        ),
        "Blocked file function": (
            "SELECT pg_read_file('test.txt');"
        ),
    }

    passed = 0

    for test_name, query in test_queries.items():
        is_valid, message = validate_sql(query)

        expected_valid = test_name in {
            "Valid SELECT",
            "Valid CTE",
            "Valid JOIN",
        }

        test_passed = is_valid == expected_valid

        if test_passed:
            passed += 1

        print(f"\nTEST: {test_name}")
        print(f"VALID: {is_valid}")
        print(f"MESSAGE: {message}")
        print(f"RESULT: {'PASS' if test_passed else 'FAIL'}")

    print(f"\nTOTAL: {passed}/{len(test_queries)} tests passed.")
