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
from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalNormalizedEvent,
    CanonicalParserShadowAutomationPermit,
    CanonicalParserShadowAutomationPermitEvent,
    CanonicalParserShadowExecutionTicket,
    CanonicalParserShadowExecutionTicketEvent,
    CanonicalParserShadowTicketExecutionResult,
    CanonicalParserShadowTicketExecutionRun,
    RawBlockchainEvent,
)
from backend.app.models.trade import Trade
from backend.app.services import blockchain_parser_shadow_ticket_execution_service as service_module
from backend.app.services.blockchain_integrity_service import register_raw_event
from backend.app.services.blockchain_parser_registry_service import DEFAULT_PARSER_REGISTRY
from backend.app.services.blockchain_parser_shadow_ticket_execution_service import (
    TICKET_EXECUTION_CONFIRMATION_PREFIX,
    TICKET_EXECUTION_EXECUTOR,
    TICKET_EXECUTION_POLICY_VERSION,
    CanonicalParserShadowTicketExecutionError,
    get_shadow_ticket_execution_run,
    get_shadow_ticket_execution_status,
    preview_shadow_ticket_execution,
    run_shadow_ticket_execution,
)

AUTOMATION_KEY = "a" * 32
NOW = datetime(2026, 7, 26, 16, 0, tzinfo=timezone.utc)
WALLET = "TicketExecutionWallet1111111111111111111111111"
TOKEN = "TicketExecutionToken11111111111111111111111111"
DEFINITION = DEFAULT_PARSER_REGISTRY.get("swap_canonical_event", "1.0.0")


def _load_m15_helpers():
    path = Path(__file__).with_name("test_parser_shadow_execution_ticket_m15.py")
    spec = importlib.util.spec_from_file_location("m15_test_helpers", path)
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
        "CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_ENABLED",
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
        "CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_MAX_SAMPLE_SIZE",
        25,
    )


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test-helius-api-key",
    }
    values.update(overrides)
    return values


def _policy(*, enabled: bool = True, max_sample: int = 25):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_ENABLED=enabled,
        CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_MAX_SAMPLE_SIZE=max_sample,
    )


def _swap(signature: str) -> dict:
    return {
        "type": "SWAP",
        "signature": signature,
        "timestamp": 1785000000,
        "source": "JUPITER",
        "fee": 5000,
        "feePayer": WALLET,
        "transactionError": None,
        "events": {
            "swap": {
                "nativeInput": {"account": WALLET, "amount": 125000000},
                "nativeOutput": None,
                "tokenInputs": [],
                "tokenOutputs": [
                    {
                        "userAccount": WALLET,
                        "mint": TOKEN,
                        "rawTokenAmount": {
                            "tokenAmount": "250000000",
                            "decimals": 6,
                        },
                    }
                ],
            }
        },
    }


def _insert_raw(db, signature: str, *, compatible: bool = True):
    event, _ = register_raw_event(
        db,
        provider="helius" if compatible else "other",
        chain="solana",
        network="mainnet-beta",
        event_type="WALLET_HISTORY_RESPONSE",
        transaction_signature=signature,
        observed_wallet=WALLET,
        payload=[_swap(signature)],
        observed_at=NOW,
    )
    db.flush()
    return event


def _prepare(db, monkeypatch, *, reservation=5, run_budget=3, event_budget=20):
    permit = M15._create_permit(
        db,
        now=NOW,
        run_budget=run_budget,
        event_budget=event_budget,
        valid_seconds=900,
    )
    permit.parser_implementation_hash = DEFINITION.implementation_hash
    permit.output_schema_version = DEFINITION.output_schema_version
    db.commit()
    ticket_payload = M15._reserve(
        db,
        monkeypatch,
        permit,
        now=NOW,
        events=reservation,
        validity=180,
        settings_object=M15._ticket_settings(),
    )
    ticket = db.scalar(
        select(CanonicalParserShadowExecutionTicket).where(
            CanonicalParserShadowExecutionTicket.ticket_id
            == ticket_payload["ticket_id"]
        )
    )
    events = [_insert_raw(db, f"m16-signature-{index}") for index in range(1, 8)]
    db.commit()
    return permit, ticket, events


