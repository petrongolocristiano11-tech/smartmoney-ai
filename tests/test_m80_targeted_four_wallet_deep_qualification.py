from __future__ import annotations

from pathlib import Path

from backend.app.services.gen4_targeted_deep_qualification_service import (
    MAX_SIGNATURES_BY_WALLET,
    M80_PUBLIC_RPC_REQUEST_CAP,
    M80_REQUIRED_QUALIFIED_WALLETS,
    TARGET_WALLETS,
    build_candidate_result,
    build_final_report,
    build_model_policy,
    validate_final_report,
)
from scripts import run_m80_targeted_four_wallet_deep_qualification as runner


def _deep(wallet: str, *, closed: int = 100, history_complete: bool = True):
    closed_trades = []
    for index in range(closed):
        pnl = 0.01 if index % 2 == 0 else -0.004
        closed_trades.append({
            "token_mint": f"token-{index % 20}",
            "pnl_sol": pnl,
            "entry_at": "2026-07-01T00:00:00+00:00",
            "exit_at": "2026-08-01T00:00:00+00:00",
        })
    return {
        "wallet_address": wallet,
        "history_complete": history_complete,
        "signature_limit_reached": not history_complete,
        "public_rpc_budget_exhausted": False,
        "signature_count": max(closed, 100),
        "transaction_count": max(closed, 100),
        "unavailable_signatures": [],
        "parsed_event_count": closed * 2,
        "backtest": {
            "model": {
                "starting_capital_sol": 1.0,
                "fixed_buy_size_sol": 0.05,
                "slippage_bps": 100,
                "fee_bps": 10,
                "copy_delay_seconds": 8,
                "delay_penalty_bps_per_minute": 25.0,
                "effective_market_friction_bps": 103.3333,
                "maximum_open_positions": 5,
            },
            "metrics": {
                "closed_trade_count": closed,
                "history_span_days": 31.0,
                "net_pnl_sol": 0.3,
                "profit_factor": 2.5,
                "win_rate_percent": 50.0,
                "maximum_drawdown_percent": 8.0,
                "open_positions": 0,
                "unique_token_count": 20,
            },
            "closed_trades": closed_trades,
            "open_positions": [],
        },
    }


def test_exact_targets_and_adaptive_depths():
    assert len(TARGET_WALLETS) == 4
    assert set(MAX_SIGNATURES_BY_WALLET) == set(TARGET_WALLETS)
    assert MAX_SIGNATURES_BY_WALLET[TARGET_WALLETS[0]] == 1400
    assert MAX_SIGNATURES_BY_WALLET[TARGET_WALLETS[1]] == 1400
    assert MAX_SIGNATURES_BY_WALLET[TARGET_WALLETS[2]] == 2600
    assert MAX_SIGNATURES_BY_WALLET[TARGET_WALLETS[3]] == 700
    assert M80_REQUIRED_QUALIFIED_WALLETS == 2
    assert M80_PUBLIC_RPC_REQUEST_CAP == 6000


def test_policy_keeps_frozen_gen4_economics():
    p = build_model_policy(maximum_signatures=1400)
    assert p["starting_capital_sol"] == 1.0
    assert p["fixed_buy_size_sol"] == 0.05
    assert p["slippage_bps"] == 100
    assert p["fee_bps"] == 10
    assert p["copy_delay_seconds"] == 8
    assert p["minimum_closed_trades"] == 100
    assert p["minimum_history_span_days"] == 30.0
    assert p["minimum_profit_factor"] == 1.3
    assert p["minimum_recent_profit_factor"] == 1.1
    assert p["maximum_drawdown_percent"] == 15.0


def test_complete_passing_history_can_promote_only_to_short_canary_pending():
    wallet = TARGET_WALLETS[0]
    p = build_model_policy(maximum_signatures=1400)
    row = build_candidate_result(
        wallet,
        _deep(wallet),
        m66_candidate={"sample": {"median_swap_sol": 1.2}},
        policy=p,
    )
    assert row["disposition"] == "QUALIFIED_PENDING_SHORT_CANARY"
    assert row["short_canary_authorized"] is False
    assert row["micro_live_authorized"] is False
    assert row["m66_observed_wallet_sample"]["median_swap_sol"] == 1.2
    assert row["copy_normalized_model"]["fixed_buy_size_sol"] == 0.05


def test_incomplete_history_cannot_promote_even_if_economics_are_positive():
    wallet = TARGET_WALLETS[0]
    p = build_model_policy(maximum_signatures=1400)
    row = build_candidate_result(
        wallet,
        _deep(wallet, history_complete=False),
        m66_candidate={"sample": {}},
        policy=p,
    )
    assert row["disposition"] == "OBSERVE_ONLY"
    assert row["reason"] == "NEEDS_MORE_PUBLIC_RPC_HISTORY"


def test_final_report_requires_two_but_never_authorizes_micro_live():
    rows = []
    for index, wallet in enumerate(TARGET_WALLETS):
        p = build_model_policy(maximum_signatures=MAX_SIGNATURES_BY_WALLET[wallet])
        row = build_candidate_result(
            wallet,
            _deep(wallet, history_complete=index < 2),
            m66_candidate={"sample": {}},
            policy=p,
        )
        rows.append(row)
    report = build_final_report(
        input_hashes={"x": "a" * 64},
        started_at_utc="2026-08-17T01:00:00+00:00",
        completed_at_utc="2026-08-17T02:00:00+00:00",
        results=rows,
        delta_cache_sha256="b" * 64,
        rpc_stats={"requests": 4000, "cache_hits": 1500},
    )
    validate_final_report(report)
    assert report["summary"]["qualified_pending_short_canary"] == 2
    assert report["summary"]["m74_minimum_wallet_count_reached"] is True
    assert report["next_step"] == "BUILD_M74_M75_QUALIFICATION_BRIDGE_AND_START_SHORT_CANARY"
    assert report["safety"]["helius_requests"] == 0
    assert report["safety"]["live_orders"] == 0
    assert report["safety"]["micro_live_execution_authorized"] is False


def test_runner_has_no_helius_endpoint_or_api_key_dependency():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "api.helius" not in lowered
    assert "helius-rpc" not in lowered
    assert "helius_api_key" not in lowered
    assert "get_wallet_history" not in source
    assert 'PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"' in source
    assert "HELIUS_REQUESTS=0" in source
    assert "HELIUS_CREDITS=0" in source
    assert "MICRO_LIVE_EXECUTION_AUTHORIZED=NO" in source


def test_first_page_refresh_key_is_deterministic():
    first = runner._signature_request_key("https://api.mainnet-beta.solana.com", TARGET_WALLETS[0])
    second = runner._signature_request_key("https://api.mainnet-beta.solana.com", TARGET_WALLETS[0])
    assert first == second
    assert len(first) == 64
