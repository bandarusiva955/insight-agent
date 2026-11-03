import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.db.schema_context import get_schema_context

load_dotenv(override=True)

API_KEY = os.getenv("GEMINI_API_KEY")
PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
FALLBACK_MODEL = "gemini-3.8-flash"

if not API_KEY:
    raise ValueError("GEMINI_API_KEY is missing from .env")

client = genai.Client(
    api_key=API_KEY,
    http_options=types.HttpOptions(timeout=120000)
)


def generate_sql(question: str) -> str:
    """Convert a business question into PostgreSQL SQL."""

    if not question or not question.strip():
        raise ValueError("Please provide a business question.")

    print("Loading database schema...", flush=True)
    schema = get_schema_context()

    prompt = f"""
You are a senior PostgreSQL developer building an AI data analyst.

Convert the user's business question into one accurate PostgreSQL query.

DATABASE SCHEMA:
{schema}

BUSINESS DEFINITIONS FOR THIS OLIST DATASET:

1. SALES AND REVENUE:
   - By default, calculate completed sales using delivered orders only.
   - Join orders to order_items using order_id.
   - Filter using orders.order_status = 'delivered'.
   - Product sales revenue means SUM(order_items.price).
   - Do not include freight unless the user explicitly asks for it.
   - Do not describe revenue as profit.

2. PRODUCT CATEGORIES:
   - Join order_items to products using product_id.
   - Use category_translation to obtain English category names.
   - Join products.product_category_name to
     category_translation.product_category_name.
   - Use LEFT JOIN so untranslated categories are not discarded.
   - Display COALESCE(
       category_translation.product_category_name_english,
       products.product_category_name
     ) as the category name.

3. ORDER COUNTS:
   - Use COUNT(DISTINCT orders.order_id) when counting orders.
   - Do not confuse order items, payment records and unique orders.

4. GENERAL:
   - Follow the actual schema and foreign keys.
   - Avoid duplicate counting caused by one-to-many joins.
   - Use meaningful column aliases.
   - Use appropriate GROUP BY and ORDER BY clauses.
   - Add LIMIT 100 for detail-row queries when appropriate.

STRICT SQL RULES:
- PostgreSQL syntax only.
- Generate only one SELECT or read-only WITH query.
- Never generate data modification or schema modification statements.
- Never invent tables or columns.
- Return SQL only, without Markdown fences or explanations.

USER QUESTION:
{question}
"""

    models_to_try = list(dict.fromkeys([
        PRIMARY_MODEL,
        FALLBACK_MODEL
    ]))

    errors = []

    for model in models_to_try:
        try:
            print(f"Generating SQL with {model}...", flush=True)

            response = client.models.generate_content(
                model=model,
                contents=prompt
            )

            sql = (response.text or "").strip()

            if not sql:
                raise ValueError(
                    f"{model} returned an empty response."
                )

            print(
                f"SQL generated successfully using {model}.",
                flush=True
            )

            return sql

        except APIError as error:
            errors.append(f"{model}: {error}")
            print(
                f"{model} unavailable. Trying fallback...",
                flush=True
            )

    raise RuntimeError(
        "Gemini models are currently unavailable. "
        "Please try again later.\n" + "\n".join(errors)
    )


if __name__ == "__main__":
    question = "Show me the top 10 product categories by sales."

    try:
        sql = generate_sql(question)
        print("\nGENERATED SQL:\n")
        print(sql)

    except Exception as error:
        print(f"\nSQL generation failed: {error}")
