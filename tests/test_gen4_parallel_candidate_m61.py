from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.database.base import Base
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4CopyabilityPosition,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.models.gen4_forward_shadow import CanonicalParserGen4ForwardCampaign
from backend.app.services import blockchain_parser_gen4_copyability_service as service
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    CAMPAIGN_ROLE_CANDIDATE,
    CAMPAIGN_ROLE_PRIMARY,
    GEN4_COPYABILITY_PROCESS_CONFIRMATION,
    GEN4_COPYABILITY_START_CONFIRMATION,
    GEN4_COPYABILITY_STOP_CONFIRMATION,
    GEN4_COPYABILITY_WEBHOOK_CONFIRMATION,
    GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
    CanonicalParserGen4CopyabilityError,
    configure_gen4_copyability_webhook,
    get_gen4_copyability_status,
    process_gen4_copyability_queue,
    receive_gen4_copyability_webhook,
    start_gen4_copyability_campaign,
    start_gen4_qualified_candidate_campaign,
    stop_gen4_copyability_campaign,
)
from backend.app.services.jupiter_swap_client import JupiterOrderResult
from backend.app.services.gen4_fastpath_shadow_service import active_fastpath_wallets


NOW = datetime(2026, 8, 7, 21, 0, 0, tzinfo=timezone.utc)
PRIMARY_A = "FsKYLBwxLQk5YMNSPYQcqceW6o8tJGF7U1aBHyEvGAyE"
PRIMARY_B = "2ZwYWRaQR7X3zcD7VX8u4Ke8znPQuKrVpRnU3Tp6UH7S"
CANDIDATE = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
CANDIDATE_2 = "43reoQjz67rzbUvmVomhVoMVyPKzrFrBs4cn3s4Kb8Kx"
TOKEN_A = "8wxkvAfEns76yBzu4MnbV7VnXWjg3iDPA9uwAQ6cpump"
TOKEN_B = "Cg1hswfyVfnFaKHSEVyNdFWEj1bmnZoA8ZnWLVbApump"


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    values = {
        "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED": True,
        "CANONICAL_PARSER_GEN4_COPYABILITY_AUTOSTART": True,
        "CANONICAL_PARSER_GEN4_COPYABILITY_QUOTE_TAKER": PRIMARY_B,
        "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_INTERVAL_SECONDS": 1,
        "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_BATCH_SIZE": 20,
        "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_LEASE_SECONDS": 30,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PROCESSING_ATTEMPTS": 3,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MIN_OBSERVATION_DAYS": 21,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MIN_CLOSED_TRADES": 30,
        "CANONICAL_PARSER_GEN4_COPYABILITY_PROOF_CLOSED_TRADES": 100,
        "CANONICAL_PARSER_GEN4_COPYABILITY_SIMULATED_INPUT_LAMPORTS": 10_000_000,
        "CANONICAL_PARSER_GEN4_COPYABILITY_SLIPPAGE_BPS": 300,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_SIGNAL_AGE_MS": 20_000,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_QUOTE_LATENCY_MS": 5_000,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PRICE_IMPACT_BPS": 500,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PRICE_DETERIORATION_BPS": 1_000,
        "CANONICAL_PARSER_GEN4_COPYABILITY_ESTIMATED_NETWORK_FEE_LAMPORTS": 100_000,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MIN_WEBHOOK_COVERAGE_PERCENT": 95.0,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MIN_PROFIT_FACTOR": 1.2,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_DRAWDOWN_PERCENT": 20.0,
    }
    for name, value in values.items():
        monkeypatch.setattr(service.settings, name, value)


def selection_snapshot():
    return {
        "activity_gate": "PASS",
        "buy_sell_parsing": "PASS",
        "quality_gate": "PASS",
        "observed_profitability": "PASS",
        "gen4_copyability": "PASS",
        "jupiter_copyability_pass": "6/6",
    }


