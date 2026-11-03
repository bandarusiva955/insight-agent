"""Unit tests for the SQL validator. No database or API key needed."""

import pytest

from app.sql.validator import validate_sql

OLIST_TABLES = {
    "customers",
    "orders",
    "order_items",
    "order_payments",
    "order_reviews",
    "products",
    "sellers",
    "category_translation",
}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT customer_id FROM customers LIMIT 5;",
        "SELECT o.order_id FROM orders o "
        "JOIN customers c ON o.customer_id = c.customer_id;",
        "WITH recent AS (SELECT order_id FROM orders LIMIT 5) "
        "SELECT order_id FROM recent;",
        "SELECT * FROM public.orders;",
        "SELECT * FROM ORDERS;",
        "SELECT * FROM (SELECT order_id FROM orders) t;",
        "SELECT order_id FROM orders UNION SELECT order_id FROM order_items;",
        "SELECT count(*) FROM generate_series(1, 10) g;",
    ],
)
def test_valid_queries_are_accepted(sql):
    valid, message = validate_sql(sql, allowed_tables=OLIST_TABLES)
    assert valid, message


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customers;",
        "DROP TABLE customers;",
        "UPDATE orders SET order_status = 'x';",
        "INSERT INTO customers VALUES (1);",
        "TRUNCATE orders;",
        "SELECT * FROM customers; DELETE FROM customers;",
        "WITH r AS (DELETE FROM customers RETURNING *) SELECT * FROM r;",
        "SELECT * INTO new_table FROM customers;",
        "SELECT * FROM orders FOR UPDATE;",
        "COPY orders TO '/tmp/x';",
        "SET ROLE postgres;",
        "SELEC name FROM customers;",
        "",
        "   ",
    ],
)
def test_unsafe_or_invalid_statements_are_rejected(sql):
    valid, _ = validate_sql(sql, allowed_tables=OLIST_TABLES)
    assert not valid


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(5);",
        "SELECT pg_catalog.pg_sleep(5);",
        "SELECT pg_read_file('/etc/passwd');",
        "SELECT pg_ls_dir('.');",
        "SELECT lo_import('/etc/passwd');",
        "SELECT set_config('transaction_read_only', 'off', true);",
        "SELECT current_setting('data_directory');",
        "SELECT pg_advisory_lock(1);",
    ],
)
def test_dangerous_functions_are_rejected(sql):
    valid, _ = validate_sql(sql, allowed_tables=OLIST_TABLES)
    assert not valid


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM pg_shadow;",
        "SELECT * FROM pg_catalog.pg_shadow;",
        "SELECT * FROM information_schema.tables;",
        "SELECT * FROM app_meta.query_audit;",
        "SELECT * FROM orders WHERE order_id IN "
        "(SELECT pid FROM pg_stat_activity);",
    ],
)
def test_system_and_non_public_schemas_are_rejected_even_without_allow_list(sql):
    valid, _ = validate_sql(sql)
    assert not valid


def test_unknown_table_is_rejected_with_allow_list():
    valid, message = validate_sql(
        "SELECT * FROM salaries;", allowed_tables=OLIST_TABLES
    )
    assert not valid
    assert "salaries" in message
    # The message lists real tables so the LLM can self-correct.
    assert "orders" in message


def test_cte_name_is_not_mistaken_for_a_missing_table():
    valid, message = validate_sql(
        "WITH totals AS (SELECT order_id FROM orders) SELECT * FROM totals;",
        allowed_tables=OLIST_TABLES,
    )
    assert valid, message


def test_cte_name_cannot_hide_a_forbidden_schema():
    valid, _ = validate_sql(
        "WITH totals AS (SELECT * FROM pg_catalog.pg_shadow) "
        "SELECT * FROM totals;",
        allowed_tables=OLIST_TABLES,
    )
    assert not valid
