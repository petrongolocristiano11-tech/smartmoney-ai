from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4CopyabilityPosition,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.models.gen4_forward_shadow import CanonicalParserGen4ForwardCampaign
from backend.app.services import blockchain_parser_gen4_copyability_service as service
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    GEN4_COPYABILITY_PROCESS_CONFIRMATION,
    GEN4_COPYABILITY_START_CONFIRMATION,
    GEN4_COPYABILITY_WEBHOOK_CONFIRMATION,
    POSITION_CLOSED,
    POSITION_OPEN,
    RECEIPT_EXCLUDED_RECOVERY,
    RECEIPT_FAILED,
    RECEIPT_PROCESSED,
    SOURCE_RECOVERY,
    SOURCE_WEBHOOK,
    CanonicalParserGen4CopyabilityError,
    configure_gen4_copyability_webhook,
    get_gen4_copyability_status,
    parse_raw_copyability_signal,
    process_gen4_copyability_queue,
    receive_gen4_copyability_webhook,
    record_gen4_copyability_recovery_events,
    start_gen4_copyability_campaign,
)
from backend.app.services.jupiter_swap_client import JupiterOrderResult, JupiterSwapClient

NOW = datetime(2026, 8, 3, 16, 0, 0, tzinfo=timezone.utc)
WALLET_A = "FsKYLBwxLQk5YMNSPYQcqceW6o8tJGF7U1aBHyEvGAyE"
WALLET_B = "2ZwYWRaQR7X3zcD7VX8u4Ke8znPQuKrVpRnU3Tp6UH7S"
TOKEN = "CopyToken111111111111111111111111111111111111"
SOL_MINT = "So11111111111111111111111111111111111111112"


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def copyability_settings(monkeypatch):
    values = {
        "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED": True,
        "CANONICAL_PARSER_GEN4_COPYABILITY_AUTOSTART": True,
        "CANONICAL_PARSER_GEN4_COPYABILITY_WEBHOOK_SECRET": "Bearer test-secret",
        "CANONICAL_PARSER_GEN4_COPYABILITY_QUOTE_TAKER": WALLET_B,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_WEBHOOK_BYTES": 2_000_000,
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
    for key, value in values.items():
        monkeypatch.setattr(service.settings, key, value)


def _forward_campaign(db: Session, anchor: datetime = NOW - timedelta(days=1)):
    row = CanonicalParserGen4ForwardCampaign(
        campaign_id=str(uuid4()),
        campaign_key="a" * 64,
        scope="GEN4_STRICT_FORWARD_SHADOW",
        status="ACTIVE",
        verdict="COLLECTING",
        strict_evidence_status="COLLECTING",
        policy_version="canonical-parser-gen4-strict-forward-shadow/1",
        policy_hash="b" * 64,
        policy_snapshot={},
        frozen_wallets=[WALLET_A, WALLET_B],
        frozen_wallet_metrics={},
        frozen_wallet_count=2,
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


def _start(db: Session, anchor: datetime = NOW):
    _forward_campaign(db)
    result = start_gen4_copyability_campaign(
        db,
        confirmation=GEN4_COPYABILITY_START_CONFIRMATION,
        actor_label="TEST",
        anchor_at=anchor,
    )
    db.commit()
    return result


def _configure(db: Session, campaign_id: str, observed_at: datetime = NOW):
    result = configure_gen4_copyability_webhook(
        db,
        campaign_id=campaign_id,
        confirmation=GEN4_COPYABILITY_WEBHOOK_CONFIRMATION,
        webhook_id="11111111-2222-3333-4444-555555555555",
        webhook_url="https://example.test/integrity/parser-gen4-copyability/webhook/helius",
        active=True,
        observed_at=observed_at,
    )
    db.commit()
    return result


def _raw_payload(
    *,
    signature: str,
    side: str,
    wallet: str = WALLET_A,
    token: str = TOKEN,
    block_time: datetime = NOW,
    token_pre: int | None = None,
    token_post: int | None = None,
    native_pre: int = 1_000_000_000,
    native_post: int | None = None,
    fee: int = 100_000,
    err=None,
):
    if side == "BUY":
        token_pre = 0 if token_pre is None else token_pre
        token_post = 1_000_000 if token_post is None else token_post
        native_post = 989_900_000 if native_post is None else native_post
    else:
        token_pre = 1_000_000 if token_pre is None else token_pre
        token_post = 0 if token_post is None else token_post
        native_post = 1_012_000_000 if native_post is None else native_post
    return {
        "slot": 123456,
        "blockTime": int(block_time.timestamp()),
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
            "err": err,
            "fee": fee,
            "preBalances": [native_pre, 0],
            "postBalances": [native_post, 0],
            "preTokenBalances": [
                {
                    "owner": wallet,
                    "mint": token,
                    "uiTokenAmount": {"amount": str(token_pre), "decimals": 6},
                }
            ],
            "postTokenBalances": [
                {
                    "owner": wallet,
                    "mint": token,
                    "uiTokenAmount": {"amount": str(token_post), "decimals": 6},
                }
            ],
        },
    }


class Clock:
    def __init__(self, current: datetime, step_ms: int = 100):
        self.current = current
        self.step = timedelta(milliseconds=step_ms)

    def __call__(self):
        value = self.current
        self.current += self.step
        return value


class FakeJupiter:
    def __init__(self, results: list[JupiterOrderResult]):
        self.results = list(results)
        self.orders: list[dict] = []
        self.execute_calls = 0

    def get_order(self, **kwargs):
        self.orders.append(kwargs)
        if not self.results:
            raise AssertionError("Nessuna risposta Jupiter fake disponibile")
        return self.results.pop(0)

    def execute_order(self, **kwargs):
        self.execute_calls += 1
        raise AssertionError("M58-M60 non deve mai eseguire un ordine")


def _order(*, in_amount: int, out_amount: int, threshold: int, impact: float = 0.01):
    return JupiterOrderResult(
        raw={
            "requestId": str(uuid4()),
            "inAmount": str(in_amount),
            "outAmount": str(out_amount),
            "otherAmountThreshold": str(threshold),
            "slippageBps": 300,
            "priceImpact": impact,
            "transaction": "unsigned-transaction-redacted",
        },
        request_id=str(uuid4()),
        transaction="unsigned-transaction-base64",
        in_amount=in_amount,
        out_amount=out_amount,
        slippage_bps=300,
        router="jupiter-ultra",
        price_impact_percent=impact,
        last_valid_block_height="1234567",
    )


def test_real_jupiter_client_quotes_without_taker_then_builds_unsigned_instructions():
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params.multi_items())
        calls.append((request.url.path, params))
        assert request.headers.get("x-api-key") == "test-jupiter-key"
        if request.url.path.endswith("/order"):
            assert "taker" not in params
            return httpx.Response(
                200,
                json={
                    "requestId": "quote-only-request",
                    "inAmount": "10000000",
                    "outAmount": "736757",
                    "slippageBps": 300,
                    "router": "metis",
                    "priceImpact": 0.01,
                    "transaction": None,
                },
            )
        if request.url.path.endswith("/build"):
            assert params.get("taker") == WALLET_B
            assert params.get("mode") == "fast"
            return httpx.Response(
                200,
                json={
                    "inAmount": "10000000",
                    "outAmount": "736964",
                    "otherAmountThreshold": "714856",
                    "slippageBps": 300,
                    "priceImpact": 0.01,
                    "computeBudgetInstructions": [],
                    "setupInstructions": [
                        {
                            "programId": "11111111111111111111111111111111",
                            "accounts": [],
                            "data": "AQ==",
                        }
                    ],
                    "swapInstruction": {
                        "programId": "11111111111111111111111111111111",
                        "accounts": [],
                        "data": "AQ==",
                    },
                    "cleanupInstruction": None,
                    "otherInstructions": [],
                    "addressesByLookupTableAddress": {},
                    "blockhashWithMetadata": {
                        "blockhash": [1, 2, 3],
                        "lastValidBlockHeight": 1234567,
                    },
                },
            )
        return httpx.Response(500, json={"error": "unexpected endpoint"})

    client = JupiterSwapClient(
        api_key="test-jupiter-key",
        base_url="https://api.jup.ag/swap/v2",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    quote = service._quote(
        input_mint=SOL_MINT,
        output_mint=TOKEN,
        amount_raw=10_000_000,
        slippage_bps=300,
        client=client,
        now_fn=Clock(NOW),
    )

    assert [path.rsplit("/", 1)[-1] for path, _ in calls] == ["order", "build"]
    assert quote.result.transaction == "UNSIGNED_INSTRUCTIONS_BUILT_NO_SIGNATURE"
    assert quote.result.out_amount == 736_964
    assert quote.result.raw["otherAmountThreshold"] == "714856"
    assert quote.result.raw["endpointSequence"] == ["order", "build"]
    assert quote.result.raw["executeEndpointCalled"] is False
    assert quote.result.raw["signedTransactionCreated"] is False
    assert quote.result.raw["signatureCreated"] is False
    assert "swapInstruction" not in quote.result.raw


def _persist_webhook(db: Session, payload: dict, received_at: datetime):
    result = receive_gen4_copyability_webhook(db, payload=payload, received_at=received_at)
    db.commit()
    return result


def test_enabled_copyability_runtime_requires_all_non_signing_secrets():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            DATABASE_URL="sqlite+pysqlite:///:memory:",
            SOLANA_RPC_URL="http://localhost",
            HELIUS_API_KEY="test",
            JUPITER_API_KEY="",
            CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED=True,
            CANONICAL_PARSER_GEN4_COPYABILITY_AUTOSTART=True,
            CANONICAL_PARSER_GEN4_COPYABILITY_WEBHOOK_SECRET="",
            CANONICAL_PARSER_GEN4_COPYABILITY_QUOTE_TAKER="",
        )


