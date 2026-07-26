from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
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


class NormalizationArtifact(Base):
    __tablename__ = "normalization_artifacts"

    __table_args__ = (
        CheckConstraint(
            "artifact_index >= 0",
            name="ck_normalization_artifacts_index_nonnegative",
        ),
        CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_normalization_artifacts_payload_hash_length",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_normalization_artifacts_implementation_hash_length",
        ),
        UniqueConstraint(
            "raw_event_id",
            "parser_name",
            "parser_version",
            "artifact_type",
            "artifact_index",
            name="uq_normalization_artifacts_event_parser_output",
        ),
        Index(
            "ix_normalization_artifacts_run_index",
            "normalization_run_id",
            "artifact_index",
        ),
        Index(
            "ix_normalization_artifacts_event_parser_version",
            "raw_event_id",
            "parser_name",
            "parser_version",
        ),
        Index(
            "ix_normalization_artifacts_payload_hash",
            "payload_hash",
        ),
    )

    id: Mapped[int] = mapped_column(
        _PRIMARY_KEY_TYPE,
        primary_key=True,
    )
    normalization_run_id: Mapped[int] = mapped_column(
        ForeignKey(
            "normalization_runs.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    raw_event_id: Mapped[int] = mapped_column(
        ForeignKey(
            "raw_blockchain_events.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    artifact_index: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict | list] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_metadata: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class NormalizationReplayBatch(Base):
    __tablename__ = "normalization_replay_batches"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')",
            name="ck_normalization_replay_batches_status",
        ),
        CheckConstraint(
            "selection_mode IN ('UNNORMALIZED', 'OUTDATED', 'REPROCESS')",
            name="ck_normalization_replay_batches_selection_mode",
        ),
        CheckConstraint(
            "requested_limit >= 1",
            name="ck_normalization_replay_batches_limit_positive",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_normalization_replay_batches_implementation_hash_length",
        ),
        CheckConstraint(
            "selected_count >= 0 AND processed_count >= 0 "
            "AND completed_count >= 0 AND failed_count >= 0 "
            "AND skipped_count >= 0",
            name="ck_normalization_replay_batches_counts_nonnegative",
        ),
        UniqueConstraint(
            "replay_id",
            name="uq_normalization_replay_batches_replay_id",
        ),
        Index(
            "ix_normalization_replay_batches_parser_version_status",
            "parser_name",
            "parser_version",
            "status",
        ),
        Index(
            "ix_normalization_replay_batches_status_created_at",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        _PRIMARY_KEY_TYPE,
        primary_key=True,
    )
    replay_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    selection_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default="RUNNING",
        nullable=False,
    )
    request_filters: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    processed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    completed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

class CanonicalNormalizedEvent(Base):
    __tablename__ = "canonical_normalized_events"

    __table_args__ = (
        CheckConstraint(
            "quality_status IN ('PASS', 'WARN', 'FAIL')",
            name="ck_canonical_normalized_events_quality_status",
        ),
        CheckConstraint(
            "side IN ('BUY', 'SELL', 'UNKNOWN')",
            name="ck_canonical_normalized_events_side",
        ),
        CheckConstraint(
            "length(canonical_event_key) = 64",
            name="ck_canonical_normalized_events_key_length",
        ),
        CheckConstraint(
            "length(canonical_payload_hash) = 64",
            name="ck_canonical_normalized_events_payload_hash_length",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_normalized_events_implementation_hash_length",
        ),
        UniqueConstraint(
            "canonical_event_id",
            name="uq_canonical_normalized_events_canonical_event_id",
        ),
        UniqueConstraint(
            "normalization_artifact_id",
            name="uq_canonical_normalized_events_artifact_id",
        ),
        UniqueConstraint(
            "canonical_event_key",
            name="uq_canonical_normalized_events_event_key",
        ),
        Index(
            "ix_canonical_normalized_events_signature_wallet",
            "transaction_signature",
            "observed_wallet",
        ),
        Index(
            "ix_canonical_normalized_events_parser_version",
            "parser_name",
            "parser_version",
        ),
        Index(
            "ix_canonical_normalized_events_block_time",
            "block_time",
        ),
        Index(
            "ix_canonical_normalized_events_quality_created",
            "quality_status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    canonical_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    canonical_event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("normalization_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    normalization_run_id: Mapped[int] = mapped_column(
        ForeignKey("normalization_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    raw_event_id: Mapped[int] = mapped_column(
        ForeignKey("raw_blockchain_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_type: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_signature: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    observed_wallet: Mapped[str | None] = mapped_column(String(64), nullable=True)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    token_mint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    sol_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    fee_lamports: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    success: Mapped[bool] = mapped_column(nullable=False)
    block_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quality_status: Mapped[str] = mapped_column(String(16), nullable=False)
    quality_flags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    canonical_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    canonical_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalShadowValidationBatch(Base):
    __tablename__ = "canonical_shadow_validation_batches"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')",
            name="ck_canonical_shadow_validation_batches_status",
        ),
        CheckConstraint(
            "requested_limit >= 1",
            name="ck_canonical_shadow_validation_batches_limit_positive",
        ),
        CheckConstraint(
            "selected_count >= 0 AND processed_count >= 0 "
            "AND match_count >= 0 AND mismatch_count >= 0 "
            "AND missing_trade_count >= 0 AND not_comparable_count >= 0 "
            "AND failed_count >= 0",
            name="ck_canonical_shadow_validation_batches_counts_nonnegative",
        ),
        UniqueConstraint(
            "validation_id",
            name="uq_canonical_shadow_validation_batches_validation_id",
        ),
        Index(
            "ix_canonical_shadow_validation_batches_status_created",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    validation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    comparator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request_filters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    match_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mismatch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_trade_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    not_comparable_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalShadowValidationResult(Base):
    __tablename__ = "canonical_shadow_validation_results"

    __table_args__ = (
        CheckConstraint(
            "status IN ('MATCH', 'MISMATCH', 'MISSING_TRADE', 'NOT_COMPARABLE')",
            name="ck_canonical_shadow_validation_results_status",
        ),
        CheckConstraint(
            "length(canonical_snapshot_hash) = 64",
            name="ck_canonical_shadow_validation_results_canonical_hash_length",
        ),
        CheckConstraint(
            "trade_snapshot_hash IS NULL OR length(trade_snapshot_hash) = 64",
            name="ck_canonical_shadow_validation_results_trade_hash_length",
        ),
        UniqueConstraint(
            "validation_batch_id",
            "canonical_event_id",
            name="uq_canonical_shadow_validation_results_batch_event",
        ),
        Index(
            "ix_canonical_shadow_validation_results_status_created",
            "status",
            "created_at",
        ),
        Index(
            "ix_canonical_shadow_validation_results_signature",
            "transaction_signature",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    validation_batch_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_shadow_validation_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_event_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_normalized_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), nullable=True
    )
    transaction_signature: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    comparator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    mismatch_fields: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    canonical_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    trade_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    canonical_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_snapshot_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalQualityAssessment(Base):
    __tablename__ = "canonical_quality_assessments"

    __table_args__ = (
        CheckConstraint(
            "status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_canonical_quality_assessments_status",
        ),
        CheckConstraint(
            "sample_size >= 0 AND comparable_count >= 0 "
            "AND match_count >= 0 AND mismatch_count >= 0 "
            "AND missing_trade_count >= 0 AND not_comparable_count >= 0 "
            "AND failed_count >= 0 AND quality_pass_count >= 0 "
            "AND quality_warn_count >= 0 AND quality_fail_count >= 0",
            name="ck_canonical_quality_assessments_counts_nonnegative",
        ),
        CheckConstraint(
            "match_rate >= 0 AND match_rate <= 100 "
            "AND mismatch_rate >= 0 AND mismatch_rate <= 100 "
            "AND missing_trade_rate >= 0 AND missing_trade_rate <= 100 "
            "AND not_comparable_rate >= 0 AND not_comparable_rate <= 100 "
            "AND failed_rate >= 0 AND failed_rate <= 100 "
            "AND quality_pass_rate >= 0 AND quality_pass_rate <= 100",
            name="ck_canonical_quality_assessments_rates_range",
        ),
        CheckConstraint(
            "length(assessment_key) = 64",
            name="ck_canonical_quality_assessments_key_length",
        ),
        CheckConstraint(
            "length(policy_hash) = 64",
            name="ck_canonical_quality_assessments_policy_hash_length",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_canonical_quality_assessments_evidence_hash_length",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_quality_assessments_parser_hash_length",
        ),
        UniqueConstraint(
            "assessment_id",
            name="uq_canonical_quality_assessments_assessment_id",
        ),
        UniqueConstraint(
            "assessment_key",
            name="uq_canonical_quality_assessments_assessment_key",
        ),
        Index(
            "ix_canonical_quality_assessments_status_evaluated",
            "status",
            "evaluated_at",
        ),
        Index(
            "ix_canonical_quality_assessments_validation_batch",
            "validation_batch_id",
        ),
        Index(
            "ix_canonical_quality_assessments_parser_version",
            "parser_name",
            "parser_version",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_batch_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_shadow_validation_batches.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    validation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    comparator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comparable_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    match_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mismatch_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    missing_trade_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    not_comparable_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quality_pass_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    quality_warn_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    quality_fail_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    match_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        default=Decimal("0"),
        nullable=False,
    )
    mismatch_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        default=Decimal("0"),
        nullable=False,
    )
    missing_trade_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        default=Decimal("0"),
        nullable=False,
    )
    not_comparable_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        default=Decimal("0"),
        nullable=False,
    )
    failed_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        default=Decimal("0"),
        nullable=False,
    )
    quality_pass_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        default=Decimal("0"),
        nullable=False,
    )
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    mismatch_field_counts: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    threshold_snapshot: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    metrics_snapshot: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    technical_metadata: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    evidence_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
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

class CanonicalParserPromotion(Base):
    __tablename__ = "canonical_parser_promotions"

    __table_args__ = (
        CheckConstraint(
            "status IN ('APPROVED', 'REVOKED')",
            name="ck_canonical_parser_promotions_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_canonical_parser_promotions_scope",
        ),
        CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_canonical_parser_promotions_event_sequence_positive",
        ),
        CheckConstraint(
            "length(promotion_key) = 64",
            name="ck_canonical_parser_promotions_key_length",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_parser_promotions_parser_hash_length",
        ),
        CheckConstraint(
            "length(assessment_policy_hash) = 64",
            name="ck_canonical_parser_promotions_assessment_policy_hash_length",
        ),
        CheckConstraint(
            "length(assessment_evidence_hash) = 64",
            name="ck_canonical_parser_promotions_assessment_evidence_hash_length",
        ),
        CheckConstraint(
            "length(promotion_policy_hash) = 64",
            name="ck_canonical_parser_promotions_policy_hash_length",
        ),
        CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_canonical_parser_promotions_manifest_hash_length",
        ),
        CheckConstraint(
            "length(latest_event_hash) = 64",
            name="ck_canonical_parser_promotions_latest_event_hash_length",
        ),
        UniqueConstraint(
            "promotion_id",
            name="uq_canonical_parser_promotions_promotion_id",
        ),
        UniqueConstraint(
            "promotion_key",
            name="uq_canonical_parser_promotions_promotion_key",
        ),
        Index(
            "ix_canonical_parser_promotions_status_scope",
            "status",
            "scope",
        ),
        Index(
            "ix_canonical_parser_promotions_assessment",
            "assessment_db_id",
        ),
        Index(
            "ix_canonical_parser_promotions_parser_version",
            "parser_name",
            "parser_version",
        ),
        Index(
            "uq_canonical_parser_promotions_active_parser_scope",
            "parser_name",
            "scope",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
            sqlite_where=text("status = 'APPROVED'"),
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_key: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_quality_assessments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(32), default="SHADOW_ONLY", nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    output_schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    assessment_policy_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    assessment_evidence_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    promotion_policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    promotion_policy_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    release_manifest: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    release_manifest_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    latest_event_sequence: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    latest_event_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalParserPromotionEvent(Base):
    __tablename__ = "canonical_parser_promotion_events"

    __table_args__ = (
        CheckConstraint(
            "sequence >= 1",
            name="ck_canonical_parser_promotion_events_sequence_positive",
        ),
        CheckConstraint(
            "event_type IN ('APPROVED', 'REVOKED')",
            name="ck_canonical_parser_promotion_events_type",
        ),
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN ('APPROVED', 'REVOKED')",
            name="ck_canonical_parser_promotion_events_previous_status",
        ),
        CheckConstraint(
            "new_status IN ('APPROVED', 'REVOKED')",
            name="ck_canonical_parser_promotion_events_new_status",
        ),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_canonical_parser_promotion_events_previous_hash_length",
        ),
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_canonical_parser_promotion_events_hash_length",
        ),
        UniqueConstraint(
            "event_id",
            name="uq_canonical_parser_promotion_events_event_id",
        ),
        UniqueConstraint(
            "promotion_db_id",
            "sequence",
            name="uq_canonical_parser_promotion_events_promotion_sequence",
        ),
        Index(
            "ix_canonical_parser_promotion_events_type_occurred",
            "event_type",
            "occurred_at",
        ),
        Index(
            "ix_canonical_parser_promotion_events_promotion_sequence",
            "promotion_db_id",
            "sequence",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_promotions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class CanonicalParserRuntimeBinding(Base):
    __tablename__ = "canonical_parser_runtime_bindings"

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'UNBOUND')",
            name="ck_canonical_parser_runtime_bindings_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_canonical_parser_runtime_bindings_scope",
        ),
        CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_canonical_parser_runtime_bindings_channel",
        ),
        CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_canonical_parser_runtime_bindings_event_sequence_positive",
        ),
        CheckConstraint(
            "length(binding_key) = 64",
            name="ck_canonical_parser_runtime_bindings_key_length",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_parser_runtime_bindings_parser_hash_length",
        ),
        CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_canonical_parser_runtime_bindings_release_hash_length",
        ),
        CheckConstraint(
            "length(binding_policy_hash) = 64",
            name="ck_canonical_parser_runtime_bindings_policy_hash_length",
        ),
        CheckConstraint(
            "length(latest_event_hash) = 64",
            name="ck_canonical_parser_runtime_bindings_latest_event_hash_length",
        ),
        UniqueConstraint(
            "binding_id",
            name="uq_canonical_parser_runtime_bindings_binding_id",
        ),
        UniqueConstraint(
            "binding_key",
            name="uq_canonical_parser_runtime_bindings_binding_key",
        ),
        Index(
            "ix_canonical_parser_runtime_bindings_status_scope_channel",
            "status",
            "scope",
            "channel",
        ),
        Index(
            "ix_canonical_parser_runtime_bindings_promotion",
            "promotion_db_id",
        ),
        Index(
            "ix_canonical_parser_runtime_bindings_parser_version",
            "parser_name",
            "parser_version",
        ),
        Index(
            "uq_canonical_parser_runtime_bindings_active_scope_channel",
            "scope",
            "channel",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_key: Mapped[str] = mapped_column(String(64), nullable=False)
    promotion_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_promotions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    bound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    unbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unbind_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalParserRuntimeBindingEvent(Base):
    __tablename__ = "canonical_parser_runtime_binding_events"

    __table_args__ = (
        CheckConstraint(
            "sequence >= 1",
            name="ck_canonical_parser_runtime_binding_events_sequence_positive",
        ),
        CheckConstraint(
            "event_type IN ('BOUND', 'UNBOUND')",
            name="ck_canonical_parser_runtime_binding_events_type",
        ),
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN ('ACTIVE', 'UNBOUND')",
            name="ck_canonical_parser_runtime_binding_events_previous_status",
        ),
        CheckConstraint(
            "new_status IN ('ACTIVE', 'UNBOUND')",
            name="ck_canonical_parser_runtime_binding_events_new_status",
        ),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_canonical_parser_runtime_binding_events_previous_hash_length",
        ),
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_canonical_parser_runtime_binding_events_hash_length",
        ),
        UniqueConstraint(
            "event_id",
            name="uq_canonical_parser_runtime_binding_events_event_id",
        ),
        UniqueConstraint(
            "binding_db_id",
            "sequence",
            name="uq_canonical_parser_runtime_binding_events_binding_sequence",
        ),
        Index(
            "ix_canonical_parser_runtime_binding_events_type_occurred",
            "event_type",
            "occurred_at",
        ),
        Index(
            "ix_canonical_parser_runtime_binding_events_binding_sequence",
            "binding_db_id",
            "sequence",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_runtime_bindings.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserAdmissionRun(Base):
    __tablename__ = "canonical_parser_admission_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')",
            name="ck_canonical_parser_admission_runs_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_canonical_parser_admission_runs_scope",
        ),
        CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_canonical_parser_admission_runs_channel",
        ),
        CheckConstraint(
            "requested_limit >= 1 AND selected_count >= 0 "
            "AND processed_count >= 0 AND passed_count >= 0 "
            "AND failed_count >= 0 AND skipped_count >= 0",
            name="ck_canonical_parser_admission_runs_counts_nonnegative",
        ),
        CheckConstraint(
            "selected_count >= processed_count",
            name="ck_canonical_parser_admission_runs_selected_processed",
        ),
        CheckConstraint(
            "processed_count = passed_count + failed_count + skipped_count",
            name="ck_canonical_parser_admission_runs_processed_breakdown",
        ),
        CheckConstraint(
            "length(admission_key) = 64",
            name="ck_canonical_parser_admission_runs_key_length",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_parser_admission_runs_parser_hash_length",
        ),
        CheckConstraint(
            "length(binding_event_hash) = 64",
            name="ck_canonical_parser_admission_runs_binding_hash_length",
        ),
        CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_canonical_parser_admission_runs_release_hash_length",
        ),
        CheckConstraint(
            "length(admission_policy_hash) = 64",
            name="ck_canonical_parser_admission_runs_policy_hash_length",
        ),
        UniqueConstraint(
            "admission_id",
            name="uq_canonical_parser_admission_runs_admission_id",
        ),
        UniqueConstraint(
            "admission_key",
            name="uq_canonical_parser_admission_runs_admission_key",
        ),
        Index(
            "ix_canonical_parser_admission_runs_status_started",
            "status",
            "started_at",
        ),
        Index(
            "ix_canonical_parser_admission_runs_binding",
            "binding_db_id",
        ),
        Index(
            "ix_canonical_parser_admission_runs_parser_version",
            "parser_name",
            "parser_version",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    admission_id: Mapped[str] = mapped_column(String(36), nullable=False)
    admission_key: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_runtime_bindings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    admission_policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    admission_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    selection_snapshot: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    metrics_snapshot: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalParserAdmissionResult(Base):
    __tablename__ = "canonical_parser_admission_results"

    __table_args__ = (
        CheckConstraint(
            "status IN ('PASS', 'FAIL', 'SKIPPED')",
            name="ck_canonical_parser_admission_results_status",
        ),
        CheckConstraint(
            "artifact_count >= 0",
            name="ck_canonical_parser_admission_results_artifact_count",
        ),
        CheckConstraint(
            "first_output_hash IS NULL OR length(first_output_hash) = 64",
            name="ck_canonical_parser_admission_results_first_hash_length",
        ),
        CheckConstraint(
            "second_output_hash IS NULL OR length(second_output_hash) = 64",
            name="ck_canonical_parser_admission_results_second_hash_length",
        ),
        UniqueConstraint(
            "result_id",
            name="uq_canonical_parser_admission_results_result_id",
        ),
        UniqueConstraint(
            "admission_run_db_id",
            "raw_event_id",
            name="uq_canonical_parser_admission_results_run_event",
        ),
        Index(
            "ix_canonical_parser_admission_results_run_status",
            "admission_run_db_id",
            "status",
        ),
        Index(
            "ix_canonical_parser_admission_results_raw_event",
            "raw_event_id",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    admission_run_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_admission_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_event_id: Mapped[int] = mapped_column(
        ForeignKey("raw_blockchain_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deterministic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    first_output_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    second_output_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    artifact_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    artifact_summary: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserRuntimeCertification(Base):
    __tablename__ = "canonical_parser_runtime_certifications"

    __table_args__ = (
        CheckConstraint(
            "status IN ('CERTIFIED', 'REVOKED')",
            name="ck_canonical_parser_runtime_certifications_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_canonical_parser_runtime_certifications_scope",
        ),
        CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_canonical_parser_runtime_certifications_channel",
        ),
        CheckConstraint(
            "admission_run_count >= 1",
            name="ck_canonical_parser_runtime_certifications_run_count",
        ),
        CheckConstraint(
            "total_processed_count >= 0 AND total_passed_count >= 0 AND total_failed_count >= 0 AND total_skipped_count >= 0",
            name="ck_canonical_parser_runtime_certifications_counts_nonnegative",
        ),
        CheckConstraint(
            "pass_rate >= 0 AND pass_rate <= 100",
            name="ck_canonical_parser_runtime_certifications_pass_rate",
        ),
        CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_canonical_parser_runtime_certifications_sequence_positive",
        ),
        CheckConstraint("length(certification_key) = 64", name="ck_canonical_parser_runtime_certifications_key_length"),
        CheckConstraint("length(parser_implementation_hash) = 64", name="ck_canonical_parser_runtime_certifications_parser_hash_length"),
        CheckConstraint("length(release_manifest_hash) = 64", name="ck_canonical_parser_runtime_certifications_release_hash_length"),
        CheckConstraint("length(certification_policy_hash) = 64", name="ck_canonical_parser_runtime_certifications_policy_hash_length"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_canonical_parser_runtime_certifications_evidence_hash_length"),
        CheckConstraint("length(latest_event_hash) = 64", name="ck_canonical_parser_runtime_certifications_latest_hash_length"),
        UniqueConstraint("certification_id", name="uq_canonical_parser_runtime_certifications_id"),
        UniqueConstraint("certification_key", name="uq_canonical_parser_runtime_certifications_key"),
        Index("ix_canonical_parser_runtime_certifications_binding_status", "binding_db_id", "status"),
        Index("ix_canonical_parser_runtime_certifications_parser_version", "parser_name", "parser_version"),
        Index("ix_canonical_parser_runtime_certifications_expires", "status", "expires_at"),
        Index(
            "uq_canonical_parser_runtime_certifications_active_binding",
            "binding_db_id",
            unique=True,
            postgresql_where=text("status = 'CERTIFIED'"),
            sqlite_where=text("status = 'CERTIFIED'"),
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_key: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_runtime_bindings.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    admission_run_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    admission_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_processed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    certified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CanonicalParserRuntimeCertificationEvent(Base):
    __tablename__ = "canonical_parser_runtime_certification_events"

    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_canonical_parser_runtime_certification_events_sequence"),
        CheckConstraint("event_type IN ('CERTIFIED', 'REVOKED')", name="ck_canonical_parser_runtime_certification_events_type"),
        CheckConstraint("previous_status IS NULL OR previous_status IN ('CERTIFIED', 'REVOKED')", name="ck_canonical_parser_cert_events_prev_status"),
        CheckConstraint("new_status IN ('CERTIFIED', 'REVOKED')", name="ck_canonical_parser_runtime_certification_events_new_status"),
        CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_canonical_parser_cert_events_prev_hash_len"),
        CheckConstraint("length(event_hash) = 64", name="ck_canonical_parser_runtime_certification_events_hash_length"),
        UniqueConstraint("event_id", name="uq_canonical_parser_runtime_certification_events_id"),
        UniqueConstraint("certification_db_id", "sequence", name="uq_canonical_parser_runtime_certification_events_sequence"),
        Index("ix_canonical_parser_runtime_certification_events_cert_sequence", "certification_db_id", "sequence"),
        Index("ix_canonical_parser_runtime_certification_events_type_time", "event_type", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_runtime_certifications.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserShadowRuntimeLease(Base):
    __tablename__ = "canonical_parser_shadow_runtime_leases"

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED', 'EXPIRED')",
            name="ck_canonical_parser_shadow_runtime_leases_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_canonical_parser_shadow_runtime_leases_scope",
        ),
        CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_canonical_parser_shadow_runtime_leases_channel",
        ),
        CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_RUNTIME')",
            name="ck_canonical_parser_shadow_runtime_leases_consumer",
        ),
        CheckConstraint(
            "lease_generation >= 1",
            name="ck_canonical_parser_shadow_runtime_leases_generation",
        ),
        CheckConstraint(
            "requested_validity_minutes >= 5",
            name="ck_canonical_parser_shadow_runtime_leases_validity",
        ),
        CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_canonical_parser_shadow_runtime_leases_sequence",
        ),
        CheckConstraint(
            "length(lease_key) = 64",
            name="ck_canonical_parser_shadow_runtime_leases_key_length",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_parser_shadow_runtime_leases_parser_hash_length",
        ),
        CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_canonical_parser_shadow_runtime_leases_release_hash_length",
        ),
        CheckConstraint(
            "length(certification_event_hash) = 64",
            name="ck_canonical_parser_shadow_runtime_leases_cert_hash_length",
        ),
        CheckConstraint(
            "length(lease_policy_hash) = 64",
            name="ck_canonical_parser_shadow_runtime_leases_policy_hash_length",
        ),
        CheckConstraint(
            "length(latest_event_hash) = 64",
            name="ck_canonical_parser_shadow_runtime_leases_latest_hash_length",
        ),
        UniqueConstraint(
            "lease_id",
            name="uq_canonical_parser_shadow_runtime_leases_id",
        ),
        UniqueConstraint(
            "lease_key",
            name="uq_canonical_parser_shadow_runtime_leases_key",
        ),
        UniqueConstraint(
            "consumer",
            "lease_generation",
            name="uq_canonical_parser_shadow_runtime_leases_generation",
        ),
        Index(
            "ix_canonical_parser_shadow_runtime_leases_cert_status",
            "certification_db_id",
            "status",
        ),
        Index(
            "ix_canonical_parser_shadow_runtime_leases_expires",
            "status",
            "expires_at",
        ),
        Index(
            "ix_canonical_parser_shadow_runtime_leases_parser_version",
            "parser_name",
            "parser_version",
        ),
        Index(
            "uq_canonical_parser_shadow_runtime_leases_active_consumer",
            "consumer",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    lease_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lease_key: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    certification_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_runtime_certifications.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    output_schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    release_manifest_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    certification_event_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    lease_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    requested_validity_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalParserShadowRuntimeLeaseEvent(Base):
    __tablename__ = "canonical_parser_shadow_runtime_lease_events"

    __table_args__ = (
        CheckConstraint(
            "sequence >= 1",
            name="ck_canonical_parser_shadow_runtime_lease_events_sequence",
        ),
        CheckConstraint(
            "event_type IN ('ISSUED', 'REVOKED', 'EXPIRED')",
            name="ck_canonical_parser_shadow_runtime_lease_events_type",
        ),
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN ('ACTIVE', 'REVOKED', 'EXPIRED')",
            name="ck_canonical_parser_shadow_runtime_lease_events_previous_status",
        ),
        CheckConstraint(
            "new_status IN ('ACTIVE', 'REVOKED', 'EXPIRED')",
            name="ck_canonical_parser_shadow_runtime_lease_events_new_status",
        ),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_canonical_shadow_lease_events_prev_hash_len",
        ),
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_canonical_parser_shadow_runtime_lease_events_hash_length",
        ),
        UniqueConstraint(
            "event_id",
            name="uq_canonical_parser_shadow_runtime_lease_events_id",
        ),
        UniqueConstraint(
            "lease_db_id",
            "sequence",
            name="uq_canonical_parser_shadow_runtime_lease_events_sequence",
        ),
        UniqueConstraint(
            "event_hash",
            name="uq_canonical_parser_shadow_runtime_lease_events_hash",
        ),
        Index(
            "ix_canonical_parser_shadow_runtime_lease_events_lease_sequence",
            "lease_db_id",
            "sequence",
        ),
        Index(
            "ix_canonical_parser_shadow_runtime_lease_events_type_time",
            "event_type",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lease_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_runtime_leases.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowConsumerRun(Base):
    __tablename__ = "canonical_parser_shadow_consumer_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')",
            name="ck_canonical_parser_shadow_consumer_runs_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_canonical_parser_shadow_consumer_runs_scope",
        ),
        CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_canonical_parser_shadow_consumer_runs_channel",
        ),
        CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_RUNTIME')",
            name="ck_canonical_parser_shadow_consumer_runs_consumer",
        ),
        CheckConstraint(
            "requested_limit >= 1 AND selected_count >= 0 "
            "AND processed_count >= 0 AND passed_count >= 0 "
            "AND failed_count >= 0 AND skipped_count >= 0 "
            "AND artifact_count >= 0",
            name="ck_canonical_parser_shadow_consumer_runs_counts_nonnegative",
        ),
        CheckConstraint(
            "selected_count >= processed_count",
            name="ck_canonical_parser_shadow_consumer_runs_selected_processed",
        ),
        CheckConstraint(
            "processed_count = passed_count + failed_count + skipped_count",
            name="ck_canonical_parser_shadow_consumer_runs_processed_breakdown",
        ),
        CheckConstraint(
            "length(run_key) = 64",
            name="ck_canonical_parser_shadow_consumer_runs_key_length",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_parser_shadow_consumer_runs_parser_hash_length",
        ),
        CheckConstraint(
            "length(lease_event_hash) = 64",
            name="ck_canonical_parser_shadow_consumer_runs_lease_hash_length",
        ),
        CheckConstraint(
            "length(certification_event_hash) = 64",
            name="ck_canonical_parser_shadow_consumer_runs_cert_hash_length",
        ),
        CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_canonical_parser_shadow_consumer_runs_release_hash_length",
        ),
        CheckConstraint(
            "length(consumer_policy_hash) = 64",
            name="ck_canonical_parser_shadow_consumer_runs_policy_hash_length",
        ),
        UniqueConstraint(
            "run_id",
            name="uq_canonical_parser_shadow_consumer_runs_id",
        ),
        UniqueConstraint(
            "run_key",
            name="uq_canonical_parser_shadow_consumer_runs_key",
        ),
        Index(
            "ix_canonical_parser_shadow_consumer_runs_lease_started",
            "lease_db_id",
            "started_at",
        ),
        Index(
            "ix_canonical_parser_shadow_consumer_runs_status_completed",
            "status",
            "completed_at",
        ),
        Index(
            "ix_canonical_parser_shadow_consumer_runs_parser_version",
            "parser_name",
            "parser_version",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_runtime_leases.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    lease_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    output_schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    release_manifest_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    lease_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_event_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    consumer_policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    consumer_policy_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    selection_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowConsumerResult(Base):
    __tablename__ = "canonical_parser_shadow_consumer_results"

    __table_args__ = (
        CheckConstraint(
            "status IN ('PASS', 'FAIL', 'SKIPPED')",
            name="ck_canonical_parser_shadow_consumer_results_status",
        ),
        CheckConstraint(
            "artifact_count >= 0",
            name="ck_canonical_parser_shadow_consumer_results_artifact_count",
        ),
        CheckConstraint(
            "length(raw_payload_hash) = 64",
            name="ck_canonical_parser_shadow_consumer_results_raw_hash_length",
        ),
        CheckConstraint(
            "output_hash IS NULL OR length(output_hash) = 64",
            name="ck_canonical_parser_shadow_consumer_results_output_hash_length",
        ),
        CheckConstraint(
            "verification_output_hash IS NULL OR length(verification_output_hash) = 64",
            name="ck_canonical_parser_shadow_consumer_results_verify_hash_length",
        ),
        UniqueConstraint(
            "result_id",
            name="uq_canonical_parser_shadow_consumer_results_id",
        ),
        UniqueConstraint(
            "consumer_run_db_id",
            "raw_event_id",
            name="uq_canonical_parser_shadow_consumer_results_run_event",
        ),
        Index(
            "ix_canonical_parser_shadow_consumer_results_run_status",
            "consumer_run_db_id",
            "status",
        ),
        Index(
            "ix_canonical_parser_shadow_consumer_results_raw_event",
            "raw_event_id",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    consumer_run_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_consumer_runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    raw_event_id: Mapped[int] = mapped_column(
        ForeignKey("raw_blockchain_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deterministic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_output_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    shadow_artifacts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowReadinessAssessment(Base):
    __tablename__ = "canonical_parser_shadow_readiness_assessments"

    __table_args__ = (
        CheckConstraint(
            "status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_shadow_readiness_assessments_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_shadow_readiness_assessments_scope",
        ),
        CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_shadow_readiness_assessments_channel",
        ),
        CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_RUNTIME')",
            name="ck_shadow_readiness_assessments_consumer",
        ),
        CheckConstraint(
            "run_count >= 0 AND total_processed_count >= 0 "
            "AND total_passed_count >= 0 AND total_failed_count >= 0 "
            "AND total_skipped_count >= 0 AND total_artifact_count >= 0 "
            "AND unique_event_count >= 0",
            name="ck_shadow_readiness_assessments_counts",
        ),
        CheckConstraint(
            "total_processed_count = total_passed_count + "
            "total_failed_count + total_skipped_count",
            name="ck_shadow_readiness_assessments_breakdown",
        ),
        CheckConstraint(
            "pass_rate >= 0 AND pass_rate <= 100",
            name="ck_shadow_readiness_assessments_pass_rate",
        ),
        CheckConstraint(
            "length(assessment_key) = 64",
            name="ck_shadow_readiness_assessments_key_len",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_shadow_readiness_assessments_parser_hash_len",
        ),
        CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_shadow_readiness_assessments_release_hash_len",
        ),
        CheckConstraint(
            "length(lease_event_hash) = 64",
            name="ck_shadow_readiness_assessments_lease_hash_len",
        ),
        CheckConstraint(
            "length(certification_event_hash) = 64",
            name="ck_shadow_readiness_assessments_cert_hash_len",
        ),
        CheckConstraint(
            "length(readiness_policy_hash) = 64",
            name="ck_shadow_readiness_assessments_policy_hash_len",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_shadow_readiness_assessments_evidence_hash_len",
        ),
        UniqueConstraint(
            "assessment_id",
            name="uq_shadow_readiness_assessments_id",
        ),
        UniqueConstraint(
            "assessment_key",
            name="uq_shadow_readiness_assessments_key",
        ),
        Index(
            "ix_shadow_readiness_assessments_lease_time",
            "lease_db_id",
            "evaluated_at",
        ),
        Index(
            "ix_shadow_readiness_assessments_status_valid",
            "status",
            "valid_until",
        ),
        Index(
            "ix_shadow_readiness_assessments_parser",
            "parser_name",
            "parser_version",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_runtime_leases.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    lease_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_event_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    readiness_policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    readiness_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_processed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), nullable=False
    )
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evidence_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    valid_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowReadinessEvidenceRun(Base):
    __tablename__ = "canonical_parser_shadow_readiness_evidence_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')",
            name="ck_shadow_readiness_evidence_runs_status",
        ),
        CheckConstraint(
            "result_count >= 0 AND processed_count >= 0 "
            "AND passed_count >= 0 AND failed_count >= 0 "
            "AND skipped_count >= 0 AND artifact_count >= 0",
            name="ck_shadow_readiness_evidence_runs_counts",
        ),
        CheckConstraint(
            "processed_count = passed_count + failed_count + skipped_count",
            name="ck_shadow_readiness_evidence_runs_breakdown",
        ),
        CheckConstraint(
            "length(run_key) = 64",
            name="ck_shadow_readiness_evidence_runs_key_len",
        ),
        CheckConstraint(
            "length(run_evidence_hash) = 64",
            name="ck_shadow_readiness_evidence_runs_hash_len",
        ),
        UniqueConstraint(
            "evidence_id",
            name="uq_shadow_readiness_evidence_runs_id",
        ),
        UniqueConstraint(
            "assessment_db_id",
            "consumer_run_db_id",
            name="uq_shadow_readiness_evidence_runs_assessment_run",
        ),
        Index(
            "ix_shadow_readiness_evidence_runs_assessment",
            "assessment_db_id",
            "completed_at",
        ),
        Index(
            "ix_shadow_readiness_evidence_runs_consumer_run",
            "consumer_run_db_id",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_readiness_assessments.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    consumer_run_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_consumer_runs.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    run_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowAutomationPermit(Base):
    __tablename__ = "canonical_parser_shadow_automation_permits"

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED', 'EXPIRED', 'EXHAUSTED')",
            name="ck_shadow_automation_permits_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_shadow_automation_permits_scope",
        ),
        CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_shadow_automation_permits_channel",
        ),
        CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_AUTOMATION')",
            name="ck_shadow_automation_permits_consumer",
        ),
        CheckConstraint(
            "permit_generation >= 1",
            name="ck_shadow_automation_permits_generation",
        ),
        CheckConstraint(
            "requested_validity_minutes >= 1",
            name="ck_shadow_automation_permits_validity",
        ),
        CheckConstraint(
            "run_budget >= 1 AND event_budget >= 1",
            name="ck_shadow_automation_permits_budget_positive",
        ),
        CheckConstraint(
            "consumed_run_count >= 0 AND consumed_run_count <= run_budget",
            name="ck_shadow_automation_permits_run_consumption",
        ),
        CheckConstraint(
            "consumed_event_count >= 0 AND consumed_event_count <= event_budget",
            name="ck_shadow_automation_permits_event_consumption",
        ),
        CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_shadow_automation_permits_sequence",
        ),
        CheckConstraint(
            "length(permit_key) = 64",
            name="ck_shadow_automation_permits_key_len",
        ),
        CheckConstraint(
            "length(assessment_key) = 64",
            name="ck_shadow_automation_permits_assessment_key_len",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_shadow_automation_permits_parser_hash_len",
        ),
        CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_shadow_automation_permits_release_hash_len",
        ),
        CheckConstraint(
            "length(lease_event_hash) = 64",
            name="ck_shadow_automation_permits_lease_hash_len",
        ),
        CheckConstraint(
            "length(certification_event_hash) = 64",
            name="ck_shadow_automation_permits_cert_hash_len",
        ),
        CheckConstraint(
            "length(readiness_policy_hash) = 64",
            name="ck_shadow_automation_permits_readiness_policy_hash_len",
        ),
        CheckConstraint(
            "length(readiness_evidence_hash) = 64",
            name="ck_shadow_automation_permits_readiness_evidence_hash_len",
        ),
        CheckConstraint(
            "length(permit_policy_hash) = 64",
            name="ck_shadow_automation_permits_policy_hash_len",
        ),
        CheckConstraint(
            "length(latest_event_hash) = 64",
            name="ck_shadow_automation_permits_latest_hash_len",
        ),
        UniqueConstraint(
            "permit_id",
            name="uq_shadow_automation_permits_id",
        ),
        UniqueConstraint(
            "permit_key",
            name="uq_shadow_automation_permits_key",
        ),
        UniqueConstraint(
            "consumer",
            "permit_generation",
            name="uq_shadow_automation_permits_generation",
        ),
        Index(
            "ix_shadow_automation_permits_assessment_status",
            "assessment_db_id",
            "status",
        ),
        Index(
            "ix_shadow_automation_permits_expires",
            "status",
            "expires_at",
        ),
        Index(
            "ix_shadow_automation_permits_parser",
            "parser_name",
            "parser_version",
        ),
        Index(
            "uq_shadow_automation_permits_active_consumer",
            "consumer",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_key: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    assessment_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_readiness_assessments.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    readiness_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    readiness_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    requested_validity_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    run_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    event_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_run_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    consumed_event_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalParserShadowAutomationPermitEvent(Base):
    __tablename__ = "canonical_parser_shadow_automation_permit_events"

    __table_args__ = (
        CheckConstraint(
            "sequence >= 1",
            name="ck_shadow_automation_permit_events_sequence",
        ),
        CheckConstraint(
            "event_type IN ('ISSUED', 'REVOKED', 'EXPIRED', 'EXHAUSTED')",
            name="ck_shadow_automation_permit_events_type",
        ),
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('ACTIVE', 'REVOKED', 'EXPIRED', 'EXHAUSTED')",
            name="ck_shadow_automation_permit_events_previous_status",
        ),
        CheckConstraint(
            "new_status IN ('ACTIVE', 'REVOKED', 'EXPIRED', 'EXHAUSTED')",
            name="ck_shadow_automation_permit_events_new_status",
        ),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_shadow_automation_permit_events_prev_hash_len",
        ),
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_shadow_automation_permit_events_hash_len",
        ),
        UniqueConstraint(
            "event_id",
            name="uq_shadow_automation_permit_events_id",
        ),
        UniqueConstraint(
            "permit_db_id",
            "sequence",
            name="uq_shadow_automation_permit_events_sequence",
        ),
        UniqueConstraint(
            "event_hash",
            name="uq_shadow_automation_permit_events_hash",
        ),
        Index(
            "ix_shadow_automation_permit_events_permit_sequence",
            "permit_db_id",
            "sequence",
        ),
        Index(
            "ix_shadow_automation_permit_events_type_time",
            "event_type",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_automation_permits.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowExecutionTicket(Base):
    __tablename__ = "canonical_parser_shadow_execution_tickets"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RESERVED', 'RELEASED', 'EXPIRED')",
            name="ck_shadow_execution_tickets_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_shadow_execution_tickets_scope",
        ),
        CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_shadow_execution_tickets_channel",
        ),
        CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_AUTOMATION')",
            name="ck_shadow_execution_tickets_consumer",
        ),
        CheckConstraint(
            "executor IN ('CERTIFIED_SHADOW_EXECUTION_TICKET')",
            name="ck_shadow_execution_tickets_executor",
        ),
        CheckConstraint(
            "ticket_generation >= 1",
            name="ck_shadow_execution_tickets_generation",
        ),
        CheckConstraint(
            "requested_validity_seconds >= 1",
            name="ck_shadow_execution_tickets_validity",
        ),
        CheckConstraint(
            "run_reservation = 1",
            name="ck_shadow_execution_tickets_run_reservation",
        ),
        CheckConstraint(
            "event_reservation >= 1",
            name="ck_shadow_execution_tickets_event_reservation",
        ),
        CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_shadow_execution_tickets_sequence",
        ),
        CheckConstraint("length(ticket_key) = 64", name="ck_shadow_execution_tickets_key_len"),
        CheckConstraint("length(permit_key) = 64", name="ck_shadow_execution_tickets_permit_key_len"),
        CheckConstraint("length(parser_implementation_hash) = 64", name="ck_shadow_execution_tickets_parser_hash_len"),
        CheckConstraint("length(release_manifest_hash) = 64", name="ck_shadow_execution_tickets_release_hash_len"),
        CheckConstraint("length(readiness_evidence_hash) = 64", name="ck_shadow_execution_tickets_readiness_hash_len"),
        CheckConstraint("length(permit_policy_hash) = 64", name="ck_shadow_execution_tickets_permit_policy_hash_len"),
        CheckConstraint("length(permit_event_hash) = 64", name="ck_shadow_execution_tickets_permit_event_hash_len"),
        CheckConstraint("length(ticket_policy_hash) = 64", name="ck_shadow_execution_tickets_policy_hash_len"),
        CheckConstraint("length(latest_event_hash) = 64", name="ck_shadow_execution_tickets_latest_hash_len"),
        UniqueConstraint("ticket_id", name="uq_shadow_execution_tickets_id"),
        UniqueConstraint("ticket_key", name="uq_shadow_execution_tickets_key"),
        UniqueConstraint("permit_db_id", "ticket_generation", name="uq_shadow_execution_tickets_generation"),
        Index("ix_shadow_execution_tickets_permit_status", "permit_db_id", "status"),
        Index("ix_shadow_execution_tickets_expires", "status", "expires_at"),
        Index("ix_shadow_execution_tickets_parser", "parser_name", "parser_version"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ticket_key: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    permit_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_automation_permits.id", ondelete="CASCADE"),
        nullable=False,
    )
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_key: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lease_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer: Mapped[str] = mapped_column(String(64), nullable=False)
    executor: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    readiness_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    requested_validity_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    run_reservation: Mapped[int] = mapped_column(Integer, nullable=False)
    event_reservation: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CanonicalParserShadowExecutionTicketEvent(Base):
    __tablename__ = "canonical_parser_shadow_execution_ticket_events"

    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_shadow_execution_ticket_events_sequence"),
        CheckConstraint("event_type IN ('RESERVED', 'RELEASED', 'EXPIRED')", name="ck_shadow_execution_ticket_events_type"),
        CheckConstraint("previous_status IS NULL OR previous_status IN ('RESERVED', 'RELEASED', 'EXPIRED')", name="ck_shadow_execution_ticket_events_previous_status"),
        CheckConstraint("new_status IN ('RESERVED', 'RELEASED', 'EXPIRED')", name="ck_shadow_execution_ticket_events_new_status"),
        CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_shadow_execution_ticket_events_prev_hash_len"),
        CheckConstraint("length(event_hash) = 64", name="ck_shadow_execution_ticket_events_hash_len"),
        UniqueConstraint("event_id", name="uq_shadow_execution_ticket_events_id"),
        UniqueConstraint("ticket_db_id", "sequence", name="uq_shadow_execution_ticket_events_sequence"),
        UniqueConstraint("event_hash", name="uq_shadow_execution_ticket_events_hash"),
        Index("ix_shadow_execution_ticket_events_ticket_sequence", "ticket_db_id", "sequence"),
        Index("ix_shadow_execution_ticket_events_type_time", "event_type", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ticket_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_execution_tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserShadowTicketExecutionRun(Base):
    __tablename__ = "canonical_parser_shadow_ticket_execution_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')",
            name="ck_shadow_ticket_execution_runs_status",
        ),
        CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_shadow_ticket_execution_runs_scope",
        ),
        CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_shadow_ticket_execution_runs_channel",
        ),
        CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_AUTOMATION')",
            name="ck_shadow_ticket_execution_runs_consumer",
        ),
        CheckConstraint(
            "executor IN ('CERTIFIED_SHADOW_TICKET_EXECUTION')",
            name="ck_shadow_ticket_execution_runs_executor",
        ),
        CheckConstraint(
            "requested_limit >= 1 AND reserved_run_count = 1 "
            "AND reserved_event_count >= 1 AND selected_count >= 0 "
            "AND processed_count >= 0 AND passed_count >= 0 "
            "AND failed_count >= 0 AND skipped_count >= 0 "
            "AND artifact_count >= 0 AND consumed_run_count >= 0 "
            "AND consumed_event_count >= 0 AND released_event_count >= 0",
            name="ck_shadow_ticket_execution_runs_counts_nonnegative",
        ),
        CheckConstraint(
            "selected_count >= processed_count",
            name="ck_shadow_ticket_execution_runs_selected_processed",
        ),
        CheckConstraint(
            "processed_count = passed_count + failed_count + skipped_count",
            name="ck_shadow_ticket_execution_runs_processed_breakdown",
        ),
        CheckConstraint(
            "consumed_run_count <= reserved_run_count",
            name="ck_shadow_ticket_execution_runs_run_budget_bound",
        ),
        CheckConstraint(
            "NOT budget_settled OR consumed_event_count + released_event_count = reserved_event_count",
            name="ck_shadow_ticket_execution_runs_event_settlement",
        ),
        CheckConstraint(
            "consumed_event_count = processed_count",
            name="ck_shadow_ticket_execution_runs_consumed_processed",
        ),
        CheckConstraint(
            "length(run_key) = 64",
            name="ck_shadow_ticket_execution_runs_key_len",
        ),
        CheckConstraint(
            "length(ticket_key) = 64",
            name="ck_shadow_ticket_execution_runs_ticket_key_len",
        ),
        CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_shadow_ticket_execution_runs_parser_hash_len",
        ),
        CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_shadow_ticket_execution_runs_release_hash_len",
        ),
        CheckConstraint(
            "length(readiness_evidence_hash) = 64",
            name="ck_shadow_ticket_execution_runs_readiness_hash_len",
        ),
        CheckConstraint(
            "length(permit_policy_hash) = 64",
            name="ck_shadow_ticket_execution_runs_permit_policy_hash_len",
        ),
        CheckConstraint(
            "length(permit_event_hash) = 64",
            name="ck_shadow_ticket_execution_runs_permit_event_hash_len",
        ),
        CheckConstraint(
            "length(ticket_policy_hash) = 64",
            name="ck_shadow_ticket_execution_runs_ticket_policy_hash_len",
        ),
        CheckConstraint(
            "length(ticket_event_hash) = 64",
            name="ck_shadow_ticket_execution_runs_ticket_event_hash_len",
        ),
        CheckConstraint(
            "length(execution_policy_hash) = 64",
            name="ck_shadow_ticket_execution_runs_policy_hash_len",
        ),
        CheckConstraint(
            "settlement_hash IS NULL OR length(settlement_hash) = 64",
            name="ck_shadow_ticket_execution_runs_settlement_hash_len",
        ),
        UniqueConstraint(
            "run_id",
            name="uq_shadow_ticket_execution_runs_id",
        ),
        UniqueConstraint(
            "run_key",
            name="uq_shadow_ticket_execution_runs_key",
        ),
        UniqueConstraint(
            "ticket_db_id",
            name="uq_shadow_ticket_execution_runs_ticket",
        ),
        Index(
            "ix_shadow_ticket_execution_runs_permit_started",
            "permit_db_id",
            "started_at",
        ),
        Index(
            "ix_shadow_ticket_execution_runs_status_completed",
            "status",
            "completed_at",
        ),
        Index(
            "ix_shadow_ticket_execution_runs_parser",
            "parser_name",
            "parser_version",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_execution_tickets.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    ticket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ticket_key: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_automation_permits.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lease_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    promotion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer: Mapped[str] = mapped_column(String(64), nullable=False)
    executor: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_implementation_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    release_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    readiness_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    released_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_settled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    settlement_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    selection_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalParserShadowTicketExecutionResult(Base):
    __tablename__ = "canonical_parser_shadow_ticket_execution_results"

    __table_args__ = (
        CheckConstraint(
            "status IN ('PASS', 'FAIL', 'SKIPPED')",
            name="ck_shadow_ticket_execution_results_status",
        ),
        CheckConstraint(
            "artifact_count >= 0",
            name="ck_shadow_ticket_execution_results_artifact_count",
        ),
        CheckConstraint(
            "length(raw_payload_hash) = 64",
            name="ck_shadow_ticket_execution_results_raw_hash_len",
        ),
        CheckConstraint(
            "output_hash IS NULL OR length(output_hash) = 64",
            name="ck_shadow_ticket_execution_results_output_hash_len",
        ),
        CheckConstraint(
            "verification_output_hash IS NULL OR length(verification_output_hash) = 64",
            name="ck_shadow_ticket_execution_results_verify_hash_len",
        ),
        UniqueConstraint(
            "result_id",
            name="uq_shadow_ticket_execution_results_id",
        ),
        UniqueConstraint(
            "execution_run_db_id",
            "raw_event_id",
            name="uq_shadow_ticket_execution_results_run_event",
        ),
        Index(
            "ix_shadow_ticket_execution_results_run_status",
            "execution_run_db_id",
            "status",
        ),
        Index(
            "ix_shadow_ticket_execution_results_raw_event",
            "raw_event_id",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    execution_run_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_ticket_execution_runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    raw_event_id: Mapped[int] = mapped_column(
        ForeignKey("raw_blockchain_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    deterministic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_output_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    shadow_artifacts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowAutomationCycle(Base):
    __tablename__ = "canonical_parser_shadow_automation_cycles"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')",
            name="ck_shadow_automation_cycles_status",
        ),
        CheckConstraint(
            "requested_event_reservation >= 1 AND requested_limit >= 1",
            name="ck_shadow_automation_cycles_requests_positive",
        ),
        CheckConstraint(
            "processed_count >= 0 AND passed_count >= 0 AND failed_count >= 0 "
            "AND skipped_count >= 0 AND artifact_count >= 0",
            name="ck_shadow_automation_cycles_counts_nonnegative",
        ),
        CheckConstraint(
            "processed_count = passed_count + failed_count + skipped_count",
            name="ck_shadow_automation_cycles_processed_breakdown",
        ),
        CheckConstraint(
            "length(cycle_key) = 64",
            name="ck_shadow_automation_cycles_key_len",
        ),
        CheckConstraint(
            "length(cycle_policy_hash) = 64",
            name="ck_shadow_automation_cycles_policy_hash_len",
        ),
        CheckConstraint(
            "latest_event_hash IS NULL OR length(latest_event_hash) = 64",
            name="ck_shadow_automation_cycles_event_hash_len",
        ),
        UniqueConstraint("cycle_id", name="uq_shadow_automation_cycles_id"),
        UniqueConstraint("cycle_key", name="uq_shadow_automation_cycles_key"),
        Index(
            "ix_shadow_automation_cycles_permit_started",
            "permit_db_id",
            "started_at",
        ),
        Index(
            "ix_shadow_automation_cycles_status_completed",
            "status",
            "completed_at",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cycle_key: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_automation_permits.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ticket_db_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_execution_tickets.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    ticket_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_run_db_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_ticket_execution_runs.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    execution_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    cycle_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    cycle_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cycle_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    requested_event_reservation: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_event_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_settled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    preview_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    execution_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalParserShadowAutomationCycleEvent(Base):
    __tablename__ = "canonical_parser_shadow_automation_cycle_events"

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('STARTED', 'COMPLETED', 'FAILED')",
            name="ck_shadow_automation_cycle_events_type",
        ),
        CheckConstraint(
            "sequence >= 1",
            name="ck_shadow_automation_cycle_events_sequence_positive",
        ),
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_shadow_automation_cycle_events_hash_len",
        ),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_shadow_automation_cycle_events_previous_hash_len",
        ),
        UniqueConstraint("event_id", name="uq_shadow_automation_cycle_events_id"),
        UniqueConstraint(
            "cycle_db_id",
            "sequence",
            name="uq_shadow_automation_cycle_events_sequence",
        ),
        Index(
            "ix_shadow_automation_cycle_events_cycle_occurred",
            "cycle_db_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cycle_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_shadow_automation_cycles.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowSchedulerState(Base):
    __tablename__ = "canonical_parser_shadow_scheduler_states"

    __table_args__ = (
        CheckConstraint(
            "status IN ('STOPPED', 'RUNNING', 'KILLED')",
            name="ck_shadow_scheduler_states_status",
        ),
        CheckConstraint(
            "generation >= 0 AND interval_seconds >= 1 "
            "AND event_reservation >= 1 AND execution_limit >= 1",
            name="ck_shadow_scheduler_states_values_positive",
        ),
        CheckConstraint(
            "lock_token_hash IS NULL OR length(lock_token_hash) = 64",
            name="ck_shadow_scheduler_states_lock_hash_len",
        ),
        CheckConstraint(
            "length(scheduler_policy_hash) = 64",
            name="ck_shadow_scheduler_states_policy_hash_len",
        ),
        CheckConstraint(
            "latest_event_hash IS NULL OR length(latest_event_hash) = 64",
            name="ck_shadow_scheduler_states_event_hash_len",
        ),
        UniqueConstraint("scheduler_name", name="uq_shadow_scheduler_states_name"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    scheduler_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    kill_switch_engaged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    kill_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    event_reservation: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    permit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scheduler_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduler_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduler_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    lock_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lock_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lock_acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_tick_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    latest_cycle_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalParserShadowSchedulerEvent(Base):
    __tablename__ = "canonical_parser_shadow_scheduler_events"

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('STARTED', 'STOPPED', 'KILLED', 'RESET', 'HEARTBEAT', "
            "'TICK_ACQUIRED', 'TICK_COMPLETED', 'TICK_FAILED', 'TICK_SKIPPED')",
            name="ck_shadow_scheduler_events_type",
        ),
        CheckConstraint("sequence >= 1", name="ck_shadow_scheduler_events_sequence_positive"),
        CheckConstraint("length(event_hash) = 64", name="ck_shadow_scheduler_events_hash_len"),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_shadow_scheduler_events_previous_hash_len",
        ),
        UniqueConstraint("event_id", name="uq_shadow_scheduler_events_id"),
        UniqueConstraint(
            "scheduler_state_db_id",
            "sequence",
            name="uq_shadow_scheduler_events_sequence",
        ),
        Index(
            "ix_shadow_scheduler_events_state_occurred",
            "scheduler_state_db_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scheduler_state_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_scheduler_states.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowSchedulerTick(Base):
    __tablename__ = "canonical_parser_shadow_scheduler_ticks"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED', 'SKIPPED', 'KILLED')",
            name="ck_shadow_scheduler_ticks_status",
        ),
        CheckConstraint(
            "requested_event_reservation >= 1 AND requested_limit >= 1",
            name="ck_shadow_scheduler_ticks_requests_positive",
        ),
        CheckConstraint("length(tick_key) = 64", name="ck_shadow_scheduler_ticks_key_len"),
        CheckConstraint(
            "length(lock_token_hash) = 64",
            name="ck_shadow_scheduler_ticks_lock_hash_len",
        ),
        UniqueConstraint("tick_id", name="uq_shadow_scheduler_ticks_id"),
        UniqueConstraint("tick_key", name="uq_shadow_scheduler_ticks_key"),
        Index(
            "ix_shadow_scheduler_ticks_state_started",
            "scheduler_state_db_id",
            "started_at",
        ),
        Index(
            "ix_shadow_scheduler_ticks_status_completed",
            "status",
            "completed_at",
        ),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    tick_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tick_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduler_state_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_scheduler_states.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scheduler_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    cycle_db_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_parser_shadow_automation_cycles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    cycle_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    permit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    lock_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_event_reservation: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_event_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    cycle_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CanonicalParserShadowSchedulerWorkerState(Base):
    __tablename__ = "canonical_parser_shadow_scheduler_worker_states"

    __table_args__ = (
        CheckConstraint(
            "status IN ('STOPPED', 'ACTIVE', 'KILLED')",
            name="ck_shadow_scheduler_worker_states_status",
        ),
        CheckConstraint(
            "generation >= 0 AND lease_epoch >= 0 AND consecutive_failures >= 0",
            name="ck_shadow_scheduler_worker_states_counters",
        ),
        CheckConstraint(
            "lease_token_hash IS NULL OR length(lease_token_hash) = 64",
            name="ck_shadow_scheduler_worker_states_lease_hash",
        ),
        CheckConstraint(
            "length(worker_policy_hash) = 64",
            name="ck_shadow_scheduler_worker_states_policy_hash",
        ),
        CheckConstraint(
            "latest_event_hash IS NULL OR length(latest_event_hash) = 64",
            name="ck_shadow_scheduler_worker_states_event_hash",
        ),
        UniqueConstraint("worker_name", name="uq_shadow_scheduler_worker_states_name"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    worker_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_iteration_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    latest_tick_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    worker_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    kill_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CanonicalParserShadowSchedulerWorkerEvent(Base):
    __tablename__ = "canonical_parser_shadow_scheduler_worker_events"

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('STARTED', 'STOPPED', 'KILLED', 'RESET', 'HEARTBEAT', "
            "'ITERATION_STARTED', 'ITERATION_COMPLETED', 'ITERATION_FAILED', 'ITERATION_IDLE')",
            name="ck_shadow_scheduler_worker_events_type",
        ),
        CheckConstraint("sequence >= 1", name="ck_shadow_scheduler_worker_events_sequence"),
        CheckConstraint("length(event_hash) = 64", name="ck_shadow_scheduler_worker_events_hash"),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_shadow_scheduler_worker_events_previous_hash",
        ),
        UniqueConstraint("event_id", name="uq_shadow_scheduler_worker_events_id"),
        UniqueConstraint("worker_state_db_id", "sequence", name="uq_shadow_scheduler_worker_events_sequence"),
        Index("ix_shadow_scheduler_worker_events_state_time", "worker_state_db_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    worker_state_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_scheduler_worker_states.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserShadowSchedulerWorkerIteration(Base):
    __tablename__ = "canonical_parser_shadow_scheduler_worker_iterations"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'IDLE', 'PASSED', 'PARTIAL', 'FAILED', 'SKIPPED', 'KILLED')",
            name="ck_shadow_scheduler_worker_iterations_status",
        ),
        CheckConstraint(
            "worker_generation >= 1 AND lease_epoch >= 1",
            name="ck_shadow_scheduler_worker_iterations_fencing",
        ),
        CheckConstraint("length(iteration_key) = 64", name="ck_shadow_scheduler_worker_iterations_key"),
        UniqueConstraint("iteration_id", name="uq_shadow_scheduler_worker_iterations_id"),
        UniqueConstraint("iteration_key", name="uq_shadow_scheduler_worker_iterations_key"),
        Index("ix_shadow_scheduler_worker_iterations_state_started", "worker_state_db_id", "started_at"),
        Index("ix_shadow_scheduler_worker_iterations_status_completed", "status", "completed_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    iteration_id: Mapped[str] = mapped_column(String(36), nullable=False)
    iteration_key: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_state_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_scheduler_worker_states.id", ondelete="RESTRICT"), nullable=False
    )
    worker_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), nullable=False)
    scheduler_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    tick_db_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_parser_shadow_scheduler_ticks.id", ondelete="RESTRICT"), nullable=True
    )
    tick_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cycle_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_event_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    scheduler_preview: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tick_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CanonicalParserShadowWorkerLoopRun(Base):
    __tablename__ = "canonical_parser_shadow_worker_loop_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'STOPPED', 'CIRCUIT_OPEN', 'FAILED', 'KILLED')",
            name="ck_shadow_worker_loop_runs_status",
        ),
        CheckConstraint(
            "requested_iterations >= 1 AND completed_iterations >= 0 AND "
            "passed_iterations >= 0 AND partial_iterations >= 0 AND idle_iterations >= 0 AND "
            "failed_iterations >= 0 AND skipped_iterations >= 0 AND max_consecutive_failures >= 1",
            name="ck_shadow_worker_loop_runs_counts",
        ),
        CheckConstraint("length(loop_key) = 64", name="ck_shadow_worker_loop_runs_key"),
        UniqueConstraint("loop_id", name="uq_shadow_worker_loop_runs_id"),
        UniqueConstraint("loop_key", name="uq_shadow_worker_loop_runs_key"),
        Index("ix_shadow_worker_loop_runs_state_started", "worker_state_db_id", "started_at"),
        Index("ix_shadow_worker_loop_runs_status_completed", "status", "completed_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    loop_id: Mapped[str] = mapped_column(String(36), nullable=False)
    loop_key: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_state_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_scheduler_worker_states.id", ondelete="RESTRICT"), nullable=False
    )
    worker_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    partial_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    idle_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    max_consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    circuit_breaker_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    kill_switch_enforced: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CanonicalParserShadowWorkerLoopIteration(Base):
    __tablename__ = "canonical_parser_shadow_worker_loop_iterations"

    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_shadow_worker_loop_iterations_sequence"),
        UniqueConstraint("loop_run_db_id", "sequence", name="uq_shadow_worker_loop_iterations_sequence"),
        UniqueConstraint("worker_iteration_db_id", name="uq_shadow_worker_loop_iterations_worker_iteration"),
        Index("ix_shadow_worker_loop_iterations_loop_sequence", "loop_run_db_id", "sequence"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    loop_run_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_worker_loop_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_iteration_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_scheduler_worker_iterations.id", ondelete="RESTRICT"), nullable=False
    )
    iteration_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