def forward_campaign(
    db: Session,
    *,
    anchor: datetime | None = None,
    campaign_key: str = "a" * 64,
    frozen_wallets: list[str] | None = None,
):
    anchor = anchor or (NOW - timedelta(days=4))
    wallets = frozen_wallets or [PRIMARY_A, PRIMARY_B]
    row = CanonicalParserGen4ForwardCampaign(
        campaign_id=str(uuid4()),
        campaign_key=campaign_key,
        scope="GEN4_STRICT_FORWARD_SHADOW",
        status="ACTIVE",
        verdict="COLLECTING",
        strict_evidence_status="COLLECTING",
        policy_version="canonical-parser-gen4-strict-forward-shadow/1",
        policy_hash="b" * 64,
        policy_snapshot={},
        frozen_wallets=wallets,
        frozen_wallet_metrics={},
        frozen_wallet_count=len(wallets),
        anchor_at=anchor,
        minimum_complete_at=anchor + timedelta(days=21),
        latest_observed_at=anchor,
        started_at=anchor,
        completed_at=None,
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
        note=None,
        technical_metadata={},
    )
    db.add(row)
    db.commit()
    return row


def start_both(db: Session):
    forward_campaign(db)
    primary = start_gen4_copyability_campaign(
        db,
        confirmation=GEN4_COPYABILITY_START_CONFIRMATION,
        actor_label="TEST",
        anchor_at=NOW,
    )
    candidate = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE],
        selection_snapshot=selection_snapshot(),
        actor_label="TEST",
        anchor_at=NOW,
    )
    db.commit()
    return primary, candidate


def configure(db: Session, campaign_id: str):
    configure_gen4_copyability_webhook(
        db,
        campaign_id=campaign_id,
        confirmation=GEN4_COPYABILITY_WEBHOOK_CONFIRMATION,
        webhook_id="m61-webhook",
        webhook_url="https://example.test/integrity/parser-gen4-copyability/webhook/helius",
        active=True,
        observed_at=NOW,
    )
    db.commit()


def raw_buy(wallet: str, token: str, signature: str):
    return {
        "slot": 123,
        "blockTime": int(NOW.timestamp()),
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [
                    {"pubkey": wallet, "signer": True, "writable": True},
                    {"pubkey": token, "signer": False, "writable": True},
                ]
            },
        },
        "meta": {
            "err": None,
            "fee": 100_000,
            "preBalances": [1_000_000_000, 0],
            "postBalances": [989_900_000, 0],
            "preTokenBalances": [
                {
                    "owner": wallet,
                    "mint": token,
                    "uiTokenAmount": {"amount": "0", "decimals": 6},
                }
            ],
            "postTokenBalances": [
                {
                    "owner": wallet,
                    "mint": token,
                    "uiTokenAmount": {"amount": "1000000", "decimals": 6},
                }
            ],
        },
    }


class FakeJupiter:
    def __init__(self):
        self.calls = []

    def get_order(self, **kwargs):
        self.calls.append(kwargs)
        return JupiterOrderResult(
            raw={
                "requestId": str(uuid4()),
                "inAmount": str(kwargs["amount_raw"]),
                "outAmount": "1000000",
                "otherAmountThreshold": "970000",
                "slippageBps": 300,
                "priceImpact": 0.1,
                "transaction": "unsigned-only",
            },
            request_id=str(uuid4()),
            transaction="unsigned-only",
            in_amount=int(kwargs["amount_raw"]),
            out_amount=1_000_000,
            slippage_bps=300,
            router="test",
            price_impact_percent=0.1,
            last_valid_block_height="1",
        )

    def execute_order(self, **_kwargs):
        raise AssertionError("M61 non deve eseguire transazioni")


