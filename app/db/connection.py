import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


def _build_url(user_var: str, password_var: str) -> str:
    """Build a local Postgres URL from the POSTGRES_* variables."""
    return (
        f"postgresql+psycopg://"
        f"{os.getenv(user_var)}:"
        f"{os.getenv(password_var)}@"
        f"{os.getenv('POSTGRES_HOST', '127.0.0.1')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB')}"
    )


def _normalize(url: str) -> str:
    """Accept the plain postgres:// URLs that hosted providers give you."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


# Admin/owner connection: schema inspection, data loading, audit log.
DATABASE_URL = _normalize(
    os.getenv("DATABASE_URL")
    or _build_url("POSTGRES_USER", "POSTGRES_PASSWORD")
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# Query connection: used to run AI-generated SQL.
# Preferred: a dedicated read-only role (see app/db/create_readonly_role.sql).
# If it is not configured, fall back to the admin engine so nothing breaks;
# the executor still enforces a read-only transaction either way.
_readonly_url = os.getenv("READONLY_DATABASE_URL")

if not _readonly_url and os.getenv("POSTGRES_READONLY_USER"):
    _readonly_url = _build_url(
        "POSTGRES_READONLY_USER", "POSTGRES_READONLY_PASSWORD"
    )

if _readonly_url:
    query_engine = create_engine(
        _normalize(_readonly_url), pool_pre_ping=True
    )
    USING_READONLY_ROLE = True
else:
    query_engine = engine
    USING_READONLY_ROLE = False


def test_connection():
    with engine.connect() as connection:
        result = connection.execute(text("SELECT version()"))
        print("Database connected successfully!")
        print(result.scalar())
        print(f"Read-only query role in use: {USING_READONLY_ROLE}")


if __name__ == "__main__":
    test_connection()
