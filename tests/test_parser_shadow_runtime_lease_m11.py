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
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserRuntimeCertification,
    CanonicalParserRuntimeCertificationEvent,
    CanonicalParserShadowRuntimeLease,
    CanonicalParserShadowRuntimeLeaseEvent,
)
from backend.app.services.blockchain_parser_runtime_certification_service import (
    CERTIFICATION_REVOKE_PREFIX,
    certify_parser_runtime,
    preview_parser_runtime_certification,
    revoke_parser_runtime_certification,
)
from backend.app.services.blockchain_parser_shadow_runtime_lease_service import (
    LEASE_CONFIRMATION_PREFIX,
    LEASE_CONSUMER,
    LEASE_POLICY_VERSION,
    LEASE_REVOKE_PREFIX,
    CanonicalParserShadowRuntimeLeaseError,
    get_shadow_runtime_lease,
    get_shadow_runtime_lease_status,
    issue_shadow_runtime_lease,
    preview_shadow_runtime_lease,
    resolve_shadow_runtime_lease,
    revoke_shadow_runtime_lease,
)

AUTOMATION_KEY = "a" * 32
NOW = datetime(2026, 7, 25, 23, 0, tzinfo=timezone.utc)


def _load_m10_helpers():
    path = Path(__file__).with_name("test_parser_runtime_certification_m10.py")
    spec = importlib.util.spec_from_file_location("m10_test_helpers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


M10 = _load_m10_helpers()


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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_LEASE_MAX_VALIDITY_MINUTES", 60)
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_SHADOW_LEASE_MIN_CERTIFICATION_REMAINING_MINUTES",
        15,
    )


def _lease_policy(*, enabled: bool = False, max_validity: int = 60, min_remaining: int = 15):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_LEASE_ENABLED=enabled,
        CANONICAL_PARSER_SHADOW_LEASE_MAX_VALIDITY_MINUTES=max_validity,
        CANONICAL_PARSER_SHADOW_LEASE_MIN_CERTIFICATION_REMAINING_MINUTES=min_remaining,
    )


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test-helius-api-key",
    }
    values.update(overrides)
    return values


def _prepare_certification(db, *, certified_at: datetime = NOW):
    M10._prepare(db)
    cert_policy = M10._cert_policy(
        CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED=True,
        CANONICAL_PARSER_RUNTIME_CERTIFICATION_VALIDITY_HOURS=24,
    )
    preview = preview_parser_runtime_certification(
        db,
        settings_object=cert_policy,
        evaluated_at=certified_at,
    )
    certification = certify_parser_runtime(
        db,
        confirmation=preview["confirmation"],
        settings_object=cert_policy,
        certified_at=certified_at,
        actor_label="m11-test",
    )
    return certification, cert_policy


def _issue(db, *, issued_at: datetime = NOW + timedelta(hours=1), validity: int = 30):
    certification, cert_policy = _prepare_certification(db)
    lease_policy = _lease_policy(enabled=True)
    preview = preview_shadow_runtime_lease(
        db,
        certification_id=certification["certification_id"],
        validity_minutes=validity,
        settings_object=lease_policy,
        evaluated_at=issued_at,
    )
    lease = issue_shadow_runtime_lease(
        db,
        confirmation=preview["confirmation"],
        certification_id=certification["certification_id"],
        validity_minutes=validity,
        settings_object=lease_policy,
        issued_at=issued_at,
        actor_label="operator",
        note="manual certified shadow authorization",
    )
    return certification, cert_policy, lease_policy, lease


def _yield_db(factory):
    db = factory()
    try:
        yield db
    finally:
        db.close()


def test_settings_defaults_are_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_LEASE_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_LEASE_MAX_VALIDITY_MINUTES == 60
    assert configured.CANONICAL_PARSER_SHADOW_LEASE_MIN_CERTIFICATION_REMAINING_MINUTES == 15


def test_status_is_disabled_by_default(db_factory):
    with db_factory() as db:
        status = get_shadow_runtime_lease_status(db)
        assert status["lease_enabled"] is False
        assert status["policy_version"] == LEASE_POLICY_VERSION
        assert status["consumer"] == LEASE_CONSUMER
        assert status["operational_guards"]["consumer_connected"] is False


def test_preview_requires_certification(db_factory):
    with db_factory() as db:
        preview = preview_shadow_runtime_lease(db, settings_object=_lease_policy())
        assert preview["eligible"] is False
        assert "ACTIVE_CERTIFICATION_MISSING" in preview["blocker_codes"] or "CERTIFICATION_MISSING" in preview["blocker_codes"]


