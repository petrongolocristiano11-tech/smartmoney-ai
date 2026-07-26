from __future__ import annotations

import ast
import importlib.util
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowSchedulerTick,
    CanonicalParserShadowSchedulerWorkerEvent,
    CanonicalParserShadowSchedulerWorkerIteration,
    CanonicalParserShadowSchedulerWorkerState,
)
from backend.app.services import blockchain_parser_shadow_worker_service as service_module
from backend.app.services.blockchain_parser_shadow_scheduler_service import CanonicalParserShadowSchedulerError
from backend.app.services.blockchain_parser_shadow_worker_service import (
    SHADOW_WORKER_HEARTBEAT_PREFIX,
    SHADOW_WORKER_KILL_PREFIX,
    SHADOW_WORKER_RESET_PREFIX,
    SHADOW_WORKER_START_PREFIX,
    SHADOW_WORKER_STOP_PREFIX,
    CanonicalParserShadowWorkerError,
    control_shadow_worker,
    get_shadow_worker_state,
    get_shadow_worker_status,
    heartbeat_shadow_worker,
    preview_shadow_worker_iteration,
    preview_shadow_worker_start,
    run_shadow_worker_iteration,
    start_shadow_worker,
)

NOW = datetime(2026, 7, 26, 19, 0, tzinfo=timezone.utc)
OWNER = "worker-a"
AUTOMATION_KEY = "a" * 32


@pytest.fixture()
def db_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def safe_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENABLED", False)
    monkeypatch.setattr(settings, "RUN_LIVE_STREAM_WORKER", False)
    monkeypatch.setattr(settings, "RUN_LIVE_POSITION_MONITOR", False)


def _settings_values(**overrides):
    values = {"DATABASE_URL": "sqlite+pysqlite:///:memory:", "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com", "HELIUS_API_KEY": "test"}
    values.update(overrides)
    return values


def _policy(enabled=True):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_WORKER_ENABLED=enabled,
        CANONICAL_PARSER_SHADOW_WORKER_LEASE_TTL_SECONDS=120,
        CANONICAL_PARSER_SHADOW_WORKER_HEARTBEAT_TIMEOUT_SECONDS=180,
        CANONICAL_PARSER_SHADOW_WORKER_MAX_CONSECUTIVE_FAILURES=3,
        CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED=True,
    )


def _start(db, owner=OWNER, now=NOW):
    preview = preview_shadow_worker_start(owner_id=owner, settings_object=_policy())
    return start_shadow_worker(db, confirmation=preview["confirmation"], owner_id=owner, settings_object=_policy(), started_at=now)


def _control(prefix, state, owner=OWNER):
    return f"{prefix}:{state.generation}:{state.lease_epoch}:{owner}:{(state.latest_event_hash or '0'*64)[:16]}"


def _patch_scheduler(monkeypatch, *, tickable=True, status="PASSED", fail=False):
    monkeypatch.setattr(service_module, "preview_shadow_scheduler_tick", lambda *a, **k: {
        "tickable": tickable,
        "reason_codes": [] if tickable else ["SHADOW_SCHEDULER_INTERVAL_NOT_ELAPSED"],
        "confirmation": "TICK-CONFIRM",
        "tick_key": "t" * 64,
        "state": {"generation": 1},
    })
    if fail:
        def _raise(*a, **k):
            raise CanonicalParserShadowSchedulerError("tick failed", code="TEST_TICK_FAILED", status_code=409)
        monkeypatch.setattr(service_module, "run_shadow_scheduler_tick", _raise)
    else:
        monkeypatch.setattr(service_module, "run_shadow_scheduler_tick", lambda *a, **k: {
            "tick_id": str(uuid4()), "cycle_id": str(uuid4()), "status": status, "reason_codes": []
        })


def _client(factory):
    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m19_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_WORKER_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_WORKER_LEASE_TTL_SECONDS == 120
    assert configured.CANONICAL_PARSER_SHADOW_WORKER_MAX_CONSECUTIVE_FAILURES == 3


def test_m19_start_disabled(db_factory):
    with db_factory() as db:
        preview = preview_shadow_worker_start(owner_id=OWNER)
        with pytest.raises(CanonicalParserShadowWorkerError) as error:
            start_shadow_worker(db, confirmation=preview["confirmation"], owner_id=OWNER)
        assert error.value.code == "CANONICAL_PARSER_SHADOW_WORKER_DISABLED"


