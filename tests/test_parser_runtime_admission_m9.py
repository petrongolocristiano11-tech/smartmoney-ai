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
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserAdmissionResult,
    CanonicalParserAdmissionRun,
    CanonicalParserPromotion,
    CanonicalParserPromotionEvent,
    CanonicalParserRuntimeBinding,
    CanonicalParserRuntimeBindingEvent,
    CanonicalQualityAssessment,
    CanonicalShadowValidationBatch,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    register_raw_event,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    NormalizedArtifactPayload,
    ParserDefinition,
    ParserRegistry,
)
from backend.app.services.blockchain_parser_runtime_admission_service import (
    ADMISSION_CONFIRMATION_PREFIX,
    ADMISSION_POLICY_VERSION,
    CanonicalParserRuntimeAdmissionError,
    get_parser_runtime_admission_run,
    get_parser_runtime_admission_status,
    preview_parser_runtime_admission,
    run_parser_runtime_admission,
)
from backend.app.services.blockchain_parser_runtime_binding_service import (
    bind_parser_runtime,
    preview_parser_runtime_binding,
)

AUTOMATION_KEY = "a" * 32
WALLET = "AdmissionWallet11111111111111111111111111111"
TOKEN = "AdmissionToken111111111111111111111111111111"
NOW = datetime(2026, 7, 25, 22, 0, tzinfo=timezone.utc)
DEFINITION = DEFAULT_PARSER_REGISTRY.get("swap_canonical_event", "1.0.0")


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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_RUNTIME_ADMISSION_ENABLED", False)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_RUNTIME_ADMISSION_MAX_SAMPLE_SIZE", 25)
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


def _policy(*, enabled: bool = False, max_sample: int = 25):
    return SimpleNamespace(
        CANONICAL_PARSER_RUNTIME_ADMISSION_ENABLED=enabled,
        CANONICAL_PARSER_RUNTIME_ADMISSION_MAX_SAMPLE_SIZE=max_sample,
    )


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test-helius-api-key",
    }
    values.update(overrides)
    return values


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
                "tokenOutputs": [{
                    "userAccount": WALLET,
                    "mint": TOKEN,
                    "rawTokenAmount": {"tokenAmount": "250000000", "decimals": 6},
                }],
            }
        },
    }


def _insert_raw(db: Session, signature: str, *, compatible: bool = True):
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


