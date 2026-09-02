from __future__ import annotations

from datetime import datetime, timedelta, timezone

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4PromotedSelectiveActivation,
    CanonicalParserGen4PromotedSelectiveDeliveryReceipt,
)
from backend.app.services import blockchain_parser_gen4_copyability_service as receiver_service
from backend.app.services.gen4_post_anchor_selective_evidence_service import (
    build_promoted_wallet_evidence,
)
from backend.app.services.gen4_promoted_selective_coverage_service import (
    build_existing_raw_webhook_update,
)

WALLET = "89f3DSmRiFsAZWQXCQMYPwyEUtxbVeCDP7JEjsXrbWST"
TOKEN = "Token111111111111111111111111111111111111"


def _policy() -> dict:
    return {
        "simulated_input_lamports": 10_000_000,
        "slippage_bps": 300,
        "max_quote_latency_ms": 5_000,
        "max_price_impact_bps": 500,
        "max_price_deterioration_bps": 1_000,
        "estimated_network_fee_lamports": 100_000,
        "live_execution": False,
        "paper_execution": False,
        "automatic_live_activation": False,
    }


def _event(sig: str, when: datetime) -> dict:
    return {
        "signature": sig,
        "wallet_address": WALLET,
        "side": "BUY",
        "fast_received_at": when,
        "fast_quote_received_at": when + timedelta(milliseconds=500),
        "fast_prequote_ms": 20,
        "fast_quote_latency_ms": 480,
        "fast_end_to_quote_ms": None,
        "fast_price_deterioration_bps": 100.0,
        "fast_price_impact_bps": 10.0,
        "fast_transaction_built": True,
        "fast_provisional_copyable": True,
        "fast_provisional_rejection_reason": None,
        "parse_error_code": None,
        "quote_error_code": None,
        "evidence": {"promoted_selective_lifecycle": {"entry_eligible": True, "policy_violation": False}},
    }


def _receipt(sig: str, when: datetime, activation_id: str) -> dict:
    return {
        "activation_id": activation_id,
        "wallet_address": WALLET,
        "signature": sig,
        "source": "WEBHOOK",
        "auth_verified": True,
        "block_time": when,
        "received_at": when + timedelta(seconds=1),
        "raw_payload": {},
    }


def _positions(events: list[dict], activation_id: str) -> list[dict]:
    return [
        {
            "activation_id": activation_id,
            "scope": "PROMOTED_CANDIDATE_FASTPATH_SELECTIVE",
            "wallet_address": WALLET,
            "entry_signature": events[i]["signature"],
            "entry_received_at": events[i]["fast_received_at"],
            "status": "CLOSED",
            "remaining_token_raw": 0,
            "entry_input_lamports": 10_000_000,
            "allocated_entry_fee_lamports": 100_000,
            "pnl_lamports": 1_000_000,
            "exit_copyable": True,
            "closed_at": events[i]["fast_received_at"] + timedelta(minutes=5),
            "evidence": {"exit_failures": []},
        }
        for i in range(10)
    ]


def _raw_buy(sig: str, when: datetime) -> dict:
    return {
        "signature": sig,
        "slot": 1,
        "blockTime": int(when.timestamp()),
        "transaction": {
            "signatures": [sig],
            "message": {"accountKeys": [WALLET]},
        },
        "meta": {
            "err": None,
            "fee": 5_000,
            "preBalances": [10_000_000],
            "postBalances": [8_995_000],
            "preTokenBalances": [],
            "postTokenBalances": [
                {
                    "accountIndex": 0,
                    "owner": WALLET,
                    "mint": TOKEN,
                    "uiTokenAmount": {"amount": "1000000", "decimals": 6},
                }
            ],
        },
    }


def test_m309_is_single_head_extending_m307():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["f6e9c2d4f581"]
    revision = scripts.get_revision("f6e9c2d4f581")
    assert revision.down_revision == "f5d8b1c3e470"


def test_provider_update_preserves_complete_raw_webhook_contract():
    detail = {
        "webhookID": "w1",
        "webhookURL": "https://example.test/integrity/parser-gen4-copyability/webhook/helius",
        "transactionTypes": ["ANY"],
        "accountAddresses": ["OLD"],
        "webhookType": "raw",
        "authHeader": "secret",
        "txnStatus": "success",
        "encoding": "jsonParsed",
        "active": True,
    }
    body = build_existing_raw_webhook_update(detail, account_addresses=["OLD", WALLET])
    assert body["accountAddresses"] == sorted(["OLD", WALLET])
    assert body["transactionTypes"] == ["ANY"]
    assert body["webhookType"] == "raw"
    assert body["authHeader"] == "secret"
    assert body["txnStatus"] == "success"
    assert body["encoding"] == "jsonParsed"
    assert "webhookID" not in body


