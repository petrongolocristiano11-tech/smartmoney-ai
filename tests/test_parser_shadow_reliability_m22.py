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
    CanonicalParserShadowReliabilityAssessment,
    CanonicalParserShadowReliabilityEvidenceLoop,
    CanonicalParserShadowSchedulerWorkerState,
    CanonicalParserShadowWorkerLoopRun,
    CanonicalParserShadowWorkerRecoveryAction,
    CanonicalParserShadowWorkerRecoveryRun,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
from backend.app.services.blockchain_parser_shadow_reliability_service import (
    CanonicalParserShadowReliabilityError,
    execute_shadow_reliability_assessment,
    get_shadow_reliability_status,
    preview_shadow_reliability_assessment,
    resolve_shadow_reliability,
)
from backend.app.services.blockchain_parser_shadow_worker_service import (
    preview_shadow_worker_start,
    start_shadow_worker,
)

NOW = datetime(2026, 7, 26, 22, 0, tzinfo=timezone.utc)
OWNER = "worker-reliability-a"
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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_RELIABILITY_ENABLED", False)


def _settings_values(**overrides):
    values={"DATABASE_URL":"sqlite+pysqlite:///:memory:","SOLANA_RPC_URL":"https://api.mainnet-beta.solana.com","HELIUS_API_KEY":"test"}
    values.update(overrides); return values


def _policy(enabled=True, min_rate=95.0):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_WORKER_ENABLED=True,
        CANONICAL_PARSER_SHADOW_WORKER_LEASE_TTL_SECONDS=3600,
        CANONICAL_PARSER_SHADOW_WORKER_HEARTBEAT_TIMEOUT_SECONDS=3600,
        CANONICAL_PARSER_SHADOW_WORKER_MAX_CONSECUTIVE_FAILURES=3,
        CANONICAL_PARSER_SHADOW_RELIABILITY_ENABLED=enabled,
        CANONICAL_PARSER_SHADOW_RELIABILITY_LOOKBACK_MINUTES=60,
        CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_LOOP_RUNS=3,
        CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_ITERATIONS=10,
        CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_PASS_RATE=min_rate,
        CANONICAL_PARSER_SHADOW_RELIABILITY_MAX_FAILED_ITERATIONS=0,
        CANONICAL_PARSER_SHADOW_RELIABILITY_MAX_CIRCUIT_OPEN_RUNS=0,
        CANONICAL_PARSER_SHADOW_RELIABILITY_MAX_RECOVERY_ACTIONS=0,
        CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_OBSERVATION_MINUTES=5,
        CANONICAL_PARSER_SHADOW_RELIABILITY_VALIDITY_MINUTES=15,
    )


def _start(db):
    policy=_policy(); preview=preview_shadow_worker_start(owner_id=OWNER,settings_object=policy)
    start_shadow_worker(db,confirmation=preview["confirmation"],owner_id=OWNER,settings_object=policy,started_at=NOW-timedelta(minutes=20))
    return db.query(CanonicalParserShadowSchedulerWorkerState).one()


def _add_loop(db,state,index,*,passed=4,partial=0,failed=0,circuit=False,status="COMPLETED"):
    completed=passed+partial+failed
    loop=CanonicalParserShadowWorkerLoopRun(
        loop_id=str(uuid4()), loop_key=calculate_payload_hash({"loop":index,"passed":passed,"partial":partial,"failed":failed,"circuit":circuit}),
        worker_state_db_id=state.id, worker_generation=state.generation, lease_epoch=state.lease_epoch,
        owner_id=OWNER,status=status,requested_iterations=max(completed,1),completed_iterations=completed,
        passed_iterations=passed,partial_iterations=partial,idle_iterations=0,failed_iterations=failed,skipped_iterations=0,
        max_consecutive_failures=2,observed_consecutive_failures=failed,circuit_breaker_open=circuit,kill_switch_enforced=False,
        actor_label="TEST",note=None,stop_reason=None,policy_snapshot={"v":1},summary={"index":index},
        started_at=NOW-timedelta(minutes=12-index*4),completed_at=NOW-timedelta(minutes=11-index*4),
    )
    db.add(loop); db.commit(); return loop


def _seed_ready(db):
    state=_start(db)
    for i in range(3): _add_loop(db,state,i)
    return state


