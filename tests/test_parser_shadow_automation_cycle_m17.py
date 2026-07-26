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
    CanonicalParserShadowAutomationPermit,
    CanonicalParserShadowExecutionTicket,
    CanonicalParserShadowTicketExecutionRun,
    RawBlockchainEvent,
)
from backend.app.services import blockchain_parser_shadow_automation_cycle_service as service_module
from backend.app.services.blockchain_parser_registry_service import DEFAULT_PARSER_REGISTRY
from backend.app.services.blockchain_parser_shadow_automation_cycle_service import (
    AUTOMATION_CYCLE_CONFIRMATION_PREFIX,
    AUTOMATION_CYCLE_EXECUTOR,
    AUTOMATION_CYCLE_POLICY_VERSION,
    CanonicalParserShadowAutomationCycleError,
    get_shadow_automation_cycle,
    get_shadow_automation_cycle_status,
    preview_shadow_automation_cycle,
    run_shadow_automation_cycle,
)
from backend.app.services.blockchain_parser_shadow_ticket_execution_service import (
    CanonicalParserShadowTicketExecutionError,
)

AUTOMATION_KEY = "a" * 32
NOW = datetime(2026, 7, 26, 17, 0, tzinfo=timezone.utc)
DEFINITION = DEFAULT_PARSER_REGISTRY.get("swap_canonical_event", "1.0.0")


def _load_m15_helpers():
    path = Path(__file__).with_name("test_parser_shadow_execution_ticket_m15.py")
    spec = importlib.util.spec_from_file_location("m15_cycle_helpers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


M15 = _load_m15_helpers()


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
        "CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_ENABLED",
        "CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_ENABLED",
        "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_ENABLED",
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_ENABLED",
        "CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED",
        "RUN_LIVE_STREAM_WORKER",
        "RUN_LIVE_POSITION_MONITOR",
    ):
        monkeypatch.setattr(settings, name, False)


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test-helius-api-key",
    }
    values.update(overrides)
    return values


def _policy(*, enabled=True, max_events=25, max_limit=25):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_ENABLED=enabled,
        CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EVENT_RESERVATION=max_events,
        CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EXECUTION_LIMIT=max_limit,
        CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_TICKET_VALIDITY_SECONDS=120,
        CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_ENABLED=True,
        CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_VALIDITY_SECONDS=180,
        CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MIN_PERMIT_REMAINING_SECONDS=30,
        CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_EVENT_RESERVATION=25,
        CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_ENABLED=True,
        CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_MAX_SAMPLE_SIZE=25,
    )


def _permit(db, monkeypatch):
    permit = M15._create_permit(db, now=NOW, run_budget=5, event_budget=50, valid_seconds=900)
    permit.parser_implementation_hash = DEFINITION.implementation_hash
    permit.output_schema_version = DEFINITION.output_schema_version
    db.commit()
    M15._patch_permit(monkeypatch, permit)
    return permit


