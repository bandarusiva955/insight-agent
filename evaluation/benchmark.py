"""
50-question benchmark for the text-to-SQL pipeline.

Each question has a reference query written by hand against the schema in
app/db/schema.sql. Questions were chosen to have one defensible answer under
the business definitions in app/metrics.py (delivered orders, item price,
freight excluded), so a mismatch means the model was wrong, not that the
question was ambiguous.

Categories: aggregation, filtering, join, time, ranking, ratio, multi_step.
"""

from dataclasses import dataclass

DELIVERED = "o.order_status = 'delivered'"

CATEGORY_NAME = """COALESCE(
    ct.product_category_name_english, p.product_category_name
)"""


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    question: str
    sql: str

    @property
    def ordered(self) -> bool:
        """Row order matters only when the reference query sorts its output."""

        return "ORDER BY" in self.sql.upper()


def _q(number: int, category: str, question: str, sql: str) -> Question:
    return Question(f"Q{number:02d}", category, question, sql.strip())


QUESTIONS = [
    # ---- aggregation ----------------------------------------------------
    _q(1, "aggregation", "How many orders are there in total?",
       "SELECT COUNT(*) AS total_orders FROM orders"),
    _q(2, "aggregation", "How many unique customers are there?",
       "SELECT COUNT(DISTINCT customer_unique_id) AS unique_customers FROM customers"),
    _q(3, "aggregation", "What is the total revenue from delivered orders?",
       f"""SELECT SUM(oi.price) AS total_revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}"""),
    _q(4, "aggregation", "What is the average item price in delivered orders?",
       f"""SELECT AVG(oi.price) AS avg_item_price
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}"""),
    _q(5, "aggregation", "How many sellers are there?",
       "SELECT COUNT(*) AS total_sellers FROM sellers"),
    _q(6, "aggregation", "How many distinct products were sold in delivered orders?",
       f"""SELECT COUNT(DISTINCT oi.product_id) AS products_sold
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}"""),
    _q(7, "aggregation", "What is the total freight value of delivered orders?",
       f"""SELECT SUM(oi.freight_value) AS total_freight
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}"""),
    _q(8, "aggregation", "What is the average review score?",
       "SELECT AVG(review_score) AS avg_review_score FROM reviews"),

    # ---- filtering ------------------------------------------------------
    _q(9, "filtering", "How many orders were canceled?",
       "SELECT COUNT(*) AS canceled_orders FROM orders WHERE order_status = 'canceled'"),
    _q(10, "filtering", "How many orders came from customers in the state of SP?",
       """SELECT COUNT(*) AS orders_from_sp
FROM orders o JOIN customers c ON c.customer_id = o.customer_id
WHERE c.customer_state = 'SP'"""),
    _q(11, "filtering", "What is the total delivered revenue from customers in RJ?",
       f"""SELECT SUM(oi.price) AS revenue
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED} AND c.customer_state = 'RJ'"""),
    _q(12, "filtering", "How many delivered orders were placed in 2018?",
       f"""SELECT COUNT(*) AS orders
FROM orders o
WHERE {DELIVERED} AND EXTRACT(YEAR FROM o.order_purchase_timestamp) = 2018"""),
    _q(13, "filtering", "How many reviews have a score of 1?",
       "SELECT COUNT(*) AS one_star_reviews FROM reviews WHERE review_score = 1"),
    _q(14, "filtering", "How many order items have a price above 500?",
       "SELECT COUNT(*) AS expensive_items FROM order_items WHERE price > 500"),
    _q(15, "filtering",
       "How many delivered orders arrived after the estimated delivery date?",
       f"""SELECT COUNT(*) AS late_orders
FROM orders o
WHERE {DELIVERED}
  AND o.order_delivered_customer_date > o.order_estimated_delivery_date"""),
    _q(16, "filtering", "How many orders were paid with a credit card?",
       """SELECT COUNT(DISTINCT order_id) AS credit_card_orders
FROM payments WHERE payment_type = 'credit_card'"""),

    # ---- join -----------------------------------------------------------
    _q(17, "join", "What is the delivered revenue by customer state?",
       f"""SELECT c.customer_state, SUM(oi.price) AS revenue
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}
GROUP BY c.customer_state
ORDER BY revenue DESC"""),
    _q(18, "join", "What are the top 5 seller states by delivered revenue?",
       f"""SELECT s.seller_state, SUM(oi.price) AS revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN sellers s ON s.seller_id = oi.seller_id
WHERE {DELIVERED}
GROUP BY s.seller_state
ORDER BY revenue DESC
LIMIT 5"""),
    _q(19, "join",
       "What are the top 10 product categories by number of delivered orders? "
       "Use English category names.",
       f"""SELECT {CATEGORY_NAME} AS category, COUNT(DISTINCT o.order_id) AS orders
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN category_translation ct ON ct.product_category_name = p.product_category_name
WHERE {DELIVERED}
GROUP BY 1
ORDER BY orders DESC, category
LIMIT 10"""),
    _q(20, "join", "What is the average review score by customer state?",
       """SELECT c.customer_state, AVG(r.review_score) AS avg_review_score
FROM reviews r
JOIN orders o ON o.order_id = r.order_id
JOIN customers c ON c.customer_id = o.customer_id
GROUP BY c.customer_state
ORDER BY c.customer_state"""),
    _q(21, "join", "Which payment type has the highest total payment value?",
       """SELECT payment_type, SUM(payment_value) AS total_value
FROM payments
GROUP BY payment_type
ORDER BY total_value DESC
LIMIT 1"""),
    _q(22, "join", "How many orders were paid with each payment type?",
       """SELECT payment_type, COUNT(DISTINCT order_id) AS orders
FROM payments
GROUP BY payment_type
ORDER BY orders DESC, payment_type"""),
    _q(23, "join",
       "What is the average delivered order value by customer state, "
       "using item prices only?",
       f"""SELECT customer_state, AVG(order_value) AS avg_order_value
FROM (
    SELECT c.customer_state, o.order_id, SUM(oi.price) AS order_value
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    JOIN order_items oi ON oi.order_id = o.order_id
    WHERE {DELIVERED}
    GROUP BY c.customer_state, o.order_id
) t
GROUP BY customer_state
ORDER BY customer_state"""),
    _q(24, "join", "Who are the top 10 sellers by delivered revenue?",
       f"""SELECT oi.seller_id, SUM(oi.price) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}
GROUP BY oi.seller_id
ORDER BY revenue DESC, oi.seller_id
LIMIT 10"""),

    # ---- time -----------------------------------------------------------
    _q(25, "time", "What is the monthly delivered revenue?",
       f"""SELECT date_trunc('month', o.order_purchase_timestamp) AS month,
       SUM(oi.price) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}
GROUP BY 1
ORDER BY 1"""),
    _q(26, "time", "How many orders were placed each year?",
       """SELECT EXTRACT(YEAR FROM order_purchase_timestamp) AS year,
       COUNT(*) AS orders
FROM orders
GROUP BY 1
ORDER BY 1"""),
    _q(27, "time", "Which month had the most delivered orders?",
       f"""SELECT date_trunc('month', o.order_purchase_timestamp) AS month,
       COUNT(*) AS orders
FROM orders o
WHERE {DELIVERED}
GROUP BY 1
ORDER BY orders DESC
LIMIT 1"""),
    _q(28, "time", "How many orders were canceled each month?",
       """SELECT date_trunc('month', order_purchase_timestamp) AS month,
       COUNT(*) AS canceled_orders
FROM orders
WHERE order_status = 'canceled'
GROUP BY 1
ORDER BY 1"""),
    _q(29, "time", "What was the total delivered revenue in 2017?",
       f"""SELECT SUM(oi.price) AS revenue_2017
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}
  AND EXTRACT(YEAR FROM o.order_purchase_timestamp) = 2017"""),
    _q(30, "time", "How many orders were placed on each day of the week?",
       """SELECT EXTRACT(DOW FROM order_purchase_timestamp) AS day_of_week,
       COUNT(*) AS orders
FROM orders
GROUP BY 1
ORDER BY 1"""),
    _q(31, "time", "What is the average delivery time in days for delivered orders?",
       f"""SELECT AVG(EXTRACT(EPOCH FROM (o.order_delivered_customer_date
                                  - o.order_purchase_timestamp)) / 86400.0)
       AS avg_delivery_days
FROM orders o
WHERE {DELIVERED} AND o.order_delivered_customer_date IS NOT NULL"""),
    _q(32, "time", "What is the average delivery time in days for each purchase month?",
       f"""SELECT date_trunc('month', o.order_purchase_timestamp) AS month,
       AVG(EXTRACT(EPOCH FROM (o.order_delivered_customer_date
                               - o.order_purchase_timestamp)) / 86400.0)
       AS avg_delivery_days
FROM orders o
WHERE {DELIVERED} AND o.order_delivered_customer_date IS NOT NULL
GROUP BY 1
ORDER BY 1"""),

    # ---- ranking --------------------------------------------------------
    _q(33, "ranking", "What are the top 10 product categories by delivered sales?",
       f"""SELECT {CATEGORY_NAME} AS category, SUM(oi.price) AS total_sales
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN category_translation ct ON ct.product_category_name = p.product_category_name
WHERE {DELIVERED}
GROUP BY 1
ORDER BY total_sales DESC
LIMIT 10"""),
    _q(34, "ranking", "Which 5 products have the highest average price?",
       """SELECT product_id, AVG(price) AS avg_price
FROM order_items
GROUP BY product_id
ORDER BY avg_price DESC, product_id
LIMIT 5"""),
    _q(35, "ranking", "Which 5 customer states have the most delivered orders?",
       f"""SELECT c.customer_state, COUNT(*) AS orders
FROM orders o JOIN customers c ON c.customer_id = o.customer_id
WHERE {DELIVERED}
GROUP BY c.customer_state
ORDER BY orders DESC, c.customer_state
LIMIT 5"""),
    _q(36, "ranking", "What are the 5 product categories with the lowest delivered sales?",
       f"""SELECT {CATEGORY_NAME} AS category, SUM(oi.price) AS total_sales
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN category_translation ct ON ct.product_category_name = p.product_category_name
WHERE {DELIVERED}
GROUP BY 1
ORDER BY total_sales ASC, category
LIMIT 5"""),
    _q(37, "ranking", "Which 3 payment types are used most often?",
       """SELECT payment_type, COUNT(*) AS payments
FROM payments
GROUP BY payment_type
ORDER BY payments DESC, payment_type
LIMIT 3"""),
    _q(38, "ranking", "Who are the top 10 customers by delivered spend?",
       f"""SELECT c.customer_unique_id, SUM(oi.price) AS total_spend
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}
GROUP BY c.customer_unique_id
ORDER BY total_spend DESC, c.customer_unique_id
LIMIT 10"""),

    # ---- ratio ----------------------------------------------------------
    _q(39, "ratio", "What percentage of orders were canceled?",
       """SELECT 100.0 * COUNT(*) FILTER (WHERE order_status = 'canceled')
       / COUNT(*) AS canceled_pct
FROM orders"""),
    _q(40, "ratio", "What percentage of delivered orders arrived late?",
       f"""SELECT 100.0 * COUNT(*) FILTER (
           WHERE o.order_delivered_customer_date > o.order_estimated_delivery_date)
       / COUNT(*) AS late_pct
FROM orders o
WHERE {DELIVERED} AND o.order_delivered_customer_date IS NOT NULL"""),
    _q(41, "ratio", "What percentage of delivered revenue came from customers in SP?",
       f"""SELECT 100.0 * SUM(oi.price) FILTER (WHERE c.customer_state = 'SP')
       / SUM(oi.price) AS sp_pct
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}"""),
    _q(42, "ratio", "What is the average number of items per delivered order?",
       f"""SELECT COUNT(*)::numeric / COUNT(DISTINCT o.order_id) AS items_per_order
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}"""),
    _q(43, "ratio", "What is the average number of installments for credit card payments?",
       """SELECT AVG(payment_installments) AS avg_installments
FROM payments WHERE payment_type = 'credit_card'"""),
    _q(44, "ratio", "What percentage of reviews have a score of 5?",
       """SELECT 100.0 * COUNT(*) FILTER (WHERE review_score = 5)
       / COUNT(*) AS five_star_pct
FROM reviews"""),

    # ---- multi_step -----------------------------------------------------
    _q(45, "multi_step",
       "Which customer state has the highest average delivery time for delivered orders?",
       f"""SELECT c.customer_state,
       AVG(EXTRACT(EPOCH FROM (o.order_delivered_customer_date
                               - o.order_purchase_timestamp)) / 86400.0)
       AS avg_delivery_days
FROM orders o JOIN customers c ON c.customer_id = o.customer_id
WHERE {DELIVERED} AND o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
ORDER BY avg_delivery_days DESC
LIMIT 1"""),
    _q(46, "multi_step", "How many customers placed more than one order?",
       """SELECT COUNT(*) AS repeat_customers
FROM (
    SELECT c.customer_unique_id
    FROM orders o JOIN customers c ON c.customer_id = o.customer_id
    GROUP BY c.customer_unique_id
    HAVING COUNT(DISTINCT o.order_id) > 1
) t"""),
    _q(47, "multi_step", "What is the delivered revenue by quarter?",
       f"""SELECT date_trunc('quarter', o.order_purchase_timestamp) AS quarter,
       SUM(oi.price) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}
GROUP BY 1
ORDER BY 1"""),
    _q(48, "multi_step", "How many delivered orders contained more than one item?",
       f"""SELECT COUNT(*) AS multi_item_orders
FROM (
    SELECT o.order_id
    FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
    WHERE {DELIVERED}
    GROUP BY o.order_id
    HAVING COUNT(*) > 1
) t"""),
    _q(49, "multi_step", "What is the average delivered revenue per unique customer?",
       f"""SELECT SUM(oi.price) / COUNT(DISTINCT c.customer_unique_id)
       AS revenue_per_customer
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE {DELIVERED}"""),
    _q(50, "multi_step", "Which seller state has the most sellers?",
       """SELECT seller_state, COUNT(*) AS sellers
FROM sellers
GROUP BY seller_state
ORDER BY sellers DESC, seller_state
LIMIT 1"""),
]
