from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import (
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


PROJECT_ROOT = Path(
    __file__
).resolve().parents[3]

ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    # =========================
    # APPLICATION
    # =========================

    APP_NAME: str = "SmartMoney AI"
    APP_VERSION: str = "1.0.0"

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
    # AUTOMATION / SECURITY
    # =========================

    AUTOMATION_API_KEY: str = Field(
        default="",
        repr=False,
    )

    PAPER_TRADING_API_KEY: str = Field(
        default="",
        repr=False,
    )

    LIVE_TRADING_API_KEY: str = Field(
        default="",
        repr=False,
    )

    PUBLIC_DISCOVERY_COOLDOWN_SECONDS: int = Field(
        default=120,
        ge=10,
        le=3600,
    )

    # =========================
    # JUPITER
    # =========================

    JUPITER_API_KEY: str = Field(
        default="",
        repr=False,
    )

    JUPITER_PRICE_API_URL: str = (
        "https://api.jup.ag/price/v3"
    )

    JUPITER_PRICE_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
    )

    JUPITER_PRICE_CACHE_SECONDS: int = Field(
        default=15,
        ge=1,
        le=300,
    )

    JUPITER_SWAP_API_URL: str = (
        "https://api.jup.ag/swap/v2"
    )

    JUPITER_SWAP_TIMEOUT_SECONDS: float = Field(
        default=20.0,
        ge=2.0,
        le=60.0,
    )

    # =========================
    # LIVE TRADING WALLET
    # =========================

    LIVE_TRADING_WALLET_ADDRESS: str = ""

    LIVE_TRADING_PRIVATE_KEY: str = Field(
        default="",
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
        return str(
            value
        ).strip().lower()

    @field_validator(
        "LOG_LEVEL",
        mode="before",
    )
    @classmethod
    def normalize_log_level(
        cls,
        value,
    ):
        normalized = str(
            value
        ).strip().upper()

        allowed_levels = {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }

        if normalized not in allowed_levels:
            raise ValueError(
                "LOG_LEVEL deve essere DEBUG, "
                "INFO, WARNING, ERROR oppure "
                "CRITICAL."
            )

        return normalized

    @field_validator(
        "DATABASE_URL",
        mode="before",
    )
    @classmethod
    def normalize_database_url(
        cls,
        value,
    ):
        normalized = str(
            value
        ).strip()

        if normalized.startswith(
            "postgres://"
        ):
            return (
                "postgresql+psycopg://"
                + normalized[
                    len("postgres://") :
                ]
            )

        if normalized.startswith(
            "postgresql://"
        ):
            return (
                "postgresql+psycopg://"
                + normalized[
                    len("postgresql://") :
                ]
            )

        return normalized

    @field_validator(
        "AUTOMATION_API_KEY",
        "PAPER_TRADING_API_KEY",
        "LIVE_TRADING_API_KEY",
        "JUPITER_API_KEY",
        "LIVE_TRADING_WALLET_ADDRESS",
        "LIVE_TRADING_PRIVATE_KEY",
        mode="before",
    )
    @classmethod
    def normalize_optional_secrets(
        cls,
        value,
    ):
        if value is None:
            return ""

        return str(
            value
        ).strip()

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
                "È ancora presente un valore "
                "dimostrativo."
            )

        return normalized

    @field_validator(
        "SOLANA_RPC_URL",
        "JUPITER_PRICE_API_URL",
        "JUPITER_SWAP_API_URL",
    )
    @classmethod
    def validate_http_url(
        cls,
        value: str,
    ):
        normalized = (
            value.strip().rstrip("/")
        )

        parsed = urlparse(
            normalized
        )

        if (
            parsed.scheme
            not in {"http", "https"}
            or not parsed.netloc
        ):
            raise ValueError(
                "La variabile deve essere un URL "
                "HTTP o HTTPS valido."
            )

        return normalized

    @field_validator(
        "LIVE_TRADING_WALLET_ADDRESS"
    )
    @classmethod
    def validate_optional_wallet_address(
        cls,
        value: str,
    ):
        if not value:
            return value

        if "YOUR_" in value.upper():
            raise ValueError(
                "LIVE_TRADING_WALLET_ADDRESS "
                "contiene un valore dimostrativo."
            )

        if not 32 <= len(value) <= 44:
            raise ValueError(
                "LIVE_TRADING_WALLET_ADDRESS "
                "non ha una lunghezza Solana valida."
            )

        return value

    @property
    def cors_origins(
        self,
    ) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin
            in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def is_production(
        self,
    ) -> bool:
        return (
            self.ENVIRONMENT
            == "production"
        )

    @property
    def is_live_trading_configured(
        self,
    ) -> bool:
        return bool(
            self.LIVE_TRADING_API_KEY
            and self.JUPITER_API_KEY
            and self.LIVE_TRADING_WALLET_ADDRESS
            and self.LIVE_TRADING_PRIVATE_KEY
        )

    @model_validator(
        mode="after"
    )
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
                "quando CORS_ALLOW_CREDENTIALS "
                "è true."
            )

        for origin in origins:
            if origin == "*":
                continue

            parsed = urlparse(
                origin
            )

            if (
                parsed.scheme
                not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                not in {"", "/"}
            ):
                raise ValueError(
                    "Origine CORS non valida: "
                    f"{origin}"
                )

        return self

    @model_validator(
        mode="after"
    )
    def validate_production_security(
        self,
    ) -> Self:
        if not self.is_production:
            return self

        if len(
            self.AUTOMATION_API_KEY
        ) < 32:
            raise ValueError(
                "In produzione "
                "AUTOMATION_API_KEY deve "
                "contenere almeno 32 caratteri."
            )

        live_values = (
            self.LIVE_TRADING_WALLET_ADDRESS,
            self.LIVE_TRADING_PRIVATE_KEY,
            self.LIVE_TRADING_API_KEY,
        )

        if any(live_values):
            if not all(live_values):
                raise ValueError(
                    "La configurazione Live Trading "
                    "in produzione deve includere "
                    "wallet, chiave privata e API "
                    "key interna."
                )

            if len(
                self.LIVE_TRADING_API_KEY
            ) < 32:
                raise ValueError(
                    "In produzione "
                    "LIVE_TRADING_API_KEY deve "
                    "contenere almeno 32 caratteri."
                )

            if not self.JUPITER_API_KEY:
                raise ValueError(
                    "JUPITER_API_KEY è obbligatoria "
                    "quando il Live Trading è "
                    "configurato in produzione."
                )

        return self


settings = Settings() 