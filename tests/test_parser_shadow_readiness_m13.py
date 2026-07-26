from __future__ import annotations

import ast
import importlib.util
from collections import Counter
from datetime import timedelta
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
    CanonicalParserShadowConsumerResult,
    CanonicalParserShadowConsumerRun,
    CanonicalParserShadowReadinessAssessment,
    CanonicalParserShadowReadinessEvidenceRun,
    CanonicalParserShadowRuntimeLease,
    RawBlockchainEvent,
)
from backend.app.models.trade import Trade
from backend.app.services.blockchain_parser_shadow_consumer_service import (
    preview_shadow_consumer_run,
    run_shadow_consumer_dry_run,
)
from backend.app.services.blockchain_parser_shadow_readiness_service import (
    READINESS_CONFIRMATION_PREFIX,
    READINESS_POLICY_VERSION,
    CanonicalParserShadowReadinessError,
    execute_shadow_consumer_readiness_assessment,
    get_shadow_consumer_readiness_assessment,
    get_shadow_consumer_readiness_status,
    preview_shadow_consumer_readiness,
    resolve_shadow_consumer_readiness,
)
from backend.app.services.blockchain_parser_shadow_runtime_lease_service import (
    LEASE_REVOKE_PREFIX,
    revoke_shadow_runtime_lease,
)

AUTOMATION_KEY = "a" * 32


def _load_m12_helpers():
    path = Path(__file__).with_name("test_parser_shadow_consumer_m12.py")
    spec = importlib.util.spec_from_file_location("m12_test_helpers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


M12 = _load_m12_helpers()
NOW = M12.NOW + timedelta(minutes=16)


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
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_RUNS": 3,
        "CANONICAL_PARSER_SHADOW_READINESS_MAX_RUNS": 20,
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_TOTAL_EVENTS": 15,
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_UNIQUE_EVENTS": 10,
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_PASS_RATE": 100.0,
        "CANONICAL_PARSER_SHADOW_READINESS_MAX_FAILED_EVENTS": 0,
        "CANONICAL_PARSER_SHADOW_READINESS_MAX_SKIPPED_EVENTS": 0,
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_OBSERVATION_SPAN_MINUTES": 5,
        "CANONICAL_PARSER_SHADOW_READINESS_MAX_EVIDENCE_AGE_MINUTES": 30,
        "CANONICAL_PARSER_SHADOW_READINESS_VALIDITY_MINUTES": 15,
    }
    for name, value in defaults.items():
        monkeypatch.setattr(settings, name, value)


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test-helius-api-key",
    }
    values.update(overrides)
    return values


def _readiness_policy(**overrides):
    values = {
        "CANONICAL_PARSER_SHADOW_READINESS_ENABLED": True,
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_RUNS": 3,
        "CANONICAL_PARSER_SHADOW_READINESS_MAX_RUNS": 20,
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_TOTAL_EVENTS": 15,
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_UNIQUE_EVENTS": 10,
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_PASS_RATE": 100.0,
        "CANONICAL_PARSER_SHADOW_READINESS_MAX_FAILED_EVENTS": 0,
        "CANONICAL_PARSER_SHADOW_READINESS_MAX_SKIPPED_EVENTS": 0,
        "CANONICAL_PARSER_SHADOW_READINESS_MIN_OBSERVATION_SPAN_MINUTES": 5,
        "CANONICAL_PARSER_SHADOW_READINESS_MAX_EVIDENCE_AGE_MINUTES": 30,
        "CANONICAL_PARSER_SHADOW_READINESS_VALIDITY_MINUTES": 15,
        "CANONICAL_PARSER_SHADOW_LEASE_ENABLED": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _consumer_policy():
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_CONSUMER_ENABLED=True,
        CANONICAL_PARSER_SHADOW_CONSUMER_MAX_SAMPLE_SIZE=25,
        CANONICAL_PARSER_SHADOW_LEASE_ENABLED=True,
    )


def _prepare_evidence(
    db,
    *,
    selections=None,
    offsets=(0, 5, 10),
):
    lease, events = M12._prepare(db)
    selections = selections or (
        [0, 1, 2, 3, 4],
        [5, 6, 7, 8, 9],
        [0, 2, 4, 6, 8],
    )
    runs = []
    for offset, indexes in zip(offsets, selections, strict=True):
        event_ids = [events[index].id for index in indexes]
        started_at = M12.NOW + timedelta(minutes=offset)
        preview = preview_shadow_consumer_run(
            db,
            lease_id=lease["lease_id"],
            raw_event_ids=event_ids,
            limit=len(event_ids),
            settings_object=_consumer_policy(),
            evaluated_at=started_at,
        )
        run = run_shadow_consumer_dry_run(
            db,
            confirmation=preview["confirmation"],
            lease_id=lease["lease_id"],
            raw_event_ids=event_ids,
            limit=len(event_ids),
            actor_label="m13-evidence",
            settings_object=_consumer_policy(),
            started_at=started_at,
            completed_at=started_at + timedelta(minutes=1),
        )
        runs.append(run)
    return lease, events, runs


