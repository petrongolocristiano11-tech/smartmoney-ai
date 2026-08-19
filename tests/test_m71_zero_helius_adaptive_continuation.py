from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_m71_zero_helius_adaptive_continuation as m71_runner

from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    canonical_sha256,
)
from backend.app.services.gen4_zero_helius_adaptive_continuation_service import (
    M71AdaptiveContinuationError,
    build_adaptive_plan,
    build_continuation_report,
    correct_local_snapshot_official_filter,
    validate_continuation_report,
    validate_input_bundle,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (
    M67_M70_CACHE_SCHEMA,
    M67_M70_DEFAULT_POLICY,
    M67_M70_RPC_SCOPE,
    M67_M70_SCOPE,
    M67_M70_SNAPSHOT_SCOPE,
    M67_M70_VERSION,
    _copyability_evidence,
    build_rpc_evidence,
    evaluate_zero_helius_pre_micro_live,
    simulate_gen4_from_public_events,
    validate_policy as validate_m67_policy,
)
from scripts.run_m67_m70_zero_helius_pre_micro_live import _finalize_cache


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "m71_zero_helius_adaptive_continuation.json"
NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
BS34 = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
TOKEN_A = "467fWX8qGPAf2norsBYTWhG7b2Z7wmhsS8RzPLHypump"


def _load_fixture() -> dict:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    expected = fixture["integrity"]["fixture_sha256"]
    payload = {key: value for key, value in fixture.items() if key != "integrity"}
    assert expected == canonical_sha256(payload)
    return fixture


def _safety(*, public_rpc_requests: int = 0) -> dict:
    return {
        "network_requests": public_rpc_requests,
        "public_rpc_requests": public_rpc_requests,
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


def _m64_summary() -> dict:
    return {
        "wallet_address": BS34,
        "report_payload_sha256": "a" * 64,
        "official": {"closed_trade_count": 83},
        "reconstructed": {"closed_trade_count": 17},
        "combined": {"closed_trade_count": 100},
        "verdict": {"status": "FAIL_ECONOMIC"},
    }


def _snapshot(fixture: dict) -> dict:
    candidates = []
    for index, row in enumerate(fixture["active_candidates"]):
        candidates.append(
            {
                "wallet_address": row["wallet_address"],
                "cluster": {"cluster_id": f"cluster-{index}", "cluster_size": 1},
                "legacy_trade_cache": {},
                "candidate_backtest": {},
                "copyability_campaign": None,
                "m64_audit": None,
                "m65_gate": None,
                "economic_score": None,
                "economic_score_status": "NOT_AVAILABLE_UNTIL_POSITION_EVIDENCE",
            }
        )
    candidates.append(
        {
            "wallet_address": BS34,
            "cluster": {"cluster_id": "cluster-bs34", "cluster_size": 1},
            "legacy_trade_cache": {},
            "candidate_backtest": {},
            "copyability_campaign": {
                "official_realtime_closed_trades": 85,
                "net_pnl_lamports": 32319569,
            },
            "m64_audit": _m64_summary(),
            "m65_gate": {
                "status": "FAIL_ECONOMIC",
                "recommended_state": "RESEARCH_ONLY",
            },
            "economic_score": None,
            "economic_score_status": "NOT_AVAILABLE_UNTIL_POSITION_EVIDENCE",
        }
    )
    snapshot = {
        "scope": M67_M70_SNAPSHOT_SCOPE,
        "version": M67_M70_VERSION,
        "snapshot_at_utc": NOW.isoformat(),
        "source": {
            "wallet_rows_total": len(candidates),
            "wallet_rows_read": len(candidates),
            "wallet_rows_truncated": False,
        },
        "candidates": candidates,
        "contracts": {
            "official_realtime_counter": 83,
            "recovery_counts_as_realtime_proof": False,
            "historical_jupiter_quotes_invented": False,
        },
        "safety": _safety(),
    }
    snapshot["integrity"] = {"snapshot_payload_sha256": canonical_sha256(snapshot)}
    return snapshot


def _events(wallet: str, *, buy_count: int, sell_count: int) -> list[dict]:
    events = []
    for index in range(buy_count):
        when = NOW - timedelta(days=5) + timedelta(minutes=index)
        events.append(
            {
                "sequence": index,
                "signature": f"buy-{wallet[:6]}-{index}",
                "slot": 1000 + index,
                "block_time": when.isoformat(),
                "wallet_address": wallet,
                "side": "BUY",
                "token_mint": TOKEN_A,
                "token_decimals": 6,
                "token_delta_raw": 1_000_000,
                "token_pre_raw": 0,
                "sell_fraction": None,
                "sol_equivalent_delta_lamports": -50_000_000,
                "source_network_fee_lamports": 0,
                "parser_version": "canonical-parser-gen4-raw-balance-delta/4",
            }
        )
    for index in range(sell_count):
        when = NOW - timedelta(days=4) + timedelta(minutes=index)
        events.append(
            {
                "sequence": buy_count + index,
                "signature": f"sell-{wallet[:6]}-{index}",
                "slot": 2000 + index,
                "block_time": when.isoformat(),
                "wallet_address": wallet,
                "side": "SELL",
                "token_mint": TOKEN_A,
                "token_decimals": 6,
                "token_delta_raw": -1_000_000,
                "token_pre_raw": 1_000_000,
                "sell_fraction": 1.0,
                "sol_equivalent_delta_lamports": 55_000_000,
                "source_network_fee_lamports": 0,
                "parser_version": "canonical-parser-gen4-raw-balance-delta/4",
            }
        )
    return events


def _bundle(fixture: dict) -> tuple[dict, dict, dict, dict]:
    policy = validate_m67_policy(dict(M67_M70_DEFAULT_POLICY))
    snapshot = _snapshot(fixture)
    activity = {}
    deep = {}
    for row in fixture["active_candidates"]:
        wallet = row["wallet_address"]
        activity[wallet] = {
            "evidence_class": "PUBLIC_RPC_SIGNATURE_ACTIVITY_NOT_SWAP_CLASSIFICATION",
            "transactions_7d": row["transactions_7d"],
            "transactions_30d": row["transactions_30d"],
            "active_days_7d": row["active_days_7d"],
            "latest_transaction_at": NOW.isoformat(),
            "activity_status": "ACTIVE_CANDIDATE",
            "deep_history_candidate": True,
            "economic_metrics_available": False,
        }
        profile = row["deep_history"]
        if profile is None:
            continue
        events = _events(
            wallet,
            buy_count=profile["buy_events"],
            sell_count=profile["sell_events"],
        )
        backtest = simulate_gen4_from_public_events(events, policy=policy)
        backtest["metrics"]["closed_trade_count"] = profile["closed_trade_count"]
        backtest["metrics"]["open_positions"] = profile["open_positions"]
        deep[wallet] = {
            "wallet_address": wallet,
            "signature_count": profile["signature_count"],
            "transaction_count": profile["transaction_count"],
            "parsed_event_count": profile["parsed_event_count"],
            "history_complete": profile["history_complete"],
            "signature_limit_reached": True,
            "public_rpc_budget_exhausted": False,
            "events": events,
            "backtest": backtest,
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
    rpc = build_rpc_evidence(
        activity_rows=activity,
        deep_rows=deep,
        rpc_stats={
            "public_origin": "https://api.mainnet-beta.solana.com",
            "requests": 525,
            "request_cap": 600,
            "cache_hits": 0,
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
    report = evaluate_zero_helius_pre_micro_live(
        snapshot,
        rpc,
        policy=policy,
        evaluated_at=NOW,
    )
    return snapshot, rpc, report, policy


def test_exact_copyability_filter_excludes_two_quarantined_positions() -> None:
    campaign = SimpleNamespace(id=1, campaign_id="campaign-a")
    rows = []
    for index in range(83):
        rows.append(
            SimpleNamespace(
                wallet_address=BS34,
                campaign_db_id=1,
                status="CLOSED",
                entry_source="WEBHOOK",
                exit_source="WEBHOOK",
                entry_copyable=True,
                exit_copyable=True,
                pnl_lamports=1 if index < 42 else -1,
                close_reason="MIRRORED_WALLET_EXIT",
                closed_at=NOW,
            )
        )
    for _ in range(2):
        rows.append(
            SimpleNamespace(
                wallet_address=BS34,
                campaign_db_id=1,
                status="CLOSED",
                entry_source="WEBHOOK",
                exit_source="RECOVERY_ONLY",
                entry_copyable=True,
                exit_copyable=False,
                pnl_lamports=None,
                close_reason="RECOVERY_GAP_QUARANTINE",
                closed_at=NOW,
            )
        )
    evidence = _copyability_evidence([campaign], rows, [])
    assert evidence[BS34]["official_realtime_closed_trades"] == 83
    assert evidence[BS34]["quarantined_seed_positions"] == 2
    assert evidence[BS34]["official_filter"] == (
        "CLOSED_WEBHOOK_ENTRY_AND_EXIT_COPYABLE_WITH_PNL"
    )


def test_signed_snapshot_correction_is_local_and_keeps_official_83() -> None:
    snapshot = _snapshot(_load_fixture())
    corrected, corrections = correct_local_snapshot_official_filter(snapshot)
    source_target = next(
        item for item in snapshot["candidates"] if item["wallet_address"] == BS34
    )
    corrected_target = next(
        item for item in corrected["candidates"] if item["wallet_address"] == BS34
    )
    assert source_target["copyability_campaign"]["official_realtime_closed_trades"] == 85
    assert corrected_target["copyability_campaign"]["official_realtime_closed_trades"] == 83
    assert corrected_target["copyability_campaign"]["non_official_closed_rows_excluded"] == 2
    assert len(corrections) == 1


def test_real_m67_profile_selects_best_four_adaptively() -> None:
    fixture = _load_fixture()
    _, rpc, report, _ = _bundle(fixture)
    plan = build_adaptive_plan(report, rpc)
    assert plan["selected_wallets"] == fixture["expected_selected_wallets"]
    actions = {row["wallet_address"]: row["action"] for row in plan["candidate_actions"]}
    assert actions == {
        row["wallet_address"]: row["expected_action"]
        for row in fixture["active_candidates"]
    }


def test_partial_economic_history_cannot_become_final_failure_or_pass() -> None:
    fixture = _load_fixture()
    snapshot, rpc, _, policy = _bundle(fixture)
    target_wallet = fixture["expected_selected_wallets"][0]
    rpc["deep_history"][target_wallet]["backtest"]["metrics"].update(
        {
            "closed_trade_count": 100,
            "net_pnl_sol": -1.0,
            "profit_factor": 0.1,
            "win_rate_percent": 1.0,
        }
    )
    rpc["integrity"] = {
        "rpc_evidence_sha256": canonical_sha256(
            {key: value for key, value in rpc.items() if key != "integrity"}
        )
    }
    result = evaluate_zero_helius_pre_micro_live(snapshot, rpc, policy=policy, evaluated_at=NOW)
    target = next(
        item for item in result["candidate_results"] if item["wallet_address"] == target_wallet
    )
    assert target["status"] == "NEEDS_MORE_PUBLIC_RPC_HISTORY"
    assert target["reason"] == "PUBLIC_RPC_POSITION_HISTORY_INCOMPLETE"


def test_continuation_report_is_hash_bound_and_disarmed() -> None:
    fixture = _load_fixture()
    snapshot, rpc, report, policy = _bundle(fixture)
    bundle = validate_input_bundle(snapshot, rpc, report)
    corrected, corrections = correct_local_snapshot_official_filter(snapshot)
    plan = build_adaptive_plan(report, rpc)
    updated_report = evaluate_zero_helius_pre_micro_live(
        corrected, rpc, policy=policy, evaluated_at=NOW
    )
    result = build_continuation_report(
        input_bundle=bundle,
        corrected_snapshot=corrected,
        corrections=corrections,
        plan=plan,
        updated_rpc_evidence=rpc,
        updated_m67_report=updated_report,
        previous_deep_history=rpc["deep_history"],
        evaluated_at=NOW,
    )
    validate_continuation_report(result)
    assert result["safety"]["helius_requests"] == 0
    assert result["safety"]["database_reads"] == 0
    assert result["decision"]["micro_live_execution_authorized"] is False

    result["decision"]["micro_live_execution_authorized"] = True
    with pytest.raises(M71AdaptiveContinuationError, match="Hash report"):
        validate_continuation_report(result)


def test_tampered_previous_report_fails_closed() -> None:
    fixture = _load_fixture()
    _, rpc, report, _ = _bundle(fixture)
    report["summary"]["selected_wallets"] = 99
    with pytest.raises(M71AdaptiveContinuationError, match="Hash report"):
        build_adaptive_plan(report, rpc)


def test_runner_replays_signed_inputs_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    snapshot, rpc, report, policy = _bundle(fixture)
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    snapshot_path = input_dir / "snapshot.json"
    rpc_path = input_dir / "rpc.json"
    report_path = input_dir / "report.json"
    cache_path = input_dir / "cache.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    rpc_path.write_text(json.dumps(rpc), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    cache = _finalize_cache(
        {
            "schema": M67_M70_CACHE_SCHEMA,
            "public_origin": "https://api.mainnet-beta.solana.com",
            "entries": {},
        }
    )
    cache_path.write_text(json.dumps(cache), encoding="utf-8")

    class _OfflineRpc:
        def __init__(self, _url: str, *, cache: dict, **_kwargs: object) -> None:
            self.cache = cache

        def close(self) -> None:
            return None

        def stats(self) -> dict:
            return {
                "public_origin": "https://api.mainnet-beta.solana.com",
                "requests": 0,
                "request_cap": 1800,
                "cache_hits": 4,
                "retry_429": 0,
                "retry_5xx": 0,
                "retry_network": 0,
                "maximum_attempts": 4,
                "throttle_seconds": 0.75,
                "helius_requests": 0,
            }

    def _offline_history(
        _rpc: object,
        wallet: str,
        *,
        first_page: list[dict],
        now: datetime,
        policy: dict,
    ) -> dict:
        del first_page, now
        previous = dict((rpc.get("deep_history") or {}).get(wallet) or {})
        if previous:
            previous["signature_count"] = max(200, int(previous["signature_count"]))
            previous["history_complete"] = True
            previous["signature_limit_reached"] = False
            return previous
        backtest = simulate_gen4_from_public_events([], policy=policy)
        return {
            "wallet_address": wallet,
            "signature_count": 0,
            "transaction_count": 0,
            "parsed_event_count": 0,
            "history_complete": True,
            "signature_limit_reached": False,
            "public_rpc_budget_exhausted": False,
            "events": [],
            "backtest": backtest,
            "historical_jupiter_quotes_invented": False,
            "helius_requests": 0,
        }

    monkeypatch.setattr(m71_runner, "CachedBudgetedPublicRpc", _OfflineRpc)
    monkeypatch.setattr(m71_runner, "_signature_page", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(m71_runner, "_collect_deep_history", _offline_history)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_m71_zero_helius_adaptive_continuation.py",
            "--confirmation",
            "RUN_M71_ZERO_HELIUS_ADAPTIVE_CONTINUATION_READ_ONLY",
            "--output-dir",
            str(output_dir),
            "--previous-snapshot",
            str(snapshot_path),
            "--previous-rpc-evidence",
            str(rpc_path),
            "--previous-report",
            str(report_path),
            "--cache-input",
            str(cache_path),
        ],
    )
    assert m71_runner.main() == 0
    outputs = sorted(output_dir.glob("*.json"))
    assert len(outputs) == 5
    final_path = next(path for path in outputs if "continuation-report" in path.name)
    final = json.loads(final_path.read_text(encoding="utf-8"))
    validate_continuation_report(final)
    assert final["safety"]["network_requests"] == 0
    assert final["safety"]["helius_requests"] == 0
