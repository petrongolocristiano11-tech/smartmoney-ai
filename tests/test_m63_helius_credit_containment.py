from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4CopyabilityPosition,
    CanonicalParserGen4CopyabilityWorkerState,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.models.gen4_forward_feed import CanonicalParserGen4ForwardFeedState
from backend.app.models.gen4_forward_shadow import CanonicalParserGen4ForwardCampaign
from backend.app.models.live_trading_worker import LiveTradingWorkerState
from backend.app.services import blockchain_parser_gen4_copyability_service as copy_service
from backend.app.services import blockchain_parser_gen4_forward_feed_service as feed_service
from backend.app.services import helius as helius_service
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    GEN4_COPYABILITY_PROCESS_CONFIRMATION,
    RECEIPT_EXCLUDED_RECOVERY,
    SOURCE_RECOVERY,
    process_gen4_copyability_queue,
    receive_gen4_copyability_webhook,
    record_gen4_copyability_raw_recovery_events,
)
from backend.app.services.blockchain_parser_gen4_forward_feed_service import (
    GEN4_FORWARD_FEED_POLL_CONFIRMATION,
    get_gen4_forward_feed_status,
    run_gen4_forward_feed_poll,
)
from backend.app.services.helius import HeliusRequestError
from backend.app.services import helius_credit_guard_service as guard_service
from backend.app.services.helius_credit_guard_service import (
    CATEGORY_ENHANCED,
    HeliusCreditGuardError,
    reserve_helius_credits,
)
from backend.app.services.live_trading_policy_service import get_or_create_live_policy
from backend.app.services.m63_helius_credit_containment_service import (
    M63_CONTAINMENT_CONFIRMATION,
    M63_TARGET_WALLET,
    apply_m63_helius_credit_containment,
)


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
PRIMARY_WALLET = "FsKYLBwxLQk5YMNSPYQcqceW6o8tJGF7U1aBHyEvGAyE"
TOKEN = "61BtvdXLEWT52BBsGh6qrsuwoGUcE3cuuS3EC8Mjpump"
PROOF_TOKEN = "GnzqboS9akb8VDMdazHRxQHtPsBgQAWUnQTBaZ5CxkyD"


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def persistent_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture(autouse=True)
def m63_settings(monkeypatch):
    values = {
        "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED": True,
        "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_INTERVAL_SECONDS": 1,
        "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_BATCH_SIZE": 20,
        "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_LEASE_SECONDS": 30,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PROCESSING_ATTEMPTS": 3,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED": True,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_INTERVAL_SECONDS": 120,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_MAX_REQUESTS_PER_RUN": 4,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_PAGE_SIZE": 100,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_OVERLAP_SECONDS": 90,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_LEASE_SECONDS": 180,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_DAILY_REQUEST_CAP": 2000,
        "CANONICAL_PARSER_GEN4_FORWARD_MAX_INGESTION_LAG_SECONDS": 300,
        "HELIUS_CREDIT_GUARD_ENABLED": True,
        "HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION": True,
        "HELIUS_APP_DAILY_CREDIT_CAP": 200,
        "HELIUS_ENHANCED_DAILY_CREDIT_CAP": 200,
        "HELIUS_RPC_DAILY_CREDIT_CAP": 100,
        "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED": False,
    }
    for module in (copy_service, feed_service, guard_service, helius_service):
        for key, value in values.items():
            monkeypatch.setattr(module.settings, key, value)


def _forward(db: Session, *, wallet: str = M63_TARGET_WALLET):
    anchor = NOW - timedelta(days=4)
    row = CanonicalParserGen4ForwardCampaign(
        campaign_id=str(uuid4()),
        campaign_key=uuid4().hex * 2,
        scope="GEN4_STRICT_FORWARD_SHADOW",
        status="ACTIVE",
        verdict="COLLECTING",
        strict_evidence_status="COLLECTING",
        policy_version="canonical-parser-gen4-strict-forward-shadow/1",
        policy_hash="b" * 64,
        policy_snapshot={},
        frozen_wallets=[wallet],
        frozen_wallet_metrics={},
        frozen_wallet_count=1,
        anchor_at=anchor,
        minimum_complete_at=anchor + timedelta(days=21),
        latest_observed_at=anchor,
        started_at=anchor,
        minimum_observation_days=21,
        minimum_closed_trades=30,
        proof_closed_trades=100,
        cycle_count=0,
        decision_count=0,
        strict_signal_count=0,
        proxy_signal_count=0,
        baseline_signal_count=0,
        strict_closed_trade_count=0,
        proxy_closed_trade_count=0,
        baseline_closed_trade_count=0,
        rejected_decision_count=0,
        strict_metrics={},
        proxy_metrics={},
        baseline_metrics={},
        evidence_gaps=[],
        safety={},
        evidence_hash="c" * 64,
        actor_label="TEST",
        technical_metadata={},
    )
    db.add(row)
    db.flush()
    return row


