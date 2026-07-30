from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
    CanonicalParserGovernedLivePosition,
    CanonicalParserGovernedLivePositionAssessment,
    CanonicalParserLiveIncident,
    CanonicalParserLivePortfolioRiskAssessment,
    CanonicalParserLivePortfolioRiskPermit,
    CanonicalParserLivePortfolioRiskPermitEvent,
)
import backend.app.services.blockchain_parser_live_portfolio_risk_service as service

NOW = datetime(2026, 7, 29, 13, 0, tzinfo=timezone.utc)
WALLET = "11111111111111111111111111111111"
TOKEN_A = "22222222222222222222222222222222"
TOKEN_B = "33333333333333333333333333333333"


def settings_for_m42(**overrides):
    values = {
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ENABLED": True,
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ENFORCEMENT_ENABLED": True,
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ASSESSMENT_TTL_SECONDS": 60,
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_PERMIT_VALIDITY_MINUTES": 10,
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_TOTAL_EXPOSURE_SOL": 1.0,
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_PENDING_BUY_SOL": 1.0,
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_OPEN_POSITIONS": 5,
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_TOKEN_CONCENTRATION_PERCENT": 100.0,
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_REQUIRE_FRESH_POSITION_ASSESSMENT": True,
        "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_FAIL_ON_HIGH_INCIDENT": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close(); Base.metadata.drop_all(engine); engine.dispose()


def add_position(db, *, position_id="position-000000000000000000000000001", token=TOKEN_A, cost="0.010", value="0.012", fresh=True):
    row = CanonicalParserGovernedLivePosition(
        position_id=position_id[:36], position_key=("a" if token == TOKEN_A else "b")*64,
        scope="M39_GOVERNED_LIVE_POSITION_LEDGER", entry_settlement_db_id=1,
        entry_settlement_id="entry-0000000000000000000000000001"[:36], last_settlement_id="entry-0000000000000000000000000001"[:36],
        micro_live_permit_id="permit-000000000000000000000000001"[:36], decision_result_id="decision-00000000000000000000000001"[:36],
        wallet_address=WALLET, token_mint=token, status="OPEN", quantity_raw=Decimal("1000000"), cost_basis_sol=Decimal(cost),
        realized_proceeds_sol=Decimal("0"), realized_pnl_sol=Decimal("0"), high_watermark_value_sol=Decimal(value), high_watermark_roi_percent=Decimal("20"),
        exit_plan={}, position_snapshot={}, evidence_hash="c"*64, position_version=1, opened_at=NOW-timedelta(minutes=5), last_assessed_at=NOW, closed_at=None,
    )
    db.add(row); db.flush()
    assessment = CanonicalParserGovernedLivePositionAssessment(
        assessment_id=("assessment-"+position_id)[:36], assessment_key=("d" if token == TOKEN_A else "e")*64,
        scope="M40_GOVERNED_LIVE_POSITION_ASSESSMENT", position_db_id=row.id, position_id=row.position_id, status="HOLD",
        quoted_output_sol=Decimal(value), current_value_sol=Decimal(value), unrealized_pnl_sol=Decimal(value)-Decimal(cost), unrealized_roi_percent=Decimal("20"),
        high_watermark_value_sol=Decimal(value), high_watermark_roi_percent=Decimal("20"), trailing_drawdown_percent=Decimal("0"), price_impact_percent=Decimal("1"),
        sell_route_available=True, token_safety_status="SAFE", source_wallet_sell_detected=False, emergency_exit_requested=False,
        reason_codes=[], assessment_snapshot={}, evidence_hash="f"*64, actor_label="TEST", note=None, quote_observed_at=NOW,
        assessed_at=NOW, expires_at=NOW+timedelta(minutes=1) if fresh else NOW-timedelta(seconds=1),
    )
    db.add(assessment); db.commit(); return row


def assess_and_persist(db, *, token="m42-assess-001", **overrides):
    args = dict(wallet_address=WALLET, side="BUY", requested_token_mint=TOKEN_B, requested_budget_sol="0.005", as_of=NOW,
                idempotency_token=token, settings_object=settings_for_m42(), evaluated_at=NOW)
    args.update(overrides)
    preview = service.preview_live_portfolio_risk_assessment(db, **args)
    result = service.assess_live_portfolio_risk(db, **{k:v for k,v in args.items() if k != "evaluated_at"}, confirmation=preview["confirmation"], assessed_at=NOW)
    return preview, result


def issue_permit(db, assessment_id, *, token="m42-permit-001"):
    preview = service.preview_live_portfolio_risk_permit(db, assessment_id=assessment_id, validity_minutes=5, idempotency_token=token,
                                                         settings_object=settings_for_m42(), evaluated_at=NOW)
    result = service.issue_live_portfolio_risk_permit(db, assessment_id=assessment_id, validity_minutes=5, idempotency_token=token,
                                                       confirmation=preview["confirmation"], settings_object=settings_for_m42(), issued_at=NOW)
    return preview, result


def test_m42_flags_false_by_default():
    configured = Settings(_env_file=None, DATABASE_URL="sqlite+pysqlite:///:memory:", SOLANA_RPC_URL="https://api.mainnet-beta.solana.com", HELIUS_API_KEY="test")
    assert configured.CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ENABLED is False
    assert configured.CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ENFORCEMENT_ENABLED is False


def test_m42_models_and_migration_registered():
    for table in ("canonical_parser_live_portfolio_risk_assessments", "canonical_parser_live_portfolio_risk_permits", "canonical_parser_live_portfolio_risk_permit_events"):
        assert table in Base.metadata.tables
    config = Config("alembic.ini"); config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("e7b9c2d5f631").down_revision == "d6a8b1c4e520"
    assert scripts.get_heads() == ["c1f3a6b9d075"]


def test_aggregate_assessment_ready_with_fresh_position(db):
    add_position(db)
    preview, result = assess_and_persist(db)
    assert preview["status"] == "READY"
    assert result["open_position_count"] == 1
    assert result["current_value_sol"] == "0.012000000"
    assert db.query(CanonicalParserLivePortfolioRiskAssessment).count() == 1


def test_concentration_limit_blocks_new_buy(db):
    add_position(db)
    preview = service.preview_live_portfolio_risk_assessment(
        db, wallet_address=WALLET, side="BUY", requested_token_mint=TOKEN_A, requested_budget_sol="0.005", as_of=NOW,
        idempotency_token="m42-concentration", settings_object=settings_for_m42(CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_TOKEN_CONCENTRATION_PERCENT=60.0), evaluated_at=NOW,
    )
    assert preview["status"] == "BLOCKED"
    assert "TOKEN_CONCENTRATION_LIMIT_EXCEEDED" in preview["reason_codes"]


def test_stale_position_assessment_is_insufficient_data(db):
    add_position(db, fresh=False)
    preview = service.preview_live_portfolio_risk_assessment(
        db, wallet_address=WALLET, side="BUY", requested_token_mint=TOKEN_B, requested_budget_sol="0.005", as_of=NOW,
        idempotency_token="m42-stale-position", settings_object=settings_for_m42(), evaluated_at=NOW,
    )
    assert preview["status"] == "INSUFFICIENT_DATA"
    assert "STALE_POSITION_ASSESSMENT" in preview["reason_codes"]


def test_high_incident_blocks_buy_but_sell_can_reduce_risk(db):
    add_position(db)
    incident = CanonicalParserLiveIncident(
        incident_id="incident-00000000000000000000000001"[:36], incident_key="1"*64, scope="M41_LIVE_INCIDENT_RESPONSE",
        source_type="MANUAL", source_id="risk", category="RISK", severity="CRITICAL", status="OPEN", freeze_new_submissions=True,
        reason_codes=["RISK"], incident_snapshot={}, evidence_hash="2"*64, actor_label="TEST", note=None, detected_at=NOW,
        acknowledged_at=None, resolved_at=None, latest_event_sequence=1, latest_event_hash="3"*64,
    )
    db.add(incident); db.commit()
    buy = service.preview_live_portfolio_risk_assessment(db, wallet_address=WALLET, side="BUY", requested_token_mint=TOKEN_B,
        requested_budget_sol="0.005", as_of=NOW, idempotency_token="m42-incident-buy", settings_object=settings_for_m42(), evaluated_at=NOW)
    sell = service.preview_live_portfolio_risk_assessment(db, wallet_address=WALLET, side="SELL", requested_token_mint=TOKEN_A,
        requested_budget_sol="0", as_of=NOW, idempotency_token="m42-incident-sell", settings_object=settings_for_m42(), evaluated_at=NOW)
    assert buy["status"] == "BLOCKED"
    assert "ACTIVE_HIGH_SEVERITY_INCIDENT" in buy["reason_codes"]
    assert sell["status"] == "READY"


def test_permit_is_single_use_and_consumed_by_submission(db):
    add_position(db)
    _, assessment = assess_and_persist(db)
    _, permit = issue_permit(db, assessment["assessment_id"])
    validation = service.validate_portfolio_risk_permit_for_submission(
        db, permit_id=permit["permit_id"], side="BUY", token_mint=TOKEN_B, requested_budget_sol="0.005",
        settings_object=settings_for_m42(), evaluated_at=NOW,
    )
    assert validation["ready"] is True
    consumed = service.consume_portfolio_risk_permit(
        db, permit_id=permit["permit_id"], submission_id="submission-0000000000000000000001"[:36], side="BUY", token_mint=TOKEN_B,
        requested_budget_sol="0.005", settings_object=settings_for_m42(), consumed_at=NOW+timedelta(seconds=1),
    )
    db.commit()
    assert consumed["consumed"] is True
    row = db.query(CanonicalParserLivePortfolioRiskPermit).one()
    assert row.status == "CONSUMED"
    assert db.query(CanonicalParserLivePortfolioRiskPermitEvent).count() == 2
    second = service.validate_portfolio_risk_permit_for_submission(db, permit_id=permit["permit_id"], side="BUY", token_mint=TOKEN_B,
        requested_budget_sol="0.005", settings_object=settings_for_m42(), evaluated_at=NOW+timedelta(seconds=2))
    assert second["ready"] is False
    assert "M42_PORTFOLIO_RISK_PERMIT_NOT_ACTIVE" in second["reason_codes"]


def test_enforcement_requires_permit(db):
    result = service.validate_portfolio_risk_permit_for_submission(db, permit_id=None, side="BUY", token_mint=TOKEN_A,
        requested_budget_sol="0.001", settings_object=settings_for_m42(), evaluated_at=NOW)
    assert result["ready"] is False
    assert result["reason_codes"] == ["M42_PORTFOLIO_RISK_PERMIT_REQUIRED"]


def test_permit_can_be_revoked(db):
    add_position(db)
    _, assessment = assess_and_persist(db)
    _, permit = issue_permit(db, assessment["assessment_id"])
    result = service.revoke_live_portfolio_risk_permit(db, permit_id=permit["permit_id"],
        confirmation=f"{service.REVOKE_PREFIX}:{permit['permit_id']}:{permit['evidence_hash']}", reason="operator cancelled",
        settings_object=settings_for_m42(), revoked_at=NOW+timedelta(seconds=1))
    assert result["status"] == "REVOKED"


def test_m38_integration_and_openapi_safety():
    m38 = Path("backend/app/services/blockchain_parser_controlled_live_submission_service.py").read_text()
    assert "get_live_submission_incident_guard" in m38
    assert "validate_portfolio_risk_permit_for_submission" in m38
    assert "consume_portfolio_risk_permit" in m38
    schema = app.openapi()
    for method, path in {
        ("get", "/integrity/parser-live-portfolio-risk/status"),
        ("post", "/integrity/parser-live-portfolio-risk/assess"),
        ("post", "/integrity/parser-live-portfolio-risk/permit/issue"),
        ("get", "/integrity/parser-live-portfolio-risk/permits/{permit_id}"),
    }:
        assert method in schema["paths"][path]
    tree = ast.parse(Path(service.__file__).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "backend.app.services.solana_transaction_signer" not in imports
    assert "backend.app.services.live_copy_trading_engine" not in imports
