from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserMicroLiveCanaryPermit,
    CanonicalParserMicroLiveCanaryPermitEvent,
    CanonicalParserMicroLiveCanarySimulation,
    CanonicalParserPaperOperationalAssessment,
    CanonicalParserUnifiedDecisionResult,
    CanonicalParserUnifiedDecisionRun,
)
from backend.app.models.live_platform_config import LivePlatformConfig
from backend.app.models.live_trading_policy import LiveTradingPolicy
from backend.app.models.paper_account import PaperAccount
import backend.app.services.blockchain_parser_micro_live_canary_service as service

NOW = datetime(2026, 7, 28, 22, 0, tzinfo=timezone.utc)


def settings_for_m35(**overrides):
    values = {
        "CANONICAL_PARSER_MICRO_LIVE_CANARY_ENABLED": True,
        "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_VALIDITY_MINUTES": 15,
        "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_TOTAL_BUDGET_SOL": 0.05,
        "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_ORDER_BUDGET_SOL": 0.01,
        "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_ORDER_COUNT": 3,
        "CANONICAL_PARSER_MICRO_LIVE_CANARY_MIN_ASSESSMENT_REMAINING_MINUTES": 2,
        "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_DECISION_AGE_MINUTES": 15,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def seed_context(db: Session, *, kill_switch=True, mode="DISABLED", armed=False, assessment_status="READY"):
    account = PaperAccount(
        name="m35-account",
        status="ACTIVE",
        starting_balance_sol=10,
        cash_balance_sol=10,
        realized_pnl_sol=0,
        max_position_size_sol=1,
        max_open_positions=10,
        daily_loss_limit_sol=5,
    )
    db.add(account)
    db.flush()
    assessment = CanonicalParserPaperOperationalAssessment(
        assessment_id="60000000-0000-0000-0000-000000000001",
        assessment_key="1" * 64,
        scope="PAPER_OPERATIONAL_READINESS",
        status=assessment_status,
        paper_account_id=account.id,
        calibration_campaign_db_id=None,
        calibration_campaign_id=None,
        settled_count=20,
        reconciliation_required_count=0,
        stale_reservation_count=0,
        budget_drift_count=0,
        reliability_score=100,
        calibration_gap_percent=5,
        policy_version="m34-test",
        policy_hash="2" * 64,
        policy_snapshot={},
        summary={},
        reason_codes=[],
        evidence_hash="3" * 64,
        actor_label="TEST",
        note=None,
        window_started_at=NOW - timedelta(hours=1),
        window_ended_at=NOW,
        completed_at=NOW,
        valid_until=NOW + timedelta(hours=1),
    )
    db.add(assessment)
    live_policy = LiveTradingPolicy(
        name="default",
        mode=mode,
        kill_switch=kill_switch,
        stream_execution_enabled=False,
        source_wallets=[],
    )
    db.add(live_policy)
    platform = LivePlatformConfig(
        name="default",
        token_safety_enabled=True,
        token_safety_fail_closed=True,
    )
    if armed:
        platform.live_armed_until = NOW + timedelta(minutes=10)
    db.add(platform)
    run = CanonicalParserUnifiedDecisionRun(
        run_id="61000000-0000-0000-0000-000000000001",
        run_key="4" * 64,
        scope="SHADOW_DECISION_ONLY",
        status="COMPLETED",
        source_trade_count=1,
        source_token_count=1,
        source_wallet_count=2,
        qualified_wallet_count=2,
        result_count=1,
        approve_count=1,
        review_count=0,
        reject_count=0,
        insufficient_data_count=0,
        policy_version="m31-test",
        policy_hash="5" * 64,
        policy_snapshot={},
        parameters={},
        summary={},
        safety={},
        evidence_hash="6" * 64,
        actor_label="TEST",
        note=None,
        data_start_at=NOW,
        data_end_at=NOW,
        started_at=NOW,
        completed_at=NOW,
        valid_until=NOW + timedelta(hours=1),
        technical_metadata={},
    )
    db.add(run)
    db.flush()
    decision = CanonicalParserUnifiedDecisionResult(
        result_id="62000000-0000-0000-0000-000000000001",
        run_db_id=run.id,
        sequence=1,
        decision="APPROVE",
        token_mint="TokenMint111111111111111111111111111111111111",
        source_trade_ids=[1],
        source_signatures=["sig"],
        source_event_at=NOW,
        raw_wallet_count=2,
        qualified_wallet_count=2,
        independent_cluster_count=2,
        follower_wallet_count=0,
        leader_wallet="Wallet1111111111111111111111111111111111111",
        signal_score=82,
        confidence_score=80,
        uncertainty_score=20,
        requested_size_sol=0.01,
        approved_size_sol=0.01,
        token_safety_status="SAFE",
        timing_status="COPYABLE",
        market_regime="UNKNOWN",
        confidence_calibration_status="BASELINE_HEURISTIC_UNCALIBRATED",
        reason_codes=[],
        positive_factors=[],
        evidence_snapshot={},
        exit_plan={"status": "PLANNED", "normal_exit": "SOURCE_SELL"},
        counterfactuals=[],
        decision_hash="7" * 64,
    )
    decision.decision_hash = service._calculate_decision_hash(decision)
    db.add(decision)
    db.commit()
    return assessment, live_policy, platform, decision


def issue(db, assessment, settings_object=None, now=NOW):
    settings_object = settings_object or settings_for_m35()
    preview = service.preview_micro_live_canary_permit(
        db,
        operational_assessment_id=assessment.assessment_id,
        validity_minutes=10,
        total_budget_sol=0.03,
        max_order_budget_sol=0.01,
        max_order_count=3,
        settings_object=settings_object,
        evaluated_at=now,
    )
    permit = service.issue_micro_live_canary_permit(
        db,
        operational_assessment_id=assessment.assessment_id,
        validity_minutes=10,
        total_budget_sol=0.03,
        max_order_budget_sol=0.01,
        max_order_count=3,
        confirmation=preview["confirmation"],
        settings_object=settings_object,
        issued_at=now,
    )
    return preview, permit


def test_m35_flag_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_MICRO_LIVE_CANARY_ENABLED is False


def test_m35_models_registered():
    assert "canonical_parser_micro_live_canary_permits" in Base.metadata.tables
    assert "canonical_parser_micro_live_canary_permit_events" in Base.metadata.tables
    assert "canonical_parser_micro_live_canary_simulations" in Base.metadata.tables


def test_m35_migration_is_consecutive():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    assert ScriptDirectory.from_config(config).get_revision("d0a2b5c8e964").down_revision == "c9f1a4b7d853"


def test_m35_service_does_not_import_signer_live_engine_or_network_clients():
    path = Path("backend/app/services/blockchain_parser_micro_live_canary_service.py")
    tree = ast.parse(path.read_text())
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    forbidden = ("solana_transaction_signer", "live_copy_trading_engine", "jupiter_swap_client", "solana_rpc", "httpx")
    assert not any(any(marker in name for marker in forbidden) for name in imports)
    targets = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "execute_order" not in targets and "simulate_transaction_base64" not in targets


def test_permit_preview_requires_ready_assessment(db):
    assessment, *_ = seed_context(db, assessment_status="REVIEW")
    with pytest.raises(service.CanonicalParserMicroLiveCanaryError) as exc:
        service.preview_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.03, max_order_budget_sol=0.01, max_order_count=3, settings_object=settings_for_m35(), evaluated_at=NOW)
    assert exc.value.code == "MICRO_LIVE_ASSESSMENT_NOT_READY"


