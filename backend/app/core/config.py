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

    HELIUS_REQUEST_TIMEOUT_SECONDS: float = Field(
        default=20.0,
        ge=2.0,
        le=120.0,
    )

    # Numero di nuovi tentativi dopo la prima richiesta.
    HELIUS_MAX_RETRIES: int = Field(
        default=3,
        ge=0,
        le=10,
    )

    HELIUS_RETRY_BASE_SECONDS: float = Field(
        default=0.75,
        ge=0.1,
        le=10.0,
    )

    HELIUS_RETRY_MAX_SECONDS: float = Field(
        default=8.0,
        ge=1.0,
        le=60.0,
    )

    # =========================
    # RAW BLOCKCHAIN CAPTURE
    # Passive shadow mode; disabled by default.
    # =========================

    RAW_BLOCKCHAIN_CAPTURE_ENABLED: bool = False

    RAW_BLOCKCHAIN_CAPTURE_PROVIDERS: str = (
        "helius,solana_rpc"
    )

    RAW_BLOCKCHAIN_CAPTURE_EVENT_TYPES: str = (
        "WALLET_HISTORY_RESPONSE,"
        "ENHANCED_TRANSACTION_RESPONSE,"
        "RPC_RESPONSE"
    )

    RAW_BLOCKCHAIN_CAPTURE_MAX_PAYLOAD_BYTES: int = Field(
        default=4_000_000,
        ge=1024,
        le=16_000_000,
    )

    RAW_BLOCKCHAIN_CAPTURE_RETENTION_DAYS: int = Field(
        default=30,
        ge=1,
        le=3650,
    )

    RAW_BLOCKCHAIN_CAPTURE_RETENTION_BATCH_SIZE: int = Field(
        default=1000,
        ge=1,
        le=10_000,
    )

    RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED: bool = False

    # =========================
    # VERSIONED NORMALIZATION REPLAY
    # Manual-only; disabled by default.
    # =========================

    RAW_BLOCKCHAIN_REPLAY_ENABLED: bool = False

    RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS: str = (
        "raw_event_envelope"
    )

    RAW_BLOCKCHAIN_REPLAY_MAX_BATCH_SIZE: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    # =========================
    # CANONICAL NORMALIZATION / SHADOW VALIDATION
    # Manual-only; disabled by default.
    # =========================

    CANONICAL_NORMALIZATION_ENABLED: bool = False

    CANONICAL_NORMALIZATION_MAX_BATCH_SIZE: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    CANONICAL_SHADOW_VALIDATION_ENABLED: bool = False

    CANONICAL_SHADOW_VALIDATION_MAX_BATCH_SIZE: int = Field(
        default=200,
        ge=1,
        le=5000,
    )

    CANONICAL_SHADOW_AMOUNT_TOLERANCE: float = Field(
        default=0.000000001,
        ge=0.0,
        le=0.01,
    )

    # =========================
    # CANONICAL QUALITY GATE
    # Assessment-only; disabled by default.
    # =========================

    CANONICAL_QUALITY_GATE_ENABLED: bool = False

    CANONICAL_QUALITY_GATE_MIN_COMPARABLE_EVENTS: int = Field(
        default=50,
        ge=10,
        le=100_000,
    )

    CANONICAL_QUALITY_GATE_MIN_MATCH_RATE: float = Field(
        default=98.0,
        ge=0.0,
        le=100.0,
    )

    CANONICAL_QUALITY_GATE_MAX_MISMATCH_RATE: float = Field(
        default=2.0,
        ge=0.0,
        le=100.0,
    )

    CANONICAL_QUALITY_GATE_MAX_MISSING_TRADE_RATE: float = Field(
        default=10.0,
        ge=0.0,
        le=100.0,
    )

    CANONICAL_QUALITY_GATE_MAX_NOT_COMPARABLE_RATE: float = Field(
        default=5.0,
        ge=0.0,
        le=100.0,
    )

    CANONICAL_QUALITY_GATE_MAX_FAILED_RATE: float = Field(
        default=0.5,
        ge=0.0,
        le=100.0,
    )

    CANONICAL_QUALITY_GATE_MIN_PASS_QUALITY_RATE: float = Field(
        default=95.0,
        ge=0.0,
        le=100.0,
    )

    CANONICAL_QUALITY_GATE_MAX_EVIDENCE_AGE_HOURS: int = Field(
        default=168,
        ge=1,
        le=8760,
    )

    # =========================
    # CANONICAL PARSER PROMOTION LEDGER
    # Audit-only; disabled by default.
    # =========================

    CANONICAL_PARSER_PROMOTION_ENABLED: bool = False

    CANONICAL_PARSER_PROMOTION_MAX_ASSESSMENT_AGE_HOURS: int = Field(
        default=168,
        ge=1,
        le=8760,
    )

    # =========================
    # CANONICAL PARSER RUNTIME BINDING
    # Metadata-only SHADOW_ONLY resolver; disabled by default.
    # =========================

    CANONICAL_PARSER_RUNTIME_BINDING_ENABLED: bool = False

    # =========================
    # CONTROLLED DISCOVERY HYDRATION
    # =========================

    DISCOVERY_HYDRATION_DEFAULT_WALLETS: int = Field(
        default=3,
        ge=1,
        le=10,
    )

    DISCOVERY_HYDRATION_MAX_WALLETS_PER_RUN: int = Field(
        default=10,
        ge=1,
        le=25,
    )

    DISCOVERY_HYDRATION_MAX_HELIUS_REQUESTS_PER_RUN: int = Field(
        default=10,
        ge=1,
        le=25,
    )

    DISCOVERY_HYDRATION_LOOKBACK_DAYS: int = Field(
        default=7,
        ge=1,
        le=14,
    )

    DISCOVERY_HYDRATION_TRANSACTION_LIMIT: int = Field(
        default=100,
        ge=1,
        le=100,
    )

    DISCOVERY_HYDRATION_COOLDOWN_HOURS: int = Field(
        default=12,
        ge=1,
        le=168,
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

    # Retry applicati soltanto alle quotazioni /order.
    # L'esecuzione /execute non viene ritentata automaticamente.
    JUPITER_SWAP_MAX_RETRIES: int = Field(
        default=2,
        ge=0,
        le=10,
    )

    JUPITER_SWAP_RETRY_BASE_SECONDS: float = Field(
        default=0.50,
        ge=0.05,
        le=10.0,
    )

    JUPITER_SWAP_RETRY_MAX_SECONDS: float = Field(
        default=4.0,
        ge=0.10,
        le=60.0,
    )

    # =========================
    # TOKEN SAFETY / MARKET DATA
    # =========================

    DEXSCREENER_API_URL: str = (
        "https://api.dexscreener.com"
    )

    TOKEN_SAFETY_TIMEOUT_SECONDS: float = Field(
        default=12.0,
        ge=2.0,
        le=60.0,
    )

    RUGCHECK_API_URL: str = ""

    RUGCHECK_API_KEY: str = Field(
        default="",
        repr=False,
    )

    LIVE_TRADING_REQUIRE_SIMULATION: bool = True

    # =========================
    # LIVE TRADING WALLET
    # =========================

    LIVE_TRADING_WALLET_ADDRESS: str = ""

    LIVE_TRADING_PRIVATE_KEY: str = Field(
        default="",
        repr=False,
    )

    # =========================
    # LIVE STREAM WORKER
    # =========================

    RUN_LIVE_STREAM_WORKER: bool = False

    LIVE_STREAM_EMBEDDED_RESTART_SECONDS: float = Field(
        default=5.0,
        ge=1.0,
        le=300.0,
    )

    LIVE_STREAM_SHUTDOWN_TIMEOUT_SECONDS: float = Field(
        default=25.0,
        ge=5.0,
        le=120.0,
    )

    LIVE_STREAM_POLICY_REFRESH_SECONDS: int = Field(
        default=10,
        ge=3,
        le=300,
    )

    LIVE_STREAM_HEARTBEAT_SECONDS: int = Field(
        default=15,
        ge=5,
        le=120,
    )

    LIVE_STREAM_LEASE_SECONDS: int = Field(
        default=60,
        ge=20,
        le=600,
    )

    LIVE_STREAM_RECONNECT_MIN_SECONDS: float = Field(
        default=2.0,
        ge=0.5,
        le=60.0,
    )

    LIVE_STREAM_RECONNECT_MAX_SECONDS: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
    )

    LIVE_STREAM_PING_INTERVAL_SECONDS: float = Field(
        default=45.0,
        ge=10.0,
        le=300.0,
    )

    LIVE_STREAM_PING_TIMEOUT_SECONDS: float = Field(
        default=20.0,
        ge=5.0,
        le=120.0,
    )

    LIVE_STREAM_OPEN_TIMEOUT_SECONDS: float = Field(
        default=20.0,
        ge=5.0,
        le=120.0,
    )

    LIVE_STREAM_SUBSCRIPTION_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        ge=5.0,
        le=180.0,
    )

    LIVE_STREAM_QUEUE_SIZE: int = Field(
        default=500,
        ge=10,
        le=10000,
    )

    LIVE_STREAM_CONSUMERS: int = Field(
        default=4,
        ge=1,
        le=32,
    )

    LIVE_STREAM_RECENT_SIGNATURES: int = Field(
        default=10000,
        ge=100,
        le=100000,
    )

    # Impedisce il rientro immediato sullo stesso token
    # dopo la chiusura completa di una posizione.
    LIVE_TOKEN_REENTRY_COOLDOWN_MINUTES: int = Field(
        default=15,
        ge=0,
        le=10080,
    )

    # Obiettivo ufficiale della campagna DRY_RUN.
    LIVE_CAMPAIGN_TARGET_CLOSED_TRADES: int = Field(
        default=100,
        ge=1,
        le=100000,
    )

    # =========================
    # POSITION MONITOR / RECONCILIATION
    # =========================

    RUN_LIVE_POSITION_MONITOR: bool = False

    LIVE_POSITION_MONITOR_INTERVAL_SECONDS: float = Field(
        default=30.0, ge=5.0, le=3600.0
    )

    LIVE_POSITION_MONITOR_LEASE_SECONDS: int = Field(
        default=120, ge=30, le=3600
    )

    LIVE_POSITION_MONITOR_RESTART_SECONDS: float = Field(
        default=5.0, ge=1.0, le=300.0
    )

    LIVE_POSITION_MONITOR_SHUTDOWN_TIMEOUT_SECONDS: float = Field(
        default=25.0, ge=5.0, le=120.0
    )

    LIVE_POSITION_MONITOR_BATCH_SIZE: int = Field(
        default=100, ge=1, le=500
    )

    LIVE_ORDER_RECONCILE_BATCH_SIZE: int = Field(
        default=50, ge=1, le=500
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
        "RUGCHECK_API_KEY",
        "RUGCHECK_API_URL",
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
        "DEXSCREENER_API_URL",
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
        "RUGCHECK_API_URL"
    )
    @classmethod
    def validate_optional_rugcheck_url(
        cls,
        value: str,
    ):
        if not value:
            return ""

        normalized = value.rstrip("/")
        parsed = urlparse(normalized)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            raise ValueError(
                "RUGCHECK_API_URL deve essere "
                "vuoto oppure un URL HTTP valido."
            )

        return normalized

    @field_validator(
        "RAW_BLOCKCHAIN_CAPTURE_PROVIDERS",
        mode="before",
    )
    @classmethod
    def normalize_raw_capture_providers(
        cls,
        value,
    ) -> str:
        if isinstance(value, (list, tuple, set)):
            raw_items = [str(item) for item in value]
        else:
            raw_items = str(value or "").split(",")

        providers: list[str] = []
        for item in raw_items:
            normalized = item.strip().lower()
            if not normalized or normalized in providers:
                continue
            if not all(
                character.isalnum()
                or character in {"_", "-"}
                for character in normalized
            ):
                raise ValueError(
                    "RAW_BLOCKCHAIN_CAPTURE_PROVIDERS "
                    "contiene un provider non valido."
                )
            providers.append(normalized)

        return ",".join(providers)

    @field_validator(
        "RAW_BLOCKCHAIN_CAPTURE_EVENT_TYPES",
        mode="before",
    )
    @classmethod
    def normalize_raw_capture_event_types(
        cls,
        value,
    ) -> str:
        if isinstance(value, (list, tuple, set)):
            raw_items = [str(item) for item in value]
        else:
            raw_items = str(value or "").split(",")

        event_types: list[str] = []
        for item in raw_items:
            normalized = item.strip().upper()
            if not normalized or normalized in event_types:
                continue
            if not all(
                character.isalnum()
                or character == "_"
                for character in normalized
            ):
                raise ValueError(
                    "RAW_BLOCKCHAIN_CAPTURE_EVENT_TYPES "
                    "contiene un event type non valido."
                )
            event_types.append(normalized)

        return ",".join(event_types)

    @field_validator(
        "RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS",
        mode="before",
    )
    @classmethod
    def normalize_raw_replay_allowed_parsers(
        cls,
        value,
    ) -> str:
        if isinstance(value, (list, tuple, set)):
            raw_items = [str(item) for item in value]
        else:
            raw_items = str(value or "").split(",")

        parsers: list[str] = []
        for item in raw_items:
            normalized = item.strip().lower()
            if not normalized or normalized in parsers:
                continue
            if not all(
                character.isalnum()
                or character == "_"
                for character in normalized
            ):
                raise ValueError(
                    "RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS "
                    "contiene un parser non valido."
                )
            parsers.append(normalized)

        return ",".join(parsers)

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
    def raw_blockchain_capture_providers(
        self,
    ) -> list[str]:
        return [
            provider.strip().lower()
            for provider
            in self.RAW_BLOCKCHAIN_CAPTURE_PROVIDERS.split(",")
            if provider.strip()
        ]

    @property
    def raw_blockchain_capture_event_types(
        self,
    ) -> list[str]:
        return [
            event_type.strip().upper()
            for event_type
            in self.RAW_BLOCKCHAIN_CAPTURE_EVENT_TYPES.split(",")
            if event_type.strip()
        ]

    @property
    def raw_blockchain_replay_allowed_parsers(
        self,
    ) -> list[str]:
        return [
            parser.strip().lower()
            for parser
            in self.RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS.split(",")
            if parser.strip()
        ]

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
    def validate_raw_capture_configuration(
        self,
    ) -> Self:
        if (
            self.RAW_BLOCKCHAIN_CAPTURE_ENABLED
            and not self.raw_blockchain_capture_providers
        ):
            raise ValueError(
                "RAW_BLOCKCHAIN_CAPTURE_PROVIDERS deve "
                "contenere almeno un provider quando "
                "la cattura è abilitata."
            )

        if (
            self.RAW_BLOCKCHAIN_CAPTURE_ENABLED
            and not self.raw_blockchain_capture_event_types
        ):
            raise ValueError(
                "RAW_BLOCKCHAIN_CAPTURE_EVENT_TYPES deve "
                "contenere almeno un event type quando "
                "la cattura è abilitata."
            )

        if (
            self.RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED
            and self.RAW_BLOCKCHAIN_CAPTURE_RETENTION_DAYS < 7
        ):
            raise ValueError(
                "Con la cancellazione retention abilitata, "
                "RAW_BLOCKCHAIN_CAPTURE_RETENTION_DAYS "
                "deve essere almeno 7."
            )

        if (
            self.RAW_BLOCKCHAIN_REPLAY_ENABLED
            and not self.raw_blockchain_replay_allowed_parsers
        ):
            raise ValueError(
                "RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS deve "
                "contenere almeno un parser quando il replay "
                "è abilitato."
            )

        return self

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
    def validate_live_stream_configuration(
        self,
    ) -> Self:
        if (
            self.LIVE_STREAM_RECONNECT_MAX_SECONDS
            < self.LIVE_STREAM_RECONNECT_MIN_SECONDS
        ):
            raise ValueError(
                "LIVE_STREAM_RECONNECT_MAX_SECONDS "
                "non può essere inferiore a "
                "LIVE_STREAM_RECONNECT_MIN_SECONDS."
            )

        if (
            self.LIVE_STREAM_LEASE_SECONDS
            < (
                self.LIVE_STREAM_HEARTBEAT_SECONDS
                * 2
            )
        ):
            raise ValueError(
                "LIVE_STREAM_LEASE_SECONDS deve "
                "essere almeno il doppio di "
                "LIVE_STREAM_HEARTBEAT_SECONDS."
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

        if (
            self.LIVE_TRADING_API_KEY
            and len(
                self.LIVE_TRADING_API_KEY
            ) < 32
        ):
            raise ValueError(
                "In produzione "
                "LIVE_TRADING_API_KEY deve "
                "contenere almeno 32 caratteri."
            )

        live_wallet_values = (
            self.LIVE_TRADING_WALLET_ADDRESS,
            self.LIVE_TRADING_PRIVATE_KEY,
        )

        if (
            any(live_wallet_values)
            and not all(live_wallet_values)
        ):
            raise ValueError(
                "La configurazione del wallet "
                "LIVE deve includere sia "
                "LIVE_TRADING_WALLET_ADDRESS sia "
                "LIVE_TRADING_PRIVATE_KEY."
            )

        if all(live_wallet_values):
            if not self.LIVE_TRADING_API_KEY:
                raise ValueError(
                    "LIVE_TRADING_API_KEY ? "
                    "obbligatoria quando il wallet "
                    "LIVE ? configurato."
                )

            if not self.JUPITER_API_KEY:
                raise ValueError(
                    "JUPITER_API_KEY ? obbligatoria "
                    "quando il wallet LIVE ? "
                    "configurato."
                )

        return self


settings = Settings()
