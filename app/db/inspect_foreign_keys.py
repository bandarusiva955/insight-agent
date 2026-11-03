
from pathlib import Path
import pandas as pd

# Locate the project root automatically
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "raw"

# Load the CSV datasets
customers = pd.read_csv(DATA_DIR / "olist_customers_dataset.csv")
orders = pd.read_csv(DATA_DIR / "olist_orders_dataset.csv")
order_items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv")
payments = pd.read_csv(DATA_DIR / "olist_order_payments_dataset.csv")
reviews = pd.read_csv(DATA_DIR / "olist_order_reviews_dataset.csv")
products = pd.read_csv(DATA_DIR / "olist_products_dataset.csv")
sellers = pd.read_csv(DATA_DIR / "olist_sellers_dataset.csv")


# Define foreign-key relationships:
# (child table, child column, parent table, parent column)

relationships = [
    ("orders", "customer_id", customers, "customer_id"),
    ("order_items", "order_id", orders, "order_id"),
    ("order_items", "product_id", products, "product_id"),
    ("order_items", "seller_id", sellers, "seller_id"),
    ("payments", "order_id", orders, "order_id"),
    ("reviews", "order_id", orders, "order_id"),
]

print("\n" + "=" * 70)
print("FOREIGN KEY VALIDATION")
print("=" * 70)

all_valid = True

for child_name, child_column, parent_df, parent_column in relationships:

    child_path = DATA_DIR / {
        "orders": "olist_orders_dataset.csv",
        "order_items": "olist_order_items_dataset.csv",
        "payments": "olist_order_payments_dataset.csv",
        "reviews": "olist_order_reviews_dataset.csv",
    }[child_name]

    child_df = pd.read_csv(child_path)

    # Ignore null foreign-key values for this check
    child_values = child_df[child_column].dropna()

    parent_values = set(parent_df[parent_column].dropna())

    invalid_values = child_values[~child_values.isin(parent_values)]

    invalid_count = len(invalid_values)

    print(f"\nRelationship: {child_name}.{child_column}")
    print(f"Parent column: {parent_column}")
    print(f"Invalid references: {invalid_count}")

    if invalid_count == 0:
        print("STATUS: VALID")
    else:
        print("STATUS: INVALID")
        print("Examples:")
        print(invalid_values.drop_duplicates().head(5).tolist())
        all_valid = False

print("\n" + "=" * 70)

if all_valid:
    print("ALL FOREIGN KEY RELATIONSHIPS ARE VALID.")
else:
    print("SOME FOREIGN KEY RELATIONSHIPS NEED INVESTIGATION.")

print("=" * 70)