def test_permit_preview_requires_kill_switch_engaged(db):
    assessment, *_ = seed_context(db, kill_switch=False)
    with pytest.raises(service.CanonicalParserMicroLiveCanaryError) as exc:
        service.preview_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.03, max_order_budget_sol=0.01, max_order_count=3, settings_object=settings_for_m35(), evaluated_at=NOW)
    assert exc.value.code == "MICRO_LIVE_CONTROL_STATE_UNSAFE"


def test_permit_preview_blocks_armed_platform(db):
    assessment, *_ = seed_context(db, armed=True)
    with pytest.raises(service.CanonicalParserMicroLiveCanaryError):
        service.preview_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.03, max_order_budget_sol=0.01, max_order_count=3, settings_object=settings_for_m35(), evaluated_at=NOW)



def test_permit_preview_requires_token_safety_fail_closed(db):
    assessment, _, platform, _ = seed_context(db)
    platform.token_safety_enabled = False
    db.commit()
    with pytest.raises(service.CanonicalParserMicroLiveCanaryError) as exc:
        service.preview_micro_live_canary_permit(
            db,
            operational_assessment_id=assessment.assessment_id,
            validity_minutes=10,
            total_budget_sol=0.03,
            max_order_budget_sol=0.01,
            max_order_count=3,
            settings_object=settings_for_m35(),
            evaluated_at=NOW,
        )
    assert exc.value.code == "MICRO_LIVE_CONTROL_STATE_UNSAFE"


