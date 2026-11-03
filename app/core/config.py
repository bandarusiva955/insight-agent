from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8-sig",
        case_sensitive=False,
        extra="ignore",
    )

    # PostgreSQL
    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: str = Field(min_length=1)
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(ge=1, le=65535)

    # Gemini
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    gemini_fallback_model: str = "gemini-3.8-flash"
    gemini_timeout_ms: int = Field(default=120000, ge=1000)

    # Application
    app_log_level: Literal[
        "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    ] = "INFO"

    # Database connection pool
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout: int = Field(default=30, ge=1)
    db_pool_recycle: int = Field(default=1800, ge=60)
    db_connect_timeout: int = Field(default=10, ge=1)

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
