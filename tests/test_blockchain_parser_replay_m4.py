from __future__ import annotations

import ast
import importlib.util
import socket
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    NormalizationArtifact,
    NormalizationReplayBatch,
    NormalizationRun,
    RawBlockchainEvent,
)
from backend.app.services.blockchain_integrity_service import (
    complete_normalization_run,
    create_normalization_run,
    register_raw_event,
)
from backend.app.services.blockchain_normalization_replay_service import (
    REPLAY_CONFIRMATION,
    NormalizationReplayError,
    execute_normalization_replay,
    get_normalization_replay_batch,
    get_parser_registry_status,
    preview_normalization_replay,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    NormalizedArtifactPayload,
    ParserDefinition,
    ParserRegistry,
    ParserRegistryError,
    parse_raw_event_envelope,
    validate_parser_artifacts,
)


AUTOMATION_KEY = "a" * 32
M4_TABLES = [
    RawBlockchainEvent.__table__,
    NormalizationRun.__table__,
    NormalizationReplayBatch.__table__,
    NormalizationArtifact.__table__,
]


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=M4_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def safe_m4_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS",
        "raw_event_envelope",
    )
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_MAX_BATCH_SIZE", 100)
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", False)
    monkeypatch.setattr(settings, "RUN_LIVE_STREAM_WORKER", False)
    monkeypatch.setattr(settings, "RUN_LIVE_POSITION_MONITOR", False)


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test-helius-api-key",
    }
    values.update(overrides)
    return values


