from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
os.environ.setdefault("HELIUS_API_KEY", "test-m64-not-used")

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_EXPECTED_DATABASE,
    M64_OFFICIAL_REALTIME_TRADES,
    M64_TARGET_RECONSTRUCTED_TRADES,
    M64_TARGET_WALLET,
    M64ReadonlyAuditError,
    PublicSolanaRpc,
    build_audit_report,
    calculate_trade_metrics,
    canonical_sha256,
    parse_public_transactions,
    readonly_database_url,
    reconstruct_closed_trades,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "m64_gen4_closed_trade_readonly_audit.json"
)
NOW = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)


def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_sanitized_fixture_uses_m62_parser_and_preserves_full_signatures():
    payload = fixture()
    parsed = parse_public_transactions(
        payload["transactions"],
        wallet_address=M64_TARGET_WALLET,
    )

    assert len(parsed["events"]) == 5
    assert len(parsed["rejected"]) == 1
    assert parsed["rejected"][0]["error_code"] == (
        "GEN4_COPYABILITY_RAW_NO_SPECULATIVE_TOKEN_DELTA"
    )
    assert parsed["events"][0]["signature"] == "m64-buy-a-full-signature"
    assert all(len(item["transaction_sha256"]) == 64 for item in parsed["events"])
    assert {item["price_basis"] for item in parsed["events"]} == {
        "SAME_TRANSACTION_SOL_OR_WSOL_AND_TOKEN_DELTAS"
    }


def test_round_trip_reconstruction_is_chronological_partial_exit_aware_and_fail_closed():
    payload = fixture()
    parsed = parse_public_transactions(
        payload["transactions"],
        wallet_address=M64_TARGET_WALLET,
    )
    result = reconstruct_closed_trades(
        list(reversed(parsed["events"])),
        policy=payload["policy"],
        target_closed_trades=M64_TARGET_RECONSTRUCTED_TRADES,
    )

    assert result["selected_closed_trade_count"] == 2
    assert result["target_reached"] is False
    assert result["open_positions_at_end"] == []
    assert result["selected_trades"][0]["entry_signature"] == (
        "m64-buy-a-full-signature"
    )
    assert result["selected_trades"][0]["exit_signatures"] == [
        "m64-sell-a-half-full-signature",
        "m64-sell-a-rest-full-signature",
    ]
    assert result["selected_trades"][0]["pnl_lamports"] > 0
    assert result["selected_trades"][1]["pnl_lamports"] < 0
    assert result["historical_entry_admission"]["entry_reject_rate_percent"] is None
    assert result["historical_entry_admission"]["price_already_moved_count"] is None
    assert all(
        item["historical_jupiter_quote"] == "UNAVAILABLE_NOT_INVENTED"
        for item in result["selected_trades"]
    )
    assert all(
        item["evidence_sha256"]
        == canonical_sha256(
            {key: value for key, value in item.items() if key != "evidence_sha256"}
        )
        for item in result["selected_trades"]
    )


def _event(index: int, side: str, token: str) -> dict:
    buy = side == "BUY"
    sequence = index * 2 + (0 if buy else 1)
    timestamp = NOW + timedelta(seconds=sequence)
    return {
        "sequence": sequence,
        "signature": f"m64-{side.lower()}-{index}-full-signature",
        "slot": 500000000 + sequence,
        "block_time": timestamp.isoformat(),
        "wallet_address": M64_TARGET_WALLET,
        "side": side,
        "token_mint": token,
        "token_decimals": 6,
        "token_delta_raw": 100_000_000 if buy else -100_000_000,
        "token_pre_raw": 0 if buy else 100_000_000,
        "sell_fraction": None if buy else 1.0,
        "sol_equivalent_delta_lamports": -10_100_000 if buy else 12_000_000,
        "source_network_fee_lamports": 100_000,
        "transaction_sha256": f"{index:064x}",
        "parser_version": "canonical-parser-gen4-raw-balance-delta/4",
        "price_basis": "SAME_TRANSACTION_SOL_OR_WSOL_AND_TOKEN_DELTAS",
    }


def test_first_seventeen_closures_are_selected_without_turning_extra_history_into_proof():
    events = []
    for index in range(18):
        token = f"M64Token{index:02d}" + "A" * 30
        events.extend([_event(index, "BUY", token), _event(index, "SELL", token)])
    result = reconstruct_closed_trades(
        events,
        policy=fixture()["policy"],
        target_closed_trades=M64_TARGET_RECONSTRUCTED_TRADES,
    )

    assert result["all_reconstructed_closed_trade_count"] == 18
    assert result["selected_closed_trade_count"] == 17
    assert result["target_reached"] is True
    assert result["selected_trades"][-1]["entry_signature"] == (
        "m64-buy-16-full-signature"
    )


