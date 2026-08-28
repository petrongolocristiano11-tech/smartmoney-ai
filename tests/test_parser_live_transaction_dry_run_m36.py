from __future__ import annotations

import ast
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
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
    CanonicalParserIsolatedSignerProfile,
    CanonicalParserIsolatedSignerProfileEvent,
    CanonicalParserLiveTransactionDryRun,
    CanonicalParserMicroLiveCanaryPermit,
    CanonicalParserMicroLiveCanarySimulation,
    CanonicalParserPaperOperationalAssessment,
    CanonicalParserUnifiedDecisionResult,
    CanonicalParserUnifiedDecisionRun,
)
from backend.app.models.live_platform_config import LivePlatformConfig
from backend.app.models.live_trading_policy import LiveTradingPolicy
from backend.app.models.paper_account import PaperAccount
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
from backend.app.services.blockchain_parser_micro_live_canary_service import (
    _live_policy_snapshot as m35_live_policy_snapshot,
    _platform_snapshot as m35_platform_snapshot,
)
from backend.app.services.jupiter_swap_client import JupiterOrderResult
from backend.app.services.solana_rpc import SolanaRpcClient
import backend.app.services.blockchain_parser_live_transaction_dry_run_service as service

NOW = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)
WALLET = service._base58_encode(bytes([1]) * 32)
TOKEN = service._base58_encode(bytes([2]) * 32)
PROGRAM = service._base58_encode(bytes([3]) * 32)
BLOCKHASH = bytes([4]) * 32


