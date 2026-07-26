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
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app import models
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowSchedulerWorkerIteration,
    CanonicalParserShadowSchedulerWorkerState,
    CanonicalParserShadowWorkerLoopRun,
    CanonicalParserShadowWorkerRecoveryAction,
    CanonicalParserShadowWorkerRecoveryRun,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
from backend.app.services.blockchain_parser_shadow_worker_recovery_service import (
    CanonicalParserShadowWorkerRecoveryError,
    get_shadow_worker_recovery_status,
    preview_shadow_worker_recovery,
    run_shadow_worker_recovery,
)
from backend.app.services.blockchain_parser_shadow_worker_service import (
    get_shadow_worker_state,
    preview_shadow_worker_start,
    start_shadow_worker,
)

NOW = datetime(2026, 7, 26, 21, 0, tzinfo=timezone.utc)
OWNER = "worker-recovery-a"
AUTOMATION_KEY = "a" * 32


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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_ENABLED", False)


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test",
    }
    values.update(overrides)
    return values


def _policy(enabled=True):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_WORKER_ENABLED=True,
        CANONICAL_PARSER_SHADOW_WORKER_LEASE_TTL_SECONDS=120,
        CANONICAL_PARSER_SHADOW_WORKER_HEARTBEAT_TIMEOUT_SECONDS=180,
        CANONICAL_PARSER_SHADOW_WORKER_MAX_CONSECUTIVE_FAILURES=3,
        CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_ENABLED=enabled,
        CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_STALE_AFTER_SECONDS=300,
        CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_MAX_TARGETS=100,
    )


def _seed_stale(db):
    policy = _policy()
    started = NOW - timedelta(minutes=20)
    preview = preview_shadow_worker_start(owner_id=OWNER, settings_object=policy)
    start_shadow_worker(
        db,
        confirmation=preview["confirmation"],
        owner_id=OWNER,
        settings_object=policy,
        started_at=started,
    )
    state = db.query(CanonicalParserShadowSchedulerWorkerState).one()
    iteration = CanonicalParserShadowSchedulerWorkerIteration(
        iteration_id=str(uuid4()),
        iteration_key=calculate_payload_hash({"iteration": "stale"}),
        worker_state_db_id=state.id,
        worker_generation=state.generation,
        lease_epoch=state.lease_epoch,
        owner_id=OWNER,
        scheduler_generation=1,
        tick_db_id=None,
        tick_id=None,
        cycle_id=None,
        status="RUNNING",
        raw_event_ids=[],
        actor_label="TEST",
        note=None,
        reason_codes=[],
        scheduler_preview={},
        tick_snapshot={},
        technical_metadata={},
        started_at=NOW - timedelta(minutes=10),
        completed_at=None,
    )
    db.add(iteration)
    db.flush()
    loop = CanonicalParserShadowWorkerLoopRun(
        loop_id=str(uuid4()),
        loop_key=calculate_payload_hash({"loop": "stale"}),
        worker_state_db_id=state.id,
        worker_generation=state.generation,
        lease_epoch=state.lease_epoch,
        owner_id=OWNER,
        status="RUNNING",
        requested_iterations=3,
        completed_iterations=0,
        passed_iterations=0,
        partial_iterations=0,
        idle_iterations=0,
        failed_iterations=0,
        skipped_iterations=0,
        max_consecutive_failures=2,
        observed_consecutive_failures=0,
        circuit_breaker_open=False,
        kill_switch_enforced=False,
        actor_label="TEST",
        note=None,
        stop_reason=None,
        policy_snapshot={},
        summary={},
        started_at=NOW - timedelta(minutes=10),
        completed_at=None,
    )
    db.add(loop)
    db.commit()
    return state, iteration, loop


def _client(factory):
    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m21_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_STALE_AFTER_SECONDS == 300
    assert configured.CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_MAX_TARGETS == 100