def _insert_binding(db: Session):
    validation_id = str(uuid4())
    batch = CanonicalShadowValidationBatch(
        validation_id=validation_id,
        comparator_version="canonical-trade-shadow/1",
        status="COMPLETED",
        request_filters={}, requested_limit=10, selected_count=10,
        processed_count=10, match_count=10, mismatch_count=0,
        missing_trade_count=0, not_comparable_count=0, failed_count=0,
        started_at=NOW, completed_at=NOW, technical_metadata={},
    )
    db.add(batch); db.flush()
    assessment = CanonicalQualityAssessment(
        assessment_id=str(uuid4()), assessment_key=calculate_payload_hash({"a": 1}),
        validation_batch_id=batch.id, validation_id=validation_id,
        policy_version="canonical-quality-gate/1",
        policy_hash=calculate_payload_hash({"p": 1}),
        evidence_hash=calculate_payload_hash({"e": 1}), status="READY",
        parser_name=DEFINITION.name, parser_version=DEFINITION.version,
        parser_implementation_hash=DEFINITION.implementation_hash,
        comparator_version="canonical-trade-shadow/1", sample_size=10,
        comparable_count=10, match_count=10, mismatch_count=0,
        missing_trade_count=0, not_comparable_count=0, failed_count=0,
        quality_pass_count=10, quality_warn_count=0, quality_fail_count=0,
        match_rate=100, mismatch_rate=0, missing_trade_rate=0,
        not_comparable_rate=0, failed_rate=0, quality_pass_rate=100,
        reason_codes=[], mismatch_field_counts={}, threshold_snapshot={},
        metrics_snapshot={}, technical_metadata={}, evidence_completed_at=NOW,
        evaluated_at=NOW,
    )
    db.add(assessment); db.flush()
    promotion_id = str(uuid4())
    promotion_event_id = str(uuid4())
    release = {
        "parser_name": DEFINITION.name,
        "parser_version": DEFINITION.version,
        "parser_implementation_hash": DEFINITION.implementation_hash,
        "output_schema_version": DEFINITION.output_schema_version,
    }
    promotion_payload = {
        "event_id": promotion_event_id, "promotion_id": promotion_id,
        "sequence": 1, "event_type": "APPROVED", "previous_status": None,
        "new_status": "APPROVED", "actor_label": "LOCAL_OPERATOR",
        "reason": None, "previous_event_hash": None,
        "occurred_at": NOW.isoformat(),
    }
    promotion_hash = calculate_payload_hash(promotion_payload)
    promotion = CanonicalParserPromotion(
        promotion_id=promotion_id,
        promotion_key=calculate_payload_hash({"promotion": promotion_id}),
        assessment_db_id=assessment.id, assessment_id=assessment.assessment_id,
        scope="SHADOW_ONLY", status="APPROVED",
        parser_name=DEFINITION.name, parser_version=DEFINITION.version,
        parser_implementation_hash=DEFINITION.implementation_hash,
        output_schema_version=DEFINITION.output_schema_version,
        assessment_policy_hash=assessment.policy_hash,
        assessment_evidence_hash=assessment.evidence_hash,
        promotion_policy_version="canonical-parser-promotion/1",
        promotion_policy_hash=calculate_payload_hash({"pp": 1}),
        release_manifest=release, release_manifest_hash=calculate_payload_hash(release),
        approved_at=NOW, revoked_at=None, revocation_reason=None,
        latest_event_sequence=1, latest_event_hash=promotion_hash,
        technical_metadata={"runtime_activation": False},
    )
    db.add(promotion); db.flush()
    db.add(CanonicalParserPromotionEvent(
        event_id=promotion_event_id, promotion_db_id=promotion.id, sequence=1,
        event_type="APPROVED", previous_status=None, new_status="APPROVED",
        actor_label="LOCAL_OPERATOR", reason=None, event_payload=promotion_payload,
        previous_event_hash=None, event_hash=promotion_hash, occurred_at=NOW,
    ))
    db.commit()
    binding_policy = SimpleNamespace(CANONICAL_PARSER_RUNTIME_BINDING_ENABLED=True)
    preview = preview_parser_runtime_binding(
        db, promotion_id=promotion.promotion_id, settings_object=binding_policy
    )
    return bind_parser_runtime(
        db, promotion_id=promotion.promotion_id,
        confirmation=preview["confirmation"], settings_object=binding_policy,
        bound_at=NOW,
    )


def _replace_bound_definition(db: Session, definition):
    binding = db.query(CanonicalParserRuntimeBinding).one()
    promotion = db.query(CanonicalParserPromotion).one()
    release = {
        "parser_name": definition.name,
        "parser_version": definition.version,
        "parser_implementation_hash": definition.implementation_hash,
        "output_schema_version": definition.output_schema_version,
    }
    promotion.parser_name = definition.name
    promotion.parser_version = definition.version
    promotion.parser_implementation_hash = definition.implementation_hash
    promotion.output_schema_version = definition.output_schema_version
    promotion.release_manifest = release
    promotion.release_manifest_hash = calculate_payload_hash(release)
    binding.parser_name = definition.name
    binding.parser_version = definition.version
    binding.parser_implementation_hash = definition.implementation_hash
    binding.output_schema_version = definition.output_schema_version
    binding.release_manifest_hash = promotion.release_manifest_hash
    db.commit()


def _client(db_factory):
    def override_get_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_settings_defaults_disabled_and_bounded():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_RUNTIME_ADMISSION_ENABLED is False
    assert configured.CANONICAL_PARSER_RUNTIME_ADMISSION_MAX_SAMPLE_SIZE == 25


def test_models_exported_and_registered():
    assert models.CanonicalParserAdmissionRun is CanonicalParserAdmissionRun
    assert models.CanonicalParserAdmissionResult is CanonicalParserAdmissionResult
    assert "canonical_parser_admission_runs" in Base.metadata.tables
    assert "canonical_parser_admission_results" in Base.metadata.tables


def test_preview_unbound_is_blocked(db_factory):
    with db_factory() as db:
        preview = preview_parser_runtime_admission(db)
    assert preview["eligible"] is False
    assert "NO_ACTIVE_BINDING" in preview["blocker_codes"]