def _copy_campaign(
    db: Session,
    forward: CanonicalParserGen4ForwardCampaign,
    *,
    role: str,
    wallet: str,
    candidate_key: str,
) -> CanonicalParserGen4CopyabilityCampaign:
    anchor = NOW - timedelta(days=4)
    row = CanonicalParserGen4CopyabilityCampaign(
        campaign_id=str(uuid4()),
        forward_campaign_db_id=forward.id,
        status="ACTIVE",
        campaign_role=role,
        candidate_key=candidate_key,
        verdict="COLLECTING",
        policy_version="canonical-parser-gen4-realtime-copyability/1",
        policy_hash="d" * 64,
        policy_snapshot={},
        frozen_wallets=[wallet],
        selection_snapshot={},
        anchor_at=anchor,
        minimum_complete_at=anchor + timedelta(days=21),
        latest_observed_at=anchor,
        started_at=anchor,
        minimum_observation_days=21,
        minimum_closed_trades=30,
        proof_closed_trades=100,
        simulated_input_lamports=10_000_000,
        slippage_bps=300,
        max_signal_age_ms=20_000,
        max_quote_latency_ms=5_000,
        max_price_impact_bps=500,
        max_price_deterioration_bps=1_000,
        estimated_network_fee_lamports=100_000,
        minimum_webhook_coverage_percent=95.0,
        minimum_profit_factor=1.2,
        maximum_drawdown_percent=20.0,
        webhook_id="m63-webhook",
        webhook_status="ACTIVE",
        webhook_url="https://backend.test/webhook",
        webhook_configured_at=anchor,
        last_webhook_at=anchor,
        receipt_count=0,
        duplicate_receipt_count=0,
        recovery_receipt_count=0,
        processed_receipt_count=0,
        failed_receipt_count=0,
        ignored_receipt_count=0,
        buy_signal_count=0,
        sell_signal_count=0,
        executable_entry_count=0,
        rejected_entry_count=0,
        open_position_count=0,
        closed_trade_count=0,
        metrics={},
        evidence_gaps=[],
        safety={},
        actor_label="TEST",
        technical_metadata={},
    )
    db.add(row)
    db.flush()
    return row


def _receipt(
    db: Session,
    campaign: CanonicalParserGen4CopyabilityCampaign,
    *,
    signature: str,
    token: str,
) -> CanonicalParserGen4WebhookReceipt:
    row = CanonicalParserGen4WebhookReceipt(
        receipt_id=str(uuid4()),
        campaign_db_id=campaign.id,
        signature=signature,
        event_hash="e" * 64,
        source="WEBHOOK",
        status="PROCESSED",
        auth_verified=True,
        wallet_address=M63_TARGET_WALLET,
        matched_wallets=[M63_TARGET_WALLET],
        slot=1,
        block_time=NOW - timedelta(minutes=20),
        received_at=NOW - timedelta(minutes=20),
        first_received_at=NOW - timedelta(minutes=20),
        last_received_at=NOW - timedelta(minutes=20),
        processed_at=NOW - timedelta(minutes=20),
        delivery_count=1,
        processing_attempts=1,
        raw_payload={},
        parsed_summary={"side": "BUY", "token_mint": token},
    )
    db.add(row)
    db.flush()
    return row


