from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.schema_context import get_schema_context


logger = get_logger(__name__)


def _create_gemini_client() -> genai.Client:

    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. "
            "Add it to your local .env file."
        )

    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=settings.gemini_timeout_ms
        ),
    )


def generate_sql(question: str) -> str:

    if not question or not question.strip():
        raise ValueError("Please provide a business question.")

    logger.info("Loading database schema.")

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
   - Do not include freight unless explicitly requested.
   - Do not describe revenue as profit.

2. PRODUCT CATEGORIES:
   - Join order_items to products using product_id.
   - Use category_translation for English category names.
   - Join products.product_category_name to
     category_translation.product_category_name.
   - Use LEFT JOIN so untranslated categories are not discarded.
   - Use COALESCE(
       category_translation.product_category_name_english,
       products.product_category_name
     ) for the category name.

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

    client = _create_gemini_client()

    models_to_try = list(dict.fromkeys([
        settings.gemini_model,
        settings.gemini_fallback_model,
    ]))

    errors = []

    for model in models_to_try:

        try:
            logger.info("Generating SQL using model: %s", model)

            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )

            sql = (response.text or "").strip()

            if not sql:
                raise RuntimeError(
                    f"{model} returned an empty response."
                )

            logger.info("SQL generation completed.")
            return sql

        except APIError as error:
            errors.append(f"{model}: {error}")

            logger.warning(
                "Model %s unavailable. Trying fallback.",
                model,
            )

    raise RuntimeError(
        "Gemini models are currently unavailable.\n"
        + "\n".join(errors)
    )


if __name__ == "__main__":

    question = "Show me the top 10 product categories by sales."

    try:
        print("\nGENERATED SQL:\n")
        print(generate_sql(question))

    except Exception:
        logger.exception("SQL generation failed.")
