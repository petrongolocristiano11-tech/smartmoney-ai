from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx
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
from backend.app.services import helius
from backend.app.services import raw_blockchain_capture_service as raw_capture
from backend.app.services.raw_blockchain_capture_service import (
    CAPTURE_STATUS_CREATED,
    CAPTURE_STATUS_DEDUPLICATED,
    CAPTURE_STATUS_DISABLED,
    CAPTURE_STATUS_FAILED,
    CAPTURE_STATUS_OVERSIZE,
    CAPTURE_STATUS_PROVIDER_DISABLED,
    RawCaptureContext,
    capture_raw_blockchain_payload_safely,
    get_raw_capture_status,
    reset_raw_capture_runtime_metrics,
)
from backend.app.services.solana_rpc import SolanaRpcClient


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
def reset_capture_state(monkeypatch):
    reset_raw_capture_runtime_metrics()
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_PROVIDERS",
        "helius,solana_rpc",
    )
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_MAX_PAYLOAD_BYTES",
        4_000_000,
    )


def _helius_response(payload):
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "https://api.helius.xyz/v0/test"),
    )


def _enable_capture(monkeypatch, db_factory):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", True)
    monkeypatch.setattr(raw_capture, "SessionLocal", db_factory)


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test-helius-api-key",
    }
    values.update(overrides)
    return values


def test_capture_configuration_is_disabled_by_default():
    configured = Settings(_env_file=None, **_settings_values())

    assert configured.RAW_BLOCKCHAIN_CAPTURE_ENABLED is False
    assert configured.raw_blockchain_capture_providers == [
        "helius",
        "solana_rpc",
    ]
    assert configured.RAW_BLOCKCHAIN_CAPTURE_MAX_PAYLOAD_BYTES == 4_000_000


def test_enabled_capture_requires_at_least_one_provider():
    with pytest.raises(ValidationError, match="almeno un provider"):
        Settings(
            _env_file=None,
            **_settings_values(
                RAW_BLOCKCHAIN_CAPTURE_ENABLED=True,
                RAW_BLOCKCHAIN_CAPTURE_PROVIDERS="",
            ),
        )


def test_disabled_capture_does_not_open_database():
    def forbidden_factory():
        raise AssertionError("Il database non deve essere aperto.")

    result = capture_raw_blockchain_payload_safely(
        {"result": {"value": 10}},
        context=RawCaptureContext(
            provider="helius",
            event_type="RPC_RESPONSE",
        ),
        session_factory=forbidden_factory,
    )

    assert result.status == CAPTURE_STATUS_DISABLED


def test_disabled_helius_integration_preserves_response_and_skips_database(
    monkeypatch,
):
    calls = 0
    payload = [{"signature": "sig-disabled", "type": "SWAP"}]

    def fake_request(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _helius_response(payload)

    def forbidden_factory():
        raise AssertionError("Il database non deve essere aperto.")

    monkeypatch.setattr(helius.httpx, "request", fake_request)
    monkeypatch.setattr(raw_capture, "SessionLocal", forbidden_factory)

    assert helius.get_wallet_history("WalletDisabled") == payload
    assert calls == 1


def test_provider_allowlist_skips_without_opening_database(monkeypatch):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", True)
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_PROVIDERS", "helius")

    def forbidden_factory():
        raise AssertionError("Il database non deve essere aperto.")

    result = capture_raw_blockchain_payload_safely(
        {"result": "ok"},
        context=RawCaptureContext(
            provider="solana_rpc",
            event_type="RPC_RESPONSE",
        ),
        session_factory=forbidden_factory,
    )

    assert result.status == CAPTURE_STATUS_PROVIDER_DISABLED


def test_helius_capture_is_passive_and_adds_no_network_requests(
    monkeypatch,
    db_factory,
):
    _enable_capture(monkeypatch, db_factory)
    calls = 0
    provider_payload = [
        {
            "signature": "sig-001",
            "slot": 123,
            "timestamp": 1_700_000_000,
            "type": "SWAP",
        }
    ]

    def fake_request(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _helius_response(provider_payload)

    monkeypatch.setattr(helius.httpx, "request", fake_request)

    returned = helius.get_wallet_history(
        "Wallet111",
        commitment="confirmed",
    )

    assert returned == provider_payload
    assert calls == 1

    with db_factory() as db:
        event = db.query(RawBlockchainEvent).one()
        assert event.provider == "helius"
        assert event.event_type == "WALLET_HISTORY_RESPONSE"
        assert event.observed_wallet == "Wallet111"
        assert event.transaction_signature == "sig-001"
        assert event.slot == 123
        assert event.commitment == "confirmed"
        assert event.raw_payload == provider_payload
        assert db.query(NormalizationRun).count() == 0


def test_helius_duplicate_capture_increments_observation_count(
    monkeypatch,
    db_factory,
):
    _enable_capture(monkeypatch, db_factory)
    payload = [{"signature": "sig-repeat", "type": "SWAP"}]
    monkeypatch.setattr(
        helius.httpx,
        "request",
        lambda *_args, **_kwargs: _helius_response(payload),
    )

    assert helius.get_wallet_history("WalletRepeat") == payload
    assert helius.get_wallet_history("WalletRepeat") == payload

    with db_factory() as db:
        event = db.query(RawBlockchainEvent).one()
        assert event.observation_count == 2


def test_sensitive_provider_content_is_redacted_only_in_storage(
    monkeypatch,
    db_factory,
):
    _enable_capture(monkeypatch, db_factory)
    secret = "provider-secret-value"
    payload = [
        {
            "signature": "sig-secret",
            "apiKey": secret,
            "debug": f"https://provider.test/path?api-key={secret}",
        }
    ]
    monkeypatch.setattr(
        helius.httpx,
        "request",
        lambda *_args, **_kwargs: _helius_response(payload),
    )

    returned = helius.get_wallet_history("WalletSecret")

    assert returned == payload
    assert returned[0]["apiKey"] == secret
    with db_factory() as db:
        stored = db.query(RawBlockchainEvent).one()
        serialized = json.dumps(stored.raw_payload, sort_keys=True)
        assert secret not in serialized
        assert "apiKey" not in serialized
        assert "[REDACTED]" in serialized
        assert stored.event_metadata["redaction_count"] == 2


def test_oversize_payload_is_skipped_without_database_write(
    monkeypatch,
    db_factory,
):
    _enable_capture(monkeypatch, db_factory)
    monkeypatch.setattr(
        settings,
        "RAW_BLOCKCHAIN_CAPTURE_MAX_PAYLOAD_BYTES",
        64,
    )

    result = capture_raw_blockchain_payload_safely(
        {"payload": "x" * 500},
        context=RawCaptureContext(
            provider="helius",
            event_type="RPC_RESPONSE",
        ),
        session_factory=db_factory,
    )

    assert result.status == CAPTURE_STATUS_OVERSIZE
    with db_factory() as db:
        assert db.query(RawBlockchainEvent).count() == 0


def test_database_failure_is_fail_open_and_sanitized(monkeypatch):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", True)
    exposed = "database-password-that-must-not-appear"

    def failing_factory():
        raise RuntimeError(
            f"postgresql://user:{exposed}@localhost/db?api-key={exposed}"
        )

    result = capture_raw_blockchain_payload_safely(
        {"result": "original-return-value"},
        context=RawCaptureContext(
            provider="helius",
            event_type="RPC_RESPONSE",
        ),
        session_factory=failing_factory,
    )

    assert result.status == CAPTURE_STATUS_FAILED
    assert result.error_message is not None
    assert exposed not in result.error_message


def test_solana_rpc_capture_preserves_return_value_and_request_count(
    monkeypatch,
    db_factory,
):
    _enable_capture(monkeypatch, db_factory)
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "context": {"slot": 456},
                    "value": 1_000_000_000,
                },
            },
        )

    client = SolanaRpcClient(
        rpc_url="https://rpc.test?api-key=not-persisted",
        transport=httpx.MockTransport(handler),
    )
    returned = client.call(
        "getBalance",
        ["WalletBalance", {"commitment": "confirmed"}],
    )

    assert returned == {
        "context": {"slot": 456},
        "value": 1_000_000_000,
    }
    assert calls == 1

    with db_factory() as db:
        event = db.query(RawBlockchainEvent).one()
        assert event.provider == "solana_rpc"
        assert event.observed_wallet == "WalletBalance"
        assert event.slot == 456
        assert event.commitment == "confirmed"
        assert "not-persisted" not in json.dumps(event.event_metadata)