def test_unconfigured_candidate_is_excluded_from_webhook_and_fastpath_proof(db: Session):
    primary, candidate = start_both(db)
    configure(db, primary["campaign_id"])

    assert active_fastpath_wallets(db) == sorted([PRIMARY_A, PRIMARY_B])

    result = receive_gen4_copyability_webhook(
        db,
        payload=raw_buy(CANDIDATE, TOKEN_B, "candidate-before-webhook"),
        received_at=NOW + timedelta(seconds=1),
    )
    db.commit()

    assert result["accepted"] == 0
    assert result["campaigns_touched"] == []
    assert (
        db.scalar(
            select(func.count(CanonicalParserGen4WebhookReceipt.id)).where(
                CanonicalParserGen4WebhookReceipt.signature == "candidate-before-webhook"
            )
        )
        == 0
    )

    configure(db, candidate["campaign_id"])
    assert active_fastpath_wallets(db) == sorted([PRIMARY_A, PRIMARY_B, CANDIDATE])

    accepted = receive_gen4_copyability_webhook(
        db,
        payload=raw_buy(CANDIDATE, TOKEN_B, "candidate-after-webhook"),
        received_at=NOW + timedelta(seconds=2),
    )
    db.commit()
    assert accepted["accepted"] == 1
    assert accepted["campaigns_touched"] == [candidate["campaign_id"]]


def test_candidate_only_m63_lineage_can_start_fresh_candidate_without_primary(db: Session):
    forward = forward_campaign(db)
    primary = start_gen4_copyability_campaign(
        db,
        confirmation=GEN4_COPYABILITY_START_CONFIRMATION,
        actor_label="TEST",
        anchor_at=NOW,
    )
    first_candidate = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE],
        selection_snapshot=selection_snapshot(),
        actor_label="TEST",
        anchor_at=NOW,
    )
    configure(db, first_candidate["campaign_id"])
    stop_gen4_copyability_campaign(
        db,
        campaign_id=primary["campaign_id"],
        confirmation=GEN4_COPYABILITY_STOP_CONFIRMATION,
        observed_at=NOW + timedelta(seconds=1),
    )
    db.commit()

    second_candidate = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE_2],
        selection_snapshot=selection_snapshot(),
        actor_label="TEST_M63_CANDIDATE_ONLY",
        anchor_at=NOW + timedelta(seconds=2),
    )
    db.commit()

    row = db.scalar(
        select(CanonicalParserGen4CopyabilityCampaign).where(
            CanonicalParserGen4CopyabilityCampaign.campaign_id
            == second_candidate["campaign_id"]
        )
    )
    assert row is not None
    assert row.forward_campaign_db_id == forward.id
    assert row.campaign_role == CAMPAIGN_ROLE_CANDIDATE
    assert row.technical_metadata["lineage_mode"] == "M63_ACTIVE_CANDIDATE_LINEAGE"
    assert (
        row.technical_metadata["lineage_reference_campaign_id"]
        == first_candidate["campaign_id"]
    )
    assert row.technical_metadata["primary_copyability_campaign_id"] is None


def test_candidate_only_retry_of_same_unconfigured_run_remains_idempotent(db: Session):
    forward_campaign(db)
    primary = start_gen4_copyability_campaign(
        db,
        confirmation=GEN4_COPYABILITY_START_CONFIRMATION,
        actor_label="TEST",
        anchor_at=NOW,
    )
    first_candidate = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE],
        selection_snapshot=selection_snapshot(),
        actor_label="TEST",
        anchor_at=NOW,
    )
    configure(db, first_candidate["campaign_id"])
    stop_gen4_copyability_campaign(
        db,
        campaign_id=primary["campaign_id"],
        confirmation=GEN4_COPYABILITY_STOP_CONFIRMATION,
        observed_at=NOW + timedelta(seconds=1),
    )
    db.commit()

    fresh = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE_2],
        selection_snapshot=selection_snapshot(),
        actor_label="TEST",
        anchor_at=NOW + timedelta(seconds=2),
    )
    replay = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE_2],
        selection_snapshot=selection_snapshot(),
        actor_label="TEST_RETRY",
        anchor_at=NOW + timedelta(seconds=3),
    )
    assert replay["campaign_id"] == fresh["campaign_id"]
    assert replay["idempotent_replay"] is True
    assert replay["webhook"]["status"] == "NOT_CONFIGURED"


