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
    CanonicalNormalizedEvent,
    CanonicalShadowValidationBatch,
    CanonicalShadowValidationResult,
    NormalizationArtifact,
    NormalizationReplayBatch,
    NormalizationRun,
    RawBlockchainEvent,
)
from backend.app.models.trade import Trade
from backend.app.services.blockchain_canonical_shadow_service import (
    CANONICAL_MATERIALIZE_CONFIRMATION,
    SHADOW_VALIDATION_CONFIRMATION,
    CanonicalShadowError,
    execute_canonical_materialization,
    execute_shadow_validation,
    get_canonical_shadow_status,
    get_shadow_validation_batch,
    preview_canonical_materialization,
    preview_shadow_validation,
)
from backend.app.services.blockchain_integrity_service import register_raw_event
from backend.app.services.blockchain_normalization_replay_service import (
    REPLAY_CONFIRMATION,
    execute_normalization_replay,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    validate_parser_artifacts,
)


AUTOMATION_KEY = "a" * 32
WALLET = "WalletM5"
TOKEN = "TokenMintM5"
POOL = "PoolM5"
M5_TABLES = [
    RawBlockchainEvent.__table__,
    NormalizationRun.__table__,
    NormalizationReplayBatch.__table__,
    NormalizationArtifact.__table__,
    Trade.__table__,
    CanonicalNormalizedEvent.__table__,
    CanonicalShadowValidationBatch.__table__,
    CanonicalShadowValidationResult.__table__,
]


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=M5_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def safe_m5_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS",
        "raw_event_envelope",
    )
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_MAX_BATCH_SIZE", 100)
    monkeypatch.setattr(settings, "CANONICAL_NORMALIZATION_ENABLED", False)
    monkeypatch.setattr(settings, "CANONICAL_NORMALIZATION_MAX_BATCH_SIZE", 100)
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "CANONICAL_SHADOW_VALIDATION_MAX_BATCH_SIZE",
        200,
    )
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_AMOUNT_TOLERANCE", 1e-9)
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", False)
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED", False)
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


def _swap(
    signature: str,
    *,
    side: str = "BUY",
    token_amount: float = 250.0,
    sol_amount: float = 0.125,
    source: str = "JUPITER",
) -> dict:
    if side == "BUY":
        native_input = {"account": WALLET, "amount": int(sol_amount * 1e9)}
        native_output = None
        token_inputs = []
        token_outputs = [
            {
                "userAccount": WALLET,
                "mint": TOKEN,
                "rawTokenAmount": {
                    "tokenAmount": str(int(token_amount * 1e6)),
                    "decimals": 6,
                },
            }
        ]
    elif side == "SELL":
        native_input = None
        native_output = {"account": WALLET, "amount": int(sol_amount * 1e9)}
        token_inputs = [
            {
                "userAccount": WALLET,
                "mint": TOKEN,
                "rawTokenAmount": {
                    "tokenAmount": str(int(token_amount * 1e6)),
                    "decimals": 6,
                },
            }
        ]
        token_outputs = []
    else:
        native_input = None
        native_output = None
        token_inputs = []
        token_outputs = []
    return {
        "type": "SWAP",
        "signature": signature,
        "timestamp": 1785000000,
        "source": source,
        "fee": 5000,
        "feePayer": WALLET,
        "transactionError": None,
        "nativeTransfers": [],
        "tokenTransfers": [],
        "accountData": [],
        "events": {
            "swap": {
                "nativeInput": native_input,
                "nativeOutput": native_output,
                "tokenInputs": token_inputs,
                "tokenOutputs": token_outputs,
            }
        },
    }