def _assess_ready(db, *, policy=None, evaluated_at=NOW):
    policy = policy or _readiness_policy()
    lease, events, runs = _prepare_evidence(db)
    preview = preview_shadow_consumer_readiness(
        db,
        lease_id=lease["lease_id"],
        settings_object=policy,
        evaluated_at=evaluated_at,
    )
    assessment = execute_shadow_consumer_readiness_assessment(
        db,
        confirmation=preview["confirmation"],
        lease_id=lease["lease_id"],
        actor_label="m13-operator",
        note="manual evidence gate",
        settings_object=policy,
        evaluated_at=evaluated_at,
    )
    return lease, events, runs, preview, assessment


def _yield_db(factory):
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _client(factory):
    def override_db():
        yield from _yield_db(factory)

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_settings_defaults_are_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_READINESS_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_READINESS_MIN_RUNS == 3
    assert configured.CANONICAL_PARSER_SHADOW_READINESS_MIN_TOTAL_EVENTS == 15
    assert configured.CANONICAL_PARSER_SHADOW_READINESS_VALIDITY_MINUTES == 15


def test_status_is_disabled_and_has_no_consumer(db_factory):
    with db_factory() as db:
        status = get_shadow_consumer_readiness_status(db)
        assert status["readiness_enabled"] is False
        assert status["policy_version"] == READINESS_POLICY_VERSION
        assert status["assessment_count"] == 0
        assert status["operational_guards"]["manual_assessment_only"] is True
        assert status["operational_guards"]["consumer_connected"] is False
        assert status["operational_guards"]["writes_trades"] is False


def test_preview_without_lease_is_not_assessable(db_factory):
    with db_factory() as db:
        preview = preview_shadow_consumer_readiness(
            db, settings_object=_readiness_policy(), evaluated_at=NOW
        )
        assert preview["assessable"] is False
        assert preview["decision"] == "BLOCKED"
        assert "SHADOW_READINESS_LEASE_MISSING" in preview["reason_codes"]


def test_preview_ready_is_deterministic_and_manual_only(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(db)
        first = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(),
            evaluated_at=NOW,
        )
        second = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(),
            evaluated_at=NOW + timedelta(minutes=1),
        )
        assert first["decision"] == "READY"
        assert first["ready"] is True
        assert first["assessment_key"] == second["assessment_key"]
        assert first["confirmation"] == second["confirmation"]
        assert first["confirmation"].startswith(READINESS_CONFIRMATION_PREFIX)
        assert first["writes_database"] is False
        assert first["writes_trades"] is False
        assert first["external_requests"] == 0
        assert first["automatic_execution"] is False


def test_preview_reports_insufficient_runs(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(
            db,
            selections=([0, 1, 2, 3, 4], [5, 6, 7, 8, 9]),
            offsets=(0, 5),
        )
        preview = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(
                CANONICAL_PARSER_SHADOW_READINESS_MIN_TOTAL_EVENTS=10,
            ),
            evaluated_at=NOW,
        )
        assert preview["decision"] == "INSUFFICIENT_DATA"
        assert "SHADOW_READINESS_RUNS_BELOW_MINIMUM" in preview["reason_codes"]


def test_preview_reports_insufficient_unique_events(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(
            db,
            selections=([0, 1], [1, 2], [2, 3, 4]),
            offsets=(0, 5, 10),
        )
        preview = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(
                CANONICAL_PARSER_SHADOW_READINESS_MIN_TOTAL_EVENTS=7,
                CANONICAL_PARSER_SHADOW_READINESS_MIN_UNIQUE_EVENTS=10,
            ),
            evaluated_at=NOW,
        )
        assert preview["decision"] == "INSUFFICIENT_DATA"
        assert "SHADOW_READINESS_UNIQUE_EVENTS_BELOW_MINIMUM" in preview["reason_codes"]


def test_preview_reports_insufficient_observation_span(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(db, offsets=(0, 1, 2))
        preview = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(
                CANONICAL_PARSER_SHADOW_READINESS_MIN_OBSERVATION_SPAN_MINUTES=5,
            ),
            evaluated_at=M12.NOW + timedelta(minutes=8),
        )
        assert preview["decision"] == "INSUFFICIENT_DATA"
        assert "SHADOW_READINESS_OBSERVATION_SPAN_BELOW_MINIMUM" in preview["reason_codes"]


