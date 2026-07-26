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
    CanonicalParserShadowAutomationCycle,
    CanonicalParserShadowAutomationCycleEvent,
    CanonicalParserShadowSchedulerEvent,
    CanonicalParserShadowSchedulerState,
    CanonicalParserShadowSchedulerTick,
)
from backend.app.services import blockchain_parser_shadow_scheduler_service as service_module
from backend.app.services.blockchain_parser_shadow_automation_cycle_service import (
    CanonicalParserShadowAutomationCycleError,
)
from backend.app.services.blockchain_parser_shadow_scheduler_service import (
    SHADOW_SCHEDULER_HEARTBEAT_PREFIX,
    SHADOW_SCHEDULER_KILL_PREFIX,
    SHADOW_SCHEDULER_NAME,
    SHADOW_SCHEDULER_POLICY_VERSION,
    SHADOW_SCHEDULER_RESET_PREFIX,
    SHADOW_SCHEDULER_START_PREFIX,
    SHADOW_SCHEDULER_STOP_PREFIX,
    SHADOW_SCHEDULER_TICK_PREFIX,
    CanonicalParserShadowSchedulerError,
    engage_shadow_scheduler_kill_switch,
    get_shadow_scheduler_state,
    get_shadow_scheduler_status,
    get_shadow_scheduler_tick,
    heartbeat_shadow_scheduler,
    preview_shadow_scheduler_start,
    preview_shadow_scheduler_tick,
    reset_shadow_scheduler_kill_switch,
    run_shadow_scheduler_tick,
    start_shadow_scheduler,
    stop_shadow_scheduler,
)

AUTOMATION_KEY = "a" * 32
NOW = datetime(2026, 7, 26, 18, 0, tzinfo=timezone.utc)
PERMIT_ID = str(uuid4())


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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED", False)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_ENABLED", False)
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


def _policy(*, enabled=True, heartbeat=300, lock_ttl=180, min_interval=300):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED=enabled,
        CANONICAL_PARSER_SHADOW_SCHEDULER_MIN_INTERVAL_SECONDS=min_interval,
        CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_INTERVAL_SECONDS=3600,
        CANONICAL_PARSER_SHADOW_SCHEDULER_LOCK_TTL_SECONDS=lock_ttl,
        CANONICAL_PARSER_SHADOW_SCHEDULER_HEARTBEAT_TIMEOUT_SECONDS=heartbeat,
        CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_EVENT_RESERVATION=25,
        CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_EXECUTION_LIMIT=25,
        CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_ENABLED=True,
        CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EVENT_RESERVATION=25,
        CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EXECUTION_LIMIT=25,
        CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_TICKET_VALIDITY_SECONDS=120,
    )


def _start(db, *, now=NOW, settings_object=None, permit_id=PERMIT_ID):
    policy = settings_object or _policy()
    preview = preview_shadow_scheduler_start(
        permit_id=permit_id,
        interval_seconds=300,
        event_reservation=5,
        limit=3,
        settings_object=policy,
    )
    return start_shadow_scheduler(
        db,
        confirmation=preview["confirmation"],
        permit_id=permit_id,
        interval_seconds=300,
        event_reservation=5,
        limit=3,
        actor_label="scheduler<script>",
        note="manual control plane",
        settings_object=policy,
        started_at=now,
    )


def _control(prefix, state):
    return f"{prefix}:{state.generation}:{(state.latest_event_hash or '0' * 64)[:16]}"


def _patch_cycle(monkeypatch, *, status="PASSED", fail=False):
    monkeypatch.setattr(
        service_module,
        "preview_shadow_automation_cycle",
        lambda *args, **kwargs: {
            "eligible": True,
            "blocker_codes": [],
            "confirmation": "RUN-CYCLE",
            "cycle_key": "c" * 64,
            "permit_id": kwargs.get("permit_id"),
        },
    )
    if fail:
        def raise_failure(*args, **kwargs):
            raise CanonicalParserShadowAutomationCycleError(
                "cycle failed", code="TEST_CYCLE_FAILURE", status_code=409
            )
        monkeypatch.setattr(service_module, "run_shadow_automation_cycle", raise_failure)
    else:
        monkeypatch.setattr(
            service_module,
            "run_shadow_automation_cycle",
            lambda *args, **kwargs: {
                "cycle_id": str(uuid4()),
                "status": status,
                "reason_codes": [] if status == "PASSED" else ["TEST_PARTIAL"],
                "processed_count": 3,
                "budget_settled": True,
            },
        )


