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
    CanonicalQualityGateError,
    execute_canonical_quality_assessment,
    get_canonical_quality_assessment,
    get_canonical_quality_gate_status,
    preview_canonical_quality_gate,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash


AUTOMATION_KEY = "a" * 32
FIXED_NOW = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)
M6_TABLES = [
    RawBlockchainEvent.__table__,
    NormalizationRun.__table__,
    NormalizationReplayBatch.__table__,
    NormalizationArtifact.__table__,
    Trade.__table__,
    CanonicalNormalizedEvent.__table__,
    CanonicalShadowValidationBatch.__table__,
    CanonicalShadowValidationResult.__table__,
    CanonicalQualityAssessment.__table__,
]


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=M6_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def safe_global_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
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


def _policy(*, enabled: bool = False, **overrides):
    values = {
        "CANONICAL_QUALITY_GATE_ENABLED": enabled,
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


def _add_chain(
    db: Session,
    *,
    index: int,
    parser_version: str = "1.0.0",
    parser_hash: str = "a" * 64,
    quality_status: str = "PASS",
):
    signature = f"m6-signature-{index}"
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
        observed_wallet="WalletM6",
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
        parser_name="swap_canonical_event",
        parser_version=parser_version,
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

    artifact_payload = {
        "signature": signature,
        "side": "BUY",
        "token_mint": "TokenM6",
    }
    artifact = NormalizationArtifact(
        normalization_run_id=run.id,
        raw_event_id=raw.id,
        parser_name="swap_canonical_event",
        parser_version=parser_version,
        parser_implementation_hash=parser_hash,
        artifact_type="CANONICAL_SWAP_EVENT",
        artifact_index=0,
        schema_version="canonical-swap/1",
        payload=artifact_payload,
        payload_hash=calculate_payload_hash(artifact_payload),
        artifact_metadata={},
    )
    db.add(artifact)
    db.flush()

    canonical_payload = {
        "signature": signature,
        "side": "BUY",
        "token_mint": "TokenM6",
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
        parser_name="swap_canonical_event",
        parser_version=parser_version,
        parser_implementation_hash=parser_hash,
        schema_version="canonical-swap/1",
        canonical_type="SWAP",
        transaction_signature=signature,
        observed_wallet="WalletM6",
        side="BUY",
        source="JUPITER",
        token_mint="TokenM6",
        token_amount=10,
        sol_amount=0.1,
        fee_lamports=5000,
        success=True,
        block_time=FIXED_NOW,
        quality_status=quality_status,
        quality_flags=[],
        canonical_payload=canonical_payload,
        canonical_payload_hash=calculate_payload_hash(canonical_payload),
        technical_metadata={},
    )
    db.add(canonical)
    db.flush()
    return canonical


def _insert_batch(
    db: Session,
    statuses: list[str],
    *,
    batch_status: str = "COMPLETED",
    failed_count: int = 0,
    completed_at: datetime | None = FIXED_NOW,
    parser_versions: list[str] | None = None,
    quality_statuses: list[str] | None = None,
):
    counts = Counter(statuses)
    batch = CanonicalShadowValidationBatch(
        validation_id=str(uuid4()),
        comparator_version="canonical-trade-shadow/1",
        status=batch_status,
        request_filters={},
        requested_limit=max(1, len(statuses) + failed_count),
        selected_count=len(statuses) + failed_count,
        processed_count=len(statuses) + failed_count,
        match_count=counts["MATCH"],
        mismatch_count=counts["MISMATCH"],
        missing_trade_count=counts["MISSING_TRADE"],
        not_comparable_count=counts["NOT_COMPARABLE"],
        failed_count=failed_count,
        started_at=FIXED_NOW - timedelta(minutes=1),
        completed_at=completed_at,
        technical_metadata={"external_requests": 0, "writes_trades": False},
    )
    db.add(batch)
    db.flush()

    for index, status in enumerate(statuses):
        parser_version = (
            parser_versions[index] if parser_versions is not None else "1.0.0"
        )
        quality_status = (
            quality_statuses[index]
            if quality_statuses is not None
            else "PASS"
        )
        canonical = _add_chain(
            db,
            index=index + batch.id * 1000,
            parser_version=parser_version,
            parser_hash=("a" if parser_version == "1.0.0" else "b") * 64,
            quality_status=quality_status,
        )
        canonical_snapshot = {
            "signature": canonical.transaction_signature,
            "side": canonical.side,
            "token_amount": "10",
        }
        trade_snapshot = None
        mismatch_fields: list[str] = []
        if status in {"MATCH", "MISMATCH"}:
            trade_snapshot = {
                "signature": canonical.transaction_signature,
                "side": "BUY" if status == "MATCH" else "SELL",
                "token_amount": "10",
            }
        if status == "MISMATCH":
            mismatch_fields = ["side"]
        db.add(
            CanonicalShadowValidationResult(
                validation_batch_id=batch.id,
                canonical_event_id=canonical.id,
                trade_id=None,
                transaction_signature=canonical.transaction_signature,
                comparator_version=batch.comparator_version,
                status=status,
                mismatch_fields=mismatch_fields,
                canonical_snapshot=canonical_snapshot,
                trade_snapshot=trade_snapshot,
                canonical_snapshot_hash=calculate_payload_hash(canonical_snapshot),
                trade_snapshot_hash=(
                    calculate_payload_hash(trade_snapshot)
                    if trade_snapshot is not None
                    else None
                ),
                technical_metadata={
                    "external_requests": 0,
                    "writes_trades": False,
                },
            )
        )
    db.commit()
    return batch


def _client(db_factory):
    def override_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m6_model_registered_and_exported():
    assert models.CanonicalQualityAssessment is CanonicalQualityAssessment
    assert "canonical_quality_assessments" in Base.metadata.tables


def test_m6_configuration_defaults_are_safe():
    configured = Settings(_env_file=None, **_settings_values())
    assert configured.CANONICAL_QUALITY_GATE_ENABLED is False
    assert configured.CANONICAL_QUALITY_GATE_MIN_COMPARABLE_EVENTS == 50
    assert configured.CANONICAL_QUALITY_GATE_MIN_MATCH_RATE == 98.0
    assert configured.CANONICAL_QUALITY_GATE_MAX_MISMATCH_RATE == 2.0
    assert configured.CANONICAL_QUALITY_GATE_MAX_EVIDENCE_AGE_HOURS == 168


def test_preview_requires_validation_evidence(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalQualityGateError) as caught:
            preview_canonical_quality_gate(db, settings_object=_policy())
    assert caught.value.code == "QUALITY_GATE_VALIDATION_BATCH_NOT_FOUND"


def test_preview_is_deterministic(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        first = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
        second = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert first["policy_hash"] == second["policy_hash"]
    assert first["evidence_hash"] == second["evidence_hash"]
    assert first["assessment_key"] == second["assessment_key"]


def test_latest_batch_is_selected_when_id_omitted(db_factory):
    with db_factory() as db:
        _insert_batch(db, ["MISMATCH"] * 10)
        latest = _insert_batch(db, ["MATCH"] * 10)
        preview = preview_canonical_quality_gate(
            db,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["validation_id"] == latest.validation_id
    assert preview["decision"] == "READY"


def test_insufficient_data_decision(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 9)
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "INSUFFICIENT_DATA"
    assert "COMPARABLE_SAMPLE_BELOW_MINIMUM" in preview["reason_codes"]


def test_ready_decision(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "READY"
    assert preview["metrics"]["match_rate"] == 100.0
    assert preview["reason_codes"] == []


def test_mismatch_rate_blocks(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 8 + ["MISMATCH"] * 2)
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "BLOCKED"
    assert "MATCH_RATE_BELOW_MINIMUM" in preview["reason_codes"]
    assert "MISMATCH_RATE_ABOVE_MAXIMUM" in preview["reason_codes"]
    assert preview["metrics"]["mismatch_field_counts"] == {"side": 2}


def test_missing_trade_rate_blocks(db_factory):
    with db_factory() as db:
        batch = _insert_batch(
            db,
            ["MATCH"] * 10 + ["MISSING_TRADE"] * 2,
        )
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "BLOCKED"
    assert "MISSING_TRADE_RATE_ABOVE_MAXIMUM" in preview["reason_codes"]


def test_not_comparable_rate_requires_review(db_factory):
    with db_factory() as db:
        batch = _insert_batch(
            db,
            ["MATCH"] * 10 + ["NOT_COMPARABLE"],
        )
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "REVIEW"
    assert "NOT_COMPARABLE_RATE_ABOVE_MAXIMUM" in preview["reason_codes"]


def test_stale_evidence_requires_review(db_factory):
    with db_factory() as db:
        batch = _insert_batch(
            db,
            ["MATCH"] * 10,
            completed_at=FIXED_NOW - timedelta(days=8),
        )
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "REVIEW"
    assert "EVIDENCE_STALE" in preview["reason_codes"]


def test_partial_batch_requires_review_when_failure_threshold_allows(db_factory):
    with db_factory() as db:
        batch = _insert_batch(
            db,
            ["MATCH"] * 10,
            batch_status="PARTIAL",
            failed_count=1,
        )
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(
                CANONICAL_QUALITY_GATE_MAX_FAILED_RATE=100.0
            ),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "REVIEW"
    assert "VALIDATION_BATCH_PARTIAL" in preview["reason_codes"]


def test_failed_batch_is_blocked(db_factory):
    with db_factory() as db:
        batch = _insert_batch(
            db,
            [],
            batch_status="FAILED",
            failed_count=1,
        )
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "BLOCKED"
    assert "VALIDATION_BATCH_FAILED" in preview["reason_codes"]


def test_tampered_snapshot_is_blocked(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        result = db.query(CanonicalShadowValidationResult).first()
        result.canonical_snapshot = {"tampered": True}
        db.commit()
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "BLOCKED"
    assert "CANONICAL_SNAPSHOT_HASH_MISMATCH" in preview["reason_codes"]


def test_batch_count_reconciliation_is_enforced(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        batch.match_count = 9
        db.commit()
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "BLOCKED"
    assert "STATUS_COUNT_RECONCILIATION_FAILED" in preview["reason_codes"]


def test_mixed_parser_identity_is_blocked(db_factory):
    with db_factory() as db:
        batch = _insert_batch(
            db,
            ["MATCH"] * 10,
            parser_versions=["1.0.0"] * 9 + ["2.0.0"],
        )
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "BLOCKED"
    assert "MIXED_PARSER_IDENTITY" in preview["reason_codes"]


def test_quality_pass_rate_is_enforced(db_factory):
    with db_factory() as db:
        batch = _insert_batch(
            db,
            ["MATCH"] * 10,
            quality_statuses=["PASS"] * 9 + ["FAIL"],
        )
        preview = preview_canonical_quality_gate(
            db,
            validation_id=batch.validation_id,
            settings_object=_policy(),
            evaluated_at=FIXED_NOW,
        )
    assert preview["decision"] == "BLOCKED"
    assert "QUALITY_PASS_RATE_BELOW_MINIMUM" in preview["reason_codes"]


def test_execute_requires_feature_flag(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        with pytest.raises(CanonicalQualityGateError) as caught:
            execute_canonical_quality_assessment(
                db,
                confirmation=QUALITY_GATE_CONFIRMATION,
                validation_id=batch.validation_id,
                settings_object=_policy(enabled=False),
                evaluated_at=FIXED_NOW,
            )
    assert caught.value.code == "CANONICAL_QUALITY_GATE_DISABLED"


def test_execute_requires_exact_confirmation(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        with pytest.raises(CanonicalQualityGateError) as caught:
            execute_canonical_quality_assessment(
                db,
                confirmation="wrong",
                validation_id=batch.validation_id,
                settings_object=_policy(enabled=True),
                evaluated_at=FIXED_NOW,
            )
    assert caught.value.code == "CANONICAL_QUALITY_GATE_CONFIRMATION_REQUIRED"


def test_assessment_is_persisted_retrieved_and_idempotent(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        first = execute_canonical_quality_assessment(
            db,
            confirmation=QUALITY_GATE_CONFIRMATION,
            validation_id=batch.validation_id,
            settings_object=_policy(enabled=True),
            evaluated_at=FIXED_NOW,
        )
        second = execute_canonical_quality_assessment(
            db,
            confirmation=QUALITY_GATE_CONFIRMATION,
            validation_id=batch.validation_id,
            settings_object=_policy(enabled=True),
            evaluated_at=FIXED_NOW,
        )
        fetched = get_canonical_quality_assessment(db, first["assessment_id"])
    assert first["created"] is True
    assert second["created"] is False
    assert first["assessment_id"] == second["assessment_id"]
    assert fetched["status"] == "READY"
    assert db.query(CanonicalQualityAssessment).count() == 1


def test_policy_change_creates_new_assessment(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        first = execute_canonical_quality_assessment(
            db,
            confirmation=QUALITY_GATE_CONFIRMATION,
            validation_id=batch.validation_id,
            settings_object=_policy(enabled=True),
            evaluated_at=FIXED_NOW,
        )
        second = execute_canonical_quality_assessment(
            db,
            confirmation=QUALITY_GATE_CONFIRMATION,
            validation_id=batch.validation_id,
            settings_object=_policy(
                enabled=True,
                CANONICAL_QUALITY_GATE_MIN_MATCH_RATE=99.0,
            ),
            evaluated_at=FIXED_NOW,
        )
    assert first["assessment_key"] != second["assessment_key"]
    assert db.query(CanonicalQualityAssessment).count() == 2


def test_status_reports_latest_assessment_and_safe_guards(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        created = execute_canonical_quality_assessment(
            db,
            confirmation=QUALITY_GATE_CONFIRMATION,
            validation_id=batch.validation_id,
            settings_object=_policy(enabled=True),
            evaluated_at=FIXED_NOW,
        )
        status = get_canonical_quality_gate_status(
            db,
            settings_object=_policy(enabled=False),
        )
    assert status["quality_gate_enabled"] is False
    assert status["assessment_count"] == 1
    assert status["latest_assessment"]["assessment_id"] == created["assessment_id"]
    assert status["operational_guards"]["writes_trades"] is False


def test_assessment_never_writes_trade_or_uses_network(monkeypatch, db_factory):
    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("Nessuna rete consentita durante M6.")

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        trade_count = db.query(Trade).count()
        result = execute_canonical_quality_assessment(
            db,
            confirmation=QUALITY_GATE_CONFIRMATION,
            validation_id=batch.validation_id,
            settings_object=_policy(enabled=True),
            evaluated_at=FIXED_NOW,
        )
        assert db.query(Trade).count() == trade_count
    assert result["technical_metadata"]["external_requests"] == 0
    assert result["technical_metadata"]["writes_trades"] is False


def test_m6_service_has_no_network_clients_or_trade_writes():
    path = Path(
        "backend/app/services/blockchain_canonical_quality_gate_service.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not (imports & {"httpx", "requests", "aiohttp", "urllib3", "websockets"})
    source = path.read_text(encoding="utf-8")
    assert "db.add(Trade" not in source
    assert "execute_source_trade" not in source
    assert "app.include_router" not in source


def test_m6_api_routes_are_protected_and_registered_once(db_factory):
    route_counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            route_counts[(method, getattr(route, "path", ""))] += 1
    expected = {
        ("GET", "/integrity/quality-gate/status"),
        ("GET", "/integrity/quality-gate/preview"),
        ("POST", "/integrity/quality-gate/assess"),
        ("GET", "/integrity/quality-gate/assessments/{assessment_id}"),
    }
    for route_key in expected:
        assert route_counts[route_key] == 1

    client = _client(db_factory)
    try:
        assert client.get("/integrity/quality-gate/status").status_code == 401
        response = client.get(
            "/integrity/quality-gate/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["quality_gate_enabled"] is False
        execute_response = client.post(
            "/integrity/quality-gate/assess",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={"confirmation": QUALITY_GATE_CONFIRMATION},
        )
        assert execute_response.status_code == 409
        assert (
            execute_response.json()["detail"]["code"]
            == "CANONICAL_QUALITY_GATE_DISABLED"
        )
    finally:
        app.dependency_overrides.clear()


def test_m6_unique_assessment_key_constraint(db_factory):
    with db_factory() as db:
        batch = _insert_batch(db, ["MATCH"] * 10)
        created = execute_canonical_quality_assessment(
            db,
            confirmation=QUALITY_GATE_CONFIRMATION,
            validation_id=batch.validation_id,
            settings_object=_policy(enabled=True),
            evaluated_at=FIXED_NOW,
        )
        original = db.query(CanonicalQualityAssessment).one()
        duplicate = CanonicalQualityAssessment(
            assessment_id=str(uuid4()),
            assessment_key=original.assessment_key,
            validation_batch_id=original.validation_batch_id,
            validation_id=original.validation_id,
            policy_version=original.policy_version,
            policy_hash=original.policy_hash,
            evidence_hash=original.evidence_hash,
            status=original.status,
            parser_name=original.parser_name,
            parser_version=original.parser_version,
            parser_implementation_hash=original.parser_implementation_hash,
            comparator_version=original.comparator_version,
            sample_size=original.sample_size,
            comparable_count=original.comparable_count,
            match_count=original.match_count,
            mismatch_count=original.mismatch_count,
            missing_trade_count=original.missing_trade_count,
            not_comparable_count=original.not_comparable_count,
            failed_count=original.failed_count,
            quality_pass_count=original.quality_pass_count,
            quality_warn_count=original.quality_warn_count,
            quality_fail_count=original.quality_fail_count,
            match_rate=original.match_rate,
            mismatch_rate=original.mismatch_rate,
            missing_trade_rate=original.missing_trade_rate,
            not_comparable_rate=original.not_comparable_rate,
            failed_rate=original.failed_rate,
            quality_pass_rate=original.quality_pass_rate,
            reason_codes=[],
            mismatch_field_counts={},
            threshold_snapshot={},
            metrics_snapshot={},
            technical_metadata={},
            evidence_completed_at=FIXED_NOW,
            evaluated_at=FIXED_NOW,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
    assert created["created"] is True


def test_m6_migration_upgrade_downgrade_upgrade_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CanonicalShadowValidationBatch.__table__],
    )
    path = Path(
        "alembic/versions/e7b2c9d4a610_add_canonical_quality_gate.py"
    )
    spec = importlib.util.spec_from_file_location("m6_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = module.op
        module.op = operations
        try:
            module.upgrade()
            tables = set(inspect(connection).get_table_names())
            assert "canonical_quality_assessments" in tables
            module.downgrade()
            tables = set(inspect(connection).get_table_names())
            assert "canonical_quality_assessments" not in tables
            module.upgrade()
            tables = set(inspect(connection).get_table_names())
            assert "canonical_quality_assessments" in tables
        finally:
            module.op = original_op
    engine.dispose()