def _ticket_payload(ticket):
    return {
        "ticket_id": ticket.ticket_id,
        "ticket_key": ticket.ticket_key,
        "permit_id": ticket.permit_id,
        "permit_key": ticket.permit_key,
        "assessment_id": ticket.assessment_id,
        "lease_id": ticket.lease_id,
        "certification_id": ticket.certification_id,
        "binding_id": ticket.binding_id,
        "promotion_id": ticket.promotion_id,
        "scope": ticket.scope,
        "channel": ticket.channel,
        "consumer": ticket.consumer,
        "status": ticket.status,
        "parser_name": ticket.parser_name,
        "parser_version": ticket.parser_version,
        "parser_implementation_hash": ticket.parser_implementation_hash,
        "output_schema_version": ticket.output_schema_version,
        "release_manifest_hash": ticket.release_manifest_hash,
        "readiness_evidence_hash": ticket.readiness_evidence_hash,
        "permit_policy_hash": ticket.permit_policy_hash,
        "permit_event_hash": ticket.permit_event_hash,
        "ticket_policy_hash": ticket.ticket_policy_hash,
        "event_reservation": ticket.event_reservation,
        "latest_event_hash": ticket.latest_event_hash,
        "expires_at": ticket.expires_at,
    }


def _patch_ticket(monkeypatch, ticket, *, drift_after=None, drift_code="TEST_TICKET_DRIFT"):
    calls = {"count": 0}

    def fake_resolution(*args, **kwargs):
        calls["count"] += 1
        evaluated_at = kwargs.get("evaluated_at") or NOW
        payload = _ticket_payload(ticket)
        expires_at = ticket.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        expired = evaluated_at >= expires_at
        drifted = drift_after is not None and calls["count"] >= drift_after
        if drifted:
            payload = dict(payload)
            payload["latest_event_hash"] = "f" * 64
        ready = ticket.status == "RESERVED" and not expired and not drifted
        return {
            "resolved": ready,
            "status": "READY" if ready else ("EXPIRED" if expired else "DRIFTED"),
            "reason_codes": [] if ready else (["SHADOW_EXECUTION_TICKET_EXPIRED"] if expired else [drift_code]),
            "ticket_enabled": True,
            "ticket_authorized": ready,
            "ticket": payload,
            "budget_reservation_connected": True,
            "budget_consumption_connected": False,
            "execution_connected": False,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_execution": False,
            "live_execution": False,
        }

    monkeypatch.setattr(service_module, "resolve_shadow_execution_ticket", fake_resolution)
    return calls


def _execute(db, monkeypatch, *, reservation=5, limit=2, completed_at=None):
    permit, ticket, events = _prepare(
        db, monkeypatch, reservation=reservation
    )
    _patch_ticket(monkeypatch, ticket)
    ids = [event.id for event in events[:limit]]
    preview = preview_shadow_ticket_execution(
        db,
        ticket_id=ticket.ticket_id,
        raw_event_ids=ids,
        limit=limit,
        settings_object=_policy(),
        evaluated_at=NOW,
    )
    result = run_shadow_ticket_execution(
        db,
        confirmation=preview["confirmation"],
        ticket_id=ticket.ticket_id,
        raw_event_ids=ids,
        limit=limit,
        actor_label="m16-operator<script>",
        note="ticket-bound manual shadow execution",
        settings_object=_policy(),
        started_at=NOW,
        completed_at=completed_at or NOW + timedelta(seconds=20),
    )
    return permit, ticket, events, preview, result


def _client(factory):
    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m16_settings_defaults_are_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_MAX_SAMPLE_SIZE == 25


def test_m16_constants_are_stable():
    assert TICKET_EXECUTION_POLICY_VERSION == "canonical-parser-shadow-ticket-execution/1"
    assert TICKET_EXECUTION_CONFIRMATION_PREFIX == "RUN_RESERVED_SHADOW_EXECUTION_TICKET"
    assert TICKET_EXECUTION_EXECUTOR == "CERTIFIED_SHADOW_TICKET_EXECUTION"