def test_permit_preview_rejects_live_runtime_flags(db):
    assessment, *_ = seed_context(db)
    with pytest.raises(service.CanonicalParserMicroLiveCanaryError) as exc:
        service.preview_micro_live_canary_permit(
            db,
            operational_assessment_id=assessment.assessment_id,
            validity_minutes=10,
            total_budget_sol=0.03,
            max_order_budget_sol=0.01,
            max_order_count=3,
            settings_object=settings_for_m35(RUN_LIVE_STREAM_WORKER=True),
            evaluated_at=NOW,
        )
    assert exc.value.code == "MICRO_LIVE_CONTROL_STATE_UNSAFE"


def test_permit_preview_respects_existing_live_policy_limits(db):
    assessment, live_policy, *_ = seed_context(db)
    live_policy.max_order_size_sol = 0.005
    db.commit()
    with pytest.raises(service.CanonicalParserMicroLiveCanaryError) as exc:
        service.preview_micro_live_canary_permit(
            db,
            operational_assessment_id=assessment.assessment_id,
            validity_minutes=10,
            total_budget_sol=0.03,
            max_order_budget_sol=0.01,
            max_order_count=3,
            settings_object=settings_for_m35(),
            evaluated_at=NOW,
        )
    assert exc.value.code == "MICRO_LIVE_POLICY_ORDER_LIMIT"


def test_simulation_requires_nonempty_idempotency_token(db):
    assessment, _, _, decision = seed_context(db)
    _, permit = issue(db, assessment)
    with pytest.raises(service.CanonicalParserMicroLiveCanaryError) as exc:
        service.preview_micro_live_canary_simulation(
            db,
            permit_id=permit["permit_id"],
            decision_result_id=decision.result_id,
            side="BUY",
            market_price_sol="0.000000000123456789",
            requested_budget_sol=0.01,
            idempotency_token="short",
            settings_object=settings_for_m35(),
            evaluated_at=NOW,
        )
    assert exc.value.code == "MICRO_LIVE_IDEMPOTENCY_TOKEN_INVALID"

def test_issue_requires_enabled_flag(db):
    assessment, *_ = seed_context(db)
    preview = service.preview_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.03, max_order_budget_sol=0.01, max_order_count=3, settings_object=settings_for_m35(), evaluated_at=NOW)
    with pytest.raises(service.CanonicalParserMicroLiveCanaryError) as exc:
        service.issue_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.03, max_order_budget_sol=0.01, max_order_count=3, confirmation=preview["confirmation"], settings_object=settings_for_m35(CANONICAL_PARSER_MICRO_LIVE_CANARY_ENABLED=False), issued_at=NOW)
    assert exc.value.code == "MICRO_LIVE_DISABLED"


def test_issue_requires_exact_confirmation_and_creates_event(db):
    assessment, *_ = seed_context(db)
    preview = service.preview_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.03, max_order_budget_sol=0.01, max_order_count=3, settings_object=settings_for_m35(), evaluated_at=NOW)
    with pytest.raises(service.CanonicalParserMicroLiveCanaryError):
        service.issue_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.03, max_order_budget_sol=0.01, max_order_count=3, confirmation="wrong", settings_object=settings_for_m35(), issued_at=NOW)
    result = service.issue_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.03, max_order_budget_sol=0.01, max_order_count=3, confirmation=preview["confirmation"], settings_object=settings_for_m35(), issued_at=NOW)
    assert result["resolved_status"] == "ACTIVE"
    assert db.scalar(select(CanonicalParserMicroLiveCanaryPermitEvent)).event_type == "ISSUED"