def _insert_raw(db: Session, signature: str, *, payload: object | None = None):
    event, created = register_raw_event(
        db,
        provider="helius",
        chain="solana",
        network="mainnet-beta",
        event_type="WALLET_HISTORY_RESPONSE",
        transaction_signature=signature,
        observed_wallet=WALLET,
        payload=payload if payload is not None else [_swap(signature)],
        observed_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    assert created is True
    db.flush()
    return event


def _run_canonical_replay(monkeypatch, db: Session, signature: str, **swap_kwargs):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS",
        "swap_canonical_event",
    )
    event = _insert_raw(db, signature, payload=[_swap(signature, **swap_kwargs)])
    db.commit()
    result = execute_normalization_replay(
        db,
        parser_name="swap_canonical_event",
        parser_version="1.0.0",
        selection_mode="REPROCESS",
        confirmation=REPLAY_CONFIRMATION,
        transaction_signature=signature,
    )
    assert result["completed_count"] == 1
    return event


def _materialize(monkeypatch, db: Session, signature: str):
    monkeypatch.setattr(settings, "CANONICAL_NORMALIZATION_ENABLED", True)
    result = execute_canonical_materialization(
        db,
        confirmation=CANONICAL_MATERIALIZE_CONFIRMATION,
        transaction_signature=signature,
    )
    assert result["created_count"] == 1
    return db.query(CanonicalNormalizedEvent).filter_by(
        transaction_signature=signature
    ).one()


def _client(db_factory):
    def override_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m5_models_are_registered_and_exported():
    assert models.CanonicalNormalizedEvent is CanonicalNormalizedEvent
    assert models.CanonicalShadowValidationBatch is CanonicalShadowValidationBatch
    assert models.CanonicalShadowValidationResult is CanonicalShadowValidationResult
    assert "canonical_normalized_events" in Base.metadata.tables
    assert "canonical_shadow_validation_batches" in Base.metadata.tables
    assert "canonical_shadow_validation_results" in Base.metadata.tables


def test_m5_configuration_defaults_are_safe():
    configured = Settings(_env_file=None, **_settings_values())
    assert configured.CANONICAL_NORMALIZATION_ENABLED is False
    assert configured.CANONICAL_NORMALIZATION_MAX_BATCH_SIZE == 100
    assert configured.CANONICAL_SHADOW_VALIDATION_ENABLED is False
    assert configured.CANONICAL_SHADOW_VALIDATION_MAX_BATCH_SIZE == 200
    assert configured.CANONICAL_SHADOW_AMOUNT_TOLERANCE == 1e-9


def test_canonical_parser_is_registered_versioned_and_safe():
    definition = DEFAULT_PARSER_REGISTRY.get("swap_canonical_event", "1.0.0")
    assert definition.output_schema_version == "canonical-swap/1"
    assert definition.performs_external_requests is False
    assert definition.writes_trades is False
    assert len(definition.implementation_hash) == 64


def test_canonical_parser_is_deterministic_for_json_key_order(db_factory):
    definition = DEFAULT_PARSER_REGISTRY.get("swap_canonical_event", "1.0.0")
    first_payload = _swap("deterministic")
    second_payload = {key: first_payload[key] for key in reversed(first_payload)}
    with db_factory() as db:
        first = _insert_raw(db, "raw-a", payload=[first_payload])
        second = _insert_raw(db, "raw-b", payload=[second_payload])
        first_hash = validate_parser_artifacts(
            definition, definition.parse(first)
        )[0]["payload_hash"]
        second_hash = validate_parser_artifacts(
            definition, definition.parse(second)
        )[0]["payload_hash"]
    assert first_hash == second_hash


def test_canonical_parser_ignores_non_swap_payload(db_factory):
    definition = DEFAULT_PARSER_REGISTRY.get("swap_canonical_event", "1.0.0")
    with db_factory() as db:
        event = _insert_raw(
            db,
            "not-swap",
            payload=[{"type": "TRANSFER", "signature": "not-swap"}],
        )
        assert definition.parse(event) == []


def test_canonical_parser_quality_warns_for_unknown_side(db_factory):
    definition = DEFAULT_PARSER_REGISTRY.get("swap_canonical_event", "1.0.0")
    with db_factory() as db:
        event = _insert_raw(db, "unknown", payload=[_swap("unknown", side="UNKNOWN")])
        artifact = definition.parse(event)[0]
    assert artifact.payload["side"] == "UNKNOWN"
    assert artifact.payload["quality_status"] == "WARN"
    assert "UNKNOWN_SIDE" in artifact.payload["quality_flags"]


