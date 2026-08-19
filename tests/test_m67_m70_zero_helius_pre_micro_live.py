from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

import backend.app.services.gen4_zero_helius_pre_micro_live_service as m67_service

from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    canonical_sha256,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (
    M67_M70_CACHE_SCHEMA,
    M67_M70_DEFAULT_POLICY,
    M67_M70_RPC_SCOPE,
    M67_M70_SNAPSHOT_SCOPE,
    M67_M70_VERSION,
    M67M70ZeroHeliusError,
    build_rpc_evidence,
    build_unified_local_snapshot,
    evaluate_zero_helius_pre_micro_live,
    simulate_gen4_from_public_events,
    summarize_signature_activity,
    validate_external_m64_report,
    validate_external_m65_report,
    validate_policy,
)
from scripts.run_m67_m70_zero_helius_pre_micro_live import (
    CachedBudgetedPublicRpc,
    PublicRpcBudgetExhausted,
    _finalize_cache,
)


WALLET_A = "3hs2zxnxHiWVTUgLyyEVUa2VtGGEb298PWb2UqNvdxQY"
WALLET_B = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
TOKEN_A = "467fWX8qGPAf2norsBYTWhG7b2Z7wmhsS8RzPLHypump"
TOKEN_B = "BFnsoMLQBYprJBN4DzpHsn2fRpAKaPqLp9nzZZnkpump"
NOW = datetime(2026, 8, 15, 2, 30, tzinfo=timezone.utc)


def _event(
    *,
    wallet: str,
    token: str,
    side: str,
    when: datetime,
    sequence: int,
    sol_lamports: int,
) -> dict:
    buy = side == "BUY"
    return {
        "sequence": sequence,
        "signature": f"{wallet[:8]}-{token[:8]}-{side}-{sequence}",
        "slot": 1000 + sequence,
        "block_time": when.isoformat(),
        "wallet_address": wallet,
        "side": side,
        "token_mint": token,
        "token_decimals": 6,
        "token_delta_raw": 1_000_000_000 if buy else -1_000_000_000,
        "token_pre_raw": 0 if buy else 1_000_000_000,
        "sell_fraction": None if buy else 1.0,
        "sol_equivalent_delta_lamports": -sol_lamports if buy else sol_lamports,
        "source_network_fee_lamports": 0,
        "parser_version": "canonical-parser-gen4-raw-balance-delta/4",
    }


def _profitable_events(wallet: str, offset_seconds: int = 0) -> list[dict]:
    start = NOW - timedelta(days=2) + timedelta(seconds=offset_seconds)
    return [
        _event(
            wallet=wallet,
            token=TOKEN_A,
            side="BUY",
            when=start,
            sequence=1,
            sol_lamports=50_000_000,
        ),
        _event(
            wallet=wallet,
            token=TOKEN_A,
            side="SELL",
            when=start + timedelta(hours=1),
            sequence=2,
            sol_lamports=70_000_000,
        ),
        _event(
            wallet=wallet,
            token=TOKEN_B,
            side="BUY",
            when=start + timedelta(days=1),
            sequence=3,
            sol_lamports=50_000_000,
        ),
        _event(
            wallet=wallet,
            token=TOKEN_B,
            side="SELL",
            when=start + timedelta(days=1, hours=1),
            sequence=4,
            sol_lamports=70_000_000,
        ),
    ]


def _fixture_policy() -> dict:
    return validate_policy(
        {
            **M67_M70_DEFAULT_POLICY,
            "minimum_closed_trades": 2,
            "minimum_recent_closed_trades": 2,
            "minimum_history_span_days": 0.5,
            "minimum_unique_tokens": 2,
            "maximum_token_concentration_percent": 50.0,
            "minimum_stability_windows": 2,
            "minimum_positive_stability_windows": 2,
            "stability_window_size": 1,
        }
    )


def _safety(public_requests: int = 0) -> dict:
    return {
        "network_requests": public_requests,
        "public_rpc_requests": public_requests,
        "helius_requests": 0,
        "database_writes": 0,
        "backend_posts": 0,
        "jupiter_requests": 0,
        "paper_orders": 0,
        "live_orders": 0,
        "signed_transactions": 0,
        "submitted_transactions": 0,
        "signer_access": False,
        "discovery_cron_changed": False,
        "primary_campaign_changed": False,
        "legacy_forward_feed_changed": False,
        "automatic_live_activation": False,
        "micro_live_execution_authorized": False,
    }