def test_models_and_migration_extend_single_head():
    assert "canonical_parser_gen4_copyability_campaigns" in Base.metadata.tables
    assert "canonical_parser_gen4_webhook_receipts" in Base.metadata.tables
    assert "canonical_parser_gen4_copyability_positions" in Base.metadata.tables
    assert "canonical_parser_gen4_copyability_worker_states" in Base.metadata.tables
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("b6f8d2e4c731")
    assert revision.down_revision == "a5e7c1d4b926"
    assert scripts.get_heads() == ["d9b2e4f7a153"]


def test_campaign_is_frozen_from_forward_and_clock_starts_on_webhook_activation(db):
    started = _start(db, NOW - timedelta(hours=3))
    campaign_id = started["campaign_id"]
    assert started["frozen_wallets"] == [WALLET_A, WALLET_B]
    original_hash = started["policy_hash"]

    configured = _configure(db, campaign_id, NOW)
    assert configured["anchor_at"].replace(tzinfo=timezone.utc) == NOW
    assert configured["minimum_complete_at"].replace(tzinfo=timezone.utc) == NOW + timedelta(days=21)
    assert configured["policy_hash"] == original_hash
    assert configured["webhook"]["status"] == "ACTIVE"
    assert configured["safety"]["live_orders_created"] == 0