def _client(factory):
    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m18_settings_defaults_are_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_SCHEDULER_MIN_INTERVAL_SECONDS == 300
    assert configured.CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_INTERVAL_SECONDS == 3600
    assert configured.CANONICAL_PARSER_SHADOW_SCHEDULER_LOCK_TTL_SECONDS == 180
    assert configured.CANONICAL_PARSER_SHADOW_SCHEDULER_HEARTBEAT_TIMEOUT_SECONDS == 300


def test_m18_constants_are_stable():
    assert SHADOW_SCHEDULER_POLICY_VERSION == "canonical-parser-shadow-scheduler/1"
    assert SHADOW_SCHEDULER_NAME == "CANONICAL_SHADOW_AUTOMATION"
    assert SHADOW_SCHEDULER_START_PREFIX == "START_CERTIFIED_SHADOW_SCHEDULER"
    assert SHADOW_SCHEDULER_TICK_PREFIX == "TICK_CERTIFIED_SHADOW_SCHEDULER"


def test_m18_status_without_state_is_stopped(db_factory):
    with db_factory() as db:
        status = get_shadow_scheduler_status(db)
        assert status["scheduler_enabled"] is False
        assert status["state"]["exists"] is False
        assert status["state"]["status"] == "STOPPED"
        assert status["operational_guards"]["automatic_loop_connected"] is False


def test_m18_start_preview_validates_bounds():
    preview = preview_shadow_scheduler_start(
        permit_id=PERMIT_ID,
        interval_seconds=10,
        event_reservation=5,
        limit=6,
        settings_object=_policy(),
    )
    assert preview["startable"] is False
    assert "SHADOW_SCHEDULER_INTERVAL_BELOW_MINIMUM" in preview["reason_codes"]
    assert "SHADOW_SCHEDULER_LIMIT_EXCEEDS_RESERVATION" in preview["reason_codes"]


def test_m18_start_disabled_by_default(db_factory):
    with db_factory() as db:
        preview = preview_shadow_scheduler_start(permit_id=PERMIT_ID, settings_object=_policy())
        with pytest.raises(CanonicalParserShadowSchedulerError) as error:
            start_shadow_scheduler(
                db,
                confirmation=preview["confirmation"],
                permit_id=PERMIT_ID,
            )
        assert error.value.code == "CANONICAL_PARSER_SHADOW_SCHEDULER_DISABLED"


def test_m18_start_requires_confirmation(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowSchedulerError) as error:
            start_shadow_scheduler(
                db,
                confirmation="stale",
                permit_id=PERMIT_ID,
                settings_object=_policy(),
                started_at=NOW,
            )
        assert error.value.code == "SHADOW_SCHEDULER_START_CONFIRMATION_REQUIRED"


def test_m18_start_persists_running_state_and_audit(db_factory):
    with db_factory() as db:
        state = _start(db)
        assert state["status"] == "RUNNING"
        assert state["generation"] == 1
        assert state["kill_switch_engaged"] is False
        assert state["scheduler_ready"] is True
        assert state["audit_chain_valid"] is True
        assert db.query(CanonicalParserShadowSchedulerEvent).count() == 1


def test_m18_start_is_idempotent_while_running(db_factory):
    with db_factory() as db:
        first = _start(db)
        second = _start(db)
        assert second["generation"] == first["generation"]
        assert db.query(CanonicalParserShadowSchedulerState).count() == 1
        assert db.query(CanonicalParserShadowSchedulerEvent).count() == 1


def test_m18_heartbeat_updates_state(db_factory):
    with db_factory() as db:
        _start(db)
        state = db.scalar(select(CanonicalParserShadowSchedulerState))
        result = heartbeat_shadow_scheduler(
            db,
            confirmation=_control(SHADOW_SCHEDULER_HEARTBEAT_PREFIX, state),
            actor_label="heartbeat",
            heartbeat_at=NOW + timedelta(seconds=30),
        )
        heartbeat = result["heartbeat_at"]
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        assert heartbeat == NOW + timedelta(seconds=30)
        assert result["latest_event_sequence"] == 2


def test_m18_heartbeat_stale_fails_readiness(db_factory):
    with db_factory() as db:
        _start(db)
        result = get_shadow_scheduler_state(
            db,
            settings_object=_policy(heartbeat=10),
            evaluated_at=NOW + timedelta(seconds=20),
        )
        assert result["heartbeat_stale"] is True
        assert result["scheduler_ready"] is False