def test_candidate_only_lineage_rejects_unconfigured_active_reference(db: Session):
    forward_campaign(db)
    primary = start_gen4_copyability_campaign(
        db,
        confirmation=GEN4_COPYABILITY_START_CONFIRMATION,
        actor_label="TEST",
        anchor_at=NOW,
    )
    first_candidate = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE],
        selection_snapshot=selection_snapshot(),
        actor_label="TEST",
        anchor_at=NOW,
    )
    stop_gen4_copyability_campaign(
        db,
        campaign_id=primary["campaign_id"],
        confirmation=GEN4_COPYABILITY_STOP_CONFIRMATION,
        observed_at=NOW + timedelta(seconds=1),
    )
    db.commit()

    with pytest.raises(CanonicalParserGen4CopyabilityError) as error:
        start_gen4_qualified_candidate_campaign(
            db,
            confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
            candidate_wallets=[CANDIDATE_2],
            selection_snapshot=selection_snapshot(),
            actor_label="TEST",
            anchor_at=NOW + timedelta(seconds=2),
        )
    assert error.value.code == "GEN4_QUALIFIED_CANDIDATE_LINEAGE_NOT_PROOF_ACTIVE"
    assert first_candidate["webhook"]["status"] == "NOT_CONFIGURED"


def test_start_parallel_candidate_preserves_primary_and_is_idempotent(db: Session):
    primary, candidate = start_both(db)
    assert primary["campaign_role"] == CAMPAIGN_ROLE_PRIMARY
    assert candidate["campaign_role"] == CAMPAIGN_ROLE_CANDIDATE
    assert primary["frozen_wallets"] == [PRIMARY_A, PRIMARY_B]
    assert candidate["frozen_wallets"] == [CANDIDATE]
    assert primary["campaign_id"] != candidate["campaign_id"]
    assert primary["candidate_key"] != candidate["candidate_key"]

    replay = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE],
        selection_snapshot=selection_snapshot(),
        anchor_at=NOW,
    )
    assert replay["campaign_id"] == candidate["campaign_id"]
    assert replay["idempotent_replay"] is True
    assert db.scalar(select(func.count(CanonicalParserGen4CopyabilityCampaign.id))) == 2


def test_archived_candidate_creates_fresh_isolated_run_on_explicit_restart(db: Session):
    _primary, candidate = start_both(db)
    stopped = stop_gen4_copyability_campaign(
        db,
        campaign_id=candidate["campaign_id"],
        confirmation=GEN4_COPYABILITY_STOP_CONFIRMATION,
        observed_at=NOW + timedelta(minutes=1),
    )
    db.commit()
    assert stopped["status"] == "COMPLETED"

    restarted = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE],
        selection_snapshot=selection_snapshot(),
        anchor_at=NOW + timedelta(minutes=2),
    )
    db.commit()

    assert restarted["campaign_id"] != candidate["campaign_id"]
    assert restarted["candidate_key"] != candidate["candidate_key"]
    assert restarted["campaign_role"] == CAMPAIGN_ROLE_CANDIDATE
    restarted_row = db.scalar(
        select(CanonicalParserGen4CopyabilityCampaign).where(
            CanonicalParserGen4CopyabilityCampaign.campaign_id == restarted["campaign_id"]
        )
    )
    assert restarted_row is not None
    assert restarted_row.technical_metadata["candidate_run_sequence"] == 1
    assert db.scalar(select(func.count(CanonicalParserGen4CopyabilityCampaign.id))) == 3


