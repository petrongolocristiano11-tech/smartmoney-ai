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