def settings_for_m36(**overrides):
    values = {
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENABLED": True,
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_JUPITER_BUILD_ENABLED": True,
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_RPC_ENABLED": True,
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_PROFILE_VALIDITY_MINUTES": 60,
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_TRANSACTION_BYTES": 1232,
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_REQUIRED_SIGNERS": 1,
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_PROGRAMS": 24,
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_SIMULATION_LOGS": 20,
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENVELOPE_TTL_SECONDS": 60,
        "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ALLOW_ADDRESS_LOOKUP_TABLES": False,
        "RUN_LIVE_STREAM_WORKER": False,
        "RUN_LIVE_POSITION_MONITOR": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def shortvec(value: int) -> bytes:
    result = bytearray()
    current = value
    while True:
        byte = current & 0x7F
        current >>= 7
        if current:
            byte |= 0x80
        result.append(byte)
        if not current:
            return bytes(result)


def make_transaction(
    *,
    wallet: str = WALLET,
    token: str = TOKEN,
    program: str = PROGRAM,
    versioned: bool = False,
    signed: bool = False,
    with_lookup: bool = False,
) -> str:
    wallet_raw = service._base58_decode(wallet)
    token_raw = service._base58_decode(token)
    program_raw = service._base58_decode(program)
    message = bytearray()
    if versioned:
        message.append(0x80)
    message.extend(bytes([1, 0, 1]))
    message.extend(shortvec(3))
    message.extend(wallet_raw + token_raw + program_raw)
    message.extend(BLOCKHASH)
    message.extend(shortvec(1))
    message.extend(bytes([2]))
    message.extend(shortvec(2))
    message.extend(bytes([0, 1]))
    message.extend(shortvec(1))
    message.extend(b"\x01")
    if versioned:
        message.extend(shortvec(1 if with_lookup else 0))
        if with_lookup:
            message.extend(bytes([5]) * 32)
            message.extend(shortvec(1))
            message.extend(bytes([0]))
            message.extend(shortvec(0))
    signature = bytes([9]) * 64 if signed else bytes(64)
    raw = shortvec(1) + signature + bytes(message)
    return base64.b64encode(raw).decode("ascii")


def make_v1_transaction(
    *,
    wallet: str = WALLET,
    token: str = TOKEN,
    program: str = PROGRAM,
    signed: bool = False,
    config_mask: int = 0x07,
) -> str:
    wallet_raw = service._base58_decode(wallet)
    token_raw = service._base58_decode(token)
    program_raw = service._base58_decode(program)
    raw = bytearray()
    raw.append(0x81)
    raw.extend(bytes([1, 0, 1]))
    raw.extend(int(config_mask).to_bytes(4, "little"))
    raw.extend(BLOCKHASH)
    raw.extend(bytes([1]))
    raw.extend(bytes([3]))
    raw.extend(wallet_raw + token_raw + program_raw)
    if config_mask & 0x03:
        raw.extend((50_000).to_bytes(8, "little"))
    if config_mask & (1 << 2):
        raw.extend((200_000).to_bytes(4, "little"))
    if config_mask & (1 << 3):
        raw.extend((0).to_bytes(4, "little"))
    if config_mask & (1 << 4):
        raw.extend((32 * 1024).to_bytes(4, "little"))
    raw.extend(bytes([2, 2]))
    raw.extend((1).to_bytes(2, "little"))
    raw.extend(bytes([0, 1]))
    raw.extend(b"\x01")
    raw.extend(bytes([9]) * 64 if signed else bytes(64))
    return base64.b64encode(bytes(raw)).decode("ascii")


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


def seed_context(db: Session, *, sim_status="READY"):
    account = PaperAccount(
        name="m36-account",
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
        assessment_id="70000000-0000-0000-0000-000000000001",
        assessment_key="1" * 64,
        scope="PAPER_OPERATIONAL_READINESS",
        status="READY",
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
        mode="DISABLED",
        kill_switch=True,
        stream_execution_enabled=False,
        source_wallets=[],
        max_slippage_bps=300,
        max_price_impact_percent=5,
    )
    platform = LivePlatformConfig(
        name="default",
        token_safety_enabled=True,
        token_safety_fail_closed=True,
    )
    db.add_all([live_policy, platform])
    run = CanonicalParserUnifiedDecisionRun(
        run_id="71000000-0000-0000-0000-000000000001",
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
        result_id="72000000-0000-0000-0000-000000000001",
        run_db_id=run.id,
        sequence=1,
        decision="APPROVE",
        token_mint=TOKEN,
        source_trade_ids=[1],
        source_signatures=["sig"],
        source_event_at=NOW,
        raw_wallet_count=2,
        qualified_wallet_count=2,
        independent_cluster_count=2,
        follower_wallet_count=0,
        leader_wallet=WALLET,
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
    db.add(decision)
    db.flush()
    permit = CanonicalParserMicroLiveCanaryPermit(
        permit_id="73000000-0000-0000-0000-000000000001",
        permit_key="8" * 64,
        operational_assessment_db_id=assessment.id,
        operational_assessment_id=assessment.assessment_id,
        assessment_evidence_hash=assessment.evidence_hash,
        scope="MICRO_LIVE_GOVERNANCE_SIMULATION_ONLY",
        status="ACTIVE",
        requested_validity_minutes=30,
        total_budget_sol=0.03,
        max_order_budget_sol=0.01,
        max_order_count=3,
        simulated_budget_sol=0.01,
        simulated_order_count=1,
        live_policy_snapshot=m35_live_policy_snapshot(live_policy),
        live_platform_snapshot=m35_platform_snapshot(platform),
        policy_version="m35-test",
        policy_hash="9" * 64,
        policy_snapshot={},
        actor_label="TEST",
        note=None,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash="a" * 64,
        technical_metadata={},
    )
    db.add(permit)
    db.flush()
    evidence = {"safe": True, "simulation": "m35"}
    simulation = CanonicalParserMicroLiveCanarySimulation(
        simulation_id="74000000-0000-0000-0000-000000000001",
        simulation_key="b" * 64,
        permit_db_id=permit.id,
        permit_id=permit.permit_id,
        decision_result_db_id=decision.id,
        decision_result_id=decision.result_id,
        decision_hash=decision.decision_hash,
        side="BUY",
        status=sim_status,
        token_mint=TOKEN,
        requested_budget_sol=0.01,
        simulated_budget_sol=0.01,
        market_price_sol=0.001,
        reason_codes=[],
        evidence_snapshot=evidence,
        evidence_hash=calculate_payload_hash(evidence),
        actor_label="TEST",
        note=None,
        simulated_at=NOW,
    )
    db.add(simulation)
    db.commit()
    return live_policy, platform, permit, simulation


def issue_profile(db: Session, *, programs=None, settings_object=None):
    settings_object = settings_object or settings_for_m36()
    programs = programs or [PROGRAM]
    preview = service.preview_isolated_signer_profile(
        db,
        wallet_address=WALLET,
        validity_minutes=30,
        allowed_program_ids=programs,
        max_transaction_bytes=1232,
        max_required_signers=1,
        allow_address_lookup_tables=False,
        settings_object=settings_object,
        evaluated_at=NOW,
    )
    return service.issue_isolated_signer_profile(
        db,
        wallet_address=WALLET,
        validity_minutes=30,
        allowed_program_ids=programs,
        max_transaction_bytes=1232,
        max_required_signers=1,
        allow_address_lookup_tables=False,
        confirmation=preview["confirmation"],
        settings_object=settings_object,
        issued_at=NOW,
    )


def run_kwargs(profile_id: str, simulation_id: str, **overrides):
    values = {
        "signer_profile_id": profile_id,
        "micro_live_simulation_id": simulation_id,
        "transaction_source": "JUPITER_ORDER",
        "unsigned_transaction_base64": make_transaction(),
        "input_mint": service.WRAPPED_SOL_MINT,
        "output_mint": TOKEN,
        "amount_raw": 10_000_000,
        "jupiter_request_id": "request-m36",
        "jupiter_router": "jupiter",
        "jupiter_price_impact_percent": 1,
        "jupiter_slippage_bps": 100,
        "idempotency_token": "m36-idempotency-123",
    }
    values.update(overrides)
    return values


class PassingRpc:
    def simulate_unsigned_transaction_base64(self, transaction):
        return {"success": True, "error": None, "units_consumed": 12345, "logs": ["ok"]}


class FailingRpc:
    def simulate_unsigned_transaction_base64(self, transaction):
        return {"success": False, "error": {"InstructionError": [0, "x"]}, "units_consumed": 100, "logs": ["failed"]}


class UnavailableRpc:
    def simulate_unsigned_transaction_base64(self, transaction):
        raise RuntimeError("rpc down")


class FakeJupiter:
    def get_order(self, **kwargs):
        return JupiterOrderResult(
            raw={},
            request_id="request-built",
            transaction=make_transaction(),
            in_amount=kwargs["amount_raw"],
            out_amount=1000,
            slippage_bps=kwargs["slippage_bps"],
            router="jupiter",
            price_impact_percent=1.0,
            last_valid_block_height="123",
        )


def test_m36_flags_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENABLED is False
    assert configured.CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_RPC_ENABLED is False
    assert configured.CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_JUPITER_BUILD_ENABLED is False


def test_m36_models_registered():
    assert "canonical_parser_isolated_signer_profiles" in Base.metadata.tables
    assert "canonical_parser_isolated_signer_profile_events" in Base.metadata.tables
    assert "canonical_parser_live_transaction_dry_runs" in Base.metadata.tables


def test_m36_migration_is_consecutive():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    revision = ScriptDirectory.from_config(config).get_revision("e1b3c6d9f075")
    assert revision.down_revision == "d0a2b5c8e964"


def test_parser_reads_legacy_unsigned_transaction():
    result = service.inspect_unsigned_solana_transaction(make_transaction())
    assert result["transaction_format"] == "LEGACY"
    assert result["all_signature_slots_zero"] is True
    assert result["required_signers"] == [WALLET]
    assert result["program_ids"] == [PROGRAM]
    assert TOKEN in result["static_account_keys"]


def test_parser_reads_v0_without_lookup_table():
    result = service.inspect_unsigned_solana_transaction(make_transaction(versioned=True))
    assert result["transaction_format"] == "V0"
    assert result["address_lookup_count"] == 0


def test_parser_reads_v1_with_transaction_config():
    result = service.inspect_unsigned_solana_transaction(make_v1_transaction())
    assert result["transaction_format"] == "V1"
    assert result["required_signers"] == [WALLET]
    assert result["program_ids"] == [PROGRAM]
    assert result["address_lookup_count"] == 0
    assert result["all_signature_slots_zero"] is True
    assert result["transaction_config"]["priority_fee_lamports"] == 50_000
    assert result["transaction_config"]["compute_unit_limit"] == 200_000


def test_solders_029_decodes_v1_transaction_fixture():
    from solders.message import MessageV1
    from solders.transaction import VersionedTransaction

    transaction = VersionedTransaction.from_bytes(
        base64.b64decode(make_v1_transaction(), validate=True)
    )
    assert isinstance(transaction.message, MessageV1)


def test_parser_rejects_v1_partial_priority_fee_mask():
    with pytest.raises(
        service.CanonicalParserLiveTransactionDryRunError
    ) as exc:
        service.inspect_unsigned_solana_transaction(
            make_v1_transaction(config_mask=0x01)
        )
    assert exc.value.code == "M36_TRANSACTION_INVALID"


def test_parser_rejects_invalid_base64():
    with pytest.raises(service.CanonicalParserLiveTransactionDryRunError) as exc:
        service.inspect_unsigned_solana_transaction("not base64")
    assert exc.value.code == "M36_TRANSACTION_BASE64_INVALID"


def test_parser_marks_existing_signature():
    result = service.inspect_unsigned_solana_transaction(make_transaction(signed=True))
    assert result["all_signature_slots_zero"] is False


def test_unsigned_rpc_uses_fail_closed_simulation_options():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": {"err": None, "logs": ["ok"], "unitsConsumed": 7}}})

    client = SolanaRpcClient(rpc_url="https://rpc.test", transport=httpx.MockTransport(handler))
    result = client.simulate_unsigned_transaction_base64("dGVzdA==")
    options = captured["params"][1]
    assert captured["method"] == "simulateTransaction"
    assert options["sigVerify"] is False
    assert options["replaceRecentBlockhash"] is True
    assert result["success"] is True


def test_profile_preview_and_issue(db):
    seed_context(db)
    preview = service.preview_isolated_signer_profile(
        db,
        wallet_address=WALLET,
        validity_minutes=30,
        allowed_program_ids=[PROGRAM],
        max_transaction_bytes=1232,
        max_required_signers=1,
        allow_address_lookup_tables=False,
        settings_object=settings_for_m36(),
        evaluated_at=NOW,
    )
    assert preview["ready"] is True
    row = issue_profile(db)
    assert row["status"] == "ACTIVE"
    assert db.query(CanonicalParserIsolatedSignerProfileEvent).count() == 1


def test_profile_issue_requires_enabled_flag(db):
    seed_context(db)
    preview = service.preview_isolated_signer_profile(
        db,
        wallet_address=WALLET,
        validity_minutes=30,
        allowed_program_ids=[PROGRAM],
        max_transaction_bytes=1232,
        max_required_signers=1,
        allow_address_lookup_tables=False,
        settings_object=settings_for_m36(),
        evaluated_at=NOW,
    )
    with pytest.raises(service.CanonicalParserLiveTransactionDryRunError) as exc:
        service.issue_isolated_signer_profile(
            db,
            wallet_address=WALLET,
            validity_minutes=30,
            allowed_program_ids=[PROGRAM],
            max_transaction_bytes=1232,
            max_required_signers=1,
            allow_address_lookup_tables=False,
            confirmation=preview["confirmation"],
            settings_object=settings_for_m36(CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENABLED=False),
            issued_at=NOW,
        )
    assert exc.value.code == "M36_DISABLED"


def test_profile_issue_is_idempotent(db):
    seed_context(db)
    first = issue_profile(db)
    second = issue_profile(db)
    assert first["profile_id"] == second["profile_id"]
    assert db.query(CanonicalParserIsolatedSignerProfile).count() == 1


def test_profile_revoke(db):
    seed_context(db)
    issued = issue_profile(db)
    row = db.scalar(select(CanonicalParserIsolatedSignerProfile))
    result = service.revoke_isolated_signer_profile(
        db,
        profile_id=issued["profile_id"],
        confirmation=f"{service.SIGNER_PROFILE_REVOKE_PREFIX}:{issued['profile_id']}:{row.latest_event_hash}",
        reason="manual revoke",
        revoked_at=NOW + timedelta(minutes=1),
    )
    assert result["status"] == "REVOKED"
    assert db.query(CanonicalParserIsolatedSignerProfileEvent).count() == 2


def test_profile_rejects_lookup_tables_when_policy_disallows(db):
    seed_context(db)
    with pytest.raises(service.CanonicalParserLiveTransactionDryRunError) as exc:
        service.preview_isolated_signer_profile(
            db,
            wallet_address=WALLET,
            validity_minutes=30,
            allowed_program_ids=[PROGRAM],
            max_transaction_bytes=1232,
            max_required_signers=1,
            allow_address_lookup_tables=True,
            settings_object=settings_for_m36(),
            evaluated_at=NOW,
        )
    assert exc.value.code == "M36_ADDRESS_LOOKUP_TABLES_DISABLED"


def test_build_preview_uses_jupiter_without_signing(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    result = service.preview_jupiter_transaction_build(
        db,
        signer_profile_id=profile["profile_id"],
        micro_live_simulation_id=simulation.simulation_id,
        amount_raw=None,
        slippage_bps=100,
        idempotency_token="build-idempotency",
        settings_object=settings_for_m36(),
        evaluated_at=NOW + timedelta(minutes=1),
        jupiter_client=FakeJupiter(),
    )
    assert result["status"] == "BUILT"
    assert result["amount_raw"] == 10_000_000
    assert result["safety"]["transaction_signed"] is False
    assert result["safety"]["transaction_sent"] is False


def test_build_preview_rejects_disabled_builder(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    with pytest.raises(service.CanonicalParserLiveTransactionDryRunError) as exc:
        service.preview_jupiter_transaction_build(
            db,
            signer_profile_id=profile["profile_id"],
            micro_live_simulation_id=simulation.simulation_id,
            amount_raw=None,
            slippage_bps=100,
            idempotency_token="build-idempotency",
            settings_object=settings_for_m36(CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_JUPITER_BUILD_ENABLED=False),
            evaluated_at=NOW + timedelta(minutes=1),
            jupiter_client=FakeJupiter(),
        )
    assert exc.value.code == "M36_JUPITER_BUILD_DISABLED"


def test_dry_run_ready_with_jupiter_provenance_and_rpc(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id)
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    result = service.run_live_transaction_dry_run(
        db,
        **kwargs,
        run_rpc_simulation=True,
        confirmation=preview["confirmation"],
        settings_object=settings_for_m36(),
        prepared_at=NOW + timedelta(minutes=1),
        rpc_client=PassingRpc(),
    )
    assert result["status"] == "READY"
    assert result["rpc_simulation_status"] == "PASSED"
    assert result["signing_envelope"]["eligible_for_external_signing"] is True
    assert result["signing_envelope"]["signing_authorized_by_backend"] is False


def test_dry_run_failed_rpc_is_blocked(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id)
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    result = service.run_live_transaction_dry_run(
        db, **kwargs, run_rpc_simulation=True, confirmation=preview["confirmation"], settings_object=settings_for_m36(), prepared_at=NOW + timedelta(minutes=1), rpc_client=FailingRpc()
    )
    assert result["status"] == "BLOCKED"
    assert "RPC_SIMULATION_FAILED" in result["reason_codes"]


def test_dry_run_unavailable_rpc_is_insufficient(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id)
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    result = service.run_live_transaction_dry_run(
        db, **kwargs, run_rpc_simulation=True, confirmation=preview["confirmation"], settings_object=settings_for_m36(), prepared_at=NOW + timedelta(minutes=1), rpc_client=UnavailableRpc()
    )
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["rpc_simulation_status"] == "UNAVAILABLE"


def test_dry_run_rpc_disabled_is_review(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id)
    disabled = settings_for_m36(CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_RPC_ENABLED=False)
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=disabled, evaluated_at=NOW + timedelta(minutes=1))
    result = service.run_live_transaction_dry_run(
        db, **kwargs, run_rpc_simulation=True, confirmation=preview["confirmation"], settings_object=disabled, prepared_at=NOW + timedelta(minutes=1), rpc_client=PassingRpc()
    )
    assert result["status"] == "REVIEW"
    assert result["rpc_simulation_status"] == "UNAVAILABLE"


def test_provided_transaction_never_becomes_ready(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    kwargs = run_kwargs(
        profile["profile_id"],
        simulation.simulation_id,
        transaction_source="PROVIDED_TRANSACTION",
        jupiter_request_id=None,
        jupiter_router=None,
        jupiter_price_impact_percent=None,
        jupiter_slippage_bps=None,
    )
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    result = service.run_live_transaction_dry_run(
        db, **kwargs, run_rpc_simulation=True, confirmation=preview["confirmation"], settings_object=settings_for_m36(), prepared_at=NOW + timedelta(minutes=1), rpc_client=PassingRpc()
    )
    assert result["status"] == "REVIEW"
    assert "TRANSACTION_PROVENANCE_UNVERIFIED" in result["reason_codes"]


def test_signed_transaction_is_blocked(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id, unsigned_transaction_base64=make_transaction(signed=True))
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    assert preview["status"] == "BLOCKED"
    assert "TRANSACTION_ALREADY_SIGNED" in preview["reason_codes"]


def test_non_allowlisted_program_is_blocked(db):
    _, _, _, simulation = seed_context(db)
    other_program = service._base58_encode(bytes([7]) * 32)
    profile = issue_profile(db, programs=[PROGRAM])
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id, unsigned_transaction_base64=make_transaction(program=other_program))
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    assert "PROGRAM_NOT_ALLOWLISTED" in preview["reason_codes"]


def test_profile_wallet_must_be_required_signer(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    other_wallet = service._base58_encode(bytes([8]) * 32)
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id, unsigned_transaction_base64=make_transaction(wallet=other_wallet))
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    assert "PROFILE_WALLET_NOT_REQUIRED_SIGNER" in preview["reason_codes"]


def test_lookup_table_is_blocked(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id, unsigned_transaction_base64=make_transaction(versioned=True, with_lookup=True))
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    assert "ADDRESS_LOOKUP_TABLES_NOT_ALLOWED" in preview["reason_codes"]


def test_m35_simulation_must_be_ready(db):
    _, _, _, simulation = seed_context(db, sim_status="BLOCKED")
    profile = issue_profile(db)
    with pytest.raises(service.CanonicalParserLiveTransactionDryRunError) as exc:
        service.preview_live_transaction_dry_run(db, **run_kwargs(profile["profile_id"], simulation.simulation_id), settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    assert exc.value.code == "M36_M35_SIMULATION_NOT_READY"


def test_m35_evidence_drift_is_blocked(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    simulation.evidence_snapshot = {"tampered": True}
    db.commit()
    with pytest.raises(service.CanonicalParserLiveTransactionDryRunError) as exc:
        service.preview_live_transaction_dry_run(db, **run_kwargs(profile["profile_id"], simulation.simulation_id), settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    assert exc.value.code == "M36_M35_EVIDENCE_DRIFT"


def test_live_policy_drift_is_blocked(db):
    live_policy, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    live_policy.max_daily_buy_sol = float(live_policy.max_daily_buy_sol) + 1
    db.commit()
    with pytest.raises(service.CanonicalParserLiveTransactionDryRunError) as exc:
        service.preview_live_transaction_dry_run(db, **run_kwargs(profile["profile_id"], simulation.simulation_id), settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    assert exc.value.code == "M36_LIVE_POLICY_DRIFT"


def test_dry_run_is_idempotent_and_does_not_store_raw_transaction(db):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id)
    preview = service.preview_live_transaction_dry_run(db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW + timedelta(minutes=1))
    first = service.run_live_transaction_dry_run(db, **kwargs, run_rpc_simulation=True, confirmation=preview["confirmation"], settings_object=settings_for_m36(), prepared_at=NOW + timedelta(minutes=1), rpc_client=PassingRpc())
    second = service.run_live_transaction_dry_run(db, **kwargs, run_rpc_simulation=True, confirmation=preview["confirmation"], settings_object=settings_for_m36(), prepared_at=NOW + timedelta(minutes=1), rpc_client=PassingRpc())
    assert first["dry_run_id"] == second["dry_run_id"]
    assert db.query(CanonicalParserLiveTransactionDryRun).count() == 1
    row = db.scalar(select(CanonicalParserLiveTransactionDryRun))
    serialized = str(row.inspection_snapshot) + str(row.signing_envelope) + str(row.rpc_simulation_snapshot)
    assert kwargs["unsigned_transaction_base64"] not in serialized


def test_status_has_no_signer_or_submission_capability(db):
    status = service.get_live_transaction_dry_run_status(db, settings_object=settings_for_m36())
    assert status["safety"]["credential_material_loaded"] is False
    assert status["safety"]["transaction_signing_available"] is False
    assert status["safety"]["transaction_submission_available"] is False


def test_service_has_no_private_key_signer_or_submission_calls():
    path = Path("backend/app/services/blockchain_parser_live_transaction_dry_run_service.py")
    source = path.read_text()
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "backend.app.services.solana_transaction_signer" not in source
    assert "solders.keypair" not in imports
    assert "sign_base64_versioned_transaction" not in calls
    assert "execute_order" not in calls
    assert "send_transaction" not in calls
    assert "send_raw_transaction" not in calls
    assert "LIVE_TRADING_PRIVATE_KEY" not in source


def test_openapi_contains_m36_operations():
    schema = app.openapi()
    required = {
        ("get", "/integrity/parser-live-transaction-dry-run/status"),
        ("get", "/integrity/parser-live-transaction-dry-run/signer-profile-preview"),
        ("post", "/integrity/parser-live-transaction-dry-run/signer-profile/issue"),
        ("post", "/integrity/parser-live-transaction-dry-run/signer-profile/revoke"),
        ("post", "/integrity/parser-live-transaction-dry-run/build-preview"),
        ("post", "/integrity/parser-live-transaction-dry-run/preview"),
        ("post", "/integrity/parser-live-transaction-dry-run/run"),
        ("get", "/integrity/parser-live-transaction-dry-run/signer-profiles/{profile_id}"),
        ("get", "/integrity/parser-live-transaction-dry-run/runs/{dry_run_id}"),
        ("get", "/integrity/parser-live-transaction-dry-run/resolve"),
    }
    for method, path in required:
        assert method in schema["paths"][path]


def test_m36_endpoint_requires_automation_key(db, monkeypatch):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get("/integrity/parser-live-transaction-dry-run/status")
        assert response.status_code in {401, 403, 503}
    finally:
        app.dependency_overrides.clear()