def test_preview_is_eligible_and_deterministic(db_factory):
    with db_factory() as db:
        certification, _ = _prepare_certification(db)
        policy = _lease_policy()
        first = preview_shadow_runtime_lease(
            db,
            certification_id=certification["certification_id"],
            validity_minutes=30,
            settings_object=policy,
            evaluated_at=NOW + timedelta(hours=1),
        )
        second = preview_shadow_runtime_lease(
            db,
            certification_id=certification["certification_id"],
            validity_minutes=30,
            settings_object=policy,
            evaluated_at=NOW + timedelta(hours=2),
        )
        assert first["eligible"] is True
        assert first["lease_key"] == second["lease_key"]
        assert first["confirmation"] == second["confirmation"]
        assert first["confirmation"].startswith(LEASE_CONFIRMATION_PREFIX)
        assert first["writes_trades"] is False
        assert first["external_requests"] == 0


def test_preview_rejects_excessive_validity(db_factory):
    with db_factory() as db:
        _prepare_certification(db)
        preview = preview_shadow_runtime_lease(
            db,
            validity_minutes=61,
            settings_object=_lease_policy(max_validity=60),
            evaluated_at=NOW,
        )
        assert "LEASE_VALIDITY_EXCEEDS_POLICY" in preview["blocker_codes"]


def test_preview_requires_remaining_certification_window(db_factory):
    with db_factory() as db:
        certification, _ = _prepare_certification(db)
        row = db.query(CanonicalParserRuntimeCertification).filter_by(
            certification_id=certification["certification_id"]
        ).one()
        row.expires_at = NOW + timedelta(minutes=40)
        db.commit()
        preview = preview_shadow_runtime_lease(
            db,
            validity_minutes=30,
            settings_object=_lease_policy(min_remaining=15),
            evaluated_at=NOW,
        )
        assert "CERTIFICATION_REMAINING_WINDOW_INSUFFICIENT" in preview["blocker_codes"]


def test_issue_is_disabled(db_factory):
    with db_factory() as db:
        certification, _ = _prepare_certification(db)
        preview = preview_shadow_runtime_lease(
            db,
            certification_id=certification["certification_id"],
            settings_object=_lease_policy(),
            evaluated_at=NOW,
        )
        with pytest.raises(CanonicalParserShadowRuntimeLeaseError) as exc:
            issue_shadow_runtime_lease(
                db,
                confirmation=preview["confirmation"],
                settings_object=_lease_policy(enabled=False),
                issued_at=NOW,
            )
        assert exc.value.code == "CANONICAL_PARSER_SHADOW_LEASE_DISABLED"


def test_issue_requires_current_confirmation(db_factory):
    with db_factory() as db:
        _prepare_certification(db)
        with pytest.raises(CanonicalParserShadowRuntimeLeaseError) as exc:
            issue_shadow_runtime_lease(
                db,
                confirmation="wrong",
                settings_object=_lease_policy(enabled=True),
                issued_at=NOW,
            )
        assert exc.value.code == "PARSER_SHADOW_LEASE_CONFIRMATION_REQUIRED"


def test_issue_persists_lease_and_audit_event(db_factory):
    with db_factory() as db:
        _, _, _, lease = _issue(db)
        assert lease["created"] is True
        assert lease["status"] == "ACTIVE"
        assert lease["consumer"] == LEASE_CONSUMER
        assert lease["requested_validity_minutes"] == 30
        assert db.query(CanonicalParserShadowRuntimeLease).count() == 1
        assert db.query(CanonicalParserShadowRuntimeLeaseEvent).count() == 1


def test_active_lease_blocks_second_issue(db_factory):
    with db_factory() as db:
        certification, _, policy, _ = _issue(db)
        preview = preview_shadow_runtime_lease(
            db,
            certification_id=certification["certification_id"],
            settings_object=policy,
            evaluated_at=NOW + timedelta(hours=1, minutes=5),
        )
        assert preview["eligible"] is False
        assert "ACTIVE_SHADOW_LEASE_EXISTS" in preview["blocker_codes"]


def test_resolver_ready_but_authorization_requires_flag(db_factory):
    with db_factory() as db:
        _, _, _, _ = _issue(db)
        disabled = resolve_shadow_runtime_lease(
            db,
            settings_object=_lease_policy(enabled=False),
            evaluated_at=NOW + timedelta(hours=1, minutes=5),
        )
        enabled = resolve_shadow_runtime_lease(
            db,
            settings_object=_lease_policy(enabled=True),
            evaluated_at=NOW + timedelta(hours=1, minutes=5),
        )
        assert disabled["status"] == "READY"
        assert disabled["consumer_authorized"] is False
        assert enabled["consumer_authorized"] is True
        assert enabled["consumer_connected"] is False
        assert enabled["runtime_activation"] is False