def test_preview_selects_compatible_events_and_dynamic_confirmation(db_factory):
    with db_factory() as db:
        binding = _insert_binding(db)
        event = _insert_raw(db, "sig-preview")
        db.commit()
        preview = preview_parser_runtime_admission(db, binding_id=binding["binding_id"])
    assert preview["eligible"] is True
    assert preview["selected_raw_event_ids"] == [event.id]
    assert preview["confirmation"].startswith(ADMISSION_CONFIRMATION_PREFIX)


def test_preview_rejects_missing_and_incompatible_explicit_events(db_factory):
    with db_factory() as db:
        _insert_binding(db)
        event = _insert_raw(db, "sig-bad", compatible=False)
        db.commit()
        preview = preview_parser_runtime_admission(
            db, raw_event_ids=[event.id, 999999]
        )
    assert "RAW_EVENTS_INCOMPATIBLE" in preview["blocker_codes"]
    assert "RAW_EVENTS_NOT_FOUND" in preview["blocker_codes"]


def test_limit_is_bounded(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserRuntimeAdmissionError) as captured:
            preview_parser_runtime_admission(db, limit=26, settings_object=_policy(max_sample=25))
    assert captured.value.code == "PARSER_ADMISSION_LIMIT_INVALID"


def test_run_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserRuntimeAdmissionError) as captured:
            run_parser_runtime_admission(db, confirmation="anything")
    assert captured.value.code == "CANONICAL_PARSER_RUNTIME_ADMISSION_DISABLED"


def test_confirmation_is_required(db_factory):
    with db_factory() as db:
        _insert_binding(db); _insert_raw(db, "sig-confirm"); db.commit()
        with pytest.raises(CanonicalParserRuntimeAdmissionError) as captured:
            run_parser_runtime_admission(
                db, confirmation="wrong", settings_object=_policy(enabled=True)
            )
    assert captured.value.code == "PARSER_ADMISSION_CONFIRMATION_REQUIRED"


def test_successful_run_persists_deterministic_results(db_factory):
    with db_factory() as db:
        binding = _insert_binding(db)
        event = _insert_raw(db, "sig-pass"); db.commit()
        policy = _policy(enabled=True)
        preview = preview_parser_runtime_admission(
            db, binding_id=binding["binding_id"], raw_event_ids=[event.id],
            settings_object=policy,
        )
        result = run_parser_runtime_admission(
            db, confirmation=preview["confirmation"], binding_id=binding["binding_id"],
            raw_event_ids=[event.id], settings_object=policy, started_at=NOW,
        )
    assert result["status"] == "PASSED"
    assert result["passed_count"] == 1
    assert result["results"][0]["deterministic"] is True
    assert result["results"][0]["artifact_count"] == 1


def test_run_is_idempotent_for_same_binding_and_selection(db_factory):
    with db_factory() as db:
        _insert_binding(db); event = _insert_raw(db, "sig-idempotent"); db.commit()
        policy = _policy(enabled=True)
        preview = preview_parser_runtime_admission(db, raw_event_ids=[event.id], settings_object=policy)
        first = run_parser_runtime_admission(db, confirmation=preview["confirmation"], raw_event_ids=[event.id], settings_object=policy)
        second = run_parser_runtime_admission(db, confirmation=preview["confirmation"], raw_event_ids=[event.id], settings_object=policy)
    assert first["admission_id"] == second["admission_id"]
    assert second["created"] is False


def test_empty_output_fails(db_factory):
    registry = ParserRegistry()
    registry.register(ParserDefinition(
        name="empty_canary", version="1.0.0", description="empty",
        supported_providers=frozenset({"helius"}),
        supported_event_types=frozenset({"WALLET_HISTORY_RESPONSE"}),
        output_schema_version="empty/1", parse=lambda event: [],
    ))
    with db_factory() as db:
        binding = _insert_binding(db)
        definition = registry.get("empty_canary", "1.0.0")
        _replace_bound_definition(db, definition)
        event = _insert_raw(db, "sig-empty"); db.commit()
        policy = _policy(enabled=True)
        preview = preview_parser_runtime_admission(db, raw_event_ids=[event.id], settings_object=policy, registry=registry)
        result = run_parser_runtime_admission(db, confirmation=preview["confirmation"], raw_event_ids=[event.id], settings_object=policy, registry=registry)
    assert result["status"] == "FAILED"
    assert "EMPTY_PARSER_OUTPUT" in result["results"][0]["reason_codes"]


