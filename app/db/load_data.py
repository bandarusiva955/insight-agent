
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from connection import engine


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "raw"

# Load parent tables before child tables
TABLES = [
    ("customers", "olist_customers_dataset.csv"),
    ("products", "olist_products_dataset.csv"),
    ("sellers", "olist_sellers_dataset.csv"),
    ("category_translation", "product_category_name_translation.csv"),
    ("orders", "olist_orders_dataset.csv"),
    ("order_items", "olist_order_items_dataset.csv"),
    ("payments", "olist_order_payments_dataset.csv"),
    ("reviews", "olist_order_reviews_dataset.csv"),
]

# Columns that should be converted to timestamps
DATE_COLUMNS = {
    "orders": [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "order_items": ["shipping_limit_date"],
    "reviews": [
        "review_creation_date",
        "review_answer_timestamp",
    ],
}

# Nullable integer columns
INTEGER_COLUMNS = {
    "customers": ["customer_zip_code_prefix"],
    "sellers": ["seller_zip_code_prefix"],
    "products": [
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
    ],
    "order_items": ["order_item_id"],
    "payments": [
        "payment_sequential",
        "payment_installments",
    ],
    "reviews": ["review_score"],
}

# Numeric columns
NUMERIC_COLUMNS = {
    "products": [
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
    "order_items": ["price", "freight_value"],
    "payments": ["payment_value"],
}


def prepare_dataframe(df, table_name):
    """Convert CSV values into database-friendly types."""

    # Convert date columns
    for column in DATE_COLUMNS.get(table_name, []):
        df[column] = pd.to_datetime(
            df[column],
            errors="coerce"
        )

    # Convert nullable integer columns
    for column in INTEGER_COLUMNS.get(table_name, []):
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        ).astype("Int64")

    # Convert numeric columns
    for column in NUMERIC_COLUMNS.get(table_name, []):
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    return df


def check_empty_tables():
    """Prevent accidental duplicate imports."""

    with engine.connect() as connection:
        for table_name, _ in TABLES:
            count = connection.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar_one()

            if count > 0:
                raise RuntimeError(
                    f"Table '{table_name}' already contains "
                    f"{count} rows. Import stopped."
                )


def load_table(table_name, file_name):
    """Load one CSV file into its PostgreSQL table."""

    file_path = DATA_DIR / file_name

    if not file_path.exists():
        raise FileNotFoundError(
            f"CSV file not found: {file_path}"
        )

    print(f"\nLoading {table_name}...")

    df = pd.read_csv(file_path)
    df = prepare_dataframe(df, table_name)

    row_count = len(df)

    # Insert the entire table in one transaction
    with engine.begin() as connection:
        df.to_sql(
            name=table_name,
            con=connection,
            if_exists="append",
            index=False,
            chunksize=2000,
        )

    print(f"Successfully loaded {row_count:,} rows.")

    return row_count


def verify_data():
    """Display final database row counts."""

    print("\n========== DATABASE VERIFICATION ==========")

    with engine.connect() as connection:
        for table_name, _ in TABLES:
            count = connection.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar_one()

            print(f"{table_name:<25} {count:>10,} rows")

    print("\nData loading and verification completed.")


def main():
    print("Starting Olist CSV import...")

    check_empty_tables()

    for table_name, file_name in TABLES:
        load_table(table_name, file_name)

    verify_data()


if __name__ == "__main__":
    main()
