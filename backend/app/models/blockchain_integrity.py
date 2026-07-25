from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


_PRIMARY_KEY_TYPE = BigInteger().with_variant(Integer, "sqlite")


class RawBlockchainEvent(Base):
    __tablename__ = "raw_blockchain_events"

    __table_args__ = (
        CheckConstraint(
            "observation_count >= 1",
            name="ck_raw_blockchain_events_observation_count_positive",
        ),
        CheckConstraint(
            "slot IS NULL OR slot >= 0",
            name="ck_raw_blockchain_events_slot_nonnegative",
        ),
        CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_raw_blockchain_events_payload_hash_length",
        ),
        CheckConstraint(
            "length(deduplication_key) = 64",
            name="ck_raw_blockchain_events_deduplication_key_length",
        ),
        UniqueConstraint(
            "deduplication_key",
            name="uq_raw_blockchain_events_deduplication_key",
        ),
        Index(
            "ix_raw_blockchain_events_provider_chain_network",
            "provider",
            "chain",
            "network",
        ),
        Index(
            "ix_raw_blockchain_events_signature",
            "transaction_signature",
        ),
        Index(
            "ix_raw_blockchain_events_wallet_first_seen",
            "observed_wallet",
            "first_seen_at",
        ),
        Index(
            "ix_raw_blockchain_events_block_time",
            "block_time",
        ),
        Index(
            "ix_raw_blockchain_events_payload_hash",
            "payload_hash",
        ),
    )

    id: Mapped[int] = mapped_column(
        _PRIMARY_KEY_TYPE,
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    network: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    transaction_signature: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    slot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    block_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    observed_wallet: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    commitment: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    raw_payload: Mapped[dict | list] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    event_metadata: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    observation_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class NormalizationRun(Base):
    __tablename__ = "normalization_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', "
            "'PARTIAL', 'FAILED', 'SKIPPED')",
            name="ck_normalization_runs_status",
        ),
        CheckConstraint(
            "produced_event_count >= 0",
            name="ck_normalization_runs_event_count_nonnegative",
        ),
        CheckConstraint(
            "produced_trade_count >= 0",
            name="ck_normalization_runs_trade_count_nonnegative",
        ),
        UniqueConstraint(
            "run_id",
            name="uq_normalization_runs_run_id",
        ),
        Index(
            "ix_normalization_runs_raw_parser_version_status",
            "raw_event_id",
            "parser_name",
            "parser_version",
            "status",
        ),
        Index(
            "ix_normalization_runs_parser_version",
            "parser_name",
            "parser_version",
        ),
        Index(
            "ix_normalization_runs_status_created_at",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        _PRIMARY_KEY_TYPE,
        primary_key=True,
    )
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    raw_event_id: Mapped[int] = mapped_column(
        ForeignKey(
            "raw_blockchain_events.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default="PENDING",
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    produced_event_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    produced_trade_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    warnings: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_metadata: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