def test_materialization_preview_has_no_writes(monkeypatch, db_factory):
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "preview")
        before = db.query(CanonicalNormalizedEvent).count()
        preview = preview_canonical_materialization(db)
        after = db.query(CanonicalNormalizedEvent).count()
    assert preview["selected_count"] == 1
    assert preview["writes_database"] is False
    assert before == after == 0


def test_materialization_is_disabled_by_default(monkeypatch, db_factory):
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "disabled")
        with pytest.raises(CanonicalShadowError) as error:
            execute_canonical_materialization(
                db,
                confirmation=CANONICAL_MATERIALIZE_CONFIRMATION,
            )
    assert error.value.code == "CANONICAL_NORMALIZATION_DISABLED"


def test_materialization_requires_exact_confirmation(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "CANONICAL_NORMALIZATION_ENABLED", True)
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "confirmation")
        with pytest.raises(CanonicalShadowError) as error:
            execute_canonical_materialization(db, confirmation="yes")
    assert error.value.code == "CANONICAL_MATERIALIZE_CONFIRMATION_REQUIRED"


def test_materialization_persists_queryable_canonical_event(monkeypatch, db_factory):
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "materialized")
        event = _materialize(monkeypatch, db, "materialized")
    assert event.side == "BUY"
    assert event.observed_wallet == WALLET
    assert event.token_mint == TOKEN
    assert str(event.token_amount) == "250.000000000000000000"
    assert str(event.sol_amount) == "0.125000000000000000"
    assert event.quality_status == "PASS"
    assert len(event.canonical_event_key) == 64
    assert len(event.canonical_payload_hash) == 64


def test_materialization_is_idempotent(monkeypatch, db_factory):
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "idempotent")
        _materialize(monkeypatch, db, "idempotent")
        second = execute_canonical_materialization(
            db,
            confirmation=CANONICAL_MATERIALIZE_CONFIRMATION,
            transaction_signature="idempotent",
        )
        count = db.query(CanonicalNormalizedEvent).count()
    assert second["selected_count"] == 0
    assert count == 1


def test_canonical_artifact_unique_constraint(db_factory):
    with db_factory() as db:
        raw = _insert_raw(db, "unique")
        run = NormalizationRun(
            run_id="run-unique",
            raw_event_id=raw.id,
            parser_name="swap_canonical_event",
            parser_version="1.0.0",
            status="COMPLETED",
            produced_event_count=1,
            produced_trade_count=0,
            warnings=[],
            technical_metadata={},
        )
        db.add(run)
        db.flush()
        artifact = NormalizationArtifact(
            normalization_run_id=run.id,
            raw_event_id=raw.id,
            parser_name="swap_canonical_event",
            parser_version="1.0.0",
            parser_implementation_hash="a" * 64,
            artifact_type="CANONICAL_SWAP_EVENT",
            artifact_index=0,
            schema_version="canonical-swap/1",
            payload={"canonical_type": "SWAP"},
            payload_hash="b" * 64,
            artifact_metadata={},
        )
        db.add(artifact)
        db.flush()
        base = dict(
            canonical_event_key="c" * 64,
            normalization_artifact_id=artifact.id,
            normalization_run_id=run.id,
            raw_event_id=raw.id,
            parser_name="swap_canonical_event",
            parser_version="1.0.0",
            parser_implementation_hash="a" * 64,
            schema_version="canonical-swap/1",
            canonical_type="SWAP",
            side="UNKNOWN",
            success=True,
            quality_status="WARN",
            quality_flags=[],
            canonical_payload={},
            canonical_payload_hash="d" * 64,
            technical_metadata={},
        )
        db.add(CanonicalNormalizedEvent(canonical_event_id="one", **base))
        db.flush()
        db.add(CanonicalNormalizedEvent(canonical_event_id="two", **base))
        with pytest.raises(IntegrityError):
            db.flush()


