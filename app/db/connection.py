from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from app.core.config import settings
from app.core.logging_config import get_logger


logger = get_logger(__name__)

DATABASE_URL: URL = settings.database_url

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    connect_args={
        "connect_timeout": settings.db_connect_timeout,
        "application_name": "InsightAgent",
    },
)


def test_connection() -> bool:

    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT version()"))
            database_version = result.scalar_one()

        logger.info("PostgreSQL connection successful.")
        print("Database connected successfully!")
        print(database_version)

        return True

    except Exception:
        logger.exception("PostgreSQL connection failed.")
        raise


if __name__ == "__main__":
    test_connection()

# Backward compatibility for existing modules
query_engine = engine