def test_m16_status_defaults_disabled_and_empty(db_factory):
    with db_factory() as db:
        status = get_shadow_ticket_execution_status(db)
        assert status["execution_enabled"] is False
        assert status["run_count"] == 0
        assert status["settled_run_count"] == 0
        assert status["operational_guards"]["manual_execution_connected"] is True
        assert status["operational_guards"]["automatic_execution"] is False


def test_m16_preview_requires_ready_authorized_ticket(db_factory, monkeypatch):
    with db_factory() as db:
        monkeypatch.setattr(
            service_module,
            "resolve_shadow_execution_ticket",
            lambda *args, **kwargs: {
                "resolved": False,
                "status": "UNTICKETED",
                "reason_codes": ["ACTIVE_SHADOW_EXECUTION_TICKET_MISSING"],
                "ticket_authorized": False,
            },
        )
        preview = preview_shadow_ticket_execution(db, settings_object=_policy())
        assert preview["eligible"] is False
        assert "SHADOW_EXECUTION_TICKET_NOT_AUTHORIZED" in preview["blocker_codes"]


def test_m16_preview_is_deterministic_bounded_and_shadow_only(db_factory, monkeypatch):
    with db_factory() as db:
        _, ticket, events = _prepare(db, monkeypatch, reservation=5)
        _patch_ticket(monkeypatch, ticket)
        ids = [events[1].id, events[0].id]
        first = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=ids,
            limit=2,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        second = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=list(reversed(ids)),
            limit=2,
            settings_object=_policy(),
            evaluated_at=NOW + timedelta(seconds=5),
        )
        assert first["eligible"] is True
        assert first["run_key"] == second["run_key"]
        assert first["confirmation"] == second["confirmation"]
        assert first["event_reservation"] == 5
        assert first["selected_count"] == 2
        assert first["writes_shadow_tables_only"] is True
        assert first["writes_trades"] is False


@pytest.mark.parametrize(
    ("limit", "max_sample"),
    [(0, 25), (26, 25)],
)
def test_m16_preview_enforces_sample_policy(db_factory, limit, max_sample):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowTicketExecutionError) as error:
            preview_shadow_ticket_execution(
                db,
                limit=limit,
                settings_object=_policy(max_sample=max_sample),
            )
        assert error.value.code == "SHADOW_TICKET_EXECUTION_LIMIT_INVALID"


def test_m16_preview_blocks_selection_over_ticket_reservation(db_factory, monkeypatch):
    with db_factory() as db:
        _, ticket, events = _prepare(db, monkeypatch, reservation=2)
        _patch_ticket(monkeypatch, ticket)
        preview = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=[event.id for event in events[:3]],
            limit=3,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        assert preview["eligible"] is False
        assert "SHADOW_TICKET_EXECUTION_LIMIT_EXCEEDS_RESERVATION" in preview["blocker_codes"]
        assert "SHADOW_TICKET_EXECUTION_SELECTION_EXCEEDS_RESERVATION" in preview["blocker_codes"]


def test_m16_run_is_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowTicketExecutionError) as error:
            run_shadow_ticket_execution(
                db,
                confirmation="anything",
                ticket_id=str(uuid4()),
            )
        assert error.value.code == "CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_DISABLED"


def test_m16_run_requires_dynamic_confirmation(db_factory, monkeypatch):
    with db_factory() as db:
        _, ticket, events = _prepare(db, monkeypatch)
        _patch_ticket(monkeypatch, ticket)
        with pytest.raises(CanonicalParserShadowTicketExecutionError) as error:
            run_shadow_ticket_execution(
                db,
                confirmation="stale",
                ticket_id=ticket.ticket_id,
                raw_event_ids=[events[0].id],
                limit=1,
                settings_object=_policy(),
                started_at=NOW,
            )
        assert error.value.code == "SHADOW_TICKET_EXECUTION_CONFIRMATION_REQUIRED"


