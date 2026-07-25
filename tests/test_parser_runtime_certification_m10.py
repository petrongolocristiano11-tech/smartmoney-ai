from __future__ import annotations

import ast
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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
    CanonicalParserRuntimeBinding,
    CanonicalParserRuntimeCertification,
    CanonicalParserRuntimeCertificationEvent,
)
from backend.app.services.blockchain_parser_runtime_admission_service import (
    preview_parser_runtime_admission,
    run_parser_runtime_admission,
)
from backend.app.services.blockchain_parser_runtime_certification_service import (
    CERTIFICATION_CONFIRMATION_PREFIX,
    CERTIFICATION_POLICY_VERSION,
    CERTIFICATION_REVOKE_PREFIX,
    CanonicalParserRuntimeCertificationError,
    certify_parser_runtime,
    get_parser_runtime_certification,
    get_parser_runtime_certification_status,
    preview_parser_runtime_certification,
    resolve_parser_runtime_certification,
    revoke_parser_runtime_certification,
)

AUTOMATION_KEY = "a" * 32
NOW = datetime(2026, 7, 25, 22, 0, tzinfo=timezone.utc)


def _load_m9_helpers():
    path = Path(__file__).with_name("test_parser_runtime_admission_m9.py")
    spec = importlib.util.spec_from_file_location("m9_test_helpers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


M9 = _load_m9_helpers()


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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_RUNS", 2)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_TOTAL_EVENTS", 10)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_PASS_RATE", 100.0)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MAX_FAILED_EVENTS", 0)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MAX_EVIDENCE_AGE_HOURS", 24)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_VALIDITY_HOURS", 24)


def _cert_policy(**overrides):
    values = {
        "CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED": False,
        "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_RUNS": 2,
        "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_TOTAL_EVENTS": 10,
        "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_PASS_RATE": 100.0,
        "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MAX_FAILED_EVENTS": 0,
        "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MAX_EVIDENCE_AGE_HOURS": 24,
        "CANONICAL_PARSER_RUNTIME_CERTIFICATION_VALIDITY_HOURS": 24,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _prepare(db: Session, *, run_count: int = 2, events_per_run: int = 5):
    binding = M9._insert_binding(db)
    admission_policy = M9._policy(enabled=True, max_sample=25)
    runs = []
    counter = 0
    for run_index in range(run_count):
        ids = []
        for event_index in range(events_per_run):
            counter += 1
            event = M9._insert_raw(db, f"m10-{run_index}-{event_index}-{counter}")
            ids.append(event.id)
        preview = preview_parser_runtime_admission(
            db,
            binding_id=binding["binding_id"],
            raw_event_ids=ids,
            limit=len(ids),
            settings_object=admission_policy,
        )
        run = run_parser_runtime_admission(
            db,
            confirmation=preview["confirmation"],
            binding_id=binding["binding_id"],
            raw_event_ids=ids,
            limit=len(ids),
            settings_object=admission_policy,
            started_at=NOW + timedelta(minutes=run_index),
        )
        runs.append(run)
    return binding, runs


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test-helius-api-key",
    }
    values.update(overrides)
    return values


def test_settings_defaults_are_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED is False
    assert configured.CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_RUNS == 2
    assert configured.CANONICAL_PARSER_RUNTIME_CERTIFICATION_VALIDITY_HOURS == 24


def test_status_is_disabled_by_default(db_factory):
    with db_factory() as db:
        status = get_parser_runtime_certification_status(db)
        assert status["certification_enabled"] is False
        assert status["policy_version"] == CERTIFICATION_POLICY_VERSION
        assert status["operational_guards"]["runtime_activation"] is False


def test_preview_requires_enough_runs(db_factory):
    with db_factory() as db:
        _prepare(db, run_count=1)
        preview = preview_parser_runtime_certification(db, settings_object=_cert_policy())
        assert preview["eligible"] is False
        assert "INSUFFICIENT_ADMISSION_RUNS" in preview["blocker_codes"]


def test_preview_requires_enough_events(db_factory):
    with db_factory() as db:
        _prepare(db, run_count=2, events_per_run=2)
        preview = preview_parser_runtime_certification(db, settings_object=_cert_policy())
        assert "INSUFFICIENT_ADMISSION_EVENTS" in preview["blocker_codes"]


def test_preview_is_eligible_and_deterministic(db_factory):
    with db_factory() as db:
        binding, _ = _prepare(db)
        policy = _cert_policy()
        first = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW + timedelta(hours=1))
        second = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW + timedelta(hours=2))
        assert first["eligible"] is True
        assert first["binding_id"] == binding["binding_id"]
        assert first["evidence_hash"] == second["evidence_hash"]
        assert first["confirmation"] == second["confirmation"]
        assert first["confirmation"].startswith(CERTIFICATION_CONFIRMATION_PREFIX)
        assert first["writes_trades"] is False
        assert first["external_requests"] == 0


