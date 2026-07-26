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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.core.config import settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowAutomationPermit,
    CanonicalParserShadowAutomationPermitEvent,
    CanonicalParserShadowExecutionTicket,
    CanonicalParserShadowExecutionTicketEvent,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
from backend.app.services.blockchain_parser_shadow_execution_ticket_service import (
    EXECUTION_TICKET_CONFIRMATION_PREFIX,
    EXECUTION_TICKET_EXECUTOR,
    EXECUTION_TICKET_POLICY_VERSION,
    EXECUTION_TICKET_RELEASE_PREFIX,
    CanonicalParserShadowExecutionTicketError,
    get_shadow_execution_ticket,
    get_shadow_execution_ticket_status,
    preview_shadow_execution_ticket,
    release_shadow_execution_ticket,
    reserve_shadow_execution_ticket,
    resolve_shadow_execution_ticket,
)

AUTOMATION_KEY = "a" * 32
NOW = datetime(2026, 7, 26, 14, 0, tzinfo=timezone.utc)


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
        "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_ENABLED",
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_ENABLED",
        "CANONICAL_PARSER_SHADOW_READINESS_ENABLED",
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
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_VALIDITY_SECONDS",
        180,
    )
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MIN_PERMIT_REMAINING_SECONDS",
        30,
    )
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_EVENT_RESERVATION",
        25,
    )


