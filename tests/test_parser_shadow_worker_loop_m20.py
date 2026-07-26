from __future__ import annotations

import ast
import importlib.util
from collections import Counter
from datetime import datetime, timezone
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
    CanonicalParserShadowSchedulerWorkerIteration,
    CanonicalParserShadowSchedulerWorkerState,
    CanonicalParserShadowWorkerLoopIteration,
    CanonicalParserShadowWorkerLoopRun,
)
from backend.app.services import blockchain_parser_shadow_worker_loop_service as loop_module
from backend.app.services import blockchain_parser_shadow_worker_service as worker_module
from backend.app.services.blockchain_parser_shadow_worker_loop_service import (
    CanonicalParserShadowWorkerLoopError,
    get_shadow_worker_loop_status,
    preview_shadow_worker_loop,
    run_shadow_worker_loop,
)
from backend.app.services.blockchain_parser_shadow_worker_service import preview_shadow_worker_start, start_shadow_worker

NOW = datetime(2026, 7, 26, 20, 0, tzinfo=timezone.utc)
OWNER = "worker-a"
AUTOMATION_KEY = "a" * 32


@pytest.fixture()
def db_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try: yield factory
    finally: engine.dispose()


@pytest.fixture(autouse=True)
def safe_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENABLED", False)


def _settings_values(**overrides):
    values = {"DATABASE_URL": "sqlite+pysqlite:///:memory:", "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com", "HELIUS_API_KEY": "test"}
    values.update(overrides); return values


def _policy(loop_enabled=True, max_failures=2):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_WORKER_ENABLED=True,
        CANONICAL_PARSER_SHADOW_WORKER_LEASE_TTL_SECONDS=120,
        CANONICAL_PARSER_SHADOW_WORKER_HEARTBEAT_TIMEOUT_SECONDS=180,
        CANONICAL_PARSER_SHADOW_WORKER_MAX_CONSECUTIVE_FAILURES=10,
        CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENABLED=loop_enabled,
        CANONICAL_PARSER_SHADOW_WORKER_LOOP_MAX_ITERATIONS=5,
        CANONICAL_PARSER_SHADOW_WORKER_LOOP_MAX_CONSECUTIVE_FAILURES=max_failures,
        CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENFORCE_KILL_SWITCH=False,
        CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED=True,
    )


def _start(db, policy=None):
    policy = policy or _policy()
    preview = preview_shadow_worker_start(owner_id=OWNER, settings_object=policy)
    return start_shadow_worker(db, confirmation=preview["confirmation"], owner_id=OWNER, settings_object=policy, started_at=NOW)


def _patch_scheduler(monkeypatch, statuses):
    queue = list(statuses)
    def preview(*a, **k):
        stamp = str(k.get("evaluated_at") or "stable")
        from backend.app.services.blockchain_integrity_service import calculate_payload_hash
        return {
            "tickable": True, "reason_codes": [], "confirmation": "TICK",
            "tick_key": calculate_payload_hash({"stamp": stamp}), "state": {"generation": 1}
        }
    monkeypatch.setattr(worker_module, "preview_shadow_scheduler_tick", preview)
    def run(*a, **k):
        status = queue.pop(0) if queue else "PASSED"
        if status == "ERROR":
            from backend.app.services.blockchain_parser_shadow_scheduler_service import CanonicalParserShadowSchedulerError
            raise CanonicalParserShadowSchedulerError("failure", code="TEST_FAIL", status_code=409)
        return {"tick_id": str(uuid4()), "cycle_id": str(uuid4()), "status": status, "reason_codes": []}
    monkeypatch.setattr(worker_module, "run_shadow_scheduler_tick", run)


def _client(factory):
    def override_db():
        db=factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override_db
    return TestClient(app)


def test_m20_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_WORKER_LOOP_MAX_ITERATIONS == 5
    assert configured.CANONICAL_PARSER_SHADOW_WORKER_LOOP_MAX_CONSECUTIVE_FAILURES == 2


def test_m20_preview_rejects_invalid_count(db_factory):
    with db_factory() as db:
        preview = preview_shadow_worker_loop(db, owner_id=OWNER, iterations=99, settings_object=_policy())
        assert preview["runnable"] is False
        assert "SHADOW_WORKER_LOOP_ITERATION_COUNT_INVALID" in preview["reason_codes"]


def test_m20_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowWorkerLoopError) as error:
            run_shadow_worker_loop(db, confirmation="x", owner_id=OWNER)
        assert error.value.code == "CANONICAL_PARSER_SHADOW_WORKER_LOOP_DISABLED"


def test_m20_successful_bounded_loop(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db); _patch_scheduler(monkeypatch, ["PASSED", "PARTIAL", "PASSED"])
        preview = preview_shadow_worker_loop(db, owner_id=OWNER, iterations=3, settings_object=_policy(), evaluated_at=NOW)
        result = run_shadow_worker_loop(db, confirmation=preview["confirmation"], owner_id=OWNER, iterations=3, settings_object=_policy(), started_at=NOW)
        assert result["status"] == "COMPLETED"
        assert result["completed_iterations"] == 3
        assert result["passed_iterations"] == 2
        assert result["partial_iterations"] == 1
        assert db.query(CanonicalParserShadowWorkerLoopIteration).count() == 3