def test_candidate_requires_all_selection_gates_and_no_wallet_overlap(db: Session):
    forward_campaign(db)
    start_gen4_copyability_campaign(
        db,
        confirmation=GEN4_COPYABILITY_START_CONFIRMATION,
        anchor_at=NOW,
    )
    db.commit()

    incomplete = selection_snapshot()
    incomplete["observed_profitability"] = "FAIL"
    with pytest.raises(CanonicalParserGen4CopyabilityError) as raised:
        start_gen4_qualified_candidate_campaign(
            db,
            confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
            candidate_wallets=[CANDIDATE],
            selection_snapshot=incomplete,
        )
    assert raised.value.code == "GEN4_QUALIFIED_CANDIDATE_SELECTION_NOT_PROVEN"

    with pytest.raises(CanonicalParserGen4CopyabilityError) as raised:
        start_gen4_qualified_candidate_campaign(
            db,
            confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
            candidate_wallets=[PRIMARY_A],
            selection_snapshot=selection_snapshot(),
        )
    assert raised.value.code == "GEN4_QUALIFIED_CANDIDATE_OVERLAPS_ACTIVE_CAMPAIGN"


def test_single_webhook_routes_events_to_isolated_campaigns(db: Session):
    primary, candidate = start_both(db)
    configure(db, primary["campaign_id"])
    configure(db, candidate["campaign_id"])

    result = receive_gen4_copyability_webhook(
        db,
        payload=[
            raw_buy(PRIMARY_A, TOKEN_A, "primary-signature"),
            raw_buy(CANDIDATE, TOKEN_B, "candidate-signature"),
        ],
        received_at=NOW,
    )
    db.commit()

    assert result["accepted"] == 2
    assert result["active_campaign_count"] == 2
    assert set(result["campaigns_touched"]) == {
        primary["campaign_id"],
        candidate["campaign_id"],
    }
    campaigns = {
        row.id: row
        for row in db.scalars(select(CanonicalParserGen4CopyabilityCampaign))
    }
    receipts = list(db.scalars(select(CanonicalParserGen4WebhookReceipt)))
    assert len(receipts) == 2
    assert {
        (campaigns[receipt.campaign_db_id].campaign_role, receipt.signature)
        for receipt in receipts
    } == {
        (CAMPAIGN_ROLE_PRIMARY, "primary-signature"),
        (CAMPAIGN_ROLE_CANDIDATE, "candidate-signature"),
    }


def test_global_worker_processes_both_campaigns_without_execution(db: Session):
    primary, candidate = start_both(db)
    configure(db, primary["campaign_id"])
    configure(db, candidate["campaign_id"])
    receive_gen4_copyability_webhook(
        db,
        payload=[
            raw_buy(PRIMARY_A, TOKEN_A, "primary-process"),
            raw_buy(CANDIDATE, TOKEN_B, "candidate-process"),
        ],
        received_at=NOW,
    )
    db.commit()

    fake = FakeJupiter()
    result = process_gen4_copyability_queue(
        db,
        confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
        owner_id="m61-test-worker",
        batch_size=20,
        observed_at=NOW,
        jupiter_client=fake,
        now_fn=lambda: NOW,
    )
    db.commit()

    assert result["summary"]["receipts_processed"] == 2
    assert set(result["campaign_ids"]) == {
        primary["campaign_id"],
        candidate["campaign_id"],
    }
    assert result["per_campaign"][primary["campaign_id"]]["receipts_processed"] == 1
    assert result["per_campaign"][candidate["campaign_id"]]["receipts_processed"] == 1
    positions = list(db.scalars(select(CanonicalParserGen4CopyabilityPosition)))
    assert len(positions) == 2
    assert len({position.campaign_db_id for position in positions}) == 2
    assert len(fake.calls) == 2


def test_status_is_backward_compatible_and_exposes_all_campaigns(db: Session):
    primary, candidate = start_both(db)
    status = get_gen4_copyability_status(db, observed_at=NOW, recent_limit=5)
    assert status["campaign"]["campaign_id"] == primary["campaign_id"]
    assert status["campaign"]["campaign_role"] == CAMPAIGN_ROLE_PRIMARY
    assert status["active_campaign_count"] == 2
    assert {
        item["campaign_id"] for item in status["active_campaigns"]
    } == {primary["campaign_id"], candidate["campaign_id"]}
    assert status["m61_parallel_candidate_support"] is True

    selected = get_gen4_copyability_status(
        db,
        observed_at=NOW,
        recent_limit=5,
        campaign_id=candidate["campaign_id"],
    )
    assert selected["campaign"]["campaign_id"] == candidate["campaign_id"]