def test_capture_failure_does_not_change_solana_rpc_success(
    monkeypatch,
):
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", True)

    def failing_factory():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(raw_capture, "SessionLocal", failing_factory)
    client = SolanaRpcClient(
        rpc_url="https://rpc.test",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": "ok"},
            )
        ),
    )

    assert client.call("getHealth") == "ok"


def test_status_service_reports_persisted_and_runtime_metrics(
    monkeypatch,
    db_factory,
):
    _enable_capture(monkeypatch, db_factory)

    first = capture_raw_blockchain_payload_safely(
        {"result": "ok"},
        context=RawCaptureContext(
            provider="helius",
            event_type="RPC_RESPONSE",
        ),
        session_factory=db_factory,
    )
    second = capture_raw_blockchain_payload_safely(
        {"result": "ok"},
        context=RawCaptureContext(
            provider="helius",
            event_type="RPC_RESPONSE",
        ),
        session_factory=db_factory,
    )

    assert first.status == CAPTURE_STATUS_CREATED
    assert second.status == CAPTURE_STATUS_DEDUPLICATED

    with db_factory() as db:
        status = get_raw_capture_status(db)

    assert status["enabled"] is True
    assert status["persisted"]["raw_events"] == 1
    assert status["persisted"]["by_provider"] == [
        {
            "provider": "helius",
            "raw_events": 1,
            "observations": 2,
        }
    ]
    assert status["runtime_metrics"][CAPTURE_STATUS_CREATED] == 1
    assert status["runtime_metrics"][CAPTURE_STATUS_DEDUPLICATED] == 1
    assert status["operational_guards"]["performs_external_requests"] is False
    assert status["operational_guards"]["starts_normalization"] is False


def test_status_api_is_read_only_and_protected(
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
            unauthorized = client.get("/integrity/raw-capture/status")
            authorized = client.get(
                "/integrity/raw-capture/status",
                headers={"X-Automation-Key": AUTOMATION_KEY},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    body = authorized.json()
    assert body["mode"] == "PASSIVE_SHADOW"
    assert body["operational_guards"]["fail_open"] is True


def test_new_capture_service_has_no_network_client_imports():
    path = Path(raw_capture.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"httpx", "requests", "aiohttp", "websockets", "urllib3"}
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])

    assert imports.isdisjoint(forbidden)


def test_milestone_does_not_enable_live_workers_or_normalization():
    assert settings.RUN_LIVE_STREAM_WORKER is False
    assert settings.RUN_LIVE_POSITION_MONITOR is False
    assert settings.RAW_BLOCKCHAIN_CAPTURE_ENABLED is False
