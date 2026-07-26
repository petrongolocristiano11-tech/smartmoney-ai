from __future__ import annotations

import ast
import importlib.util
from collections import Counter
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalNormalizedEvent,
    CanonicalParserShadowConsumerResult,
    CanonicalParserShadowConsumerRun,
    RawBlockchainEvent,
)
from backend.app.models.trade import Trade
from backend.app.services import blockchain_parser_shadow_consumer_service as service_module
from backend.app.services.blockchain_parser_shadow_consumer_service import (
    SHADOW_CONSUMER_CONFIRMATION_PREFIX,
    SHADOW_CONSUMER_POLICY_VERSION,
    CanonicalParserShadowConsumerError,
    get_shadow_consumer_run,
    get_shadow_consumer_status,
    preview_shadow_consumer_run,
    run_shadow_consumer_dry_run,
)

AUTOMATION_KEY = "a" * 32


def _load_m11_helpers():
    path = Path(__file__).with_name("test_parser_shadow_runtime_lease_m11.py")
    spec = importlib.util.spec_from_file_location("m11_test_helpers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


M11 = _load_m11_helpers()
NOW = M11.NOW + timedelta(hours=1, minutes=5)


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def safe_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    for name in (
        "CANONICAL_PARSER_SHADOW_CONSUMER_ENABLED",
        "CANONICAL_PARSER_SHADOW_LEASE_ENABLED",
        "CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED",
        "CANONICAL_PARSER_RUNTIME_ADMISSION_ENABLED",
        "CANONICAL_PARSER_RUNTIME_BINDING_ENABLED",
        "CANONICAL_PARSER_PROMOTION_ENABLED",
        "CANONICAL_QUALITY_GATE_ENABLED",
        "CANONICAL_NORMALIZATION_ENABLED",
        "CANONICAL_SHADOW_VALIDATION_ENABLED",
        "RAW_BLOCKCHAIN_REPLAY_ENABLED",
        "RAW_BLOCKCHAIN_CAPTURE_ENABLED",
        "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED",
        "RUN_LIVE_STREAM_WORKER",
        "RUN_LIVE_POSITION_MONITOR",
    ):
        monkeypatch.setattr(settings, name, False)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_CONSUMER_MAX_SAMPLE_SIZE", 25)


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test-helius-api-key",
    }
    values.update(overrides)
    return values


def _policy(*, enabled: bool = True, lease_enabled: bool = True, max_sample: int = 25):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_CONSUMER_ENABLED=enabled,
        CANONICAL_PARSER_SHADOW_CONSUMER_MAX_SAMPLE_SIZE=max_sample,
        CANONICAL_PARSER_SHADOW_LEASE_ENABLED=lease_enabled,
    )


def _prepare(db):
    _, _, _, lease = M11._issue(
        db,
        issued_at=M11.NOW + timedelta(hours=1),
        validity=30,
    )
    events = list(db.scalars(select(RawBlockchainEvent).order_by(RawBlockchainEvent.id)))
    assert len(events) >= 10
    return lease, events


def _execute(db, *, limit: int = 2, policy=None):
    policy = policy or _policy()
    lease, events = _prepare(db)
    ids = [event.id for event in events[:limit]]
    preview = preview_shadow_consumer_run(
        db,
        lease_id=lease["lease_id"],
        raw_event_ids=ids,
        limit=limit,
        settings_object=policy,
        evaluated_at=NOW,
    )
    result = run_shadow_consumer_dry_run(
        db,
        confirmation=preview["confirmation"],
        lease_id=lease["lease_id"],
        raw_event_ids=ids,
        limit=limit,
        actor_label="m12-operator",
        note="bounded certified shadow execution",
        settings_object=policy,
        started_at=NOW,
        completed_at=NOW + timedelta(minutes=1),
    )
    return lease, events, preview, result


def _client(factory):
    def override_db():
        yield from _yield_db(factory)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _yield_db(factory):
    db = factory()
    try:
        yield db
    finally:
        db.close()


def test_settings_defaults_are_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_CONSUMER_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_CONSUMER_MAX_SAMPLE_SIZE == 25