def test_stale_evidence_requires_review_while_lease_is_active(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(db)
        preview = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(
                CANONICAL_PARSER_SHADOW_READINESS_MAX_EVIDENCE_AGE_MINUTES=5,
            ),
            evaluated_at=M12.NOW + timedelta(minutes=24),
        )
        assert preview["decision"] == "REVIEW"
        assert "SHADOW_EVIDENCE_STALE" in preview["reason_codes"]


def test_tampered_result_hash_blocks_readiness(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(db)
        result = db.scalars(select(CanonicalParserShadowConsumerResult)).first()
        result.output_hash = "f" * 64
        db.commit()
        preview = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(),
            evaluated_at=NOW,
        )
        assert preview["decision"] == "BLOCKED"
        assert "SHADOW_RESULT_OUTPUT_HASH_MISMATCH" in preview["reason_codes"]


def test_raw_payload_drift_blocks_readiness(db_factory):
    with db_factory() as db:
        lease, events, _ = _prepare_evidence(db)
        events[0].raw_payload = [{"type": "SWAP", "tampered": True}]
        db.commit()
        preview = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(),
            evaluated_at=NOW,
        )
        assert preview["decision"] == "BLOCKED"
        assert "SHADOW_RESULT_RAW_PAYLOAD_HASH_INVALID" in preview["reason_codes"]


def test_run_count_tampering_blocks_readiness(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(db)
        run = db.scalars(select(CanonicalParserShadowConsumerRun)).first()
        run.passed_count += 1
        run.processed_count += 1
        run.selected_count += 1
        db.commit()
        preview = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(),
            evaluated_at=NOW,
        )
        assert preview["decision"] == "BLOCKED"
        assert "SHADOW_RUN_RESULT_COUNT_MISMATCH" in preview["reason_codes"]


def test_run_key_tampering_blocks_readiness(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(db)
        run = db.scalars(select(CanonicalParserShadowConsumerRun)).first()
        run.run_key = "e" * 64
        db.commit()
        preview = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(),
            evaluated_at=NOW,
        )
        assert preview["decision"] == "BLOCKED"
        assert "SHADOW_RUN_KEY_INVALID" in preview["reason_codes"]


def test_assessment_is_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(CanonicalParserShadowReadinessError) as exc:
            execute_shadow_consumer_readiness_assessment(
                db, confirmation="anything"
            )
        assert exc.value.code == "CANONICAL_PARSER_SHADOW_READINESS_DISABLED"