def test_recovery_before_webhook_does_not_start_realtime_clock(db):
    started = _start(db, NOW - timedelta(hours=3))
    recovery = record_gen4_copyability_recovery_events(
        db,
        wallet_address=WALLET_A,
        transactions=[
            {
                "signature": "pre-webhook-recovery",
                "timestamp": int((NOW - timedelta(minutes=1)).timestamp()),
                "type": "SWAP",
            }
        ],
        observed_at=NOW - timedelta(seconds=30),
    )
    db.commit()
    assert recovery["created"] == 1

    configured = _configure(db, started["campaign_id"], NOW)
    assert configured["anchor_at"].replace(tzinfo=timezone.utc) == NOW
    assert configured["minimum_complete_at"].replace(tzinfo=timezone.utc) == NOW + timedelta(days=21)
    assert configured["counts"]["recovery_receipt_count"] == 1


def test_raw_parser_accepts_only_unambiguous_sol_paired_swaps():
    buy = parse_raw_copyability_signal(
        _raw_payload(signature="buy-parser", side="BUY"),
        frozen_wallets=[WALLET_A, WALLET_B],
    )
    assert buy.side == "BUY"
    assert buy.token_delta_raw == 1_000_000
    assert buy.sol_equivalent_delta_lamports == -10_100_000
    assert buy.wallet_effective_price_sol == pytest.approx(0.01)

    sell = parse_raw_copyability_signal(
        _raw_payload(signature="sell-parser", side="SELL"),
        frozen_wallets=[WALLET_A, WALLET_B],
    )
    assert sell.side == "SELL"
    assert sell.sell_fraction == pytest.approx(1.0)

    transfer = _raw_payload(
        signature="not-sol-paired",
        side="BUY",
        native_post=999_900_000,
    )
    with pytest.raises(CanonicalParserGen4CopyabilityError) as error:
        parse_raw_copyability_signal(transfer, frozen_wallets=[WALLET_A, WALLET_B])
    assert error.value.code == "GEN4_COPYABILITY_RAW_NOT_SOL_PAIRED_BUY"