def _local_snapshot(*, m65_failure: bool = False) -> dict:
    candidates = []
    for wallet, cluster in ((WALLET_A, "cluster-a"), (WALLET_B, "cluster-b")):
        m65 = None
        if m65_failure and wallet == WALLET_B:
            m65 = {
                "wallet_address": wallet,
                "gate_payload_sha256": "a" * 64,
                "status": "FAIL_ECONOMIC",
                "recommended_state": "RESEARCH_ONLY_RECENT_STABILITY_FAILED",
                "economic_failure_reasons": ["RECENT_NET_PNL_NOT_POSITIVE"],
                "analytics": {},
            }
        candidates.append(
            {
                "wallet_address": wallet,
                "cluster": {"cluster_id": cluster, "cluster_size": 1},
                "legacy_trade_cache": {},
                "candidate_backtest": {},
                "copyability_campaign": None,
                "m64_audit": None,
                "m65_gate": m65,
                "economic_score": None,
                "economic_score_status": "NOT_AVAILABLE_UNTIL_POSITION_EVIDENCE",
            }
        )
    snapshot = {
        "scope": M67_M70_SNAPSHOT_SCOPE,
        "version": M67_M70_VERSION,
        "snapshot_at_utc": NOW.isoformat(),
        "source": {
            "wallet_rows_total": 2,
            "wallet_rows_read": 2,
            "wallet_rows_truncated": False,
            "legacy_trade_rows_lifetime": 0,
            "copyability_campaign_rows": 0,
            "copyability_position_rows": 0,
            "copyability_receipt_aggregate_rows": 0,
            "m64_reports": 0,
            "m65_reports": int(m65_failure),
            "database_query_count": 9,
        },
        "candidates": candidates,
        "contracts": {
            "official_realtime_counter": 83,
            "recovery_counts_as_realtime_proof": False,
            "historical_jupiter_quotes_invented": False,
            "parser_version": "canonical-parser-gen4-raw-balance-delta/4",
            "copyability_policy_version": "canonical-parser-gen4-realtime-copyability/1",
        },
        "safety": _safety(),
    }
    snapshot["integrity"] = {"snapshot_payload_sha256": canonical_sha256(snapshot)}
    return snapshot


def _rpc_evidence(policy: dict) -> dict:
    activity = {
        wallet: {
            "evidence_class": "PUBLIC_RPC_SIGNATURE_ACTIVITY_NOT_SWAP_CLASSIFICATION",
            "transactions_7d": 4,
            "transactions_30d": 4,
            "active_days_7d": 2,
            "latest_transaction_at": NOW.isoformat(),
            "activity_status": "ACTIVE_CANDIDATE",
            "deep_history_candidate": True,
            "economic_metrics_available": False,
        }
        for wallet in (WALLET_A, WALLET_B)
    }
    deep = {}
    for wallet, offset in ((WALLET_A, 0), (WALLET_B, 60)):
        events = _profitable_events(wallet, offset)
        deep[wallet] = {
            "wallet_address": wallet,
            "history_complete": True,
            "events": events,
            "backtest": simulate_gen4_from_public_events(events, policy=policy),
            "historical_jupiter_quotes_invented": False,
            "helius_requests": 0,
        }
    cache = _finalize_cache(
        {
            "schema": M67_M70_CACHE_SCHEMA,
            "public_origin": "https://api.mainnet-beta.solana.com",
            "entries": {},
        }
    )
    return build_rpc_evidence(
        activity_rows=activity,
        deep_rows=deep,
        rpc_stats={
            "public_origin": "https://api.mainnet-beta.solana.com",
            "requests": 0,
            "request_cap": 600,
            "cache_hits": 8,
            "retry_429": 0,
            "retry_5xx": 0,
            "retry_network": 0,
            "maximum_attempts": 4,
            "throttle_seconds": 0.65,
            "helius_requests": 0,
        },
        cache=cache,
        policy=policy,
        collected_at=NOW,
    )