def test_m20_circuit_breaker_opens_after_failures(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db); _patch_scheduler(monkeypatch, ["ERROR", "ERROR", "PASSED"])
        preview = preview_shadow_worker_loop(db, owner_id=OWNER, iterations=3, settings_object=_policy(max_failures=2), evaluated_at=NOW)
        result = run_shadow_worker_loop(db, confirmation=preview["confirmation"], owner_id=OWNER, iterations=3, settings_object=_policy(max_failures=2), started_at=NOW)
        assert result["status"] == "CIRCUIT_OPEN"
        assert result["circuit_breaker_open"] is True
        assert result["completed_iterations"] == 2
        assert result["kill_switch_enforced"] is False


def test_m20_retry_is_idempotent(db_factory, monkeypatch):
    with db_factory() as db:
        _start(db); _patch_scheduler(monkeypatch, ["PASSED"])
        preview = preview_shadow_worker_loop(db, owner_id=OWNER, iterations=1, settings_object=_policy(), evaluated_at=NOW)
        first = run_shadow_worker_loop(db, confirmation=preview["confirmation"], owner_id=OWNER, iterations=1, settings_object=_policy(), started_at=NOW)
        second = run_shadow_worker_loop(db, confirmation=preview["confirmation"], owner_id=OWNER, iterations=1, settings_object=_policy(), started_at=NOW)
        assert second["loop_id"] == first["loop_id"]
        assert db.query(CanonicalParserShadowWorkerLoopRun).count() == 1


def test_m20_owner_mismatch_is_blocked(db_factory):
    with db_factory() as db:
        _start(db)
        preview = preview_shadow_worker_loop(db, owner_id="other", iterations=1, settings_object=_policy(), evaluated_at=NOW)
        assert preview["runnable"] is False
        assert "SHADOW_WORKER_LOOP_OWNER_MISMATCH" in preview["reason_codes"]


def test_m20_status_reports_no_daemon(db_factory):
    with db_factory() as db:
        status = get_shadow_worker_loop_status(db, settings_object=_policy())
        assert status["operational_guards"]["background_daemon"] is False
        assert status["operational_guards"]["sleep_calls"] is False


def test_m20_models_registered():
    names = set(Base.metadata.tables)
    assert "canonical_parser_shadow_worker_loop_runs" in names
    assert "canonical_parser_shadow_worker_loop_iterations" in names
    assert models.CanonicalParserShadowWorkerLoopRun is CanonicalParserShadowWorkerLoopRun


def test_m20_service_has_no_network_trade_paper_live_thread_or_sleep():
    path = Path("backend/app/services/blockchain_parser_shadow_worker_loop_service.py")
    tree = ast.parse(path.read_text())
    imports=set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module: imports.add(node.module.split(".")[0])
    assert not imports & {"httpx", "requests", "aiohttp", "threading", "asyncio", "time"}
    source=path.read_text()
    assert "Trade(" not in source and "PaperOrder(" not in source and "LiveCopyOrder(" not in source
    assert '"background_daemon": False' in source


def test_m20_api_routes_protected_and_unique(db_factory):
    expected={("GET","/integrity/parser-shadow-worker-loop/status"),("GET","/integrity/parser-shadow-worker-loop/preview"),("POST","/integrity/parser-shadow-worker-loop/run"),("GET","/integrity/parser-shadow-worker-loop/runs/{loop_id}")}
    counts=Counter()
    for route in app.routes:
        for method in getattr(route,"methods",set()) or set(): counts[(method,route.path)]+=1
    for route in expected: assert counts[route]==1
    client=_client(db_factory)
    try:
        for method,path in expected:
            actual=path.replace("{loop_id}",str(uuid4()))
            if "preview" in actual: actual += "?owner_id=worker-a"
            assert client.request(method,actual).status_code in {401,403}
    finally: app.dependency_overrides.clear()


def test_m20_migration_round_trip():
    path=Path("alembic/versions/a7e4c2d9b631_add_bounded_shadow_worker_loop.py")
    spec=importlib.util.spec_from_file_location("m20_migration",path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.down_revision=="f5a1c8e3d729"
    engine=create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine,tables=[CanonicalParserShadowSchedulerWorkerState.__table__,CanonicalParserShadowSchedulerWorkerIteration.__table__])
    with engine.begin() as connection:
        operations=Operations(MigrationContext.configure(connection)); original=module.op; module.op=operations
        try:
            module.upgrade(); assert "canonical_parser_shadow_worker_loop_runs" in set(inspect(connection).get_table_names())
            module.downgrade(); assert "canonical_parser_shadow_worker_loop_runs" not in set(inspect(connection).get_table_names())
        finally: module.op=original
    engine.dispose()
