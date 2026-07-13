from logging.config import dictConfig

from backend.app.core.config import settings


def configure_logging() -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": (
                        "%(asctime)s | "
                        "%(levelname)s | "
                        "%(name)s | "
                        "%(message)s"
                    ),
                },
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "handlers": ["default"],
                "level": settings.LOG_LEVEL,
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["default"],
                    "level": settings.LOG_LEVEL,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["default"],
                    "level": settings.LOG_LEVEL,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": "WARNING",
                    "propagate": False,
                },
            },
        }
    ) 