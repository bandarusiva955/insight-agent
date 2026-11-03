
from pathlib import Path
import pandas as pd

DATA_DIR = Path("data/raw")

checks = {
    "customers": {
        "file": "olist_customers_dataset.csv",
        "keys": ["customer_id"],
    },
    "orders": {
        "file": "olist_orders_dataset.csv",
        "keys": ["order_id"],
    },
    "order_items": {
        "file": "olist_order_items_dataset.csv",
        "keys": ["order_id", "order_item_id"],
    },
    "payments": {
        "file": "olist_order_payments_dataset.csv",
        "keys": ["order_id", "payment_sequential"],
    },
    "reviews": {
        "file": "olist_order_reviews_dataset.csv",
        "keys": ["review_id", "order_id"],
    },
    "products": {
        "file": "olist_products_dataset.csv",
        "keys": ["product_id"],
    },
    "sellers": {
        "file": "olist_sellers_dataset.csv",
        "keys": ["seller_id"],
    },
}

for table, details in checks.items():
    df = pd.read_csv(DATA_DIR / details["file"])

    keys = details["keys"]
    duplicate_count = df.duplicated(subset=keys).sum()

    print(f"\nTABLE: {table}")
    print(f"Rows: {len(df)}")
    print(f"Candidate key: {keys}")
    print(f"Duplicate key combinations: {duplicate_count}")

    if duplicate_count == 0:
        print("Candidate key is unique.")
    else:
        print("WARNING: Duplicate key combinations found.")