def test_receiver_persists_authenticated_promoted_receipt_without_legacy_campaign(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    CanonicalParserGen4PromotedSelectiveActivation.__table__.create(engine)
    CanonicalParserGen4PromotedSelectiveDeliveryReceipt.__table__.create(engine)
    anchor = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(receiver_service, "_active_copyability_campaigns", lambda db: [])
    with Session(engine) as db:
        activation = CanonicalParserGen4PromotedSelectiveActivation(
            activation_id="a" * 36,
            wallet_address=WALLET,
            status="ACTIVE",
            activation_anchor_at=anchor,
            decision_envelope_sha256="d" * 64,
            formal_m306_report_sha256="e" * 64,
            policy_hash="f" * 64,
            policy_snapshot=_policy(),
            decision_envelope={},
            evidence={},
            draining_at=None,
            stopped_at=None,
        )
        db.add(activation)
        db.flush()
        result = receiver_service.receive_gen4_copyability_webhook(
            db,
            payload=_raw_buy("RAW1", anchor + timedelta(minutes=1)),
            received_at=anchor + timedelta(minutes=1, seconds=1),
        )
        db.flush()
        rows = list(db.scalars(select(CanonicalParserGen4PromotedSelectiveDeliveryReceipt)))
        assert result["accepted"] == 0
        assert result["promoted_accepted"] == 1
        assert result["promoted_duplicates"] == 0
        assert result["promoted_activations_touched"] == ["a" * 36]
        assert len(rows) == 1
        assert rows[0].auth_verified is True
        assert rows[0].source == "WEBHOOK"
        assert rows[0].signature == "RAW1"


def test_exact_95_percent_authenticated_coverage_satisfies_m298_coverage_check():
    anchor = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    activation_id = "a" * 36
    activation = {"activation_id": activation_id, "activation_anchor_at": anchor, "policy_snapshot": _policy()}
    events = [_event(f"SIG{i}", anchor + timedelta(minutes=30 + i * 60)) for i in range(20)]
    receipts = [_receipt(f"SIG{i}", events[i]["fast_received_at"], activation_id) for i in range(19)]
    result = build_promoted_wallet_evidence(
        wallet=WALLET,
        events=events,
        positions=_positions(events, activation_id),
        activation=activation,
        terminal_at=anchor + timedelta(hours=25),
        delivery_receipts=receipts,
    )
    row = result["wallet_evidence"]
    evaluation = result["m298_individual_evaluation"]
    assert row["webhook_coverage_percent"] == 95.0
    assert row["technical_failures"] == 0
    assert evaluation["checks"]["webhook_coverage"] is True
    assert evaluation["passed"] is True
    assert result["coverage_blocker"] is None


def test_90_percent_authenticated_coverage_fails_closed():
    anchor = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    activation_id = "a" * 36
    activation = {"activation_id": activation_id, "activation_anchor_at": anchor, "policy_snapshot": _policy()}
    events = [_event(f"SIG{i}", anchor + timedelta(minutes=30 + i * 60)) for i in range(20)]
    receipts = [_receipt(f"SIG{i}", events[i]["fast_received_at"], activation_id) for i in range(18)]
    result = build_promoted_wallet_evidence(
        wallet=WALLET,
        events=events,
        positions=_positions(events, activation_id),
        activation=activation,
        terminal_at=anchor + timedelta(hours=25),
        delivery_receipts=receipts,
    )
    assert result["wallet_evidence"]["webhook_coverage_percent"] == 90.0
    assert result["m298_individual_evaluation"]["checks"]["webhook_coverage"] is False
    assert result["m298_individual_evaluation"]["passed"] is False
    assert result["coverage_blocker"] == "AUTHENTICATED_WEBHOOK_COVERAGE_BELOW_M298_THRESHOLD"


def test_webhook_only_parseable_buy_is_delivery_gap_technical_evidence():
    anchor = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    activation_id = "a" * 36
    activation = {"activation_id": activation_id, "activation_anchor_at": anchor, "policy_snapshot": _policy()}
    events = [_event(f"SIG{i}", anchor + timedelta(minutes=30 + i * 60)) for i in range(20)]
    receipts = [_receipt(f"SIG{i}", events[i]["fast_received_at"], activation_id) for i in range(20)]
    gap_at = anchor + timedelta(hours=22)
    receipts.append({
        "activation_id": activation_id,
        "wallet_address": WALLET,
        "signature": "WEBHOOK_ONLY_BUY",
        "source": "WEBHOOK",
        "auth_verified": True,
        "block_time": gap_at,
        "received_at": gap_at + timedelta(seconds=1),
        "raw_payload": _raw_buy("WEBHOOK_ONLY_BUY", gap_at),
    })
    result = build_promoted_wallet_evidence(
        wallet=WALLET,
        events=events,
        positions=_positions(events, activation_id),
        activation=activation,
        terminal_at=anchor + timedelta(hours=25),
        delivery_receipts=receipts,
    )
    assert result["wallet_evidence"]["webhook_coverage_percent"] == 100.0
    assert result["wallet_evidence"]["technical_failures"] == 0
    assert result["wallet_evidence"]["unresolved_failures"] == 1
    assert result["m298_individual_evaluation"]["checks"]["zero_technical_failures"] is True
    assert result["m298_individual_evaluation"]["checks"]["zero_unresolved_failures"] is False
    assert result["m298_individual_evaluation"]["passed"] is False
    assert result["coverage_blocker"] == "WEBHOOK_ONLY_BUY_GAP_TECHNICAL_EVIDENCE"