def test_nondeterministic_output_is_blocked_at_preview(db_factory):
    registry = ParserRegistry()
    counter = {"n": 0}
    def parse(event):
        counter["n"] += 1
        return [NormalizedArtifactPayload("TEST_EVENT", "test/1", {"n": counter["n"]})]
    registry.register(ParserDefinition(
        name="nondeterministic_canary", version="1.0.0", description="bad",
        supported_providers=frozenset({"helius"}),
        supported_event_types=frozenset({"WALLET_HISTORY_RESPONSE"}),
        output_schema_version="test/1", parse=parse, deterministic=False,
    ))
    with db_factory() as db:
        _insert_binding(db)
        definition = registry.get("nondeterministic_canary", "1.0.0")
        _replace_bound_definition(db, definition)
        _insert_raw(db, "sig-non-det"); db.commit()
        preview = preview_parser_runtime_admission(db, registry=registry)
    assert "PARSER_NOT_DETERMINISTIC" in preview["blocker_codes"]


def test_parser_exception_is_sanitized(db_factory):
    registry = ParserRegistry()
    def parse(event):
        raise RuntimeError("api_key=SUPERSECRET")
    registry.register(ParserDefinition(
        name="failing_canary", version="1.0.0", description="fail",
        supported_providers=frozenset({"helius"}),
        supported_event_types=frozenset({"WALLET_HISTORY_RESPONSE"}),
        output_schema_version="fail/1", parse=parse,
    ))
    with db_factory() as db:
        _insert_binding(db)
        definition = registry.get("failing_canary", "1.0.0")
        _replace_bound_definition(db, definition)
        event=_insert_raw(db,"sig-error"); db.commit()
        policy=_policy(enabled=True)
        preview=preview_parser_runtime_admission(db,raw_event_ids=[event.id],settings_object=policy,registry=registry)
        result=run_parser_runtime_admission(db,confirmation=preview["confirmation"],raw_event_ids=[event.id],settings_object=policy,registry=registry)
    serialized=str(result)
    assert "SUPERSECRET" not in serialized
    assert "[REDACTED]" in serialized


def test_status_and_read_run(db_factory):
    with db_factory() as db:
        _insert_binding(db); event=_insert_raw(db,"sig-status"); db.commit()
        policy=_policy(enabled=True)
        preview=preview_parser_runtime_admission(db,raw_event_ids=[event.id],settings_object=policy)
        created=run_parser_runtime_admission(db,confirmation=preview["confirmation"],raw_event_ids=[event.id],settings_object=policy)
        status=get_parser_runtime_admission_status(db,settings_object=policy)
        detail=get_parser_runtime_admission_run(db,created["admission_id"])
    assert status["status_counts"]["PASSED"] == 1
    assert detail["admission_id"] == created["admission_id"]


def test_missing_run_returns_404(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserRuntimeAdmissionError) as captured:
            get_parser_runtime_admission_run(db, str(uuid4()))
    assert captured.value.status_code == 404


def test_no_network_or_trade_writes(monkeypatch, db_factory):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    with db_factory() as db:
        _insert_binding(db); event=_insert_raw(db,"sig-safe"); db.commit()
        policy=_policy(enabled=True)
        preview=preview_parser_runtime_admission(db,raw_event_ids=[event.id],settings_object=policy)
        result=run_parser_runtime_admission(db,confirmation=preview["confirmation"],raw_event_ids=[event.id],settings_object=policy)
    assert result["technical_metadata"]["writes_trades"] is False
    assert result["technical_metadata"]["external_requests"] == 0


def test_service_has_no_network_clients_or_trade_writes():
    path=Path("backend/app/services/blockchain_parser_runtime_admission_service.py")
    tree=ast.parse(path.read_text(encoding="utf-8"))
    imports=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import): imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node,ast.ImportFrom) and node.module: imports.add(node.module.split(".")[0])
    assert not imports & {"httpx","requests","aiohttp","urllib3","websockets"}
    source=path.read_text(encoding="utf-8")
    assert "db.add(Trade" not in source
    assert "RUN_LIVE" not in source


def test_admission_service_not_imported_by_operational_pipelines():
    consumers=[]
    for path in Path("backend/app").rglob("*.py"):
        if path.name in {"main.py","blockchain_parser_runtime_admission_service.py"}:
            continue
        if "blockchain_parser_runtime_admission_service" in path.read_text(encoding="utf-8"):
            consumers.append(str(path))
    assert consumers == []


