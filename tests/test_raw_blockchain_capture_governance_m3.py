import ast
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    NormalizationRun,
    RawBlockchainEvent,
)
from backend.app.services.blockchain_integrity_service import (
    create_normalization_run,
    register_raw_event,
)
from backend.app.services import raw_blockchain_capture_service as capture_service
from backend.app.services.raw_blockchain_capture_governance_service import (
    RETENTION_CONFIRMATION,
    RawCaptureGovernanceError,
    get_raw_capture_readiness,
    preview_raw_capture_retention,
    prune_raw_capture_retention,
    run_raw_capture_canary,
)
from backend.app.services.raw_blockchain_capture_service import (
    CAPTURE_STATUS_EVENT_TYPE_DISABLED,
    RawCaptureContext,
    capture_raw_blockchain_payload_safely,
    get_raw_capture_status,
)


AUTOMATION_KEY = "a" * 32


@pytest.fixture()
def db_factory():
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
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def reset_m3_settings(monkeypatch):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_PROVIDERS",
        "helius,solana_rpc",
    )
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_EVENT_TYPES",
        "WALLET_HISTORY_RESPONSE,ENHANCED_TRANSACTION_RESPONSE,RPC_RESPONSE",
    )
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_MAX_PAYLOAD_BYTES",
        4_000_000,
    )
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_RETENTION_DAYS",
        30,
    )
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_RETENTION_BATCH_SIZE",
        1000,
    )
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED",
        False,
    )


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
    observed_at: datetime,
    provider: str = "helius",
):
    event, created = register_raw_event(
        db,
        provider=provider,
        chain="solana",
        network="mainnet-beta",
        event_type="WALLET_HISTORY_RESPONSE",
        transaction_signature=signature,
        observed_wallet="WalletM3",
        payload={"signature": signature},
        observed_at=observed_at,
    )
    assert created is True
    db.flush()
    return event


def test_m3_configuration_defaults_are_safe():
    configured = Settings(_env_file=None, **_settings_values())

    assert configured.RAW_BLOCKCHAIN_CAPTURE_ENABLED is False
    assert configured.RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED is False
    assert configured.raw_blockchain_capture_event_types == [
        "WALLET_HISTORY_RESPONSE",
        "ENHANCED_TRANSACTION_RESPONSE",
        "RPC_RESPONSE",
    ]
    assert configured.RAW_BLOCKCHAIN_CAPTURE_RETENTION_DAYS == 30
    assert configured.RAW_BLOCKCHAIN_CAPTURE_RETENTION_BATCH_SIZE == 1000


def test_enabled_capture_requires_event_types():
    with pytest.raises(ValidationError, match="almeno un event type"):
        Settings(
            _env_file=None,
            **_settings_values(
                RAW_BLOCKCHAIN_CAPTURE_ENABLED=True,
                RAW_BLOCKCHAIN_CAPTURE_EVENT_TYPES="",
            ),
        )


def test_prune_enabled_requires_minimum_seven_day_retention():
    with pytest.raises(ValidationError, match="almeno 7"):
        Settings(
            _env_file=None,
            **_settings_values(
                RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED=True,
                RAW_BLOCKCHAIN_CAPTURE_RETENTION_DAYS=1,
            ),
        )


def test_event_type_allowlist_skips_without_opening_database(monkeypatch):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", True)

    def forbidden_factory():
        raise AssertionError("Il database non deve essere aperto.")

    result = capture_raw_blockchain_payload_safely(
        {"result": "ok"},
        context=RawCaptureContext(
            provider="helius",
            event_type="UNAPPROVED_RESPONSE",
        ),
        session_factory=forbidden_factory,
    )

    assert result.status == CAPTURE_STATUS_EVENT_TYPE_DISABLED


def test_status_exposes_governance_configuration(db_factory):
    with db_factory() as db:
        status = get_raw_capture_status(db)

    assert status["event_types"] == [
        "ENHANCED_TRANSACTION_RESPONSE",
        "RPC_RESPONSE",
        "WALLET_HISTORY_RESPONSE",
    ]
    assert status["retention"] == {
        "days": 30,
        "batch_size": 1000,
        "prune_enabled": False,
    }


def test_readiness_is_local_only_and_ready_while_capture_disabled(
    monkeypatch,
    db_factory,
):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)

    with db_factory() as db:
        readiness = get_raw_capture_readiness(db)

    assert readiness["ready"] is True
    assert readiness["state"] == "READY_DISABLED"
    assert readiness["capture_enabled"] is False
    assert readiness["operational_guards"]["performs_external_requests"] is False
    assert readiness["retention"]["deletes_normalized_events"] is False


def test_canary_validates_storage_and_rolls_back(db_factory):
    with db_factory() as db:
        result = run_raw_capture_canary(db)
        persisted = db.query(RawBlockchainEvent).count()

    assert result["status"] == "PASSED"
    assert result["redaction_count"] == 2
    assert result["persisted"] is False
    assert result["database_write_rolled_back"] is True
    assert result["external_requests"] == 0
    assert persisted == 0