def test_gen4_public_event_simulation_uses_frozen_model() -> None:
    result = simulate_gen4_from_public_events(
        _profitable_events(WALLET_A),
        policy=_fixture_policy(),
    )

    assert result["model"] == {
        "starting_capital_sol": 1.0,
        "fixed_buy_size_sol": 0.05,
        "slippage_bps": 100,
        "fee_bps": 10,
        "copy_delay_seconds": 8,
        "delay_penalty_bps_per_minute": 25.0,
        "effective_market_friction_bps": 103.3333,
        "maximum_open_positions": 5,
    }
    assert result["metrics"]["closed_trade_count"] == 2
    assert result["metrics"]["net_pnl_sol"] > 0
    assert result["metrics"]["profit_factor"] == 999.0
    assert result["metrics"]["open_positions"] == 0
    assert result["metrics"]["historical_jupiter_quotes_invented"] is False


def test_two_independent_wallets_are_selected_but_live_stays_disarmed() -> None:
    policy = _fixture_policy()
    report = evaluate_zero_helius_pre_micro_live(
        _local_snapshot(),
        _rpc_evidence(policy),
        policy=policy,
        evaluated_at=NOW,
    )

    assert report["summary"]["wallets_qualified_pending_canary"] == 2
    assert report["summary"]["selected_wallets"] == 2
    assert report["summary"]["multi_wallet_minimum_reached"] is True
    assert report["multi_wallet_consensus"]["independent_signals"] >= 1
    assert report["pre_micro_live_foundation"]["state"] == "PREPARED_DISARMED"
    assert report["short_canary_contract"]["activation_authorized"] is False
    assert report["safety"]["helius_requests"] == 0
    assert report["safety"]["live_orders"] == 0
    assert report["safety"]["signer_access"] is False


def test_m65_definitive_failure_overrides_profitable_public_proxy() -> None:
    policy = _fixture_policy()
    report = evaluate_zero_helius_pre_micro_live(
        _local_snapshot(m65_failure=True),
        _rpc_evidence(policy),
        policy=policy,
        evaluated_at=NOW,
    )
    target = next(
        item for item in report["candidate_results"] if item["wallet_address"] == WALLET_B
    )

    assert target["status"] == "RESEARCH_ONLY"
    assert target["reason"] == "M65_DEFINITIVE_ECONOMIC_FAIL"
    assert all(item["wallet_address"] != WALLET_B for item in report["selected_wallets"])


def test_signature_activity_never_creates_economic_metrics() -> None:
    policy = _fixture_policy()
    rows = [
        {
            "signature": f"sig-{index}",
            "blockTime": int((NOW - timedelta(days=index % 4)).timestamp()),
            "err": None,
        }
        for index in range(10)
    ]
    result = summarize_signature_activity(rows, now=NOW, policy=policy)

    assert result["activity_status"] == "ACTIVE_CANDIDATE"
    assert result["deep_history_candidate"] is True
    assert result["economic_metrics_available"] is False
    assert "profit_factor" not in result


def test_policy_rejects_non_gen4_costs() -> None:
    with pytest.raises(M67M70ZeroHeliusError, match="Slippage"):
        validate_policy({**M67_M70_DEFAULT_POLICY, "slippage_bps": 99})


def test_public_rpc_rejects_helius_endpoint() -> None:
    cache = _finalize_cache(
        {
            "schema": M67_M70_CACHE_SCHEMA,
            "public_origin": "https://mainnet.helius-rpc.com",
            "entries": {},
        }
    )
    with pytest.raises(M67M70ZeroHeliusError, match="Helius"):
        CachedBudgetedPublicRpc(
            "https://mainnet.helius-rpc.com/?api-key=secret",
            cache=cache,
            request_cap=30,
            maximum_attempts=1,
            throttle_seconds=0,
        )


class _FailingClient:
    def post(self, *args, **kwargs):  # noqa: ANN002,ANN003
        raise httpx.ConnectError("offline")

    def close(self) -> None:
        return None


