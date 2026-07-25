from __future__ import annotations

import ast
import importlib.util
import socket
from collections import Counter
from datetime import datetime, timezone
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
    CanonicalParserPromotion,
    CanonicalParserPromotionEvent,
    CanonicalParserRuntimeBinding,
    CanonicalParserRuntimeBindingEvent,
    CanonicalQualityAssessment,
    CanonicalShadowValidationBatch,
)
from backend.app.models.trade import Trade
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
)
from backend.app.services.blockchain_parser_runtime_binding_service import (
    BIND_CONFIRMATION_PREFIX,
    RUNTIME_CHANNEL,
    RUNTIME_SCOPE,
    UNBIND_CONFIRMATION_PREFIX,
    CanonicalParserRuntimeBindingError,
    bind_parser_runtime,
    get_parser_runtime_binding,
    get_parser_runtime_status,
    preview_parser_runtime_binding,
    resolve_shadow_parser_runtime,
    unbind_parser_runtime,
)


AUTOMATION_KEY = "a" * 32
FIXED_NOW = datetime(2026, 7, 25, 22, 0, tzinfo=timezone.utc)
DEFINITION = DEFAULT_PARSER_REGISTRY.get("swap_canonical_event", "1.0.0")
M8_TABLES = [
    CanonicalShadowValidationBatch.__table__,
    CanonicalQualityAssessment.__table__,
    CanonicalParserPromotion.__table__,
    CanonicalParserPromotionEvent.__table__,
    CanonicalParserRuntimeBinding.__table__,
    CanonicalParserRuntimeBindingEvent.__table__,
]


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=M8_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def safe_global_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_RUNTIME_BINDING_ENABLED", False)
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


def _policy(*, binding_enabled: bool = False):
    return SimpleNamespace(
        CANONICAL_PARSER_RUNTIME_BINDING_ENABLED=binding_enabled,
    )


def _promotion_event_payload(
    *, event_id: str, promotion_id: str, occurred_at: datetime
) -> dict:
    return {
        "event_id": event_id,
        "promotion_id": promotion_id,
        "sequence": 1,
        "event_type": "APPROVED",
        "previous_status": None,
        "new_status": "APPROVED",
        "actor_label": "LOCAL_OPERATOR",
        "reason": None,
        "previous_event_hash": None,
        "occurred_at": occurred_at.isoformat(),
    }


def _insert_approved_promotion(
    db: Session,
    *, suffix: str = "one",
    status: str = "APPROVED",
) -> CanonicalParserPromotion:
    validation_id = str(uuid4())
    batch = CanonicalShadowValidationBatch(
        validation_id=validation_id,
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
        started_at=FIXED_NOW,
        completed_at=FIXED_NOW,
        technical_metadata={},
    )
    db.add(batch)
    db.flush()
    assessment_id = str(uuid4())
    assessment = CanonicalQualityAssessment(
        assessment_id=assessment_id,
        assessment_key=calculate_payload_hash({"assessment": suffix}),
        validation_batch_id=batch.id,
        validation_id=validation_id,
        policy_version="canonical-quality-gate/1",
        policy_hash=calculate_payload_hash({"policy": suffix}),
        evidence_hash=calculate_payload_hash({"evidence": suffix}),
        status="READY",
        parser_name=DEFINITION.name,
        parser_version=DEFINITION.version,
        parser_implementation_hash=DEFINITION.implementation_hash,
        comparator_version="canonical-trade-shadow/1",
        sample_size=10,
        comparable_count=10,
        match_count=10,
        mismatch_count=0,
        missing_trade_count=0,
        not_comparable_count=0,
        failed_count=0,
        quality_pass_count=10,
        quality_warn_count=0,
        quality_fail_count=0,
        match_rate=100,
        mismatch_rate=0,
        missing_trade_rate=0,
        not_comparable_rate=0,
        failed_rate=0,
        quality_pass_rate=100,
        reason_codes=[],
        mismatch_field_counts={},
        threshold_snapshot={},
        metrics_snapshot={},
        technical_metadata={},
        evidence_completed_at=FIXED_NOW,
        evaluated_at=FIXED_NOW,
    )
    db.add(assessment)
    db.flush()
    promotion_id = str(uuid4())
    event_id = str(uuid4())
    release_manifest = {
        "parser_name": DEFINITION.name,
        "parser_version": DEFINITION.version,
        "parser_implementation_hash": DEFINITION.implementation_hash,
        "output_schema_version": DEFINITION.output_schema_version,
        "suffix": suffix,
    }
    payload = _promotion_event_payload(
        event_id=event_id,
        promotion_id=promotion_id,
        occurred_at=FIXED_NOW,
    )
    event_hash = calculate_payload_hash(payload)
    promotion = CanonicalParserPromotion(
        promotion_id=promotion_id,
        promotion_key=calculate_payload_hash({"promotion": suffix}),
        assessment_db_id=assessment.id,
        assessment_id=assessment.assessment_id,
        scope="SHADOW_ONLY",
        status=status,
        parser_name=DEFINITION.name,
        parser_version=DEFINITION.version,
        parser_implementation_hash=DEFINITION.implementation_hash,
        output_schema_version=DEFINITION.output_schema_version,
        assessment_policy_hash=assessment.policy_hash,
        assessment_evidence_hash=assessment.evidence_hash,
        promotion_policy_version="canonical-parser-promotion/1",
        promotion_policy_hash=calculate_payload_hash({"promotion-policy": suffix}),
        release_manifest=release_manifest,
        release_manifest_hash=calculate_payload_hash(release_manifest),
        approved_at=FIXED_NOW,
        revoked_at=FIXED_NOW if status == "REVOKED" else None,
        revocation_reason="test" if status == "REVOKED" else None,
        latest_event_sequence=1,
        latest_event_hash=event_hash,
        technical_metadata={"runtime_activation": False},
    )
    db.add(promotion)
    db.flush()
    db.add(
        CanonicalParserPromotionEvent(
            event_id=event_id,
            promotion_db_id=promotion.id,
            sequence=1,
            event_type="APPROVED",
            previous_status=None,
            new_status="APPROVED",
            actor_label="LOCAL_OPERATOR",
            reason=None,
            event_payload=payload,
            previous_event_hash=None,
            event_hash=event_hash,
            occurred_at=FIXED_NOW,
        )
    )
    db.commit()
    db.refresh(promotion)
    return promotion