def test_retention_preview_separates_eligible_and_protected(db_factory):
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    old = now - timedelta(days=45)
    recent = now - timedelta(days=3)

    with db_factory() as db:
        eligible = _insert_event(db, signature="eligible", observed_at=old)
        protected = _insert_event(db, signature="protected", observed_at=old)
        _insert_event(db, signature="recent", observed_at=recent)
        create_normalization_run(
            db,
            raw_event_id=protected.id,
            parser_name="m3-test-parser",
            parser_version="1.0.0",
        )
        db.commit()

        preview = preview_raw_capture_retention(db, as_of=now)

    assert preview["expired_events"] == 2
    assert preview["normalization_protected_events"] == 1
    assert preview["eligible_events"] == 1
    assert preview["candidate_ids"] == [eligible.id]


def test_retention_dry_run_never_deletes(db_factory):
    old = datetime.now(timezone.utc) - timedelta(days=60)

    with db_factory() as db:
        _insert_event(db, signature="dry-run", observed_at=old)
        db.commit()
        result = prune_raw_capture_retention(
            db,
            dry_run=True,
            confirmation="",
        )
        remaining = db.query(RawBlockchainEvent).count()

    assert result["execution"]["performed"] is False
    assert result["execution"]["deleted_events"] == 0
    assert remaining == 1


def test_retention_delete_is_blocked_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(
            RawCaptureGovernanceError,
            match="disabilitata",
        ):
            prune_raw_capture_retention(
                db,
                dry_run=False,
                confirmation=RETENTION_CONFIRMATION,
            )


def test_retention_delete_requires_exact_confirmation(monkeypatch, db_factory):
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED",
        True,
    )

    with db_factory() as db:
        with pytest.raises(
            RawCaptureGovernanceError,
            match="Conferma retention non valida",
        ):
            prune_raw_capture_retention(
                db,
                dry_run=False,
                confirmation="wrong",
            )


def test_retention_prunes_only_unnormalized_events(monkeypatch, db_factory):
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED",
        True,
    )
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=60)

    with db_factory() as db:
        eligible = _insert_event(db, signature="delete-me", observed_at=old)
        protected = _insert_event(db, signature="keep-me", observed_at=old)
        create_normalization_run(
            db,
            raw_event_id=protected.id,
            parser_name="m3-test-parser",
            parser_version="1.0.0",
        )
        db.commit()

        result = prune_raw_capture_retention(
            db,
            dry_run=False,
            confirmation=RETENTION_CONFIRMATION,
        )
        remaining_ids = {
            row.id
            for row in db.query(RawBlockchainEvent).all()
        }

    assert result["execution"]["deleted_events"] == 1
    assert eligible.id not in remaining_ids
    assert protected.id in remaining_ids


def test_retention_respects_configured_batch_ceiling(monkeypatch, db_factory):
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_RETENTION_BATCH_SIZE",
        2,
    )
    old = datetime.now(timezone.utc) - timedelta(days=60)

    with db_factory() as db:
        for index in range(4):
            _insert_event(
                db,
                signature=f"batch-{index}",
                observed_at=old + timedelta(seconds=index),
            )
        db.commit()

        result = prune_raw_capture_retention(
            db,
            dry_run=False,
            confirmation=RETENTION_CONFIRMATION,
            batch_size=10,
        )
        remaining = db.query(RawBlockchainEvent).count()

    assert result["effective_batch_size"] == 2
    assert result["execution"]["deleted_events"] == 2
    assert remaining == 2


def test_governance_endpoints_are_protected_and_non_live(
    monkeypatch,
    db_factory,
):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)

    def override_get_db():
        db: Session = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            unauthorized = client.get(
                "/integrity/raw-capture/readiness"
            )
            readiness = client.get(
                "/integrity/raw-capture/readiness",
                headers={"X-Automation-Key": AUTOMATION_KEY},
            )
            canary = client.post(
                "/integrity/raw-capture/canary",
                headers={"X-Automation-Key": AUTOMATION_KEY},
            )
            preview = client.get(
                "/integrity/raw-capture/retention/preview",
                headers={"X-Automation-Key": AUTOMATION_KEY},
            )
            blocked_prune = client.post(
                "/integrity/raw-capture/retention/prune",
                headers={"X-Automation-Key": AUTOMATION_KEY},
                json={
                    "dry_run": False,
                    "confirmation": RETENTION_CONFIRMATION,
                },
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert unauthorized.status_code == 401
    assert readiness.status_code == 200
    assert canary.status_code == 200
    assert canary.json()["persisted"] is False
    assert preview.status_code == 200
    assert blocked_prune.status_code == 409
    assert blocked_prune.json()["detail"]["code"] == "RAW_CAPTURE_PRUNE_DISABLED"
    assert settings.RAW_BLOCKCHAIN_CAPTURE_ENABLED is False
    assert settings.RUN_LIVE_STREAM_WORKER is False
    assert settings.RUN_LIVE_POSITION_MONITOR is False


def test_governance_routes_are_registered_once():
    expected = {
        ("GET", "/integrity/raw-capture/readiness"),
        ("POST", "/integrity/raw-capture/canary"),
        ("GET", "/integrity/raw-capture/retention/preview"),
        ("POST", "/integrity/raw-capture/retention/prune"),
    }
    counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", None) or set():
            key = (method, getattr(route, "path", ""))
            if key in expected:
                counts[key] += 1

    assert counts == Counter({key: 1 for key in expected})


def test_governance_service_has_no_network_client_imports():
    import backend.app.services.raw_blockchain_capture_governance_service as module

    path = Path(module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"httpx", "requests", "aiohttp", "websockets", "urllib3"}
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])

    assert imports.isdisjoint(forbidden)