def test_m61_legacy_webhook_configurator_uses_active_campaign_union():
    source = Path("scripts/configure_gen4_copyability_helius_webhook.py").read_text(
        encoding="utf-8"
    )
    assert 'status.get("active_campaigns")' in source
    assert "wallet_owners" in source
    assert "registered_campaigns" in source
    assert "M61_SINGLE_WEBHOOK_UNION_ROUTING=ENABLED" in source
    assert "len(wallets) != 2" not in source
    assert '"transactionTypes": ["ANY"]' not in source
    assert 'f"{HELIUS_WEBHOOK_API}/{selected_id}"' in source


def _activation_primary_payload():
    return {
        "campaign_id": "89026d62-1e4e-452b-b0bf-8a5e3dd373e4",
        "campaign_role": "PRIMARY_FORWARD",
        "status": "ACTIVE",
        "anchor_at": "2026-08-03T23:04:08.419988+00:00",
        "frozen_wallets": [PRIMARY_A, PRIMARY_B],
        "counts": {
            "receipt_count": 7,
            "duplicate_receipt_count": 0,
            "recovery_receipt_count": 0,
            "processed_receipt_count": 7,
            "failed_receipt_count": 0,
            "ignored_receipt_count": 7,
            "buy_signal_count": 0,
            "sell_signal_count": 0,
            "executable_entry_count": 0,
            "rejected_entry_count": 0,
            "open_position_count": 0,
            "closed_trade_count": 0,
        },
        "webhook": {"status": "ACTIVE", "webhook_id": "wh-1"},
    }


def _activation_candidate_payload(candidate_id: str):
    return {
        "campaign_id": candidate_id,
        "campaign_role": "QUALIFIED_CANDIDATE",
        "status": "ACTIVE",
        "anchor_at": "2026-08-07T21:00:00+00:00",
        "frozen_wallets": [CANDIDATE],
        "counts": {},
        "webhook": {"status": "ACTIVE", "webhook_id": "wh-1"},
    }


def test_activation_uses_existing_webhook_union_and_preserves_primary(monkeypatch):
    from scripts import activate_gen4_parallel_candidate_m61 as activation

    candidate_id = "11111111-2222-3333-4444-555555555555"
    primary = _activation_primary_payload()
    candidate = _activation_candidate_payload(candidate_id)
    before = {
        "m61_parallel_candidate_support": True,
        "active_campaign_count": 1,
        "active_campaigns": [primary],
        "safety": service._safety(),
    }
    after = {
        "m61_parallel_candidate_support": True,
        "active_campaign_count": 2,
        "active_campaigns": [primary, candidate],
        "safety": service._safety(),
    }
    backend_calls = []
    helius_calls = []
    status_reads = 0

    def fake_backend(_client, method, path, _automation_key, payload=None):
        nonlocal status_reads
        backend_calls.append((method, path, payload))
        if method == "GET" and path == activation.STATUS_PATH:
            status_reads += 1
            return before if status_reads == 1 else after
        if method == "POST" and path == activation.START_PATH:
            return {**candidate, "idempotent_replay": False}
        if method == "POST" and path == activation.CONFIGURE_PATH:
            return primary if payload["campaign_id"] == primary["campaign_id"] else candidate
        raise AssertionError((method, path, payload))

    provider_addresses = {PRIMARY_A, PRIMARY_B}

    def fake_helius(_client, method, url, _helius_key, payload=None):
        nonlocal provider_addresses
        helius_calls.append((method, url, payload))
        if method == "GET" and url == activation.HELIUS_WEBHOOK_API:
            return [
                {
                    "webhookID": "wh-1",
                    "webhookURL": "https://backend.test" + activation.WEBHOOK_PATH,
                    "accountAddresses": [],
                    "webhookType": "raw",
                    "active": True,
                }
            ]
        if method == "PUT":
            provider_addresses = set(payload["accountAddresses"])
            return {"webhookID": "wh-1"}
        if method == "GET" and url.endswith("/wh-1"):
            return {
                "webhookID": "wh-1",
                "webhookURL": "https://backend.test" + activation.WEBHOOK_PATH,
                "accountAddresses": sorted(provider_addresses),
                "webhookType": "raw",
                "active": True,
            }
        raise AssertionError((method, url, payload))

    monkeypatch.setattr(activation, "backend_request", fake_backend)
    monkeypatch.setattr(activation, "helius_request", fake_helius)
    state = activation.ActivationState()
    activation.activate(
        object(),
        state=state,
        helius_key="helius-redacted",
        automation_key="automation-redacted",
        webhook_secret="Bearer redacted",
        target_url="https://backend.test" + activation.WEBHOOK_PATH,
    )

    assert state.candidate_id == candidate_id
    assert state.candidate_created_now is True
    assert state.webhook_updated is True
    put = next(call for call in helius_calls if call[0] == "PUT")
    assert set(put[2]["accountAddresses"]) == {PRIMARY_A, PRIMARY_B, CANDIDATE}
    assert "transactionTypes" not in put[2]
    configured_ids = {
        call[2]["campaign_id"]
        for call in backend_calls
        if call[0] == "POST" and call[1] == activation.CONFIGURE_PATH
    }
    assert configured_ids == {candidate_id}
    assert all(
        call[2]["campaign_id"] != primary["campaign_id"]
        for call in backend_calls
        if call[0] == "POST" and call[1] == activation.CONFIGURE_PATH
    )