def test_m16_success_settles_budget_once_and_releases_unused_reservation(db_factory, monkeypatch):
    with db_factory() as db:
        permit, ticket, _, _, result = _execute(
            db, monkeypatch, reservation=5, limit=2
        )
        db.refresh(permit)
        db.refresh(ticket)
        assert result["created"] is True
        assert result["status"] == "PASSED"
        assert result["processed_count"] == 2
        assert result["consumed_run_count"] == 1
        assert result["consumed_event_count"] == 2
        assert result["released_event_count"] == 3
        assert result["budget_settled"] is True
        assert len(result["settlement_hash"]) == 64
        assert permit.consumed_run_count == 1
        assert permit.consumed_event_count == 2
        assert ticket.status == "RELEASED"
        assert db.query(Trade).count() == 0
        assert db.query(CanonicalNormalizedEvent).count() == 0
        assert db.query(CanonicalParserShadowTicketExecutionResult).count() == 2


def test_m16_retry_is_idempotent_and_does_not_double_consume(db_factory, monkeypatch):
    with db_factory() as db:
        permit, ticket, events, preview, first = _execute(
            db, monkeypatch, reservation=4, limit=2
        )
        second = run_shadow_ticket_execution(
            db,
            confirmation=preview["confirmation"],
            ticket_id=ticket.ticket_id,
            raw_event_ids=[event.id for event in events[:2]],
            limit=2,
            settings_object=_policy(),
        )
        db.refresh(permit)
        assert second["created"] is False
        assert second["run_id"] == first["run_id"]
        assert permit.consumed_run_count == 1
        assert permit.consumed_event_count == 2
        assert db.query(CanonicalParserShadowTicketExecutionRun).count() == 1


def test_m16_raw_payload_tampering_fails_but_accounts_processed_event(db_factory, monkeypatch):
    with db_factory() as db:
        permit, ticket, events = _prepare(db, monkeypatch, reservation=2)
        event = events[0]
        event.raw_payload = [{"type": "SWAP", "tampered": True}]
        db.flush()
        _patch_ticket(monkeypatch, ticket)
        preview = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=[event.id],
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        result = run_shadow_ticket_execution(
            db,
            confirmation=preview["confirmation"],
            ticket_id=ticket.ticket_id,
            raw_event_ids=[event.id],
            limit=1,
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
        )
        db.refresh(permit)
        assert result["status"] == "FAILED"
        assert result["results"][0]["reason_codes"] == ["RAW_PAYLOAD_HASH_MISMATCH"]
        assert result["consumed_event_count"] == 1
        assert permit.consumed_event_count == 1


def test_m16_final_ticket_drift_fails_closed_and_still_settles_accounting(db_factory, monkeypatch):
    with db_factory() as db:
        permit, ticket, events = _prepare(db, monkeypatch, reservation=3)
        _patch_ticket(monkeypatch, ticket, drift_after=3)
        preview = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=[events[0].id],
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        result = run_shadow_ticket_execution(
            db,
            confirmation=preview["confirmation"],
            ticket_id=ticket.ticket_id,
            raw_event_ids=[events[0].id],
            limit=1,
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
        )
        db.refresh(permit)
        assert result["status"] == "FAILED"
        assert "SHADOW_EXECUTION_TICKET_INTERLOCK_TRIPPED" in result["reason_codes"]
        assert "TEST_TICKET_DRIFT" in result["reason_codes"]
        assert permit.consumed_run_count == 1


def test_m16_expired_during_execution_is_failed_and_ticket_expires(db_factory, monkeypatch):
    with db_factory() as db:
        permit, ticket, events = _prepare(db, monkeypatch, reservation=2)
        ticket.expires_at = NOW + timedelta(seconds=5)
        db.commit()
        _patch_ticket(monkeypatch, ticket)
        preview = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=[events[0].id],
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        result = run_shadow_ticket_execution(
            db,
            confirmation=preview["confirmation"],
            ticket_id=ticket.ticket_id,
            raw_event_ids=[events[0].id],
            limit=1,
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
        )
        db.refresh(ticket)
        db.refresh(permit)
        assert result["status"] == "FAILED"
        assert "SHADOW_EXECUTION_TICKET_EXPIRED" in result["reason_codes"]
        assert ticket.status == "EXPIRED"
        assert permit.consumed_event_count == 1