def test_shadow_preview_has_no_writes(monkeypatch, db_factory):
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "shadow-preview")
        _materialize(monkeypatch, db, "shadow-preview")
        before = db.query(CanonicalShadowValidationBatch).count()
        preview = preview_shadow_validation(db)
        after = db.query(CanonicalShadowValidationBatch).count()
    assert preview["selected_count"] == 1
    assert before == after == 0
    assert preview["writes_trades"] is False


def test_shadow_validation_is_disabled_by_default(monkeypatch, db_factory):
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "shadow-disabled")
        _materialize(monkeypatch, db, "shadow-disabled")
        with pytest.raises(CanonicalShadowError) as error:
            execute_shadow_validation(
                db,
                confirmation=SHADOW_VALIDATION_CONFIRMATION,
            )
    assert error.value.code == "CANONICAL_SHADOW_VALIDATION_DISABLED"


def test_shadow_validation_requires_confirmation(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", True)
    with db_factory() as db:
        with pytest.raises(CanonicalShadowError) as error:
            execute_shadow_validation(db, confirmation="yes")
    assert error.value.code == "SHADOW_VALIDATION_CONFIRMATION_REQUIRED"


def test_shadow_validation_match(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", True)
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "match")
        canonical = _materialize(monkeypatch, db, "match")
        db.add(
            Trade(
                signature="match",
                wallet_address=WALLET,
                side="BUY",
                source="JUPITER",
                token_mint=TOKEN,
                token_amount=250.0,
                sol_amount=0.125,
                fee=5000,
                success=True,
                block_time=canonical.block_time,
            )
        )
        db.commit()
        result = execute_shadow_validation(
            db,
            confirmation=SHADOW_VALIDATION_CONFIRMATION,
            transaction_signature="match",
        )
        validation = db.query(CanonicalShadowValidationResult).one()
    assert result["match_count"] == 1
    assert validation.status == "MATCH"
    assert validation.mismatch_fields == []


def test_shadow_validation_detects_mismatch(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", True)
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "mismatch")
        canonical = _materialize(monkeypatch, db, "mismatch")
        db.add(
            Trade(
                signature="mismatch",
                wallet_address=WALLET,
                side="SELL",
                source="JUPITER",
                token_mint=TOKEN,
                token_amount=249.0,
                sol_amount=0.125,
                fee=5000,
                success=True,
                block_time=canonical.block_time,
            )
        )
        db.commit()
        result = execute_shadow_validation(
            db,
            confirmation=SHADOW_VALIDATION_CONFIRMATION,
            transaction_signature="mismatch",
        )
        validation = db.query(CanonicalShadowValidationResult).one()
    assert result["mismatch_count"] == 1
    assert validation.status == "MISMATCH"
    assert set(validation.mismatch_fields) == {"side", "token_amount"}


def test_shadow_validation_marks_missing_trade(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", True)
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "missing")
        _materialize(monkeypatch, db, "missing")
        result = execute_shadow_validation(
            db,
            confirmation=SHADOW_VALIDATION_CONFIRMATION,
            transaction_signature="missing",
        )
    assert result["missing_trade_count"] == 1


def test_shadow_validation_marks_unknown_as_not_comparable(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", True)
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "unknown-shadow", side="UNKNOWN")
        _materialize(monkeypatch, db, "unknown-shadow")
        result = execute_shadow_validation(
            db,
            confirmation=SHADOW_VALIDATION_CONFIRMATION,
            transaction_signature="unknown-shadow",
        )
    assert result["not_comparable_count"] == 1


def test_shadow_validation_never_modifies_trade(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", True)
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "immutable")
        canonical = _materialize(monkeypatch, db, "immutable")
        trade = Trade(
            signature="immutable",
            wallet_address=WALLET,
            side="SELL",
            source="ORIGINAL",
            token_mint=TOKEN,
            token_amount=1.0,
            sol_amount=2.0,
            fee=3.0,
            success=True,
            block_time=canonical.block_time,
        )
        db.add(trade)
        db.commit()
        before = (trade.side, trade.source, trade.token_amount, trade.sol_amount)
        before_count = db.query(Trade).count()
        execute_shadow_validation(
            db,
            confirmation=SHADOW_VALIDATION_CONFIRMATION,
            transaction_signature="immutable",
        )
        db.refresh(trade)
        after = (trade.side, trade.source, trade.token_amount, trade.sol_amount)
    assert before == after
    assert before_count == 1


def test_shadow_batch_can_be_retrieved(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", True)
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "batch")
        _materialize(monkeypatch, db, "batch")
        created = execute_shadow_validation(
            db,
            confirmation=SHADOW_VALIDATION_CONFIRMATION,
        )
        fetched = get_shadow_validation_batch(db, created["validation_id"])
    assert fetched["validation_id"] == created["validation_id"]
    assert fetched["result_counts"]["MISSING_TRADE"] == 1


def test_status_reports_safe_operational_guards(db_factory):
    with db_factory() as db:
        status = get_canonical_shadow_status(db)
    assert status["canonical_normalization_enabled"] is False
    assert status["shadow_validation_enabled"] is False
    assert status["operational_guards"]["external_requests"] == 0
    assert status["operational_guards"]["writes_trades"] is False


def test_m5_service_has_no_network_clients_or_trade_writes():
    path = Path("backend/app/services/blockchain_canonical_shadow_service.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not (imports & {"httpx", "requests", "aiohttp", "urllib3", "websockets"})
    source = path.read_text(encoding="utf-8")
    assert "db.add(Trade" not in source
    assert "Trade(**" not in source


def test_full_m5_pipeline_performs_no_external_requests(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", True)

    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("Nessuna rete consentita durante M5.")

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)
    with db_factory() as db:
        _run_canonical_replay(monkeypatch, db, "no-network")
        _materialize(monkeypatch, db, "no-network")
        result = execute_shadow_validation(
            db,
            confirmation=SHADOW_VALIDATION_CONFIRMATION,
        )
    assert result["missing_trade_count"] == 1
    assert result["technical_metadata"]["external_requests"] == 0


def test_m5_api_routes_are_protected_and_registered_once(db_factory):
    route_counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            route_counts[(method, getattr(route, "path", ""))] += 1
    expected = {
        ("GET", "/integrity/canonical/status"),
        ("GET", "/integrity/canonical/materialization/preview"),
        ("POST", "/integrity/canonical/materialization/execute"),
        ("GET", "/integrity/shadow-validation/preview"),
        ("POST", "/integrity/shadow-validation/execute"),
        ("GET", "/integrity/shadow-validation/batches/{validation_id}"),
    }
    for route_key in expected:
        assert route_counts[route_key] == 1

    client = _client(db_factory)
    try:
        assert client.get("/integrity/canonical/status").status_code == 401
        response = client.get(
            "/integrity/canonical/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["canonical_normalization_enabled"] is False
        execute_response = client.post(
            "/integrity/canonical/materialization/execute",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={"confirmation": CANONICAL_MATERIALIZE_CONFIRMATION},
        )
        assert execute_response.status_code == 409
        assert (
            execute_response.json()["detail"]["code"]
            == "CANONICAL_NORMALIZATION_DISABLED"
        )
    finally:
        app.dependency_overrides.clear()


def test_m5_migration_upgrade_downgrade_upgrade_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            RawBlockchainEvent.__table__,
            NormalizationRun.__table__,
            NormalizationReplayBatch.__table__,
            NormalizationArtifact.__table__,
            Trade.__table__,
        ],
    )
    path = Path(
        "alembic/versions/d5e8a1c4f702_add_canonical_shadow_validation.py"
    )
    spec = importlib.util.spec_from_file_location("m5_migration", path)
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
            assert "canonical_normalized_events" in tables
            assert "canonical_shadow_validation_batches" in tables
            assert "canonical_shadow_validation_results" in tables
            module.downgrade()
            tables = set(inspect(connection).get_table_names())
            assert "canonical_normalized_events" not in tables
            assert "canonical_shadow_validation_batches" not in tables
            assert "canonical_shadow_validation_results" not in tables
            module.upgrade()
            tables = set(inspect(connection).get_table_names())
            assert "canonical_normalized_events" in tables
        finally:
            module.op = original_op
    engine.dispose()
