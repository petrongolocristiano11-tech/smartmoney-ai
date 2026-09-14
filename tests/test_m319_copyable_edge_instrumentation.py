from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.services import blockchain_parser_gen4_copyability_service as parser
from backend.app.services import gen4_fastpath_shadow_runtime as runtime_module
import backend.app.services.gen4_fastpath_shadow_service as service


WALLET = "D7Z3ZkAjMnbvjq151vAd8xGfxA636zYz8WMb8DuvEqjd"
TOKEN = "5mHL4MEaATdQoTwLPgAbk9boaK2SUk18WEGB7okZpump"


def test_m319_raw_effective_price_supports_buy_and_sell_symmetrically():
    buy = parser._wallet_effective_price_sol_from_raw(
        side="BUY",
        sol_equivalent_delta_lamports=-10_100_000,
        token_delta_raw=1_000_000,
        token_decimals=6,
        fee_lamports=100_000,
    )
    sell = parser._wallet_effective_price_sol_from_raw(
        side="SELL",
        sol_equivalent_delta_lamports=9_900_000,
        token_delta_raw=-1_000_000,
        token_decimals=6,
        fee_lamports=100_000,
    )
    assert buy == 0.01
    assert sell == 0.01
    assert "_wallet_effective_price_sol_from_raw" in inspect.getsource(
        parser.parse_raw_copyability_signal
    )


def test_m319_wss_normalizer_preserves_block_time_when_provider_supplies_it():
    message = {
        "params": {
            "result": {
                "signature": "SIG1",
                "slot": 123,
                "blockTime": 1_789_000_000,
                "transaction": {
                    "meta": {},
                    "transaction": {
                        "signatures": ["SIG1"],
                        "message": {"accountKeys": []},
                    },
                },
            }
        }
    }
    payload = service.normalize_helius_transaction_notification(message)
    assert payload["slot"] == 123
    assert payload["blockTime"] == 1_789_000_000


def _signal(*, side="BUY", block_time=None, effective=0.01):
    return SimpleNamespace(
        signature="SIG1",
        slot=123,
        block_time=block_time,
        wallet_address=WALLET,
        side=side,
        token_mint=TOKEN,
        token_decimals=6,
        token_delta_raw=(1_000_000 if side == "BUY" else -1_000_000),
        token_pre_raw=(0 if side == "BUY" else 1_000_000),
        sol_equivalent_delta_lamports=(-10_100_000 if side == "BUY" else 9_900_000),
        wallet_effective_price_sol=effective,
        sell_fraction=(None if side == "BUY" else 1.0),
        evidence={"fee_lamports": 100_000},
    )


def test_m319_candidate_observation_captures_end_to_end_components_without_gate():
    received = datetime(2026, 9, 14, 18, 0, 1, tzinfo=timezone.utc)
    block = received - timedelta(milliseconds=800)
    parsed = received + timedelta(milliseconds=25)
    event = SimpleNamespace(
        slot=123,
        fast_received_at=received,
        evidence={"observation_scope": service.FASTPATH_CANDIDATE_SCOPE},
    )
    observation = service._new_m319_candidate_observation(
        event=event,
        signal=_signal(block_time=block),
        received_at=received,
        parsed_at=parsed,
    )
    assert observation["observation_only"] is True
    assert observation["backfill"] is False
    assert observation["automatic_filtering"] is False
    assert observation["automatic_promotion"] is False
    assert observation["chain_to_receive_ms"] == 800
    assert observation["receive_to_parse_ms"] == 25
    assert observation["source_trade"]["wallet_effective_price_sol"] == 0.01

    service._m319_set_candidate_observation(event, observation)
    quote = SimpleNamespace(
        requested_at=received + timedelta(milliseconds=30),
        received_at=received + timedelta(milliseconds=430),
        latency_ms=400,
        result=SimpleNamespace(transaction="unsigned"),
    )
    service._m319_update_buy_quote(
        event,
        quote=quote,
        deterioration_bps=125.0,
        price_impact_bps=30.0,
        rejection_reason=None,
    )
    current = event.evidence[service.M319_COPYABLE_EDGE_EVIDENCE_KEY]
    assert current["follower_entry"]["receive_to_quote_received_ms"] == 430
    assert current["follower_entry"]["chain_to_quote_received_ms"] == 1230
    assert current["follower_entry"]["price_deterioration_bps"] == 125.0
    assert service.M314_CANDIDATE_ROUNDTRIP_GATE_ARMED is False