def test_raw_parser_accepts_existing_wsol_as_sol_equivalent_base_asset():
    payload = _raw_payload(
        signature="buy-with-existing-wsol",
        side="BUY",
        native_post=999_900_000,
    )
    payload["meta"]["preTokenBalances"].append(
        {
            "owner": WALLET_A,
            "mint": SOL_MINT,
            "uiTokenAmount": {"amount": "50000000", "decimals": 9},
        }
    )
    payload["meta"]["postTokenBalances"].append(
        {
            "owner": WALLET_A,
            "mint": SOL_MINT,
            "uiTokenAmount": {"amount": "40000000", "decimals": 9},
        }
    )

    signal = parse_raw_copyability_signal(
        payload,
        frozen_wallets=[WALLET_A, WALLET_B],
    )

    assert signal.side == "BUY"
    assert signal.sol_equivalent_delta_lamports == -10_100_000
    assert signal.wallet_effective_price_sol == pytest.approx(0.01)
    assert signal.evidence["native_delta_lamports"] == -100_000
    assert signal.evidence["wsol_delta_lamports"] == -10_000_000


def test_webhook_is_idempotent_and_late_webhook_never_promotes_recovery(db):
    campaign = _start(db)
    _configure(db, campaign["campaign_id"])
    payload = _raw_payload(signature="duplicate-signature", side="BUY")
    payload["meta"]["logMessages"] = ["large-log"] * 100
    payload["meta"]["innerInstructions"] = [{"large": "tree"}]
    payload["transaction"]["message"]["instructions"] = [{"large": "instruction"}]

    first = _persist_webhook(db, payload, NOW + timedelta(seconds=1))
    second = _persist_webhook(db, payload, NOW + timedelta(seconds=2))
    assert first["accepted"] == 1
    assert second["duplicates"] == 1
    receipt = db.query(CanonicalParserGen4WebhookReceipt).one()
    assert receipt.source == SOURCE_WEBHOOK
    assert receipt.delivery_count == 2
    assert receipt.raw_payload["_storage"]["schema"] == "GEN4_COPYABILITY_RAW_REPLAY_SUBSET_V1"
    assert "logMessages" not in receipt.raw_payload["meta"]
    assert "innerInstructions" not in receipt.raw_payload["meta"]
    assert "instructions" not in receipt.raw_payload["transaction"]["message"]

    recovery = record_gen4_copyability_recovery_events(
        db,
        wallet_address=WALLET_A,
        transactions=[{"signature": "recovery-first", "timestamp": int(NOW.timestamp()), "type": "SWAP"}],
        observed_at=NOW + timedelta(minutes=2),
    )
    db.commit()
    assert recovery["created"] == 1
    late = _persist_webhook(
        db,
        _raw_payload(signature="recovery-first", side="BUY"),
        NOW + timedelta(minutes=2, seconds=1),
    )
    assert late["duplicates"] == 1
    recovered = db.query(CanonicalParserGen4WebhookReceipt).filter_by(signature="recovery-first").one()
    assert recovered.source == SOURCE_RECOVERY
    assert recovered.status == RECEIPT_EXCLUDED_RECOVERY
    assert recovered.parsed_summary["late_webhook_received_at"]


def test_buy_and_sell_use_detection_time_quotes_and_never_execute(db):
    campaign = _start(db)
    _configure(db, campaign["campaign_id"])
    _persist_webhook(
        db,
        _raw_payload(signature="buy-copyable", side="BUY"),
        NOW + timedelta(seconds=1),
    )
    client = FakeJupiter([
        _order(in_amount=10_000_000, out_amount=1_000_000, threshold=970_000, impact=0.01),
    ])
    result = process_gen4_copyability_queue(
        db,
        confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
        owner_id="worker-a",
        observed_at=NOW + timedelta(seconds=1),
        jupiter_client=client,
        now_fn=Clock(NOW + timedelta(seconds=1, milliseconds=100)),
    )
    db.commit()
    assert result["summary"]["entries_opened"] == 1
    position = db.query(CanonicalParserGen4CopyabilityPosition).one()
    assert position.status == POSITION_OPEN
    assert position.entry_source == SOURCE_WEBHOOK
    assert position.entry_output_token_raw == 970_000
    assert position.entry_transaction_built is True
    assert position.entry_copyable is True
    assert client.orders[0]["input_mint"] == SOL_MINT
    assert client.orders[0]["output_mint"] == TOKEN
    assert client.execute_calls == 0

    _persist_webhook(
        db,
        _raw_payload(signature="sell-copyable", side="SELL", block_time=NOW + timedelta(seconds=2)),
        NOW + timedelta(seconds=3),
    )
    client.results.append(
        _order(in_amount=970_000, out_amount=12_000_000, threshold=11_500_000, impact=0.01)
    )
    result = process_gen4_copyability_queue(
        db,
        confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
        owner_id="worker-a",
        observed_at=NOW + timedelta(seconds=3),
        jupiter_client=client,
        now_fn=Clock(NOW + timedelta(seconds=3, milliseconds=100)),
    )
    db.commit()
    assert result["summary"]["positions_closed"] == 1
    db.refresh(position)
    assert position.status == POSITION_CLOSED
    assert position.exit_source == SOURCE_WEBHOOK
    assert position.pnl_lamports == 1_300_000
    assert position.return_percent == pytest.approx(12.871287, rel=1e-5)
    assert client.execute_calls == 0

    status = get_gen4_copyability_status(db, observed_at=NOW + timedelta(seconds=4))
    assert status["campaign"]["counts"]["closed_trade_count"] == 1
    assert status["campaign"]["metrics"]["net_pnl_lamports"] == 1_300_000
    assert status["campaign"]["metrics"]["automatic_live_activation"] is False
    assert status["safety"]["submitted_transactions"] == 0