def test_activation_failsafe_restores_webhook_and_stops_only_new_candidate(monkeypatch):
    from scripts import activate_gen4_parallel_candidate_m61 as activation

    candidate_id = "11111111-2222-3333-4444-555555555555"
    state = activation.ActivationState(
        candidate_id=candidate_id,
        candidate_created_now=True,
        webhook_id="wh-1",
        original_addresses=[PRIMARY_A, PRIMARY_B],
        webhook_updated=True,
    )
    backend_calls = []
    helius_calls = []

    def fake_backend(_client, method, path, _automation_key, payload=None):
        backend_calls.append((method, path, payload))
        return {"status": "COMPLETED"}

    def fake_helius(_client, method, url, _helius_key, payload=None):
        helius_calls.append((method, url, payload))
        return {"webhookID": "wh-1"}

    monkeypatch.setattr(activation, "backend_request", fake_backend)
    monkeypatch.setattr(activation, "helius_request", fake_helius)
    activation.rollback_activation(
        object(),
        state=state,
        helius_key="helius-redacted",
        automation_key="automation-redacted",
        webhook_secret="Bearer redacted",
        target_url="https://backend.test" + activation.WEBHOOK_PATH,
    )

    assert len(helius_calls) == 1
    assert set(helius_calls[0][2]["accountAddresses"]) == {PRIMARY_A, PRIMARY_B}
    stop_calls = [
        call for call in backend_calls if call[0] == "POST" and call[1] == activation.STOP_PATH
    ]
    assert len(stop_calls) == 1
    assert stop_calls[0][2]["campaign_id"] == candidate_id
    assert stop_calls[0][2]["confirmation"] == activation.STOP_CONFIRMATION