def test_issue_is_idempotent(db):
    assessment, *_ = seed_context(db)
    _, first = issue(db, assessment)
    _, second = issue(db, assessment)
    assert first["permit_id"] == second["permit_id"]
    assert db.query(CanonicalParserMicroLiveCanaryPermit).count() == 1


def test_simulation_preview_ready_and_never_authorizes_live(db):
    assessment, _, _, decision = seed_context(db)
    _, permit = issue(db, assessment)
    preview = service.preview_micro_live_canary_simulation(db, permit_id=permit["permit_id"], decision_result_id=decision.result_id, side="BUY", market_price_sol=0.001, requested_budget_sol=0.01, idempotency_token="simulate-12345678", settings_object=settings_for_m35(), evaluated_at=NOW + timedelta(minutes=1))
    assert preview["status"] == "READY"
    assert preview["evidence"]["safety"]["transaction_sent"] is False
    assert preview["evidence"]["safety"]["live_execution_authorized"] is False


def test_simulation_blocks_token_not_safe(db):
    assessment, _, _, decision = seed_context(db)
    _, permit = issue(db, assessment)
    decision.token_safety_status = "UNSAFE"
    decision.decision_hash = service._calculate_decision_hash(decision)
    db.commit()
    preview = service.preview_micro_live_canary_simulation(db, permit_id=permit["permit_id"], decision_result_id=decision.result_id, side="BUY", market_price_sol=0.001, requested_budget_sol=0.01, idempotency_token="simulate-unsafe", settings_object=settings_for_m35(), evaluated_at=NOW + timedelta(minutes=1))
    assert preview["status"] == "BLOCKED"
    assert "TOKEN_NOT_SAFE" in preview["reason_codes"]


def test_simulation_detects_policy_drift(db):
    assessment, live_policy, _, decision = seed_context(db)
    _, permit = issue(db, assessment)
    live_policy.max_order_size_sol = 0.09
    db.commit()
    preview = service.preview_micro_live_canary_simulation(db, permit_id=permit["permit_id"], decision_result_id=decision.result_id, side="BUY", market_price_sol=0.001, requested_budget_sol=0.01, idempotency_token="simulate-drift", settings_object=settings_for_m35(), evaluated_at=NOW + timedelta(minutes=1))
    assert preview["status"] == "BLOCKED"
    assert "LIVE_POLICY_DRIFT" in preview["reason_codes"]


def test_simulate_persists_metadata_and_consumes_only_simulation_budget(db):
    assessment, _, _, decision = seed_context(db)
    _, permit = issue(db, assessment)
    preview = service.preview_micro_live_canary_simulation(db, permit_id=permit["permit_id"], decision_result_id=decision.result_id, side="BUY", market_price_sol=0.001, requested_budget_sol=0.01, idempotency_token="simulate-ready-1", settings_object=settings_for_m35(), evaluated_at=NOW + timedelta(minutes=1))
    result = service.simulate_micro_live_canary(db, permit_id=permit["permit_id"], decision_result_id=decision.result_id, side="BUY", market_price_sol=0.001, requested_budget_sol=0.01, idempotency_token="simulate-ready-1", confirmation=preview["confirmation"], settings_object=settings_for_m35(), simulated_at=NOW + timedelta(minutes=1))
    assert result["status"] == "READY"
    stored = db.scalar(select(CanonicalParserMicroLiveCanaryPermit))
    assert str(stored.simulated_budget_sol) == "0.010000000"
    assert stored.simulated_order_count == 1
    assert db.query(CanonicalParserMicroLiveCanarySimulation).count() == 1