def _ticket_settings(*, enabled: bool = True, **overrides):
    values = {
        "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_ENABLED": enabled,
        "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_VALIDITY_SECONDS": 180,
        "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MIN_PERMIT_REMAINING_SECONDS": 30,
        "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_EVENT_RESERVATION": 25,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _create_permit(
    db,
    *,
    now: datetime = NOW,
    run_budget: int = 3,
    event_budget: int = 50,
    consumed_runs: int = 0,
    consumed_events: int = 0,
    valid_seconds: int = 600,
):
    policy = {
        "policy_version": "canonical-parser-shadow-automation-permit/1",
        "manual_issue_only": True,
    }
    permit_id = str(uuid4())
    event_id = str(uuid4())
    event_payload = {
        "event_id": event_id,
        "permit_id": permit_id,
        "sequence": 1,
        "event_type": "ISSUED",
        "previous_status": None,
        "new_status": "ACTIVE",
        "actor_label": "TEST_OPERATOR",
        "reason": "test permit",
        "previous_event_hash": None,
        "occurred_at": now.isoformat(),
    }
    event_hash = calculate_payload_hash(event_payload)
    permit_generation = db.query(CanonicalParserShadowAutomationPermit).count() + 1
    permit = CanonicalParserShadowAutomationPermit(
        permit_id=permit_id,
        permit_key=calculate_payload_hash({"permit": permit_id}),
        permit_generation=permit_generation,
        assessment_db_id=1,
        assessment_id=str(uuid4()),
        assessment_key="a" * 64,
        lease_id=str(uuid4()),
        certification_id=str(uuid4()),
        binding_id=str(uuid4()),
        promotion_id=str(uuid4()),
        scope="SHADOW_ONLY",
        channel="CANONICAL_SHADOW",
        consumer="CERTIFIED_SHADOW_AUTOMATION",
        status="ACTIVE",
        parser_name="swap_canonical_event",
        parser_version="1.0.0",
        parser_implementation_hash="1" * 64,
        output_schema_version="canonical-swap/1",
        release_manifest_hash="2" * 64,
        lease_event_hash="3" * 64,
        certification_event_hash="4" * 64,
        readiness_policy_hash="5" * 64,
        readiness_evidence_hash="6" * 64,
        permit_policy_version="canonical-parser-shadow-automation-permit/1",
        permit_policy_hash=calculate_payload_hash(policy),
        permit_policy_snapshot=policy,
        requested_validity_minutes=10,
        run_budget=run_budget,
        event_budget=event_budget,
        consumed_run_count=consumed_runs,
        consumed_event_count=consumed_events,
        actor_label="TEST_OPERATOR",
        note="test permit",
        issued_at=now,
        expires_at=now + timedelta(seconds=valid_seconds),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash=event_hash,
        technical_metadata={"metadata_only": True},
    )
    db.add(permit)
    db.flush()
    db.add(
        CanonicalParserShadowAutomationPermitEvent(
            event_id=event_id,
            permit_db_id=permit.id,
            sequence=1,
            event_type="ISSUED",
            previous_status=None,
            new_status="ACTIVE",
            actor_label="TEST_OPERATOR",
            reason="test permit",
            event_payload=event_payload,
            previous_event_hash=None,
            event_hash=event_hash,
            occurred_at=now,
        )
    )
    db.commit()
    db.refresh(permit)
    return permit


def _permit_payload(permit):
    return {
        "permit_id": permit.permit_id,
        "permit_key": permit.permit_key,
        "assessment_id": permit.assessment_id,
        "lease_id": permit.lease_id,
        "certification_id": permit.certification_id,
        "binding_id": permit.binding_id,
        "promotion_id": permit.promotion_id,
        "scope": permit.scope,
        "channel": permit.channel,
        "consumer": permit.consumer,
        "status": permit.status,
        "parser_name": permit.parser_name,
        "parser_version": permit.parser_version,
        "parser_implementation_hash": permit.parser_implementation_hash,
        "output_schema_version": permit.output_schema_version,
        "release_manifest_hash": permit.release_manifest_hash,
        "readiness_evidence_hash": permit.readiness_evidence_hash,
        "permit_policy_hash": permit.permit_policy_hash,
        "latest_event_hash": permit.latest_event_hash,
        "run_budget": permit.run_budget,
        "event_budget": permit.event_budget,
        "consumed_run_count": permit.consumed_run_count,
        "consumed_event_count": permit.consumed_event_count,
        "expires_at": permit.expires_at,
    }


def _patch_permit(monkeypatch, permit, **changes):
    import backend.app.services.blockchain_parser_shadow_execution_ticket_service as service

    def fake_resolution(*args, **kwargs):
        payload = _permit_payload(permit)
        payload.update(changes.get("permit_changes", {}))
        return {
            "resolved": changes.get("resolved", True),
            "status": changes.get("status", "READY"),
            "reason_codes": changes.get("reason_codes", []),
            "permit_enabled": True,
            "automation_authorized": changes.get("automation_authorized", True),
            "permit": payload,
            "budget_consumption_connected": False,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_execution": False,
            "live_execution": False,
        }

    monkeypatch.setattr(service, "resolve_shadow_automation_permit", fake_resolution)


def _reserve(
    db,
    monkeypatch,
    permit,
    *,
    now=NOW,
    events=10,
    validity=120,
    settings_object=None,
):
    _patch_permit(monkeypatch, permit)
    policy = settings_object or _ticket_settings()
    preview = preview_shadow_execution_ticket(
        db,
        permit_id=permit.permit_id,
        validity_seconds=validity,
        event_reservation=events,
        settings_object=policy,
        evaluated_at=now,
    )
    return reserve_shadow_execution_ticket(
        db,
        confirmation=preview["confirmation"],
        permit_id=permit.permit_id,
        validity_seconds=validity,
        event_reservation=events,
        actor_label="operator<script>",
        note="atomic reservation",
        settings_object=policy,
        issued_at=now,
    )


def _client(db_factory):
    def override_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m15_constants_are_stable():
    assert EXECUTION_TICKET_POLICY_VERSION == "canonical-parser-shadow-execution-ticket/1"
    assert EXECUTION_TICKET_CONFIRMATION_PREFIX == "RESERVE_CERTIFIED_SHADOW_EXECUTION_TICKET"
    assert EXECUTION_TICKET_RELEASE_PREFIX == "RELEASE_CERTIFIED_SHADOW_EXECUTION_TICKET"
    assert EXECUTION_TICKET_EXECUTOR == "CERTIFIED_SHADOW_EXECUTION_TICKET"


def test_m15_status_defaults_disabled_and_empty(db_factory):
    with db_factory() as db:
        status = get_shadow_execution_ticket_status(db)
        assert status["ticket_enabled"] is False
        assert status["ticket_count"] == 0
        assert status["active_run_reservations"] == 0
        assert status["operational_guards"]["budget_reservation_connected"] is True
        assert status["operational_guards"]["execution_connected"] is False


def test_m15_preview_ready_reserves_one_run_and_events(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        _patch_permit(monkeypatch, permit)
        preview = preview_shadow_execution_ticket(
            db,
            permit_id=permit.permit_id,
            validity_seconds=120,
            event_reservation=10,
            settings_object=_ticket_settings(),
            evaluated_at=NOW,
        )
        assert preview["reservable"] is True
        assert preview["run_reservation"] == 1
        assert preview["event_reservation"] == 10
        assert preview["remaining_run_budget"] == 3
        assert preview["remaining_event_budget"] == 50
        assert preview["confirmation"].startswith(EXECUTION_TICKET_CONFIRMATION_PREFIX)
        assert preview["writes_database"] is False


@pytest.mark.parametrize(
    ("validity", "events", "reason"),
    [
        (181, 10, "SHADOW_EXECUTION_TICKET_VALIDITY_ABOVE_MAXIMUM"),
        (120, 26, "SHADOW_EXECUTION_TICKET_EVENT_RESERVATION_ABOVE_MAXIMUM"),
        (0, 10, "SHADOW_EXECUTION_TICKET_VALIDITY_BELOW_MINIMUM"),
        (120, 0, "SHADOW_EXECUTION_TICKET_EVENT_RESERVATION_BELOW_MINIMUM"),
    ],
)
def test_m15_preview_enforces_policy_bounds(db_factory, monkeypatch, validity, events, reason):
    with db_factory() as db:
        permit = _create_permit(db)
        _patch_permit(monkeypatch, permit)
        preview = preview_shadow_execution_ticket(
            db,
            permit_id=permit.permit_id,
            validity_seconds=validity,
            event_reservation=events,
            settings_object=_ticket_settings(),
            evaluated_at=NOW,
        )
        assert preview["reservable"] is False
        assert reason in preview["reason_codes"]


def test_m15_preview_blocks_permit_mismatch(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        _patch_permit(monkeypatch, permit)
        preview = preview_shadow_execution_ticket(
            db,
            permit_id=str(uuid4()),
            settings_object=_ticket_settings(),
            evaluated_at=NOW,
        )
        assert preview["reservable"] is False
        assert "SHADOW_EXECUTION_TICKET_PERMIT_MISSING_OR_MISMATCHED" in preview["reason_codes"]


def test_m15_reserve_disabled_is_fail_closed(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        _patch_permit(monkeypatch, permit)
        with pytest.raises(CanonicalParserShadowExecutionTicketError) as error:
            reserve_shadow_execution_ticket(
                db,
                confirmation="anything",
                permit_id=permit.permit_id,
                settings_object=_ticket_settings(enabled=False),
                issued_at=NOW,
            )
        assert error.value.code == "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_DISABLED"


def test_m15_reserve_requires_dynamic_confirmation(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        _patch_permit(monkeypatch, permit)
        with pytest.raises(CanonicalParserShadowExecutionTicketError) as error:
            reserve_shadow_execution_ticket(
                db,
                confirmation="wrong",
                permit_id=permit.permit_id,
                settings_object=_ticket_settings(),
                issued_at=NOW,
            )
        assert error.value.code == "SHADOW_EXECUTION_TICKET_CONFIRMATION_MISMATCH"


def test_m15_reserve_persists_ticket_and_audit_event(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        result = _reserve(db, monkeypatch, permit)
        assert result["status"] == "RESERVED"
        assert result["audit_chain_valid"] is True
        assert result["remaining_run_budget_after_reservation"] == 2
        assert result["remaining_event_budget_after_reservation"] == 40
        ticket = db.scalar(select(CanonicalParserShadowExecutionTicket))
        event = db.scalar(select(CanonicalParserShadowExecutionTicketEvent))
        assert ticket is not None and event is not None
        assert event.event_type == "RESERVED"
        assert "<script>" not in ticket.actor_label


def test_m15_multiple_tickets_reserve_budget_without_consuming(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db, run_budget=3, event_budget=30)
        first = _reserve(db, monkeypatch, permit, events=10, now=NOW)
        second = _reserve(db, monkeypatch, permit, events=15, now=NOW + timedelta(seconds=1))
        assert first["ticket_id"] != second["ticket_id"]
        status = get_shadow_execution_ticket_status(db, evaluated_at=NOW + timedelta(seconds=2))
        assert status["active_run_reservations"] == 2
        assert status["active_event_reservations"] == 25
        db.refresh(permit)
        assert permit.consumed_run_count == 0
        assert permit.consumed_event_count == 0


def test_m15_run_budget_prevents_overbooking(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db, run_budget=1, event_budget=50)
        _reserve(db, monkeypatch, permit, events=10)
        _patch_permit(monkeypatch, permit)
        preview = preview_shadow_execution_ticket(
            db,
            permit_id=permit.permit_id,
            event_reservation=10,
            settings_object=_ticket_settings(),
            evaluated_at=NOW + timedelta(seconds=1),
        )
        assert preview["reservable"] is False
        assert "SHADOW_EXECUTION_TICKET_RUN_BUDGET_UNAVAILABLE" in preview["reason_codes"]


def test_m15_event_budget_prevents_overbooking(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db, run_budget=3, event_budget=20)
        _reserve(db, monkeypatch, permit, events=15)
        _patch_permit(monkeypatch, permit)
        preview = preview_shadow_execution_ticket(
            db,
            permit_id=permit.permit_id,
            event_reservation=10,
            settings_object=_ticket_settings(),
            evaluated_at=NOW + timedelta(seconds=1),
        )
        assert preview["reservable"] is False
        assert "SHADOW_EXECUTION_TICKET_EVENT_BUDGET_UNAVAILABLE" in preview["reason_codes"]


def test_m15_expired_ticket_is_reclaimed_before_new_reservation(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db, run_budget=1, event_budget=20)
        first = _reserve(db, monkeypatch, permit, events=10, validity=1)
        second = _reserve(
            db,
            monkeypatch,
            permit,
            events=10,
            validity=60,
            now=NOW + timedelta(seconds=2),
        )
        assert first["ticket_id"] in second["expired_ticket_ids"]
        old = db.scalar(
            select(CanonicalParserShadowExecutionTicket).where(
                CanonicalParserShadowExecutionTicket.ticket_id == first["ticket_id"]
            )
        )
        assert old.status == "EXPIRED"


def test_m15_duplicate_confirmation_returns_idempotent_ticket(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        _patch_permit(monkeypatch, permit)
        preview = preview_shadow_execution_ticket(
            db,
            permit_id=permit.permit_id,
            event_reservation=10,
            settings_object=_ticket_settings(),
            evaluated_at=NOW,
        )
        first = reserve_shadow_execution_ticket(
            db,
            confirmation=preview["confirmation"],
            permit_id=permit.permit_id,
            event_reservation=10,
            settings_object=_ticket_settings(),
            issued_at=NOW,
        )
        second = reserve_shadow_execution_ticket(
            db,
            confirmation=preview["confirmation"],
            permit_id=permit.permit_id,
            event_reservation=10,
            settings_object=_ticket_settings(),
            issued_at=NOW + timedelta(seconds=1),
        )
        assert second["ticket_id"] == first["ticket_id"]
        assert second["idempotent"] is True


def test_m15_get_ticket_and_not_found(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        result = _reserve(db, monkeypatch, permit)
        payload = get_shadow_execution_ticket(db, result["ticket_id"])
        assert payload["audit_chain_valid"] is True
        assert payload["release_confirmation"].endswith(result["ticket_id"])
        with pytest.raises(CanonicalParserShadowExecutionTicketError) as error:
            get_shadow_execution_ticket(db, str(uuid4()))
        assert error.value.code == "SHADOW_EXECUTION_TICKET_NOT_FOUND"


def test_m15_release_requires_confirmation_and_is_idempotent(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        result = _reserve(db, monkeypatch, permit)
        with pytest.raises(CanonicalParserShadowExecutionTicketError) as error:
            release_shadow_execution_ticket(
                db,
                ticket_id=result["ticket_id"],
                confirmation="wrong",
                reason="operator release",
                released_at=NOW + timedelta(seconds=1),
            )
        assert error.value.code == "SHADOW_EXECUTION_TICKET_RELEASE_CONFIRMATION_MISMATCH"
        confirmation = f"{EXECUTION_TICKET_RELEASE_PREFIX}:{result['ticket_id']}"
        released = release_shadow_execution_ticket(
            db,
            ticket_id=result["ticket_id"],
            confirmation=confirmation,
            reason="operator release",
            released_at=NOW + timedelta(seconds=1),
        )
        again = release_shadow_execution_ticket(
            db,
            ticket_id=result["ticket_id"],
            confirmation=confirmation,
            reason="operator release",
            released_at=NOW + timedelta(seconds=2),
        )
        assert released["status"] == "RELEASED"
        assert again["idempotent"] is True
        assert db.query(CanonicalParserShadowExecutionTicketEvent).count() == 2


def test_m15_tampered_audit_chain_blocks_release(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        result = _reserve(db, monkeypatch, permit)
        event = db.scalar(select(CanonicalParserShadowExecutionTicketEvent))
        event.event_payload = {"tampered": True}
        db.commit()
        with pytest.raises(CanonicalParserShadowExecutionTicketError) as error:
            release_shadow_execution_ticket(
                db,
                ticket_id=result["ticket_id"],
                confirmation=f"{EXECUTION_TICKET_RELEASE_PREFIX}:{result['ticket_id']}",
                reason="release",
                released_at=NOW + timedelta(seconds=1),
            )
        assert error.value.code == "PARSER_SHADOW_EXECUTION_TICKET_AUDIT_CHAIN_INVALID"


def test_m15_resolve_ready_but_flag_controls_authorization(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        result = _reserve(db, monkeypatch, permit)
        _patch_permit(monkeypatch, permit)
        disabled = resolve_shadow_execution_ticket(
            db,
            ticket_id=result["ticket_id"],
            settings_object=_ticket_settings(enabled=False),
            evaluated_at=NOW + timedelta(seconds=1),
        )
        enabled = resolve_shadow_execution_ticket(
            db,
            ticket_id=result["ticket_id"],
            settings_object=_ticket_settings(enabled=True),
            evaluated_at=NOW + timedelta(seconds=1),
        )
        assert disabled["status"] == "READY"
        assert disabled["ticket_authorized"] is False
        assert enabled["ticket_authorized"] is True
        assert enabled["execution_connected"] is False


def test_m15_resolve_expired_and_released(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        result = _reserve(db, monkeypatch, permit, validity=1)
        _patch_permit(monkeypatch, permit)
        expired = resolve_shadow_execution_ticket(
            db,
            ticket_id=result["ticket_id"],
            settings_object=_ticket_settings(),
            evaluated_at=NOW + timedelta(seconds=2),
        )
        assert expired["status"] == "EXPIRED"
        permit.status = "EXPIRED"
        db.commit()

    with db_factory() as db:
        permit = _create_permit(db)
        result = _reserve(db, monkeypatch, permit)
        release_shadow_execution_ticket(
            db,
            ticket_id=result["ticket_id"],
            confirmation=f"{EXECUTION_TICKET_RELEASE_PREFIX}:{result['ticket_id']}",
            reason="release",
            released_at=NOW + timedelta(seconds=1),
        )
        _patch_permit(monkeypatch, permit)
        released = resolve_shadow_execution_ticket(
            db,
            ticket_id=result["ticket_id"],
            settings_object=_ticket_settings(),
            evaluated_at=NOW + timedelta(seconds=2),
        )
        assert released["status"] == "RELEASED"


def test_m15_resolve_detects_policy_and_permit_drift(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db)
        result = _reserve(db, monkeypatch, permit)
        _patch_permit(monkeypatch, permit)
        policy_drift = resolve_shadow_execution_ticket(
            db,
            ticket_id=result["ticket_id"],
            settings_object=_ticket_settings(
                CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_EVENT_RESERVATION=24
            ),
            evaluated_at=NOW + timedelta(seconds=1),
        )
        assert policy_drift["status"] == "DRIFTED"
        assert "SHADOW_EXECUTION_TICKET_POLICY_DRIFT" in policy_drift["reason_codes"]
        _patch_permit(monkeypatch, permit, permit_changes={"release_manifest_hash": "9" * 64})
        permit_drift = resolve_shadow_execution_ticket(
            db,
            ticket_id=result["ticket_id"],
            settings_object=_ticket_settings(),
            evaluated_at=NOW + timedelta(seconds=1),
        )
        assert "SHADOW_EXECUTION_TICKET_RELEASE_DRIFT" in permit_drift["reason_codes"]


def test_m15_resolve_detects_budget_overbooking(db_factory, monkeypatch):
    with db_factory() as db:
        permit = _create_permit(db, run_budget=1, event_budget=10)
        first = _reserve(db, monkeypatch, permit, events=10)
        original = db.scalar(
            select(CanonicalParserShadowExecutionTicket).where(
                CanonicalParserShadowExecutionTicket.ticket_id == first["ticket_id"]
            )
        )
        duplicate = CanonicalParserShadowExecutionTicket(
            **{
                column.name: getattr(original, column.name)
                for column in CanonicalParserShadowExecutionTicket.__table__.columns
                if column.name not in {"id", "ticket_id", "ticket_key", "ticket_generation", "created_at", "updated_at"}
            },
            ticket_id=str(uuid4()),
            ticket_key="f" * 64,
            ticket_generation=2,
        )
        db.add(duplicate)
        db.commit()
        _patch_permit(monkeypatch, permit)
        resolution = resolve_shadow_execution_ticket(
            db,
            ticket_id=first["ticket_id"],
            settings_object=_ticket_settings(),
            evaluated_at=NOW + timedelta(seconds=1),
        )
        assert resolution["status"] == "DRIFTED"
        assert "SHADOW_EXECUTION_TICKET_RUN_BUDGET_OVERBOOKED" in resolution["reason_codes"]
        assert "SHADOW_EXECUTION_TICKET_EVENT_BUDGET_OVERBOOKED" in resolution["reason_codes"]


def test_m15_models_are_registered_and_generation_is_unique(db_factory, monkeypatch):
    assert "canonical_parser_shadow_execution_tickets" in Base.metadata.tables
    assert "canonical_parser_shadow_execution_ticket_events" in Base.metadata.tables
    assert models.CanonicalParserShadowExecutionTicket is CanonicalParserShadowExecutionTicket
    assert models.CanonicalParserShadowExecutionTicketEvent is CanonicalParserShadowExecutionTicketEvent
    with db_factory() as db:
        permit = _create_permit(db)
        result = _reserve(db, monkeypatch, permit)
        ticket = db.scalar(
            select(CanonicalParserShadowExecutionTicket).where(
                CanonicalParserShadowExecutionTicket.ticket_id == result["ticket_id"]
            )
        )
        duplicate = CanonicalParserShadowExecutionTicket(
            **{
                column.name: getattr(ticket, column.name)
                for column in CanonicalParserShadowExecutionTicket.__table__.columns
                if column.name not in {"id", "ticket_id", "ticket_key", "created_at", "updated_at"}
            },
            ticket_id=str(uuid4()),
            ticket_key="e" * 64,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


def test_m15_service_has_no_network_trade_execution_scheduler_or_worker():
    path = Path("backend/app/services/blockchain_parser_shadow_execution_ticket_service.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports & {"httpx", "requests", "aiohttp", "urllib3", "websockets"}
    assert "Trade(" not in source
    assert "PaperOrder(" not in source
    assert "LiveCopyOrder(" not in source
    assert "CanonicalNormalizedEvent(" not in source
    assert "RUN_LIVE" not in source
    assert '"budget_consumption_connected": False' in source
    assert '"execution_connected": False' in source
    assert '"scheduler_connected": False' in source
    assert '"worker_connected": False' in source


def test_m15_service_not_imported_by_operational_pipelines():
    forbidden = []
    allowed = {
        "main.py",
        "blockchain_parser_shadow_execution_ticket_service.py",
        "blockchain_parser_shadow_ticket_execution_service.py",
    }
    for path in Path("backend/app").rglob("*.py"):
        if path.name in allowed:
            continue
        if "blockchain_parser_shadow_execution_ticket_service" in path.read_text(encoding="utf-8"):
            forbidden.append(str(path))
    assert forbidden == []


def test_m15_api_routes_are_protected_and_registered_once(db_factory):
    counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            counts[(method, getattr(route, "path", ""))] += 1
    expected = {
        ("GET", "/integrity/parser-shadow-execution-ticket/status"),
        ("GET", "/integrity/parser-shadow-execution-ticket/preview"),
        ("POST", "/integrity/parser-shadow-execution-ticket/reserve"),
        ("POST", "/integrity/parser-shadow-execution-ticket/release"),
        ("GET", "/integrity/parser-shadow-execution-ticket/tickets/{ticket_id}"),
        ("GET", "/integrity/parser-shadow-execution-ticket/resolve"),
    }
    for route in expected:
        assert counts[route] == 1
    client = _client(db_factory)
    try:
        assert client.get("/integrity/parser-shadow-execution-ticket/status").status_code == 401
        response = client.get(
            "/integrity/parser-shadow-execution-ticket/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["ticket_enabled"] is False
        post = client.post(
            "/integrity/parser-shadow-execution-ticket/reserve",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={"confirmation": "anything"},
        )
        assert post.status_code == 409
        assert post.json()["detail"]["code"] == "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_DISABLED"
    finally:
        app.dependency_overrides.clear()


def test_m15_migration_upgrade_downgrade_upgrade_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    path = Path("alembic/versions/b7d1f4a6c825_add_shadow_execution_ticket.py")
    spec = importlib.util.spec_from_file_location("m15_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE canonical_parser_shadow_automation_permits (id INTEGER PRIMARY KEY)"
        )
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_shadow_execution_tickets" in names
    assert "canonical_parser_shadow_execution_ticket_events" in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.downgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_shadow_execution_tickets" not in names
    assert "canonical_parser_shadow_execution_ticket_events" not in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    assert "canonical_parser_shadow_execution_tickets" in inspect(engine).get_table_names()
    engine.dispose()