def test_stale_entry_is_rejected_even_when_quote_exists(db):
    campaign = _start(db)
    _configure(db, campaign["campaign_id"])
    payload = _raw_payload(
        signature="stale-buy",
        side="BUY",
        block_time=NOW - timedelta(minutes=1),
    )
    _persist_webhook(db, payload, NOW)
    client = FakeJupiter([
        _order(in_amount=10_000_000, out_amount=1_000_000, threshold=970_000),
    ])
    result = process_gen4_copyability_queue(
        db,
        confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
        owner_id="worker-stale",
        observed_at=NOW,
        jupiter_client=client,
        now_fn=Clock(NOW + timedelta(milliseconds=100)),
    )
    db.commit()
    assert result["summary"]["entries_rejected"] == 1
    position = db.query(CanonicalParserGen4CopyabilityPosition).one()
    assert position.entry_copyable is False
    assert position.entry_rejection_reason == "SIGNAL_TOO_OLD"
    assert position.status != POSITION_OPEN


def test_recovery_only_receipts_are_excluded_from_queue_and_profit_metrics(db):
    campaign = _start(db)
    _configure(db, campaign["campaign_id"])
    record_gen4_copyability_recovery_events(
        db,
        wallet_address=WALLET_A,
        transactions=[{"signature": "only-recovery", "timestamp": int(NOW.timestamp()), "type": "SWAP"}],
        observed_at=NOW + timedelta(minutes=2),
    )
    db.commit()
    client = FakeJupiter([])
    result = process_gen4_copyability_queue(
        db,
        confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
        owner_id="worker-recovery",
        observed_at=NOW + timedelta(minutes=2),
        jupiter_client=client,
    )
    db.commit()
    assert result["summary"]["receipts_processed"] == 0
    status = get_gen4_copyability_status(db, observed_at=NOW + timedelta(minutes=2))
    assert status["campaign"]["counts"]["recovery_receipt_count"] == 1
    assert status["campaign"]["counts"]["closed_trade_count"] == 0
    assert status["campaign"]["metrics"]["recovery_only_receipts"] == 1
    assert client.orders == []


