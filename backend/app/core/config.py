from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    # =========================
    # APPLICATION
    # =========================

    APP_NAME: str = "SmartMoney AI"
    APP_VERSION: str = "0.9.0"

    ENVIRONMENT: Literal[
        "development",
        "test",
        "production",
    ] = "development"

    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    ENABLE_DOCS: bool = True

    # =========================
    # DATABASE
    # =========================

    DATABASE_URL: str = Field(
        ...,
        repr=False,
    )

    SQL_ECHO: bool = False
    DB_POOL_RECYCLE_SECONDS: int = Field(
        default=1800,
        ge=0,
    )

    # =========================
    # SOLANA / HELIUS
    # =========================

    SOLANA_RPC_URL: str

    HELIUS_API_KEY: str = Field(
        ...,
        repr=False,
    )

    # =========================
    # CORS
    # =========================

    CORS_ORIGINS: str = (
        "http://localhost:5173,"
        "http://localhost:5174,"
        "http://127.0.0.1:5173,"
        "http://127.0.0.1:5174"
    )

    CORS_ALLOW_CREDENTIALS: bool = True

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator(
        "ENVIRONMENT",
        mode="before",
    )
    @classmethod
    def normalize_environment(
        cls,
        value,
    ):
        return str(value).strip().lower()

    @field_validator(
        "LOG_LEVEL",
        mode="before",
    )
    @classmethod
    def normalize_log_level(
        cls,
        value,
    ):
        normalized = str(value).strip().upper()

        allowed_levels = {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }

        if normalized not in allowed_levels:
            raise ValueError(
                "LOG_LEVEL deve essere DEBUG, INFO, "
                "WARNING, ERROR oppure CRITICAL."
            )

        return normalized

    @field_validator(
        "DATABASE_URL",
        "SOLANA_RPC_URL",
        "HELIUS_API_KEY",
    )
    @classmethod
    def validate_required_values(
        cls,
        value: str,
    ):
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "La variabile non può essere vuota."
            )

        if "YOUR_" in normalized.upper():
            raise ValueError(
                "È ancora presente un valore dimostrativo."
            )

        return normalized

    @field_validator("SOLANA_RPC_URL")
    @classmethod
    def validate_solana_rpc_url(
        cls,
        value: str,
    ):
        parsed = urlparse(value)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            raise ValueError(
                "SOLANA_RPC_URL deve essere un URL "
                "HTTP o HTTPS valido."
            )

        return value.rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @model_validator(mode="after")
    def validate_cors_configuration(
        self,
    ) -> Self:
        origins = self.cors_origins

        if not origins:
            raise ValueError(
                "CORS_ORIGINS deve contenere "
                "almeno un'origine."
            )

        if (
            self.CORS_ALLOW_CREDENTIALS
            and "*" in origins
        ):
            raise ValueError(
                "Non usare '*' in CORS_ORIGINS "
                "quando CORS_ALLOW_CREDENTIALS è true."
            )

        for origin in origins:
            if origin == "*":
                continue

            parsed = urlparse(origin)

            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
            ):
                raise ValueError(
                    f"Origine CORS non valida: {origin}"
                )

        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings() 