def test_preview_detects_stale_evidence(db_factory):
    with db_factory() as db:
        _prepare(db)
        run = db.query(CanonicalParserAdmissionRun).first()
        run.completed_at = NOW - timedelta(days=3)
        db.commit()
        preview = preview_parser_runtime_certification(
            db,
            settings_object=_cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_MAX_EVIDENCE_AGE_HOURS=1),
            evaluated_at=NOW,
        )
        assert "ADMISSION_EVIDENCE_STALE" in preview["blocker_codes"]


def test_preview_detects_result_count_tampering(db_factory):
    with db_factory() as db:
        _prepare(db)
        result = db.query(CanonicalParserAdmissionResult).first()
        db.delete(result)
        db.commit()
        preview = preview_parser_runtime_certification(db, settings_object=_cert_policy())
        assert "ADMISSION_RESULT_COUNT_MISMATCH" in preview["blocker_codes"]


def test_preview_detects_output_hash_tampering(db_factory):
    with db_factory() as db:
        _prepare(db)
        result = db.query(CanonicalParserAdmissionResult).first()
        result.second_output_hash = "f" * 64
        db.commit()
        preview = preview_parser_runtime_certification(db, settings_object=_cert_policy())
        assert "ADMISSION_RESULT_HASH_MISMATCH" in preview["blocker_codes"]


def test_preview_detects_binding_drift(db_factory):
    with db_factory() as db:
        _prepare(db)
        binding = db.query(CanonicalParserRuntimeBinding).one()
        binding.latest_event_hash = "e" * 64
        db.commit()
        preview = preview_parser_runtime_certification(db, settings_object=_cert_policy())
        assert preview["eligible"] is False


def test_certify_is_disabled(db_factory):
    with db_factory() as db:
        _prepare(db)
        preview = preview_parser_runtime_certification(db, settings_object=_cert_policy())
        with pytest.raises(CanonicalParserRuntimeCertificationError) as exc:
            certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=_cert_policy())
        assert exc.value.code == "CANONICAL_PARSER_RUNTIME_CERTIFICATION_DISABLED"


def test_certify_requires_current_confirmation(db_factory):
    with db_factory() as db:
        _prepare(db)
        with pytest.raises(CanonicalParserRuntimeCertificationError) as exc:
            certify_parser_runtime(
                db,
                confirmation="wrong",
                settings_object=_cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True),
            )
        assert exc.value.code == "PARSER_RUNTIME_CERTIFICATION_CONFIRMATION_REQUIRED"


def test_certification_persists_evidence_and_event(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW + timedelta(hours=1))
        result = certify_parser_runtime(
            db,
            confirmation=preview["confirmation"],
            settings_object=policy,
            certified_at=NOW + timedelta(hours=1),
            actor_label="operator",
            note="manual evidence approval",
        )
        assert result["created"] is True
        assert result["status"] == "CERTIFIED"
        assert result["admission_run_count"] == 2
        assert result["total_passed_count"] == 10
        assert result["pass_rate"] == 100.0
        assert db.query(CanonicalParserRuntimeCertificationEvent).count() == 1


def test_certification_is_idempotent(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW)
        first = certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        second = certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        assert first["certification_id"] == second["certification_id"]
        assert second["created"] is False
        assert db.query(CanonicalParserRuntimeCertification).count() == 1


def test_resolver_returns_certified(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW)
        certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        resolution = resolve_parser_runtime_certification(db, evaluated_at=NOW + timedelta(hours=1))
        assert resolution["resolved"] is True
        assert resolution["status"] == "CERTIFIED"
        assert resolution["runtime_activation"] is False


def test_resolver_returns_expired(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True, CANONICAL_PARSER_RUNTIME_CERTIFICATION_VALIDITY_HOURS=1)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW)
        certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        resolution = resolve_parser_runtime_certification(db, evaluated_at=NOW + timedelta(hours=2))
        assert resolution["resolved"] is False
        assert resolution["status"] == "EXPIRED"


def test_resolver_detects_certification_chain_tampering(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW)
        certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        event = db.query(CanonicalParserRuntimeCertificationEvent).one()
        event.event_hash = "0" * 64
        db.commit()
        resolution = resolve_parser_runtime_certification(db, evaluated_at=NOW)
        assert resolution["status"] == "DRIFTED"


def test_revoke_requires_confirmation(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW)
        cert = certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        with pytest.raises(CanonicalParserRuntimeCertificationError) as exc:
            revoke_parser_runtime_certification(
                db,
                certification_id=cert["certification_id"],
                confirmation="wrong",
                reason="manual revoke",
                settings_object=policy,
            )
        assert exc.value.code == "PARSER_RUNTIME_CERTIFICATION_REVOKE_CONFIRMATION_REQUIRED"