def _position(
    db: Session,
    campaign: CanonicalParserGen4CopyabilityCampaign,
    receipt: CanonicalParserGen4WebhookReceipt,
    *,
    token: str,
    closed: bool,
) -> CanonicalParserGen4CopyabilityPosition:
    row = CanonicalParserGen4CopyabilityPosition(
        position_id=str(uuid4()),
        campaign_db_id=campaign.id,
        entry_receipt_db_id=receipt.id,
        status="CLOSED" if closed else "OPEN",
        wallet_address=M63_TARGET_WALLET,
        token_mint=token,
        token_decimals=6,
        entry_signature=receipt.signature,
        entry_source="WEBHOOK",
        entry_signal_at=NOW - timedelta(minutes=20),
        entry_received_at=NOW - timedelta(minutes=20),
        opened_at=NOW - timedelta(minutes=20),
        closed_at=(NOW - timedelta(minutes=10) if closed else None),
        entry_transaction_built=True,
        entry_copyable=True,
        entry_input_lamports=10_000_000,
        entry_output_token_raw=1_000_000,
        remaining_token_raw=0 if closed else 1_000_000,
        realized_output_lamports=12_000_000 if closed else 0,
        allocated_entry_fee_lamports=100_000,
        allocated_exit_fee_lamports=100_000 if closed else 0,
        pnl_lamports=1_800_000 if closed else None,
        return_percent=17.82 if closed else None,
        close_reason="MIRRORED_WALLET_EXIT" if closed else None,
        exit_source="WEBHOOK" if closed else None,
        last_exit_signature="proof-exit" if closed else None,
        exit_transaction_built=closed,
        exit_copyable=closed,
        entry_quote={},
        exit_quotes=[],
        evidence={},
    )
    db.add(row)
    db.flush()
    return row


def _raw_payload(*, signature: str, side: str, block_time: datetime) -> dict:
    buy = side == "BUY"
    return {
        "slot": 123456,
        "blockTime": int(block_time.timestamp()),
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [
                    {"pubkey": M63_TARGET_WALLET, "signer": True, "writable": True},
                    {"pubkey": TOKEN, "signer": False, "writable": True},
                ]
            },
        },
        "meta": {
            "err": None,
            "fee": 100_000,
            "preBalances": [1_000_000_000, 0],
            "postBalances": [989_900_000 if buy else 1_012_000_000, 0],
            "preTokenBalances": [
                {
                    "owner": M63_TARGET_WALLET,
                    "mint": TOKEN,
                    "uiTokenAmount": {
                        "amount": "0" if buy else "1000000",
                        "decimals": 6,
                    },
                }
            ],
            "postTokenBalances": [
                {
                    "owner": M63_TARGET_WALLET,
                    "mint": TOKEN,
                    "uiTokenAmount": {
                        "amount": "1000000" if buy else "0",
                        "decimals": 6,
                    },
                }
            ],
        },
    }


def test_automatic_enhanced_is_blocked_before_network(
    persistent_session_factory,
    monkeypatch,
):
    network_calls = 0

    def reserve(**kwargs):
        return reserve_helius_credits(
            **kwargs,
            session_factory=persistent_session_factory,
            force=True,
        )

    def forbidden_network(*args, **kwargs):
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("La rete non deve essere raggiunta")

    monkeypatch.setattr(helius_service, "reserve_helius_credits", reserve)
    monkeypatch.setattr(helius_service.httpx, "request", forbidden_network)

    with pytest.raises(HeliusRequestError) as captured:
        helius_service.get_enhanced_transaction(
            "m63-signature",
            request_origin="TEST_AUTOMATIC",
            automatic=True,
        )
    assert captured.value.error_code == "HELIUS_AUTOMATIC_ENHANCED_DISABLED"
    assert network_calls == 0


def test_credit_budget_persists_and_resets_by_utc_day(
    persistent_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        guard_service.settings,
        "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED",
        True,
    )
    first = reserve_helius_credits(
        category=CATEGORY_ENHANCED,
        estimated_credits=100,
        origin="TEST_FIRST",
        automatic=True,
        now=NOW,
        session_factory=persistent_session_factory,
        force=True,
    )
    second = reserve_helius_credits(
        category=CATEGORY_ENHANCED,
        estimated_credits=100,
        origin="TEST_SECOND",
        automatic=False,
        now=NOW,
        session_factory=persistent_session_factory,
        force=True,
    )
    assert first["daily_total_credits"] == 100
    assert second["daily_total_credits"] == 200
    with pytest.raises(HeliusCreditGuardError) as captured:
        reserve_helius_credits(
            category=CATEGORY_ENHANCED,
            estimated_credits=100,
            origin="TEST_BLOCKED",
            automatic=False,
            now=NOW,
            session_factory=persistent_session_factory,
            force=True,
        )
    assert captured.value.code == "HELIUS_DAILY_TOTAL_CREDIT_CAP_REACHED"

    next_day = reserve_helius_credits(
        category=CATEGORY_ENHANCED,
        estimated_credits=100,
        origin="TEST_NEXT_DAY",
        automatic=False,
        now=NOW + timedelta(days=1),
        session_factory=persistent_session_factory,
        force=True,
    )
    assert next_day["daily_total_credits"] == 100
    assert next_day["lifetime_reserved_credits"] == 300
    assert next_day["lifetime_blocked_requests"] == 1