def test_api_routes_protected_and_registered_once(db_factory):
    counts=Counter()
    for route in app.routes:
        for method in getattr(route,"methods",set()) or set():
            counts[(method,getattr(route,"path",""))]+=1
    expected={
        ("GET","/integrity/parser-admission/status"),
        ("GET","/integrity/parser-admission/preview"),
        ("POST","/integrity/parser-admission/run"),
        ("GET","/integrity/parser-admission/runs/{admission_id}"),
    }
    assert all(counts[item]==1 for item in expected)
    client=_client(db_factory)
    try:
        assert client.get("/integrity/parser-admission/status").status_code==401
        response=client.get("/integrity/parser-admission/status",headers={"X-Automation-Key":AUTOMATION_KEY})
        assert response.status_code==200
        assert response.json()["admission_enabled"] is False
    finally:
        app.dependency_overrides.clear()


def test_migration_upgrade_downgrade_upgrade_round_trip():
    engine=create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        CanonicalShadowValidationBatch.__table__, CanonicalQualityAssessment.__table__,
        CanonicalParserPromotion.__table__, CanonicalParserPromotionEvent.__table__,
        CanonicalParserRuntimeBinding.__table__, CanonicalParserRuntimeBindingEvent.__table__,
        models.RawBlockchainEvent.__table__,
    ])
    path=Path("alembic/versions/b4e6a9d1c027_add_parser_runtime_admission_canary.py")
    spec=importlib.util.spec_from_file_location("m9_migration",path); assert spec and spec.loader
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with engine.begin() as connection:
        module.op=Operations(MigrationContext.configure(connection)); module.upgrade()
    names=set(inspect(engine).get_table_names())
    assert "canonical_parser_admission_runs" in names
    assert "canonical_parser_admission_results" in names
    with engine.begin() as connection:
        module.op=Operations(MigrationContext.configure(connection)); module.downgrade()
    names=set(inspect(engine).get_table_names())
    assert "canonical_parser_admission_runs" not in names
    with engine.begin() as connection:
        module.op=Operations(MigrationContext.configure(connection)); module.upgrade()
    assert "canonical_parser_admission_runs" in inspect(engine).get_table_names()
    engine.dispose()


def test_policy_version_and_confirmation_prefix_are_stable():
    assert ADMISSION_POLICY_VERSION == "canonical-parser-runtime-admission/1"
    assert ADMISSION_CONFIRMATION_PREFIX == "RUN_PARSER_RUNTIME_ADMISSION"


def test_runtime_drift_after_execution_fails_run(monkeypatch, db_factory):
    import backend.app.services.blockchain_parser_runtime_admission_service as module

    with db_factory() as db:
        _insert_binding(db); event = _insert_raw(db, "sig-drift"); db.commit()
        policy = _policy(enabled=True)
        preview = preview_parser_runtime_admission(
            db, raw_event_ids=[event.id], settings_object=policy
        )
        real_resolve = module.resolve_shadow_parser_runtime
        calls = {"count": 0}

        def resolve_with_drift(*args, **kwargs):
            calls["count"] += 1
            result = real_resolve(*args, **kwargs)
            if calls["count"] >= 2:
                result = dict(result)
                result["resolved"] = False
                result["status"] = "DRIFTED"
                result["reason_codes"] = ["TEST_DRIFT"]
            return result

        monkeypatch.setattr(module, "resolve_shadow_parser_runtime", resolve_with_drift)
        result = run_parser_runtime_admission(
            db,
            confirmation=preview["confirmation"],
            raw_event_ids=[event.id],
            settings_object=policy,
        )
    assert result["status"] == "FAILED"
    assert "RUNTIME_BINDING_DRIFT_DETECTED" in result["reason_codes"]