def test_revoke_requires_reason(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW)
        cert = certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        with pytest.raises(CanonicalParserRuntimeCertificationError) as exc:
            revoke_parser_runtime_certification(
                db,
                certification_id=cert["certification_id"],
                confirmation=f"{CERTIFICATION_REVOKE_PREFIX}:{cert['certification_id']}",
                reason="  ",
                settings_object=policy,
            )
        assert exc.value.code == "PARSER_RUNTIME_CERTIFICATION_REVOKE_REASON_REQUIRED"


def test_revoke_appends_audit_event(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW)
        cert = certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        revoked = revoke_parser_runtime_certification(
            db,
            certification_id=cert["certification_id"],
            confirmation=f"{CERTIFICATION_REVOKE_PREFIX}:{cert['certification_id']}",
            reason="superseded evidence",
            settings_object=policy,
            revoked_at=NOW + timedelta(hours=1),
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["latest_event_sequence"] == 2
        assert db.query(CanonicalParserRuntimeCertificationEvent).count() == 2
        assert resolve_parser_runtime_certification(db, evaluated_at=NOW)["status"] == "UNCERTIFIED"


def test_revoke_blocks_tampered_chain(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW)
        cert = certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        event = db.query(CanonicalParserRuntimeCertificationEvent).one()
        event.event_payload = {"tampered": True}
        db.commit()
        with pytest.raises(CanonicalParserRuntimeCertificationError) as exc:
            revoke_parser_runtime_certification(
                db,
                certification_id=cert["certification_id"],
                confirmation=f"{CERTIFICATION_REVOKE_PREFIX}:{cert['certification_id']}",
                reason="manual revoke",
                settings_object=policy,
            )
        assert exc.value.code == "PARSER_RUNTIME_CERTIFICATION_AUDIT_CHAIN_INVALID"


def test_get_certification_includes_chain_status(db_factory):
    with db_factory() as db:
        _prepare(db)
        policy = _cert_policy(CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True)
        preview = preview_parser_runtime_certification(db, settings_object=policy, evaluated_at=NOW)
        cert = certify_parser_runtime(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
        detail = get_parser_runtime_certification(db, cert["certification_id"])
        assert detail["audit_chain_valid"] is True
        assert detail["revoke_confirmation"].endswith(cert["certification_id"])


def test_get_missing_certification_is_404(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserRuntimeCertificationError) as exc:
            get_parser_runtime_certification(db, "00000000-0000-0000-0000-000000000000")
        assert exc.value.status_code == 404


def test_api_endpoints_are_protected_and_registered_once(db_factory):
    factory = db_factory
    app.dependency_overrides[get_db] = lambda: (yield from _yield_db(factory))
    client = TestClient(app)
    try:
        assert client.get("/integrity/parser-certification/status").status_code in {401, 403}
        response = client.get(
            "/integrity/parser-certification/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
    expected = {
        ("GET", "/integrity/parser-certification/status"),
        ("GET", "/integrity/parser-certification/preview"),
        ("POST", "/integrity/parser-certification/certify"),
        ("POST", "/integrity/parser-certification/revoke"),
        ("GET", "/integrity/parser-certification/certifications/{certification_id}"),
        ("GET", "/integrity/parser-certification/resolve"),
    }
    counts = {}
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            key = (method, getattr(route, "path", ""))
            counts[key] = counts.get(key, 0) + 1
    for key in expected:
        assert counts.get(key) == 1


def _yield_db(factory):
    db = factory()
    try:
        yield db
    finally:
        db.close()


def test_models_are_exported_and_registered():
    assert models.CanonicalParserRuntimeCertification is CanonicalParserRuntimeCertification
    assert models.CanonicalParserRuntimeCertificationEvent is CanonicalParserRuntimeCertificationEvent
    assert "canonical_parser_runtime_certifications" in Base.metadata.tables
    assert "canonical_parser_runtime_certification_events" in Base.metadata.tables


def test_service_has_no_network_or_trade_writes():
    path = Path("backend/app/services/blockchain_parser_runtime_certification_service.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports.intersection({"httpx", "requests", "aiohttp", "websockets", "urllib3"})
    source = path.read_text(encoding="utf-8")
    assert "models.trade" not in source.lower()
    assert "Trade(" not in source


def test_migration_round_trip_sqlite():
    migration_path = Path("alembic/versions/c6f1e8a3d942_add_runtime_admission_certification.py")
    spec = importlib.util.spec_from_file_location("m10_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table in (
            "canonical_parser_runtime_certification_events",
            "canonical_parser_runtime_certifications",
        ):
            Base.metadata.tables[table].drop(connection, checkfirst=True)
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original = migration.op
        migration.op = operations
        try:
            migration.upgrade()
            names = set(inspect(connection).get_table_names())
            assert "canonical_parser_runtime_certifications" in names
            assert "canonical_parser_runtime_certification_events" in names
            migration.downgrade()
            names = set(inspect(connection).get_table_names())
            assert "canonical_parser_runtime_certifications" not in names
            migration.upgrade()
        finally:
            migration.op = original
    engine.dispose()
