from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserLiveObservabilitySnapshot,
    CanonicalParserPreproductionCertification,
    CanonicalParserPreproductionCertificationCheck,
    CanonicalParserPreproductionCertificationEvent,
    CanonicalParserPreproductionReleaseApproval,
    CanonicalParserPreproductionReleaseApprovalEvent,
)
import backend.app.services.blockchain_parser_preproduction_certification_service as service

NOW = datetime(2026, 7, 29, 14, 30, tzinfo=timezone.utc)
WALLET = "1" * 32
TOKEN = "2" * 32
COMMIT = "a" * 40
TEST_HASH = "b" * 64


def settings_for_m44(**overrides):
    values = {
        "CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_ENABLED": True,
        "CANONICAL_PARSER_PREPRODUCTION_RELEASE_GUARD_ENABLED": True,
        "CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_TTL_MINUTES": 30,
        "CANONICAL_PARSER_PREPRODUCTION_MAX_RELEASE_VALIDITY_MINUTES": 10,
        "CANONICAL_PARSER_PREPRODUCTION_MIN_FULL_TEST_COUNT": 1137,
        "CANONICAL_PARSER_PREPRODUCTION_REQUIRED_FASTAPI_VERSION": "0.138.2",
        "CANONICAL_PARSER_PREPRODUCTION_REQUIRE_HEALTHY_OBSERVABILITY": True,
        "CANONICAL_PARSER_PREPRODUCTION_REQUIRE_ZERO_OPEN_CRITICAL_ALERTS": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture()
def db(monkeypatch) -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(service, "_runtime_fastapi_version", lambda: "0.138.2")
    monkeypatch.setattr(service, "_script_head", lambda: service.EXPECTED_ALEMBIC_HEAD)
    monkeypatch.setattr(service, "_database_head", lambda db: service.EXPECTED_ALEMBIC_HEAD)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def add_healthy_snapshot(db: Session) -> CanonicalParserLiveObservabilitySnapshot:
    row = CanonicalParserLiveObservabilitySnapshot(
        snapshot_id="snapshot-0000000000000000000000001"[:36],
        snapshot_key="c" * 64,
        scope="M43_LIVE_OPERATIONAL_OBSERVABILITY",
        status="HEALTHY",
        uncertain_submission_count=0,
        stale_submission_count=0,
        unsettled_count=0,
        review_position_count=0,
        active_incident_count=0,
        open_alert_count=0,
        reason_codes=[],
        metric_snapshot={"counts": {}},
        policy_snapshot={},
        evidence_hash="d" * 64,
        actor_label="TEST",
        note=None,
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    db.add(row)
    db.commit()
    return row


def certification_preview(db: Session, snapshot_id: str, **overrides):
    args = {
        "observability_snapshot_id": snapshot_id,
        "git_commit_sha": COMMIT,
        "clean_worktree_attested": True,
        "full_test_count": 1137,
        "full_test_failures": 0,
        "test_evidence_hash": TEST_HASH,
        "idempotency_token": "m44-certification-001",
        "settings_object": settings_for_m44(),
        "evaluated_at": NOW,
    }
    args.update(overrides)
    return service.preview_preproduction_certification(db, **args), args


def certify(db: Session, snapshot_id: str):
    preview, args = certification_preview(db, snapshot_id)
    persisted = service.certify_preproduction_readiness(
        db,
        **{k: v for k, v in args.items() if k != "evaluated_at"},
        confirmation=preview["confirmation"],
        certified_at=NOW,
    )
    return preview, persisted


def issue_release(db: Session, certification_id: str, *, token="m44-release-001"):
    args = {
        "certification_id": certification_id,
        "wallet_address": WALLET,
        "side": "BUY",
        "token_mint": TOKEN,
        "max_budget_sol": "0.005",
        "validity_minutes": 5,
        "idempotency_token": token,
        "settings_object": settings_for_m44(),
        "evaluated_at": NOW,
    }
    preview = service.preview_preproduction_release_approval(db, **args)
    result = service.issue_preproduction_release_approval(
        db,
        **{k: v for k, v in args.items() if k != "evaluated_at"},
        confirmation=preview["confirmation"],
        issued_at=NOW,
    )
    return preview, result


def test_m44_flags_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_ENABLED is False
    assert configured.CANONICAL_PARSER_PREPRODUCTION_RELEASE_GUARD_ENABLED is False


def test_m44_models_and_migration_are_registered():
    for table in (
        "canonical_parser_preproduction_certifications",
        "canonical_parser_preproduction_certification_checks",
        "canonical_parser_preproduction_certification_events",
        "canonical_parser_preproduction_release_approvals",
        "canonical_parser_preproduction_release_approval_events",
    ):
        assert table in Base.metadata.tables
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("a9d1e4f7b853").down_revision == "f8c0d3e6a742"
    assert scripts.get_heads() == ["c1f3a6b9d075"]


def test_certification_preview_passes_all_checks(db):
    snapshot = add_healthy_snapshot(db)
    preview, _ = certification_preview(db, snapshot.snapshot_id)
    assert preview["status"] == "READY"
    assert len(preview["checks"]) == 12
    assert preview["failed_checks"] == []


def test_certification_blocks_failed_full_suite(db):
    snapshot = add_healthy_snapshot(db)
    preview, _ = certification_preview(
        db,
        snapshot.snapshot_id,
        full_test_count=1000,
        full_test_failures=1,
        idempotency_token="m44-certification-fail",
    )
    assert preview["status"] == "BLOCKED"
    assert "FULL_TEST_SUITE" in preview["failed_checks"]


def test_certification_persists_checks_and_event(db):
    snapshot = add_healthy_snapshot(db)
    _, result = certify(db, snapshot.snapshot_id)
    assert result["status"] == "ACTIVE"
    assert db.query(CanonicalParserPreproductionCertification).count() == 1
    assert db.query(CanonicalParserPreproductionCertificationCheck).count() == 12
    assert db.query(CanonicalParserPreproductionCertificationEvent).count() == 1


def test_release_is_bound_and_single_use(db):
    snapshot = add_healthy_snapshot(db)
    _, certification = certify(db, snapshot.snapshot_id)
    _, release = issue_release(db, certification["certification_id"])
    validation = service.validate_preproduction_release_for_submission(
        db,
        release_id=release["release_id"],
        wallet_address=WALLET,
        side="BUY",
        token_mint=TOKEN,
        requested_budget_sol="0.005",
        settings_object=settings_for_m44(),
        evaluated_at=NOW,
    )
    assert validation["ready"] is True
    consumed = service.consume_preproduction_release_approval(
        db,
        release_id=release["release_id"],
        submission_id="submission-0000000000000000000001"[:36],
        wallet_address=WALLET,
        side="BUY",
        token_mint=TOKEN,
        requested_budget_sol="0.005",
        settings_object=settings_for_m44(),
        consumed_at=NOW + timedelta(seconds=1),
    )
    db.commit()
    assert consumed["consumed"] is True
    row = db.query(CanonicalParserPreproductionReleaseApproval).one()
    assert row.status == "CONSUMED"
    assert db.query(CanonicalParserPreproductionReleaseApprovalEvent).count() == 2
    second = service.validate_preproduction_release_for_submission(
        db,
        release_id=release["release_id"],
        wallet_address=WALLET,
        side="BUY",
        token_mint=TOKEN,
        requested_budget_sol="0.005",
        settings_object=settings_for_m44(),
        evaluated_at=NOW + timedelta(seconds=2),
    )
    assert second["ready"] is False
    assert "M44_PREPRODUCTION_RELEASE_NOT_ACTIVE" in second["reason_codes"]


def test_release_wallet_and_budget_mismatch_are_blocked(db):
    snapshot = add_healthy_snapshot(db)
    _, certification = certify(db, snapshot.snapshot_id)
    _, release = issue_release(db, certification["certification_id"])
    validation = service.validate_preproduction_release_for_submission(
        db,
        release_id=release["release_id"],
        wallet_address="3" * 32,
        side="BUY",
        token_mint=TOKEN,
        requested_budget_sol="0.006",
        settings_object=settings_for_m44(),
        evaluated_at=NOW,
    )
    assert validation["ready"] is False
    assert "M44_PREPRODUCTION_RELEASE_WALLET_MISMATCH" in validation["reason_codes"]
    assert "M44_PREPRODUCTION_RELEASE_BUDGET_EXCEEDED" in validation["reason_codes"]


def test_release_guard_disabled_does_not_require_approval(db):
    result = service.validate_preproduction_release_for_submission(
        db,
        release_id=None,
        wallet_address=WALLET,
        side="BUY",
        token_mint=TOKEN,
        requested_budget_sol="0.005",
        settings_object=settings_for_m44(CANONICAL_PARSER_PREPRODUCTION_RELEASE_GUARD_ENABLED=False),
        evaluated_at=NOW,
    )
    assert result["required"] is False
    assert result["ready"] is True


def test_certification_and_release_can_be_revoked(db):
    snapshot = add_healthy_snapshot(db)
    _, certification = certify(db, snapshot.snapshot_id)
    _, release = issue_release(db, certification["certification_id"])
    revoked_release = service.revoke_preproduction_release_approval(
        db,
        release_id=release["release_id"],
        confirmation=f"{service.REVOKE_RELEASE_PREFIX}:{release['release_id']}:{release['evidence_hash']}",
        reason="operator cancelled",
        settings_object=settings_for_m44(),
        revoked_at=NOW + timedelta(seconds=1),
    )
    revoked_certification = service.revoke_preproduction_certification(
        db,
        certification_id=certification["certification_id"],
        confirmation=f"{service.REVOKE_CERT_PREFIX}:{certification['certification_id']}:{certification['evidence_hash']}",
        reason="new build required",
        settings_object=settings_for_m44(),
        revoked_at=NOW + timedelta(seconds=2),
    )
    assert revoked_release["status"] == "REVOKED"
    assert revoked_certification["status"] == "REVOKED"


def test_m38_integration_openapi_and_static_safety():
    m38 = Path("backend/app/services/blockchain_parser_controlled_live_submission_service.py").read_text()
    assert "validate_preproduction_release_for_submission" in m38
    assert "consume_preproduction_release_approval" in m38
    assert "preproduction_release_approval_id" in m38
    schema = app.openapi()
    required = {
        ("get", "/integrity/parser-preproduction-certification/status"),
        ("post", "/integrity/parser-preproduction-certification/certify"),
        ("post", "/integrity/parser-preproduction-certification/release/issue"),
        ("get", "/integrity/parser-preproduction-certification/releases/{release_id}"),
    }
    for method, path in required:
        assert method in schema["paths"][path]
    tree = ast.parse(Path(service.__file__).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "backend.app.services.solana_transaction_signer" not in imports
    assert "backend.app.services.live_copy_trading_engine" not in imports
    assert "backend.app.workers.helius_live_trading_worker" not in imports