def _insert_event(
    db: Session,
    *,
    signature: str,
    provider: str = "helius",
    event_type: str = "WALLET_HISTORY_RESPONSE",
    payload: dict | None = None,
):
    event, created = register_raw_event(
        db,
        provider=provider,
        chain="solana",
        network="mainnet-beta",
        event_type=event_type,
        transaction_signature=signature,
        observed_wallet="WalletM4",
        payload=payload or {"signature": signature, "type": "SWAP"},
        observed_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    assert created is True
    db.flush()
    return event


def _client(db_factory):
    def override_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m4_models_are_registered_and_exported():
    assert models.NormalizationArtifact is NormalizationArtifact
    assert models.NormalizationReplayBatch is NormalizationReplayBatch
    assert "normalization_artifacts" in Base.metadata.tables
    assert "normalization_replay_batches" in Base.metadata.tables


def test_m4_configuration_defaults_are_safe():
    configured = Settings(_env_file=None, **_settings_values())

    assert configured.RAW_BLOCKCHAIN_REPLAY_ENABLED is False
    assert configured.raw_blockchain_replay_allowed_parsers == [
        "raw_event_envelope"
    ]
    assert configured.RAW_BLOCKCHAIN_REPLAY_MAX_BATCH_SIZE == 100


def test_enabled_replay_requires_allowed_parser():
    with pytest.raises(ValidationError, match="almeno un parser"):
        Settings(
            _env_file=None,
            **_settings_values(
                RAW_BLOCKCHAIN_REPLAY_ENABLED=True,
                RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS="",
            ),
        )


def test_default_parser_registry_is_versioned_and_safe():
    status = get_parser_registry_status()

    assert status["replay_enabled"] is False
    assert len(status["registry_manifest_hash"]) == 64
    assert status["parsers"][0]["name"] == "raw_event_envelope"
    assert status["parsers"][0]["version"] == "1.0.0"
    assert status["parsers"][0]["performs_external_requests"] is False
    assert status["parsers"][0]["writes_trades"] is False
    assert status["operational_guards"]["automatic_execution"] is False


def test_registry_rejects_duplicate_name_and_version():
    registry = ParserRegistry()
    definition = ParserDefinition(
        name="test_parser",
        version="1.0.0",
        description="test",
        supported_providers=frozenset({"helius"}),
        supported_event_types=frozenset({"RPC_RESPONSE"}),
        output_schema_version="test/1",
        parse=parse_raw_event_envelope,
    )
    registry.register(definition)

    with pytest.raises(ParserRegistryError) as error:
        registry.register(definition)

    assert error.value.code == "PARSER_VERSION_ALREADY_REGISTERED"


def test_registry_rejects_network_or_trade_writing_parser():
    with pytest.raises(ParserRegistryError, match="richieste esterne"):
        ParserRegistry().register(
            ParserDefinition(
                name="network_parser",
                version="1.0.0",
                description="unsafe",
                supported_providers=frozenset({"helius"}),
                supported_event_types=frozenset({"RPC_RESPONSE"}),
                output_schema_version="unsafe/1",
                parse=parse_raw_event_envelope,
                performs_external_requests=True,
            )
        )

    with pytest.raises(ParserRegistryError, match="Trade"):
        ParserRegistry().register(
            ParserDefinition(
                name="trade_parser",
                version="1.0.0",
                description="unsafe",
                supported_providers=frozenset({"helius"}),
                supported_event_types=frozenset({"RPC_RESPONSE"}),
                output_schema_version="unsafe/1",
                parse=parse_raw_event_envelope,
                writes_trades=True,
            )
        )


def test_parser_compatibility_is_explicit(db_factory):
    definition = DEFAULT_PARSER_REGISTRY.get("raw_event_envelope", "1.0.0")
    with db_factory() as db:
        supported = _insert_event(db, signature="supported")
        unsupported = _insert_event(
            db,
            signature="unsupported",
            provider="other_provider",
        )

    assert definition.supports(supported) is True
    assert definition.supports(unsupported) is False


def test_builtin_parser_output_is_deterministic(db_factory):
    definition = DEFAULT_PARSER_REGISTRY.get("raw_event_envelope", "1.0.0")
    with db_factory() as db:
        first = _insert_event(
            db,
            signature="deterministic-a",
            payload={"b": 2, "a": 1},
        )
        second = _insert_event(
            db,
            signature="deterministic-a-copy",
            payload={"a": 1, "b": 2},
        )
        second.transaction_signature = first.transaction_signature
        first_artifacts = validate_parser_artifacts(
            definition,
            definition.parse(first),
        )
        second_artifacts = validate_parser_artifacts(
            definition,
            definition.parse(second),
        )

    assert first_artifacts[0]["payload_hash"] == second_artifacts[0][
        "payload_hash"
    ]


def test_preview_selects_unnormalized_without_database_writes(db_factory):
    with db_factory() as db:
        event = _insert_event(db, signature="preview")
        db.commit()
        before_runs = db.query(NormalizationRun).count()
        before_batches = db.query(NormalizationReplayBatch).count()

        preview = preview_normalization_replay(
            db,
            parser_name="raw_event_envelope",
            parser_version="1.0.0",
            selection_mode="UNNORMALIZED",
        )

        assert preview["candidate_ids"] == [event.id]
        assert preview["writes_database"] is False
        assert preview["external_requests"] == 0
        assert db.query(NormalizationRun).count() == before_runs
        assert db.query(NormalizationReplayBatch).count() == before_batches


def test_preview_filters_by_event_type_and_compatibility(db_factory):
    with db_factory() as db:
        selected = _insert_event(db, signature="selected")
        _insert_event(
            db,
            signature="different-type",
            event_type="ENHANCED_TRANSACTION_RESPONSE",
        )
        _insert_event(
            db,
            signature="unsupported-provider",
            provider="unsupported",
        )
        db.commit()

        preview = preview_normalization_replay(
            db,
            parser_name="raw_event_envelope",
            parser_version="1.0.0",
            selection_mode="UNNORMALIZED",
            event_type="WALLET_HISTORY_RESPONSE",
        )

    assert preview["candidate_ids"] == [selected.id]


def test_outdated_preview_selects_old_version_only(db_factory):
    with db_factory() as db:
        event = _insert_event(db, signature="outdated")
        run = create_normalization_run(
            db,
            raw_event_id=event.id,
            parser_name="raw_event_envelope",
            parser_version="0.9.0",
        )
        complete_normalization_run(db, run, produced_event_count=1)
        db.commit()

        preview = preview_normalization_replay(
            db,
            parser_name="raw_event_envelope",
            parser_version="1.0.0",
            selection_mode="OUTDATED",
        )

    assert preview["candidate_ids"] == [event.id]


def test_execute_is_disabled_by_default(db_factory):
    with db_factory() as db:
        _insert_event(db, signature="disabled")
        db.commit()
        with pytest.raises(NormalizationReplayError) as error:
            execute_normalization_replay(
                db,
                parser_name="raw_event_envelope",
                parser_version="1.0.0",
                selection_mode="REPROCESS",
                confirmation=REPLAY_CONFIRMATION,
            )

    assert error.value.code == "REPLAY_DISABLED"


def test_execute_requires_exact_confirmation(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", True)
    with db_factory() as db:
        _insert_event(db, signature="confirmation")
        db.commit()
        with pytest.raises(NormalizationReplayError) as error:
            execute_normalization_replay(
                db,
                parser_name="raw_event_envelope",
                parser_version="1.0.0",
                selection_mode="REPROCESS",
                confirmation="yes",
            )

    assert error.value.code == "REPLAY_CONFIRMATION_REQUIRED"


def test_execute_persists_batch_run_and_artifact(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", True)
    with db_factory() as db:
        event = _insert_event(db, signature="execute")
        db.commit()

        result = execute_normalization_replay(
            db,
            parser_name="raw_event_envelope",
            parser_version="1.0.0",
            selection_mode="REPROCESS",
            confirmation=REPLAY_CONFIRMATION,
        )

        batch = db.query(NormalizationReplayBatch).one()
        run = db.query(NormalizationRun).one()
        artifact = db.query(NormalizationArtifact).one()

    assert result["status"] == "COMPLETED"
    assert result["completed_count"] == 1
    assert result["failed_count"] == 0
    assert batch.replay_id == result["replay_id"]
    assert run.raw_event_id == event.id
    assert run.status == "COMPLETED"
    assert run.produced_event_count == 1
    assert run.produced_trade_count == 0
    assert artifact.raw_event_id == event.id
    assert artifact.normalization_run_id == run.id
    assert artifact.artifact_type == "RAW_EVENT_ENVELOPE"
    assert artifact.parser_version == "1.0.0"
    assert len(artifact.payload_hash) == 64
    assert artifact.payload["raw_payload_hash"] == event.payload_hash


def test_current_version_is_not_replayed_twice(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", True)
    with db_factory() as db:
        _insert_event(db, signature="once")
        db.commit()
        first = execute_normalization_replay(
            db,
            parser_name="raw_event_envelope",
            parser_version="1.0.0",
            selection_mode="REPROCESS",
            confirmation=REPLAY_CONFIRMATION,
        )
        second = execute_normalization_replay(
            db,
            parser_name="raw_event_envelope",
            parser_version="1.0.0",
            selection_mode="REPROCESS",
            confirmation=REPLAY_CONFIRMATION,
        )

        assert first["completed_count"] == 1
        assert second["selected_count"] == 0
        assert db.query(NormalizationArtifact).count() == 1
        assert db.query(NormalizationRun).count() == 1


def test_artifact_unique_constraint_blocks_duplicate_current_output(db_factory):
    definition = DEFAULT_PARSER_REGISTRY.get("raw_event_envelope", "1.0.0")
    with db_factory() as db:
        event = _insert_event(db, signature="unique")
        run = create_normalization_run(
            db,
            raw_event_id=event.id,
            parser_name=definition.name,
            parser_version=definition.version,
        )
        db.flush()
        artifact_values = {
            "normalization_run_id": run.id,
            "raw_event_id": event.id,
            "parser_name": definition.name,
            "parser_version": definition.version,
            "parser_implementation_hash": definition.implementation_hash,
            "artifact_type": "RAW_EVENT_ENVELOPE",
            "artifact_index": 0,
            "schema_version": "raw-event-envelope/1",
            "payload": {"ok": True},
            "payload_hash": "a" * 64,
            "artifact_metadata": {},
        }
        db.add(NormalizationArtifact(**artifact_values))
        db.flush()
        db.add(NormalizationArtifact(**artifact_values))
        with pytest.raises(IntegrityError):
            db.flush()


def test_parser_failure_is_audited_as_failed_batch(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", True)

    def failing_parser(_event):
        raise RuntimeError("api_key=secret must be sanitized")

    registry = ParserRegistry()
    registry.register(
        ParserDefinition(
            name="failing_parser",
            version="1.0.0",
            description="failure test",
            supported_providers=frozenset({"helius"}),
            supported_event_types=frozenset({"WALLET_HISTORY_RESPONSE"}),
            output_schema_version="failure/1",
            parse=failing_parser,
        )
    )
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS",
        "failing_parser",
    )

    with db_factory() as db:
        _insert_event(db, signature="failure")
        db.commit()
        result = execute_normalization_replay(
            db,
            parser_name="failing_parser",
            parser_version="1.0.0",
            selection_mode="REPROCESS",
            confirmation=REPLAY_CONFIRMATION,
            registry=registry,
        )
        run = db.query(NormalizationRun).one()

    assert result["status"] == "FAILED"
    assert result["failed_count"] == 1
    assert run.status == "FAILED"
    assert "secret" not in run.error_message
    assert "[REDACTED]" in run.error_message


def test_replay_batch_can_be_retrieved(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", True)
    with db_factory() as db:
        _insert_event(db, signature="retrieve")
        db.commit()
        created = execute_normalization_replay(
            db,
            parser_name="raw_event_envelope",
            parser_version="1.0.0",
            selection_mode="REPROCESS",
            confirmation=REPLAY_CONFIRMATION,
        )
        fetched = get_normalization_replay_batch(db, created["replay_id"])

    assert fetched == created


def test_services_have_no_network_clients_or_trade_imports():
    service_paths = [
        Path("backend/app/services/blockchain_parser_registry_service.py"),
        Path("backend/app/services/blockchain_normalization_replay_service.py"),
    ]
    forbidden_imports = {
        "httpx",
        "requests",
        "aiohttp",
        "urllib3",
        "websockets",
    }
    for path in service_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        assert not (imports & forbidden_imports)
        source = path.read_text(encoding="utf-8")
        assert "backend.app.models.trade" not in source.lower()
        assert "Trade(" not in source


def test_replay_execution_performs_no_external_requests(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", True)

    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("Nessuna rete consentita durante il replay.")

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)
    with db_factory() as db:
        _insert_event(db, signature="no-network")
        db.commit()
        result = execute_normalization_replay(
            db,
            parser_name="raw_event_envelope",
            parser_version="1.0.0",
            selection_mode="REPROCESS",
            confirmation=REPLAY_CONFIRMATION,
        )

    assert result["completed_count"] == 1
    assert result["technical_metadata"]["external_requests"] == 0


def test_m4_api_routes_are_protected_and_registered_once(db_factory):
    route_counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            route_counts[(method, getattr(route, "path", ""))] += 1

    expected = {
        ("GET", "/integrity/parsers"),
        ("GET", "/integrity/replay/preview"),
        ("POST", "/integrity/replay/execute"),
        ("GET", "/integrity/replay/batches/{replay_id}"),
    }
    for route_key in expected:
        assert route_counts[route_key] == 1

    client = _client(db_factory)
    try:
        assert client.get("/integrity/parsers").status_code == 401
        response = client.get(
            "/integrity/parsers",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["replay_enabled"] is False

        execute_response = client.post(
            "/integrity/replay/execute",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={
                "parser_name": "raw_event_envelope",
                "parser_version": "1.0.0",
                "selection_mode": "REPROCESS",
                "confirmation": REPLAY_CONFIRMATION,
            },
        )
        assert execute_response.status_code == 409
        assert execute_response.json()["detail"]["code"] == "REPLAY_DISABLED"
    finally:
        app.dependency_overrides.clear()


def test_m4_migration_upgrade_and_downgrade_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            RawBlockchainEvent.__table__,
            NormalizationRun.__table__,
        ],
    )
    migration_path = Path(
        "alembic/versions/c3a7f9e2b4d1_add_versioned_parser_replay.py"
    )
    spec = importlib.util.spec_from_file_location("m4_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = module.op
        module.op = operations
        try:
            module.upgrade()
            tables = set(inspect(connection).get_table_names())
            assert "normalization_artifacts" in tables
            assert "normalization_replay_batches" in tables
            module.downgrade()
            tables = set(inspect(connection).get_table_names())
            assert "normalization_artifacts" not in tables
            assert "normalization_replay_batches" not in tables
            module.upgrade()
            tables = set(inspect(connection).get_table_names())
            assert "normalization_artifacts" in tables
            assert "normalization_replay_batches" in tables
        finally:
            module.op = original_op
    engine.dispose()