def test_target_cutoff_extends_only_the_same_close_batch_for_sensitivity():
    token = "M64SharedCloseBatch" + "A" * 30
    events = [_event(index, "BUY", token) for index in range(18)]
    close = _event(99, "SELL", token)
    close["token_delta_raw"] = -1_800_000_000
    close["token_pre_raw"] = 1_800_000_000
    close["sol_equivalent_delta_lamports"] = 216_000_000
    events.append(close)

    result = reconstruct_closed_trades(
        events,
        policy=fixture()["policy"],
        target_closed_trades=M64_TARGET_RECONSTRUCTED_TRADES,
    )

    assert result["selected_closed_trade_count"] == 17
    assert result["all_reconstructed_closed_trade_count"] == 18
    assert result["complete_close_batch_trade_count"] == 18
    assert result["supplemental_cutoff_batch_trade_count"] == 1
    assert result["target_cut_through_close_batch"] is True
    assert result["supplemental_cutoff_batch_trades"][0]["entry_signature"] == (
        "m64-buy-17-full-signature"
    )
    assert all(
        item["evidence_sha256"]
        == canonical_sha256(
            {key: value for key, value in item.items() if key != "evidence_sha256"}
        )
        for item in (
            result["selected_trades"]
            + result["supplemental_cutoff_batch_trades"]
        )
    )


def test_quarantined_realtime_entry_seed_is_replayed_without_a_public_rebuy():
    payload = fixture()
    parsed = parse_public_transactions(
        payload["transactions"],
        wallet_address=M64_TARGET_WALLET,
    )
    token = next(item["token_mint"] for item in parsed["events"] if item["side"] == "SELL")
    sell_events = [
        item
        for item in parsed["events"]
        if item["side"] == "SELL" and item["token_mint"] == token
    ]
    seed = {
        "entry_signature": "m64-quarantined-realtime-entry",
        "token_mint": token,
        "token_decimals": 6,
        "entry_signal_at": "2026-08-12T17:59:00+00:00",
        "entry_sequence": -1,
        "entry_input_lamports": 10_000_000,
        "entry_expected_output_token_raw": 103_092_783,
        "entry_conservative_output_token_raw": 100_000_000,
        "entry_output_token_raw": 100_000_000,
        "allocated_entry_fee_lamports": 100_000,
    }

    result = reconstruct_closed_trades(
        sell_events,
        policy=payload["policy"],
        target_closed_trades=17,
        seed_positions=[seed],
    )

    assert result["seeded_open_position_count"] == 1
    assert result["ignored_sell_events"] == 0
    assert result["selected_closed_trade_count"] == 1
    trade = result["selected_trades"][0]
    assert trade["entry_signature"] == seed["entry_signature"]
    assert trade["entry_evidence_class"].startswith("EXACT_REALTIME")
    assert trade["pricing_quality"] == (
        "EXACT_REALTIME_ENTRY_QUOTE_PLUS_ESTIMATED_ONCHAIN_EXIT_PROXY"
    )


def test_metrics_match_gen4_profit_factor_and_drawdown_method():
    trades = [
        {
            "entry_signature": "one",
            "closed_at": "2026-08-12T00:00:01+00:00",
            "pnl_lamports": 300,
            "cost_lamports": 1000,
            "fee_lamports": 20,
            "return_percent": 30.0,
        },
        {
            "entry_signature": "two",
            "closed_at": "2026-08-12T00:00:02+00:00",
            "pnl_lamports": -200,
            "cost_lamports": 1000,
            "fee_lamports": 20,
            "return_percent": -20.0,
        },
        {
            "entry_signature": "three",
            "closed_at": "2026-08-12T00:00:03+00:00",
            "pnl_lamports": 100,
            "cost_lamports": 1000,
            "fee_lamports": 20,
            "return_percent": 10.0,
        },
    ]
    metrics = calculate_trade_metrics(trades, evidence_quality="TEST")

    assert metrics["net_pnl_lamports"] == 200
    assert metrics["gross_profit_lamports"] == 400
    assert metrics["gross_loss_lamports"] == 200
    assert metrics["profit_factor"] == 2.0
    assert metrics["win_rate_percent"] == pytest.approx(66.66666667)
    assert metrics["maximum_drawdown_lamports"] == 200
    assert metrics["total_allocated_fees_lamports"] == 60


def test_drawdown_tie_break_matches_production_entry_sequence():
    same_close = "2026-08-12T00:00:01+00:00"
    trades = [
        {
            "entry_signature": "z-positive-first",
            "entry_sequence": 10,
            "entry_signal_at": "2026-08-11T23:00:00+00:00",
            "closed_at": same_close,
            "close_sequence": 50,
            "pnl_lamports": 100,
            "cost_lamports": 1000,
            "fee_lamports": 0,
            "return_percent": 10.0,
        },
        {
            "entry_signature": "a-negative-second",
            "entry_sequence": 11,
            "entry_signal_at": "2026-08-11T23:01:00+00:00",
            "closed_at": same_close,
            "close_sequence": 50,
            "pnl_lamports": -300,
            "cost_lamports": 1000,
            "fee_lamports": 0,
            "return_percent": -30.0,
        },
    ]

    metrics = calculate_trade_metrics(trades, evidence_quality="TEST")

    assert metrics["maximum_drawdown_lamports"] == 300
    assert metrics["equity_curve"][0]["entry_signature"] == "z-positive-first"


