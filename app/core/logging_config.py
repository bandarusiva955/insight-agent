import logging

from app.core.config import settings


def configure_logging() -> None:

    log_level = getattr(logging, settings.app_log_level)

    logging.basicConfig(
        level=log_level,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


configure_logging()