def test_m16_permit_exhaustion_is_persisted_with_audit_event(db_factory, monkeypatch):
    with db_factory() as db:
        permit, ticket, events = _prepare(
            db,
            monkeypatch,
            reservation=2,
            run_budget=1,
            event_budget=2,
        )
        _patch_ticket(monkeypatch, ticket)
        preview = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=[event.id for event in events[:2]],
            limit=2,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        result = run_shadow_ticket_execution(
            db,
            confirmation=preview["confirmation"],
            ticket_id=ticket.ticket_id,
            raw_event_ids=[event.id for event in events[:2]],
            limit=2,
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
        )
        db.refresh(permit)
        assert result["status"] == "PASSED"
        assert permit.status == "EXHAUSTED"
        assert db.query(CanonicalParserShadowAutomationPermitEvent).count() == 2


def test_m16_budget_settlement_failure_rolls_back_run_and_ticket(db_factory, monkeypatch):
    with db_factory() as db:
        permit, ticket, events = _prepare(
            db,
            monkeypatch,
            reservation=1,
            run_budget=1,
            event_budget=1,
        )
        _patch_ticket(monkeypatch, ticket)
        preview = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=[events[0].id],
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        permit.consumed_run_count = 1
        permit.consumed_event_count = 1
        db.commit()
        with pytest.raises(CanonicalParserShadowTicketExecutionError) as error:
            run_shadow_ticket_execution(
                db,
                confirmation=preview["confirmation"],
                ticket_id=ticket.ticket_id,
                raw_event_ids=[events[0].id],
                limit=1,
                settings_object=_policy(),
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=10),
            )
        assert error.value.code == "SHADOW_TICKET_EXECUTION_RUN_BUDGET_SETTLEMENT_FAILED"
        assert db.query(CanonicalParserShadowTicketExecutionRun).count() == 0
        db.refresh(ticket)
        assert ticket.status == "RESERVED"


def test_m16_actor_and_note_are_sanitized(db_factory, monkeypatch):
    with db_factory() as db:
        _, ticket, events = _prepare(db, monkeypatch, reservation=1)
        _patch_ticket(monkeypatch, ticket)
        preview = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=[events[0].id],
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        result = run_shadow_ticket_execution(
            db,
            confirmation=preview["confirmation"],
            ticket_id=ticket.ticket_id,
            raw_event_ids=[events[0].id],
            limit=1,
            actor_label="operator\nsecret",
            note="note\r\nline",
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
        )
        assert "\n" not in result["actor_label"]
        assert "\r" not in result["note"]


def test_m16_get_run_and_status_counts(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, _, _, result = _execute(db, monkeypatch, reservation=3, limit=2)
        loaded = get_shadow_ticket_execution_run(db, result["run_id"])
        assert loaded["run_id"] == result["run_id"]
        status = get_shadow_ticket_execution_status(db, settings_object=_policy())
        assert status["run_count"] == 1
        assert status["status_counts"]["PASSED"] == 1
        assert status["settled_run_count"] == 1
        assert status["settled_event_count"] == 2
        assert status["released_event_count"] == 1
        with pytest.raises(CanonicalParserShadowTicketExecutionError) as error:
            get_shadow_ticket_execution_run(db, str(uuid4()))
        assert error.value.status_code == 404


def test_m16_models_are_registered_and_ticket_is_unique(db_factory, monkeypatch):
    names = set(Base.metadata.tables)
    assert "canonical_parser_shadow_ticket_execution_runs" in names
    assert "canonical_parser_shadow_ticket_execution_results" in names
    assert models.CanonicalParserShadowTicketExecutionRun is CanonicalParserShadowTicketExecutionRun
    assert models.CanonicalParserShadowTicketExecutionResult is CanonicalParserShadowTicketExecutionResult
    with db_factory() as db:
        _, ticket, events = _prepare(db, monkeypatch, reservation=1)
        _patch_ticket(monkeypatch, ticket)
        preview = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket.ticket_id,
            raw_event_ids=[events[0].id],
            limit=1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        result = run_shadow_ticket_execution(
            db,
            confirmation=preview["confirmation"],
            ticket_id=ticket.ticket_id,
            raw_event_ids=[events[0].id],
            limit=1,
            settings_object=_policy(),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=10),
        )
        row = db.scalar(select(CanonicalParserShadowTicketExecutionRun))
        duplicate = CanonicalParserShadowTicketExecutionRun(
            **{
                key: getattr(row, key)
                for key in (
                    "run_id", "run_key", "ticket_db_id", "ticket_id", "ticket_key",
                    "permit_db_id", "permit_id", "assessment_id", "lease_id",
                    "certification_id", "binding_id", "promotion_id", "scope",
                    "channel", "consumer", "executor", "status", "parser_name",
                    "parser_version", "parser_implementation_hash",
                    "output_schema_version", "release_manifest_hash",
                    "readiness_evidence_hash", "permit_policy_hash",
                    "permit_event_hash", "ticket_policy_hash", "ticket_event_hash",
                    "execution_policy_version", "execution_policy_hash",
                    "execution_policy_snapshot", "requested_limit",
                    "reserved_run_count", "reserved_event_count", "selected_count",
                    "processed_count", "passed_count", "failed_count", "skipped_count",
                    "artifact_count", "consumed_run_count", "consumed_event_count",
                    "released_event_count", "budget_settled", "settlement_hash",
                    "actor_label", "note", "reason_codes", "selection_snapshot",
                    "metrics_snapshot", "technical_metadata", "started_at", "completed_at",
                )
            }
        )
        duplicate.run_id = str(uuid4())
        duplicate.run_key = "f" * 64
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert result["budget_settled"] is True