def _add_recovery_action(db,state):
    run=CanonicalParserShadowWorkerRecoveryRun(
        recovery_id=str(uuid4()),recovery_key=calculate_payload_hash({"recovery":"incident"}),worker_state_db_id=state.id,
        worker_generation=state.generation,lease_epoch=state.lease_epoch,owner_id=OWNER,status="COMPLETED",
        detected_worker_count=1,detected_iteration_count=0,detected_loop_count=0,recovered_worker_count=1,recovered_iteration_count=0,recovered_loop_count=0,
        actor_label="TEST",note=None,reason_codes=[],target_snapshot={},policy_version="test",policy_hash=calculate_payload_hash({"p":1}),policy_snapshot={},summary={},
        started_at=NOW-timedelta(minutes=2),completed_at=NOW-timedelta(minutes=2),
    )
    db.add(run); db.flush()
    db.add(CanonicalParserShadowWorkerRecoveryAction(
        recovery_run_db_id=run.id,sequence=1,target_type="WORKER_STATE",target_id="worker",action_type="STOP_STALE_WORKER",
        previous_status="ACTIVE",new_status="STOPPED",reason_codes=["incident"],snapshot_before={},snapshot_after={},occurred_at=NOW-timedelta(minutes=2),
    )); db.commit()


def _client(factory):
    def override_db():
        db=factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override_db
    return TestClient(app)


def test_m22_settings_defaults_fail_closed():
    configured=Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_RELIABILITY_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_LOOP_RUNS == 3
    assert configured.CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_PASS_RATE == 95.0


def test_m22_preview_ready_with_stable_evidence(db_factory):
    with db_factory() as db:
        _seed_ready(db)
        preview=preview_shadow_reliability_assessment(db,settings_object=_policy(),evaluated_at=NOW)
        assert preview["status"] == "READY"
        assert preview["metrics"]["loop_count"] == 3
        assert preview["metrics"]["completed_iteration_count"] == 12
        assert preview["paper_authorized"] is False


def test_m22_insufficient_without_evidence(db_factory):
    with db_factory() as db:
        _start(db)
        preview=preview_shadow_reliability_assessment(db,settings_object=_policy(),evaluated_at=NOW)
        assert preview["status"] == "INSUFFICIENT_DATA"


def test_m22_review_for_low_pass_rate_without_failures(db_factory):
    with db_factory() as db:
        state=_start(db)
        _add_loop(db,state,0,passed=3,partial=1); _add_loop(db,state,1,passed=3,partial=1); _add_loop(db,state,2,passed=3,partial=1)
        preview=preview_shadow_reliability_assessment(db,settings_object=_policy(),evaluated_at=NOW)
        assert preview["status"] == "REVIEW"
        assert preview["metrics"]["pass_rate"] == 75.0


def test_m22_blocked_for_failed_iteration(db_factory):
    with db_factory() as db:
        state=_start(db)
        _add_loop(db,state,0); _add_loop(db,state,1); _add_loop(db,state,2,passed=3,failed=1)
        preview=preview_shadow_reliability_assessment(db,settings_object=_policy(),evaluated_at=NOW)
        assert preview["status"] == "BLOCKED"
        assert "SHADOW_RELIABILITY_FAILED_ITERATIONS_EXCEEDED" in preview["reason_codes"]


def test_m22_blocked_for_circuit_open(db_factory):
    with db_factory() as db:
        state=_start(db)
        _add_loop(db,state,0); _add_loop(db,state,1); _add_loop(db,state,2,circuit=True,status="CIRCUIT_OPEN")
        preview=preview_shadow_reliability_assessment(db,settings_object=_policy(),evaluated_at=NOW)
        assert preview["status"] == "BLOCKED"


def test_m22_blocked_for_recent_recovery_action(db_factory):
    with db_factory() as db:
        state=_seed_ready(db); _add_recovery_action(db,state)
        preview=preview_shadow_reliability_assessment(db,settings_object=_policy(),evaluated_at=NOW)
        assert preview["status"] == "BLOCKED"
        assert preview["metrics"]["recovery_action_count"] == 1