def test_m21_preview_detects_stale_targets(db_factory):
    with db_factory() as db:
        _seed_stale(db)
        preview = preview_shadow_worker_recovery(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["recoverable"] is True
        assert preview["detected_worker_count"] == 1
        assert preview["detected_iteration_count"] == 1
        assert preview["detected_loop_count"] == 1


def test_m21_recovery_closes_stale_state_atomically(db_factory):
    with db_factory() as db:
        state, iteration, loop = _seed_stale(db)
        preview = preview_shadow_worker_recovery(db, settings_object=_policy(), evaluated_at=NOW)
        result = run_shadow_worker_recovery(
            db,
            confirmation=preview["confirmation"],
            settings_object=_policy(),
            started_at=NOW,
        )
        assert result["status"] == "COMPLETED"
        assert len(result["actions"]) == 3
        db.refresh(state); db.refresh(iteration); db.refresh(loop)
        assert state.status == "STOPPED"
        assert state.owner_id is None
        assert iteration.status == "FAILED"
        assert loop.status == "STOPPED"
        assert get_shadow_worker_state(db, settings_object=_policy(), evaluated_at=NOW)["audit_chain_valid"] is True


def test_m21_retry_is_idempotent(db_factory):
    with db_factory() as db:
        _seed_stale(db)
        preview = preview_shadow_worker_recovery(db, settings_object=_policy(), evaluated_at=NOW)
        first = run_shadow_worker_recovery(db, confirmation=preview["confirmation"], settings_object=_policy(), started_at=NOW)
        second = run_shadow_worker_recovery(db, confirmation=preview["confirmation"], settings_object=_policy(), started_at=NOW)
        assert second["recovery_id"] == first["recovery_id"]
        assert db.query(CanonicalParserShadowWorkerRecoveryRun).count() == 1


def test_m21_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowWorkerRecoveryError) as error:
            run_shadow_worker_recovery(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_DISABLED"


def test_m21_noop_preview_is_not_recoverable(db_factory):
    with db_factory() as db:
        preview = preview_shadow_worker_recovery(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["recoverable"] is False
        assert "SHADOW_WORKER_RECOVERY_NO_STALE_TARGETS" in preview["reason_codes"]


def test_m21_invalid_confirmation_blocked(db_factory):
    with db_factory() as db:
        _seed_stale(db)
        with pytest.raises(CanonicalParserShadowWorkerRecoveryError) as error:
            run_shadow_worker_recovery(db, confirmation="wrong", settings_object=_policy(), started_at=NOW)
        assert error.value.code == "SHADOW_WORKER_RECOVERY_CONFIRMATION_REQUIRED"


def test_m21_status_reports_manual_only(db_factory):
    with db_factory() as db:
        status = get_shadow_worker_recovery_status(db, settings_object=_policy())
        assert status["operational_guards"]["manual_only"] is True
        assert status["operational_guards"]["automatic_recovery_connected"] is False


def test_m21_models_registered():
    names = set(Base.metadata.tables)
    assert "canonical_parser_shadow_worker_recovery_runs" in names
    assert "canonical_parser_shadow_worker_recovery_actions" in names
    assert models.CanonicalParserShadowWorkerRecoveryRun is CanonicalParserShadowWorkerRecoveryRun
    assert models.CanonicalParserShadowWorkerRecoveryAction is CanonicalParserShadowWorkerRecoveryAction


def test_m21_service_has_no_network_trade_paper_live_or_daemon():
    path = Path("backend/app/services/blockchain_parser_shadow_worker_recovery_service.py")
    tree = ast.parse(path.read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports & {"httpx", "requests", "aiohttp", "threading", "asyncio", "time"}
    source = path.read_text()
    assert "Trade(" not in source and "PaperOrder(" not in source and "LiveCopyOrder(" not in source
    assert '"automatic_recovery_connected": False' in source


def test_m21_api_routes_protected_and_unique(db_factory):
    expected = {
        ("GET", "/integrity/parser-shadow-worker-recovery/status"),
        ("GET", "/integrity/parser-shadow-worker-recovery/preview"),
        ("POST", "/integrity/parser-shadow-worker-recovery/run"),
        ("GET", "/integrity/parser-shadow-worker-recovery/runs/{recovery_id}"),
    }
    counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            counts[(method, route.path)] += 1
    for route in expected:
        assert counts[route] == 1
    client = _client(db_factory)
    try:
        for method, path in expected:
            actual = path.replace("{recovery_id}", str(uuid4()))
            assert client.request(method, actual).status_code in {401, 403}
    finally:
        app.dependency_overrides.clear()


def test_m21_migration_round_trip():
    path = Path("alembic/versions/b9f2d6a4c713_add_shadow_worker_recovery.py")
    spec = importlib.util.spec_from_file_location("m21_migration", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.down_revision == "a7e4c2d9b631"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[CanonicalParserShadowSchedulerWorkerState.__table__])
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection)); original = module.op; module.op = operations
        try:
            module.upgrade()
            assert "canonical_parser_shadow_worker_recovery_runs" in set(inspect(connection).get_table_names())
            module.downgrade()
            assert "canonical_parser_shadow_worker_recovery_runs" not in set(inspect(connection).get_table_names())
        finally:
            module.op = original
    engine.dispose()