def test_m16_service_has_no_network_live_paper_or_trade_writes():
    path = Path("backend/app/services/blockchain_parser_shadow_ticket_execution_service.py")
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
    assert "CanonicalNormalizedEvent(" not in source
    assert "RUN_LIVE" not in source
    assert '"scheduler_connected": False' in source
    assert '"worker_connected": False' in source
    assert '"automatic_execution": False' in source


def test_m16_service_not_imported_by_operational_pipelines():
    forbidden = []
    allowed = {
        "main.py",
        "blockchain_parser_shadow_ticket_execution_service.py",
    }
    for path in Path("backend/app").rglob("*.py"):
        if path.name in allowed:
            continue
        if "blockchain_parser_shadow_ticket_execution_service" in path.read_text(
            encoding="utf-8"
        ):
            forbidden.append(str(path))
    assert forbidden == []


def test_m16_api_routes_are_protected_and_registered_once(db_factory):
    counts = Counter()
    expected = {
        ("GET", "/integrity/parser-shadow-ticket-execution/status"),
        ("GET", "/integrity/parser-shadow-ticket-execution/preview"),
        ("POST", "/integrity/parser-shadow-ticket-execution/run"),
        ("GET", "/integrity/parser-shadow-ticket-execution/runs/{run_id}"),
    }
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            counts[(method, getattr(route, "path", ""))] += 1
    for route in expected:
        assert counts[route] == 1
    client = _client(db_factory)
    try:
        for method, path in expected:
            actual = path.replace("{run_id}", str(uuid4()))
            response = client.request(method, actual)
            assert response.status_code in {401, 403}
    finally:
        app.dependency_overrides.clear()


def test_m16_migration_upgrade_downgrade_upgrade_round_trip():
    path = Path("alembic/versions/c9e3a7f2d418_add_shadow_ticket_execution.py")
    spec = importlib.util.spec_from_file_location("m16_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.revision == "c9e3a7f2d418"
    assert module.down_revision == "b7d1f4a6c825"

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            RawBlockchainEvent.__table__,
            CanonicalParserShadowAutomationPermit.__table__,
            CanonicalParserShadowExecutionTicket.__table__,
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
            assert "canonical_parser_shadow_ticket_execution_runs" in names
            assert "canonical_parser_shadow_ticket_execution_results" in names
            module.downgrade()
            names = set(inspect(connection).get_table_names())
            assert "canonical_parser_shadow_ticket_execution_runs" not in names
            module.upgrade()
            names = set(inspect(connection).get_table_names())
            assert "canonical_parser_shadow_ticket_execution_results" in names
        finally:
            module.op = original
    engine.dispose()
