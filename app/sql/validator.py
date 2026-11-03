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
    # file system, large objects, cross-database access
    "pg_read_file",
    "pg_read_binary_file",
    "pg_write_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    # server control
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "pg_log_backend_memory_contexts",
    # resource abuse and session tampering
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "set_config",
    "current_setting",
    "pg_advisory_lock",
    "pg_advisory_xact_lock",
    "pg_try_advisory_lock",
    "pg_try_advisory_xact_lock",
}

# Only the public schema holds business data. Anything else (pg_catalog,
# information_schema, app_meta, ...) is off limits to generated SQL.
ALLOWED_SCHEMAS = {"", "public"}


def validate_sql(sql: str, allowed_tables=None) -> tuple[bool, str]:
    """
    Validate PostgreSQL SQL.

    Only one read-only SELECT-style statement is allowed. System catalogs
    and non-public schemas are always rejected. When allowed_tables is
    given, every table the query reads must be one of them (names defined
    by the query's own WITH clauses are fine).
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

        # Table access control.
        cte_names = {
            cte.alias.lower()
            for cte in statement.find_all(exp.CTE)
            if cte.alias
        }

        allowed = (
            None
            if allowed_tables is None
            else {name.lower() for name in allowed_tables}
        )

        for table in statement.find_all(exp.Table):
            table_name = table.name.lower()
            schema_name = table.db.lower()

            # Table-valued functions such as generate_series() have no name;
            # the function checks above and the statement timeout cover them.
            if not table_name:
                continue

            if schema_name not in ALLOWED_SCHEMAS:
                return False, (
                    f"Access to schema '{schema_name}' is not allowed."
                )

            if table_name.startswith("pg_"):
                return False, (
                    f"Access to system table '{table_name}' is not allowed."
                )

            if (
                allowed is not None
                and table_name not in allowed
                and not (schema_name == "" and table_name in cte_names)
            ):
                return False, (
                    f"Table '{table_name}' is not available. "
                    f"Use only these tables: {', '.join(sorted(allowed))}."
                )

        return True, "SQL validation successful."

    except sqlglot.errors.ParseError as error:
        return False, f"Invalid SQL syntax: {error}"

    except Exception as error:
        return False, f"SQL validation failed: {error}"
