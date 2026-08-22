from __future__ import annotations

import inspect
import struct
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.services import gen4_fastpath_shadow_service as service
from backend.app.services import pump_bonding_curve_shadow as pump


def _pubkey(seed: int) -> str:
    return pump._b58encode(bytes(((seed + index) % 256 for index in range(32))))


def _synthetic_payload(*, later_same_mint: bool = False):
    wallet = _pubkey(1)
    mint = _pubkey(40)
    fee_recipient = _pubkey(80)
    creator = _pubkey(120)

    target_spendable = 800_000_000
    target_net = pump._calc_net_lamports(target_spendable, 95, 30)
    pre_virtual_sol = 30_000_000_000
    pre_virtual_token = 1_000_000_000_000_000
    target_tokens = pump._quote_tokens_out(
        net_lamports=target_net,
        virtual_token_reserves=pre_virtual_token,
        virtual_sol_reserves=pre_virtual_sol,
    )
    post_virtual_sol = pre_virtual_sol + target_net
    post_virtual_token = pre_virtual_token - target_tokens
    post_real_token = 700_000_000_000_000

    outer_raw = (
        pump.BUY_EXACT_SOL_IN_DISCRIMINATOR
        + struct.pack("<Q", target_spendable)
        + struct.pack("<Q", max(1, target_tokens * 95 // 100))
        + b"\x01"
    )
    event_raw = bytearray()
    event_raw += pump.EVENT_CPI_DISCRIMINATOR
    event_raw += pump.TRADE_EVENT_DISCRIMINATOR
    event_raw += bytes(((40 + index) % 256 for index in range(32)))
    event_raw += struct.pack("<Q", target_net)
    event_raw += struct.pack("<Q", target_tokens)
    event_raw += b"\x01"
    event_raw += bytes(((1 + index) % 256 for index in range(32)))
    event_raw += struct.pack("<q", 1_777_000_000)
    event_raw += struct.pack("<Q", post_virtual_sol)
    event_raw += struct.pack("<Q", post_virtual_token)
    event_raw += struct.pack("<Q", 1_000_000_000)
    event_raw += struct.pack("<Q", post_real_token)
    event_raw += bytes(((80 + index) % 256 for index in range(32)))
    event_raw += struct.pack("<Q", 95)
    event_raw += struct.pack("<Q", 7_500_000)
    event_raw += bytes(((120 + index) % 256 for index in range(32)))
    event_raw += struct.pack("<Q", 0)
    event_raw += struct.pack("<Q", 0)

    accounts = [_pubkey(160 + index) for index in range(18)]
    accounts[2] = mint
    accounts[6] = wallet

    instructions = [
        {
            "programId": pump.PUMP_PROGRAM_ID,
            "accounts": accounts,
            "data": pump._b58encode(outer_raw),
        }
    ]
    if later_same_mint:
        later_accounts = list(accounts)
        instructions.append(
            {
                "programId": pump.PUMP_PROGRAM_ID,
                "accounts": later_accounts,
                "data": pump._b58encode(b"\x00" * 8),
            }
        )

    payload = {
        "signature": "synthetic-signature",
        "slot": 1,
        "transaction": {
            "signatures": ["synthetic-signature"],
            "message": {
                "accountKeys": [],
                "instructions": instructions,
            },
        },
        "meta": {
            "loadedAddresses": {"writable": [], "readonly": []},
            "innerInstructions": [
                {
                    "index": 0,
                    "instructions": [
                        {
                            "programId": pump.PUMP_PROGRAM_ID,
                            "accounts": [],
                            "data": pump._b58encode(bytes(event_raw)),
                        }
                    ],
                }
            ],
        },
    }
    wallet_effective_price = (
        (target_spendable / pump.LAMPORTS_PER_SOL)
        / (target_tokens / 1_000_000)
    )
    return payload, wallet, mint, wallet_effective_price


def test_fee_inference_recovers_redirected_30bps_exactly():
    for spendable in (10_000_000, 600_000_000, 800_000_000, 1_300_000_000):
        curve_net = pump._calc_net_lamports(spendable, 95, 30)
        assert (
            pump._infer_secondary_fee_bps(
                spendable_lamports=spendable,
                curve_net_lamports=curve_net,
                protocol_fee_bps=95,
            )
            == 30
        )


def test_pump_shadow_quote_is_local_available_and_does_not_mutate_canonical():
    payload, wallet, mint, wallet_price = _synthetic_payload()
    result = pump.quote_pump_buy_exact_sol_in_shadow(
        payload,
        wallet_address=wallet,
        token_mint=mint,
        token_decimals=6,
        wallet_effective_price_sol=wallet_price,
        simulated_input_lamports=10_000_000,
        slippage_bps=300,
    )
    assert result["available"] is True
    assert result["provider_api_calls"] == 0
    assert result["rpc_reads"] == 0
    assert result["transaction_built"] is False
    assert result["canonical_acceptance_mutated"] is False
    assert result["inferred_secondary_fee_bps"] == 30
    assert result["secondary_fee_interpretation"] == "REDIRECTED_OR_CASHBACK_FEE"
    assert result["expected_out_raw"] > 0
    assert result["conservative_out_raw"] > 0
    assert result["pam_pass"] is True
    assert result["live_execution"] is False
    assert result["signer_access"] is False


def test_pump_shadow_fails_closed_when_same_transaction_moves_same_mint_later():
    payload, wallet, mint, wallet_price = _synthetic_payload(
        later_same_mint=True
    )
    result = pump.quote_pump_buy_exact_sol_in_shadow(
        payload,
        wallet_address=wallet,
        token_mint=mint,
        token_decimals=6,
        wallet_effective_price_sol=wallet_price,
        simulated_input_lamports=10_000_000,
        slippage_bps=300,
    )
    assert result["available"] is False
    assert result["reason"] == "LATER_SAME_MINT_PUMP_INSTRUCTION"
    assert result["provider_api_calls"] == 0
    assert result["canonical_acceptance_mutated"] is False


def _candidate_row(*, pump_shadow, canonical_copyable: bool):
    now = datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        signature=f"sig-{id(pump_shadow)}",
        wallet_address="CANDIDATE",
        side="BUY",
        fast_received_at=now,
        fast_prequote_ms=1,
        fast_quote_latency_ms=500,
        fast_quote_received_at=now,
        fast_end_to_quote_ms=None,
        fast_lead_vs_webhook_ms=None,
        confirmed_path_end_to_quote_ms=None,
        fast_price_deterioration_bps=(500.0 if canonical_copyable else 1500.0),
        fast_price_impact_bps=10.0,
        fast_out_amount=100,
        fast_transaction_built=True,
        fast_provisional_copyable=canonical_copyable,
        fast_provisional_rejection_reason=(
            None if canonical_copyable else "PRICE_ALREADY_MOVED"
        ),
        fast_reconciled_copyable=None,
        fast_reconciled_rejection_reason=None,
        webhook_reconciled_at=None,
        parse_error_code=None,
        quote_error_code=None,
        evidence={
            "observation_scope": service.FASTPATH_CANDIDATE_SCOPE,
            "pump_shadow": pump_shadow,
        },
    )


def test_candidate_status_exposes_ab_without_changing_canonical_counts(monkeypatch):
    monkeypatch.setattr(
        service,
        "configured_fastpath_candidate_wallets",
        lambda: ["CANDIDATE"],
    )
    available = {
        "available": True,
        "quote_latency_ms": 0.25,
        "price_deterioration_bps": 500.0,
        "diagnostic_curve_impact_bps": 3.0,
        "pam_pass": True,
        "diagnostic_quote_pass": True,
    }
    unavailable = {
        "available": False,
        "reason": "DIRECT_BUY_EXACT_SOL_IN_COUNT_0",
        "quote_latency_ms": 0.05,
    }
    rows = [
        _candidate_row(pump_shadow=available, canonical_copyable=False),
        _candidate_row(pump_shadow=unavailable, canonical_copyable=True),
    ]
    status = service._candidate_status(rows, recent_limit=50)

    assert status["buy_count"] == 2
    assert status["provisional_copyable_count"] == 1
    assert status["entry_acceptance_rate_percent"] == 50.0
    assert status["pump_shadow_ab"]["attempted_buy_count"] == 2
    assert status["pump_shadow_ab"]["available_quote_count"] == 1
    assert status["pump_shadow_ab"]["pam_pass_count"] == 1
    assert status["pump_shadow_ab"]["canonical_acceptance_mutated"] is False
    assert status["pump_shadow_ab"]["m75_forward_pass"] is False
    assert status["recent"][0]["pump_shadow"] is not None


def test_pump_shadow_module_has_no_network_signing_or_submission_dependencies():
    source = inspect.getsource(pump)
    forbidden = (
        "httpx",
        "urllib.request",
        "requests.",
        "JupiterSwapClient",
        "execute_order",
        "sendTransaction",
        "send_raw_transaction",
        "Keypair",
    )
    for token in forbidden:
        assert token not in source
