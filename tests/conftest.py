"""
Shared test setup.

Database tests need a PostgreSQL database whose name contains "test", given by
TEST_DATABASE_URL. They load deterministic synthetic data (tests/support) and
are skipped when the variable is not set. The tests that expect the REAL Olist
data are marked `real_data` and only run with INSIGHTAGENT_REAL_DATA=1.
"""

import os
from pathlib import Path

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

if TEST_DATABASE_URL:
    # Must happen before any app module is imported.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ.pop("READONLY_DATABASE_URL", None)
    os.environ.pop("POSTGRES_READONLY_USER", None)

os.environ.setdefault("GEMINI_API_KEY", "test-key")

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "app" / "db" / "schema.sql"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("INSIGHTAGENT_REAL_DATA") == "1":
        return

    skip_real = pytest.mark.skip(
        reason="needs the real Olist data and Gemini key "
        "(set INSIGHTAGENT_REAL_DATA=1)"
    )

    for item in items:
        if "real_data" in item.keywords:
            item.add_marker(skip_real)


@pytest.fixture(scope="session")
def seeded_db():
    """Engine bound to a test database filled with synthetic Olist-shaped data."""

    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")

    from sqlalchemy import text

    from app.db.connection import engine
    from app.db.schema_context import clear_schema_cache
    from tests.support.synthetic_data import LOAD_ORDER, build_synthetic_dataset

    database_name = engine.url.database or ""

    if "test" not in database_name.lower():
        pytest.skip(
            f"Refusing to reset database '{database_name}': "
            "its name must contain 'test'."
        )

    statements = [
        statement.strip()
        for statement in SCHEMA_FILE.read_text().split(";")
        if statement.strip()
    ]

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS app_meta CASCADE"))
        connection.execute(text("DROP SCHEMA IF EXISTS live CASCADE"))
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

        for statement in statements:
            connection.exec_driver_sql(statement)

    data = build_synthetic_dataset()

    with engine.begin() as connection:
        for table in LOAD_ORDER:
            data[table].to_sql(
                table, connection, if_exists="append", index=False, chunksize=1000
            )

    clear_schema_cache()

    return engine