def test_status_is_disabled_and_reports_manual_guard(db_factory):
    with db_factory() as db:
        status = get_shadow_consumer_status(db)
        assert status["consumer_enabled"] is False
        assert status["policy_version"] == SHADOW_CONSUMER_POLICY_VERSION
        assert status["operational_guards"]["manual_consumer_connected"] is True
        assert status["operational_guards"]["automatic_consumer_connected"] is False
        assert status["operational_guards"]["writes_trades"] is False


def test_preview_requires_active_authorized_lease(db_factory):
    with db_factory() as db:
        preview = preview_shadow_consumer_run(db, settings_object=_policy())
        assert preview["eligible"] is False
        assert "SHADOW_LEASE_CONSUMER_NOT_AUTHORIZED" in preview["blocker_codes"]


def test_preview_is_eligible_deterministic_and_bounded(db_factory):
    with db_factory() as db:
        lease, events = _prepare(db)
        ids = [events[0].id, events[1].id]
        first = preview_shadow_consumer_run(
            db, lease_id=lease["lease_id"], raw_event_ids=ids, limit=2,
            settings_object=_policy(), evaluated_at=NOW,
        )
        second = preview_shadow_consumer_run(
            db, lease_id=lease["lease_id"], raw_event_ids=list(reversed(ids)), limit=2,
            settings_object=_policy(), evaluated_at=NOW + timedelta(minutes=1),
        )
        assert first["eligible"] is True
        assert first["run_key"] == second["run_key"]
        assert first["confirmation"] == second["confirmation"]
        assert first["confirmation"].startswith(SHADOW_CONSUMER_CONFIRMATION_PREFIX)
        assert first["writes_shadow_tables_only"] is True
        assert first["writes_trades"] is False
        assert first["external_requests"] == 0


def test_preview_rejects_invalid_limits_and_sample_size(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowConsumerError) as exc:
            preview_shadow_consumer_run(db, limit=3, settings_object=_policy(max_sample=2))
        assert exc.value.code == "SHADOW_CONSUMER_LIMIT_INVALID"
        with pytest.raises(CanonicalParserShadowConsumerError) as exc:
            preview_shadow_consumer_run(
                db, raw_event_ids=[1, 2, 3], limit=2,
                settings_object=_policy(max_sample=2),
            )
        assert exc.value.code == "SHADOW_CONSUMER_SAMPLE_TOO_LARGE"


def test_preview_reports_missing_and_lease_mismatch(db_factory):
    with db_factory() as db:
        lease, _ = _prepare(db)
        preview = preview_shadow_consumer_run(
            db,
            lease_id=str(uuid4()),
            raw_event_ids=[999999],
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        assert preview["eligible"] is False
        assert "SHADOW_LEASE_ID_MISMATCH" in preview["blocker_codes"]
        assert "RAW_EVENTS_NOT_FOUND" in preview["blocker_codes"]


def test_run_is_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowConsumerError) as exc:
            run_shadow_consumer_dry_run(db, confirmation="anything")
        assert exc.value.code == "CANONICAL_PARSER_SHADOW_CONSUMER_DISABLED"


def test_run_requires_current_confirmation(db_factory):
    with db_factory() as db:
        lease, events = _prepare(db)
        with pytest.raises(CanonicalParserShadowConsumerError) as exc:
            run_shadow_consumer_dry_run(
                db,
                confirmation="stale",
                lease_id=lease["lease_id"],
                raw_event_ids=[events[0].id],
                limit=1,
                settings_object=_policy(),
                started_at=NOW,
            )
        assert exc.value.code == "SHADOW_CONSUMER_CONFIRMATION_REQUIRED"


def test_successful_run_persists_only_shadow_results(db_factory):
    with db_factory() as db:
        _, _, _, result = _execute(db)
        assert result["created"] is True
        assert result["status"] == "PASSED"
        assert result["processed_count"] == 2
        assert result["passed_count"] == 2
        assert result["failed_count"] == 0
        assert result["artifact_count"] >= 2
        assert len(result["results"]) == 2
        assert all(item["deterministic"] is True for item in result["results"])
        assert all(item["shadow_artifacts"] for item in result["results"])
        assert db.query(Trade).count() == 0
        assert db.query(CanonicalNormalizedEvent).count() == 0


