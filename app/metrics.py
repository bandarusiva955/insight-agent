"""
Business definitions used by InsightAgent.

Keeping them in one place means the prompt sent to the LLM and the note shown
in the UI can never drift apart. Later phases will replace this module with a
per-workspace metric dictionary stored in the database.
"""

BUSINESS_DEFINITIONS = """BUSINESS DEFINITIONS FOR THIS OLIST DATASET:

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
   - Add LIMIT 100 for detail-row queries when appropriate."""

# Short note shown under the generated SQL in the UI.
METRIC_NOTE = (
    "Definitions: sales = item price of delivered orders (freight excluded). "
    "Amounts are in Brazilian Real (R$). Revenue is not profit."
)

# Column-name keywords that mark a column as a money amount (display only).
MONEY_KEYWORDS = (
    "sales",
    "revenue",
    "price",
    "payment",
    "freight",
    "amount",
    "spend",
    "gmv",
    "aov",
)