def test_resolver_returns_expired(db_factory):
    with db_factory() as db:
        _issue(db, validity=5)
        resolution = resolve_shadow_runtime_lease(
            db,
            settings_object=_lease_policy(enabled=True),
            evaluated_at=NOW + timedelta(hours=1, minutes=6),
        )
        assert resolution["resolved"] is False
        assert resolution["status"] == "EXPIRED"
        assert resolution["consumer_authorized"] is False


def test_expired_lease_is_closed_before_reissue(db_factory):
    with db_factory() as db:
        certification, _, policy, first = _issue(db, validity=5)
        issue_time = NOW + timedelta(hours=1, minutes=6)
        preview = preview_shadow_runtime_lease(
            db,
            certification_id=certification["certification_id"],
            validity_minutes=5,
            settings_object=policy,
            evaluated_at=issue_time,
        )
        second = issue_shadow_runtime_lease(
            db,
            confirmation=preview["confirmation"],
            certification_id=certification["certification_id"],
            validity_minutes=5,
            settings_object=policy,
            issued_at=issue_time,
        )
        first_row = db.query(CanonicalParserShadowRuntimeLease).filter_by(
            lease_id=first["lease_id"]
        ).one()
        assert first_row.status == "EXPIRED"
        assert second["lease_generation"] == 2
        assert first["lease_id"] in second["expired_lease_ids"]
        assert db.query(CanonicalParserShadowRuntimeLeaseEvent).count() == 3


def test_resolver_detects_certification_revocation(db_factory):
    with db_factory() as db:
        certification, cert_policy, _, _ = _issue(db)
        revoke_parser_runtime_certification(
            db,
            certification_id=certification["certification_id"],
            confirmation=f"{CERTIFICATION_REVOKE_PREFIX}:{certification['certification_id']}",
            reason="manual revoke",
            settings_object=cert_policy,
            revoked_at=NOW + timedelta(hours=1, minutes=2),
        )
        resolution = resolve_shadow_runtime_lease(
            db,
            settings_object=_lease_policy(enabled=True),
            evaluated_at=NOW + timedelta(hours=1, minutes=3),
        )
        assert resolution["status"] == "DRIFTED"
        assert resolution["consumer_authorized"] is False


def test_resolver_detects_certification_event_hash_drift(db_factory):
    with db_factory() as db:
        _issue(db)
        certification = db.query(CanonicalParserRuntimeCertification).one()
        certification.latest_event_hash = "f" * 64
        db.commit()
        resolution = resolve_shadow_runtime_lease(
            db,
            settings_object=_lease_policy(enabled=True),
            evaluated_at=NOW + timedelta(hours=1, minutes=2),
        )
        assert resolution["status"] == "DRIFTED"
        assert "CERTIFICATION_EVENT_HASH_DRIFT" in resolution["reason_codes"] or "CERTIFICATION_LATEST_HASH_INVALID" in resolution["reason_codes"]


def test_resolver_detects_lease_chain_tampering(db_factory):
    with db_factory() as db:
        _issue(db)
        event = db.query(CanonicalParserShadowRuntimeLeaseEvent).one()
        event.event_payload = {"tampered": True}
        db.commit()
        resolution = resolve_shadow_runtime_lease(
            db,
            settings_object=_lease_policy(enabled=True),
            evaluated_at=NOW + timedelta(hours=1, minutes=2),
        )
        assert resolution["status"] == "DRIFTED"
        assert "LEASE_EVENT_HASH_INVALID" in resolution["reason_codes"]


def test_resolver_detects_policy_snapshot_tampering(db_factory):
    with db_factory() as db:
        _issue(db)
        lease = db.query(CanonicalParserShadowRuntimeLease).one()
        lease.lease_policy_snapshot = {"tampered": True}
        db.commit()
        resolution = resolve_shadow_runtime_lease(
            db,
            settings_object=_lease_policy(enabled=True),
            evaluated_at=NOW + timedelta(hours=1, minutes=2),
        )
        assert "LEASE_POLICY_HASH_INVALID" in resolution["reason_codes"]


def test_revoke_requires_confirmation(db_factory):
    with db_factory() as db:
        _, _, policy, lease = _issue(db)
        with pytest.raises(CanonicalParserShadowRuntimeLeaseError) as exc:
            revoke_shadow_runtime_lease(
                db,
                lease_id=lease["lease_id"],
                confirmation="wrong",
                reason="manual revoke",
                settings_object=policy,
            )
        assert exc.value.code == "PARSER_SHADOW_LEASE_REVOKE_CONFIRMATION_REQUIRED"


