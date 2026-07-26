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
    CanonicalParserShadowReadinessAssessment,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
from backend.app.services.blockchain_parser_shadow_automation_permit_service import (
    AUTOMATION_PERMIT_CONFIRMATION_PREFIX,
    AUTOMATION_PERMIT_CONSUMER,
    AUTOMATION_PERMIT_POLICY_VERSION,
    AUTOMATION_PERMIT_REVOKE_PREFIX,
    CanonicalParserShadowAutomationPermitError,
    get_shadow_automation_permit,
    get_shadow_automation_permit_status,
    issue_shadow_automation_permit,
    preview_shadow_automation_permit,
    resolve_shadow_automation_permit,
    revoke_shadow_automation_permit,
)

AUTOMATION_KEY = "a" * 32
NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


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
    defaults = {
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_VALIDITY_MINUTES": 10,
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MIN_READINESS_REMAINING_MINUTES": 2,
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_RUN_BUDGET": 5,
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_EVENT_BUDGET": 100,
    }
    for name, value in defaults.items():
        monkeypatch.setattr(settings, name, value)


def _permit_settings(*, enabled: bool = True, **overrides):
    values = {
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_ENABLED": enabled,
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_VALIDITY_MINUTES": 10,
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MIN_READINESS_REMAINING_MINUTES": 2,
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_RUN_BUDGET": 5,
        "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_EVENT_BUDGET": 100,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _create_ready_assessment(db, *, now: datetime = NOW, valid_minutes: int = 15):
    policy_snapshot = {
        "policy_version": "canonical-parser-shadow-readiness/1",
        "manual": True,
    }
    evidence_snapshot = {
        "run_ids": [str(uuid4()), str(uuid4()), str(uuid4())],
        "run_count": 3,
        "total_processed_count": 15,
    }
    assessment = CanonicalParserShadowReadinessAssessment(
        assessment_id=str(uuid4()),
        assessment_key=calculate_payload_hash(
            {"assessment": str(uuid4()), "evaluated_at": now.isoformat()}
        ),
        lease_db_id=1,
        lease_id=str(uuid4()),
        certification_id=str(uuid4()),
        binding_id=str(uuid4()),
        promotion_id=str(uuid4()),
        scope="SHADOW_ONLY",
        channel="CANONICAL_SHADOW",
        consumer="CERTIFIED_SHADOW_RUNTIME",
        status="READY",
        parser_name="swap_canonical_event",
        parser_version="1.0.0",
        parser_implementation_hash="1" * 64,
        output_schema_version="canonical-swap/1",
        release_manifest_hash="2" * 64,
        lease_event_hash="3" * 64,
        certification_event_hash="4" * 64,
        readiness_policy_version="canonical-parser-shadow-readiness/1",
        readiness_policy_hash=calculate_payload_hash(policy_snapshot),
        evidence_hash=calculate_payload_hash(evidence_snapshot),
        run_ids=evidence_snapshot["run_ids"],
        run_count=3,
        total_processed_count=15,
        total_passed_count=15,
        total_failed_count=0,
        total_skipped_count=0,
        total_artifact_count=15,
        unique_event_count=10,
        pass_rate=100,
        reason_codes=[],
        policy_snapshot=policy_snapshot,
        evidence_snapshot=evidence_snapshot,
        metrics_snapshot={"pass_rate": 100.0},
        actor_label="TEST_OPERATOR",
        note=None,
        evidence_started_at=now - timedelta(minutes=6),
        evidence_completed_at=now - timedelta(minutes=1),
        evaluated_at=now,
        valid_until=now + timedelta(minutes=valid_minutes),
        technical_metadata={"manual_only": True},
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


def _assessment_payload(assessment):
    return {
        "assessment_id": assessment.assessment_id,
        "assessment_key": assessment.assessment_key,
        "lease_id": assessment.lease_id,
        "certification_id": assessment.certification_id,
        "binding_id": assessment.binding_id,
        "promotion_id": assessment.promotion_id,
        "scope": assessment.scope,
        "channel": assessment.channel,
        "consumer": assessment.consumer,
        "status": assessment.status,
        "parser_name": assessment.parser_name,
        "parser_version": assessment.parser_version,
        "parser_implementation_hash": assessment.parser_implementation_hash,
        "output_schema_version": assessment.output_schema_version,
        "release_manifest_hash": assessment.release_manifest_hash,
        "lease_event_hash": assessment.lease_event_hash,
        "certification_event_hash": assessment.certification_event_hash,
        "readiness_policy_hash": assessment.readiness_policy_hash,
        "evidence_hash": assessment.evidence_hash,
        "valid_until": assessment.valid_until,
    }


def _patch_ready(monkeypatch, assessment, **changes):
    import backend.app.services.blockchain_parser_shadow_automation_permit_service as service

    def fake_resolution(*args, **kwargs):
        payload = _assessment_payload(assessment)
        payload.update(changes.pop("assessment_changes", {}))
        return {
            "resolved": changes.get("resolved", True),
            "status": changes.get("status", "READY"),
            "reason_codes": changes.get("reason_codes", []),
            "readiness_enabled": True,
            "consumer_authorized": changes.get("consumer_authorized", True),
            "consumer_connected": False,
            "assessment": payload,
            "automatic_execution": False,
            "starts_workers": False,
            "live_execution": False,
        }

    monkeypatch.setattr(service, "resolve_shadow_consumer_readiness", fake_resolution)


def _issue(db, monkeypatch, assessment, *, now=NOW, settings_object=None, **kwargs):
    _patch_ready(monkeypatch, assessment)
    policy = settings_object or _permit_settings()
    preview = preview_shadow_automation_permit(
        db,
        assessment_id=assessment.assessment_id,
        validity_minutes=kwargs.get("validity_minutes", 5),
        run_budget=kwargs.get("run_budget", 3),
        event_budget=kwargs.get("event_budget", 50),
        settings_object=policy,
        evaluated_at=now,
    )
    return issue_shadow_automation_permit(
        db,
        confirmation=preview["confirmation"],
        assessment_id=assessment.assessment_id,
        validity_minutes=kwargs.get("validity_minutes", 5),
        run_budget=kwargs.get("run_budget", 3),
        event_budget=kwargs.get("event_budget", 50),
        actor_label="operator<script>",
        note="bounded permit",
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


def test_m14_constants_are_stable():
    assert AUTOMATION_PERMIT_POLICY_VERSION == "canonical-parser-shadow-automation-permit/1"
    assert AUTOMATION_PERMIT_CONFIRMATION_PREFIX == "ISSUE_CERTIFIED_SHADOW_AUTOMATION_PERMIT"
    assert AUTOMATION_PERMIT_REVOKE_PREFIX == "REVOKE_CERTIFIED_SHADOW_AUTOMATION_PERMIT"
    assert AUTOMATION_PERMIT_CONSUMER == "CERTIFIED_SHADOW_AUTOMATION"


def test_m14_status_defaults_to_disabled_and_empty(db_factory):
    with db_factory() as db:
        status = get_shadow_automation_permit_status(db)
        assert status["permit_enabled"] is False
        assert status["permit_count"] == 0
        assert status["operational_guards"]["scheduler_connected"] is False
        assert status["operational_guards"]["worker_connected"] is False


def test_m14_preview_ready_has_bounded_confirmation(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _patch_ready(monkeypatch, assessment)
        preview = preview_shadow_automation_permit(
            db,
            assessment_id=assessment.assessment_id,
            settings_object=_permit_settings(),
            evaluated_at=NOW,
        )
        assert preview["issuable"] is True
        assert preview["run_budget"] == 3
        assert preview["event_budget"] == 50
        assert preview["confirmation"].startswith(
            f"{AUTOMATION_PERMIT_CONFIRMATION_PREFIX}:{assessment.assessment_id}:"
        )
        assert preview["writes_database"] is False


def test_m14_preview_rejects_policy_limits(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _patch_ready(monkeypatch, assessment)
        preview = preview_shadow_automation_permit(
            db,
            validity_minutes=11,
            run_budget=6,
            event_budget=101,
            settings_object=_permit_settings(),
            evaluated_at=NOW,
        )
        assert preview["issuable"] is False
        assert "AUTOMATION_PERMIT_VALIDITY_ABOVE_MAXIMUM" in preview["reason_codes"]
        assert "AUTOMATION_PERMIT_RUN_BUDGET_ABOVE_MAXIMUM" in preview["reason_codes"]
        assert "AUTOMATION_PERMIT_EVENT_BUDGET_ABOVE_MAXIMUM" in preview["reason_codes"]


def test_m14_preview_requires_authorized_readiness(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _patch_ready(monkeypatch, assessment, consumer_authorized=False)
        preview = preview_shadow_automation_permit(
            db, settings_object=_permit_settings(), evaluated_at=NOW
        )
        assert preview["issuable"] is False
        assert "SHADOW_READINESS_NOT_AUTHORIZED" in preview["reason_codes"]


def test_m14_preview_requires_remaining_readiness_window(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db, valid_minutes=1)
        _patch_ready(monkeypatch, assessment)
        preview = preview_shadow_automation_permit(
            db, settings_object=_permit_settings(), evaluated_at=NOW
        )
        assert preview["issuable"] is False
        assert "SHADOW_READINESS_REMAINING_WINDOW_TOO_SHORT" in preview["reason_codes"]


def test_m14_issue_disabled_fails_closed(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _patch_ready(monkeypatch, assessment)
        with pytest.raises(CanonicalParserShadowAutomationPermitError) as error:
            issue_shadow_automation_permit(
                db,
                confirmation="x",
                settings_object=_permit_settings(enabled=False),
                issued_at=NOW,
            )
        assert error.value.code == "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_DISABLED"


def test_m14_issue_requires_dynamic_confirmation(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _patch_ready(monkeypatch, assessment)
        with pytest.raises(CanonicalParserShadowAutomationPermitError) as error:
            issue_shadow_automation_permit(
                db,
                confirmation="wrong",
                assessment_id=assessment.assessment_id,
                settings_object=_permit_settings(),
                issued_at=NOW,
            )
        assert error.value.code == "SHADOW_AUTOMATION_PERMIT_CONFIRMATION_REQUIRED"


def test_m14_issue_creates_permit_and_audit_event(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        result = _issue(db, monkeypatch, assessment)
        assert result["created"] is True
        assert result["status"] == "ACTIVE"
        assert result["run_budget"] == 3
        assert result["event_budget"] == 50
        assert result["remaining_run_budget"] == 3
        assert result["remaining_event_budget"] == 50
        assert result["actor_label"] == "operator<script>"
        permit = db.scalar(select(CanonicalParserShadowAutomationPermit))
        event = db.scalar(select(CanonicalParserShadowAutomationPermitEvent))
        assert permit is not None and event is not None
        assert event.event_type == "ISSUED"
        assert calculate_payload_hash(event.event_payload) == event.event_hash


def test_m14_active_permit_blocks_second_issue(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment)
        preview = preview_shadow_automation_permit(
            db,
            assessment_id=assessment.assessment_id,
            settings_object=_permit_settings(),
            evaluated_at=NOW + timedelta(seconds=1),
        )
        assert preview["issuable"] is False
        assert "ACTIVE_SHADOW_AUTOMATION_PERMIT_EXISTS" in preview["reason_codes"]


def test_m14_expired_permit_is_closed_before_reissue(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        first = _issue(
            db,
            monkeypatch,
            assessment,
            validity_minutes=1,
            now=NOW,
        )
        _patch_ready(monkeypatch, assessment)
        later = NOW + timedelta(minutes=2)
        preview = preview_shadow_automation_permit(
            db,
            assessment_id=assessment.assessment_id,
            validity_minutes=1,
            settings_object=_permit_settings(),
            evaluated_at=later,
        )
        second = issue_shadow_automation_permit(
            db,
            confirmation=preview["confirmation"],
            assessment_id=assessment.assessment_id,
            validity_minutes=1,
            settings_object=_permit_settings(),
            issued_at=later,
        )
        assert first["permit_id"] != second["permit_id"]
        assert first["permit_id"] in second["expired_permit_ids"]
        statuses = list(db.scalars(select(CanonicalParserShadowAutomationPermit.status)))
        assert sorted(statuses) == ["ACTIVE", "EXPIRED"]


def test_m14_get_returns_audit_state_and_revoke_confirmation(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        result = _issue(db, monkeypatch, assessment)
        payload = get_shadow_automation_permit(db, result["permit_id"])
        assert payload["audit_chain_valid"] is True
        assert payload["revoke_confirmation"] == f"{AUTOMATION_PERMIT_REVOKE_PREFIX}:{result['permit_id']}"


def test_m14_get_missing_returns_404(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowAutomationPermitError) as error:
            get_shadow_automation_permit(db, str(uuid4()))
        assert error.value.status_code == 404


def test_m14_revoke_requires_confirmation_and_reason(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        result = _issue(db, monkeypatch, assessment)
        with pytest.raises(CanonicalParserShadowAutomationPermitError) as error:
            revoke_shadow_automation_permit(
                db,
                permit_id=result["permit_id"],
                confirmation="wrong",
                reason="stop",
                settings_object=_permit_settings(),
                revoked_at=NOW + timedelta(minutes=1),
            )
        assert error.value.code == "SHADOW_AUTOMATION_PERMIT_REVOKE_CONFIRMATION_REQUIRED"
        with pytest.raises(CanonicalParserShadowAutomationPermitError) as error:
            revoke_shadow_automation_permit(
                db,
                permit_id=result["permit_id"],
                confirmation=f"{AUTOMATION_PERMIT_REVOKE_PREFIX}:{result['permit_id']}",
                reason="   ",
                settings_object=_permit_settings(),
                revoked_at=NOW + timedelta(minutes=1),
            )
        assert error.value.code == "SHADOW_AUTOMATION_PERMIT_REVOKE_REASON_REQUIRED"


def test_m14_revoke_appends_audit_event_and_is_idempotent(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        result = _issue(db, monkeypatch, assessment)
        confirmation = f"{AUTOMATION_PERMIT_REVOKE_PREFIX}:{result['permit_id']}"
        revoked = revoke_shadow_automation_permit(
            db,
            permit_id=result["permit_id"],
            confirmation=confirmation,
            reason="manual stop",
            settings_object=_permit_settings(),
            revoked_at=NOW + timedelta(minutes=1),
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["updated"] is True
        again = revoke_shadow_automation_permit(
            db,
            permit_id=result["permit_id"],
            confirmation=confirmation,
            reason="manual stop",
            settings_object=_permit_settings(),
            revoked_at=NOW + timedelta(minutes=2),
        )
        assert again["updated"] is False
        assert db.query(CanonicalParserShadowAutomationPermitEvent).count() == 2


def test_m14_tampered_audit_chain_blocks_revoke(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        result = _issue(db, monkeypatch, assessment)
        event = db.scalar(select(CanonicalParserShadowAutomationPermitEvent))
        event.event_payload = {"tampered": True}
        db.commit()
        with pytest.raises(CanonicalParserShadowAutomationPermitError) as error:
            revoke_shadow_automation_permit(
                db,
                permit_id=result["permit_id"],
                confirmation=f"{AUTOMATION_PERMIT_REVOKE_PREFIX}:{result['permit_id']}",
                reason="stop",
                settings_object=_permit_settings(),
                revoked_at=NOW + timedelta(minutes=1),
            )
        assert error.value.code == "PARSER_SHADOW_AUTOMATION_PERMIT_AUDIT_CHAIN_INVALID"


def test_m14_resolve_ready_and_authorized(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        result = _issue(db, monkeypatch, assessment)
        _patch_ready(monkeypatch, assessment)
        resolution = resolve_shadow_automation_permit(
            db, settings_object=_permit_settings(), evaluated_at=NOW
        )
        assert resolution["resolved"] is True
        assert resolution["status"] == "READY"
        assert resolution["automation_authorized"] is True
        assert resolution["permit"]["permit_id"] == result["permit_id"]
        assert resolution["scheduler_connected"] is False


def test_m14_resolve_ready_but_feature_disabled_is_not_authorized(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment)
        _patch_ready(monkeypatch, assessment)
        resolution = resolve_shadow_automation_permit(
            db, settings_object=_permit_settings(enabled=False), evaluated_at=NOW
        )
        assert resolution["resolved"] is False or resolution["status"] in {"READY", "DRIFTED"}
        assert resolution["automation_authorized"] is False


def test_m14_resolve_unpermitted(db_factory):
    with db_factory() as db:
        resolution = resolve_shadow_automation_permit(
            db, settings_object=_permit_settings(), evaluated_at=NOW
        )
        assert resolution["status"] == "UNPERMITTED"
        assert resolution["automation_authorized"] is False


def test_m14_resolve_expired(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment, validity_minutes=1)
        _patch_ready(monkeypatch, assessment)
        resolution = resolve_shadow_automation_permit(
            db,
            settings_object=_permit_settings(),
            evaluated_at=NOW + timedelta(minutes=2),
        )
        assert resolution["status"] == "EXPIRED"
        assert resolution["resolved"] is False


def test_m14_resolve_exhausted_run_budget(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment)
        permit = db.scalar(select(CanonicalParserShadowAutomationPermit))
        permit.consumed_run_count = permit.run_budget
        db.commit()
        _patch_ready(monkeypatch, assessment)
        resolution = resolve_shadow_automation_permit(
            db, settings_object=_permit_settings(), evaluated_at=NOW
        )
        assert resolution["status"] == "EXHAUSTED"
        assert "SHADOW_AUTOMATION_PERMIT_RUN_BUDGET_EXHAUSTED" in resolution["reason_codes"]


def test_m14_resolve_exhausted_event_budget(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment)
        permit = db.scalar(select(CanonicalParserShadowAutomationPermit))
        permit.consumed_event_count = permit.event_budget
        db.commit()
        _patch_ready(monkeypatch, assessment)
        resolution = resolve_shadow_automation_permit(
            db, settings_object=_permit_settings(), evaluated_at=NOW
        )
        assert resolution["status"] == "EXHAUSTED"
        assert "SHADOW_AUTOMATION_PERMIT_EVENT_BUDGET_EXHAUSTED" in resolution["reason_codes"]


def test_m14_resolve_detects_policy_drift(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment)
        _patch_ready(monkeypatch, assessment)
        resolution = resolve_shadow_automation_permit(
            db,
            settings_object=_permit_settings(
                CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_RUN_BUDGET=6
            ),
            evaluated_at=NOW,
        )
        assert resolution["status"] == "DRIFTED"
        assert "SHADOW_AUTOMATION_PERMIT_POLICY_DRIFT" in resolution["reason_codes"]


def test_m14_resolve_detects_readiness_drift(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment)
        _patch_ready(
            monkeypatch,
            assessment,
            resolved=False,
            status="DRIFTED",
            reason_codes=["SHADOW_READINESS_CURRENT_RUN_DRIFT"],
            consumer_authorized=False,
        )
        resolution = resolve_shadow_automation_permit(
            db, settings_object=_permit_settings(), evaluated_at=NOW
        )
        assert resolution["status"] == "DRIFTED"
        assert "SHADOW_READINESS_CURRENT_RUN_DRIFT" in resolution["reason_codes"]


def test_m14_resolve_detects_assessment_evidence_tampering(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment)
        assessment.evidence_snapshot = {"tampered": True}
        db.commit()
        _patch_ready(monkeypatch, assessment)
        resolution = resolve_shadow_automation_permit(
            db, settings_object=_permit_settings(), evaluated_at=NOW
        )
        assert resolution["status"] == "DRIFTED"
        assert "SHADOW_AUTOMATION_PERMIT_READINESS_EVIDENCE_HASH_INVALID" in resolution["reason_codes"]


def test_m14_resolve_detects_assessment_key_tampering(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment)
        assessment.assessment_key = "f" * 64
        db.commit()
        _patch_ready(monkeypatch, assessment)
        resolution = resolve_shadow_automation_permit(
            db, settings_object=_permit_settings(), evaluated_at=NOW
        )
        assert resolution["status"] == "DRIFTED"
        assert "SHADOW_AUTOMATION_PERMIT_ASSESSMENT_KEY_INVALID" in resolution["reason_codes"]


def test_m14_status_counts_terminal_states(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        result = _issue(db, monkeypatch, assessment)
        revoke_shadow_automation_permit(
            db,
            permit_id=result["permit_id"],
            confirmation=f"{AUTOMATION_PERMIT_REVOKE_PREFIX}:{result['permit_id']}",
            reason="done",
            settings_object=_permit_settings(),
            revoked_at=NOW + timedelta(minutes=1),
        )
        status = get_shadow_automation_permit_status(
            db, settings_object=_permit_settings()
        )
        assert status["permit_count"] == 1
        assert status["status_counts"]["REVOKED"] == 1


def test_m14_models_registered_and_active_permit_unique(db_factory, monkeypatch):
    names = set(Base.metadata.tables)
    assert "canonical_parser_shadow_automation_permits" in names
    assert "canonical_parser_shadow_automation_permit_events" in names
    assert models.CanonicalParserShadowAutomationPermit is CanonicalParserShadowAutomationPermit
    assert models.CanonicalParserShadowAutomationPermitEvent is CanonicalParserShadowAutomationPermitEvent
    with db_factory() as db:
        assessment = _create_ready_assessment(db)
        _issue(db, monkeypatch, assessment)
        existing = db.scalar(select(CanonicalParserShadowAutomationPermit))
        duplicate = CanonicalParserShadowAutomationPermit(
            permit_id=str(uuid4()),
            permit_key="a" * 64,
            permit_generation=2,
            assessment_db_id=assessment.id,
            assessment_id=assessment.assessment_id,
            assessment_key=assessment.assessment_key,
            lease_id=assessment.lease_id,
            certification_id=assessment.certification_id,
            binding_id=assessment.binding_id,
            promotion_id=assessment.promotion_id,
            scope="SHADOW_ONLY",
            channel="CANONICAL_SHADOW",
            consumer=AUTOMATION_PERMIT_CONSUMER,
            status="ACTIVE",
            parser_name=assessment.parser_name,
            parser_version=assessment.parser_version,
            parser_implementation_hash=assessment.parser_implementation_hash,
            output_schema_version=assessment.output_schema_version,
            release_manifest_hash=assessment.release_manifest_hash,
            lease_event_hash=assessment.lease_event_hash,
            certification_event_hash=assessment.certification_event_hash,
            readiness_policy_hash=assessment.readiness_policy_hash,
            readiness_evidence_hash=assessment.evidence_hash,
            permit_policy_version=existing.permit_policy_version,
            permit_policy_hash=existing.permit_policy_hash,
            permit_policy_snapshot=existing.permit_policy_snapshot,
            requested_validity_minutes=5,
            run_budget=3,
            event_budget=50,
            consumed_run_count=0,
            consumed_event_count=0,
            actor_label="x",
            note=None,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
            revoked_at=None,
            revocation_reason=None,
            latest_event_sequence=1,
            latest_event_hash="b" * 64,
            technical_metadata={},
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


def test_m14_service_has_no_network_trade_live_worker_or_budget_consumer():
    path = Path(
        "backend/app/services/blockchain_parser_shadow_automation_permit_service.py"
    )
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
    assert '"scheduler_connected": False' in source
    assert '"worker_connected": False' in source


def test_m14_service_not_imported_by_operational_pipelines():
    forbidden = []
    allowed = {
        "main.py",
        "blockchain_parser_shadow_automation_permit_service.py",
        "blockchain_parser_shadow_execution_ticket_service.py",
    }
    for path in Path("backend/app").rglob("*.py"):
        if path.name in allowed:
            continue
        if "blockchain_parser_shadow_automation_permit_service" in path.read_text(
            encoding="utf-8"
        ):
            forbidden.append(str(path))
    assert forbidden == []


def test_m14_api_routes_are_protected_and_registered_once(db_factory):
    counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            counts[(method, getattr(route, "path", ""))] += 1
    expected = {
        ("GET", "/integrity/parser-shadow-automation-permit/status"),
        ("GET", "/integrity/parser-shadow-automation-permit/preview"),
        ("POST", "/integrity/parser-shadow-automation-permit/issue"),
        ("POST", "/integrity/parser-shadow-automation-permit/revoke"),
        ("GET", "/integrity/parser-shadow-automation-permit/permits/{permit_id}"),
        ("GET", "/integrity/parser-shadow-automation-permit/resolve"),
    }
    for route in expected:
        assert counts[route] == 1
    client = _client(db_factory)
    try:
        assert client.get("/integrity/parser-shadow-automation-permit/status").status_code == 401
        response = client.get(
            "/integrity/parser-shadow-automation-permit/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["permit_enabled"] is False
        post = client.post(
            "/integrity/parser-shadow-automation-permit/issue",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={"confirmation": "anything"},
        )
        assert post.status_code == 409
        assert post.json()["detail"]["code"] == "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_DISABLED"
    finally:
        app.dependency_overrides.clear()


def test_m14_migration_upgrade_downgrade_upgrade_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    path = Path(
        "alembic/versions/a5c9e2f4b716_add_shadow_automation_permit.py"
    )
    spec = importlib.util.spec_from_file_location("m14_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE canonical_parser_shadow_readiness_assessments "
            "(id INTEGER PRIMARY KEY)"
        )
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_shadow_automation_permits" in names
    assert "canonical_parser_shadow_automation_permit_events" in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.downgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_shadow_automation_permits" not in names
    assert "canonical_parser_shadow_automation_permit_events" not in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    assert "canonical_parser_shadow_automation_permits" in inspect(engine).get_table_names()
    engine.dispose()
