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
    # CANONICAL PARSER RUNTIME ADMISSION CANARY
    # Manual shadow-only consumer; disabled by default.
    # =========================

    CANONICAL_PARSER_RUNTIME_ADMISSION_ENABLED: bool = False

    CANONICAL_PARSER_RUNTIME_ADMISSION_MAX_SAMPLE_SIZE: int = Field(
        default=25,
        ge=1,
        le=100,
    )

    # =========================
    # CANONICAL PARSER RUNTIME CERTIFICATION
    # Metadata-only admission evidence governance; disabled by default.
    # =========================

    CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED: bool = False

    CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_RUNS: int = Field(
        default=2, ge=1, le=20
    )
    CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_TOTAL_EVENTS: int = Field(
        default=10, ge=1, le=10000
    )
    CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_PASS_RATE: float = Field(
        default=100.0, ge=0.0, le=100.0
    )
    CANONICAL_PARSER_RUNTIME_CERTIFICATION_MAX_FAILED_EVENTS: int = Field(
        default=0, ge=0, le=1000
    )
    CANONICAL_PARSER_RUNTIME_CERTIFICATION_MAX_EVIDENCE_AGE_HOURS: int = Field(
        default=24, ge=1, le=8760
    )
    CANONICAL_PARSER_RUNTIME_CERTIFICATION_VALIDITY_HOURS: int = Field(
        default=24, ge=1, le=8760
    )

    # =========================
    # CERTIFIED SHADOW RUNTIME LEASE
    # Manual metadata-only consumer interlock; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_LEASE_ENABLED: bool = False

    CANONICAL_PARSER_SHADOW_LEASE_MAX_VALIDITY_MINUTES: int = Field(
        default=60, ge=5, le=1440
    )
    CANONICAL_PARSER_SHADOW_LEASE_MIN_CERTIFICATION_REMAINING_MINUTES: int = Field(
        default=15, ge=0, le=1440
    )

    # =========================
    # CERTIFIED SHADOW CONSUMER DRY-RUN
    # Manual bounded shadow execution; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_CONSUMER_ENABLED: bool = False

    CANONICAL_PARSER_SHADOW_CONSUMER_MAX_SAMPLE_SIZE: int = Field(
        default=25, ge=1, le=100
    )

    # =========================
    # SHADOW CONSUMER READINESS ASSESSMENT
    # Manual evidence gate; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_READINESS_ENABLED: bool = False

    CANONICAL_PARSER_SHADOW_READINESS_MIN_RUNS: int = Field(
        default=3, ge=1, le=20
    )
    CANONICAL_PARSER_SHADOW_READINESS_MAX_RUNS: int = Field(
        default=20, ge=1, le=100
    )
    CANONICAL_PARSER_SHADOW_READINESS_MIN_TOTAL_EVENTS: int = Field(
        default=15, ge=1, le=10000
    )
    CANONICAL_PARSER_SHADOW_READINESS_MIN_UNIQUE_EVENTS: int = Field(
        default=10, ge=1, le=10000
    )
    CANONICAL_PARSER_SHADOW_READINESS_MIN_PASS_RATE: float = Field(
        default=100.0, ge=0.0, le=100.0
    )
    CANONICAL_PARSER_SHADOW_READINESS_MAX_FAILED_EVENTS: int = Field(
        default=0, ge=0, le=1000
    )
    CANONICAL_PARSER_SHADOW_READINESS_MAX_SKIPPED_EVENTS: int = Field(
        default=0, ge=0, le=1000
    )
    CANONICAL_PARSER_SHADOW_READINESS_MIN_OBSERVATION_SPAN_MINUTES: int = Field(
        default=5, ge=0, le=10080
    )
    CANONICAL_PARSER_SHADOW_READINESS_MAX_EVIDENCE_AGE_MINUTES: int = Field(
        default=30, ge=1, le=10080
    )
    CANONICAL_PARSER_SHADOW_READINESS_VALIDITY_MINUTES: int = Field(
        default=15, ge=1, le=1440
    )

    # =========================
    # CERTIFIED SHADOW AUTOMATION PERMIT
    # Manual bounded authorization metadata; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_ENABLED: bool = False

    CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_VALIDITY_MINUTES: int = Field(
        default=10, ge=1, le=1440
    )
    CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MIN_READINESS_REMAINING_MINUTES: int = Field(
        default=2, ge=0, le=1440
    )
    CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_RUN_BUDGET: int = Field(
        default=5, ge=1, le=1000
    )
    CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_EVENT_BUDGET: int = Field(
        default=100, ge=1, le=100000
    )

    # =========================
    # CERTIFIED SHADOW EXECUTION TICKET
    # Manual atomic budget reservation; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_ENABLED: bool = False

    CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_VALIDITY_SECONDS: int = Field(
        default=180, ge=1, le=3600
    )
    CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MIN_PERMIT_REMAINING_SECONDS: int = Field(
        default=30, ge=0, le=3600
    )
    CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_EVENT_RESERVATION: int = Field(
        default=25, ge=1, le=100000
    )

    # =========================
    # TICKET-BOUND SHADOW EXECUTION AND BUDGET SETTLEMENT
    # Manual parser execution only; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_ENABLED: bool = False

    CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_MAX_SAMPLE_SIZE: int = Field(
        default=25, ge=1, le=100
    )

    # =========================
    # SHADOW AUTOMATION CYCLE COORDINATOR
    # Manual reserve + execute orchestration; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_ENABLED: bool = False
    CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EVENT_RESERVATION: int = Field(
        default=25, ge=1, le=100
    )
    CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EXECUTION_LIMIT: int = Field(
        default=25, ge=1, le=100
    )
    CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_TICKET_VALIDITY_SECONDS: int = Field(
        default=120, ge=1, le=3600
    )

    # =========================
    # SHADOW SCHEDULER CONTROL PLANE
    # Persistent state, lock, heartbeat and kill switch. Manual tick only.
    # =========================

    CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED: bool = False
    CANONICAL_PARSER_SHADOW_SCHEDULER_MIN_INTERVAL_SECONDS: int = Field(
        default=300, ge=1, le=86400
    )
    CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_INTERVAL_SECONDS: int = Field(
        default=3600, ge=1, le=86400
    )
    CANONICAL_PARSER_SHADOW_SCHEDULER_LOCK_TTL_SECONDS: int = Field(
        default=180, ge=1, le=3600
    )
    CANONICAL_PARSER_SHADOW_SCHEDULER_HEARTBEAT_TIMEOUT_SECONDS: int = Field(
        default=300, ge=1, le=86400
    )
    CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_EVENT_RESERVATION: int = Field(
        default=25, ge=1, le=100
    )
    CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_EXECUTION_LIMIT: int = Field(
        default=25, ge=1, le=100
    )

    # =========================
    # SHADOW SCHEDULER WORKER LEASE / FENCING
    # Single-iteration runtime only; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_WORKER_ENABLED: bool = False
    CANONICAL_PARSER_SHADOW_WORKER_LEASE_TTL_SECONDS: int = Field(
        default=120, ge=5, le=3600
    )
    CANONICAL_PARSER_SHADOW_WORKER_HEARTBEAT_TIMEOUT_SECONDS: int = Field(
        default=180, ge=5, le=86400
    )
    CANONICAL_PARSER_SHADOW_WORKER_MAX_CONSECUTIVE_FAILURES: int = Field(
        default=3, ge=1, le=100
    )

    # =========================
    # BOUNDED SHADOW WORKER LOOP / CIRCUIT BREAKER
    # Explicit bounded supervisor session; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENABLED: bool = False
    CANONICAL_PARSER_SHADOW_WORKER_LOOP_MAX_ITERATIONS: int = Field(
        default=5, ge=1, le=50
    )
    CANONICAL_PARSER_SHADOW_WORKER_LOOP_MAX_CONSECUTIVE_FAILURES: int = Field(
        default=2, ge=1, le=20
    )
    CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENFORCE_KILL_SWITCH: bool = False

    # =========================
    # SHADOW WORKER RECOVERY / RECONCILIATION
    # Manual stale-state cleanup only; disabled by default.
    # =========================

    CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_ENABLED: bool = False
    CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_STALE_AFTER_SECONDS: int = Field(
        default=300, ge=5, le=86400
    )
    CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_MAX_TARGETS: int = Field(
        default=100, ge=1, le=1000
    )

    # =========================
    # SHADOW AUTOMATION RELIABILITY EVIDENCE GATE
    # Manual evidence-only assessment; no PAPER/LIVE admission.
    # =========================

    CANONICAL_PARSER_SHADOW_RELIABILITY_ENABLED: bool = False
    CANONICAL_PARSER_SHADOW_RELIABILITY_LOOKBACK_MINUTES: int = Field(
        default=60, ge=1, le=10080
    )
    CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_LOOP_RUNS: int = Field(
        default=3, ge=1, le=1000
    )
    CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_ITERATIONS: int = Field(
        default=10, ge=1, le=100000
    )
    CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_PASS_RATE: float = Field(
        default=95.0, ge=0.0, le=100.0
    )
    CANONICAL_PARSER_SHADOW_RELIABILITY_MAX_FAILED_ITERATIONS: int = Field(
        default=0, ge=0, le=100000
    )
    CANONICAL_PARSER_SHADOW_RELIABILITY_MAX_CIRCUIT_OPEN_RUNS: int = Field(
        default=0, ge=0, le=1000
    )
    CANONICAL_PARSER_SHADOW_RELIABILITY_MAX_RECOVERY_ACTIONS: int = Field(
        default=0, ge=0, le=1000
    )
    CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_OBSERVATION_MINUTES: int = Field(
        default=5, ge=0, le=10080
    )
    CANONICAL_PARSER_SHADOW_RELIABILITY_VALIDITY_MINUTES: int = Field(
        default=15, ge=1, le=1440
    )


    # =========================
    # SHADOW RELIABILITY CERTIFICATION
    # Manual, revocable certification of M22 READY evidence.
    # =========================

    CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_ENABLED: bool = False
    CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_VALIDITY_MINUTES: int = Field(
        default=60, ge=1, le=10080
    )

    # =========================
    # PAPER PROJECTION DRY-RUN
    # Projection-only compatibility analysis; never writes PAPER/LIVE state.
    # =========================

    CANONICAL_PARSER_PAPER_PROJECTION_ENABLED: bool = False
    CANONICAL_PARSER_PAPER_PROJECTION_LOOKBACK_MINUTES: int = Field(
        default=1440, ge=1, le=10080
    )
    CANONICAL_PARSER_PAPER_PROJECTION_MAX_SOURCE_RUNS: int = Field(
        default=10, ge=1, le=1000
    )
    CANONICAL_PARSER_PAPER_PROJECTION_MAX_ARTIFACTS: int = Field(
        default=100, ge=1, le=10000
    )
    CANONICAL_PARSER_PAPER_PROJECTION_MIN_PROJECTABLE_RESULTS: int = Field(
        default=1, ge=1, le=10000
    )

    # =========================
    # PAPER PROJECTION READINESS GATE
    # Evidence-only assessment across multiple M24 dry-runs.
    # =========================

    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_ENABLED: bool = False
    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_LOOKBACK_MINUTES: int = Field(
        default=1440, ge=1, le=10080
    )
    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MAX_SOURCE_RUNS: int = Field(
        default=20, ge=1, le=1000
    )
    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_RUNS: int = Field(
        default=3, ge=1, le=1000
    )
    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_RESULTS: int = Field(
        default=3, ge=1, le=100000
    )
    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_PROJECTABLE_RATE: float = Field(
        default=100.0, ge=0.0, le=100.0
    )
    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MAX_REVIEW_RESULTS: int = Field(
        default=0, ge=0, le=100000
    )
    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MAX_REJECTED_RESULTS: int = Field(
        default=0, ge=0, le=100000
    )
    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_OBSERVATION_MINUTES: int = Field(
        default=5, ge=0, le=10080
    )
    CANONICAL_PARSER_PAPER_PROJECTION_READINESS_VALIDITY_MINUTES: int = Field(
        default=30, ge=1, le=10080
    )

    # =========================
    # PAPER ADMISSION CERTIFICATION
    # Metadata-only certification; not connected to PAPER execution.
    # =========================

    CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_ENABLED: bool = False
    CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_VALIDITY_MINUTES: int = Field(
        default=60, ge=1, le=10080
    )

    # =========================
    # PAPER RUNTIME BINDING
    # Read-only metadata binding to one PAPER account.
    # =========================

    CANONICAL_PARSER_PAPER_RUNTIME_BINDING_ENABLED: bool = False
    CANONICAL_PARSER_PAPER_RUNTIME_BINDING_VALIDITY_MINUTES: int = Field(
        default=60, ge=1, le=10080
    )

    # =========================
    # PAPER ADMISSION CANARY
    # Read-only risk interlock; never executes PAPER orders.
    # =========================

    CANONICAL_PARSER_PAPER_ADMISSION_CANARY_ENABLED: bool = False
    CANONICAL_PARSER_PAPER_ADMISSION_CANARY_VALIDITY_MINUTES: int = Field(
        default=15, ge=1, le=1440
    )
    CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_SOURCE_RUNS: int = Field(
        default=3, ge=1, le=100
    )
    CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_RESULTS: int = Field(
        default=25, ge=1, le=1000
    )
    CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MIN_ADMISSIBLE_RESULTS: int = Field(
        default=1, ge=1, le=1000
    )
    CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_CUMULATIVE_BUY_FRACTION: float = Field(
        default=0.5, gt=0, le=1
    )

    # =========================
    # PAPER CANARY READINESS EVIDENCE GATE
    # Aggregates M28 metadata only; disabled by default.
    # =========================

    CANONICAL_PARSER_PAPER_CANARY_READINESS_ENABLED: bool = False
    CANONICAL_PARSER_PAPER_CANARY_READINESS_LOOKBACK_MINUTES: int = Field(
        default=1440, ge=1, le=10080
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_SOURCE_RUNS: int = Field(
        default=20, ge=1, le=200
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_RUNS: int = Field(
        default=3, ge=1, le=200
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_RESULTS: int = Field(
        default=3, ge=1, le=10000
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_ADMISSIBLE_RESULTS: int = Field(
        default=3, ge=1, le=10000
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_REVIEW_RUNS: int = Field(
        default=0, ge=0, le=200
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_BLOCKED_RUNS: int = Field(
        default=0, ge=0, le=200
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_INSUFFICIENT_RUNS: int = Field(
        default=0, ge=0, le=200
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_OBSERVATION_MINUTES: int = Field(
        default=5, ge=0, le=10080
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_SOURCE_AGE_MINUTES: int = Field(
        default=30, ge=1, le=10080
    )
    CANONICAL_PARSER_PAPER_CANARY_READINESS_VALIDITY_MINUTES: int = Field(
        default=30, ge=1, le=1440
    )

    # =========================
    # PAPER EXECUTION PERMIT GOVERNANCE
    # Metadata-only permit; disabled by default and disconnected from execution.
    # =========================

    CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_ENABLED: bool = False
    CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_VALIDITY_MINUTES: int = Field(
        default=60, ge=1, le=1440
    )
    CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_TOTAL_BUDGET_SOL: float = Field(
        default=1.0, gt=0, le=1000000
    )
    CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_ORDER_BUDGET_SOL: float = Field(
        default=0.25, gt=0, le=1000000
    )
    CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_ORDER_COUNT: int = Field(
        default=20, ge=1, le=100000
    )
    CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MIN_READINESS_REMAINING_MINUTES: int = Field(
        default=2, ge=0, le=1440
    )

    # =========================
    # UNIFIED DECISION INTELLIGENCE & SHADOW VALIDATION
    # Read-only decision replay; disabled by default and disconnected from execution.
    # =========================

    CANONICAL_PARSER_UNIFIED_DECISION_ENABLED: bool = False
    CANONICAL_PARSER_UNIFIED_DECISION_LOOKBACK_MINUTES: int = Field(
        default=1440, ge=1, le=10080
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MAX_SOURCE_TRADES: int = Field(
        default=1000, ge=1, le=100000
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MAX_RESULTS: int = Field(
        default=100, ge=1, le=1000
    )
    CANONICAL_PARSER_UNIFIED_DECISION_VALIDITY_MINUTES: int = Field(
        default=30, ge=1, le=1440
    )
    CANONICAL_PARSER_UNIFIED_DECISION_WALLET_FRESHNESS_MINUTES: int = Field(
        default=1440, ge=1, le=10080
    )
    CANONICAL_PARSER_UNIFIED_DECISION_TOKEN_FRESHNESS_MINUTES: int = Field(
        default=30, ge=1, le=1440
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MIN_QUALIFIED_WALLETS: int = Field(
        default=2, ge=1, le=100
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MIN_INDEPENDENT_CLUSTERS: int = Field(
        default=2, ge=1, le=100
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MIN_APPROVE_SCORE: float = Field(
        default=72.0, ge=0, le=100
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MIN_REVIEW_SCORE: float = Field(
        default=55.0, ge=0, le=100
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MAX_COPY_LATENCY_SECONDS: int = Field(
        default=180, ge=1, le=86400
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MAX_STALE_SECONDS: int = Field(
        default=900, ge=1, le=86400
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MIN_TOKEN_LIQUIDITY_USD: float = Field(
        default=25000.0, ge=0, le=1000000000
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MAX_TOKEN_RISK_SCORE: int = Field(
        default=35, ge=0, le=100
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MAX_TOP_HOLDER_PERCENT: float = Field(
        default=25.0, ge=0, le=100
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MIN_EDGE_STRENGTH: float = Field(
        default=60.0, ge=0, le=100
    )
    CANONICAL_PARSER_UNIFIED_DECISION_FOLLOWER_DELAY_SECONDS: int = Field(
        default=30, ge=0, le=3600
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MAX_SIZE_SOL: float = Field(
        default=0.05, gt=0, le=1000000
    )
    CANONICAL_PARSER_UNIFIED_DECISION_STOP_LOSS_PERCENT: float = Field(
        default=15.0, gt=0, le=100
    )
    CANONICAL_PARSER_UNIFIED_DECISION_TAKE_PROFIT_PERCENT: float = Field(
        default=30.0, gt=0, le=10000
    )
    CANONICAL_PARSER_UNIFIED_DECISION_MAX_HOLD_MINUTES: int = Field(
        default=240, ge=1, le=10080
    )

    # =========================
    # PERMIT-BOUND PAPER EXECUTION
    # Manual only; disabled by default; never authorizes LIVE.
    # =========================

    CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_ENABLED: bool = False
    CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_RESERVATION_TIMEOUT_MINUTES: int = Field(
        default=10, ge=1, le=1440
    )
    CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_MAX_SLIPPAGE_PERCENT: float = Field(
        default=5.0, ge=0, le=50
    )
    CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_MAX_FEE_PERCENT: float = Field(
        default=2.0, ge=0, le=20
    )
    CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_MAX_DECISION_AGE_MINUTES: int = Field(
        default=30, ge=1, le=1440
    )

    # =========================
    # PAPER RELIABILITY & CALIBRATION CAMPAIGN
    # Analytics only; disabled by default; never changes policies automatically.
    # =========================

    CANONICAL_PARSER_PAPER_CALIBRATION_ENABLED: bool = False
    CANONICAL_PARSER_PAPER_CALIBRATION_DEFAULT_LOOKBACK_DAYS: int = Field(
        default=30, ge=1, le=3650
    )
    CANONICAL_PARSER_PAPER_CALIBRATION_MIN_SETTLED_ATTEMPTS: int = Field(
        default=20, ge=1, le=1000000
    )
    CANONICAL_PARSER_PAPER_CALIBRATION_MIN_CLOSED_OUTCOMES: int = Field(
        default=10, ge=1, le=1000000
    )
    CANONICAL_PARSER_PAPER_CALIBRATION_MAX_CALIBRATION_GAP_PERCENT: float = Field(
        default=20.0, ge=0, le=100
    )
    CANONICAL_PARSER_PAPER_CALIBRATION_MIN_RELIABILITY_SCORE: float = Field(
        default=98.0, ge=0, le=100
    )

    # =========================
    # M34 PAPER CAMPAIGN ORCHESTRATION & OPERATIONAL HARDENING
    # Manual only; disabled by default; no worker/scheduler/stream.
    # =========================

    CANONICAL_PARSER_PAPER_CAMPAIGN_ORCHESTRATION_ENABLED: bool = False
    CANONICAL_PARSER_PAPER_CAMPAIGN_MAX_ITEMS: int = Field(
        default=10, ge=1, le=100
    )
    CANONICAL_PARSER_PAPER_CAMPAIGN_RECOVERY_LIMIT: int = Field(
        default=25, ge=1, le=500
    )
    CANONICAL_PARSER_PAPER_OPERATIONAL_LOOKBACK_HOURS: int = Field(
        default=24, ge=1, le=8760
    )
    CANONICAL_PARSER_PAPER_OPERATIONAL_MIN_SETTLED: int = Field(
        default=20, ge=1, le=1000000
    )
    CANONICAL_PARSER_PAPER_OPERATIONAL_MAX_RECONCILIATION_REQUIRED: int = Field(
        default=0, ge=0, le=1000000
    )
    CANONICAL_PARSER_PAPER_OPERATIONAL_MIN_RELIABILITY_SCORE: float = Field(
        default=98.0, ge=0, le=100
    )
    CANONICAL_PARSER_PAPER_OPERATIONAL_MAX_CALIBRATION_GAP_PERCENT: float = Field(
        default=20.0, ge=0, le=100
    )
    CANONICAL_PARSER_PAPER_OPERATIONAL_MAX_CALIBRATION_AGE_MINUTES: int = Field(
        default=120, ge=1, le=10080
    )
    CANONICAL_PARSER_PAPER_OPERATIONAL_VALIDITY_MINUTES: int = Field(
        default=30, ge=1, le=1440
    )

    # =========================
    # M35 MICRO-LIVE CANARY GOVERNANCE & SIMULATION
    # Metadata/simulation only; disabled by default; never arms or executes LIVE.
    # =========================

    CANONICAL_PARSER_MICRO_LIVE_CANARY_ENABLED: bool = False
    CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_VALIDITY_MINUTES: int = Field(
        default=15, ge=1, le=60
    )
    CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_TOTAL_BUDGET_SOL: float = Field(
        default=0.05, gt=0, le=10
    )
    CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_ORDER_BUDGET_SOL: float = Field(
        default=0.01, gt=0, le=1
    )
    CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_ORDER_COUNT: int = Field(
        default=3, ge=1, le=20
    )
    CANONICAL_PARSER_MICRO_LIVE_CANARY_MIN_ASSESSMENT_REMAINING_MINUTES: int = Field(
        default=2, ge=1, le=30
    )
    CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_DECISION_AGE_MINUTES: int = Field(
        default=15, ge=1, le=1440
    )

    # =========================
    # M36 ISOLATED SIGNER & LIVE TRANSACTION DRY-RUN
    # Pre-sign inspection/simulation only; disabled by default; never signs or sends.
    # =========================

    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_JUPITER_BUILD_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_RPC_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_PROFILE_VALIDITY_MINUTES: int = Field(
        default=60, ge=1, le=1440
    )
    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_TRANSACTION_BYTES: int = Field(
        default=1232, ge=1, le=4096
    )
    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_REQUIRED_SIGNERS: int = Field(
        default=1, ge=1, le=16
    )
    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_PROGRAMS: int = Field(
        default=24, ge=1, le=128
    )
    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_SIMULATION_LOGS: int = Field(
        default=20, ge=0, le=100
    )
    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENVELOPE_TTL_SECONDS: int = Field(
        default=60, ge=5, le=600
    )
    CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ALLOW_ADDRESS_LOOKUP_TABLES: bool = False


    # =========================
    # M37 EXTERNAL SIGNING APPROVAL
    # Signed transaction verification only; disabled by default.
    # =========================

    CANONICAL_PARSER_EXTERNAL_SIGNING_APPROVAL_ENABLED: bool = False
    CANONICAL_PARSER_EXTERNAL_SIGNING_RPC_ENABLED: bool = False
    CANONICAL_PARSER_EXTERNAL_SIGNING_APPROVAL_TTL_SECONDS: int = Field(
        default=60, ge=5, le=600
    )

    # =========================
    # M38 CONTROLLED LIVE SUBMISSION
    # Manual one-shot RPC submission only; disabled by default.
    # =========================

    CANONICAL_PARSER_CONTROLLED_LIVE_SUBMISSION_ENABLED: bool = False
    CANONICAL_PARSER_CONTROLLED_LIVE_SEND_RPC_ENABLED: bool = False
    CANONICAL_PARSER_CONTROLLED_LIVE_RECONCILIATION_ENABLED: bool = False
    CANONICAL_PARSER_CONTROLLED_LIVE_MAX_PENDING_SECONDS: int = Field(
        default=180, ge=30, le=3600
    )

    # =========================
    # M39 AUTHORITATIVE ON-CHAIN SETTLEMENT
    # Manual read-only reconciliation and governed position attribution.
    # =========================

    CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_RPC_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_REQUIRE_FINALIZED: bool = True
    CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_MAX_TRANSACTION_AGE_SECONDS: int = Field(
        default=900, ge=30, le=86400
    )
    CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_MAX_BUY_INPUT_DEVIATION_BPS: int = Field(
        default=3000, ge=0, le=10000
    )

    # =========================
    # M40 GOVERNED LIVE POSITION LIFECYCLE & EXIT INTENT
    # Manual assessment and exit authorization only.
    # =========================

    CANONICAL_PARSER_GOVERNED_LIVE_POSITION_ENABLED: bool = False
    CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_QUOTE_AGE_SECONDS: int = Field(
        default=30, ge=1, le=3600
    )
    CANONICAL_PARSER_GOVERNED_LIVE_POSITION_ASSESSMENT_TTL_SECONDS: int = Field(
        default=30, ge=5, le=3600
    )
    CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_INTENT_VALIDITY_MINUTES: int = Field(
        default=10, ge=1, le=1440
    )
    CANONICAL_PARSER_GOVERNED_LIVE_POSITION_STOP_LOSS_PERCENT: float = Field(
        default=10.0, ge=0.1, le=100.0
    )
    CANONICAL_PARSER_GOVERNED_LIVE_POSITION_TAKE_PROFIT_PERCENT: float = Field(
        default=25.0, ge=0.1, le=10000.0
    )
    CANONICAL_PARSER_GOVERNED_LIVE_POSITION_TRAILING_STOP_PERCENT: float = Field(
        default=8.0, ge=0.1, le=100.0
    )
    CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_AGE_MINUTES: int = Field(
        default=1440, ge=1, le=525600
    )
    CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_EXIT_PRICE_IMPACT_PERCENT: float = Field(
        default=10.0, ge=0.0, le=100.0
    )

    # =========================
    # M41 LIVE INCIDENT RESPONSE & RECOVERY
    # Manual incident governance; no autonomous recovery.
    # =========================

    CANONICAL_PARSER_LIVE_INCIDENT_RESPONSE_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_INCIDENT_SUBMISSION_GUARD_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_INCIDENT_STALE_SUBMISSION_SECONDS: int = Field(
        default=300, ge=30, le=86400
    )
    CANONICAL_PARSER_LIVE_INCIDENT_MAX_RECOVERY_VALIDITY_MINUTES: int = Field(
        default=15, ge=1, le=1440
    )

    # =========================
    # M42 AGGREGATED LIVE PORTFOLIO RISK
    # Manual portfolio assessment and single-use risk permit.
    # =========================

    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ENFORCEMENT_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ASSESSMENT_TTL_SECONDS: int = Field(
        default=60, ge=5, le=3600
    )
    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_PERMIT_VALIDITY_MINUTES: int = Field(
        default=10, ge=1, le=1440
    )
    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_TOTAL_EXPOSURE_SOL: float = Field(
        default=0.05, ge=0.0, le=1_000_000.0
    )
    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_PENDING_BUY_SOL: float = Field(
        default=0.02, ge=0.0, le=1_000_000.0
    )
    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_OPEN_POSITIONS: int = Field(
        default=3, ge=0, le=10000
    )
    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_TOKEN_CONCENTRATION_PERCENT: float = Field(
        default=50.0, ge=0.0, le=100.0
    )
    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_REQUIRE_FRESH_POSITION_ASSESSMENT: bool = True
    CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_FAIL_ON_HIGH_INCIDENT: bool = True

    # =========================
    # M43 LIVE OPERATIONAL OBSERVABILITY & ALERT LEDGER
    # Manual observation and alert lifecycle; no external notification dispatch.
    # =========================

    CANONICAL_PARSER_LIVE_OBSERVABILITY_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_ALERT_LEDGER_ENABLED: bool = False
    CANONICAL_PARSER_LIVE_OBSERVABILITY_SNAPSHOT_TTL_SECONDS: int = Field(
        default=60, ge=5, le=3600
    )
    CANONICAL_PARSER_LIVE_OBSERVABILITY_STALE_SUBMISSION_SECONDS: int = Field(
        default=300, ge=30, le=86400
    )
    CANONICAL_PARSER_LIVE_OBSERVABILITY_CRITICAL_OPEN_ALERT_THRESHOLD: int = Field(
        default=1, ge=1, le=1000
    )

    # =========================
    # M44 PREPRODUCTION CERTIFICATION & SINGLE-USE RELEASE APPROVAL
    # Manual certification; no deploy, LIVE enablement, signing or sending.
    # =========================

    CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_ENABLED: bool = False
    CANONICAL_PARSER_PREPRODUCTION_RELEASE_GUARD_ENABLED: bool = False
    CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_TTL_MINUTES: int = Field(
        default=30, ge=1, le=1440
    )
    CANONICAL_PARSER_PREPRODUCTION_MAX_RELEASE_VALIDITY_MINUTES: int = Field(
        default=10, ge=1, le=1440
    )
    CANONICAL_PARSER_PREPRODUCTION_MIN_FULL_TEST_COUNT: int = Field(
        default=1188, ge=1, le=1000000
    )
    CANONICAL_PARSER_PREPRODUCTION_REQUIRED_FASTAPI_VERSION: str = "0.138.2"
    CANONICAL_PARSER_PREPRODUCTION_REQUIRE_HEALTHY_OBSERVABILITY: bool = True
    CANONICAL_PARSER_PREPRODUCTION_REQUIRE_ZERO_OPEN_CRITICAL_ALERTS: bool = True

    # M45 ASSISTED MICRO-LIVE PILOT & RUNBOOK
    CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_ENABLED: bool = False
    CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_GUARD_ENABLED: bool = False
    CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_VALIDITY_MINUTES: int = Field(default=60, ge=5, le=1440)
    CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_ENTRY_BUDGET_SOL: float = Field(default=0.005, gt=0, le=1)
    CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_TOTAL_FEE_SOL: float = Field(default=0.001, ge=0, le=1)
    CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_POSITION_DURATION_MINUTES: int = Field(default=30, ge=1, le=1440)
    CANONICAL_PARSER_ASSISTED_MICRO_LIVE_REQUIRE_HEALTHY_OBSERVABILITY: bool = True
    CANONICAL_PARSER_ASSISTED_MICRO_LIVE_REQUIRE_ACTIVE_CERTIFICATION: bool = True

    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_ENABLED: bool = False
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_GUARD_ENABLED: bool = False
    CANONICAL_PARSER_PRODUCTION_CIRCUIT_BREAKER_ENABLED: bool = False
    CANONICAL_PARSER_PRODUCTION_HARDENING_ASSESSMENT_TTL_MINUTES: int = Field(default=15, ge=1, le=1440)
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_PILOT_LOOKBACK_DAYS: int = Field(default=30, ge=1, le=3650)
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MIN_COMPLETED_PILOTS_ASSISTED: int = Field(default=1, ge=1, le=1000)
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MIN_COMPLETED_PILOTS_SUPERVISED: int = Field(default=3, ge=1, le=1000)
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MIN_COMPLETED_PILOTS_CANDIDATE: int = Field(default=5, ge=1, le=1000)
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MAX_VALIDITY_MINUTES: int = Field(default=60, ge=1, le=1440)
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MAX_BUDGET_SOL: float = Field(default=0.01, gt=0, le=1)
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MAX_SUBMISSIONS: int = Field(default=10, ge=1, le=100)
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_REQUIRE_HEALTHY_OBSERVABILITY: bool = True
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_REQUIRE_ZERO_ACTIVE_INCIDENTS: bool = True
    CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_REQUIRE_ZERO_UNCERTAIN_SUBMISSIONS: bool = True

    # =========================
    # M47 GEN4 WALK-FORWARD PROFITABILITY VALIDATION
    # Historical analytics only; disabled by default; no execution connections.
    # =========================

    CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED: bool = False
    CANONICAL_PARSER_GEN4_PROFITABILITY_TRAINING_DAYS: int = Field(default=14, ge=3, le=365)
    CANONICAL_PARSER_GEN4_PROFITABILITY_TEST_DAYS: int = Field(default=7, ge=1, le=90)
    CANONICAL_PARSER_GEN4_PROFITABILITY_STEP_DAYS: int = Field(default=7, ge=1, le=90)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WINDOWS: int = Field(default=4, ge=1, le=24)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_SOURCE_TRADES: int = Field(default=100000, ge=100, le=1000000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TRAINING_SOURCE_TRADES: int = Field(default=10, ge=1, le=100000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TRAINING_CLOSED_POSITIONS: int = Field(default=5, ge=1, le=100000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_WALLET_WIN_RATE_PERCENT: float = Field(default=40.0, ge=0, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_WALLET_PROFIT_FACTOR: float = Field(default=1.10, ge=0, le=1000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_DRAWDOWN_PERCENT: float = Field(default=25.0, ge=0, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_OPEN_POSITIONS: int = Field(default=2, ge=0, le=1000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_CONSENSUS_WINDOW_SECONDS: int = Field(default=180, ge=1, le=86400)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_QUALIFIED_WALLETS: int = Field(default=2, ge=1, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_INDEPENDENT_CLUSTERS: int = Field(default=2, ge=1, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_EDGE_STRENGTH: float = Field(default=60.0, ge=0, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_TOKEN_SNAPSHOT_MAX_AGE_MINUTES: int = Field(default=30, ge=1, le=10080)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TOKEN_LIQUIDITY_USD: float = Field(default=25000.0, ge=0, le=1000000000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_TOKEN_RISK_SCORE: int = Field(default=35, ge=0, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_TOP_HOLDER_PERCENT: float = Field(default=25.0, ge=0, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_STARTING_CAPITAL_SOL: float = Field(default=1.0, gt=0, le=1000000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_ORDER_SIZE_SOL: float = Field(default=0.005, gt=0, le=1000000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_SLIPPAGE_BPS: int = Field(default=100, ge=0, le=10000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_FEE_BPS: int = Field(default=10, ge=0, le=10000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_COPY_DELAY_SECONDS: int = Field(default=8, ge=0, le=86400)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_EXECUTION_LAG_SECONDS: int = Field(default=180, ge=1, le=86400)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_OPEN_POSITIONS: int = Field(default=5, ge=1, le=1000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_STOP_LOSS_PERCENT: float = Field(default=15.0, gt=0, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_TAKE_PROFIT_PERCENT: float = Field(default=30.0, gt=0, le=10000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_HOLD_MINUTES: int = Field(default=240, ge=1, le=10080)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_EVALUABLE_CLOSED_TRADES: int = Field(default=30, ge=1, le=1000000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PROOF_CLOSED_TRADES: int = Field(default=100, ge=1, le=1000000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PORTFOLIO_PROFIT_FACTOR: float = Field(default=1.30, ge=0, le=1000)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PORTFOLIO_DRAWDOWN_PERCENT: float = Field(default=25.0, ge=0, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_POSITIVE_WINDOW_PERCENT: float = Field(default=60.0, ge=0, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_PROFIT_CONCENTRATION_PERCENT: float = Field(default=40.0, ge=0, le=100)
    CANONICAL_PARSER_GEN4_PROFITABILITY_EXCLUDED_TOKEN_MINTS: str = ""
    CANONICAL_PARSER_GEN4_PROFITABILITY_PRICE_CONTINUITY_WINDOW_SECONDS: int = Field(
        default=3600,
        ge=60,
        le=86400,
    )
    CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PRICE_DISCONTINUITY_RATIO: float = Field(
        default=25.0,
        ge=1.01,
        le=1000000.0,
    )

    # =========================
    # M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN
    # Metadata-only forward observation; disabled by default; no execution connections.
    # =========================

    CANONICAL_PARSER_GEN4_FORWARD_ENABLED: bool = False
    CANONICAL_PARSER_GEN4_FORWARD_TRAINING_DAYS: int = Field(default=14, ge=3, le=365)
    CANONICAL_PARSER_GEN4_FORWARD_MIN_FROZEN_WALLETS: int = Field(default=2, ge=2, le=100)
    CANONICAL_PARSER_GEN4_FORWARD_MAX_FROZEN_WALLETS: int = Field(default=20, ge=2, le=100)
    CANONICAL_PARSER_GEN4_FORWARD_MIN_OBSERVATION_DAYS: int = Field(default=21, ge=1, le=3650)
    CANONICAL_PARSER_GEN4_FORWARD_MIN_CLOSED_TRADES: int = Field(default=30, ge=1, le=1000000)
    CANONICAL_PARSER_GEN4_FORWARD_PROOF_CLOSED_TRADES: int = Field(default=100, ge=1, le=1000000)
    CANONICAL_PARSER_GEN4_FORWARD_MAX_SOURCE_TRADES_PER_CYCLE: int = Field(default=200000, ge=100, le=2000000)
    CANONICAL_PARSER_GEN4_FORWARD_MAX_INGESTION_LAG_SECONDS: int = Field(default=300, ge=1, le=86400)
    CANONICAL_PARSER_GEN4_FORWARD_MAX_SAFETY_WAIT_MINUTES: int = Field(default=30, ge=1, le=10080)

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