def test_m18_stop_clears_lock_and_stops(db_factory):
    with db_factory() as db:
        _start(db)
        state = db.scalar(select(CanonicalParserShadowSchedulerState))
        state.lock_token_hash = "f" * 64
        state.lock_expires_at = NOW + timedelta(seconds=100)
        db.commit()
        result = stop_shadow_scheduler(
            db,
            confirmation=_control(SHADOW_SCHEDULER_STOP_PREFIX, state),
            reason="operator stop",
            stopped_at=NOW + timedelta(seconds=5),
        )
        assert result["status"] == "STOPPED"
        assert result["lock_token_hash"] is None


def test_m18_kill_switch_and_reset(db_factory):
    with db_factory() as db:
        _start(db)
        state = db.scalar(select(CanonicalParserShadowSchedulerState))
        killed = engage_shadow_scheduler_kill_switch(
            db,
            confirmation=_control(SHADOW_SCHEDULER_KILL_PREFIX, state),
            reason="emergency stop",
            killed_at=NOW + timedelta(seconds=5),
        )
        assert killed["status"] == "KILLED"
        assert killed["kill_switch_engaged"] is True
        state = db.scalar(select(CanonicalParserShadowSchedulerState))
        reset = reset_shadow_scheduler_kill_switch(
            db,
            confirmation=_control(SHADOW_SCHEDULER_RESET_PREFIX, state),
            reason="review complete",
            reset_at=NOW + timedelta(seconds=10),
        )
        assert reset["status"] == "STOPPED"
        assert reset["kill_switch_engaged"] is False
        assert reset["generation"] == 2


def test_m18_tick_preview_requires_running_state(db_factory, monkeypatch):
    with db_factory() as db:
        _patch_cycle(monkeypatch)
        preview = preview_shadow_scheduler_tick(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["tickable"] is False
        assert "SHADOW_SCHEDULER_STATE_MISSING" in preview["reason_codes"]


def test_m18_tick_preview_detects_lock_and_interval(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db)
        _patch_cycle(monkeypatch)
        state = db.scalar(select(CanonicalParserShadowSchedulerState))
        state.lock_token_hash = "a" * 64
        state.lock_expires_at = NOW + timedelta(seconds=100)
        state.next_run_not_before = NOW + timedelta(seconds=100)
        db.commit()
        preview = preview_shadow_scheduler_tick(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["tickable"] is False
        assert "SHADOW_SCHEDULER_LOCK_HELD" in preview["reason_codes"]
        assert "SHADOW_SCHEDULER_INTERVAL_NOT_ELAPSED" in preview["reason_codes"]


def test_m18_tick_success_acquires_and_releases_lock(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db)
        _patch_cycle(monkeypatch, status="PASSED")
        preview = preview_shadow_scheduler_tick(db, settings_object=_policy(), evaluated_at=NOW)
        result = run_shadow_scheduler_tick(
            db,
            confirmation=preview["confirmation"],
            actor_label="tick",
            note="manual scheduler tick",
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=20),
        )
        assert result["status"] == "PASSED"
        assert result["cycle_id"]
        state = db.scalar(select(CanonicalParserShadowSchedulerState))
        assert state.lock_token_hash is None
        assert state.latest_tick_id == result["tick_id"]
        assert state.latest_cycle_id == result["cycle_id"]
        next_run = state.next_run_not_before
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
        assert next_run == NOW + timedelta(seconds=320)


def test_m18_tick_partial_is_preserved(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db)
        _patch_cycle(monkeypatch, status="PARTIAL")
        preview = preview_shadow_scheduler_tick(db, settings_object=_policy(), evaluated_at=NOW)
        result = run_shadow_scheduler_tick(
            db,
            confirmation=preview["confirmation"],
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
        )
        assert result["status"] == "PARTIAL"
        assert "TEST_PARTIAL" in result["reason_codes"]


def test_m18_tick_failure_releases_lock_and_persists_failed_tick(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db)
        _patch_cycle(monkeypatch, fail=True)
        preview = preview_shadow_scheduler_tick(db, settings_object=_policy(), evaluated_at=NOW)
        with pytest.raises(CanonicalParserShadowSchedulerError) as error:
            run_shadow_scheduler_tick(
                db,
                confirmation=preview["confirmation"],
                settings_object=_policy(),
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=10),
            )
        assert error.value.code == "SHADOW_SCHEDULER_TICK_CYCLE_FAILED"
        tick = db.scalar(select(CanonicalParserShadowSchedulerTick))
        state = db.scalar(select(CanonicalParserShadowSchedulerState))
        assert tick.status == "FAILED"
        assert tick.reason_codes == ["TEST_CYCLE_FAILURE"]
        assert state.lock_token_hash is None


