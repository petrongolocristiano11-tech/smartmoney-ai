from __future__ import annotations

import ast
import importlib.util
import socket
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalNormalizedEvent,
    CanonicalParserPromotion,
    CanonicalParserPromotionEvent,
    CanonicalQualityAssessment,
    CanonicalShadowValidationBatch,
    CanonicalShadowValidationResult,
    NormalizationArtifact,
    NormalizationReplayBatch,
    NormalizationRun,
    RawBlockchainEvent,
)
from backend.app.models.trade import Trade
from backend.app.services.blockchain_canonical_quality_gate_service import (
    QUALITY_GATE_CONFIRMATION,
    execute_canonical_quality_assessment,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
from backend.app.services.blockchain_parser_promotion_service import (
    APPROVAL_CONFIRMATION_PREFIX,
    REVOCATION_CONFIRMATION_PREFIX,
    CanonicalParserPromotionError,
    approve_parser_promotion,
    get_parser_promotion,
    get_parser_promotion_status,
    preview_parser_promotion,
    revoke_parser_promotion,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
)


AUTOMATION_KEY = "a" * 32
FIXED_NOW = datetime(2026, 7, 25, 20, 0, tzinfo=timezone.utc)
PARSER_DEFINITION = DEFAULT_PARSER_REGISTRY.get("swap_canonical_event", "1.0.0")
M7_TABLES = [
    RawBlockchainEvent.__table__,
    NormalizationRun.__table__,
    NormalizationReplayBatch.__table__,
    NormalizationArtifact.__table__,
    Trade.__table__,
    CanonicalNormalizedEvent.__table__,
    CanonicalShadowValidationBatch.__table__,
    CanonicalShadowValidationResult.__table__,
    CanonicalQualityAssessment.__table__,
    CanonicalParserPromotion.__table__,
    CanonicalParserPromotionEvent.__table__,
]


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=M7_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def safe_global_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_PROMOTION_ENABLED", False)
    monkeypatch.setattr(settings, "CANONICAL_QUALITY_GATE_ENABLED", False)
    monkeypatch.setattr(settings, "CANONICAL_NORMALIZATION_ENABLED", False)
    monkeypatch.setattr(settings, "CANONICAL_SHADOW_VALIDATION_ENABLED", False)
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_REPLAY_ENABLED", False)
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", False)
    monkeypatch.setattr(settings, "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED", False)
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


def _policy(*, promotion_enabled: bool = False, **overrides):
    values = {
        "CANONICAL_PARSER_PROMOTION_ENABLED": promotion_enabled,
        "CANONICAL_PARSER_PROMOTION_MAX_ASSESSMENT_AGE_HOURS": 168,
        "CANONICAL_QUALITY_GATE_ENABLED": True,
        "CANONICAL_QUALITY_GATE_MIN_COMPARABLE_EVENTS": 10,
        "CANONICAL_QUALITY_GATE_MIN_MATCH_RATE": 98.0,
        "CANONICAL_QUALITY_GATE_MAX_MISMATCH_RATE": 2.0,
        "CANONICAL_QUALITY_GATE_MAX_MISSING_TRADE_RATE": 10.0,
        "CANONICAL_QUALITY_GATE_MAX_NOT_COMPARABLE_RATE": 5.0,
        "CANONICAL_QUALITY_GATE_MAX_FAILED_RATE": 0.5,
        "CANONICAL_QUALITY_GATE_MIN_PASS_QUALITY_RATE": 95.0,
        "CANONICAL_QUALITY_GATE_MAX_EVIDENCE_AGE_HOURS": 168,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _add_chain(db: Session, *, index: int):
    signature = f"m7-signature-{index}"
    payload = {"signature": signature, "index": index}
    payload_hash = calculate_payload_hash(payload)
    raw = RawBlockchainEvent(
        provider="helius",
        chain="solana",
        network="mainnet-beta",
        event_type="WALLET_HISTORY_RESPONSE",
        transaction_signature=signature,
        slot=index,
        block_time=FIXED_NOW,
        observed_wallet="WalletM7",
        commitment="finalized",
        raw_payload=payload,
        payload_hash=payload_hash,
        deduplication_key=calculate_payload_hash(
            {"signature": signature, "payload_hash": payload_hash}
        ),
        event_metadata={},
        first_seen_at=FIXED_NOW,
        last_seen_at=FIXED_NOW,
        observation_count=1,
    )
    db.add(raw)
    db.flush()
    run = NormalizationRun(
        run_id=str(uuid4()),
        raw_event_id=raw.id,
        parser_name=PARSER_DEFINITION.name,
        parser_version=PARSER_DEFINITION.version,
        status="COMPLETED",
        started_at=FIXED_NOW,
        completed_at=FIXED_NOW,
        produced_event_count=1,
        produced_trade_count=0,
        warnings=[],
        technical_metadata={},
    )
    db.add(run)
    db.flush()
    artifact_payload = {"signature": signature, "side": "BUY"}
    artifact = NormalizationArtifact(
        normalization_run_id=run.id,
        raw_event_id=raw.id,
        parser_name=PARSER_DEFINITION.name,
        parser_version=PARSER_DEFINITION.version,
        parser_implementation_hash=PARSER_DEFINITION.implementation_hash,
        artifact_type="CANONICAL_SWAP_EVENT",
        artifact_index=0,
        schema_version=PARSER_DEFINITION.output_schema_version,
        payload=artifact_payload,
        payload_hash=calculate_payload_hash(artifact_payload),
        artifact_metadata={},
    )
    db.add(artifact)
    db.flush()
    canonical_payload = {
        "signature": signature,
        "side": "BUY",
        "token_mint": "TokenM7",
        "token_amount": "10",
        "sol_amount": "0.1",
    }
    canonical = CanonicalNormalizedEvent(
        canonical_event_id=str(uuid4()),
        canonical_event_key=calculate_payload_hash(
            {"signature": signature, "artifact_id": artifact.id}
        ),
        normalization_artifact_id=artifact.id,
        normalization_run_id=run.id,
        raw_event_id=raw.id,
        parser_name=PARSER_DEFINITION.name,
        parser_version=PARSER_DEFINITION.version,
        parser_implementation_hash=PARSER_DEFINITION.implementation_hash,
        schema_version=PARSER_DEFINITION.output_schema_version,
        canonical_type="SWAP",
        transaction_signature=signature,
        observed_wallet="WalletM7",
        side="BUY",
        source="JUPITER",
        token_mint="TokenM7",
        token_amount=10,
        sol_amount=0.1,
        fee_lamports=5000,
        success=True,
        block_time=FIXED_NOW,
        quality_status="PASS",
        quality_flags=[],
        canonical_payload=canonical_payload,
        canonical_payload_hash=calculate_payload_hash(canonical_payload),
        technical_metadata={},
    )
    db.add(canonical)
    db.flush()
    return canonical


def _insert_ready_assessment(db: Session, *, seed: int = 0):
    batch = CanonicalShadowValidationBatch(
        validation_id=str(uuid4()),
        comparator_version="canonical-trade-shadow/1",
        status="COMPLETED",
        request_filters={},
        requested_limit=10,
        selected_count=10,
        processed_count=10,
        match_count=10,
        mismatch_count=0,
        missing_trade_count=0,
        not_comparable_count=0,
        failed_count=0,
        started_at=FIXED_NOW - timedelta(minutes=1),
        completed_at=FIXED_NOW,
        technical_metadata={"external_requests": 0, "writes_trades": False},
    )
    db.add(batch)
    db.flush()
    for index in range(10):
        canonical = _add_chain(db, index=seed * 1000 + index)
        canonical_snapshot = {
            "signature": canonical.transaction_signature,
            "side": "BUY",
            "token_amount": "10",
        }
        trade_snapshot = dict(canonical_snapshot)
        db.add(
            CanonicalShadowValidationResult(
                validation_batch_id=batch.id,
                canonical_event_id=canonical.id,
                trade_id=None,
                transaction_signature=canonical.transaction_signature,
                comparator_version=batch.comparator_version,
                status="MATCH",
                mismatch_fields=[],
                canonical_snapshot=canonical_snapshot,
                trade_snapshot=trade_snapshot,
                canonical_snapshot_hash=calculate_payload_hash(
                    canonical_snapshot
                ),
                trade_snapshot_hash=calculate_payload_hash(trade_snapshot),
                technical_metadata={
                    "external_requests": 0,
                    "writes_trades": False,
                },
            )
        )
    db.commit()
    result = execute_canonical_quality_assessment(
        db,
        confirmation=QUALITY_GATE_CONFIRMATION,
        validation_id=batch.validation_id,
        settings_object=_policy(),
        evaluated_at=FIXED_NOW,
    )
    return db.query(CanonicalQualityAssessment).filter_by(
        assessment_id=result["assessment_id"]
    ).one()


def _client(db_factory):
    def override_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _approve(db: Session, assessment: CanonicalQualityAssessment):
    policy = _policy(promotion_enabled=True)
    preview = preview_parser_promotion(
        db,
        assessment_id=assessment.assessment_id,
        settings_object=policy,
        evaluated_at=FIXED_NOW,
    )
    return approve_parser_promotion(
        db,
        assessment_id=assessment.assessment_id,
        confirmation=preview["confirmation"],
        settings_object=policy,
        approved_at=FIXED_NOW,
    )


def test_m7_models_registered_and_exported():
    assert models.CanonicalParserPromotion is CanonicalParserPromotion
    assert models.CanonicalParserPromotionEvent is CanonicalParserPromotionEvent
    assert "canonical_parser_promotions" in Base.metadata.tables
    assert "canonical_parser_promotion_events" in Base.metadata.tables


def test_m7_configuration_defaults_are_safe():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_PROMOTION_ENABLED is False
    assert configured.CANONICAL_PARSER_PROMOTION_MAX_ASSESSMENT_AGE_HOURS == 168


def test_preview_requires_ready_assessment(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserPromotionError) as error:
            preview_parser_promotion(db, settings_object=_policy())
    assert error.value.code == "PARSER_PROMOTION_ASSESSMENT_NOT_FOUND"


def test_preview_ready_assessment_is_eligible_and_deterministic(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        first = preview_parser_promotion(
            db,
            assessment_id=assessment.assessment_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
        second = preview_parser_promotion(
            db,
            assessment_id=assessment.assessment_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert first["eligible"] is True
    assert first["promotion_key"] == second["promotion_key"]
    assert first["release_manifest_hash"] == second["release_manifest_hash"]
    assert first["confirmation"].startswith(APPROVAL_CONFIRMATION_PREFIX)
    assert first["operational_guards"]["activates_runtime_parser"] is False


def test_preview_latest_ready_assessment_when_id_omitted(db_factory):
    with db_factory() as db:
        _insert_ready_assessment(db, seed=1)
        latest = _insert_ready_assessment(db, seed=2)
        preview = preview_parser_promotion(
            db,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["assessment_id"] == latest.assessment_id


def test_non_ready_assessment_is_blocked(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        assessment.status = "REVIEW"
        db.commit()
        preview = preview_parser_promotion(
            db,
            assessment_id=assessment.assessment_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["eligible"] is False
    assert "ASSESSMENT_NOT_READY" in preview["blocker_codes"]


def test_stale_assessment_is_blocked(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        preview = preview_parser_promotion(
            db,
            assessment_id=assessment.assessment_id,
            settings_object=_policy(
                CANONICAL_PARSER_PROMOTION_MAX_ASSESSMENT_AGE_HOURS=1
            ),
            evaluated_at=FIXED_NOW + timedelta(hours=2),
        )
    assert "ASSESSMENT_EVIDENCE_STALE" in preview["blocker_codes"]


def test_parser_hash_mismatch_is_blocked(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        assessment.parser_implementation_hash = "f" * 64
        db.commit()
        preview = preview_parser_promotion(
            db,
            assessment_id=assessment.assessment_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["eligible"] is False
    assert "PARSER_IMPLEMENTATION_HASH_MISMATCH" in preview["blocker_codes"]


def test_unregistered_parser_is_blocked(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        assessment.parser_name = "unknown_parser"
        db.commit()
        preview = preview_parser_promotion(
            db,
            assessment_id=assessment.assessment_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert "PARSER_NOT_REGISTERED" in preview["blocker_codes"]


def test_unsupported_scope_is_rejected(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        with pytest.raises(CanonicalParserPromotionError) as error:
            preview_parser_promotion(
                db,
                assessment_id=assessment.assessment_id,
                scope="LIVE",
                settings_object=_policy(),
            )
    assert error.value.code == "PARSER_PROMOTION_SCOPE_UNSUPPORTED"


def test_approval_requires_feature_flag(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        with pytest.raises(CanonicalParserPromotionError) as error:
            approve_parser_promotion(
                db,
                assessment_id=assessment.assessment_id,
                confirmation="anything",
                settings_object=_policy(promotion_enabled=False),
            )
    assert error.value.code == "CANONICAL_PARSER_PROMOTION_DISABLED"


def test_approval_requires_dynamic_confirmation(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        with pytest.raises(CanonicalParserPromotionError) as error:
            approve_parser_promotion(
                db,
                assessment_id=assessment.assessment_id,
                confirmation="APPROVE_CANONICAL_PARSER",
                settings_object=_policy(promotion_enabled=True),
                approved_at=FIXED_NOW,
            )
    assert error.value.code == "PARSER_PROMOTION_CONFIRMATION_REQUIRED"


def test_approval_persists_release_and_first_audit_event(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        result = _approve(db, assessment)
        promotion = db.query(CanonicalParserPromotion).one()
        event = db.query(CanonicalParserPromotionEvent).one()
    assert result["created"] is True
    assert result["status"] == "APPROVED"
    assert result["audit_chain"]["valid"] is True
    assert promotion.latest_event_sequence == 1
    assert promotion.latest_event_hash == event.event_hash
    assert event.event_type == "APPROVED"


def test_approval_is_idempotent(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        first = _approve(db, assessment)
        second = _approve(db, assessment)
        promotion_count = db.query(CanonicalParserPromotion).count()
        event_count = db.query(CanonicalParserPromotionEvent).count()
    assert first["created"] is True
    assert second["created"] is False
    assert promotion_count == 1
    assert event_count == 1


def test_active_promotion_blocks_different_assessment(db_factory):
    with db_factory() as db:
        first_assessment = _insert_ready_assessment(db, seed=1)
        _approve(db, first_assessment)
        second_assessment = _insert_ready_assessment(db, seed=2)
        preview = preview_parser_promotion(
            db,
            assessment_id=second_assessment.assessment_id,
            settings_object=_policy(promotion_enabled=True),
            evaluated_at=FIXED_NOW,
        )
    assert preview["eligible"] is False
    assert "ACTIVE_PROMOTION_ALREADY_EXISTS" in preview["blocker_codes"]


def test_revocation_requires_exact_confirmation(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        approved = _approve(db, assessment)
        with pytest.raises(CanonicalParserPromotionError) as error:
            revoke_parser_promotion(
                db,
                promotion_id=approved["promotion_id"],
                confirmation="REVOKE_CANONICAL_PARSER",
                reason="superseded",
                settings_object=_policy(promotion_enabled=True),
            )
    assert (
        error.value.code
        == "PARSER_PROMOTION_REVOCATION_CONFIRMATION_REQUIRED"
    )


def test_revocation_requires_reason(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        approved = _approve(db, assessment)
        with pytest.raises(CanonicalParserPromotionError) as error:
            revoke_parser_promotion(
                db,
                promotion_id=approved["promotion_id"],
                confirmation=(
                    f"{REVOCATION_CONFIRMATION_PREFIX}:"
                    f"{approved['promotion_id']}"
                ),
                reason=" ",
                settings_object=_policy(promotion_enabled=True),
            )
    assert error.value.code == "PARSER_PROMOTION_REVOCATION_REASON_REQUIRED"


def test_revocation_appends_hash_chained_event(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        approved = _approve(db, assessment)
        revoked = revoke_parser_promotion(
            db,
            promotion_id=approved["promotion_id"],
            confirmation=(
                f"{REVOCATION_CONFIRMATION_PREFIX}:{approved['promotion_id']}"
            ),
            reason="Parser superseded",
            settings_object=_policy(promotion_enabled=True),
            revoked_at=FIXED_NOW + timedelta(minutes=1),
        )
        events = db.query(CanonicalParserPromotionEvent).order_by(
            CanonicalParserPromotionEvent.sequence
        ).all()
    assert revoked["status"] == "REVOKED"
    assert revoked["audit_chain"]["valid"] is True
    assert [event.sequence for event in events] == [1, 2]
    assert events[1].previous_event_hash == events[0].event_hash


def test_revocation_is_idempotent(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        approved = _approve(db, assessment)
        confirmation = (
            f"{REVOCATION_CONFIRMATION_PREFIX}:{approved['promotion_id']}"
        )
        first = revoke_parser_promotion(
            db,
            promotion_id=approved["promotion_id"],
            confirmation=confirmation,
            reason="Parser superseded",
            settings_object=_policy(promotion_enabled=True),
        )
        second = revoke_parser_promotion(
            db,
            promotion_id=approved["promotion_id"],
            confirmation=confirmation,
            reason="Parser superseded",
            settings_object=_policy(promotion_enabled=True),
        )
    assert first["created"] is True
    assert second["created"] is False
    assert db.query(CanonicalParserPromotionEvent).count() == 2


def test_revocation_frees_active_slot_for_new_assessment(db_factory):
    with db_factory() as db:
        first_assessment = _insert_ready_assessment(db, seed=1)
        approved = _approve(db, first_assessment)
        revoke_parser_promotion(
            db,
            promotion_id=approved["promotion_id"],
            confirmation=(
                f"{REVOCATION_CONFIRMATION_PREFIX}:{approved['promotion_id']}"
            ),
            reason="New evidence required",
            settings_object=_policy(promotion_enabled=True),
        )
        second_assessment = _insert_ready_assessment(db, seed=2)
        preview = preview_parser_promotion(
            db,
            assessment_id=second_assessment.assessment_id,
            settings_object=_policy(promotion_enabled=True),
            evaluated_at=FIXED_NOW,
        )
    assert preview["eligible"] is True


def test_tampered_event_chain_blocks_revocation(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        approved = _approve(db, assessment)
        event = db.query(CanonicalParserPromotionEvent).one()
        event.actor_label = "TAMPERED"
        db.commit()
        detail = get_parser_promotion(db, approved["promotion_id"])
        with pytest.raises(CanonicalParserPromotionError) as error:
            revoke_parser_promotion(
                db,
                promotion_id=approved["promotion_id"],
                confirmation=(
                    f"{REVOCATION_CONFIRMATION_PREFIX}:"
                    f"{approved['promotion_id']}"
                ),
                reason="Security response",
                settings_object=_policy(promotion_enabled=True),
            )
    assert detail["audit_chain"]["valid"] is False
    assert error.value.code == "PARSER_PROMOTION_AUDIT_CHAIN_INVALID"


def test_note_and_reason_are_sanitized(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        policy = _policy(promotion_enabled=True)
        preview = preview_parser_promotion(
            db,
            assessment_id=assessment.assessment_id,
            settings_object=policy,
            evaluated_at=FIXED_NOW,
        )
        approved = approve_parser_promotion(
            db,
            assessment_id=assessment.assessment_id,
            confirmation=preview["confirmation"],
            note="api_key=SUPERSECRET",
            settings_object=policy,
            approved_at=FIXED_NOW,
        )
        detail = get_parser_promotion(db, approved["promotion_id"])
    serialized = str(detail)
    assert "SUPERSECRET" not in serialized
    assert "[REDACTED]" in serialized


def test_status_reports_counts_and_never_enables_runtime(db_factory):
    with db_factory() as db:
        empty = get_parser_promotion_status(db, settings_object=_policy())
        assessment = _insert_ready_assessment(db)
        _approve(db, assessment)
        populated = get_parser_promotion_status(
            db, settings_object=_policy(promotion_enabled=True)
        )
    assert empty["promotion_count"] == 0
    assert populated["status_counts"]["APPROVED"] == 1
    assert populated["operational_guards"]["runtime_selection_enabled"] is False


def test_get_promotion_includes_audit_events(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        approved = _approve(db, assessment)
        detail = get_parser_promotion(db, approved["promotion_id"])
    assert len(detail["events"]) == 1
    assert detail["events"][0]["event_type"] == "APPROVED"


def test_promotion_never_writes_trade_or_uses_network(monkeypatch, db_factory):
    def forbidden_network(*args, **kwargs):
        raise AssertionError("network access forbidden")

    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        before = db.query(Trade).count()
        _approve(db, assessment)
        after = db.query(Trade).count()
    assert before == after == 0


def test_m7_service_has_no_network_clients_or_trade_writes():
    path = Path(
        "backend/app/services/blockchain_parser_promotion_service.py"
    )
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
    assert "LIVE_" not in source


def test_m7_api_routes_are_protected_and_registered_once(db_factory):
    route_counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            route_counts[(method, getattr(route, "path", ""))] += 1
    expected = {
        ("GET", "/integrity/parser-promotion/status"),
        ("GET", "/integrity/parser-promotion/preview"),
        ("POST", "/integrity/parser-promotion/approve"),
        ("POST", "/integrity/parser-promotion/revoke"),
        ("GET", "/integrity/parser-promotion/promotions/{promotion_id}"),
    }
    for route_key in expected:
        assert route_counts[route_key] == 1

    client = _client(db_factory)
    try:
        assert client.get("/integrity/parser-promotion/status").status_code == 401
        response = client.get(
            "/integrity/parser-promotion/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["promotion_enabled"] is False
        execute_response = client.post(
            "/integrity/parser-promotion/approve",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={"confirmation": "anything"},
        )
        assert execute_response.status_code == 409
        assert (
            execute_response.json()["detail"]["code"]
            == "CANONICAL_PARSER_PROMOTION_DISABLED"
        )
    finally:
        app.dependency_overrides.clear()


def test_active_promotion_partial_unique_constraint(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        approved = _approve(db, assessment)
        original = db.query(CanonicalParserPromotion).one()
        duplicate = CanonicalParserPromotion(
            promotion_id=str(uuid4()),
            promotion_key="f" * 64,
            assessment_db_id=original.assessment_db_id,
            assessment_id=original.assessment_id,
            scope=original.scope,
            status="APPROVED",
            parser_name=original.parser_name,
            parser_version="9.9.9",
            parser_implementation_hash="e" * 64,
            output_schema_version=original.output_schema_version,
            assessment_policy_hash=original.assessment_policy_hash,
            assessment_evidence_hash=original.assessment_evidence_hash,
            promotion_policy_version=original.promotion_policy_version,
            promotion_policy_hash=original.promotion_policy_hash,
            release_manifest={},
            release_manifest_hash="d" * 64,
            approved_at=FIXED_NOW,
            latest_event_sequence=1,
            latest_event_hash="c" * 64,
            technical_metadata={},
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
    assert approved["created"] is True


def test_promotion_event_sequence_unique_constraint(db_factory):
    with db_factory() as db:
        assessment = _insert_ready_assessment(db)
        _approve(db, assessment)
        promotion = db.query(CanonicalParserPromotion).one()
        duplicate = CanonicalParserPromotionEvent(
            event_id=str(uuid4()),
            promotion_db_id=promotion.id,
            sequence=1,
            event_type="APPROVED",
            previous_status=None,
            new_status="APPROVED",
            actor_label="LOCAL_OPERATOR",
            reason=None,
            event_payload={"duplicate": True},
            previous_event_hash=None,
            event_hash="b" * 64,
            occurred_at=FIXED_NOW,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


def test_m7_migration_upgrade_downgrade_upgrade_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            RawBlockchainEvent.__table__,
            NormalizationRun.__table__,
            NormalizationReplayBatch.__table__,
            NormalizationArtifact.__table__,
            Trade.__table__,
            CanonicalNormalizedEvent.__table__,
            CanonicalShadowValidationBatch.__table__,
            CanonicalShadowValidationResult.__table__,
            CanonicalQualityAssessment.__table__,
        ],
    )
    migration_path = Path(
        "alembic/versions/f9c4d7a2b815_add_parser_promotion_ledger.py"
    )
    spec = importlib.util.spec_from_file_location("m7_migration", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        module.op = Operations(context)
        module.upgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_promotions" in names
    assert "canonical_parser_promotion_events" in names

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        module.op = Operations(context)
        module.downgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_promotions" not in names
    assert "canonical_parser_promotion_events" not in names

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        module.op = Operations(context)
        module.upgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_promotions" in names
    assert "canonical_parser_promotion_events" in names
    engine.dispose()