def test_m22_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowReliabilityError) as error:
            execute_shadow_reliability_assessment(db,confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_SHADOW_RELIABILITY_DISABLED"


def test_m22_persistence_and_idempotency(db_factory):
    with db_factory() as db:
        _seed_ready(db)
        preview=preview_shadow_reliability_assessment(db,settings_object=_policy(),evaluated_at=NOW)
        first=execute_shadow_reliability_assessment(db,confirmation=preview["confirmation"],settings_object=_policy(),evaluated_at=NOW)
        second=execute_shadow_reliability_assessment(db,confirmation=preview["confirmation"],settings_object=_policy(),evaluated_at=NOW)
        assert first["assessment_id"] == second["assessment_id"]
        assert db.query(CanonicalParserShadowReliabilityEvidenceLoop).count() == 3


def test_m22_resolve_ready_and_expired(db_factory):
    with db_factory() as db:
        _seed_ready(db)
        preview=preview_shadow_reliability_assessment(db,settings_object=_policy(),evaluated_at=NOW)
        execute_shadow_reliability_assessment(db,confirmation=preview["confirmation"],settings_object=_policy(),evaluated_at=NOW)
        assert resolve_shadow_reliability(db,settings_object=_policy(),evaluated_at=NOW)["resolved_status"] == "READY"
        assert resolve_shadow_reliability(db,settings_object=_policy(),evaluated_at=NOW+timedelta(minutes=16))["resolved_status"] == "EXPIRED"


def test_m22_resolve_detects_loop_drift(db_factory):
    with db_factory() as db:
        _seed_ready(db)
        preview=preview_shadow_reliability_assessment(db,settings_object=_policy(),evaluated_at=NOW)
        execute_shadow_reliability_assessment(db,confirmation=preview["confirmation"],settings_object=_policy(),evaluated_at=NOW)
        loop=db.query(CanonicalParserShadowWorkerLoopRun).first(); loop.summary={"tampered":True}; db.commit()
        assert resolve_shadow_reliability(db,settings_object=_policy(),evaluated_at=NOW)["resolved_status"] == "DRIFTED"


def test_m22_status_is_evidence_only(db_factory):
    with db_factory() as db:
        status=get_shadow_reliability_status(db,settings_object=_policy())
        assert status["operational_guards"]["manual_assessment_only"] is True
        assert status["operational_guards"]["paper_admission_connected"] is False


def test_m22_models_registered():
    names=set(Base.metadata.tables)
    assert "canonical_parser_shadow_reliability_assessments" in names
    assert "canonical_parser_shadow_reliability_evidence_loops" in names
    assert models.CanonicalParserShadowReliabilityAssessment is CanonicalParserShadowReliabilityAssessment


def test_m22_service_has_no_network_trade_paper_live_or_worker_loop():
    path=Path("backend/app/services/blockchain_parser_shadow_reliability_service.py")
    tree=ast.parse(path.read_text()); imports=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import): imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node,ast.ImportFrom) and node.module: imports.add(node.module.split(".")[0])
    assert not imports & {"httpx","requests","aiohttp","threading","asyncio","time"}
    source=path.read_text()
    assert "Trade(" not in source and "PaperOrder(" not in source and "LiveCopyOrder(" not in source
    assert '"paper_admission_connected": False' in source


def test_m22_api_routes_protected_and_unique(db_factory):
    expected={("GET","/integrity/parser-shadow-reliability/status"),("GET","/integrity/parser-shadow-reliability/preview"),("POST","/integrity/parser-shadow-reliability/assess"),("GET","/integrity/parser-shadow-reliability/assessments/{assessment_id}"),("GET","/integrity/parser-shadow-reliability/resolve")}
    counts=Counter()
    for route in app.routes:
        for method in getattr(route,"methods",set()) or set(): counts[(method,route.path)]+=1
    for route in expected: assert counts[route]==1
    client=_client(db_factory)
    try:
        for method,path in expected:
            actual=path.replace("{assessment_id}",str(uuid4()))
            assert client.request(method,actual).status_code in {401,403}
    finally: app.dependency_overrides.clear()


def test_m22_migration_round_trip():
    path=Path("alembic/versions/c1a8e5d3f924_add_shadow_reliability_gate.py")
    spec=importlib.util.spec_from_file_location("m22_migration",path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.down_revision=="b9f2d6a4c713"
    engine=create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine,tables=[CanonicalParserShadowSchedulerWorkerState.__table__,CanonicalParserShadowWorkerLoopRun.__table__])
    with engine.begin() as connection:
        operations=Operations(MigrationContext.configure(connection)); original=module.op; module.op=operations
        try:
            module.upgrade(); assert "canonical_parser_shadow_reliability_assessments" in set(inspect(connection).get_table_names())
            module.downgrade(); assert "canonical_parser_shadow_reliability_assessments" not in set(inspect(connection).get_table_names())
        finally: module.op=original
    engine.dispose()