def test_simulate_is_idempotent(db):
    assessment, _, _, decision = seed_context(db)
    _, permit = issue(db, assessment)
    kwargs = dict(permit_id=permit["permit_id"], decision_result_id=decision.result_id, side="BUY", market_price_sol=0.001, requested_budget_sol=0.01, idempotency_token="same-simulation", settings_object=settings_for_m35(), evaluated_at=NOW + timedelta(minutes=1))
    preview = service.preview_micro_live_canary_simulation(db, **kwargs)
    first = service.simulate_micro_live_canary(db, **{k:v for k,v in kwargs.items() if k != "evaluated_at"}, confirmation=preview["confirmation"], simulated_at=NOW + timedelta(minutes=1))
    second = service.simulate_micro_live_canary(db, **{k:v for k,v in kwargs.items() if k != "evaluated_at"}, confirmation=preview["confirmation"], simulated_at=NOW + timedelta(minutes=1))
    assert first["simulation_id"] == second["simulation_id"]
    assert db.scalar(select(CanonicalParserMicroLiveCanaryPermit)).simulated_order_count == 1


def test_permit_exhausts_after_bounded_simulations(db):
    assessment, _, _, decision = seed_context(db)
    small = settings_for_m35(CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_ORDER_COUNT=1)
    preview = service.preview_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.01, max_order_budget_sol=0.01, max_order_count=1, settings_object=small, evaluated_at=NOW)
    permit = service.issue_micro_live_canary_permit(db, operational_assessment_id=assessment.assessment_id, validity_minutes=10, total_budget_sol=0.01, max_order_budget_sol=0.01, max_order_count=1, confirmation=preview["confirmation"], settings_object=small, issued_at=NOW)
    sim_preview = service.preview_micro_live_canary_simulation(db, permit_id=permit["permit_id"], decision_result_id=decision.result_id, side="BUY", market_price_sol=0.001, requested_budget_sol=0.01, idempotency_token="exhaust-sim", settings_object=small, evaluated_at=NOW + timedelta(minutes=1))
    service.simulate_micro_live_canary(db, permit_id=permit["permit_id"], decision_result_id=decision.result_id, side="BUY", market_price_sol=0.001, requested_budget_sol=0.01, idempotency_token="exhaust-sim", confirmation=sim_preview["confirmation"], settings_object=small, simulated_at=NOW + timedelta(minutes=1))
    assert db.scalar(select(CanonicalParserMicroLiveCanaryPermit)).status == "EXHAUSTED"


def test_revoke_is_manual_and_audited(db):
    assessment, *_ = seed_context(db)
    _, permit_payload = issue(db, assessment)
    stored = db.scalar(select(CanonicalParserMicroLiveCanaryPermit))
    confirmation = f"{service.MICRO_LIVE_REVOKE_PREFIX}:{stored.permit_id}:{stored.latest_event_hash}"
    result = service.revoke_micro_live_canary_permit(db, permit_id=stored.permit_id, confirmation=confirmation, reason="manual stop", revoked_at=NOW + timedelta(minutes=1))
    assert result["status"] == "REVOKED"
    events = list(db.scalars(select(CanonicalParserMicroLiveCanaryPermitEvent).order_by(CanonicalParserMicroLiveCanaryPermitEvent.sequence)))
    assert events[-1].event_type == "REVOKED"


def test_m35_openapi_operations_and_automation_header():
    schema = app.openapi()
    required = {
        ("get", "/integrity/parser-micro-live-canary/status"),
        ("get", "/integrity/parser-micro-live-canary/permit-preview"),
        ("post", "/integrity/parser-micro-live-canary/issue"),
        ("post", "/integrity/parser-micro-live-canary/revoke"),
        ("get", "/integrity/parser-micro-live-canary/simulation-preview"),
        ("post", "/integrity/parser-micro-live-canary/simulate"),
        ("get", "/integrity/parser-micro-live-canary/permits/{permit_id}"),
        ("get", "/integrity/parser-micro-live-canary/simulations/{simulation_id}"),
        ("get", "/integrity/parser-micro-live-canary/resolve"),
    }
    for method, path in required:
        operation = schema["paths"][path][method]
        parameters = operation.get("parameters", [])
        assert any(p.get("name") == "X-Automation-Key" and p.get("in") == "header" for p in parameters)


def test_m35_api_rejects_missing_automation_key(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        assert client.get("/integrity/parser-micro-live-canary/status").status_code in {401, 403, 503}
    finally:
        app.dependency_overrides.clear()