def test_assessment_requires_current_confirmation(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(db)
        with pytest.raises(CanonicalParserShadowReadinessError) as exc:
            execute_shadow_consumer_readiness_assessment(
                db,
                confirmation="stale",
                lease_id=lease["lease_id"],
                settings_object=_readiness_policy(),
                evaluated_at=NOW,
            )
        assert exc.value.code == "SHADOW_READINESS_CONFIRMATION_REQUIRED"


def test_ready_assessment_persists_immutable_evidence_only(db_factory):
    with db_factory() as db:
        _, _, _, _, assessment = _assess_ready(db)
        assert assessment["created"] is True
        assert assessment["status"] == "READY"
        assert assessment["run_count"] == 3
        assert assessment["total_processed_count"] == 15
        assert assessment["unique_event_count"] == 10
        assert len(assessment["evidence_runs"]) == 3
        assert db.query(CanonicalParserShadowReadinessAssessment).count() == 1
        assert db.query(CanonicalParserShadowReadinessEvidenceRun).count() == 3
        assert db.query(Trade).count() == 0
        assert db.query(CanonicalNormalizedEvent).count() == 0


def test_assessment_is_idempotent_by_policy_and_evidence(db_factory):
    with db_factory() as db:
        lease, _, _, preview, first = _assess_ready(db)
        second = execute_shadow_consumer_readiness_assessment(
            db,
            confirmation=preview["confirmation"],
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(),
            evaluated_at=NOW + timedelta(minutes=1),
        )
        assert second["created"] is False
        assert second["assessment_id"] == first["assessment_id"]
        assert db.query(CanonicalParserShadowReadinessAssessment).count() == 1


def test_actor_and_note_are_sanitized(db_factory):
    with db_factory() as db:
        lease, _, _ = _prepare_evidence(db)
        preview = preview_shadow_consumer_readiness(
            db,
            lease_id=lease["lease_id"],
            settings_object=_readiness_policy(),
            evaluated_at=NOW,
        )
        assessment = execute_shadow_consumer_readiness_assessment(
            db,
            confirmation=preview["confirmation"],
            lease_id=lease["lease_id"],
            actor_label="operator\nsecret",
            note="line\r\nprivate",
            settings_object=_readiness_policy(),
            evaluated_at=NOW,
        )
        assert "\n" not in assessment["actor_label"]
        assert "\r" not in assessment["note"]


def test_get_assessment_and_not_found(db_factory):
    with db_factory() as db:
        _, _, _, _, assessment = _assess_ready(db)
        loaded = get_shadow_consumer_readiness_assessment(
            db, assessment["assessment_id"]
        )
        assert loaded["assessment_id"] == assessment["assessment_id"]
        with pytest.raises(CanonicalParserShadowReadinessError) as exc:
            get_shadow_consumer_readiness_assessment(db, str(uuid4()))
        assert exc.value.status_code == 404


def test_resolve_ready_but_flag_disabled_is_not_authorized(db_factory):
    with db_factory() as db:
        _assess_ready(db)
        resolution = resolve_shadow_consumer_readiness(
            db,
            settings_object=_readiness_policy(
                CANONICAL_PARSER_SHADOW_READINESS_ENABLED=False,
            ),
            evaluated_at=NOW,
        )
        assert resolution["status"] == "READY"
        assert resolution["resolved"] is True
        assert resolution["consumer_authorized"] is False
        assert resolution["consumer_connected"] is False


def test_resolve_ready_authorizes_only_with_both_manual_flags(db_factory):
    with db_factory() as db:
        _assess_ready(db)
        resolution = resolve_shadow_consumer_readiness(
            db,
            settings_object=_readiness_policy(),
            evaluated_at=NOW,
        )
        assert resolution["status"] == "READY"
        assert resolution["consumer_authorized"] is True
        assert resolution["automatic_execution"] is False
        assert resolution["live_execution"] is False


def test_resolve_expires_before_lease(db_factory):
    with db_factory() as db:
        policy = _readiness_policy(
            CANONICAL_PARSER_SHADOW_READINESS_VALIDITY_MINUTES=5,
        )
        _assess_ready(db, policy=policy)
        resolution = resolve_shadow_consumer_readiness(
            db,
            settings_object=policy,
            evaluated_at=NOW + timedelta(minutes=6),
        )
        assert resolution["status"] == "EXPIRED"
        assert resolution["consumer_authorized"] is False


def test_resolve_detects_policy_drift(db_factory):
    with db_factory() as db:
        _assess_ready(db)
        resolution = resolve_shadow_consumer_readiness(
            db,
            settings_object=_readiness_policy(
                CANONICAL_PARSER_SHADOW_READINESS_MIN_RUNS=4,
            ),
            evaluated_at=NOW,
        )
        assert resolution["status"] == "DRIFTED"
        assert "SHADOW_READINESS_POLICY_DRIFT" in resolution["reason_codes"]


def test_resolve_detects_assessment_evidence_tampering(db_factory):
    with db_factory() as db:
        _assess_ready(db)
        row = db.query(CanonicalParserShadowReadinessAssessment).one()
        row.evidence_snapshot = {"tampered": True}
        db.commit()
        resolution = resolve_shadow_consumer_readiness(
            db, settings_object=_readiness_policy(), evaluated_at=NOW
        )
        assert resolution["status"] == "DRIFTED"
        assert "SHADOW_READINESS_EVIDENCE_HASH_INVALID" in resolution["reason_codes"]


def test_resolve_detects_evidence_link_tampering(db_factory):
    with db_factory() as db:
        _assess_ready(db)
        link = db.query(CanonicalParserShadowReadinessEvidenceRun).first()
        link.evidence_snapshot = {"tampered": True}
        db.commit()
        resolution = resolve_shadow_consumer_readiness(
            db, settings_object=_readiness_policy(), evaluated_at=NOW
        )
        assert resolution["status"] == "DRIFTED"
        assert "SHADOW_READINESS_LINK_HASH_INVALID" in resolution["reason_codes"]


def test_resolve_fails_closed_after_lease_revocation(db_factory):
    with db_factory() as db:
        lease, _, _, _, _ = _assess_ready(db)
        revoke_shadow_runtime_lease(
            db,
            lease_id=lease["lease_id"],
            confirmation=f"{LEASE_REVOKE_PREFIX}:{lease['lease_id']}",
            reason="manual readiness interlock test",
            actor_label="m13-test",
            settings_object=_readiness_policy(),
            revoked_at=NOW + timedelta(minutes=1),
        )
        resolution = resolve_shadow_consumer_readiness(
            db,
            settings_object=_readiness_policy(),
            evaluated_at=NOW + timedelta(minutes=1),
        )
        assert resolution["resolved"] is False
        assert resolution["consumer_authorized"] is False
        assert resolution["status"] in {"UNASSESSED", "DRIFTED"}


def test_status_counts_assessment_decisions(db_factory):
    with db_factory() as db:
        _assess_ready(db)
        status = get_shadow_consumer_readiness_status(
            db, settings_object=_readiness_policy()
        )
        assert status["assessment_count"] == 1
        assert status["status_counts"]["READY"] == 1


def test_m13_models_are_registered_and_evidence_is_unique(db_factory):
    names = set(Base.metadata.tables)
    assert "canonical_parser_shadow_readiness_assessments" in names
    assert "canonical_parser_shadow_readiness_evidence_runs" in names
    assert (
        models.CanonicalParserShadowReadinessAssessment
        is CanonicalParserShadowReadinessAssessment
    )
    assert (
        models.CanonicalParserShadowReadinessEvidenceRun
        is CanonicalParserShadowReadinessEvidenceRun
    )
    with db_factory() as db:
        _assess_ready(db)
        original = db.query(CanonicalParserShadowReadinessEvidenceRun).first()
        duplicate = CanonicalParserShadowReadinessEvidenceRun(
            evidence_id=str(uuid4()),
            assessment_db_id=original.assessment_db_id,
            consumer_run_db_id=original.consumer_run_db_id,
            run_id=original.run_id,
            run_key=original.run_key,
            status=original.status,
            result_count=original.result_count,
            processed_count=original.processed_count,
            passed_count=original.passed_count,
            failed_count=original.failed_count,
            skipped_count=original.skipped_count,
            artifact_count=original.artifact_count,
            run_evidence_hash=original.run_evidence_hash,
            completed_at=original.completed_at,
            evidence_snapshot=original.evidence_snapshot,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


def test_m13_service_has_no_network_trade_live_or_worker_writes():
    path = Path(
        "backend/app/services/blockchain_parser_shadow_readiness_service.py"
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


def test_m13_service_not_imported_by_operational_pipelines():
    forbidden = []
    allowed = {
        "main.py",
        "blockchain_parser_shadow_readiness_service.py",
    }
    for path in Path("backend/app").rglob("*.py"):
        if path.name in allowed:
            continue
        if "blockchain_parser_shadow_readiness_service" in path.read_text(
            encoding="utf-8"
        ):
            forbidden.append(str(path))
    assert forbidden == []


def test_m13_api_routes_are_protected_and_registered_once(db_factory):
    counts = Counter()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            counts[(method, getattr(route, "path", ""))] += 1
    expected = {
        ("GET", "/integrity/parser-shadow-readiness/status"),
        ("GET", "/integrity/parser-shadow-readiness/preview"),
        ("POST", "/integrity/parser-shadow-readiness/assess"),
        (
            "GET",
            "/integrity/parser-shadow-readiness/assessments/{assessment_id}",
        ),
        ("GET", "/integrity/parser-shadow-readiness/resolve"),
    }
    for route in expected:
        assert counts[route] == 1
    client = _client(db_factory)
    try:
        assert (
            client.get("/integrity/parser-shadow-readiness/status").status_code
            == 401
        )
        response = client.get(
            "/integrity/parser-shadow-readiness/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["readiness_enabled"] is False
        post = client.post(
            "/integrity/parser-shadow-readiness/assess",
            headers={"X-Automation-Key": AUTOMATION_KEY},
            json={"confirmation": "anything"},
        )
        assert post.status_code == 409
        assert (
            post.json()["detail"]["code"]
            == "CANONICAL_PARSER_SHADOW_READINESS_DISABLED"
        )
    finally:
        app.dependency_overrides.clear()


def test_m13_migration_upgrade_downgrade_upgrade_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    path = Path(
        "alembic/versions/f3b7d9e2a614_add_shadow_consumer_readiness.py"
    )
    spec = importlib.util.spec_from_file_location("m13_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE canonical_parser_shadow_runtime_leases "
            "(id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE canonical_parser_shadow_consumer_runs "
            "(id INTEGER PRIMARY KEY)"
        )
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_shadow_readiness_assessments" in names
    assert "canonical_parser_shadow_readiness_evidence_runs" in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.downgrade()
    names = set(inspect(engine).get_table_names())
    assert "canonical_parser_shadow_readiness_assessments" not in names
    assert "canonical_parser_shadow_readiness_evidence_runs" not in names
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    assert (
        "canonical_parser_shadow_readiness_assessments"
        in inspect(engine).get_table_names()
    )
    engine.dispose()
