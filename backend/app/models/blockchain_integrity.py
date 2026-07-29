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


class CanonicalParserShadowWorkerRecoveryRun(Base):
    __tablename__ = "canonical_parser_shadow_worker_recovery_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'NOOP')",
            name="ck_shadow_worker_recovery_runs_status",
        ),
        CheckConstraint(
            "detected_worker_count >= 0 AND detected_iteration_count >= 0 "
            "AND detected_loop_count >= 0 AND recovered_worker_count >= 0 "
            "AND recovered_iteration_count >= 0 AND recovered_loop_count >= 0",
            name="ck_shadow_worker_recovery_runs_counts",
        ),
        CheckConstraint(
            "length(recovery_key) = 64",
            name="ck_shadow_worker_recovery_runs_key",
        ),
        CheckConstraint(
            "length(policy_hash) = 64",
            name="ck_shadow_worker_recovery_runs_policy_hash",
        ),
        UniqueConstraint("recovery_id", name="uq_shadow_worker_recovery_runs_id"),
        UniqueConstraint("recovery_key", name="uq_shadow_worker_recovery_runs_key"),
        Index("ix_shadow_worker_recovery_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    recovery_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recovery_key: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_state_db_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_parser_shadow_scheduler_worker_states.id", ondelete="RESTRICT"),
        nullable=True,
    )
    worker_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detected_worker_count: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_iteration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_loop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recovered_worker_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recovered_iteration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recovered_loop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    target_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowWorkerRecoveryAction(Base):
    __tablename__ = "canonical_parser_shadow_worker_recovery_actions"

    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_shadow_worker_recovery_actions_sequence"),
        CheckConstraint(
            "target_type IN ('WORKER_STATE', 'WORKER_ITERATION', 'WORKER_LOOP')",
            name="ck_shadow_worker_recovery_actions_target_type",
        ),
        CheckConstraint(
            "action_type IN ('STOP_STALE_WORKER', 'FAIL_STALE_ITERATION', 'STOP_STALE_LOOP')",
            name="ck_shadow_worker_recovery_actions_type",
        ),
        UniqueConstraint(
            "recovery_run_db_id", "sequence", name="uq_shadow_worker_recovery_actions_sequence"
        ),
        UniqueConstraint(
            "recovery_run_db_id", "target_type", "target_id",
            name="uq_shadow_worker_recovery_actions_target",
        ),
        Index("ix_shadow_worker_recovery_actions_run_sequence", "recovery_run_db_id", "sequence"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    recovery_run_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_worker_recovery_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    snapshot_before: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    snapshot_after: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowReliabilityAssessment(Base):
    __tablename__ = "canonical_parser_shadow_reliability_assessments"

    __table_args__ = (
        CheckConstraint(
            "status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_shadow_reliability_assessments_status",
        ),
        CheckConstraint(
            "loop_count >= 0 AND completed_iteration_count >= 0 "
            "AND passed_iteration_count >= 0 AND partial_iteration_count >= 0 "
            "AND idle_iteration_count >= 0 AND failed_iteration_count >= 0 "
            "AND skipped_iteration_count >= 0 AND circuit_open_count >= 0 "
            "AND recovery_run_count >= 0 AND recovery_action_count >= 0",
            name="ck_shadow_reliability_assessments_counts",
        ),
        CheckConstraint(
            "pass_rate >= 0 AND pass_rate <= 100",
            name="ck_shadow_reliability_assessments_pass_rate",
        ),
        CheckConstraint("length(assessment_key) = 64", name="ck_shadow_reliability_assessments_key"),
        CheckConstraint("length(policy_hash) = 64", name="ck_shadow_reliability_assessments_policy_hash"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_shadow_reliability_assessments_evidence_hash"),
        UniqueConstraint("assessment_id", name="uq_shadow_reliability_assessments_id"),
        UniqueConstraint("assessment_key", name="uq_shadow_reliability_assessments_key"),
        Index("ix_shadow_reliability_assessments_status_valid", "status", "valid_until"),
        Index("ix_shadow_reliability_assessments_worker_time", "worker_state_db_id", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_state_db_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_parser_shadow_scheduler_worker_states.id", ondelete="RESTRICT"),
        nullable=True,
    )
    worker_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    loop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_iteration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_iteration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    partial_iteration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    idle_iteration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_iteration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_iteration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    circuit_open_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recovery_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recovery_action_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    observation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observation_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowReliabilityEvidenceLoop(Base):
    __tablename__ = "canonical_parser_shadow_reliability_evidence_loops"

    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_shadow_reliability_evidence_loops_sequence"),
        CheckConstraint("length(loop_evidence_hash) = 64", name="ck_shadow_reliability_evidence_loops_hash"),
        UniqueConstraint(
            "assessment_db_id", "sequence", name="uq_shadow_reliability_evidence_loops_sequence"
        ),
        UniqueConstraint(
            "assessment_db_id", "loop_run_db_id", name="uq_shadow_reliability_evidence_loops_run"
        ),
        Index("ix_shadow_reliability_evidence_loops_assessment", "assessment_db_id", "sequence"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_reliability_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    loop_run_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_shadow_worker_loop_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    loop_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    completed_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    partial_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    idle_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    circuit_breaker_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    loop_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserShadowReliabilityCertification(Base):
    __tablename__ = "canonical_parser_shadow_reliability_certifications"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_shadow_reliability_certifications_status"),
        CheckConstraint("length(certification_key) = 64", name="ck_shadow_reliability_certifications_key"),
        CheckConstraint("length(policy_hash) = 64", name="ck_shadow_reliability_certifications_policy_hash"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_shadow_reliability_certifications_evidence_hash"),
        CheckConstraint("latest_event_sequence >= 1", name="ck_shadow_reliability_certifications_event_sequence"),
        CheckConstraint("length(latest_event_hash) = 64", name="ck_shadow_reliability_certifications_event_hash"),
        UniqueConstraint("certification_id", name="uq_shadow_reliability_certifications_id"),
        UniqueConstraint("certification_key", name="uq_shadow_reliability_certifications_key"),
        Index("ix_shadow_reliability_certifications_status_expiry", "status", "expires_at"),
        Index("ix_shadow_reliability_certifications_assessment", "assessment_db_id", "certified_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_key: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_shadow_reliability_assessments.id", ondelete="RESTRICT"), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    certified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CanonicalParserShadowReliabilityCertificationEvent(Base):
    __tablename__ = "canonical_parser_shadow_reliability_certification_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_shadow_reliability_certification_events_sequence"),
        CheckConstraint("event_type IN ('CERTIFIED', 'REVOKED')", name="ck_shadow_reliability_certification_events_type"),
        CheckConstraint("new_status IN ('ACTIVE', 'REVOKED')", name="ck_shadow_reliability_certification_events_status"),
        CheckConstraint("length(event_hash) = 64", name="ck_shadow_reliability_certification_events_hash"),
        UniqueConstraint("event_id", name="uq_shadow_reliability_certification_events_id"),
        UniqueConstraint("certification_db_id", "sequence", name="uq_shadow_reliability_certification_events_sequence"),
        Index("ix_shadow_reliability_certification_events_cert_sequence", "certification_db_id", "sequence"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_shadow_reliability_certifications.id", ondelete="CASCADE"), nullable=False)
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


class CanonicalParserPaperProjectionRun(Base):
    __tablename__ = "canonical_parser_paper_projection_runs"
    __table_args__ = (
        CheckConstraint("status IN ('PASSED', 'PARTIAL', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_parser_paper_projection_runs_status"),
        CheckConstraint("source_run_count >= 0 AND source_result_count >= 0 AND projectable_count >= 0 AND review_count >= 0 AND rejected_count >= 0", name="ck_parser_paper_projection_runs_counts"),
        CheckConstraint("source_result_count = projectable_count + review_count + rejected_count", name="ck_parser_paper_projection_runs_breakdown"),
        CheckConstraint("length(projection_key) = 64", name="ck_parser_paper_projection_runs_key"),
        CheckConstraint("length(certification_event_hash) = 64", name="ck_parser_paper_projection_runs_cert_event_hash"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_projection_runs_policy_hash"),
        CheckConstraint("length(source_evidence_hash) = 64", name="ck_parser_paper_projection_runs_evidence_hash"),
        UniqueConstraint("projection_id", name="uq_parser_paper_projection_runs_id"),
        UniqueConstraint("projection_key", name="uq_parser_paper_projection_runs_key"),
        Index("ix_parser_paper_projection_runs_status_completed", "status", "completed_at"),
        Index("ix_parser_paper_projection_runs_certification", "certification_db_id", "started_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    projection_id: Mapped[str] = mapped_column(String(36), nullable=False)
    projection_key: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_shadow_reliability_certifications.id", ondelete="RESTRICT"), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projectable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperProjectionResult(Base):
    __tablename__ = "canonical_parser_paper_projection_results"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_paper_projection_results_sequence"),
        CheckConstraint("status IN ('PROJECTABLE', 'REVIEW', 'REJECTED')", name="ck_parser_paper_projection_results_status"),
        CheckConstraint("action IN ('BUY', 'SELL', 'UNKNOWN')", name="ck_parser_paper_projection_results_action"),
        CheckConstraint("artifact_index >= 0", name="ck_parser_paper_projection_results_artifact_index"),
        CheckConstraint("length(artifact_hash) = 64", name="ck_parser_paper_projection_results_artifact_hash"),
        CheckConstraint("length(projection_hash) = 64", name="ck_parser_paper_projection_results_projection_hash"),
        UniqueConstraint("result_id", name="uq_parser_paper_projection_results_id"),
        UniqueConstraint("projection_run_db_id", "sequence", name="uq_parser_paper_projection_results_sequence"),
        UniqueConstraint("projection_run_db_id", "source_result_db_id", "artifact_index", name="uq_parser_paper_projection_results_source_artifact"),
        Index("ix_parser_paper_projection_results_run_status", "projection_run_db_id", "status"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    projection_run_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_projection_runs.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_execution_run_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_shadow_ticket_execution_runs.id", ondelete="RESTRICT"), nullable=False)
    source_execution_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_result_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_shadow_ticket_execution_results.id", ondelete="RESTRICT"), nullable=False)
    source_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    raw_event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    wallet_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_mint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_amount: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sol_amount: Mapped[str | None] = mapped_column(String(120), nullable=True)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperProjectionReadinessAssessment(Base):
    __tablename__ = "canonical_parser_paper_projection_readiness_assessments"
    __table_args__ = (
        CheckConstraint("status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_parser_paper_projection_readiness_status"),
        CheckConstraint("run_count >= 0 AND result_count >= 0 AND projectable_count >= 0 AND review_count >= 0 AND rejected_count >= 0", name="ck_parser_paper_projection_readiness_counts"),
        CheckConstraint("result_count = projectable_count + review_count + rejected_count", name="ck_parser_paper_projection_readiness_breakdown"),
        CheckConstraint("projectable_rate >= 0 AND projectable_rate <= 100", name="ck_parser_paper_projection_readiness_rate"),
        CheckConstraint("length(assessment_key) = 64", name="ck_parser_paper_projection_readiness_key"),
        CheckConstraint("length(certification_event_hash) = 64", name="ck_parser_paper_projection_readiness_cert_hash"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_projection_readiness_policy_hash"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_projection_readiness_evidence_hash"),
        UniqueConstraint("assessment_id", name="uq_parser_paper_projection_readiness_id"),
        UniqueConstraint("assessment_key", name="uq_parser_paper_projection_readiness_key"),
        Index("ix_parser_paper_projection_readiness_status_valid", "status", "valid_until"),
        Index("ix_parser_paper_projection_readiness_cert", "certification_db_id", "evaluated_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_shadow_reliability_certifications.id", ondelete="RESTRICT"), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projectable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projectable_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    observation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observation_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperProjectionReadinessEvidenceRun(Base):
    __tablename__ = "canonical_parser_paper_projection_readiness_evidence_runs"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_paper_projection_readiness_evidence_sequence"),
        CheckConstraint("status IN ('PASSED', 'PARTIAL', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_parser_paper_projection_readiness_evidence_status"),
        CheckConstraint("source_result_count >= 0 AND projectable_count >= 0 AND review_count >= 0 AND rejected_count >= 0", name="ck_parser_paper_projection_readiness_evidence_counts"),
        CheckConstraint("source_result_count = projectable_count + review_count + rejected_count", name="ck_parser_paper_projection_readiness_evidence_breakdown"),
        CheckConstraint("length(projection_key) = 64", name="ck_parser_paper_projection_readiness_evidence_projection_key"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_projection_readiness_evidence_policy_hash"),
        CheckConstraint("length(source_evidence_hash) = 64", name="ck_parser_paper_projection_readiness_evidence_source_hash"),
        CheckConstraint("length(run_evidence_hash) = 64", name="ck_parser_paper_projection_readiness_evidence_run_hash"),
        UniqueConstraint("assessment_db_id", "sequence", name="uq_parser_paper_projection_readiness_evidence_sequence"),
        UniqueConstraint("assessment_db_id", "projection_run_db_id", name="uq_parser_paper_projection_readiness_evidence_run"),
        Index("ix_parser_paper_projection_readiness_evidence_assessment", "assessment_db_id", "sequence"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_projection_readiness_assessments.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    projection_run_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_projection_runs.id", ondelete="RESTRICT"), nullable=False)
    projection_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projectable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    projection_key: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperAdmissionCertification(Base):
    __tablename__ = "canonical_parser_paper_admission_certifications"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_parser_paper_admission_certifications_status"),
        CheckConstraint("length(certification_key) = 64", name="ck_parser_paper_admission_certifications_key"),
        CheckConstraint("length(reliability_certification_event_hash) = 64", name="ck_parser_paper_admission_certifications_reliability_hash"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_admission_certifications_evidence_hash"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_admission_certifications_policy_hash"),
        CheckConstraint("latest_event_sequence >= 1", name="ck_parser_paper_admission_certifications_event_sequence"),
        CheckConstraint("length(latest_event_hash) = 64", name="ck_parser_paper_admission_certifications_event_hash"),
        UniqueConstraint("certification_id", name="uq_parser_paper_admission_certifications_id"),
        UniqueConstraint("certification_key", name="uq_parser_paper_admission_certifications_key"),
        Index("ix_parser_paper_admission_certifications_status_expiry", "status", "expires_at"),
        Index("ix_parser_paper_admission_certifications_assessment", "assessment_db_id", "certified_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_key: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_projection_readiness_assessments.id", ondelete="RESTRICT"), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    reliability_certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reliability_certification_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    certified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CanonicalParserPaperAdmissionCertificationEvent(Base):
    __tablename__ = "canonical_parser_paper_admission_certification_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_paper_admission_certification_events_sequence"),
        CheckConstraint("event_type IN ('CERTIFIED', 'REVOKED')", name="ck_parser_paper_admission_certification_events_type"),
        CheckConstraint("new_status IN ('ACTIVE', 'REVOKED')", name="ck_parser_paper_admission_certification_events_status"),
        CheckConstraint("length(event_hash) = 64", name="ck_parser_paper_admission_certification_events_hash"),
        UniqueConstraint("event_id", name="uq_parser_paper_admission_certification_events_id"),
        UniqueConstraint("certification_db_id", "sequence", name="uq_parser_paper_admission_certification_events_sequence"),
        Index("ix_parser_paper_admission_certification_events_cert_sequence", "certification_db_id", "sequence"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_admission_certifications.id", ondelete="CASCADE"), nullable=False)
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


class CanonicalParserPaperRuntimeBinding(Base):
    __tablename__ = "canonical_parser_paper_runtime_bindings"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'UNBOUND')", name="ck_parser_paper_runtime_bindings_status"),
        CheckConstraint("mode = 'READ_ONLY_CANARY'", name="ck_parser_paper_runtime_bindings_mode"),
        CheckConstraint("length(binding_key) = 64", name="ck_parser_paper_runtime_bindings_key"),
        CheckConstraint("length(certification_event_hash) = 64", name="ck_parser_paper_runtime_bindings_cert_hash"),
        CheckConstraint("length(account_snapshot_hash) = 64", name="ck_parser_paper_runtime_bindings_account_hash"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_runtime_bindings_policy_hash"),
        CheckConstraint("latest_event_sequence >= 1", name="ck_parser_paper_runtime_bindings_event_sequence"),
        CheckConstraint("length(latest_event_hash) = 64", name="ck_parser_paper_runtime_bindings_event_hash"),
        UniqueConstraint("binding_id", name="uq_parser_paper_runtime_bindings_id"),
        UniqueConstraint("binding_key", name="uq_parser_paper_runtime_bindings_key"),
        Index("ix_parser_paper_runtime_bindings_status_expiry", "status", "expires_at"),
        Index("ix_parser_paper_runtime_bindings_account", "paper_account_id", "bound_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_key: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_admission_certifications.id", ondelete="RESTRICT"), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    paper_account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False)
    paper_account_name: Mapped[str] = mapped_column(String(80), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    account_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    account_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unbind_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CanonicalParserPaperRuntimeBindingEvent(Base):
    __tablename__ = "canonical_parser_paper_runtime_binding_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_paper_runtime_binding_events_sequence"),
        CheckConstraint("event_type IN ('BOUND', 'UNBOUND')", name="ck_parser_paper_runtime_binding_events_type"),
        CheckConstraint("new_status IN ('ACTIVE', 'UNBOUND')", name="ck_parser_paper_runtime_binding_events_status"),
        CheckConstraint("length(event_hash) = 64", name="ck_parser_paper_runtime_binding_events_hash"),
        UniqueConstraint("event_id", name="uq_parser_paper_runtime_binding_events_id"),
        UniqueConstraint("binding_db_id", "sequence", name="uq_parser_paper_runtime_binding_events_sequence"),
        Index("ix_parser_paper_runtime_binding_events_binding_sequence", "binding_db_id", "sequence"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_runtime_bindings.id", ondelete="CASCADE"), nullable=False)
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


class CanonicalParserPaperAdmissionCanaryRun(Base):
    __tablename__ = "canonical_parser_paper_admission_canary_runs"
    __table_args__ = (
        CheckConstraint("status IN ('PASSED', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_parser_paper_admission_canary_runs_status"),
        CheckConstraint("source_result_count >= 0 AND admissible_count >= 0 AND review_count >= 0 AND blocked_count >= 0", name="ck_parser_paper_admission_canary_runs_counts"),
        CheckConstraint("source_result_count = admissible_count + review_count + blocked_count", name="ck_parser_paper_admission_canary_runs_breakdown"),
        CheckConstraint("length(canary_key) = 64", name="ck_parser_paper_admission_canary_runs_key"),
        CheckConstraint("length(binding_event_hash) = 64", name="ck_parser_paper_admission_canary_runs_binding_hash"),
        CheckConstraint("length(source_evidence_hash) = 64", name="ck_parser_paper_admission_canary_runs_source_hash"),
        CheckConstraint("length(account_state_hash) = 64", name="ck_parser_paper_admission_canary_runs_account_hash"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_admission_canary_runs_policy_hash"),
        UniqueConstraint("canary_id", name="uq_parser_paper_admission_canary_runs_id"),
        UniqueConstraint("canary_key", name="uq_parser_paper_admission_canary_runs_key"),
        Index("ix_parser_paper_admission_canary_runs_status_completed", "status", "completed_at"),
        Index("ix_parser_paper_admission_canary_runs_binding", "binding_db_id", "started_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    canary_id: Mapped[str] = mapped_column(String(36), nullable=False)
    canary_key: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_runtime_bindings.id", ondelete="RESTRICT"), nullable=False)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    paper_account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False)
    source_result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    admissible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    account_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    account_state_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperAdmissionCanaryResult(Base):
    __tablename__ = "canonical_parser_paper_admission_canary_results"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_paper_admission_canary_results_sequence"),
        CheckConstraint("status IN ('ADMISSIBLE', 'REVIEW', 'BLOCKED')", name="ck_parser_paper_admission_canary_results_status"),
        CheckConstraint("action IN ('BUY', 'SELL', 'UNKNOWN')", name="ck_parser_paper_admission_canary_results_action"),
        CheckConstraint("length(source_projection_hash) = 64", name="ck_parser_paper_admission_canary_results_projection_hash"),
        CheckConstraint("length(canary_hash) = 64", name="ck_parser_paper_admission_canary_results_hash"),
        UniqueConstraint("result_id", name="uq_parser_paper_admission_canary_results_id"),
        UniqueConstraint("canary_run_db_id", "sequence", name="uq_parser_paper_admission_canary_results_sequence"),
        UniqueConstraint("canary_run_db_id", "source_projection_result_db_id", name="uq_parser_paper_admission_canary_results_source"),
        Index("ix_parser_paper_admission_canary_results_run_status", "canary_run_db_id", "status"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    canary_run_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_admission_canary_runs.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_projection_result_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_projection_results.id", ondelete="RESTRICT"), nullable=False)
    source_projection_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    token_mint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_amount: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sol_amount: Mapped[str | None] = mapped_column(String(120), nullable=True)
    projected_cash_after_sol: Mapped[str | None] = mapped_column(String(120), nullable=True)
    projected_open_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    canary_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    canary_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperCanaryReadinessAssessment(Base):
    __tablename__ = "canonical_parser_paper_canary_readiness_assessments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_parser_paper_canary_readiness_status",
        ),
        CheckConstraint(
            "run_count >= 0 AND passed_run_count >= 0 AND review_run_count >= 0 "
            "AND blocked_run_count >= 0 AND insufficient_run_count >= 0",
            name="ck_parser_paper_canary_readiness_run_counts",
        ),
        CheckConstraint(
            "run_count = passed_run_count + review_run_count + blocked_run_count + insufficient_run_count",
            name="ck_parser_paper_canary_readiness_run_breakdown",
        ),
        CheckConstraint(
            "result_count >= 0 AND admissible_count >= 0 AND review_result_count >= 0 AND blocked_result_count >= 0",
            name="ck_parser_paper_canary_readiness_result_counts",
        ),
        CheckConstraint(
            "result_count = admissible_count + review_result_count + blocked_result_count",
            name="ck_parser_paper_canary_readiness_result_breakdown",
        ),
        CheckConstraint("length(assessment_key) = 64", name="ck_parser_paper_canary_readiness_key"),
        CheckConstraint("length(binding_event_hash) = 64", name="ck_parser_paper_canary_readiness_binding_hash"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_canary_readiness_policy_hash"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_hash"),
        UniqueConstraint("assessment_id", name="uq_parser_paper_canary_readiness_id"),
        UniqueConstraint("assessment_key", name="uq_parser_paper_canary_readiness_key"),
        Index("ix_parser_paper_canary_readiness_status_valid", "status", "valid_until"),
        Index("ix_parser_paper_canary_readiness_binding_evaluated", "binding_db_id", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_paper_runtime_bindings.id", ondelete="RESTRICT"), nullable=False
    )
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    paper_account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    insufficient_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    admissible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observation_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_source_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freshness_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperCanaryReadinessEvidenceRun(Base):
    __tablename__ = "canonical_parser_paper_canary_readiness_evidence_runs"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_paper_canary_readiness_evidence_sequence"),
        CheckConstraint(
            "status IN ('PASSED', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_parser_paper_canary_readiness_evidence_status",
        ),
        CheckConstraint(
            "source_result_count >= 0 AND admissible_count >= 0 AND review_count >= 0 AND blocked_count >= 0",
            name="ck_parser_paper_canary_readiness_evidence_counts",
        ),
        CheckConstraint(
            "source_result_count = admissible_count + review_count + blocked_count",
            name="ck_parser_paper_canary_readiness_evidence_breakdown",
        ),
        CheckConstraint("length(canary_key) = 64", name="ck_parser_paper_canary_readiness_evidence_key"),
        CheckConstraint("length(binding_event_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_binding_hash"),
        CheckConstraint("length(source_evidence_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_source_hash"),
        CheckConstraint("length(account_state_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_account_hash"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_policy_hash"),
        CheckConstraint("length(run_evidence_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_run_hash"),
        UniqueConstraint("assessment_db_id", "sequence", name="uq_parser_paper_canary_readiness_evidence_sequence"),
        UniqueConstraint("assessment_db_id", "canary_run_db_id", name="uq_parser_paper_canary_readiness_evidence_source"),
        Index("ix_parser_paper_canary_readiness_evidence_assessment_status", "assessment_db_id", "status"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_paper_canary_readiness_assessments.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    canary_run_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_paper_admission_canary_runs.id", ondelete="RESTRICT"), nullable=False
    )
    canary_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    admissible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False)
    canary_key: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    account_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperExecutionPermit(Base):
    __tablename__ = "canonical_parser_paper_execution_permits"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_parser_paper_execution_permits_status"),
        CheckConstraint(
            "scope = 'PAPER_EXECUTION_METADATA_ONLY'",
            name="ck_parser_paper_execution_permits_scope",
        ),
        CheckConstraint("requested_validity_minutes >= 1", name="ck_parser_paper_execution_permits_validity"),
        CheckConstraint(
            "total_budget_sol > 0 AND max_order_budget_sol > 0 AND max_order_budget_sol <= total_budget_sol",
            name="ck_parser_paper_execution_permits_budget",
        ),
        CheckConstraint("max_order_count >= 1", name="ck_parser_paper_execution_permits_order_count"),
        CheckConstraint(
            "consumed_budget_sol >= 0 AND consumed_budget_sol <= total_budget_sol",
            name="ck_parser_paper_execution_permits_consumed_budget",
        ),
        CheckConstraint(
            "consumed_order_count >= 0 AND consumed_order_count <= max_order_count",
            name="ck_parser_paper_execution_permits_consumed_orders",
        ),
        CheckConstraint("latest_event_sequence >= 1", name="ck_parser_paper_execution_permits_event_sequence"),
        CheckConstraint("length(permit_key) = 64", name="ck_parser_paper_execution_permits_key"),
        CheckConstraint("length(readiness_evidence_hash) = 64", name="ck_parser_paper_execution_permits_evidence_hash"),
        CheckConstraint("length(binding_event_hash) = 64", name="ck_parser_paper_execution_permits_binding_hash"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_execution_permits_policy_hash"),
        CheckConstraint("length(latest_event_hash) = 64", name="ck_parser_paper_execution_permits_event_hash"),
        UniqueConstraint("permit_id", name="uq_parser_paper_execution_permits_id"),
        UniqueConstraint("permit_key", name="uq_parser_paper_execution_permits_key"),
        Index("ix_parser_paper_execution_permits_status_expires", "status", "expires_at"),
        Index("ix_parser_paper_execution_permits_account_issued", "paper_account_id", "issued_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_key: Mapped[str] = mapped_column(String(64), nullable=False)
    readiness_assessment_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_paper_canary_readiness_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    readiness_assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    readiness_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_paper_runtime_bindings.id", ondelete="RESTRICT"), nullable=False
    )
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    paper_account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False)
    paper_account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_validity_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    total_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    max_order_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    max_order_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), default=Decimal("0"), nullable=False)
    consumed_order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperExecutionPermitEvent(Base):
    __tablename__ = "canonical_parser_paper_execution_permit_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_paper_execution_permit_events_sequence"),
        CheckConstraint("event_type IN ('ISSUED', 'REVOKED')", name="ck_parser_paper_execution_permit_events_type"),
        CheckConstraint("new_status IN ('ACTIVE', 'REVOKED')", name="ck_parser_paper_execution_permit_events_status"),
        CheckConstraint("length(event_hash) = 64", name="ck_parser_paper_execution_permit_events_hash"),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_parser_paper_execution_permit_events_previous_hash",
        ),
        UniqueConstraint("event_id", name="uq_parser_paper_execution_permit_events_id"),
        UniqueConstraint("permit_db_id", "sequence", name="uq_parser_paper_execution_permit_events_sequence"),
        Index("ix_parser_paper_execution_permit_events_permit_occurred", "permit_db_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_paper_execution_permits.id", ondelete="CASCADE"), nullable=False
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


class CanonicalParserUnifiedDecisionRun(Base):
    __tablename__ = "canonical_parser_unified_decision_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('COMPLETED', 'PARTIAL', 'FAILED')",
            name="ck_parser_unified_decision_runs_status",
        ),
        CheckConstraint(
            "scope = 'SHADOW_DECISION_ONLY'",
            name="ck_parser_unified_decision_runs_scope",
        ),
        CheckConstraint(
            "source_trade_count >= 0 AND source_token_count >= 0 "
            "AND source_wallet_count >= 0 AND qualified_wallet_count >= 0",
            name="ck_parser_unified_decision_runs_source_counts",
        ),
        CheckConstraint(
            "result_count >= 0 AND approve_count >= 0 AND review_count >= 0 "
            "AND reject_count >= 0 AND insufficient_data_count >= 0",
            name="ck_parser_unified_decision_runs_decision_counts",
        ),
        CheckConstraint(
            "result_count = approve_count + review_count + reject_count + insufficient_data_count",
            name="ck_parser_unified_decision_runs_decision_breakdown",
        ),
        CheckConstraint("length(run_key) = 64", name="ck_parser_unified_decision_runs_key"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_unified_decision_runs_policy_hash"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_parser_unified_decision_runs_evidence_hash"),
        UniqueConstraint("run_id", name="uq_parser_unified_decision_runs_id"),
        UniqueConstraint("run_key", name="uq_parser_unified_decision_runs_key"),
        Index("ix_parser_unified_decision_runs_status_completed", "status", "completed_at"),
        Index("ix_parser_unified_decision_runs_valid_until", "valid_until"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_wallet_count: Mapped[int] = mapped_column(Integer, nullable=False)
    qualified_wallet_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    approve_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reject_count: Mapped[int] = mapped_column(Integer, nullable=False)
    insufficient_data_count: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    safety: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserUnifiedDecisionResult(Base):
    __tablename__ = "canonical_parser_unified_decision_results"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('APPROVE', 'REVIEW', 'REJECT', 'INSUFFICIENT_DATA')",
            name="ck_parser_unified_decision_results_decision",
        ),
        CheckConstraint(
            "token_safety_status IN ('SAFE', 'REVIEW', 'UNSAFE', 'INSUFFICIENT_DATA')",
            name="ck_parser_unified_decision_results_token_status",
        ),
        CheckConstraint(
            "timing_status IN ('COPYABLE', 'LATE', 'STALE', 'INSUFFICIENT_DATA')",
            name="ck_parser_unified_decision_results_timing_status",
        ),
        CheckConstraint(
            "raw_wallet_count >= 0 AND qualified_wallet_count >= 0 "
            "AND independent_cluster_count >= 0 AND follower_wallet_count >= 0",
            name="ck_parser_unified_decision_results_counts",
        ),
        CheckConstraint(
            "signal_score >= 0 AND signal_score <= 100 "
            "AND confidence_score >= 0 AND confidence_score <= 100 "
            "AND uncertainty_score >= 0 AND uncertainty_score <= 100",
            name="ck_parser_unified_decision_results_scores",
        ),
        CheckConstraint(
            "requested_size_sol >= 0 AND approved_size_sol >= 0 "
            "AND approved_size_sol <= requested_size_sol",
            name="ck_parser_unified_decision_results_sizes",
        ),
        CheckConstraint("sequence >= 1", name="ck_parser_unified_decision_results_sequence"),
        CheckConstraint("length(decision_hash) = 64", name="ck_parser_unified_decision_results_hash"),
        UniqueConstraint("result_id", name="uq_parser_unified_decision_results_id"),
        UniqueConstraint("run_db_id", "sequence", name="uq_parser_unified_decision_results_sequence"),
        UniqueConstraint("run_db_id", "token_mint", name="uq_parser_unified_decision_results_token"),
        Index("ix_parser_unified_decision_results_run_decision", "run_db_id", "decision"),
        Index("ix_parser_unified_decision_results_token_created", "token_mint", "created_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_unified_decision_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_trade_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    source_signatures: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    source_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_wallet_count: Mapped[int] = mapped_column(Integer, nullable=False)
    qualified_wallet_count: Mapped[int] = mapped_column(Integer, nullable=False)
    independent_cluster_count: Mapped[int] = mapped_column(Integer, nullable=False)
    follower_wallet_count: Mapped[int] = mapped_column(Integer, nullable=False)
    leader_wallet: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    uncertainty_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    requested_size_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    approved_size_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    token_safety_status: Mapped[str] = mapped_column(String(24), nullable=False)
    timing_status: Mapped[str] = mapped_column(String(24), nullable=False)
    market_regime: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence_calibration_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    positive_factors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    exit_plan: Mapped[dict] = mapped_column(JSON, nullable=False)
    counterfactuals: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserUnifiedDecisionWalletEvidence(Base):
    __tablename__ = "canonical_parser_unified_decision_wallet_evidence"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_unified_decision_wallet_evidence_sequence"),
        CheckConstraint(
            "qualification_status IN ('QUALIFIED', 'REVIEW', 'REJECTED', 'INSUFFICIENT_DATA', 'EXPIRED')",
            name="ck_parser_unified_decision_wallet_evidence_status",
        ),
        CheckConstraint(
            "role IN ('EARLY_LEADER', 'CONFIRMING_LEADER', 'FOLLOWER', 'LATE_FOLLOWER', 'UNQUALIFIED')",
            name="ck_parser_unified_decision_wallet_evidence_role",
        ),
        CheckConstraint(
            "final_score >= 0 AND final_score <= 100 "
            "AND confidence_score >= 0 AND confidence_score <= 100",
            name="ck_parser_unified_decision_wallet_evidence_scores",
        ),
        CheckConstraint("length(cluster_key) = 64", name="ck_parser_unified_decision_wallet_evidence_cluster"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_parser_unified_decision_wallet_evidence_hash"),
        UniqueConstraint("evidence_id", name="uq_parser_unified_decision_wallet_evidence_id"),
        UniqueConstraint("result_db_id", "wallet_address", name="uq_parser_unified_decision_wallet_evidence_wallet"),
        UniqueConstraint("result_db_id", "sequence", name="uq_parser_unified_decision_wallet_evidence_sequence"),
        Index("ix_parser_unified_decision_wallet_evidence_result_status", "result_db_id", "qualification_status"),
        Index("ix_parser_unified_decision_wallet_evidence_wallet_created", "wallet_address", "created_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(36), nullable=False)
    result_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_unified_decision_results.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    cluster_key: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    qualification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    final_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    positive_factors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserPermitBoundPaperExecution(Base):
    __tablename__ = "canonical_parser_permit_bound_paper_executions"
    __table_args__ = (
        CheckConstraint(
            "side IN ('BUY', 'SELL')",
            name="ck_parser_permit_bound_paper_executions_side",
        ),
        CheckConstraint(
            "status IN ('RESERVED', 'SETTLED', 'RELEASED', 'FAILED', 'RECONCILIATION_REQUIRED')",
            name="ck_parser_permit_bound_paper_executions_status",
        ),
        CheckConstraint(
            "requested_budget_sol >= 0 AND reserved_budget_sol >= 0 AND settled_budget_sol >= 0",
            name="ck_parser_permit_bound_paper_executions_budgets",
        ),
        CheckConstraint(
            "quantity >= 0 AND market_price_sol > 0 AND slippage_percent >= 0 AND fee_percent >= 0",
            name="ck_parser_permit_bound_paper_executions_values",
        ),
        CheckConstraint("length(idempotency_key) = 64", name="ck_parser_permit_bound_paper_executions_idempotency"),
        CheckConstraint("length(decision_hash) = 64", name="ck_parser_permit_bound_paper_executions_decision_hash"),
        CheckConstraint("length(reservation_hash) = 64", name="ck_parser_permit_bound_paper_executions_reservation_hash"),
        CheckConstraint(
            "settlement_hash IS NULL OR length(settlement_hash) = 64",
            name="ck_parser_permit_bound_paper_executions_settlement_hash",
        ),
        UniqueConstraint("execution_id", name="uq_parser_permit_bound_paper_executions_id"),
        UniqueConstraint("idempotency_key", name="uq_parser_permit_bound_paper_executions_idempotency"),
        Index("ix_parser_permit_bound_paper_executions_status_created", "status", "created_at"),
        Index("ix_parser_permit_bound_paper_executions_permit_created", "permit_db_id", "created_at"),
        Index("ix_parser_permit_bound_paper_executions_account_token", "paper_account_id", "token_mint"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_paper_execution_permits.id", ondelete="RESTRICT"), nullable=False
    )
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_result_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_unified_decision_results.id", ondelete="RESTRICT"), nullable=False
    )
    decision_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    paper_account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False)
    paper_order_id: Mapped[int | None] = mapped_column(ForeignKey("paper_orders.id", ondelete="SET NULL"), nullable=True)
    paper_position_id: Mapped[int | None] = mapped_column(ForeignKey("paper_positions.id", ondelete="SET NULL"), nullable=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    reserved_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    settled_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    market_price_sol: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    slippage_percent: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    fee_percent: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    signal_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    permit_budget_before_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    permit_order_count_before: Mapped[int] = mapped_column(Integer, nullable=False)
    reservation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    settlement_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPermitBoundPaperExecutionEvent(Base):
    __tablename__ = "canonical_parser_permit_bound_paper_execution_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_permit_bound_paper_execution_events_sequence"),
        CheckConstraint(
            "event_type IN ('RESERVED', 'SETTLED', 'RELEASED', 'FAILED', 'RECONCILIATION_REQUIRED')",
            name="ck_parser_permit_bound_paper_execution_events_type",
        ),
        CheckConstraint("length(event_hash) = 64", name="ck_parser_permit_bound_paper_execution_events_hash"),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_parser_permit_bound_paper_execution_events_previous_hash",
        ),
        UniqueConstraint("event_id", name="uq_parser_permit_bound_paper_execution_events_id"),
        UniqueConstraint("execution_db_id", "sequence", name="uq_parser_permit_bound_paper_execution_events_sequence"),
        Index("ix_parser_permit_bound_paper_execution_events_execution", "execution_db_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    execution_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_permit_bound_paper_executions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperCalibrationCampaign(Base):
    __tablename__ = "canonical_parser_paper_calibration_campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_parser_paper_calibration_campaigns_status",
        ),
        CheckConstraint(
            "scope = 'PAPER_ANALYTICS_ONLY'",
            name="ck_parser_paper_calibration_campaigns_scope",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND settled_count >= 0 AND released_count >= 0 AND failed_count >= 0",
            name="ck_parser_paper_calibration_campaigns_attempt_counts",
        ),
        CheckConstraint(
            "buy_count >= 0 AND sell_count >= 0 AND closed_outcome_count >= 0 AND winning_outcome_count >= 0",
            name="ck_parser_paper_calibration_campaigns_outcome_counts",
        ),
        CheckConstraint("length(campaign_key) = 64", name="ck_parser_paper_calibration_campaigns_key"),
        CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_calibration_campaigns_policy_hash"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_calibration_campaigns_evidence_hash"),
        UniqueConstraint("campaign_id", name="uq_parser_paper_calibration_campaigns_id"),
        UniqueConstraint("campaign_key", name="uq_parser_paper_calibration_campaigns_key"),
        Index("ix_parser_paper_calibration_campaigns_account_completed", "paper_account_id", "completed_at"),
        Index("ix_parser_paper_calibration_campaigns_status_completed", "status", "completed_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    paper_account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False)
    permit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    settled_count: Mapped[int] = mapped_column(Integer, nullable=False)
    released_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reconciliation_required_count: Mapped[int] = mapped_column(Integer, nullable=False)
    buy_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sell_count: Mapped[int] = mapped_column(Integer, nullable=False)
    closed_outcome_count: Mapped[int] = mapped_column(Integer, nullable=False)
    winning_outcome_count: Mapped[int] = mapped_column(Integer, nullable=False)
    realized_pnl_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    total_fee_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    estimated_slippage_cost_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    win_rate_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    profit_factor: Mapped[Decimal | None] = mapped_column(Numeric(20, 9), nullable=True)
    brier_score: Mapped[Decimal | None] = mapped_column(Numeric(12, 9), nullable=True)
    calibration_gap_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    reliability_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    segments: Mapped[dict] = mapped_column(JSON, nullable=False)
    recommendations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperCalibrationEvidence(Base):
    __tablename__ = "canonical_parser_paper_calibration_evidence"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_parser_paper_calibration_evidence_sequence"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_calibration_evidence_hash"),
        UniqueConstraint("campaign_db_id", "sequence", name="uq_parser_paper_calibration_evidence_sequence"),
        UniqueConstraint("campaign_db_id", "execution_db_id", name="uq_parser_paper_calibration_evidence_execution"),
        Index("ix_parser_paper_calibration_evidence_campaign_status", "campaign_db_id", "execution_status"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    campaign_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_paper_calibration_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_permit_bound_paper_executions.id", ondelete="RESTRICT"), nullable=False
    )
    execution_id: Mapped[str] = mapped_column(String(36), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    realized_pnl_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperCampaignRun(Base):
    __tablename__ = "canonical_parser_paper_campaign_runs"
    __table_args__ = (
        CheckConstraint("scope = 'PAPER_MANUAL_ORCHESTRATION'", name="ck_m34_campaign_scope"),
        CheckConstraint("status IN ('COMPLETED','PARTIAL','BLOCKED','FAILED','NOOP','RECONCILIATION_REQUIRED')", name="ck_m34_campaign_status"),
        CheckConstraint("requested_count >= 0 AND selected_count >= 0 AND settled_count >= 0 AND released_count >= 0 AND failed_count >= 0 AND reconciliation_required_count >= 0 AND skipped_count >= 0", name="ck_m34_campaign_counts"),
        CheckConstraint("requested_budget_sol >= 0 AND settled_budget_sol >= 0", name="ck_m34_campaign_budget"),
        CheckConstraint("length(campaign_key) = 64 AND length(policy_hash) = 64 AND length(evidence_hash) = 64", name="ck_m34_campaign_hashes"),
        UniqueConstraint("campaign_id", name="uq_m34_campaign_id"),
        UniqueConstraint("campaign_key", name="uq_m34_campaign_key"),
        Index("ix_m34_campaign_account_created", "paper_account_id", "created_at"),
        Index("ix_m34_campaign_status_created", "status", "created_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    paper_account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False)
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    settled_count: Mapped[int] = mapped_column(Integer, nullable=False)
    released_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reconciliation_required_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    settled_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    safety: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperCampaignItem(Base):
    __tablename__ = "canonical_parser_paper_campaign_items"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m34_item_sequence"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_m34_item_side"),
        CheckConstraint("status IN ('SETTLED','RELEASED','FAILED','RECONCILIATION_REQUIRED','SKIPPED')", name="ck_m34_item_status"),
        CheckConstraint("market_price_sol > 0 AND requested_budget_sol >= 0 AND settled_budget_sol >= 0", name="ck_m34_item_values"),
        CheckConstraint("length(idempotency_key) = 64 AND length(item_hash) = 64", name="ck_m34_item_hashes"),
        UniqueConstraint("campaign_db_id", "sequence", name="uq_m34_item_sequence"),
        UniqueConstraint("campaign_db_id", "decision_result_id", "side", name="uq_m34_item_decision_side"),
        Index("ix_m34_item_campaign_status", "campaign_db_id", "status"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    campaign_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_campaign_runs.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    market_price_sol: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    requested_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    settled_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    item_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPaperOperationalAssessment(Base):
    __tablename__ = "canonical_parser_paper_operational_assessments"
    __table_args__ = (
        CheckConstraint("status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m34_assessment_status"),
        CheckConstraint("scope = 'PAPER_OPERATIONAL_READINESS'", name="ck_m34_assessment_scope"),
        CheckConstraint("settled_count >= 0 AND reconciliation_required_count >= 0 AND stale_reservation_count >= 0 AND budget_drift_count >= 0", name="ck_m34_assessment_counts"),
        CheckConstraint("length(assessment_key) = 64 AND length(policy_hash) = 64 AND length(evidence_hash) = 64", name="ck_m34_assessment_hashes"),
        UniqueConstraint("assessment_id", name="uq_m34_assessment_id"),
        UniqueConstraint("assessment_key", name="uq_m34_assessment_key"),
        Index("ix_m34_assessment_account_completed", "paper_account_id", "completed_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    paper_account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False)
    calibration_campaign_db_id: Mapped[int | None] = mapped_column(ForeignKey("canonical_parser_paper_calibration_campaigns.id", ondelete="SET NULL"), nullable=True)
    calibration_campaign_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    settled_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reconciliation_required_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stale_reservation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_drift_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reliability_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    calibration_gap_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserMicroLiveCanaryPermit(Base):
    __tablename__ = "canonical_parser_micro_live_canary_permits"
    __table_args__ = (
        CheckConstraint("scope = 'MICRO_LIVE_GOVERNANCE_SIMULATION_ONLY'", name="ck_m35_permit_scope"),
        CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','EXHAUSTED')", name="ck_m35_permit_status"),
        CheckConstraint("total_budget_sol > 0 AND max_order_budget_sol > 0 AND max_order_budget_sol <= total_budget_sol", name="ck_m35_permit_budgets"),
        CheckConstraint("max_order_count >= 1 AND simulated_order_count >= 0 AND simulated_budget_sol >= 0", name="ck_m35_permit_counts"),
        CheckConstraint("length(permit_key) = 64 AND length(assessment_evidence_hash) = 64 AND length(policy_hash) = 64", name="ck_m35_permit_hashes"),
        UniqueConstraint("permit_id", name="uq_m35_permit_id"),
        UniqueConstraint("permit_key", name="uq_m35_permit_key"),
        Index("ix_m35_permit_status_expiry", "status", "expires_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_key: Mapped[str] = mapped_column(String(64), nullable=False)
    operational_assessment_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_paper_operational_assessments.id", ondelete="RESTRICT"), nullable=False)
    operational_assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_validity_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    total_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    max_order_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    max_order_count: Mapped[int] = mapped_column(Integer, nullable=False)
    simulated_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    simulated_order_count: Mapped[int] = mapped_column(Integer, nullable=False)
    live_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    live_platform_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    technical_metadata: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserMicroLiveCanaryPermitEvent(Base):
    __tablename__ = "canonical_parser_micro_live_canary_permit_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m35_event_sequence"),
        CheckConstraint("event_type IN ('ISSUED','SIMULATED','REVOKED','EXPIRED','EXHAUSTED')", name="ck_m35_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m35_event_hash"),
        UniqueConstraint("event_id", name="uq_m35_event_id"),
        UniqueConstraint("permit_db_id", "sequence", name="uq_m35_event_sequence"),
        Index("ix_m35_event_permit_time", "permit_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_micro_live_canary_permits.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserMicroLiveCanarySimulation(Base):
    __tablename__ = "canonical_parser_micro_live_canary_simulations"
    __table_args__ = (
        CheckConstraint("side IN ('BUY','SELL')", name="ck_m35_sim_side"),
        CheckConstraint("status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m35_sim_status"),
        CheckConstraint("requested_budget_sol >= 0 AND simulated_budget_sol >= 0 AND market_price_sol > 0", name="ck_m35_sim_values"),
        CheckConstraint("length(simulation_key) = 64 AND length(decision_hash) = 64 AND length(evidence_hash) = 64", name="ck_m35_sim_hashes"),
        UniqueConstraint("simulation_id", name="uq_m35_sim_id"),
        UniqueConstraint("simulation_key", name="uq_m35_sim_key"),
        Index("ix_m35_sim_permit_created", "permit_db_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    simulation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    simulation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_micro_live_canary_permits.id", ondelete="RESTRICT"), nullable=False)
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_result_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_unified_decision_results.id", ondelete="RESTRICT"), nullable=False)
    decision_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    simulated_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    market_price_sol: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    simulated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserIsolatedSignerProfile(Base):
    __tablename__ = "canonical_parser_isolated_signer_profiles"
    __table_args__ = (
        CheckConstraint(
            "scope = 'M36_ISOLATED_SIGNER_DRY_RUN_ONLY'",
            name="ck_m36_signer_profile_scope",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','REVOKED','EXPIRED')",
            name="ck_m36_signer_profile_status",
        ),
        CheckConstraint(
            "network = 'mainnet-beta'",
            name="ck_m36_signer_profile_network",
        ),
        CheckConstraint(
            "validity_minutes >= 1 AND max_transaction_bytes >= 1 "
            "AND max_required_signers >= 1",
            name="ck_m36_signer_profile_limits",
        ),
        CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_m36_signer_profile_event_sequence",
        ),
        CheckConstraint(
            "length(profile_key) = 64 AND length(policy_hash) = 64 "
            "AND length(latest_event_hash) = 64",
            name="ck_m36_signer_profile_hashes",
        ),
        UniqueConstraint("profile_id", name="uq_m36_signer_profile_id"),
        UniqueConstraint("profile_key", name="uq_m36_signer_profile_key"),
        Index("ix_m36_signer_profile_status_expiry", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    network: Mapped[str] = mapped_column(String(24), nullable=False)
    allowed_program_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    max_transaction_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    max_required_signers: Mapped[int] = mapped_column(Integer, nullable=False)
    allow_address_lookup_tables: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validity_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserIsolatedSignerProfileEvent(Base):
    __tablename__ = "canonical_parser_isolated_signer_profile_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m36_signer_event_sequence"),
        CheckConstraint(
            "event_type IN ('ISSUED','REVOKED','EXPIRED')",
            name="ck_m36_signer_event_type",
        ),
        CheckConstraint("length(event_hash) = 64", name="ck_m36_signer_event_hash"),
        UniqueConstraint("event_id", name="uq_m36_signer_event_id"),
        UniqueConstraint(
            "profile_db_id", "sequence", name="uq_m36_signer_event_sequence"
        ),
        Index("ix_m36_signer_event_profile_time", "profile_db_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    profile_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_isolated_signer_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserLiveTransactionDryRun(Base):
    __tablename__ = "canonical_parser_live_transaction_dry_runs"
    __table_args__ = (
        CheckConstraint(
            "scope = 'M36_PRE_SIGN_DRY_RUN_ONLY'",
            name="ck_m36_dry_run_scope",
        ),
        CheckConstraint(
            "status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')",
            name="ck_m36_dry_run_status",
        ),
        CheckConstraint(
            "transaction_source IN ('JUPITER_ORDER','PROVIDED_TRANSACTION')",
            name="ck_m36_dry_run_source",
        ),
        CheckConstraint(
            "transaction_format IN ('LEGACY','V0')",
            name="ck_m36_dry_run_format",
        ),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_m36_dry_run_side"),
        CheckConstraint(
            "rpc_simulation_status IN ('PASSED','FAILED','SKIPPED','UNAVAILABLE')",
            name="ck_m36_dry_run_rpc_status",
        ),
        CheckConstraint(
            "transaction_size_bytes > 0 AND signature_slot_count >= 0 "
            "AND required_signer_count >= 1 AND static_account_count >= 1 "
            "AND instruction_count >= 1 AND address_lookup_count >= 0",
            name="ck_m36_dry_run_counts",
        ),
        CheckConstraint(
            "amount_raw > 0 AND requested_budget_sol >= 0",
            name="ck_m36_dry_run_values",
        ),
        CheckConstraint(
            "jupiter_slippage_bps IS NULL OR jupiter_slippage_bps >= 0",
            name="ck_m36_dry_run_slippage",
        ),
        CheckConstraint(
            "length(dry_run_key) = 64 AND length(transaction_hash) = 64 "
            "AND length(message_hash) = 64 AND length(account_keys_hash) = 64 "
            "AND length(signing_envelope_hash) = 64 AND length(evidence_hash) = 64",
            name="ck_m36_dry_run_hashes",
        ),
        UniqueConstraint("dry_run_id", name="uq_m36_dry_run_id"),
        UniqueConstraint("dry_run_key", name="uq_m36_dry_run_key"),
        Index("ix_m36_dry_run_status_prepared", "status", "prepared_at"),
        Index("ix_m36_dry_run_profile_prepared", "signer_profile_db_id", "prepared_at"),
        Index("ix_m36_dry_run_simulation", "micro_live_simulation_db_id"),
    )

    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    dry_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dry_run_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    signer_profile_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_isolated_signer_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    signer_profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    micro_live_simulation_db_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_parser_micro_live_canary_simulations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    micro_live_simulation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    micro_live_permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    transaction_source: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_format: Mapped[str] = mapped_column(String(12), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    output_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    requested_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    transaction_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    signature_slot_count: Mapped[int] = mapped_column(Integer, nullable=False)
    required_signer_count: Mapped[int] = mapped_column(Integer, nullable=False)
    static_account_count: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    address_lookup_count: Mapped[int] = mapped_column(Integer, nullable=False)
    required_signers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    program_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    writable_accounts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    account_keys_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    jupiter_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    jupiter_router: Mapped[str | None] = mapped_column(String(160), nullable=True)
    jupiter_price_impact_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    jupiter_slippage_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpc_simulation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    units_consumed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    inspection_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    rpc_simulation_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    signing_envelope: Mapped[dict] = mapped_column(JSON, nullable=False)
    signing_envelope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    envelope_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class CanonicalParserExternalSigningApproval(Base):
    __tablename__ = "canonical_parser_external_signing_approvals"
    __table_args__ = (
        CheckConstraint("scope = 'M37_EXTERNAL_SIGNING_APPROVAL_ONLY'", name="ck_m37_approval_scope"),
        CheckConstraint("status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA','REVOKED','EXPIRED')", name="ck_m37_approval_status"),
        CheckConstraint("signature_verification_status IN ('PASSED','FAILED')", name="ck_m37_signature_status"),
        CheckConstraint("rpc_simulation_status IN ('PASSED','FAILED','SKIPPED','UNAVAILABLE')", name="ck_m37_rpc_status"),
        CheckConstraint("signature_count >= 1", name="ck_m37_signature_count"),
        CheckConstraint("length(approval_key) = 64 AND length(signed_transaction_hash) = 64 AND length(message_hash) = 64 AND length(approval_envelope_hash) = 64 AND length(evidence_hash) = 64", name="ck_m37_hashes"),
        UniqueConstraint("approval_id", name="uq_m37_approval_id"),
        UniqueConstraint("approval_key", name="uq_m37_approval_key"),
        Index("ix_m37_approval_status_expiry", "status", "expires_at"),
        Index("ix_m37_approval_dry_run", "dry_run_db_id"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approval_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    dry_run_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_transaction_dry_runs.id", ondelete="RESTRICT"), nullable=False)
    dry_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    signer_profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    micro_live_permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    signed_transaction_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_signature: Mapped[str] = mapped_column(String(96), nullable=False)
    verified_signers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    signature_count: Mapped[int] = mapped_column(Integer, nullable=False)
    signature_verification_status: Mapped[str] = mapped_column(String(16), nullable=False)
    rpc_simulation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    units_consumed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    verification_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    rpc_simulation_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    approval_envelope: Mapped[dict] = mapped_column(JSON, nullable=False)
    approval_envelope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserExternalSigningApprovalEvent(Base):
    __tablename__ = "canonical_parser_external_signing_approval_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m37_event_sequence"),
        CheckConstraint("event_type IN ('APPROVED','REVOKED','EXPIRED')", name="ck_m37_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m37_event_hash"),
        UniqueConstraint("event_id", name="uq_m37_event_id"),
        UniqueConstraint("approval_db_id", "sequence", name="uq_m37_event_sequence"),
        Index("ix_m37_event_approval_time", "approval_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approval_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_external_signing_approvals.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserControlledLiveSubmission(Base):
    __tablename__ = "canonical_parser_controlled_live_submissions"
    __table_args__ = (
        CheckConstraint("scope = 'M38_MANUAL_CONTROLLED_LIVE_SUBMISSION'", name="ck_m38_submission_scope"),
        CheckConstraint("status IN ('RESERVED','SUBMITTED','PROCESSED','CONFIRMED','FINALIZED','FAILED','RECONCILIATION_REQUIRED')", name="ck_m38_submission_status"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_m38_submission_side"),
        CheckConstraint("reserved_budget_sol >= 0", name="ck_m38_submission_budget"),
        CheckConstraint("length(submission_key) = 64 AND length(signed_transaction_hash) = 64 AND length(evidence_hash) = 64", name="ck_m38_submission_hashes"),
        UniqueConstraint("submission_id", name="uq_m38_submission_id"),
        UniqueConstraint("submission_key", name="uq_m38_submission_key"),
        UniqueConstraint("approval_db_id", name="uq_m38_submission_approval"),
        UniqueConstraint("rpc_signature", name="uq_m38_rpc_signature"),
        Index("ix_m38_submission_permit_status", "micro_live_permit_id", "status"),
        Index("ix_m38_submission_status_created", "status", "created_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    submission_id: Mapped[str] = mapped_column(String(36), nullable=False)
    submission_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(56), nullable=False)
    approval_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_external_signing_approvals.id", ondelete="RESTRICT"), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dry_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    micro_live_permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    reserved_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    signed_transaction_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_signature: Mapped[str] = mapped_column(String(96), nullable=False)
    rpc_signature: Mapped[str | None] = mapped_column(String(96), nullable=True)
    send_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confirmation_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    confirmation_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chain_error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    reservation_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    submission_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserControlledLiveSubmissionEvent(Base):
    __tablename__ = "canonical_parser_controlled_live_submission_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m38_event_sequence"),
        CheckConstraint("event_type IN ('RESERVED','SUBMITTED','RECONCILED','CONFIRMED','FINALIZED','FAILED','UNCERTAIN')", name="ck_m38_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m38_event_hash"),
        UniqueConstraint("event_id", name="uq_m38_event_id"),
        UniqueConstraint("submission_db_id", "sequence", name="uq_m38_event_sequence"),
        Index("ix_m38_event_submission_time", "submission_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    submission_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_controlled_live_submissions.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class CanonicalParserLiveOnchainSettlement(Base):
    __tablename__ = "canonical_parser_live_onchain_settlements"
    __table_args__ = (
        CheckConstraint("scope = 'M39_AUTHORITATIVE_ONCHAIN_SETTLEMENT'", name="ck_m39_settlement_scope"),
        CheckConstraint("status IN ('SETTLED','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m39_settlement_status"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_m39_settlement_side"),
        CheckConstraint("fee_lamports >= 0 AND actual_input_amount_raw >= 0 AND actual_output_amount_raw >= 0", name="ck_m39_settlement_amounts"),
        CheckConstraint("length(settlement_key) = 64 AND length(evidence_hash) = 64", name="ck_m39_settlement_hashes"),
        UniqueConstraint("settlement_id", name="uq_m39_settlement_id"),
        UniqueConstraint("settlement_key", name="uq_m39_settlement_key"),
        UniqueConstraint("submission_db_id", name="uq_m39_settlement_submission"),
        Index("ix_m39_settlement_status_time", "status", "settled_at"),
        Index("ix_m39_settlement_wallet_token", "wallet_address", "token_mint"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    settlement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    settlement_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    submission_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_controlled_live_submissions.id", ondelete="RESTRICT"), nullable=False)
    submission_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dry_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    micro_live_permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    position_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    rpc_signature: Mapped[str] = mapped_column(String(96), nullable=False)
    confirmation_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    slot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    block_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fee_lamports: Mapped[Decimal] = mapped_column(Numeric(20, 0), nullable=False)
    wallet_sol_delta_lamports: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    token_delta_raw: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    actual_input_amount_raw: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    actual_output_amount_raw: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    actual_input_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    actual_output_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    transaction_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    attribution_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserLiveOnchainSettlementEvent(Base):
    __tablename__ = "canonical_parser_live_onchain_settlement_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m39_settlement_event_sequence"),
        CheckConstraint("event_type IN ('SETTLED','REVIEW','BLOCKED','INSUFFICIENT_DATA','POSITION_OPENED','POSITION_REDUCED','POSITION_CLOSED')", name="ck_m39_settlement_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m39_settlement_event_hash"),
        UniqueConstraint("event_id", name="uq_m39_settlement_event_id"),
        UniqueConstraint("settlement_db_id", "sequence", name="uq_m39_settlement_event_sequence"),
        Index("ix_m39_settlement_event_time", "settlement_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    settlement_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_onchain_settlements.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserGovernedLivePosition(Base):
    __tablename__ = "canonical_parser_governed_live_positions"
    __table_args__ = (
        CheckConstraint("scope = 'M39_GOVERNED_LIVE_POSITION_LEDGER'", name="ck_m39_position_scope"),
        CheckConstraint("status IN ('OPEN','CLOSED','REVIEW')", name="ck_m39_position_status"),
        CheckConstraint("quantity_raw >= 0 AND cost_basis_sol >= 0 AND realized_proceeds_sol >= 0", name="ck_m39_position_values"),
        CheckConstraint("position_version >= 1", name="ck_m39_position_version"),
        CheckConstraint("length(position_key) = 64 AND length(evidence_hash) = 64", name="ck_m39_position_hashes"),
        UniqueConstraint("position_id", name="uq_m39_position_id"),
        UniqueConstraint("position_key", name="uq_m39_position_key"),
        UniqueConstraint("entry_settlement_db_id", name="uq_m39_position_entry_settlement"),
        Index("ix_m39_position_status_token", "status", "token_mint"),
        Index("ix_m39_position_wallet_opened", "wallet_address", "opened_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    position_id: Mapped[str] = mapped_column(String(36), nullable=False)
    position_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    entry_settlement_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_onchain_settlements.id", ondelete="RESTRICT"), nullable=False)
    entry_settlement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    last_settlement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    micro_live_permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity_raw: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    cost_basis_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    realized_proceeds_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    realized_pnl_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    high_watermark_value_sol: Mapped[Decimal | None] = mapped_column(Numeric(20, 9), nullable=True)
    high_watermark_roi_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    exit_plan: Mapped[dict] = mapped_column(JSON, nullable=False)
    position_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    position_version: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CanonicalParserGovernedLivePositionAssessment(Base):
    __tablename__ = "canonical_parser_governed_live_position_assessments"
    __table_args__ = (
        CheckConstraint("scope = 'M40_GOVERNED_LIVE_POSITION_ASSESSMENT'", name="ck_m40_assessment_scope"),
        CheckConstraint("status IN ('HOLD','EXIT_READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m40_assessment_status"),
        CheckConstraint("quoted_output_sol >= 0 AND current_value_sol >= 0", name="ck_m40_assessment_values"),
        CheckConstraint("price_impact_percent >= 0", name="ck_m40_assessment_price_impact"),
        CheckConstraint("token_safety_status IN ('SAFE','REVIEW','UNSAFE','UNKNOWN')", name="ck_m40_assessment_token_safety"),
        CheckConstraint("length(assessment_key) = 64 AND length(evidence_hash) = 64", name="ck_m40_assessment_hashes"),
        UniqueConstraint("assessment_id", name="uq_m40_assessment_id"),
        UniqueConstraint("assessment_key", name="uq_m40_assessment_key"),
        Index("ix_m40_assessment_position_time", "position_db_id", "assessed_at"),
        Index("ix_m40_assessment_status_expiry", "status", "expires_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(52), nullable=False)
    position_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_governed_live_positions.id", ondelete="RESTRICT"), nullable=False)
    position_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    quoted_output_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    current_value_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    unrealized_pnl_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    unrealized_roi_percent: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    high_watermark_value_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    high_watermark_roi_percent: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    trailing_drawdown_percent: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    price_impact_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    sell_route_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    token_safety_status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_wallet_sell_detected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    emergency_exit_requested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    assessment_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserGovernedLiveExitIntent(Base):
    __tablename__ = "canonical_parser_governed_live_exit_intents"
    __table_args__ = (
        CheckConstraint("scope = 'M40_MANUAL_GOVERNED_LIVE_EXIT_INTENT'", name="ck_m40_intent_scope"),
        CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','CONSUMED')", name="ck_m40_intent_status"),
        CheckConstraint("quantity_raw > 0 AND percentage > 0 AND percentage <= 100", name="ck_m40_intent_quantity"),
        CheckConstraint("expected_output_sol >= 0 AND minimum_output_sol >= 0", name="ck_m40_intent_output"),
        CheckConstraint("latest_event_sequence >= 1", name="ck_m40_intent_event_sequence"),
        CheckConstraint("length(intent_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m40_intent_hashes"),
        UniqueConstraint("intent_id", name="uq_m40_intent_id"),
        UniqueConstraint("intent_key", name="uq_m40_intent_key"),
        Index("ix_m40_intent_position_status", "position_db_id", "status"),
        Index("ix_m40_intent_status_expiry", "status", "expires_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    intent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(52), nullable=False)
    position_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_governed_live_positions.id", ondelete="RESTRICT"), nullable=False)
    position_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_governed_live_position_assessments.id", ondelete="RESTRICT"), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    micro_live_permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity_raw: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    percentage: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    expected_output_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    minimum_output_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    intent_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserGovernedLiveExitIntentEvent(Base):
    __tablename__ = "canonical_parser_governed_live_exit_intent_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m40_intent_event_sequence"),
        CheckConstraint("event_type IN ('ISSUED','REVOKED','EXPIRED','CONSUMED')", name="ck_m40_intent_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m40_intent_event_hash"),
        UniqueConstraint("event_id", name="uq_m40_intent_event_id"),
        UniqueConstraint("intent_db_id", "sequence", name="uq_m40_intent_event_sequence"),
        Index("ix_m40_intent_event_time", "intent_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    intent_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_governed_live_exit_intents.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class CanonicalParserLiveIncident(Base):
    __tablename__ = "canonical_parser_live_incidents"
    __table_args__ = (
        CheckConstraint("scope = 'M41_LIVE_INCIDENT_RESPONSE'", name="ck_m41_incident_scope"),
        CheckConstraint("source_type IN ('SUBMISSION','SETTLEMENT','POSITION','MANUAL')", name="ck_m41_incident_source_type"),
        CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_m41_incident_severity"),
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RECOVERY_AUTHORIZED','RESOLVED')", name="ck_m41_incident_status"),
        CheckConstraint("latest_event_sequence >= 1", name="ck_m41_incident_event_sequence"),
        CheckConstraint("length(incident_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m41_incident_hashes"),
        UniqueConstraint("incident_id", name="uq_m41_incident_id"),
        UniqueConstraint("incident_key", name="uq_m41_incident_key"),
        Index("ix_m41_incident_status_severity", "status", "severity"),
        Index("ix_m41_incident_source", "source_type", "source_id"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(36), nullable=False)
    incident_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(96), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    freeze_new_submissions: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    incident_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserLiveIncidentEvent(Base):
    __tablename__ = "canonical_parser_live_incident_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m41_incident_event_sequence"),
        CheckConstraint("event_type IN ('DECLARED','ACKNOWLEDGED','RECOVERY_AUTHORIZED','RECOVERY_REVOKED','RECOVERY_CONSUMED','RESOLVED')", name="ck_m41_incident_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m41_incident_event_hash"),
        UniqueConstraint("event_id", name="uq_m41_incident_event_id"),
        UniqueConstraint("incident_db_id", "sequence", name="uq_m41_incident_event_sequence"),
        Index("ix_m41_incident_event_time", "incident_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    incident_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_incidents.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserLiveRecoveryAuthorization(Base):
    __tablename__ = "canonical_parser_live_recovery_authorizations"
    __table_args__ = (
        CheckConstraint("scope = 'M41_MANUAL_LIVE_RECOVERY_AUTHORIZATION'", name="ck_m41_recovery_scope"),
        CheckConstraint("action IN ('RECONCILE_SUBMISSION','RETRY_SETTLEMENT_READ','MANUAL_POSITION_REVIEW','FREEZE_NEW_SUBMISSIONS','UNFREEZE_NEW_SUBMISSIONS')", name="ck_m41_recovery_action"),
        CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','CONSUMED')", name="ck_m41_recovery_status"),
        CheckConstraint("length(recovery_key) = 64 AND length(evidence_hash) = 64", name="ck_m41_recovery_hashes"),
        UniqueConstraint("recovery_id", name="uq_m41_recovery_id"),
        UniqueConstraint("recovery_key", name="uq_m41_recovery_key"),
        Index("ix_m41_recovery_incident_status", "incident_db_id", "status"),
        Index("ix_m41_recovery_status_expiry", "status", "expires_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    recovery_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recovery_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    incident_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_incidents.id", ondelete="RESTRICT"), nullable=False)
    incident_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    recovery_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserLivePortfolioRiskAssessment(Base):
    __tablename__ = "canonical_parser_live_portfolio_risk_assessments"
    __table_args__ = (
        CheckConstraint("scope = 'M42_AGGREGATED_LIVE_PORTFOLIO_RISK'", name="ck_m42_assessment_scope"),
        CheckConstraint("status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m42_assessment_status"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_m42_assessment_side"),
        CheckConstraint("open_position_count >= 0 AND stale_position_count >= 0 AND active_incident_count >= 0", name="ck_m42_assessment_counts"),
        CheckConstraint("total_cost_basis_sol >= 0 AND current_value_sol >= 0 AND pending_buy_sol >= 0 AND gross_exposure_sol >= 0 AND requested_budget_sol >= 0", name="ck_m42_assessment_values"),
        CheckConstraint("max_token_concentration_percent >= 0 AND max_token_concentration_percent <= 100", name="ck_m42_assessment_concentration"),
        CheckConstraint("length(assessment_key) = 64 AND length(evidence_hash) = 64", name="ck_m42_assessment_hashes"),
        UniqueConstraint("assessment_id", name="uq_m42_assessment_id"),
        UniqueConstraint("assessment_key", name="uq_m42_assessment_key"),
        Index("ix_m42_assessment_wallet_time", "wallet_address", "assessed_at"),
        Index("ix_m42_assessment_status_expiry", "status", "expires_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    requested_token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    open_position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stale_position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    active_incident_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cost_basis_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    current_value_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    unrealized_pnl_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    pending_buy_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    gross_exposure_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    max_token_concentration_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    largest_token_mint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    position_breakdown: Mapped[list] = mapped_column(JSON, nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserLivePortfolioRiskPermit(Base):
    __tablename__ = "canonical_parser_live_portfolio_risk_permits"
    __table_args__ = (
        CheckConstraint("scope = 'M42_MANUAL_PORTFOLIO_RISK_PERMIT'", name="ck_m42_permit_scope"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_m42_permit_side"),
        CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','CONSUMED')", name="ck_m42_permit_status"),
        CheckConstraint("requested_budget_sol >= 0 AND max_additional_exposure_sol >= 0", name="ck_m42_permit_values"),
        CheckConstraint("latest_event_sequence >= 1", name="ck_m42_permit_event_sequence"),
        CheckConstraint("length(permit_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m42_permit_hashes"),
        UniqueConstraint("permit_id", name="uq_m42_permit_id"),
        UniqueConstraint("permit_key", name="uq_m42_permit_key"),
        Index("ix_m42_permit_wallet_status", "wallet_address", "status"),
        Index("ix_m42_permit_status_expiry", "status", "expires_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    assessment_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_portfolio_risk_assessments.id", ondelete="RESTRICT"), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    max_additional_exposure_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    permit_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_submission_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserLivePortfolioRiskPermitEvent(Base):
    __tablename__ = "canonical_parser_live_portfolio_risk_permit_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m42_permit_event_sequence"),
        CheckConstraint("event_type IN ('ISSUED','REVOKED','EXPIRED','CONSUMED')", name="ck_m42_permit_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m42_permit_event_hash"),
        UniqueConstraint("event_id", name="uq_m42_permit_event_id"),
        UniqueConstraint("permit_db_id", "sequence", name="uq_m42_permit_event_sequence"),
        Index("ix_m42_permit_event_time", "permit_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permit_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_portfolio_risk_permits.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserLiveObservabilitySnapshot(Base):
    __tablename__ = "canonical_parser_live_observability_snapshots"
    __table_args__ = (
        CheckConstraint("scope = 'M43_LIVE_OPERATIONAL_OBSERVABILITY'", name="ck_m43_snapshot_scope"),
        CheckConstraint("status IN ('HEALTHY','DEGRADED','CRITICAL','INSUFFICIENT_DATA')", name="ck_m43_snapshot_status"),
        CheckConstraint("uncertain_submission_count >= 0 AND stale_submission_count >= 0 AND unsettled_count >= 0 AND review_position_count >= 0 AND active_incident_count >= 0 AND open_alert_count >= 0", name="ck_m43_snapshot_counts"),
        CheckConstraint("length(snapshot_key) = 64 AND length(evidence_hash) = 64", name="ck_m43_snapshot_hashes"),
        UniqueConstraint("snapshot_id", name="uq_m43_snapshot_id"),
        UniqueConstraint("snapshot_key", name="uq_m43_snapshot_key"),
        Index("ix_m43_snapshot_status_time", "status", "observed_at"),
        Index("ix_m43_snapshot_expiry", "expires_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    uncertain_submission_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stale_submission_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unsettled_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    active_incident_count: Mapped[int] = mapped_column(Integer, nullable=False)
    open_alert_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    metric_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserLiveOperationalAlert(Base):
    __tablename__ = "canonical_parser_live_operational_alerts"
    __table_args__ = (
        CheckConstraint("scope = 'M43_MANUAL_OPERATIONAL_ALERT'", name="ck_m43_alert_scope"),
        CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_m43_alert_severity"),
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED')", name="ck_m43_alert_status"),
        CheckConstraint("latest_event_sequence >= 1", name="ck_m43_alert_event_sequence"),
        CheckConstraint("length(alert_key) = 64 AND length(fingerprint) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m43_alert_hashes"),
        UniqueConstraint("alert_id", name="uq_m43_alert_id"),
        UniqueConstraint("alert_key", name="uq_m43_alert_key"),
        Index("ix_m43_alert_fingerprint_status", "fingerprint", "status"),
        Index("ix_m43_alert_severity_status", "severity", "status"),
        Index("ix_m43_alert_last_seen", "last_seen_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    alert_id: Mapped[str] = mapped_column(String(36), nullable=False)
    alert_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    snapshot_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_observability_snapshots.id", ondelete="RESTRICT"), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(96), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    alert_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserLiveOperationalAlertEvent(Base):
    __tablename__ = "canonical_parser_live_operational_alert_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m43_alert_event_sequence"),
        CheckConstraint("event_type IN ('OPENED','ACKNOWLEDGED','RESOLVED')", name="ck_m43_alert_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m43_alert_event_hash"),
        UniqueConstraint("event_id", name="uq_m43_alert_event_id"),
        UniqueConstraint("alert_db_id", "sequence", name="uq_m43_alert_event_sequence"),
        Index("ix_m43_alert_event_time", "alert_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    alert_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_operational_alerts.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPreproductionCertification(Base):
    __tablename__ = "canonical_parser_preproduction_certifications"
    __table_args__ = (
        CheckConstraint("scope = 'M44_PREPRODUCTION_CERTIFICATION'", name="ck_m44_certification_scope"),
        CheckConstraint("environment = 'PREPRODUCTION'", name="ck_m44_certification_environment"),
        CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED')", name="ck_m44_certification_status"),
        CheckConstraint("full_test_count >= 0 AND full_test_failures >= 0", name="ck_m44_certification_test_counts"),
        CheckConstraint("latest_event_sequence >= 1", name="ck_m44_certification_event_sequence"),
        CheckConstraint("length(certification_key) = 64 AND length(test_evidence_hash) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m44_certification_hashes"),
        UniqueConstraint("certification_id", name="uq_m44_certification_id"),
        UniqueConstraint("certification_key", name="uq_m44_certification_key"),
        Index("ix_m44_certification_status_expiry", "status", "expires_at"),
        Index("ix_m44_certification_commit", "git_commit_sha"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    observability_snapshot_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_live_observability_snapshots.id", ondelete="RESTRICT"), nullable=False)
    observability_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    git_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    alembic_head: Mapped[str] = mapped_column(String(12), nullable=False)
    fastapi_version: Mapped[str] = mapped_column(String(32), nullable=False)
    clean_worktree_attested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    full_test_count: Mapped[int] = mapped_column(Integer, nullable=False)
    full_test_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    test_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    check_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    certified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPreproductionCertificationCheck(Base):
    __tablename__ = "canonical_parser_preproduction_certification_checks"
    __table_args__ = (
        CheckConstraint("status IN ('PASS','FAIL')", name="ck_m44_certification_check_status"),
        CheckConstraint("length(evidence_hash) = 64", name="ck_m44_certification_check_hash"),
        UniqueConstraint("check_id", name="uq_m44_certification_check_id"),
        UniqueConstraint("certification_db_id", "check_name", name="uq_m44_certification_check_name"),
        Index("ix_m44_certification_check_status", "certification_db_id", "status"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    check_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_preproduction_certifications.id", ondelete="CASCADE"), nullable=False)
    check_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    check_detail: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPreproductionCertificationEvent(Base):
    __tablename__ = "canonical_parser_preproduction_certification_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m44_certification_event_sequence"),
        CheckConstraint("event_type IN ('CERTIFIED','REVOKED','EXPIRED')", name="ck_m44_certification_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m44_certification_event_hash"),
        UniqueConstraint("event_id", name="uq_m44_certification_event_id"),
        UniqueConstraint("certification_db_id", "sequence", name="uq_m44_certification_event_sequence"),
        Index("ix_m44_certification_event_time", "certification_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    certification_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_preproduction_certifications.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPreproductionReleaseApproval(Base):
    __tablename__ = "canonical_parser_preproduction_release_approvals"
    __table_args__ = (
        CheckConstraint("scope = 'M44_SINGLE_USE_PREPRODUCTION_RELEASE_APPROVAL'", name="ck_m44_release_scope"),
        CheckConstraint("network = 'mainnet-beta'", name="ck_m44_release_network"),
        CheckConstraint("side IN ('BUY','SELL')", name="ck_m44_release_side"),
        CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','CONSUMED')", name="ck_m44_release_status"),
        CheckConstraint("max_budget_sol >= 0", name="ck_m44_release_budget"),
        CheckConstraint("latest_event_sequence >= 1", name="ck_m44_release_event_sequence"),
        CheckConstraint("length(release_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m44_release_hashes"),
        UniqueConstraint("release_id", name="uq_m44_release_id"),
        UniqueConstraint("release_key", name="uq_m44_release_key"),
        Index("ix_m44_release_wallet_status", "wallet_address", "status"),
        Index("ix_m44_release_status_expiry", "status", "expires_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    release_id: Mapped[str] = mapped_column(String(36), nullable=False)
    release_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    certification_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_preproduction_certifications.id", ondelete="RESTRICT"), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    network: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    max_budget_sol: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_submission_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalParserPreproductionReleaseApprovalEvent(Base):
    __tablename__ = "canonical_parser_preproduction_release_approval_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_m44_release_event_sequence"),
        CheckConstraint("event_type IN ('ISSUED','REVOKED','EXPIRED','CONSUMED')", name="ck_m44_release_event_type"),
        CheckConstraint("length(event_hash) = 64", name="ck_m44_release_event_hash"),
        UniqueConstraint("event_id", name="uq_m44_release_event_id"),
        UniqueConstraint("release_db_id", "sequence", name="uq_m44_release_event_sequence"),
        Index("ix_m44_release_event_time", "release_db_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(_PRIMARY_KEY_TYPE, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    release_db_id: Mapped[int] = mapped_column(ForeignKey("canonical_parser_preproduction_release_approvals.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