class _ReconDB:
    def __init__(self, rows, receipt):
        self.rows = list(rows)
        self.receipt = receipt
        self.scalar_calls = 0

    def scalars(self, _statement):
        return list(self.rows)

    def scalar(self, _statement):
        self.scalar_calls += 1
        return self.receipt


def _candidate_row(observation, received):
    return SimpleNamespace(
        id=1,
        event_id="E1",
        signature="SIG1",
        slot=123,
        evidence={
            "observation_scope": service.FASTPATH_CANDIDATE_SCOPE,
            service.M319_COPYABLE_EDGE_EVIDENCE_KEY: observation,
        },
        fast_received_at=received,
        fast_parse_completed_at=received + timedelta(milliseconds=20),
        fast_quote_received_at=received + timedelta(milliseconds=420),
        webhook_received_at=None,
        webhook_block_time=None,
        webhook_reconciled_at=None,
        fast_lead_vs_webhook_ms=None,
        fast_end_to_quote_ms=None,
    )


def test_m319_candidate_reconcile_uses_existing_webhook_receipt_forward_only():
    received = datetime(2026, 9, 14, 18, 0, 1, tzinfo=timezone.utc)
    parsed = received + timedelta(milliseconds=20)
    observation = service._new_m319_candidate_observation(
        event=SimpleNamespace(slot=123),
        signal=_signal(block_time=None),
        received_at=received,
        parsed_at=parsed,
    )
    row = _candidate_row(observation, received)
    receipt = SimpleNamespace(
        received_at=received + timedelta(milliseconds=900),
        block_time=received - timedelta(milliseconds=750),
    )
    db = _ReconDB([row], receipt)
    result = service.reconcile_m319_candidate_edge_instrumentation(
        db,
        limit=10,
        now=received + timedelta(seconds=2),
    )
    current = row.evidence[service.M319_COPYABLE_EDGE_EVIDENCE_KEY]
    assert result["reconciled_m319_candidate_rows"] == 1
    assert result["provider_calls"] == 0
    assert result["backfill"] is False
    assert row.webhook_reconciled_at is not None
    assert current["source_block_time_origin"] == "RAW_WEBHOOK_RECEIPT"
    assert current["chain_to_receive_ms"] == 750
    assert current["follower_entry"] is None
    assert current["reconciliation"]["matched_raw_webhook"] is True


def test_m319_reconcile_never_backfills_historical_candidate_without_marker():
    received = datetime(2026, 9, 14, 18, 0, 1, tzinfo=timezone.utc)
    row = SimpleNamespace(
        id=1,
        event_id="OLD",
        signature="OLDSIG",
        evidence={"observation_scope": service.FASTPATH_CANDIDATE_SCOPE},
        fast_received_at=received,
        fast_parse_completed_at=received,
        fast_quote_received_at=None,
        webhook_reconciled_at=None,
    )
    db = _ReconDB([row], None)
    result = service.reconcile_m319_candidate_edge_instrumentation(
        db,
        limit=10,
        now=received + timedelta(seconds=1),
    )
    assert result["checked_m319_candidate_rows"] == 0
    assert db.scalar_calls == 0
    assert service.M319_COPYABLE_EDGE_EVIDENCE_KEY not in row.evidence


def test_m319_runtime_reconciles_candidate_instrumentation_without_new_provider_loop():
    source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime._reconcile)
    assert "reconcile_fastpath_events" in source
    assert "reconcile_m319_candidate_edge_instrumentation" in source
    assert "db.commit()" in source