def test_activation_failsafe_stops_preexisting_unmonitored_candidate(monkeypatch):
    from scripts import activate_gen4_parallel_candidate_m61 as activation

    candidate_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    state = activation.ActivationState(
        candidate_id=candidate_id,
        candidate_created_now=False,
        candidate_existed_before=True,
        candidate_was_monitored_before=False,
        webhook_id="wh-1",
        original_addresses=[PRIMARY_A, PRIMARY_B],
        webhook_updated=True,
    )
    backend_calls = []
    helius_calls = []

    def fake_backend(_client, method, path, _automation_key, payload=None):
        backend_calls.append((method, path, payload))
        return {"status": "COMPLETED"}

    def fake_helius(_client, method, url, _helius_key, payload=None):
        helius_calls.append((method, url, payload))
        return {"webhookID": "wh-1"}

    monkeypatch.setattr(activation, "backend_request", fake_backend)
    monkeypatch.setattr(activation, "helius_request", fake_helius)
    activation.rollback_activation(
        object(),
        state=state,
        helius_key="helius-redacted",
        automation_key="automation-redacted",
        webhook_secret="Bearer redacted",
        target_url="https://backend.test" + activation.WEBHOOK_PATH,
    )

    assert len(helius_calls) == 1
    assert set(helius_calls[0][2]["accountAddresses"]) == {PRIMARY_A, PRIMARY_B}
    stop_calls = [
        call for call in backend_calls
        if call[0] == "POST" and call[1] == activation.STOP_PATH
    ]
    assert len(stop_calls) == 1
    assert stop_calls[0][2]["campaign_id"] == candidate_id


def test_deploy_script_supports_safe_resume_after_partial_m61():
    source = Path("scripts/deploy_gen4_parallel_candidate_m61.py").read_text(
        encoding="utf-8"
    )
    assert "REMOTE_M61_RESUME_MODE=" in source
    assert "M61_COMMIT_REUSED=YES" in source
    assert "remote_before not in {PARENT_HEAD, TARGET_HEAD}" in source
    assert 'subject != "feat: add Gen4 parallel candidate copyability M61"' in source


def test_activation_failsafe_does_not_stop_preexisting_candidate_when_webhook_state_unknown(monkeypatch):
    from scripts import activate_gen4_parallel_candidate_m61 as activation

    candidate_id = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
    state = activation.ActivationState(
        candidate_id=candidate_id,
        candidate_created_now=False,
        candidate_existed_before=True,
        candidate_was_monitored_before=None,
        webhook_updated=False,
    )
    backend_calls = []

    def fake_backend(_client, method, path, _automation_key, payload=None):
        backend_calls.append((method, path, payload))
        return {"status": "COMPLETED"}

    monkeypatch.setattr(activation, "backend_request", fake_backend)
    activation.rollback_activation(
        object(),
        state=state,
        helius_key="helius-redacted",
        automation_key="automation-redacted",
        webhook_secret="Bearer redacted",
        target_url="https://backend.test" + activation.WEBHOOK_PATH,
    )

    stop_calls = [
        call for call in backend_calls
        if call[0] == "POST" and call[1] == activation.STOP_PATH
    ]
    assert stop_calls == []


def test_candidate_is_bound_to_primary_forward_lineage_not_newer_unrelated_forward(db: Session):
    original_forward = forward_campaign(db)
    primary = start_gen4_copyability_campaign(
        db,
        confirmation=GEN4_COPYABILITY_START_CONFIRMATION,
        actor_label="TEST",
        anchor_at=NOW,
    )
    db.commit()

    unrelated = forward_campaign(
        db,
        anchor=NOW + timedelta(minutes=5),
        campaign_key="d" * 64,
        frozen_wallets=["11111111111111111111111111111111"],
    )

    candidate = start_gen4_qualified_candidate_campaign(
        db,
        confirmation=GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION,
        candidate_wallets=[CANDIDATE],
        selection_snapshot=selection_snapshot(),
        anchor_at=NOW + timedelta(minutes=10),
    )
    db.commit()

    primary_row = db.scalar(
        select(CanonicalParserGen4CopyabilityCampaign).where(
            CanonicalParserGen4CopyabilityCampaign.campaign_id == primary["campaign_id"]
        )
    )
    candidate_row = db.scalar(
        select(CanonicalParserGen4CopyabilityCampaign).where(
            CanonicalParserGen4CopyabilityCampaign.campaign_id == candidate["campaign_id"]
        )
    )
    assert primary_row is not None
    assert candidate_row is not None
    assert primary_row.forward_campaign_db_id == original_forward.id
    assert candidate_row.forward_campaign_db_id == original_forward.id
    assert candidate_row.forward_campaign_db_id != unrelated.id