def _patch_execution_success(monkeypatch, *, status="PASSED", processed=2):
    monkeypatch.setattr(
        service_module,
        "preview_shadow_ticket_execution",
        lambda *args, **kwargs: {
            "eligible": True,
            "confirmation": "RUN-EXECUTION",
            "run_key": "d" * 64,
        },
    )
    monkeypatch.setattr(
        service_module,
        "run_shadow_ticket_execution",
        lambda *args, **kwargs: {
            "run_id": str(uuid4()),
            "status": status,
            "processed_count": processed,
            "passed_count": processed if status == "PASSED" else max(0, processed - 1),
            "failed_count": 0 if status == "PASSED" else 1,
            "skipped_count": 0,
            "artifact_count": processed,
            "budget_settled": True,
            "reason_codes": [] if status == "PASSED" else ["TEST_PARTIAL"],
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


def test_m17_settings_defaults_are_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EVENT_RESERVATION == 25
    assert configured.CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EXECUTION_LIMIT == 25
    assert configured.CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_TICKET_VALIDITY_SECONDS == 120


def test_m17_constants_are_stable():
    assert AUTOMATION_CYCLE_POLICY_VERSION == "canonical-parser-shadow-automation-cycle/1"
    assert AUTOMATION_CYCLE_CONFIRMATION_PREFIX == "RUN_CERTIFIED_SHADOW_AUTOMATION_CYCLE"
    assert AUTOMATION_CYCLE_EXECUTOR == "CERTIFIED_SHADOW_AUTOMATION_COORDINATOR"


def test_m17_status_defaults_disabled_and_empty(db_factory):
    with db_factory() as db:
        status = get_shadow_automation_cycle_status(db)
        assert status["cycle_enabled"] is False
        assert status["cycle_count"] == 0
        assert status["operational_guards"]["manual_only"] is True
        assert status["operational_guards"]["scheduler_connected"] is False


def test_m17_preview_is_deterministic_and_manual(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _permit(db, monkeypatch)
        first = preview_shadow_automation_cycle(
            db,
            permit_id=permit.permit_id,
            raw_event_ids=[3, 1, 3],
            event_reservation=5,
            limit=2,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        second = preview_shadow_automation_cycle(
            db,
            permit_id=permit.permit_id,
            raw_event_ids=[1, 3],
            event_reservation=5,
            limit=2,
            settings_object=_policy(),
            evaluated_at=NOW + timedelta(seconds=5),
        )
        assert first["cycle_key"] == second["cycle_key"]
        assert first["confirmation"] == second["confirmation"]
        assert first["raw_event_ids"] == [1, 3]
        assert first["manual_only"] is True
        assert first["automatic_loop_connected"] is False


@pytest.mark.parametrize(
    ("reservation", "limit", "expected"),
    [
        (0, 1, "SHADOW_AUTOMATION_CYCLE_EVENT_RESERVATION_INVALID"),
        (26, 1, "SHADOW_AUTOMATION_CYCLE_EVENT_RESERVATION_INVALID"),
        (5, 0, "SHADOW_AUTOMATION_CYCLE_LIMIT_INVALID"),
        (5, 6, "SHADOW_AUTOMATION_CYCLE_LIMIT_EXCEEDS_RESERVATION"),
    ],
)
def test_m17_preview_enforces_bounds(db_factory, monkeypatch, reservation, limit, expected):
    with db_factory() as db:
        permit = _permit(db, monkeypatch)
        preview = preview_shadow_automation_cycle(
            db,
            permit_id=permit.permit_id,
            event_reservation=reservation,
            limit=limit,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        assert preview["eligible"] is False
        assert expected in preview["blocker_codes"]


def test_m17_preview_rejects_invalid_raw_id(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowAutomationCycleError) as error:
            preview_shadow_automation_cycle(db, raw_event_ids=[0], settings_object=_policy())
        assert error.value.code == "SHADOW_AUTOMATION_CYCLE_RAW_EVENT_ID_INVALID"


def test_m17_run_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowAutomationCycleError) as error:
            run_shadow_automation_cycle(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_DISABLED"


def test_m17_run_requires_dynamic_confirmation(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _permit(db, monkeypatch)
        with pytest.raises(CanonicalParserShadowAutomationCycleError) as error:
            run_shadow_automation_cycle(
                db,
                confirmation="stale",
                permit_id=permit.permit_id,
                settings_object=_policy(),
                started_at=NOW,
            )
        assert error.value.code == "SHADOW_AUTOMATION_CYCLE_CONFIRMATION_REQUIRED"


def test_m17_success_coordinates_ticket_and_execution(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _permit(db, monkeypatch)
        _patch_execution_success(monkeypatch, processed=2)
        preview = preview_shadow_automation_cycle(
            db,
            permit_id=permit.permit_id,
            event_reservation=3,
            limit=2,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        result = run_shadow_automation_cycle(
            db,
            confirmation=preview["confirmation"],
            permit_id=permit.permit_id,
            event_reservation=3,
            limit=2,
            actor_label="cycle<script>",
            note="manual cycle",
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
        )
        assert result["created"] is True
        assert result["status"] == "PASSED"
        assert result["ticket_id"]
        assert result["execution_run_id"]
        assert result["processed_count"] == 2
        assert result["budget_settled"] is True
        assert result["audit_chain_valid"] is True
        assert len(result["events"]) == 2


def test_m17_retry_is_idempotent(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _permit(db, monkeypatch)
        _patch_execution_success(monkeypatch, processed=1)
        preview = preview_shadow_automation_cycle(
            db,
            permit_id=permit.permit_id,
            event_reservation=2,
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        first = run_shadow_automation_cycle(
            db,
            confirmation=preview["confirmation"],
            permit_id=permit.permit_id,
            event_reservation=2,
            limit=1,
            settings_object=_policy(),
            started_at=NOW,
        )
        second = run_shadow_automation_cycle(
            db,
            confirmation=preview["confirmation"],
            permit_id=permit.permit_id,
            event_reservation=2,
            limit=1,
            settings_object=_policy(),
            started_at=NOW,
        )
        assert second["created"] is False
        assert second["cycle_id"] == first["cycle_id"]
        assert db.query(CanonicalParserShadowAutomationCycle).count() == 1


def test_m17_failure_compensates_ticket_and_persists_failed_cycle(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _permit(db, monkeypatch)
        monkeypatch.setattr(
            service_module,
            "preview_shadow_ticket_execution",
            lambda *args, **kwargs: {"eligible": True, "confirmation": "RUN"},
        )

        def fail(*args, **kwargs):
            raise CanonicalParserShadowTicketExecutionError(
                "boom", code="TEST_EXECUTION_FAILED", status_code=409
            )

        monkeypatch.setattr(service_module, "run_shadow_ticket_execution", fail)
        preview = preview_shadow_automation_cycle(
            db,
            permit_id=permit.permit_id,
            event_reservation=2,
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        with pytest.raises(CanonicalParserShadowAutomationCycleError):
            run_shadow_automation_cycle(
                db,
                confirmation=preview["confirmation"],
                permit_id=permit.permit_id,
                event_reservation=2,
                limit=1,
                settings_object=_policy(),
                started_at=NOW,
            )
        cycle = db.scalar(select(CanonicalParserShadowAutomationCycle))
        ticket = db.scalar(select(CanonicalParserShadowExecutionTicket))
        assert cycle.status == "FAILED"
        assert cycle.reason_codes == ["TEST_EXECUTION_FAILED"]
        assert ticket.status == "RELEASED"
        assert db.query(CanonicalParserShadowAutomationCycleEvent).count() == 2


def test_m17_actor_and_note_are_sanitized(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _permit(db, monkeypatch)
        _patch_execution_success(monkeypatch, processed=1)
        preview = preview_shadow_automation_cycle(
            db,
            permit_id=permit.permit_id,
            event_reservation=1,
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        result = run_shadow_automation_cycle(
            db,
            confirmation=preview["confirmation"],
            permit_id=permit.permit_id,
            event_reservation=1,
            limit=1,
            actor_label="operator\nsecret",
            note="note\r\nline",
            settings_object=_policy(),
            started_at=NOW,
        )
        assert "\n" not in result["actor_label"]
        assert "\r" not in result["note"]


def test_m17_audit_tampering_is_detected(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _permit(db, monkeypatch)
        _patch_execution_success(monkeypatch, processed=1)
        preview = preview_shadow_automation_cycle(
            db,
            permit_id=permit.permit_id,
            event_reservation=1,
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        result = run_shadow_automation_cycle(
            db,
            confirmation=preview["confirmation"],
            permit_id=permit.permit_id,
            event_reservation=1,
            limit=1,
            settings_object=_policy(),
            started_at=NOW,
        )
        event = db.scalar(select(CanonicalParserShadowAutomationCycleEvent).order_by(CanonicalParserShadowAutomationCycleEvent.sequence.desc()))
        event.event_hash = "f" * 64
        db.commit()
        loaded = get_shadow_automation_cycle(db, result["cycle_id"])
        assert loaded["audit_chain_valid"] is False


def test_m17_models_registered(db_factory):
    names = set(Base.metadata.tables)
    assert "canonical_parser_shadow_automation_cycles" in names
    assert "canonical_parser_shadow_automation_cycle_events" in names
    assert models.CanonicalParserShadowAutomationCycle is CanonicalParserShadowAutomationCycle
    assert models.CanonicalParserShadowAutomationCycleEvent is CanonicalParserShadowAutomationCycleEvent


def test_m17_service_has_no_network_or_operational_writes():
    path = Path("backend/app/services/blockchain_parser_shadow_automation_cycle_service.py")
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
    assert '"scheduler_connected": False' in source
    assert '"worker_connected": False' in source


def test_m17_service_not_imported_by_workers_or_live_pipelines():
    forbidden = []
    for path in Path("backend/app").rglob("*.py"):
        if path.name in {"main.py", "blockchain_parser_shadow_scheduler_service.py", "blockchain_parser_shadow_automation_cycle_service.py"}:
            continue
        if "blockchain_parser_shadow_automation_cycle_service" in path.read_text(encoding="utf-8"):
            forbidden.append(str(path))
    assert forbidden == []


def test_m17_api_routes_protected_and_unique(db_factory):
    expected = {
        ("GET", "/integrity/parser-shadow-automation-cycle/status"),
        ("GET", "/integrity/parser-shadow-automation-cycle/preview"),
        ("POST", "/integrity/parser-shadow-automation-cycle/run"),
        ("GET", "/integrity/parser-shadow-automation-cycle/cycles/{cycle_id}"),
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
            response = client.request(method, path.replace("{cycle_id}", str(uuid4())))
            assert response.status_code in {401, 403}
    finally:
        app.dependency_overrides.clear()


def test_m17_migration_round_trip():
    path = Path("alembic/versions/d1f5a8c3e927_add_shadow_automation_cycle.py")
    spec = importlib.util.spec_from_file_location("m17_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.revision == "d1f5a8c3e927"
    assert module.down_revision == "c9e3a7f2d418"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CanonicalParserShadowAutomationPermit.__table__,
            CanonicalParserShadowExecutionTicket.__table__,
            CanonicalParserShadowTicketExecutionRun.__table__,
            RawBlockchainEvent.__table__,
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
            assert "canonical_parser_shadow_automation_cycles" in names
            assert "canonical_parser_shadow_automation_cycle_events" in names
            module.downgrade()
            assert "canonical_parser_shadow_automation_cycles" not in set(inspect(connection).get_table_names())
            module.upgrade()
            assert "canonical_parser_shadow_automation_cycle_events" in set(inspect(connection).get_table_names())
        finally:
            module.op = original
    engine.dispose()