def test_m19_start_persists_lease_and_audit(db_factory):
    with db_factory() as db:
        state = _start(db)
        assert state["worker_ready"] is True
        assert state["lease_epoch"] == 1
        assert state["owner_id"] == OWNER
        assert db.query(CanonicalParserShadowSchedulerWorkerEvent).count() == 1


def test_m19_active_lease_blocks_other_owner(db_factory):
    with db_factory() as db:
        _start(db)
        preview = preview_shadow_worker_start(owner_id="worker-b", settings_object=_policy())
        with pytest.raises(CanonicalParserShadowWorkerError) as error:
            start_shadow_worker(db, confirmation=preview["confirmation"], owner_id="worker-b", settings_object=_policy(), started_at=NOW + timedelta(seconds=1))
        assert error.value.code == "SHADOW_WORKER_LEASE_HELD"


def test_m19_expired_lease_allows_fenced_takeover(db_factory):
    with db_factory() as db:
        _start(db)
        preview = preview_shadow_worker_start(owner_id="worker-b", settings_object=_policy())
        state = start_shadow_worker(db, confirmation=preview["confirmation"], owner_id="worker-b", settings_object=_policy(), started_at=NOW + timedelta(seconds=121))
        assert state["lease_epoch"] == 2
        assert state["owner_id"] == "worker-b"
        assert state["audit_chain_valid"] is True


def test_m19_heartbeat_renews_lease(db_factory):
    with db_factory() as db:
        _start(db)
        state = db.scalar(select(CanonicalParserShadowSchedulerWorkerState))
        result = heartbeat_shadow_worker(db, confirmation=_control(SHADOW_WORKER_HEARTBEAT_PREFIX, state), owner_id=OWNER, settings_object=_policy(), heartbeat_at=NOW + timedelta(seconds=30))
        assert result["lease_active"] is True
        assert result["audit_chain_valid"] is True


def test_m19_idle_iteration_is_persisted(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db)
        _patch_scheduler(monkeypatch, tickable=False)
        preview = preview_shadow_worker_iteration(db, owner_id=OWNER, settings_object=_policy(), evaluated_at=NOW + timedelta(seconds=1))
        result = run_shadow_worker_iteration(db, confirmation=preview["confirmation"], owner_id=OWNER, settings_object=_policy(), started_at=NOW + timedelta(seconds=1), completed_at=NOW + timedelta(seconds=2))
        assert result["status"] == "IDLE"
        assert db.query(CanonicalParserShadowSchedulerWorkerIteration).count() == 1


def test_m19_success_iteration_records_tick_snapshot(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db)
        _patch_scheduler(monkeypatch, status="PASSED")
        preview = preview_shadow_worker_iteration(db, owner_id=OWNER, settings_object=_policy(), evaluated_at=NOW + timedelta(seconds=1))
        result = run_shadow_worker_iteration(db, confirmation=preview["confirmation"], owner_id=OWNER, settings_object=_policy(), started_at=NOW + timedelta(seconds=1), completed_at=NOW + timedelta(seconds=2))
        assert result["status"] == "PASSED"
        assert result["tick_id"]
        state = get_shadow_worker_state(db, settings_object=_policy(), evaluated_at=NOW + timedelta(seconds=2))
        assert state["consecutive_failures"] == 0


def test_m19_failed_iteration_increments_failure_counter(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db)
        _patch_scheduler(monkeypatch, fail=True)
        preview = preview_shadow_worker_iteration(db, owner_id=OWNER, settings_object=_policy(), evaluated_at=NOW + timedelta(seconds=1))
        with pytest.raises(CanonicalParserShadowWorkerError):
            run_shadow_worker_iteration(db, confirmation=preview["confirmation"], owner_id=OWNER, settings_object=_policy(), started_at=NOW + timedelta(seconds=1), completed_at=NOW + timedelta(seconds=2))
        state = db.scalar(select(CanonicalParserShadowSchedulerWorkerState))
        assert state.consecutive_failures == 1
        iteration = db.scalar(select(CanonicalParserShadowSchedulerWorkerIteration))
        assert iteration.status == "FAILED"