def test_database_url_is_forced_to_logical_database_and_server_read_only():
    url = readonly_database_url(
        "postgresql://readonly-user:secret-value@example.invalid:5432/railway"
    )

    assert url.database == M64_EXPECTED_DATABASE
    assert url.drivername == "postgresql+psycopg"
    assert "default_transaction_read_only=on" in url.query["options"]
    assert "secret-value" not in str(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://mainnet.helius-rpc.com/?api-key=forbidden",
        "https://user:password@api.mainnet-beta.solana.com",
        "http://api.mainnet-beta.solana.com",
    ],
)
def test_rpc_rejects_helius_credentials_and_plain_http(url: str):
    with pytest.raises(M64ReadonlyAuditError):
        PublicSolanaRpc(url)


class FakeClient:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def response(status: int, body: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=body,
        headers=headers,
        request=httpx.Request("POST", "https://api.mainnet-beta.solana.com"),
    )


def test_public_rpc_honors_429_retry_after_and_counts_requests_without_helius():
    sleeps = []
    client = FakeClient(
        [
            response(429, {}, {"Retry-After": "0.01"}),
            response(200, {"jsonrpc": "2.0", "id": 2, "result": []}),
        ]
    )
    rpc = PublicSolanaRpc(
        "https://api.mainnet-beta.solana.com",
        client=client,
        throttle_seconds=0,
        sleep_fn=sleeps.append,
    )

    assert rpc.call("getSignaturesForAddress", [M64_TARGET_WALLET, {}]) == []
    assert rpc.requests == 2
    assert rpc.retry_429 == 1
    assert rpc.stats()["helius_requests"] == 0
    assert sleeps


def _official_trade(index: int) -> dict:
    pnl = 100_000 if index % 2 == 0 else -50_000
    return {
        "entry_signature": f"official-entry-{index}",
        "last_exit_signature": f"official-exit-{index}",
        "token_mint": f"OfficialToken{index}",
        "closed_at": (NOW + timedelta(minutes=index)).isoformat(),
        "pnl_lamports": pnl,
        "cost_lamports": 10_100_000,
        "fee_lamports": 200_000,
        "return_percent": pnl / 10_100_000 * 100.0,
    }


def test_report_keeps_83_official_separate_and_marks_combined_as_analytic_only():
    parsed = parse_public_transactions(
        fixture()["transactions"],
        wallet_address=M64_TARGET_WALLET,
    )
    reconstructed = reconstruct_closed_trades(
        parsed["events"],
        policy=fixture()["policy"],
        target_closed_trades=17,
    )
    official = {
        "database": {
            "database_name": "smartmoney_gen4",
            "transaction_read_only": "on",
            "alembic_head": "c8a1f3d6e942",
        },
        "campaign": {
            **fixture()["policy"],
            "official_admission_attempt_count": 92,
            "rejected_entry_count_observed": 9,
            "official_entry_reject_rate_percent": 9 / 92 * 100.0,
        },
        "boundary": {
            "after_utc": "2026-08-10T19:50:19+00:00",
            "after_signature": "full-frozen-boundary-signature",
        },
        "containment": {
            "public_rpc_recovery_counts_as_realtime_proof": False
        },
        "official_trades": [_official_trade(index) for index in range(83)],
    }
    public_result = {
        "boundary_reached": True,
        "signature_limit_reached": False,
        "signatures": [{} for _ in fixture()["transactions"]],
        "transactions": fixture()["transactions"],
        "unavailable": [],
    }
    report = build_audit_report(
        official_snapshot=official,
        public_result=public_result,
        parser_result=parsed,
        reconstruction=reconstructed,
        rpc_stats={"requests": 7, "helius_requests": 0},
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        raw_evidence_sha256="a" * 64,
    )

    assert report["samples"]["official_realtime"]["closed_trade_count"] == 83
    assert report["samples"]["reconstructed"]["closed_trade_count"] == 2
    assert report["samples"]["combined_equivalent"]["closed_trade_count"] == 85
    assert report["samples"]["combined_equivalent"]["target_100_reached"] is False
    assert report["samples"]["combined_equivalent"]["evidence_class"] == (
        "ANALYTIC_EQUIVALENT_NOT_OFFICIAL_REALTIME_PROOF"
    )
    assert report["samples"]["cutoff_complete_batch_sensitivity"][
        "closed_trade_count"
    ] == 85
    assert report["samples"]["cutoff_complete_batch_sensitivity"][
        "target_cut_through_close_batch"
    ] is False
    assert report["safety"]["helius_requests"] == 0
    assert report["safety"]["database_writes"] == 0
    assert report["safety"]["backend_posts"] == 0
    assert report["evidence_quality"]["historical_jupiter_quotes"] == (
        "UNAVAILABLE_NOT_INVENTED"
    )
    assert report["verdict"]["official_realtime_counter_remains"] == (
        M64_OFFICIAL_REALTIME_TRADES
    )