def test_mixed_parser_results_produce_partial(db_factory):
    registry = ParserRegistry()

    def parse(event):
        if event.transaction_signature == "sig-fail-one":
            raise RuntimeError("controlled")
        return [NormalizedArtifactPayload("TEST_EVENT", "test/1", {"ok": True})]

    registry.register(ParserDefinition(
        name="mixed_canary", version="1.0.0", description="mixed",
        supported_providers=frozenset({"helius"}),
        supported_event_types=frozenset({"WALLET_HISTORY_RESPONSE"}),
        output_schema_version="test/1", parse=parse,
    ))
    with db_factory() as db:
        _insert_binding(db)
        definition = registry.get("mixed_canary", "1.0.0")
        _replace_bound_definition(db, definition)
        one = _insert_raw(db, "sig-pass-one")
        two = _insert_raw(db, "sig-fail-one")
        db.commit()
        policy = _policy(enabled=True)
        preview = preview_parser_runtime_admission(
            db, raw_event_ids=[one.id, two.id], settings_object=policy, registry=registry
        )
        result = run_parser_runtime_admission(
            db, confirmation=preview["confirmation"],
            raw_event_ids=[one.id, two.id], settings_object=policy, registry=registry,
        )
    assert result["status"] == "PARTIAL"
    assert result["passed_count"] == 1
    assert result["failed_count"] == 1


def test_actor_and_note_are_sanitized(db_factory):
    with db_factory() as db:
        _insert_binding(db); event = _insert_raw(db, "sig-note"); db.commit()
        policy = _policy(enabled=True)
        preview = preview_parser_runtime_admission(
            db, raw_event_ids=[event.id], settings_object=policy
        )
        result = run_parser_runtime_admission(
            db, confirmation=preview["confirmation"], raw_event_ids=[event.id],
            settings_object=policy, actor_label="api_key=ACTORSECRET",
            note="Bearer NOTESECRET",
        )
    serialized = str(result)
    assert "ACTORSECRET" not in serialized
    assert "NOTESECRET" not in serialized
    assert "[REDACTED]" in serialized


def test_admission_key_unique_constraint(db_factory):
    from sqlalchemy.exc import IntegrityError

    with db_factory() as db:
        _insert_binding(db); event = _insert_raw(db, "sig-unique"); db.commit()
        policy = _policy(enabled=True)
        preview = preview_parser_runtime_admission(
            db, raw_event_ids=[event.id], settings_object=policy
        )
        run_parser_runtime_admission(
            db, confirmation=preview["confirmation"], raw_event_ids=[event.id],
            settings_object=policy,
        )
        original = db.query(CanonicalParserAdmissionRun).one()
        duplicate = CanonicalParserAdmissionRun(
            admission_id=str(uuid4()), admission_key=original.admission_key,
            binding_db_id=original.binding_db_id, binding_id=original.binding_id,
            promotion_id=original.promotion_id, scope=original.scope,
            channel=original.channel, status="PASSED",
            parser_name=original.parser_name, parser_version=original.parser_version,
            parser_implementation_hash=original.parser_implementation_hash,
            output_schema_version=original.output_schema_version,
            binding_event_hash=original.binding_event_hash,
            release_manifest_hash=original.release_manifest_hash,
            admission_policy_version=original.admission_policy_version,
            admission_policy_hash=original.admission_policy_hash,
            requested_limit=1, selected_count=0, processed_count=0,
            passed_count=0, failed_count=0, skipped_count=0,
            actor_label="LOCAL_OPERATOR", note=None, reason_codes=[],
            selection_snapshot={}, metrics_snapshot={}, technical_metadata={},
            started_at=NOW, completed_at=NOW,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


def test_result_run_event_unique_constraint(db_factory):
    from sqlalchemy.exc import IntegrityError

    with db_factory() as db:
        _insert_binding(db); event = _insert_raw(db, "sig-result-unique"); db.commit()
        policy = _policy(enabled=True)
        preview = preview_parser_runtime_admission(
            db, raw_event_ids=[event.id], settings_object=policy
        )
        run_parser_runtime_admission(
            db, confirmation=preview["confirmation"], raw_event_ids=[event.id],
            settings_object=policy,
        )
        original = db.query(CanonicalParserAdmissionResult).one()
        db.add(CanonicalParserAdmissionResult(
            result_id=str(uuid4()), admission_run_db_id=original.admission_run_db_id,
            raw_event_id=original.raw_event_id, status="PASS", compatible=True,
            deterministic=True, first_output_hash="a" * 64,
            second_output_hash="a" * 64, artifact_count=1,
            artifact_summary=[], reason_codes=[], error_message=None,
            started_at=NOW, completed_at=NOW,
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_api_run_is_disabled_by_default(db_factory):
    client = _client(db_factory)
    try:
        response = client.post(
            "/integrity/parser-admission/run",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={"confirmation": "anything"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "CANONICAL_PARSER_RUNTIME_ADMISSION_DISABLED"
    finally:
        app.dependency_overrides.clear()