def test_forward_recovery_disabled_before_provider_call(db, monkeypatch):
    forward = _forward(db)
    get_gen4_forward_feed_status(db)
    monkeypatch.setattr(
        feed_service,
        "_webhook_gated_wallets",
        lambda *args, **kwargs: ([M63_TARGET_WALLET], {"acquisition_mode": "TEST"}),
    )
    monkeypatch.setattr(
        feed_service,
        "get_wallet_history",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Enhanced non deve essere chiamata")
        ),
    )
    result = run_gen4_forward_feed_poll(
        db,
        campaign_id=forward.campaign_id,
        confirmation=GEN4_FORWARD_FEED_POLL_CONFIRMATION,
        observed_at=NOW,
    )
    assert result["run"]["status"] == "SKIPPED_BUDGET"
    assert result["run"]["error_code"] == "HELIUS_AUTOMATIC_ENHANCED_DISABLED"
    assert result["run"]["helius_requests"] == 0


def test_containment_preserves_target_and_pauses_only_other_consumers(db):
    forward = _forward(db)
    primary = _copy_campaign(
        db,
        forward,
        role="PRIMARY_FORWARD",
        wallet=PRIMARY_WALLET,
        candidate_key="p" * 64,
    )
    target = _copy_campaign(
        db,
        forward,
        role="QUALIFIED_CANDIDATE",
        wallet=M63_TARGET_WALLET,
        candidate_key="q" * 64,
    )
    target.closed_trade_count = 83
    feed_state = CanonicalParserGen4ForwardFeedState(
        state_id=str(uuid4()),
        campaign_db_id=forward.id,
        enabled=True,
        interval_seconds=120,
        max_requests_per_run=4,
        page_size=100,
        overlap_seconds=90,
        feed_started_at=NOW - timedelta(days=4),
        technical_metadata={},
    )
    policy = get_or_create_live_policy(db)
    policy.mode = "DRY_RUN"
    policy.stream_execution_enabled = True
    policy.source_wallets = [PRIMARY_WALLET]
    legacy_worker = LiveTradingWorkerState(
        id=1,
        status="RUNNING",
        active_wallets=[PRIMARY_WALLET],
        monitored_wallets=1,
        active_subscriptions=1,
        queue_depth=2,
    )
    copy_worker = CanonicalParserGen4CopyabilityWorkerState(
        state_id="GEN4_COPYABILITY_GLOBAL",
        enabled=True,
        poll_interval_seconds=1,
        batch_size=20,
        technical_metadata={},
    )
    db.add_all([feed_state, legacy_worker, copy_worker])
    db.flush()

    result = apply_m63_helius_credit_containment(
        db,
        confirmation=M63_CONTAINMENT_CONFIRMATION,
        observed_at=NOW,
    )
    assert result["target_closed_trade_count"] == 83
    assert result["rows_deleted"] == 0
    assert target.status == "ACTIVE"
    assert target.closed_trade_count == 83
    assert primary.status == "PAUSED"
    assert feed_state.enabled is False
    assert policy.mode == "DRY_RUN"
    assert policy.stream_execution_enabled is False
    assert legacy_worker.status == "STOPPED"
    assert legacy_worker.active_wallets == []
    assert copy_worker.enabled is True
    assert (
        target.technical_metadata["m63_helius_credit_containment"]
        ["original_state"]["campaign_statuses"][primary.campaign_id]
        == "ACTIVE"
    )
    assert target.technical_metadata["m63_helius_credit_containment"][
        "public_rpc_recovery_after_utc"
    ] == target.last_webhook_at.isoformat()


