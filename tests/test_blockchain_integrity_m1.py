from __future__ import annotations

import importlib.util
import socket
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.database.base import Base
from backend.app.models.blockchain_integrity import (
    NormalizationRun,
    RawBlockchainEvent,
)
from backend.app.services.blockchain_integrity_service import (
    MAX_ERROR_MESSAGE_LENGTH,
    calculate_payload_hash,
    canonicalize_payload,
    complete_normalization_run,
    create_normalization_run,
    fail_normalization_run,
    get_events_for_reprocessing,
    get_events_with_outdated_parser,
    get_unnormalized_events,
    register_raw_event,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            RawBlockchainEvent.__table__,
            NormalizationRun.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _register(
    db: Session,
    *,
    signature: str = "sig-001",
    payload: dict | None = None,
    observed_at: datetime | None = None,
):
    return register_raw_event(
        db,
        provider="Helius",
        chain="Solana",
        network="mainnet-beta",
        event_type="swap",
        transaction_signature=signature,
        slot=123,
        observed_wallet="Wallet111",
        commitment="confirmed",
        payload=payload or {"signature": signature, "type": "SWAP"},
        event_metadata={"source": "milestone-test"},
        observed_at=observed_at,
    )


def test_models_are_registered_and_exported():
    assert models.RawBlockchainEvent is RawBlockchainEvent
    assert models.NormalizationRun is NormalizationRun
    assert "raw_blockchain_events" in Base.metadata.tables
    assert "normalization_runs" in Base.metadata.tables


def test_canonicalization_is_deterministic():
    first = {"z": 3, "nested": {"b": 2, "a": 1}, "items": [2, 1]}
    second = {"items": [2, 1], "nested": {"a": 1, "b": 2}, "z": 3}

    assert canonicalize_payload(first) == canonicalize_payload(second)
    assert canonicalize_payload(first) == (
        '{"items":[2,1],"nested":{"a":1,"b":2},"z":3}'
    )


def test_hash_is_equal_when_json_key_order_changes():
    assert calculate_payload_hash({"b": 2, "a": 1}) == calculate_payload_hash(
        {"a": 1, "b": 2}
    )


def test_hash_changes_for_semantically_different_payload():
    assert calculate_payload_hash({"amount": 1}) != calculate_payload_hash(
        {"amount": 2}
    )


def test_payload_with_secret_field_is_rejected_before_hashing():
    with pytest.raises(ValueError, match="campo sensibile"):
        calculate_payload_hash({"signature": "sig", "api_key": "secret-value"})


def test_first_raw_event_insert(db: Session):
    event, created = _register(db)
    db.commit()

    assert created is True
    assert event.id is not None
    assert event.provider == "helius"
    assert event.chain == "solana"
    assert event.event_type == "SWAP"
    assert event.observation_count == 1
    assert len(event.payload_hash) == 64
    assert len(event.deduplication_key) == 64


def test_deduplication_increments_observation_and_preserves_payload(db: Session):
    first_time = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    second_time = first_time + timedelta(minutes=5)
    original_payload = {"signature": "sig-001", "meta": {"b": 2, "a": 1}}

    first, created_first = _register(
        db,
        payload=original_payload,
        observed_at=first_time,
    )
    db.commit()

    second, created_second = _register(
        db,
        payload={"meta": {"a": 1, "b": 2}, "signature": "sig-001"},
        observed_at=second_time,
    )
    db.commit()

    assert created_first is True
    assert created_second is False
    assert second.id == first.id
    assert second.observation_count == 2
    assert _as_utc(second.last_seen_at) == second_time
    assert _as_utc(second.first_seen_at) == first_time
    assert second.raw_payload == original_payload
    assert db.query(RawBlockchainEvent).count() == 1


def test_older_repeat_does_not_move_last_seen_backwards(db: Session):
    latest = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    older = latest - timedelta(hours=1)
    event, _ = _register(db, observed_at=latest)
    db.commit()

    repeated, created = _register(db, observed_at=older)
    db.commit()

    assert created is False
    assert repeated.id == event.id
    assert repeated.observation_count == 2
    assert _as_utc(repeated.last_seen_at) == latest
    assert _as_utc(repeated.first_seen_at) == latest


def test_database_unique_constraint_rejects_duplicate_key(db: Session):
    event, _ = _register(db)
    db.commit()

    duplicate = RawBlockchainEvent(
        provider=event.provider,
        chain=event.chain,
        network=event.network,
        event_type=event.event_type,
        transaction_signature=event.transaction_signature,
        slot=event.slot,
        observed_wallet=event.observed_wallet,
        commitment=event.commitment,
        raw_payload={"different": "stored value does not bypass identity"},
        payload_hash="a" * 64,
        deduplication_key=event.deduplication_key,
        event_metadata={},
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        observation_count=1,
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_parser_provenance_is_persisted(db: Session):
    event, _ = _register(db)
    db.commit()

    run = create_normalization_run(
        db,
        raw_event_id=event.id,
        parser_name="helius_swap_parser",
        parser_version="1.0.0",
        technical_metadata={
            "worker": "normalizer-1",
            "api_key": "must-not-be-stored",
        },
    )
    db.commit()

    assert run.raw_event_id == event.id
    assert run.parser_name == "helius_swap_parser"
    assert run.parser_version == "1.0.0"
    assert run.status == "RUNNING"
    assert run.started_at is not None
    assert run.technical_metadata["api_key"] == "[REDACTED]"


def test_normalization_run_can_be_completed(db: Session):
    event, _ = _register(db)
    db.commit()
    run = create_normalization_run(
        db,
        raw_event_id=event.id,
        parser_name="helius_swap_parser",
        parser_version="1.0.0",
    )

    completed = complete_normalization_run(
        db,
        run,
        produced_event_count=1,
        produced_trade_count=2,
        warnings=["minor warning"],
    )
    db.commit()

    assert completed.status == "COMPLETED"
    assert completed.completed_at is not None
    assert completed.produced_event_count == 1
    assert completed.produced_trade_count == 2
    assert completed.warnings == ["minor warning"]
    assert completed.error_message is None


def test_normalization_failure_sanitizes_and_limits_error(db: Session):
    event, _ = _register(db)
    db.commit()
    run = create_normalization_run(
        db,
        raw_event_id=event.id,
        parser_name="helius_swap_parser",
        parser_version="1.0.0",
    )
    secret = "s" * 3000

    failed = fail_normalization_run(
        db,
        run,
        "request failed api-key=" + secret + " " + ("x" * 3000),
    )
    db.commit()

    assert failed.status == "FAILED"
    assert failed.completed_at is not None
    assert "s" * 100 not in failed.error_message
    assert "[REDACTED]" in failed.error_message
    assert len(failed.error_message) <= MAX_ERROR_MESSAGE_LENGTH


def test_get_unnormalized_events_returns_only_unprocessed(db: Session):
    unprocessed, _ = _register(db, signature="sig-unprocessed")
    processed, _ = _register(db, signature="sig-processed")
    db.commit()
    run = create_normalization_run(
        db,
        raw_event_id=processed.id,
        parser_name="helius_swap_parser",
        parser_version="1.0.0",
    )
    complete_normalization_run(db, run)
    db.commit()

    result = get_unnormalized_events(
        db,
        parser_name="helius_swap_parser",
    )

    assert [event.id for event in result] == [unprocessed.id]


def test_get_outdated_parser_events_excludes_current_version(db: Session):
    outdated, _ = _register(db, signature="sig-old")
    current, _ = _register(db, signature="sig-current")
    never, _ = _register(db, signature="sig-never")
    db.commit()

    old_run = create_normalization_run(
        db,
        raw_event_id=outdated.id,
        parser_name="helius_swap_parser",
        parser_version="1.0.0",
    )
    complete_normalization_run(db, old_run)
    current_run = create_normalization_run(
        db,
        raw_event_id=current.id,
        parser_name="helius_swap_parser",
        parser_version="2.0.0",
    )
    complete_normalization_run(db, current_run)
    db.commit()

    result = get_events_with_outdated_parser(
        db,
        parser_name="helius_swap_parser",
        current_parser_version="2.0.0",
    )

    assert [event.id for event in result] == [outdated.id]
    assert never.id not in {event.id for event in result}


def test_reprocessing_selects_never_failed_and_outdated(db: Session):
    never, _ = _register(db, signature="sig-never")
    failed_event, _ = _register(db, signature="sig-failed")
    outdated, _ = _register(db, signature="sig-outdated")
    current, _ = _register(db, signature="sig-current")
    db.commit()

    failed_run = create_normalization_run(
        db,
        raw_event_id=failed_event.id,
        parser_name="parser",
        parser_version="2",
    )
    fail_normalization_run(db, failed_run, "failed")
    old_run = create_normalization_run(
        db,
        raw_event_id=outdated.id,
        parser_name="parser",
        parser_version="1",
    )
    complete_normalization_run(db, old_run)
    current_run = create_normalization_run(
        db,
        raw_event_id=current.id,
        parser_name="parser",
        parser_version="2",
    )
    complete_normalization_run(db, current_run)
    db.commit()

    result = get_events_for_reprocessing(
        db,
        parser_name="parser",
        current_parser_version="2",
    )

    assert {event.id for event in result} == {
        never.id,
        failed_event.id,
        outdated.id,
    }


def test_replay_filters_provider_signature_wallet_and_time(db: Session):
    start = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
    wanted, _ = _register(db, signature="sig-filter", observed_at=start)
    _register(
        db,
        signature="sig-outside",
        observed_at=start - timedelta(days=1),
    )
    db.commit()

    result = get_unnormalized_events(
        db,
        provider="HELIUS",
        transaction_signature="sig-filter",
        observed_wallet="Wallet111",
        observed_from=start - timedelta(minutes=1),
        observed_to=start + timedelta(minutes=1),
    )

    assert [event.id for event in result] == [wanted.id]


def test_new_service_performs_no_external_requests(db: Session, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external network request attempted")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    event, created = _register(db, signature="sig-offline")
    run = create_normalization_run(
        db,
        raw_event_id=event.id,
        parser_name="offline_parser",
        parser_version="1",
    )
    complete_normalization_run(db, run)
    db.commit()

    assert created is True
    assert run.status == "COMPLETED"


def test_named_constraints_and_indexes_are_present():
    raw_table = Base.metadata.tables["raw_blockchain_events"]
    run_table = Base.metadata.tables["normalization_runs"]

    raw_constraints = {item.name for item in raw_table.constraints}
    run_constraints = {item.name for item in run_table.constraints}
    raw_indexes = {item.name for item in raw_table.indexes}
    run_indexes = {item.name for item in run_table.indexes}

    assert "uq_raw_blockchain_events_deduplication_key" in raw_constraints
    assert "ck_raw_blockchain_events_observation_count_positive" in raw_constraints
    assert "uq_normalization_runs_run_id" in run_constraints
    assert "ck_normalization_runs_status" in run_constraints
    assert "ix_raw_blockchain_events_provider_chain_network" in raw_indexes
    assert "ix_normalization_runs_raw_parser_version_status" in run_indexes


def test_migration_upgrade_downgrade_upgrade_roundtrip():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "b1c9e4f7a2d6_add_live_grade_integrity_foundation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "smartmoney_m1_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)
        migration.upgrade()
        assert {
            "raw_blockchain_events",
            "normalization_runs",
        }.issubset(inspect(connection).get_table_names())

        migration.downgrade()
        assert "raw_blockchain_events" not in inspect(connection).get_table_names()
        assert "normalization_runs" not in inspect(connection).get_table_names()

        migration.upgrade()
        assert {
            "raw_blockchain_events",
            "normalization_runs",
        }.issubset(inspect(connection).get_table_names())

    engine.dispose()
