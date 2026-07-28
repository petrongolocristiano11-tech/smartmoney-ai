import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.core.config import settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserUnifiedDecisionResult,
    CanonicalParserUnifiedDecisionRun,
    CanonicalParserUnifiedDecisionWalletEvidence,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_order import PaperOrder
from backend.app.models.paper_position import PaperPosition
from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
from backend.app.models.trade import Trade
from backend.app.models.wallet_edge import WalletEdge
import backend.app.services.blockchain_parser_unified_decision_service as M31

NOW = datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)
AUTOMATION_KEY = "m" * 32
TOKEN = "T" * 44
TOKEN_2 = "U" * 44


def policy_settings(**overrides):
    values = {
        "CANONICAL_PARSER_UNIFIED_DECISION_ENABLED": True,
        "CANONICAL_PARSER_UNIFIED_DECISION_LOOKBACK_MINUTES": 1440,
        "CANONICAL_PARSER_UNIFIED_DECISION_MAX_SOURCE_TRADES": 1000,
        "CANONICAL_PARSER_UNIFIED_DECISION_MAX_RESULTS": 100,
        "CANONICAL_PARSER_UNIFIED_DECISION_VALIDITY_MINUTES": 30,
        "CANONICAL_PARSER_UNIFIED_DECISION_WALLET_FRESHNESS_MINUTES": 1440,
        "CANONICAL_PARSER_UNIFIED_DECISION_TOKEN_FRESHNESS_MINUTES": 30,
        "CANONICAL_PARSER_UNIFIED_DECISION_MIN_QUALIFIED_WALLETS": 2,
        "CANONICAL_PARSER_UNIFIED_DECISION_MIN_INDEPENDENT_CLUSTERS": 2,
        "CANONICAL_PARSER_UNIFIED_DECISION_MIN_APPROVE_SCORE": 72.0,
        "CANONICAL_PARSER_UNIFIED_DECISION_MIN_REVIEW_SCORE": 55.0,
        "CANONICAL_PARSER_UNIFIED_DECISION_MAX_COPY_LATENCY_SECONDS": 180,
        "CANONICAL_PARSER_UNIFIED_DECISION_MAX_STALE_SECONDS": 900,
        "CANONICAL_PARSER_UNIFIED_DECISION_MIN_TOKEN_LIQUIDITY_USD": 25000.0,
        "CANONICAL_PARSER_UNIFIED_DECISION_MAX_TOKEN_RISK_SCORE": 35,
        "CANONICAL_PARSER_UNIFIED_DECISION_MAX_TOP_HOLDER_PERCENT": 25.0,
        "CANONICAL_PARSER_UNIFIED_DECISION_MIN_EDGE_STRENGTH": 60.0,
        "CANONICAL_PARSER_UNIFIED_DECISION_FOLLOWER_DELAY_SECONDS": 30,
        "CANONICAL_PARSER_UNIFIED_DECISION_MAX_SIZE_SOL": 0.05,
        "CANONICAL_PARSER_UNIFIED_DECISION_STOP_LOSS_PERCENT": 15.0,
        "CANONICAL_PARSER_UNIFIED_DECISION_TAKE_PROFIT_PERCENT": 30.0,
        "CANONICAL_PARSER_UNIFIED_DECISION_MAX_HOLD_MINUTES": 240,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db(db_factory):
    session = db_factory()
    try:
        yield session
    finally:
        session.close()


def add_wallet(
    db,
    address: str,
    *,
    now: datetime = NOW,
    eligible: bool = True,
    suspicious: bool = False,
    score: float = 92.0,
):
    row = DiscoveredWallet(
        wallet_address=address,
        smart_score=score,
        ranking_score=score,
        roi_percent=45.0,
        win_rate_percent=70.0,
        profit_loss_sol=5.0,
        reliable_positions=20,
        last_swap_at=now - timedelta(minutes=1),
        swaps_24h=12,
        swaps_7d=40,
        activity_score=90.0,
        activity_classification="ATTIVO",
        activity_eligible=eligible,
        activity_reasons=[],
        activity_calculated_at=now - timedelta(minutes=2),
        quality_score=90.0,
        quality_classification="SOSPETTO" if suspicious else "COPIABILE",
        quality_eligible=eligible and not suspicious,
        quality_reasons=["SUSPICIOUS"] if suspicious else [],
        quality_calculated_at=now - timedelta(minutes=2),
        quality_sample_swaps_7d=40,
        meaningful_swaps_7d=35,
        buy_sell_balance_score_7d=80.0 if not suspicious else 5.0,
        top_token_concentration_7d=0.35 if not suspicious else 0.99,
        promotion_status="PROMOSSO",
        promotion_eligible=eligible,
        promotion_reasons=[],
        promotion_calculated_at=now - timedelta(minutes=2),
        latest_backtest_run_id=str(uuid4()),
        backtest_score=90.0,
        backtest_total_return_percent=35.0,
        backtest_net_pnl_sol=4.0,
        backtest_win_rate_percent=68.0,
        backtest_profit_factor=2.2,
        backtest_max_drawdown_percent=12.0,
        backtest_completed_positions=30,
        backtest_open_positions=1,
        backtest_execution_coverage_percent=95.0,
        backtest_jupiter_status="READY",
        backtest_jupiter_compatibility_percent=95.0,
        backtest_data_sufficient=eligible,
        backtest_data_sufficiency_score=95.0,
        backtest_history_span_days=45.0,
        backtest_matched_sell_ratio_percent=95.0,
        exitability_gate_status="READY",
        exitability_gate_score=92.0,
        exitability_gate_eligible=eligible,
        exitability_gate_reasons=[],
        exitability_gate_calculated_at=now - timedelta(minutes=2),
        eligible=eligible,
        eligibility_reasons=[],
        status="UPDATED",
    )
    db.add(row)
    db.flush()
    return row


def add_trade(
    db,
    address: str,
    *,
    token: str = TOKEN,
    event_at: datetime = NOW - timedelta(seconds=30),
    sol_amount: float = 0.08,
    raw_json: str | None = None,
):
    row = Trade(
        signature=f"sig-{uuid4()}",
        wallet_address=address,
        side="BUY",
        source="HELIUS",
        token_mint=token,
        token_amount=1000.0,
        sol_amount=sol_amount,
        fee=0.00001,
        success=True,
        block_time=event_at,
        raw_json=raw_json,
    )
    db.add(row)
    db.flush()
    return row


def add_safe_token(db, token: str = TOKEN, *, fetched_at: datetime = NOW - timedelta(minutes=1), unsafe=False):
    row = TokenSafetySnapshot(
        token_mint=token,
        liquidity_usd=100000.0 if not unsafe else 1000.0,
        market_cap_usd=500000.0,
        volume_24h_usd=200000.0,
        top_holder_percent=10.0 if not unsafe else 80.0,
        risk_score=10 if not unsafe else 90,
        honeypot=unsafe,
        mint_authority_enabled=unsafe,
        freeze_authority_enabled=unsafe,
        rugged=unsafe,
        rugcheck_passed=not unsafe,
        source="ONCHAIN+DEXSCREENER+JUPITER",
        reasons=[],
        raw_payload={"provider_errors": {}},
        fetched_at=fetched_at,
    )
    db.add(row)
    db.flush()
    return row


def seed_approve(db, *, now: datetime = NOW):
    add_wallet(db, "wallet-a", now=now)
    add_wallet(db, "wallet-b", now=now)
    add_trade(db, "wallet-a", event_at=now - timedelta(seconds=40), sol_amount=0.08)
    add_trade(db, "wallet-b", event_at=now - timedelta(seconds=20), sol_amount=0.06)
    add_safe_token(db, fetched_at=now - timedelta(minutes=1))
    db.commit()


def run_m31(db, **kwargs):
    return M31.run_unified_decision_shadow_validation(
        db,
        confirmation=M31.UNIFIED_DECISION_CONFIRMATION,
        settings_object=kwargs.pop("settings_object", policy_settings()),
        evaluated_at=kwargs.pop("evaluated_at", NOW),
        **kwargs,
    )


def test_policy_is_fail_closed_and_metadata_only():
    policy = M31._policy_snapshot(policy_settings())
    assert policy["manual_run_only"] is True
    assert policy["external_requests_allowed"] is False
    assert policy["paper_execution_connected"] is False
    assert policy["paper_order_writes"] is False
    assert policy["paper_position_writes"] is False
    assert policy["permit_consumption_connected"] is False
    assert policy["live_execution_authorized"] is False


def test_run_disabled_by_default_guard(db):
    with pytest.raises(M31.CanonicalParserUnifiedDecisionError) as caught:
        M31.run_unified_decision_shadow_validation(
            db,
            confirmation=M31.UNIFIED_DECISION_CONFIRMATION,
            settings_object=policy_settings(CANONICAL_PARSER_UNIFIED_DECISION_ENABLED=False),
            evaluated_at=NOW,
        )
    assert caught.value.code == "UNIFIED_DECISION_DISABLED"


def test_confirmation_required(db):
    with pytest.raises(M31.CanonicalParserUnifiedDecisionError) as caught:
        M31.run_unified_decision_shadow_validation(
            db,
            confirmation="NO",
            settings_object=policy_settings(),
            evaluated_at=NOW,
        )
    assert caught.value.code == "UNIFIED_DECISION_CONFIRMATION_REQUIRED"


def test_approve_uses_qualified_independent_wallets(db):
    seed_approve(db)
    payload = run_m31(db)
    assert payload["approve_count"] == 1
    result = payload["results"][0]
    assert result["decision"] == "APPROVE"
    assert result["qualified_wallet_count"] == 2
    assert result["independent_cluster_count"] == 2
    assert result["token_safety_status"] == "SAFE"
    assert result["timing_status"] == "COPYABLE"
    assert result["approved_size_sol"] != "0.000000000"
    assert result["exit_plan"]["metadata_only"] is True


def test_strong_wallet_edge_prevents_false_consensus(db):
    seed_approve(db)
    db.add(WalletEdge(source_wallet="wallet-a", target_wallet="wallet-b", token_mint=TOKEN, strength=95.0))
    db.commit()
    payload = run_m31(db)
    result = payload["results"][0]
    assert result["decision"] == "REJECT"
    assert result["independent_cluster_count"] == 1
    assert "INDEPENDENT_CLUSTERS_BELOW_MINIMUM" in result["reason_codes"]


def test_low_strength_edge_does_not_merge_independent_wallets(db):
    seed_approve(db)
    db.add(WalletEdge(source_wallet="wallet-a", target_wallet="wallet-b", token_mint=TOKEN, strength=20.0))
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["independent_cluster_count"] == 2
    assert result["decision"] == "APPROVE"


def test_follower_role_is_audited(db):
    add_wallet(db, "wallet-a")
    add_wallet(db, "wallet-b")
    add_wallet(db, "wallet-c")
    add_trade(db, "wallet-a", event_at=NOW - timedelta(seconds=50))
    add_trade(db, "wallet-b", event_at=NOW - timedelta(seconds=10))
    add_trade(db, "wallet-c", event_at=NOW - timedelta(seconds=25))
    db.add(WalletEdge(source_wallet="wallet-a", target_wallet="wallet-b", token_mint=TOKEN, strength=95.0))
    add_safe_token(db)
    db.commit()
    result = run_m31(db)["results"][0]
    roles = {row["wallet_address"]: row["role"] for row in result["wallet_evidence"]}
    assert roles["wallet-a"] in {"EARLY_LEADER", "CONFIRMING_LEADER"}
    assert roles["wallet-b"] == "LATE_FOLLOWER"
    assert result["follower_wallet_count"] == 1


def test_unsafe_token_is_rejected(db):
    add_wallet(db, "wallet-a")
    add_wallet(db, "wallet-b")
    add_trade(db, "wallet-a")
    add_trade(db, "wallet-b")
    add_safe_token(db, unsafe=True)
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["decision"] == "REJECT"
    assert result["token_safety_status"] == "UNSAFE"
    assert "TOKEN_HONEYPOT" in result["reason_codes"]


def test_missing_token_evidence_is_insufficient(db):
    add_wallet(db, "wallet-a")
    add_wallet(db, "wallet-b")
    add_trade(db, "wallet-a")
    add_trade(db, "wallet-b")
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["decision"] == "INSUFFICIENT_DATA"
    assert "TOKEN_SAFETY_SNAPSHOT_MISSING" in result["reason_codes"]


def test_expired_token_evidence_is_insufficient(db):
    seed_approve(db)
    token = db.scalar(select(TokenSafetySnapshot).where(TokenSafetySnapshot.token_mint == TOKEN))
    token.fetched_at = NOW - timedelta(hours=2)
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["decision"] == "INSUFFICIENT_DATA"
    assert "TOKEN_SAFETY_SNAPSHOT_EXPIRED" in result["reason_codes"]


def test_late_copy_is_rejected_even_for_good_wallets(db):
    add_wallet(db, "wallet-a")
    add_wallet(db, "wallet-b")
    add_trade(db, "wallet-a", event_at=NOW - timedelta(minutes=5))
    add_trade(db, "wallet-b", event_at=NOW - timedelta(minutes=4))
    add_safe_token(db)
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["timing_status"] == "LATE"
    assert result["decision"] == "REJECT"


def test_missing_wallet_evidence_is_insufficient(db):
    add_trade(db, "unknown-a")
    add_trade(db, "unknown-b")
    add_safe_token(db)
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["decision"] == "INSUFFICIENT_DATA"
    assert "DISCOVERED_WALLET_NOT_FOUND" in result["reason_codes"]


def test_expired_wallet_evidence_is_insufficient(db):
    old = NOW - timedelta(days=2)
    add_wallet(db, "wallet-a", now=old)
    add_wallet(db, "wallet-b", now=old)
    add_trade(db, "wallet-a")
    add_trade(db, "wallet-b")
    add_safe_token(db)
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["decision"] == "INSUFFICIENT_DATA"
    assert "WALLET_EVIDENCE_EXPIRED" in result["reason_codes"]


def test_potential_copytrader_bait_is_rejected(db):
    add_wallet(db, "wallet-a", suspicious=True)
    add_wallet(db, "wallet-b")
    add_trade(db, "wallet-a")
    add_trade(db, "wallet-b")
    add_safe_token(db)
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["decision"] in {"REJECT", "INSUFFICIENT_DATA"}
    assert "POTENTIAL_COPYTRADER_BAIT" in result["reason_codes"]


def test_invalid_raw_json_fails_closed(db):
    add_wallet(db, "wallet-a")
    add_wallet(db, "wallet-b")
    add_trade(db, "wallet-a", raw_json="not-json")
    add_trade(db, "wallet-b")
    add_safe_token(db)
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["decision"] == "INSUFFICIENT_DATA"
    assert "DATA_CONFLICT_RAW_JSON_INVALID" in result["reason_codes"]


def test_future_wallet_snapshot_fails_closed(db):
    add_wallet(db, "wallet-a", now=NOW + timedelta(minutes=10))
    add_wallet(db, "wallet-b")
    add_trade(db, "wallet-a")
    add_trade(db, "wallet-b")
    add_safe_token(db)
    db.commit()
    result = run_m31(db)["results"][0]
    assert result["decision"] == "INSUFFICIENT_DATA"
    assert "WALLET_EVIDENCE_FROM_FUTURE" in result["reason_codes"]


def test_uncertainty_budget_caps_size(db):
    seed_approve(db)
    result = run_m31(db)["results"][0]
    assert float(result["requested_size_sol"]) == pytest.approx(0.07)
    assert 0 < float(result["approved_size_sol"]) <= 0.05
    assert result["evidence_snapshot"]["sizing"]["metadata_only"] is True


def test_counterfactuals_never_create_orders(db):
    seed_approve(db)
    result = run_m31(db)["results"][0]
    assert len(result["counterfactuals"]) == 5
    assert all(row["creates_order"] is False for row in result["counterfactuals"])


def test_idempotent_run_does_not_duplicate_metadata(db):
    seed_approve(db)
    first = run_m31(db)
    second = run_m31(db)
    assert first["run_id"] == second["run_id"]
    assert second["idempotent_replay"] is True
    assert db.scalar(select(func.count(CanonicalParserUnifiedDecisionRun.id))) == 1
    assert db.scalar(select(func.count(CanonicalParserUnifiedDecisionResult.id))) == 1
    assert db.scalar(select(func.count(CanonicalParserUnifiedDecisionWalletEvidence.id))) == 2


def test_decision_hash_is_deterministic(db):
    seed_approve(db)
    preview_a = M31.preview_unified_decision(db, settings_object=policy_settings(), evaluated_at=NOW)
    preview_b = M31.preview_unified_decision(db, settings_object=policy_settings(), evaluated_at=NOW)
    assert preview_a["results"][0]["decision_hash"] == preview_b["results"][0]["decision_hash"]


def test_run_does_not_write_operational_tables(db):
    seed_approve(db)
    db.add(PaperAccount(name="paper-safe", starting_balance_sol=10.0, cash_balance_sol=10.0, status="ACTIVE"))
    db.commit()
    before = {
        "trade": db.scalar(select(func.count(Trade.id))),
        "order": db.scalar(select(func.count(PaperOrder.id))),
        "position": db.scalar(select(func.count(PaperPosition.id))),
        "account": db.scalar(select(func.count(PaperAccount.id))),
    }
    run_m31(db)
    after = {
        "trade": db.scalar(select(func.count(Trade.id))),
        "order": db.scalar(select(func.count(PaperOrder.id))),
        "position": db.scalar(select(func.count(PaperPosition.id))),
        "account": db.scalar(select(func.count(PaperAccount.id))),
    }
    assert after == before


def test_resolve_and_get_run(db):
    seed_approve(db)
    created = run_m31(db)
    fetched = M31.get_unified_decision_run(db, created["run_id"])
    resolved = M31.resolve_unified_decision(db, evaluated_at=NOW)
    assert fetched["evidence_hash"] == created["evidence_hash"]
    assert resolved["resolved"] is True
    assert resolved["run_id"] == created["run_id"]


def test_resolve_expired_returns_false(db):
    seed_approve(db)
    run_m31(db)
    resolved = M31.resolve_unified_decision(db, evaluated_at=NOW + timedelta(hours=1))
    assert resolved["resolved"] is False
    assert "UNIFIED_DECISION_CURRENT_RUN_NOT_FOUND" in resolved["reason_codes"]


def test_get_missing_run_returns_404_error(db):
    with pytest.raises(M31.CanonicalParserUnifiedDecisionError) as caught:
        M31.get_unified_decision_run(db, str(uuid4()))
    assert caught.value.status_code == 404


def test_policy_bounds_are_enforced(db):
    with pytest.raises(M31.CanonicalParserUnifiedDecisionError) as caught:
        run_m31(db, lookback_minutes=2000, settings_object=policy_settings(CANONICAL_PARSER_UNIFIED_DECISION_LOOKBACK_MINUTES=100))
    assert caught.value.code == "UNIFIED_DECISION_LOOKBACK_ABOVE_MAXIMUM"


def test_multiple_tokens_have_stable_sequence(db):
    seed_approve(db)
    add_trade(db, "wallet-a", token=TOKEN_2, event_at=NOW - timedelta(seconds=10))
    add_trade(db, "wallet-b", token=TOKEN_2, event_at=NOW - timedelta(seconds=5))
    add_safe_token(db, token=TOKEN_2)
    db.commit()
    payload = run_m31(db)
    assert [row["sequence"] for row in payload["results"]] == [1, 2]
    assert payload["results"][0]["token_mint"] == TOKEN_2


def test_api_routes_require_automation_key(db_factory, monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_UNIFIED_DECISION_ENABLED", True)

    def override_db():
        session = db_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        assert client.get("/integrity/parser-unified-decision/status").status_code == 401
        response = client.get(
            "/integrity/parser-unified-decision/status",
            headers={"X-Automation-Key": AUTOMATION_KEY},
        )
        assert response.status_code == 200
        assert response.json()["safety"]["paper_execution_connected"] is False
    finally:
        app.dependency_overrides.clear()


def test_openapi_contains_exact_m31_operations():
    schema = app.openapi()
    expected = {
        ("get", "/integrity/parser-unified-decision/status"),
        ("get", "/integrity/parser-unified-decision/preview"),
        ("post", "/integrity/parser-unified-decision/run"),
        ("get", "/integrity/parser-unified-decision/runs/{run_id}"),
        ("get", "/integrity/parser-unified-decision/resolve"),
    }
    actual = {
        (method, path)
        for path, operations in schema["paths"].items()
        for method in operations
        if path.startswith("/integrity/parser-unified-decision/")
    }
    assert actual == expected
    for method, path in expected:
        parameters = schema["paths"][path][method].get("parameters", [])
        assert any(item.get("name") == "X-Automation-Key" for item in parameters)


def test_service_has_no_forbidden_operational_imports_or_calls():
    service_path = Path("backend/app/services/blockchain_parser_unified_decision_service.py")
    tree = ast.parse(service_path.read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden_import_fragments = {
        "paper_trading_engine",
        "paper_autopilot_engine",
        "live_trading_engine",
        "jupiter_swap_client",
        "solana_rpc",
    }
    assert not any(fragment in name for fragment in forbidden_import_fragments for name in imported)
    forbidden_calls = {"create_order", "execute_trade", "send_transaction", "consume_permit"}
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert forbidden_calls.isdisjoint(calls)


def test_m31_models_are_registered():
    tables = Base.metadata.tables
    assert "canonical_parser_unified_decision_runs" in tables
    assert "canonical_parser_unified_decision_results" in tables
    assert "canonical_parser_unified_decision_wallet_evidence" in tables


def test_migration_is_consecutive_from_m30():
    text = Path("alembic/versions/f2c8a6d1e735_add_unified_decision_shadow_validation.py").read_text()
    assert 'revision: str = "f2c8a6d1e735"' in text
    assert 'down_revision: str | Sequence[str] | None = "e3b8d5f1a942"' in text


def test_status_reports_real_counts(db):
    seed_approve(db)
    run_m31(db)
    status = M31.get_unified_decision_status(db, settings_object=policy_settings(), evaluated_at=NOW)
    assert status["run_count"] == 1
    assert status["decision_counts"]["APPROVE"] == 1
    assert status["latest_run_current"] is True