def test_m18_tick_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowSchedulerError) as error:
            run_shadow_scheduler_tick(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_SHADOW_SCHEDULER_DISABLED"


def test_m18_audit_tampering_blocks_scheduler_readiness(db_factory):
    with db_factory() as db:
        _start(db)
        event = db.scalar(select(CanonicalParserShadowSchedulerEvent))
        event.event_hash = "f" * 64
        db.commit()
        state = get_shadow_scheduler_state(db, settings_object=_policy(), evaluated_at=NOW)
        assert state["audit_chain_valid"] is False
        assert state["scheduler_ready"] is False


def test_m18_get_tick_not_found(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowSchedulerError) as error:
            get_shadow_scheduler_tick(db, str(uuid4()))
        assert error.value.status_code == 404


def test_m18_models_registered():
    names = set(Base.metadata.tables)
    assert "canonical_parser_shadow_scheduler_states" in names
    assert "canonical_parser_shadow_scheduler_events" in names
    assert "canonical_parser_shadow_scheduler_ticks" in names
    assert models.CanonicalParserShadowSchedulerState is CanonicalParserShadowSchedulerState
    assert models.CanonicalParserShadowSchedulerEvent is CanonicalParserShadowSchedulerEvent
    assert models.CanonicalParserShadowSchedulerTick is CanonicalParserShadowSchedulerTick


def test_m18_service_has_no_network_live_paper_or_trade_writes():
    path = Path("backend/app/services/blockchain_parser_shadow_scheduler_service.py")
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
    assert '"automatic_loop_connected": False' in source
    assert '"worker_connected": False' in source


def test_m18_service_not_imported_by_workers_or_live_pipelines():
    forbidden = []
    for path in Path("backend/app").rglob("*.py"):
        if path.name in {
            "main.py",
            "blockchain_parser_shadow_scheduler_service.py",
            "blockchain_parser_shadow_worker_service.py",
            "blockchain_parser_shadow_worker_loop_service.py",
        }:
            continue
        if "blockchain_parser_shadow_scheduler_service" in path.read_text(encoding="utf-8"):
            forbidden.append(str(path))
    assert forbidden == []


def test_m18_api_routes_protected_and_unique(db_factory):
    expected = {
        ("GET", "/integrity/parser-shadow-scheduler/status"),
        ("GET", "/integrity/parser-shadow-scheduler/state"),
        ("GET", "/integrity/parser-shadow-scheduler/start-preview"),
        ("POST", "/integrity/parser-shadow-scheduler/start"),
        ("POST", "/integrity/parser-shadow-scheduler/stop"),
        ("POST", "/integrity/parser-shadow-scheduler/kill"),
        ("POST", "/integrity/parser-shadow-scheduler/reset"),
        ("POST", "/integrity/parser-shadow-scheduler/heartbeat"),
        ("GET", "/integrity/parser-shadow-scheduler/tick-preview"),
        ("POST", "/integrity/parser-shadow-scheduler/tick"),
        ("GET", "/integrity/parser-shadow-scheduler/ticks/{tick_id}"),
    }
    counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            counts[(method, getattr(route, "path", ""))] += 1
    for route in expected:
        assert counts[route] == 1
    client = _client(db_factory)
    try:
        for method, path in expected:
            actual = path.replace("{tick_id}", str(uuid4()))
            if "start-preview" in actual:
                actual += f"?permit_id={PERMIT_ID}"
            response = client.request(method, actual)
            assert response.status_code in {401, 403}
    finally:
        app.dependency_overrides.clear()


def test_m18_migration_round_trip():
    path = Path("alembic/versions/e3b7c9d4f821_add_shadow_scheduler_control_plane.py")
    spec = importlib.util.spec_from_file_location("m18_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.revision == "e3b7c9d4f821"
    assert module.down_revision == "d1f5a8c3e927"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CanonicalParserShadowAutomationCycle.__table__,
            CanonicalParserShadowAutomationCycleEvent.__table__,
        ],
    )
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original = module.op
        module.op = operations
        try:
            module.upgrade()
            names = set(inspect(connection).get_table_names())
            assert "canonical_parser_shadow_scheduler_states" in names
            assert "canonical_parser_shadow_scheduler_events" in names
            assert "canonical_parser_shadow_scheduler_ticks" in names
            module.downgrade()
            assert "canonical_parser_shadow_scheduler_states" not in set(inspect(connection).get_table_names())
            module.upgrade()
            assert "canonical_parser_shadow_scheduler_ticks" in set(inspect(connection).get_table_names())
        finally:
            module.op = original
    engine.dispose()