def test_unexpected_receipt_failure_does_not_poison_the_worker_batch(db):
    campaign = _start(db)
    _configure(db, campaign["campaign_id"])
    _persist_webhook(
        db,
        _raw_payload(signature="unexpected-first", side="BUY"),
        NOW + timedelta(seconds=1),
    )
    _persist_webhook(
        db,
        _raw_payload(signature="healthy-second", side="BUY"),
        NOW + timedelta(seconds=2),
    )

    class OneFailureThenSuccess:
        def __init__(self):
            self.calls = 0

        def get_order(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("synthetic unexpected failure")
            return _order(
                in_amount=10_000_000,
                out_amount=1_000_000,
                threshold=970_000,
                impact=0.01,
            )

    result = process_gen4_copyability_queue(
        db,
        confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
        owner_id="worker-savepoint",
        batch_size=20,
        observed_at=NOW + timedelta(seconds=2),
        jupiter_client=OneFailureThenSuccess(),
        now_fn=Clock(NOW + timedelta(seconds=2, milliseconds=100)),
    )
    db.commit()

    assert result["summary"]["failures"] == 1
    assert result["summary"]["entries_opened"] == 1
    receipts = {row.signature: row for row in db.query(CanonicalParserGen4WebhookReceipt).all()}
    assert receipts["unexpected-first"].status == RECEIPT_FAILED
    assert receipts["unexpected-first"].processing_attempts == 1
    assert receipts["healthy-second"].status == RECEIPT_PROCESSED
    assert db.query(CanonicalParserGen4CopyabilityPosition).count() == 1


def test_failed_receipts_stop_retrying_after_frozen_attempt_limit(db):
    campaign = _start(db)
    _configure(db, campaign["campaign_id"])
    _persist_webhook(
        db,
        _raw_payload(signature="always-fails", side="BUY"),
        NOW + timedelta(seconds=1),
    )

    class BrokenJupiter(FakeJupiter):
        def get_order(self, **kwargs):
            self.orders.append(kwargs)
            raise RuntimeError("temporary provider failure")

    client = BrokenJupiter([])
    for attempt in range(5):
        process_gen4_copyability_queue(
            db,
            confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
            owner_id=f"retry-{attempt}",
            observed_at=NOW + timedelta(seconds=attempt + 1),
            jupiter_client=client,
            now_fn=Clock(NOW + timedelta(seconds=attempt + 1, milliseconds=100)),
        )
        db.commit()
    receipt = db.query(CanonicalParserGen4WebhookReceipt).one()
    assert receipt.status == RECEIPT_FAILED
    assert receipt.processing_attempts == 3
    assert len(client.orders) == 3


def test_worker_lease_prevents_parallel_processing(db):
    campaign = _start(db)
    _configure(db, campaign["campaign_id"])
    status = get_gen4_copyability_status(db, observed_at=NOW)
    db.commit()
    worker = status["worker_state"]
    state = db.query(service.CanonicalParserGen4CopyabilityWorkerState).one()
    state.lease_owner = "other-worker"
    state.lease_expires_at = NOW + timedelta(minutes=1)
    db.commit()
    result = process_gen4_copyability_queue(
        db,
        confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
        owner_id="this-worker",
        observed_at=NOW,
        jupiter_client=FakeJupiter([]),
    )
    assert result["status"] == "SKIPPED_LOCKED"
    assert result["owner_id"] == "other-worker"
    assert worker["state_id"] == state.state_id


def test_helius_configurator_preserves_unrelated_webhooks_by_default():
    source = Path("scripts/configure_gen4_copyability_helius_webhook.py").read_text(
        encoding="utf-8"
    )
    assert "selected = exact" in source
    assert "exact or same_wallets" not in source
    assert "Nessun webhook esistente è stato modificato" in source
    assert "GEN4_REPLACE_WEBHOOK_CONFIRMATION" in source


def test_no_runtime_path_calls_jupiter_execute_or_live_engine():
    source = Path("backend/app/services/blockchain_parser_gen4_copyability_service.py").read_text(
        encoding="utf-8"
    )
    runtime = Path("backend/app/services/gen4_copyability_runtime.py").read_text(encoding="utf-8")
    worker = Path("backend/app/workers/gen4_copyability_worker.py").read_text(encoding="utf-8")
    joined = "\n".join([source, runtime, worker])
    assert ".execute_order(" not in joined
    assert "live_copy_trading_engine" not in joined
    assert "signed_transaction=" not in joined
    assert "get_quote_and_unsigned_build" in source


def test_postgresql_migration_harness_uses_effective_database_url(
    tmp_path,
    monkeypatch,
):
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts/test_gen4_copyability_postgresql_migration.py"
    spec = importlib.util.spec_from_file_location(
        "gen4_copyability_migration_harness",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        'DATABASE_URL="postgresql://user:password@localhost:5432/smartmoney"\n',
        encoding="utf-8",
    )
    assert module.resolve_database_url(tmp_path) == (
        "postgresql+psycopg://user:password@localhost:5432/smartmoney"
    )

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://env_user:env_password@localhost:5432/env_db",
    )
    assert module.resolve_database_url(tmp_path).endswith("/env_db")

    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=sqlite+pysqlite:///:memory:\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="PostgreSQL reale"):
        module.resolve_database_url(tmp_path)

    harness_text = script_path.read_text(encoding="utf-8")
    assert 'environment_value = str(os.environ.pop("DATABASE_URL", "")' in harness_text
    assert 'child_env["DATABASE_URL"] = database_url' in harness_text
    assert 'child_env.pop("DATABASE_URL", None)' in harness_text
