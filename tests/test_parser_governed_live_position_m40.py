from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.models.blockchain_integrity import (
    CanonicalParserGovernedLiveExitIntent,
    CanonicalParserGovernedLiveExitIntentEvent,
    CanonicalParserGovernedLivePosition,
    CanonicalParserGovernedLivePositionAssessment,
    CanonicalParserUnifiedDecisionResult,
    CanonicalParserUnifiedDecisionRun,
)
import backend.app.services.blockchain_parser_governed_live_position_service as service
import backend.app.services.blockchain_parser_micro_live_canary_service as m35
from tests.test_parser_live_onchain_settlement_m39 import settle_buy
from tests.test_parser_live_transaction_dry_run_m36 import NOW
from tests.test_parser_micro_live_canary_m35 import settings_for_m35


def settings_for_m40(**overrides):
    values = {
        "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_ENABLED": True,
        "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_QUOTE_AGE_SECONDS": 30,
        "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_ASSESSMENT_TTL_SECONDS": 30,
        "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_INTENT_VALIDITY_MINUTES": 10,
        "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_STOP_LOSS_PERCENT": 10.0,
        "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_TAKE_PROFIT_PERCENT": 25.0,
        "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_TRAILING_STOP_PERCENT": 8.0,
        "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_AGE_MINUTES": 1440,
        "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_EXIT_PRICE_IMPACT_PERCENT": 10.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close(); Base.metadata.drop_all(engine); engine.dispose()


def open_position(db, monkeypatch):
    _, settled, _ = settle_buy(db, monkeypatch)
    return db.scalar(select(CanonicalParserGovernedLivePosition).where(CanonicalParserGovernedLivePosition.position_id == settled["position_id"]))


def assess(db, position, *, quoted="0.008000000", token="m40-assess-001", **overrides):
    args = dict(position_id=position.position_id, quoted_output_sol=quoted, price_impact_percent=1,
                sell_route_available=True, token_safety_status="SAFE", source_wallet_sell_detected=False,
                emergency_exit_requested=False, quote_observed_at=NOW + timedelta(seconds=5),
                idempotency_token=token, settings_object=settings_for_m40(), evaluated_at=NOW + timedelta(seconds=5))
    args.update(overrides)
    preview = service.preview_governed_live_position_assessment(db, **args)
    result = service.assess_governed_live_position(
        db, **{k:v for k,v in args.items() if k != "evaluated_at"}, confirmation=preview["confirmation"], assessed_at=NOW + timedelta(seconds=5)
    )
    return preview, result


def issue_intent(db, assessment_id, *, token="m40-intent-001"):
    preview = service.preview_governed_live_exit_intent(
        db, assessment_id=assessment_id, percentage=100, validity_minutes=5,
        idempotency_token=token, settings_object=settings_for_m40(), evaluated_at=NOW + timedelta(seconds=6),
    )
    result = service.issue_governed_live_exit_intent(
        db, assessment_id=assessment_id, percentage=100, validity_minutes=5,
        idempotency_token=token, confirmation=preview["confirmation"], settings_object=settings_for_m40(), issued_at=NOW + timedelta(seconds=6),
    )
    return preview, result


def test_m40_flag_false_by_default():
    configured = Settings(_env_file=None, DATABASE_URL="sqlite+pysqlite:///:memory:", SOLANA_RPC_URL="https://api.mainnet-beta.solana.com", HELIUS_API_KEY="test")
    assert configured.CANONICAL_PARSER_GOVERNED_LIVE_POSITION_ENABLED is False


def test_m40_models_registered():
    for table in (
        "canonical_parser_governed_live_position_assessments",
        "canonical_parser_governed_live_exit_intents",
        "canonical_parser_governed_live_exit_intent_events",
    ):
        assert table in Base.metadata.tables


def test_m40_migration_is_consecutive_and_head():
    config = Config("alembic.ini"); config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("c5f7a0b3d419").down_revision == "b4e6f9a2c308"
    assert scripts.get_heads() == ["c5f7a0b3d419"]


def test_hold_assessment_without_trigger(db, monkeypatch):
    position = open_position(db, monkeypatch)
    preview, result = assess(db, position, quoted="0.010005000")
    assert preview["status"] == "HOLD"
    assert result["status"] == "HOLD"


def test_stop_loss_creates_exit_ready_assessment(db, monkeypatch):
    position = open_position(db, monkeypatch)
    preview, result = assess(db, position, quoted="0.008000000")
    assert preview["status"] == "EXIT_READY"
    assert "STOP_LOSS_TRIGGERED" in result["reason_codes"]
    assert db.query(CanonicalParserGovernedLivePositionAssessment).count() == 1


def test_sell_route_missing_blocks_even_emergency(db, monkeypatch):
    position = open_position(db, monkeypatch)
    preview = service.preview_governed_live_position_assessment(
        db, position_id=position.position_id, quoted_output_sol="0.008", price_impact_percent=1,
        sell_route_available=False, token_safety_status="UNSAFE", source_wallet_sell_detected=False,
        emergency_exit_requested=True, quote_observed_at=NOW + timedelta(seconds=5), idempotency_token="m40-no-route",
        settings_object=settings_for_m40(), evaluated_at=NOW + timedelta(seconds=5),
    )
    assert preview["status"] == "BLOCKED"
    assert "SELL_ROUTE_UNAVAILABLE" in preview["reason_codes"]


def test_stale_quote_is_insufficient_data(db, monkeypatch):
    position = open_position(db, monkeypatch)
    preview = service.preview_governed_live_position_assessment(
        db, position_id=position.position_id, quoted_output_sol="0.008", price_impact_percent=1,
        sell_route_available=True, token_safety_status="SAFE", source_wallet_sell_detected=False,
        emergency_exit_requested=False, quote_observed_at=NOW, idempotency_token="m40-stale-quote",
        settings_object=settings_for_m40(), evaluated_at=NOW + timedelta(minutes=2),
    )
    assert preview["status"] == "INSUFFICIENT_DATA"
    assert "QUOTE_STALE" in preview["reason_codes"]


def test_exit_intent_is_manual_bounded_and_audited(db, monkeypatch):
    position = open_position(db, monkeypatch)
    _, assessment = assess(db, position)
    preview, intent = issue_intent(db, assessment["assessment_id"])
    assert preview["ready"] is True
    assert intent["status"] == "ACTIVE"
    assert intent["quantity_raw"] == "1000000"
    assert intent["micro_live_permit_id"] == position.micro_live_permit_id
    assert db.query(CanonicalParserGovernedLiveExitIntentEvent).count() == 1


def test_only_one_active_intent_per_position(db, monkeypatch):
    position = open_position(db, monkeypatch)
    _, assessment = assess(db, position)
    issue_intent(db, assessment["assessment_id"])
    second = service.preview_governed_live_exit_intent(
        db, assessment_id=assessment["assessment_id"], percentage=50, validity_minutes=5,
        idempotency_token="m40-intent-second", settings_object=settings_for_m40(), evaluated_at=NOW + timedelta(seconds=7),
    )
    assert second["status"] == "BLOCKED"
    assert "ACTIVE_INTENT_EXISTS" in second["reason_codes"]


def test_governed_exit_allows_sell_after_entry_decision_expiry_and_consumes_intent(db, monkeypatch):
    position = open_position(db, monkeypatch)
    _, assessment = assess(db, position)
    _, intent = issue_intent(db, assessment["assessment_id"])
    run = db.scalar(select(CanonicalParserUnifiedDecisionRun))
    run.valid_until = NOW - timedelta(minutes=1)
    run.completed_at = NOW - timedelta(hours=1)
    decision = db.scalar(select(CanonicalParserUnifiedDecisionResult))
    decision.decision_hash = m35._calculate_decision_hash(decision)
    db.commit()
    preview = m35.preview_micro_live_canary_simulation(
        db, permit_id=position.micro_live_permit_id, decision_result_id=position.decision_result_id,
        side="SELL", market_price_sol="0.000000001", requested_budget_sol=0,
        idempotency_token="m40-m35-exit", governed_exit_intent_id=intent["intent_id"],
        settings_object=settings_for_m35(), evaluated_at=NOW + timedelta(seconds=7),
    )
    assert preview["status"] == "READY"
    assert "DECISION_EXPIRED" not in preview["reason_codes"]
    result = m35.simulate_micro_live_canary(
        db, permit_id=position.micro_live_permit_id, decision_result_id=position.decision_result_id,
        side="SELL", market_price_sol="0.000000001", requested_budget_sol=0,
        idempotency_token="m40-m35-exit", governed_exit_intent_id=intent["intent_id"],
        confirmation=preview["confirmation"], settings_object=settings_for_m35(), simulated_at=NOW + timedelta(seconds=7),
    )
    assert result["status"] == "READY"
    row = db.scalar(select(CanonicalParserGovernedLiveExitIntent).where(CanonicalParserGovernedLiveExitIntent.intent_id == intent["intent_id"]))
    assert row.status == "CONSUMED"
    assert row.consumed_at is not None


def test_revoke_intent(db, monkeypatch):
    position = open_position(db, monkeypatch)
    _, assessment = assess(db, position)
    _, intent = issue_intent(db, assessment["assessment_id"])
    row = db.scalar(select(CanonicalParserGovernedLiveExitIntent).where(CanonicalParserGovernedLiveExitIntent.intent_id == intent["intent_id"]))
    confirmation = f"{service.REVOKE_PREFIX}:{row.intent_id}:{row.latest_event_hash}"
    result = service.revoke_governed_live_exit_intent(db, intent_id=row.intent_id, confirmation=confirmation, reason="operator cancel", revoked_at=NOW + timedelta(seconds=7))
    assert result["status"] == "REVOKED"
    assert db.query(CanonicalParserGovernedLiveExitIntentEvent).count() == 2


def test_m40_has_no_automatic_execution_calls():
    source = Path(service.__file__).read_text()
    tree = ast.parse(source)
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "send_signed_transaction_base64" not in called
    assert "get_order" not in called
    assert "simulate_transaction_base64" not in called
    assert "Trade" not in source