def test_run_is_idempotent_by_manifest(db_factory):
    with db_factory() as db:
        lease, events, preview, first = _execute(db, limit=1)
        second = run_shadow_consumer_dry_run(
            db,
            confirmation=preview["confirmation"],
            lease_id=lease["lease_id"],
            raw_event_ids=[events[0].id],
            limit=1,
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(minutes=1),
        )
        assert second["created"] is False
        assert second["run_id"] == first["run_id"]
        assert db.query(CanonicalParserShadowConsumerRun).count() == 1


def test_raw_payload_hash_tampering_is_persisted_as_failure(db_factory):
    with db_factory() as db:
        lease, events = _prepare(db)
        event = events[0]
        event.raw_payload = [{"type": "SWAP", "tampered": True}]
        db.flush()
        preview = preview_shadow_consumer_run(
            db, lease_id=lease["lease_id"], raw_event_ids=[event.id], limit=1,
            settings_object=_policy(), evaluated_at=NOW,
        )
        result = run_shadow_consumer_dry_run(
            db, confirmation=preview["confirmation"], lease_id=lease["lease_id"],
            raw_event_ids=[event.id], limit=1, settings_object=_policy(),
            started_at=NOW, completed_at=NOW + timedelta(minutes=1),
        )
        assert result["status"] == "FAILED"
        assert result["results"][0]["reason_codes"] == ["RAW_PAYLOAD_HASH_MISMATCH"]


def test_end_of_run_lease_interlock_fails_closed(db_factory, monkeypatch):
    with db_factory() as db:
        lease, events = _prepare(db)
        real_resolve = service_module.resolve_shadow_runtime_lease
        calls = {"count": 0}

        def drifting(*args, **kwargs):
            calls["count"] += 1
            resolved = real_resolve(*args, **kwargs)
            if calls["count"] >= 3:
                resolved = dict(resolved)
                resolved["resolved"] = False
                resolved["consumer_authorized"] = False
                resolved["status"] = "DRIFTED"
                resolved["reason_codes"] = ["TEST_LEASE_DRIFT"]
            return resolved

        monkeypatch.setattr(service_module, "resolve_shadow_runtime_lease", drifting)
        preview = preview_shadow_consumer_run(
            db, lease_id=lease["lease_id"], raw_event_ids=[events[0].id], limit=1,
            settings_object=_policy(), evaluated_at=NOW,
        )
        result = run_shadow_consumer_dry_run(
            db, confirmation=preview["confirmation"], lease_id=lease["lease_id"],
            raw_event_ids=[events[0].id], limit=1, settings_object=_policy(),
            started_at=NOW, completed_at=NOW + timedelta(minutes=1),
        )
        assert result["status"] == "FAILED"
        assert "SHADOW_LEASE_INTERLOCK_TRIPPED" in result["reason_codes"]
        assert "TEST_LEASE_DRIFT" in result["reason_codes"]


def test_get_run_and_not_found(db_factory):
    with db_factory() as db:
        _, _, _, result = _execute(db, limit=1)
        loaded = get_shadow_consumer_run(db, result["run_id"])
        assert loaded["run_id"] == result["run_id"]
        with pytest.raises(CanonicalParserShadowConsumerError) as exc:
            get_shadow_consumer_run(db, str(uuid4()))
        assert exc.value.status_code == 404


def test_status_counts_completed_runs(db_factory):
    with db_factory() as db:
        _execute(db, limit=1)
        status = get_shadow_consumer_status(db, settings_object=_policy())
        assert status["run_count"] == 1
        assert status["status_counts"]["PASSED"] == 1


def test_actor_and_note_are_sanitized(db_factory):
    with db_factory() as db:
        lease, events = _prepare(db)
        preview = preview_shadow_consumer_run(
            db, lease_id=lease["lease_id"], raw_event_ids=[events[0].id], limit=1,
            settings_object=_policy(), evaluated_at=NOW,
        )
        result = run_shadow_consumer_dry_run(
            db, confirmation=preview["confirmation"], lease_id=lease["lease_id"],
            raw_event_ids=[events[0].id], limit=1, actor_label="operator\nsecret",
            note="note\r\nline", settings_object=_policy(), started_at=NOW,
            completed_at=NOW + timedelta(minutes=1),
        )
        assert "\n" not in result["actor_label"]
        assert "\r" not in result["note"]