def test_raw_gap_recovery_quarantines_balance_without_changing_proof(db):
    forward = _forward(db)
    campaign = _copy_campaign(
        db,
        forward,
        role="QUALIFIED_CANDIDATE",
        wallet=M63_TARGET_WALLET,
        candidate_key="q" * 64,
    )
    proof_receipt = _receipt(db, campaign, signature="proof-entry", token=PROOF_TOKEN)
    open_receipt = _receipt(db, campaign, signature="open-entry", token=TOKEN)
    _position(db, campaign, proof_receipt, token=PROOF_TOKEN, closed=True)
    open_position = _position(db, campaign, open_receipt, token=TOKEN, closed=False)
    copy_service._refresh_campaign_metrics(db, campaign, observed_at=NOW - timedelta(minutes=5))
    assert campaign.closed_trade_count == 1

    recovery = record_gen4_copyability_raw_recovery_events(
        db,
        wallet_address=M63_TARGET_WALLET,
        transactions=[
            _raw_payload(
                signature="public-rpc-gap-buy",
                side="BUY",
                block_time=NOW - timedelta(minutes=4),
            )
        ],
        observed_at=NOW - timedelta(minutes=3),
    )
    assert recovery["created"] == 1
    assert recovery["parsed"] == 1
    assert recovery["positions_quarantined"] == 1
    assert recovery["active_quarantined_tokens"] == 1
    assert campaign.closed_trade_count == 1
    assert open_position.close_reason == "RECOVERY_GAP_QUARANTINE"
    assert open_position.exit_source == SOURCE_RECOVERY
    assert open_position.exit_copyable is False
    recovered = db.query(CanonicalParserGen4WebhookReceipt).filter_by(
        signature="public-rpc-gap-buy"
    ).one()
    assert recovered.status == RECEIPT_EXCLUDED_RECOVERY
    assert recovered.source == SOURCE_RECOVERY

    receive_gen4_copyability_webhook(
        db,
        payload=_raw_payload(
            signature="realtime-buy-during-quarantine",
            side="BUY",
            block_time=NOW - timedelta(seconds=1),
        ),
        received_at=NOW,
    )

    class NoJupiter:
        def __getattr__(self, name):
            raise AssertionError("Jupiter non deve essere chiamato durante la quarantena")

    processed = process_gen4_copyability_queue(
        db,
        confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
        owner_id="m63-test",
        observed_at=NOW,
        jupiter_client=NoJupiter(),
        now_fn=lambda: NOW,
    )
    assert processed["summary"]["quotes_requested"] == 0
    ignored = db.query(CanonicalParserGen4WebhookReceipt).filter_by(
        signature="realtime-buy-during-quarantine"
    ).one()
    assert ignored.parsed_summary["ignored_reason"] == "RECOVERY_GAP_TOKEN_QUARANTINED"

    receive_gen4_copyability_webhook(
        db,
        payload=_raw_payload(
            signature="realtime-full-exit-clears-quarantine",
            side="SELL",
            block_time=NOW + timedelta(seconds=1),
        ),
        received_at=NOW + timedelta(seconds=2),
    )
    process_gen4_copyability_queue(
        db,
        confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
        owner_id="m63-test",
        observed_at=NOW + timedelta(seconds=2),
        jupiter_client=NoJupiter(),
        now_fn=lambda: NOW + timedelta(seconds=2),
    )
    cleared = db.query(CanonicalParserGen4WebhookReceipt).filter_by(
        signature="realtime-full-exit-clears-quarantine"
    ).one()
    assert (
        cleared.parsed_summary["ignored_reason"]
        == "RECOVERY_GAP_TOKEN_QUARANTINE_CLEARED"
    )
    tokens = campaign.technical_metadata["m63_public_rpc_recovery_gap"]["tokens"]
    assert tokens == {}
    assert campaign.closed_trade_count == 1


def test_m63_adds_no_migration_and_preserves_head():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1
    assert "e4c7a9d1b268" in {
        revision.revision for revision in scripts.walk_revisions()
    }


def test_candidate_only_worker_preserves_m61_role_contract_without_primary_restart():
    source = Path("backend/app/workers/gen4_copyability_worker.py").read_text(
        encoding="utf-8-sig"
    )
    assert 'item.get("campaign_role") == "PRIMARY_FORWARD"' in source
    assert "if not campaigns:" in source
    assert "if primary is None:" not in source
    assert "gen4_copyability_candidate_only_runtime" in source