def test_revoke_appends_audit_event(db_factory):
    with db_factory() as db:
        _, _, policy, lease = _issue(db)
        revoked = revoke_shadow_runtime_lease(
            db,
            lease_id=lease["lease_id"],
            confirmation=f"{LEASE_REVOKE_PREFIX}:{lease['lease_id']}",
            reason="operator stop",
            settings_object=policy,
            revoked_at=NOW + timedelta(hours=1, minutes=2),
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["latest_event_sequence"] == 2
        assert db.query(CanonicalParserShadowRuntimeLeaseEvent).count() == 2
        assert resolve_shadow_runtime_lease(db)["status"] == "UNLEASED"


def test_revoke_blocks_tampered_chain(db_factory):
    with db_factory() as db:
        _, _, policy, lease = _issue(db)
        event = db.query(CanonicalParserShadowRuntimeLeaseEvent).one()
        event.event_hash = "0" * 64
        db.commit()
        with pytest.raises(CanonicalParserShadowRuntimeLeaseError) as exc:
            revoke_shadow_runtime_lease(
                db,
                lease_id=lease["lease_id"],
                confirmation=f"{LEASE_REVOKE_PREFIX}:{lease['lease_id']}",
                reason="manual revoke",
                settings_object=policy,
            )
        assert exc.value.code == "PARSER_SHADOW_LEASE_AUDIT_CHAIN_INVALID"


def test_get_lease_includes_chain_status(db_factory):
    with db_factory() as db:
        _, _, _, lease = _issue(db)
        detail = get_shadow_runtime_lease(db, lease["lease_id"])
        assert detail["audit_chain_valid"] is True
        assert detail["revoke_confirmation"].endswith(lease["lease_id"])


def test_get_missing_lease_is_404(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowRuntimeLeaseError) as exc:
            get_shadow_runtime_lease(db, "00000000-0000-0000-0000-000000000000")
        assert exc.value.status_code == 404


def test_api_endpoints_are_protected_and_registered_once(db_factory):
    app.dependency_overrides[get_db] = lambda: (yield from _yield_db(db_factory))
    client = TestClient(app)
    try:
        assert client.get("/integrity/parser-shadow-lease/status").status_code in {401, 403}
        response = client.get(
            "/integrity/parser-shadow-lease/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
    expected = {
        ("GET", "/integrity/parser-shadow-lease/status"),
        ("GET", "/integrity/parser-shadow-lease/preview"),
        ("POST", "/integrity/parser-shadow-lease/issue"),
        ("POST", "/integrity/parser-shadow-lease/revoke"),
        ("GET", "/integrity/parser-shadow-lease/leases/{lease_id}"),
        ("GET", "/integrity/parser-shadow-lease/resolve"),
    }
    counts = {}
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            key = (method, getattr(route, "path", ""))
            counts[key] = counts.get(key, 0) + 1
    for key in expected:
        assert counts.get(key) == 1


def test_models_are_exported_and_registered():
    assert models.CanonicalParserShadowRuntimeLease is CanonicalParserShadowRuntimeLease
    assert models.CanonicalParserShadowRuntimeLeaseEvent is CanonicalParserShadowRuntimeLeaseEvent
    assert "canonical_parser_shadow_runtime_leases" in Base.metadata.tables
    assert "canonical_parser_shadow_runtime_lease_events" in Base.metadata.tables


def test_service_has_no_network_trade_writes_or_operational_consumers():
    path = Path("backend/app/services/blockchain_parser_shadow_runtime_lease_service.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports.intersection({"httpx", "requests", "aiohttp", "websockets", "urllib3"})
    source = path.read_text(encoding="utf-8")
    assert "db.add(Trade" not in source
    assert "execute_source_trade" not in source
    assert '"consumer_connected": False' in source
    consumers = []
    for candidate in Path("backend/app").rglob("*.py"):
        if candidate.name in {
            "main.py",
            path.name,
            "blockchain_parser_shadow_consumer_service.py",
            "blockchain_parser_shadow_readiness_service.py",
            "blockchain_parser_shadow_automation_permit_service.py",
        }:
            continue
        if "blockchain_parser_shadow_runtime_lease_service" in candidate.read_text(encoding="utf-8"):
            consumers.append(str(candidate))
    assert consumers == []


def test_migration_round_trip_sqlite():
    migration_path = Path("alembic/versions/d8c2f5a7e104_add_certified_shadow_runtime_lease.py")
    spec = importlib.util.spec_from_file_location("m11_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table in (
            "canonical_parser_shadow_runtime_lease_events",
            "canonical_parser_shadow_runtime_leases",
        ):
            Base.metadata.tables[table].drop(connection, checkfirst=True)
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original = migration.op
        migration.op = operations
        try:
            migration.upgrade()
            names = set(inspect(connection).get_table_names())
            assert "canonical_parser_shadow_runtime_leases" in names
            assert "canonical_parser_shadow_runtime_lease_events" in names
            migration.downgrade()
            names = set(inspect(connection).get_table_names())
            assert "canonical_parser_shadow_runtime_leases" not in names
            migration.upgrade()
        finally:
            migration.op = original
    engine.dispose()