def test_m19_kill_and_reset(db_factory):
    with db_factory() as db:
        _start(db)
        state = db.scalar(select(CanonicalParserShadowSchedulerWorkerState))
        killed = control_shadow_worker(db, action="KILL", confirmation=_control(SHADOW_WORKER_KILL_PREFIX, state), owner_id=OWNER, reason="operator stop", settings_object=_policy(), occurred_at=NOW + timedelta(seconds=3))
        assert killed["status"] == "KILLED"
        state = db.scalar(select(CanonicalParserShadowSchedulerWorkerState))
        reset = control_shadow_worker(db, action="RESET", confirmation=_control(SHADOW_WORKER_RESET_PREFIX, state), owner_id=OWNER, reason="reviewed", settings_object=_policy(), occurred_at=NOW + timedelta(seconds=4))
        assert reset["status"] == "STOPPED"


def test_m19_audit_tampering_blocks_readiness(db_factory):
    with db_factory() as db:
        _start(db)
        event = db.scalar(select(CanonicalParserShadowSchedulerWorkerEvent))
        event.event_hash = "f" * 64
        db.commit()
        state = get_shadow_worker_state(db, settings_object=_policy(), evaluated_at=NOW)
        assert state["audit_chain_valid"] is False
        assert state["worker_ready"] is False


def test_m19_status_counts(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db)
        _patch_scheduler(monkeypatch, tickable=False)
        preview = preview_shadow_worker_iteration(db, owner_id=OWNER, settings_object=_policy(), evaluated_at=NOW + timedelta(seconds=1))
        run_shadow_worker_iteration(db, confirmation=preview["confirmation"], owner_id=OWNER, settings_object=_policy(), started_at=NOW + timedelta(seconds=1), completed_at=NOW + timedelta(seconds=2))
        status = get_shadow_worker_status(db, settings_object=_policy())
        assert status["iteration_status_counts"]["IDLE"] == 1
        assert status["operational_guards"]["background_loop_connected"] is False


def test_m19_models_registered():
    names = set(Base.metadata.tables)
    assert "canonical_parser_shadow_scheduler_worker_states" in names
    assert "canonical_parser_shadow_scheduler_worker_events" in names
    assert "canonical_parser_shadow_scheduler_worker_iterations" in names
    assert models.CanonicalParserShadowSchedulerWorkerState is CanonicalParserShadowSchedulerWorkerState


def test_m19_service_has_no_network_trade_paper_live_or_thread():
    path = Path("backend/app/services/blockchain_parser_shadow_worker_service.py")
    tree = ast.parse(path.read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module: imports.add(node.module.split(".")[0])
    assert not imports & {"httpx", "requests", "aiohttp", "threading", "asyncio"}
    source = path.read_text()
    assert "Trade(" not in source and "PaperOrder(" not in source and "LiveCopyOrder(" not in source
    assert '"background_loop_connected": False' in source


def test_m19_api_routes_are_protected_and_unique(db_factory):
    expected = {
        ("GET", "/integrity/parser-shadow-worker/status"),
        ("GET", "/integrity/parser-shadow-worker/state"),
        ("GET", "/integrity/parser-shadow-worker/start-preview"),
        ("POST", "/integrity/parser-shadow-worker/start"),
        ("POST", "/integrity/parser-shadow-worker/stop"),
        ("POST", "/integrity/parser-shadow-worker/kill"),
        ("POST", "/integrity/parser-shadow-worker/reset"),
        ("POST", "/integrity/parser-shadow-worker/heartbeat"),
        ("GET", "/integrity/parser-shadow-worker/iteration-preview"),
        ("POST", "/integrity/parser-shadow-worker/iterate"),
        ("GET", "/integrity/parser-shadow-worker/iterations/{iteration_id}"),
    }
    counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set(): counts[(method, route.path)] += 1
    for route in expected: assert counts[route] == 1
    client = _client(db_factory)
    try:
        for method, path in expected:
            actual = path.replace("{iteration_id}", str(uuid4()))
            if "preview" in actual: actual += "?owner_id=worker-a"
            assert client.request(method, actual).status_code in {401, 403}
    finally:
        app.dependency_overrides.clear()


def test_m19_migration_round_trip():
    path = Path("alembic/versions/f5a1c8e3d729_add_shadow_scheduler_worker_runtime.py")
    spec = importlib.util.spec_from_file_location("m19_migration", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.down_revision == "e3b7c9d4f821"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[CanonicalParserShadowSchedulerTick.__table__])
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection)); original = module.op; module.op = operations
        try:
            module.upgrade(); names = set(inspect(connection).get_table_names())
            assert "canonical_parser_shadow_scheduler_worker_iterations" in names
            module.downgrade(); assert "canonical_parser_shadow_scheduler_worker_states" not in set(inspect(connection).get_table_names())
        finally: module.op = original
    engine.dispose()