def _bind(db: Session, promotion: CanonicalParserPromotion):
    policy = _policy(binding_enabled=True)
    preview = preview_parser_runtime_binding(
        db,
        promotion_id=promotion.promotion_id,
        settings_object=policy,
    )
    return bind_parser_runtime(
        db,
        promotion_id=promotion.promotion_id,
        confirmation=preview["confirmation"],
        settings_object=policy,
        bound_at=FIXED_NOW,
    )


def _client(db_factory):
    def override_get_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_settings_default_runtime_binding_disabled():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_RUNTIME_BINDING_ENABLED is False


def test_models_exported_and_registered():
    assert models.CanonicalParserRuntimeBinding is CanonicalParserRuntimeBinding
    assert models.CanonicalParserRuntimeBindingEvent is CanonicalParserRuntimeBindingEvent
    assert "canonical_parser_runtime_bindings" in Base.metadata.tables
    assert "canonical_parser_runtime_binding_events" in Base.metadata.tables


def test_preview_is_dry_run_and_dynamic(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        preview = preview_parser_runtime_binding(db, promotion_id=promotion.promotion_id)
        assert db.query(CanonicalParserRuntimeBinding).count() == 0
    assert preview["eligible"] is True
    assert preview["writes_database"] is False
    assert preview["confirmation"].startswith(
        f"{BIND_CONFIRMATION_PREFIX}:{promotion.promotion_id}:{RUNTIME_CHANNEL}:"
    )


def test_preview_rejects_revoked_promotion(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db, status="REVOKED")
        preview = preview_parser_runtime_binding(db, promotion_id=promotion.promotion_id)
    assert preview["eligible"] is False
    assert "PROMOTION_NOT_APPROVED" in preview["blocker_codes"]


def test_preview_rejects_unsupported_scope_and_channel(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        with pytest.raises(CanonicalParserRuntimeBindingError):
            preview_parser_runtime_binding(db, promotion_id=promotion.promotion_id, scope="LIVE")
        with pytest.raises(CanonicalParserRuntimeBindingError):
            preview_parser_runtime_binding(db, promotion_id=promotion.promotion_id, channel="LIVE")


def test_bind_requires_feature_flag(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        with pytest.raises(CanonicalParserRuntimeBindingError) as captured:
            bind_parser_runtime(db, promotion_id=promotion.promotion_id, confirmation="x")
    assert captured.value.code == "CANONICAL_PARSER_RUNTIME_BINDING_DISABLED"


def test_bind_requires_exact_confirmation(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        with pytest.raises(CanonicalParserRuntimeBindingError) as captured:
            bind_parser_runtime(
                db,
                promotion_id=promotion.promotion_id,
                confirmation="wrong",
                settings_object=_policy(binding_enabled=True),
            )
    assert captured.value.code == "PARSER_RUNTIME_BINDING_CONFIRMATION_REQUIRED"


def test_bind_creates_binding_and_event(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        result = _bind(db, promotion)
        binding = db.query(CanonicalParserRuntimeBinding).one()
        event = db.query(CanonicalParserRuntimeBindingEvent).one()
    assert result["created"] is True
    assert binding.status == "ACTIVE"
    assert event.event_type == "BOUND"
    assert result["resolution_health"]["status"] == "HEALTHY"


def test_bind_is_idempotent(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        first = _bind(db, promotion)
        second = _bind(db, promotion)
        count = db.query(CanonicalParserRuntimeBinding).count()
    assert first["binding_id"] == second["binding_id"]
    assert second["created"] is False
    assert count == 1


def test_second_active_promotion_is_blocked(db_factory):
    with db_factory() as db:
        first = _insert_approved_promotion(db, suffix="first")
        _bind(db, first)
        first.status = "REVOKED"
        first.revoked_at = FIXED_NOW
        first.revocation_reason = "superseded"
        db.commit()
        second = _insert_approved_promotion(db, suffix="second")
        preview = preview_parser_runtime_binding(db, promotion_id=second.promotion_id)
    assert preview["eligible"] is False
    assert "ACTIVE_BINDING_EXISTS" in preview["blocker_codes"]


def test_resolve_without_binding_returns_unbound(db_factory):
    with db_factory() as db:
        result = resolve_shadow_parser_runtime(db)
    assert result["resolved"] is False
    assert result["status"] == "UNBOUND"
    assert result["runtime_consumer_enabled"] is False


def test_resolve_healthy_returns_metadata_only(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        _bind(db, promotion)
        result = resolve_shadow_parser_runtime(db)
    assert result["resolved"] is True
    assert result["status"] == "HEALTHY"
    assert result["parser"]["name"] == DEFINITION.name
    assert result["metadata_resolution_only"] is True


def test_revoked_promotion_causes_drift(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        _bind(db, promotion)
        promotion.status = "REVOKED"
        db.commit()
        result = resolve_shadow_parser_runtime(db)
    assert result["status"] == "DRIFTED"
    assert "PROMOTION_NOT_APPROVED" in result["reason_codes"]


def test_binding_identity_tamper_causes_drift(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        _bind(db, promotion)
        binding = db.query(CanonicalParserRuntimeBinding).one()
        binding.parser_implementation_hash = "f" * 64
        db.commit()
        result = resolve_shadow_parser_runtime(db)
    assert result["status"] == "DRIFTED"
    assert "BINDING_IMPLEMENTATION_HASH_DRIFT" in result["reason_codes"]


def test_binding_event_tamper_causes_drift(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        _bind(db, promotion)
        event = db.query(CanonicalParserRuntimeBindingEvent).one()
        event.event_hash = "e" * 64
        db.commit()
        result = resolve_shadow_parser_runtime(db)
    assert result["status"] == "DRIFTED"
    assert "BINDING_AUDIT_CHAIN_INVALID" in result["reason_codes"]


def test_unbind_requires_feature_flag(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        bound = _bind(db, promotion)
        with pytest.raises(CanonicalParserRuntimeBindingError) as captured:
            unbind_parser_runtime(
                db,
                binding_id=bound["binding_id"],
                confirmation=f"{UNBIND_CONFIRMATION_PREFIX}:{bound['binding_id']}",
                reason="stop",
            )
    assert captured.value.code == "CANONICAL_PARSER_RUNTIME_BINDING_DISABLED"


def test_unbind_requires_confirmation_and_reason(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        bound = _bind(db, promotion)
        policy = _policy(binding_enabled=True)
        with pytest.raises(CanonicalParserRuntimeBindingError):
            unbind_parser_runtime(
                db, binding_id=bound["binding_id"], confirmation="wrong",
                reason="stop", settings_object=policy,
            )
        with pytest.raises(CanonicalParserRuntimeBindingError):
            unbind_parser_runtime(
                db, binding_id=bound["binding_id"],
                confirmation=f"{UNBIND_CONFIRMATION_PREFIX}:{bound['binding_id']}",
                reason="", settings_object=policy,
            )


def test_unbind_appends_audit_event_and_resolver_unbound(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        bound = _bind(db, promotion)
        result = unbind_parser_runtime(
            db,
            binding_id=bound["binding_id"],
            confirmation=f"{UNBIND_CONFIRMATION_PREFIX}:{bound['binding_id']}",
            reason="manual rollback",
            settings_object=_policy(binding_enabled=True),
            unbound_at=FIXED_NOW,
        )
        resolution = resolve_shadow_parser_runtime(db)
        events = db.query(CanonicalParserRuntimeBindingEvent).order_by(
            CanonicalParserRuntimeBindingEvent.sequence
        ).all()
    assert result["status"] == "UNBOUND"
    assert [event.event_type for event in events] == ["BOUND", "UNBOUND"]
    assert resolution["status"] == "UNBOUND"


def test_unbind_is_idempotent(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        bound = _bind(db, promotion)
        policy = _policy(binding_enabled=True)
        confirmation = f"{UNBIND_CONFIRMATION_PREFIX}:{bound['binding_id']}"
        first = unbind_parser_runtime(
            db, binding_id=bound["binding_id"], confirmation=confirmation,
            reason="manual rollback", settings_object=policy,
        )
        second = unbind_parser_runtime(
            db, binding_id=bound["binding_id"], confirmation=confirmation,
            reason="manual rollback", settings_object=policy,
        )
    assert first["binding_id"] == second["binding_id"]
    assert second["created"] is False


def test_rebind_same_promotion_reuses_binding_with_new_event(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        bound = _bind(db, promotion)
        policy = _policy(binding_enabled=True)
        unbind_parser_runtime(
            db, binding_id=bound["binding_id"],
            confirmation=f"{UNBIND_CONFIRMATION_PREFIX}:{bound['binding_id']}",
            reason="cycle", settings_object=policy,
        )
        preview = preview_parser_runtime_binding(
            db, promotion_id=promotion.promotion_id, settings_object=policy
        )
        rebound = bind_parser_runtime(
            db, promotion_id=promotion.promotion_id,
            confirmation=preview["confirmation"], settings_object=policy,
        )
        events = db.query(CanonicalParserRuntimeBindingEvent).order_by(
            CanonicalParserRuntimeBindingEvent.sequence
        ).all()
    assert rebound["binding_id"] == bound["binding_id"]
    assert rebound["status"] == "ACTIVE"
    assert [event.event_type for event in events] == ["BOUND", "UNBOUND", "BOUND"]


def test_tampered_chain_blocks_unbind(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        bound = _bind(db, promotion)
        event = db.query(CanonicalParserRuntimeBindingEvent).one()
        event.event_hash = "a" * 64
        db.commit()
        with pytest.raises(CanonicalParserRuntimeBindingError) as captured:
            unbind_parser_runtime(
                db, binding_id=bound["binding_id"],
                confirmation=f"{UNBIND_CONFIRMATION_PREFIX}:{bound['binding_id']}",
                reason="stop", settings_object=_policy(binding_enabled=True),
            )
    assert captured.value.code == "PARSER_RUNTIME_BINDING_AUDIT_CHAIN_INVALID"


def test_get_binding_includes_events(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        bound = _bind(db, promotion)
        detail = get_parser_runtime_binding(db, bound["binding_id"])
    assert len(detail["events"]) == 1
    assert detail["events"][0]["event_type"] == "BOUND"


def test_status_reports_counts_and_no_runtime_consumer(db_factory):
    with db_factory() as db:
        empty = get_parser_runtime_status(db)
        promotion = _insert_approved_promotion(db)
        _bind(db, promotion)
        populated = get_parser_runtime_status(
            db, settings_object=_policy(binding_enabled=True)
        )
    assert empty["binding_count"] == 0
    assert populated["status_counts"]["ACTIVE"] == 1
    assert populated["operational_guards"]["runtime_consumer_enabled"] is False


def test_note_and_reason_are_sanitized(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        policy = _policy(binding_enabled=True)
        preview = preview_parser_runtime_binding(db, promotion_id=promotion.promotion_id)
        bound = bind_parser_runtime(
            db, promotion_id=promotion.promotion_id,
            confirmation=preview["confirmation"], note="api_key=SUPERSECRET",
            settings_object=policy,
        )
        detail = get_parser_runtime_binding(db, bound["binding_id"])
    serialized = str(detail)
    assert "SUPERSECRET" not in serialized
    assert "[REDACTED]" in serialized


def test_binding_never_writes_trade_or_uses_network(monkeypatch, db_factory):
    monkeypatch.setattr(
        socket, "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        before = db.query(Trade).count() if "trades" in inspect(db.bind).get_table_names() else 0
        _bind(db, promotion)
        after = db.query(Trade).count() if "trades" in inspect(db.bind).get_table_names() else 0
    assert before == after == 0


def test_m8_service_has_no_network_clients_or_trade_writes():
    path = Path("backend/app/services/blockchain_parser_runtime_binding_service.py")
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


def test_runtime_binding_service_not_imported_by_operational_pipelines():
    forbidden = []
    for path in Path("backend/app").rglob("*.py"):
        if path.name in {"main.py", "blockchain_parser_runtime_binding_service.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        if "blockchain_parser_runtime_binding_service" in source:
            forbidden.append(str(path))
    assert forbidden == []


def test_m8_api_routes_are_protected_and_registered_once(db_factory):
    counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            counts[(method, getattr(route, "path", ""))] += 1
    expected = {
        ("GET", "/integrity/parser-runtime/status"),
        ("GET", "/integrity/parser-runtime/preview"),
        ("POST", "/integrity/parser-runtime/bind"),
        ("POST", "/integrity/parser-runtime/unbind"),
        ("GET", "/integrity/parser-runtime/bindings/{binding_id}"),
        ("GET", "/integrity/parser-runtime/resolve"),
    }
    for route in expected:
        assert counts[route] == 1
    client = _client(db_factory)
    try:
        assert client.get("/integrity/parser-runtime/status").status_code == 401
        response = client.get(
            "/integrity/parser-runtime/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["binding_enabled"] is False
        post = client.post(
            "/integrity/parser-runtime/bind",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={"promotion_id": str(uuid4()), "confirmation": "anything"},
        )
        assert post.status_code == 409
        assert post.json()["detail"]["code"] == "CANONICAL_PARSER_RUNTIME_BINDING_DISABLED"
    finally:
        app.dependency_overrides.clear()


def test_active_binding_partial_unique_constraint(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        _bind(db, promotion)
        original = db.query(CanonicalParserRuntimeBinding).one()
        duplicate = CanonicalParserRuntimeBinding(
            binding_id=str(uuid4()), binding_key="f" * 64,
            promotion_db_id=promotion.id, promotion_id=promotion.promotion_id,
            scope=RUNTIME_SCOPE, channel=RUNTIME_CHANNEL, status="ACTIVE",
            parser_name=original.parser_name, parser_version="9.9.9",
            parser_implementation_hash="e" * 64,
            output_schema_version=original.output_schema_version,
            release_manifest_hash=original.release_manifest_hash,
            binding_policy_version=original.binding_policy_version,
            binding_policy_hash="d" * 64, bound_at=FIXED_NOW,
            latest_event_sequence=1, latest_event_hash="c" * 64,
            technical_metadata={},
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


def test_binding_event_sequence_unique_constraint(db_factory):
    with db_factory() as db:
        promotion = _insert_approved_promotion(db)
        _bind(db, promotion)
        binding = db.query(CanonicalParserRuntimeBinding).one()
        duplicate = CanonicalParserRuntimeBindingEvent(
            event_id=str(uuid4()), binding_db_id=binding.id, sequence=1,
            event_type="BOUND", previous_status=None, new_status="ACTIVE",
            actor_label="LOCAL_OPERATOR", reason=None,
            event_payload={"duplicate": True}, previous_event_hash=None,
            event_hash="b" * 64, occurred_at=FIXED_NOW,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


def test_m8_migration_upgrade_downgrade_upgrade_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CanonicalShadowValidationBatch.__table__,
            CanonicalQualityAssessment.__table__,
            CanonicalParserPromotion.__table__,
            CanonicalParserPromotionEvent.__table__,
        ],
    )
    path = Path("alembic/versions/a2d8f4c6b913_add_parser_runtime_binding.py")
    spec = importlib.util.spec_from_file_location("m8_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_runtime_bindings" in names
    assert "canonical_parser_runtime_binding_events" in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.downgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_runtime_bindings" not in names
    assert "canonical_parser_runtime_binding_events" not in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    assert "canonical_parser_runtime_bindings" in inspect(engine).get_table_names()
    engine.dispose()