def test_public_rpc_request_cap_is_hard_even_on_retries() -> None:
    cache = _finalize_cache(
        {
            "schema": M67_M70_CACHE_SCHEMA,
            "public_origin": "https://api.mainnet-beta.solana.com",
            "entries": {},
        }
    )
    rpc = CachedBudgetedPublicRpc(
        "https://api.mainnet-beta.solana.com",
        cache=cache,
        request_cap=1,
        maximum_attempts=4,
        throttle_seconds=0,
        client=_FailingClient(),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(PublicRpcBudgetExhausted):
        rpc.call("getHealth", [])
    assert rpc.requests == 1


def _m64_report() -> dict:
    report = {
        "scope": "M64_GEN4_83_PLUS_RECONSTRUCTED_CLOSED_TRADES_READ_ONLY",
        "campaign": {"wallet": WALLET_B},
        "samples": {
            "official_realtime": {"closed_trade_count": 83, "metrics": {}},
            "reconstructed": {"closed_trade_count": 17, "metrics": {}},
            "combined_equivalent": {"closed_trade_count": 100, "metrics": {}},
        },
        "verdict": {},
        "safety": {
            "helius_requests": 0,
            "database_writes": 0,
            "backend_posts": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "official_counter_mutated": False,
            "recovery_counted_as_realtime_proof": False,
        },
    }
    report["integrity"] = {"report_payload_sha256": canonical_sha256(report)}
    return report


def _m65_report() -> dict:
    report = {
        "scope": "M65_GEN4_DEFINITIVE_WALLET_QUALIFICATION_GATE_READ_ONLY",
        "candidate": {
            "wallet": WALLET_B,
            "recommended_state": "RESEARCH_ONLY_RECENT_STABILITY_FAILED",
        },
        "verdict": {
            "status": "FAIL_ECONOMIC",
            "micro_live_execution_authorized": False,
        },
        "economic_failure_reasons": ["RECENT_NET_PNL_NOT_POSITIVE"],
        "analytics": {},
        "safety": {
            "helius_requests": 0,
            "database_writes": 0,
            "backend_posts": 0,
            "jupiter_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
        },
    }
    report["integrity"] = {"gate_payload_sha256": canonical_sha256(report)}
    return report


def test_external_m64_and_m65_reports_are_hash_verified() -> None:
    assert validate_external_m64_report(_m64_report())["wallet_address"] == WALLET_B
    assert validate_external_m65_report(_m65_report())["status"] == "FAIL_ECONOMIC"

    corrupted = _m64_report()
    corrupted["samples"]["combined_equivalent"]["closed_trade_count"] = 99
    with pytest.raises(M67M70ZeroHeliusError, match="Hash interno"):
        validate_external_m64_report(corrupted)


def test_unified_snapshot_includes_campaign_and_external_only_wallets(monkeypatch) -> None:
    monkeypatch.setattr(
        m67_service,
        "build_cached_discovery_snapshot",
        lambda *args, **kwargs: {
            "source": {
                "wallet_rows_total": 0,
                "wallet_rows_read": 0,
                "wallet_rows_truncated": False,
                "cached_trade_rows_lifetime": 0,
                "database_query_count": 6,
            },
            "candidates": [],
        },
    )

    class _Query:
        def __init__(self, rows):
            self.rows = rows

        def order_by(self, *args):  # noqa: ANN002
            return self

        def filter(self, *args):  # noqa: ANN002
            return self

        def group_by(self, *args):  # noqa: ANN002
            return self

        def all(self):
            return self.rows

    class _Database:
        def __init__(self):
            self.calls = 0

        def query(self, *args):  # noqa: ANN002
            self.calls += 1
            if self.calls == 1:
                return _Query(
                    [
                        SimpleNamespace(
                            id=1,
                            campaign_id="campaign-a",
                            frozen_wallets=[{"wallet_address": WALLET_A}],
                        )
                    ]
                )
            return _Query([])

    snapshot = build_unified_local_snapshot(
        _Database(),
        m64_reports=[_m64_report()],
        now=NOW,
    )

    assert [item["wallet_address"] for item in snapshot["candidates"]] == sorted(
        [WALLET_A, WALLET_B]
    )
    assert snapshot["source"]["m66_wallet_rows_read"] == 0
    assert snapshot["source"]["union_only_wallet_rows"] == 2
    target = next(
        item for item in snapshot["candidates"] if item["wallet_address"] == WALLET_B
    )
    assert target["m64_audit"]["combined"]["closed_trade_count"] == 100


def test_rpc_evidence_hash_is_fail_closed() -> None:
    evidence = _rpc_evidence(_fixture_policy())
    assert evidence["scope"] == M67_M70_RPC_SCOPE
    evidence["activity"][WALLET_A]["transactions_7d"] = 999
    with pytest.raises(M67M70ZeroHeliusError, match="Hash evidenza RPC"):
        evaluate_zero_helius_pre_micro_live(
            _local_snapshot(),
            evidence,
            policy=_fixture_policy(),
            evaluated_at=NOW,
        )
