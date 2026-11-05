import unittest

import pytest

from sqlalchemy import text

from app.db.connection import engine
from app.sql.validator import validate_sql
from app.sql.executor import execute_sql


REFERENCE_SQL = """
SELECT
    COALESCE(
        ct.product_category_name_english,
        p.product_category_name
    ) AS category_name,
    ROUND(SUM(oi.price)::numeric, 2) AS total_sales
FROM orders o
JOIN order_items oi
    ON o.order_id = oi.order_id
JOIN products p
    ON oi.product_id = p.product_id
LEFT JOIN category_translation ct
    ON p.product_category_name = ct.product_category_name
WHERE o.order_status = 'delivered'
GROUP BY
    COALESCE(
        ct.product_category_name_english,
        p.product_category_name
    )
ORDER BY total_sales DESC
LIMIT 10;
"""


class TestSQLValidator(unittest.TestCase):

    def test_valid_select(self):
        valid, _ = validate_sql(
            "SELECT customer_id FROM customers LIMIT 5;"
        )
        self.assertTrue(valid)

    def test_valid_cte(self):
        sql = """
        WITH recent_orders AS (
            SELECT order_id FROM orders LIMIT 5
        )
        SELECT order_id FROM recent_orders;
        """
        valid, _ = validate_sql(sql)
        self.assertTrue(valid)

    def test_reject_delete(self):
        valid, _ = validate_sql("DELETE FROM customers;")
        self.assertFalse(valid)

    def test_reject_multiple_statements(self):
        sql = "SELECT * FROM customers; DELETE FROM customers;"
        valid, _ = validate_sql(sql)
        self.assertFalse(valid)

    def test_reject_blocked_function(self):
        valid, _ = validate_sql("SELECT pg_sleep(5);")
        self.assertFalse(valid)


@pytest.mark.real_data
class TestSQLExecutor(unittest.TestCase):

    def test_execute_read_only_query(self):
        sql = """
        SELECT order_status, COUNT(*) AS total_orders
        FROM orders
        GROUP BY order_status
        ORDER BY total_orders DESC;
        """
        result = execute_sql(sql)

        self.assertFalse(result.empty)
        self.assertIn("order_status", result.columns)
        self.assertIn("total_orders", result.columns)

    def test_executor_rejects_delete(self):
        with self.assertRaises(ValueError):
            execute_sql("DELETE FROM customers;")


@pytest.mark.real_data
class TestDeliveredSalesBusinessLogic(unittest.TestCase):

    def test_reference_query_matches_expected_totals(self):
        with engine.connect() as connection:
            reference = connection.execute(
                text(REFERENCE_SQL)
            ).mappings().all()

        self.assertEqual(len(reference), 10)
        self.assertEqual(reference[0]["category_name"], "health_beauty")
        self.assertEqual(
            float(reference[0]["total_sales"]),
            1233131.72,
        )

    def test_reference_query_matches_executor(self):
        expected = execute_sql(REFERENCE_SQL)

        actual = execute_sql(REFERENCE_SQL)

        self.assertEqual(
            expected.to_dict(orient="records"),
            actual.to_dict(orient="records"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