def test_m12_models_are_registered():
    names = set(Base.metadata.tables)
    assert "canonical_parser_shadow_consumer_runs" in names
    assert "canonical_parser_shadow_consumer_results" in names
    assert models.CanonicalParserShadowConsumerRun is CanonicalParserShadowConsumerRun
    assert models.CanonicalParserShadowConsumerResult is CanonicalParserShadowConsumerResult


def test_m12_service_has_no_network_clients_trade_or_live_writes():
    path = Path("backend/app/services/blockchain_parser_shadow_consumer_service.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports & {"httpx", "requests", "aiohttp", "urllib3", "websockets"}
    source = path.read_text(encoding="utf-8")
    assert "Trade(" not in source
    assert "PaperOrder(" not in source
    assert "LiveCopyOrder(" not in source
    assert "RUN_LIVE" not in source


def test_m12_service_not_imported_by_operational_pipelines():
    forbidden = []
    allowed = {
        "main.py",
        "blockchain_parser_shadow_consumer_service.py",
        "blockchain_parser_shadow_readiness_service.py",
    }
    for path in Path("backend/app").rglob("*.py"):
        if path.name in allowed:
            continue
        if "blockchain_parser_shadow_consumer_service" in path.read_text(encoding="utf-8"):
            forbidden.append(str(path))
    assert forbidden == []


def test_m12_api_routes_are_protected_and_registered_once(db_factory):
    counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            counts[(method, getattr(route, "path", ""))] += 1
    expected = {
        ("GET", "/integrity/parser-shadow-consumer/status"),
        ("GET", "/integrity/parser-shadow-consumer/preview"),
        ("POST", "/integrity/parser-shadow-consumer/run"),
        ("GET", "/integrity/parser-shadow-consumer/runs/{run_id}"),
    }
    for route in expected:
        assert counts[route] == 1
    client = _client(db_factory)
    try:
        assert client.get("/integrity/parser-shadow-consumer/status").status_code == 401
        response = client.get(
            "/integrity/parser-shadow-consumer/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["consumer_enabled"] is False
        post = client.post(
            "/integrity/parser-shadow-consumer/run",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={"confirmation": "anything"},
        )
        assert post.status_code == 409
        assert post.json()["detail"]["code"] == "CANONICAL_PARSER_SHADOW_CONSUMER_DISABLED"
    finally:
        app.dependency_overrides.clear()


def test_result_unique_per_run_and_raw_event(db_factory):
    with db_factory() as db:
        _, _, _, result = _execute(db, limit=1)
        run = db.query(CanonicalParserShadowConsumerRun).one()
        original = db.query(CanonicalParserShadowConsumerResult).one()
        duplicate = CanonicalParserShadowConsumerResult(
            result_id=str(uuid4()), consumer_run_db_id=run.id,
            raw_event_id=original.raw_event_id, raw_payload_hash=original.raw_payload_hash,
            status="PASS", compatible=True, deterministic=True,
            output_hash="a" * 64, verification_output_hash="a" * 64,
            artifact_count=1, shadow_artifacts=[{"x": 1}], reason_codes=[],
            error_message=None, started_at=NOW, completed_at=NOW,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


def test_m12_migration_upgrade_downgrade_upgrade_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    path = Path("alembic/versions/e1a4c7b9f205_add_certified_shadow_consumer.py")
    spec = importlib.util.spec_from_file_location("m12_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE canonical_parser_shadow_runtime_leases (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE raw_blockchain_events (id INTEGER PRIMARY KEY)")
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_shadow_consumer_runs" in names
    assert "canonical_parser_shadow_consumer_results" in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.downgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_shadow_consumer_runs" not in names
    assert "canonical_parser_shadow_consumer_results" not in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    assert "canonical_parser_shadow_consumer_runs" in inspect(engine).get_table_names()
    engine.dispose()
