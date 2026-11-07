import unittest

import pytest

from sqlalchemy import text

from app.db.connection import engine
from app.llm.sql_generator import generate_sql
from app.sql.validator import validate_sql
from app.sql.executor import execute_sql


QUESTION = (
    "Show me the top 10 product categories by delivered product sales. "
    "Use only delivered orders, exclude freight, use English category "
    "names where available, and return columns named category_name "
    "and total_sales."
)

REFERENCE_SQL = """
SELECT
    COALESCE(
        ct.product_category_name_english,
        p.product_category_name
    ) AS category_name,
    SUM(oi.price) AS total_sales
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


@pytest.mark.real_data
class TestGeneratedSQLAccuracy(unittest.TestCase):

    def test_generated_sql_matches_reference(self):
        print("\nGenerating SQL with Gemini...", flush=True)

        generated_sql = generate_sql(QUESTION)

        print("\nGenerated SQL:")
        print(generated_sql)

        valid, message = validate_sql(generated_sql)
        self.assertTrue(valid, f"Generated SQL rejected: {message}")

        actual = execute_sql(generated_sql)

        with engine.connect() as connection:
            expected = connection.execute(
                text(REFERENCE_SQL)
            ).mappings().all()

        self.assertIn("category_name", actual.columns)
        self.assertIn("total_sales", actual.columns)
        self.assertEqual(len(actual), 10)

        expected_results = {
            row["category_name"]: round(float(row["total_sales"]), 2)
            for row in expected
        }

        actual_results = {
            row["category_name"]: round(float(row["total_sales"]), 2)
            for row in actual.to_dict(orient="records")
        }

        self.assertEqual(
            actual_results,
            expected_results,
            "Generated SQL results differ from the trusted reference."
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
