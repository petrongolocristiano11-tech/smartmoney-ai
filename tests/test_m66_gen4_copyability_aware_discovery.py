from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database.base import Base
from backend.app.models.candidate_backtest import CandidateBacktestRun
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.models.wallet_edge import WalletEdge
from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    canonical_sha256,
)
from backend.app.services.gen4_copyability_aware_discovery_service import (
    M66_DEFAULT_POLICY,
    M66DiscoveryError,
    STATUS_BLOCKED,
    STATUS_NEEDS_FRESH_EVIDENCE,
    STATUS_NEEDS_HISTORY,
    STATUS_QUALIFIED,
    STATUS_RESEARCH_ONLY,
    build_cached_discovery_snapshot,
    evaluate_copyability_aware_discovery,
    validate_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/m66_gen4_copyability_aware_discovery.json"
NOW = datetime(2026, 8, 14, 20, 30, tzinfo=timezone.utc)


def fixture_snapshot() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def sign(snapshot: dict) -> dict:
    snapshot["integrity"] = {
        "snapshot_payload_sha256": canonical_sha256(
            {key: value for key, value in snapshot.items() if key != "integrity"}
        )
    }
    return snapshot


def ready_candidate(address: str = "44444444444444444444444444444444") -> dict:
    candidate = copy.deepcopy(fixture_snapshot()["candidates"][0])
    candidate["wallet_address"] = address
    candidate["independence"] = {
        "cluster_id": f"cluster-{address[:8]}",
        "cluster_size": 1,
        "cluster_members": [address],
        "high_risk_edge_count": 0,
        "shared_token_relationship_count": 0,
        "relevant_edge_count": 0,
        "relationship_status": "NO_HIGH_RISK_RELATIONSHIP_DETECTED",
        "independence_verified": False,
        "consensus_eligible": False,
    }
    return candidate


def one_candidate_snapshot(candidate: dict) -> dict:
    snapshot = fixture_snapshot()
    snapshot["candidates"] = [candidate]
    snapshot["source"]["wallet_rows_total"] = 1
    snapshot["source"]["wallet_rows_read"] = 1
    snapshot["source"]["wallet_rows_truncated"] = False
    snapshot["source"]["backtest_rows_read"] = 1
    return sign(snapshot)


def test_signed_fixture_is_valid_and_cluster_collision_is_deterministic():
    snapshot = fixture_snapshot()
    validated = validate_snapshot(snapshot)
    assert validated["candidate_count"] == 3

    report = evaluate_copyability_aware_discovery(
        snapshot,
        evaluated_at=NOW,
    )
    assert report["discovery"] == "PASS"
    assert report["summary"]["wallets_qualified_for_short_canary"] == 2
    assert report["summary"]["wallets_selected_for_short_canary"] == 1
    assert report["summary"]["wallets_research_only"] == 1
    assert report["summary"]["cached_wallets_total_zero_helius_credits"] == 3
    assert report["summary"]["cached_wallets_with_completed_backtest"] == 3
    selected = report["selected_wallets"]
    assert len(selected) == 1
    assert selected[0]["wallet_address"] == "11111111111111111111111111111111"
    collision = next(
        item
        for item in report["candidate_results"]
        if item["wallet_address"] == "22222222222222222222222222222222"
    )
    assert collision["selection"]["cluster_collision"] is True


def test_snapshot_tampering_fails_closed():
    snapshot = fixture_snapshot()
    snapshot["candidates"][0]["economics"]["net_pnl_sol"] = 999
    with pytest.raises(M66DiscoveryError, match="Hash snapshot M66 non valido"):
        validate_snapshot(snapshot)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("network_requests", 1, "network_requests"),
        ("cached_only", False, "non cached-only"),
        ("wallets_applied", True, "applicato wallet"),
    ],
)
def test_snapshot_safety_contract_fails_closed(field, value, message):
    snapshot = fixture_snapshot()
    snapshot["safety"][field] = value
    sign(snapshot)
    with pytest.raises(M66DiscoveryError, match=message):
        validate_snapshot(snapshot)


def test_duplicate_wallet_fails_closed_even_with_valid_hash():
    snapshot = fixture_snapshot()
    snapshot["candidates"].append(copy.deepcopy(snapshot["candidates"][0]))
    snapshot["source"]["wallet_rows_total"] = 4
    snapshot["source"]["wallet_rows_read"] = 4
    sign(snapshot)
    with pytest.raises(M66DiscoveryError, match="Wallet duplicato"):
        validate_snapshot(snapshot)


def test_cached_inventory_count_cannot_be_understated_or_mismatched():
    snapshot = fixture_snapshot()
    snapshot["source"]["wallet_rows_total"] = 2
    sign(snapshot)
    with pytest.raises(M66DiscoveryError, match="totale M66 inferiore"):
        validate_snapshot(snapshot)

    snapshot = fixture_snapshot()
    snapshot["source"]["wallet_rows_read"] = 2
    sign(snapshot)
    with pytest.raises(M66DiscoveryError, match="incoerente con i candidati"):
        validate_snapshot(snapshot)


def test_best_trade_dependency_is_research_only():
    candidate = ready_candidate()
    candidate["economics"]["net_pnl_without_best_trade_sol"] = -0.01
    report = evaluate_copyability_aware_discovery(
        one_candidate_snapshot(candidate),
        evaluated_at=NOW,
    )
    result = report["candidate_results"][0]
    assert result["status"] == STATUS_RESEARCH_ONLY
    assert "BEST_TRADE_DEPENDENCY_EXCESSIVE" in result["failure_reasons"]


def test_strong_preliminary_candidate_queues_only_targeted_history():
    candidate = ready_candidate()
    candidate["economics"]["closed_trade_count"] = 60
    candidate["economics"]["position_result_count"] = 60
    candidate["economics"]["history_span_days"] = 18
    candidate["economics"]["stability_windows"] = candidate["economics"][
        "stability_windows"
    ][:3]
    candidate["economics"]["positive_stability_window_count"] = 3
    report = evaluate_copyability_aware_discovery(
        one_candidate_snapshot(candidate),
        evaluated_at=NOW,
    )
    result = report["candidate_results"][0]
    assert result["status"] == STATUS_NEEDS_HISTORY
    assert report["acquisition_plan"]["wallets_queued"] == 1
    assert report["acquisition_plan"]["requests_allocated"] <= 40
    assert report["acquisition_plan"]["execution_authorized"] is False
    assert report["safety"]["network_requests"] == 0


def test_stale_but_economic_candidate_needs_fresh_evidence():
    candidate = ready_candidate()
    stale = "2026-07-01T00:00:00+00:00"
    candidate["activity"]["calculated_at"] = stale
    candidate["quality"]["calculated_at"] = stale
    candidate["economics"]["calculated_at"] = stale
    candidate["copyability"]["exitability_calculated_at"] = stale
    report = evaluate_copyability_aware_discovery(
        one_candidate_snapshot(candidate),
        evaluated_at=NOW,
    )
    assert report["candidate_results"][0]["status"] == STATUS_NEEDS_FRESH_EVIDENCE


@pytest.mark.parametrize(
    ("field_path", "value", "reason"),
    [
        (("quality", "classification"), "NON_COPIABILE", "QUALITY_NOT_COPYABLE"),
        (("copyability", "open_positions"), 1, "OPEN_POSITIONS_PRESENT"),
        (("quality", "invalid_amount_swaps_7d"), 1, "INVALID_SWAP_AMOUNTS_PRESENT"),
    ],
)
def test_hard_copyability_failures_are_blocked(field_path, value, reason):
    candidate = ready_candidate()
    candidate[field_path[0]][field_path[1]] = value
    report = evaluate_copyability_aware_discovery(
        one_candidate_snapshot(candidate),
        evaluated_at=NOW,
    )
    result = report["candidate_results"][0]
    assert result["status"] == STATUS_BLOCKED
    assert reason in result["failure_reasons"]


def test_strict_threshold_candidate_is_qualified_but_micro_live_remains_off():
    candidate = ready_candidate()
    report = evaluate_copyability_aware_discovery(
        one_candidate_snapshot(candidate),
        evaluated_at=NOW,
    )
    result = report["candidate_results"][0]
    assert result["status"] == STATUS_QUALIFIED
    assert result["short_canary_required"] is True
    assert result["micro_live_execution_authorized"] is False
    assert report["activation"]["micro_live_preparation_authorized"] is False
    assert report["activation"]["micro_live_execution_authorized"] is False
    assert report["activation"]["discovery_cron_reactivation_authorized"] is False


def test_non_gen4_backtest_parameters_cannot_qualify():
    candidate = ready_candidate()
    candidate["copyability"]["backtest_starting_capital_sol"] = 2.0
    report = evaluate_copyability_aware_discovery(
        one_candidate_snapshot(candidate),
        evaluated_at=NOW,
    )
    result = report["candidate_results"][0]
    assert result["status"] == STATUS_NEEDS_FRESH_EVIDENCE
    assert "BACKTEST_STARTING_CAPITAL_NOT_GEN4" in result["failure_reasons"]
    assert result["micro_live_execution_authorized"] is False


def test_canary_contract_reuses_definitive_m65_safety_thresholds():
    report = evaluate_copyability_aware_discovery(
        one_candidate_snapshot(ready_candidate()),
        evaluated_at=NOW,
    )
    canary = report["short_canary_contract"]
    assert canary["minimum_observation_hours"] == 24
    assert canary["minimum_entry_attempts"] == 20
    assert canary["minimum_closed_trades"] == 10
    assert canary["minimum_webhook_coverage_percent"] == 95
    assert canary["minimum_unsigned_build_coverage_percent"] == 100
    assert canary["recovery_counts_as_realtime_proof"] is False


def test_policy_has_buffer_over_m65_profit_factor_and_three_wallet_cap():
    assert M66_DEFAULT_POLICY["minimum_profit_factor"] == 1.30
    assert M66_DEFAULT_POLICY["maximum_selected_wallets"] == 3
    assert M66_DEFAULT_POLICY["minimum_closed_trades"] == 100
    assert M66_DEFAULT_POLICY["maximum_drawdown_percent"] == 15.0
    assert M66_DEFAULT_POLICY["required_backtest_starting_capital_sol"] == 1.0
    assert M66_DEFAULT_POLICY["required_backtest_fixed_buy_size_sol"] == 0.05
    assert M66_DEFAULT_POLICY["required_backtest_slippage_bps"] == 100
    assert M66_DEFAULT_POLICY["required_backtest_fee_bps"] == 10
    assert M66_DEFAULT_POLICY["required_backtest_copy_delay_seconds"] == 8
    assert M66_DEFAULT_POLICY[
        "required_backtest_delay_penalty_bps_per_minute"
    ] == 25.0
    assert M66_DEFAULT_POLICY["required_backtest_max_open_positions"] == 5


def test_report_never_invents_historical_jupiter_or_authorizes_consensus():
    report = evaluate_copyability_aware_discovery(
        one_candidate_snapshot(ready_candidate()),
        evaluated_at=NOW,
    )
    assert report["safety"]["historical_jupiter_quotes_invented"] is False
    assert report["safety"]["jupiter_requests"] == 0
    consensus = report["multi_wallet_consensus_readiness"]
    assert consensus["activation_authorized"] is False
    assert consensus["same_cluster_signals_count"] is False
    assert consensus["copy_chain_signals_count"] is False
    assert consensus["manual_independence_confirmation_required"] is True


def _position(index: int) -> dict:
    token = f"Token{index % 20:02d}"
    pnl = 0.004 if index % 3 else -0.002
    return {
        "token_mint": token,
        "entry_at": (NOW - timedelta(days=40, minutes=index)).isoformat(),
        "exit_at": (NOW - timedelta(days=39, minutes=index)).isoformat(),
        "entry_signature": f"entry-{index:03d}",
        "exit_signature": f"exit-{index:03d}",
        "cost_basis_sol": 0.05,
        "proceeds_sol": 0.05 + pnl,
        "pnl_sol": pnl,
    }


def test_cached_database_builder_performs_only_reads_and_clusters_repeated_shared_tokens():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        for index, address in enumerate(
            (
                "44444444444444444444444444444444",
                "55555555555555555555555555555555",
            ),
            start=1,
        ):
            db.add(
                DiscoveredWallet(
                    wallet_address=address,
                    smart_score=90 - index,
                    ranking_score=90 - index,
                    last_swap_at=NOW - timedelta(hours=1),
                    swaps_24h=8,
                    swaps_7d=25,
                    buys_7d=13,
                    sells_7d=12,
                    active_days_7d=5,
                    activity_score=88,
                    activity_classification="ATTIVO",
                    activity_eligible=True,
                    activity_calculated_at=NOW,
                    quality_score=90,
                    quality_classification="COPIABILE",
                    quality_eligible=True,
                    quality_sample_swaps_7d=25,
                    dust_ratio_7d=0.05,
                    size_compatibility_ratio_7d=0.9,
                    quality_calculated_at=NOW,
                    exit_price_current_route_percent=100,
                    exitability_gate_status="READY",
                    exitability_gate_score=90,
                    exitability_gate_eligible=True,
                    exitability_gate_calculated_at=NOW,
                )
            )
            db.add(
                CandidateBacktestRun(
                    run_id=f"db-fixture-{index}",
                    wallet_address=address,
                    status="COMPLETED",
                    decision="PROMOSSO",
                    parameters={
                        "starting_capital_sol": 1.0,
                        "fixed_buy_size_sol": 0.05,
                        "slippage_bps": 100,
                        "fee_bps": 10,
                        "copy_delay_seconds": 8,
                        "delay_penalty_bps_per_minute": 25.0,
                        "effective_market_friction_bps": 103.3333,
                        "max_open_positions": 5,
                    },
                    completed_positions=100,
                    open_positions=0,
                    net_pnl_sol=0.2,
                    win_rate_percent=66,
                    profit_factor=4,
                    max_drawdown_percent=5,
                    execution_coverage_percent=95,
                    matched_sell_ratio_percent=100,
                    history_span_days=40,
                    effective_starting_equity_sol=1,
                    jupiter_status="PASSED",
                    jupiter_compatibility_percent=100,
                    position_results=[_position(item) for item in range(100)],
                    started_at=NOW - timedelta(hours=2),
                    completed_at=NOW - timedelta(hours=1),
                )
            )
        for token_index in range(3):
            db.add(
                WalletEdge(
                    source_wallet="44444444444444444444444444444444",
                    target_wallet="55555555555555555555555555555555",
                    token_mint=f"SharedToken{token_index}",
                    edge_type="SHARED_TOKEN",
                    strength=80,
                )
            )
        db.commit()
        before = (
            db.query(DiscoveredWallet).count(),
            db.query(CandidateBacktestRun).count(),
            db.query(WalletEdge).count(),
        )
        snapshot = build_cached_discovery_snapshot(db, now=NOW)
        after = (
            db.query(DiscoveredWallet).count(),
            db.query(CandidateBacktestRun).count(),
            db.query(WalletEdge).count(),
        )
        assert before == after
        assert snapshot["source"]["wallet_rows_total"] == 2
        assert snapshot["source"]["wallet_rows_read"] == 2
        assert snapshot["source"]["wallet_rows_truncated"] is False
        assert not db.new
        assert not db.dirty
        assert not db.deleted
        cluster_ids = {
            row["independence"]["cluster_id"] for row in snapshot["candidates"]
        }
        assert len(cluster_ids) == 1
        assert all(
            row["independence"]["cluster_size"] == 2
            for row in snapshot["candidates"]
        )
        validate_snapshot(snapshot)
    engine.dispose()


def test_cached_trade_rows_are_enriched_in_memory_and_queue_only_targeted_history():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    address = "66666666666666666666666666666666"
    with Session(engine, expire_on_commit=False) as db:
        db.add(
            DiscoveredWallet(
                wallet_address=address,
                smart_score=0,
                ranking_score=0,
            )
        )
        for index in range(8):
            db.add(
                Trade(
                    signature=f"cached-trade-{index}",
                    wallet_address=address,
                    side="BUY" if index % 2 == 0 else "SELL",
                    token_mint=f"CachedToken{(index // 2) % 4}",
                    token_amount=1000,
                    sol_amount=0.05,
                    fee=0.000005,
                    success=True,
                    block_time=NOW
                    - timedelta(days=index % 3, minutes=index),
                )
            )
        db.commit()
        before = db.query(Trade).count()
        snapshot = build_cached_discovery_snapshot(db, now=NOW)
        assert db.query(Trade).count() == before
        assert not db.new
        assert not db.dirty
        assert not db.deleted

        source = snapshot["source"]
        assert source["cached_trade_rows_lifetime"] == 8
        assert source["cached_trade_rows_7d"] == 8
        assert source["wallets_with_cached_trade_evidence"] == 1
        assert source["wallets_with_cached_recent_trade_evidence"] == 1
        assert source["database_query_count"] == 6
        candidate = snapshot["candidates"][0]
        assert candidate["source"]["activity_evidence_source"] == (
            "DERIVED_IN_MEMORY_FROM_CACHED_TRADE_ROWS"
        )
        assert candidate["activity"]["classification"] == "ATTIVO"
        assert candidate["quality"]["classification"] == "OSSERVAZIONE"
        assert candidate["local_trade_evidence"]["prescreen_passed"] is True
        assert candidate["economics"]["evidence_class"] == "MISSING"
        assert candidate["economics"]["closed_trade_count"] == 0

        report = evaluate_copyability_aware_discovery(
            snapshot,
            evaluated_at=NOW,
        )
        result = report["candidate_results"][0]
        assert result["status"] == STATUS_NEEDS_HISTORY
        assert report["summary"][
            "cached_wallets_passing_zero_credit_trade_prescreen"
        ] == 1
        assert report["summary"][
            "cached_wallets_with_local_trade_evidence"
        ] == 1
        assert report["acquisition_plan"]["wallets_queued"] == 1
        assert report["safety"]["helius_requests"] == 0
        assert result["analytics"][
            "economic_metrics_inferred_from_cached_trades"
        ] is False
    engine.dispose()


def test_missing_cached_trade_rows_are_reported_explicitly_and_not_queued():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    address = "77777777777777777777777777777777"
    with Session(engine, expire_on_commit=False) as db:
        db.add(DiscoveredWallet(wallet_address=address))
        db.commit()
        snapshot = build_cached_discovery_snapshot(db, now=NOW)
        report = evaluate_copyability_aware_discovery(
            snapshot,
            evaluated_at=NOW,
        )
        result = report["candidate_results"][0]
        assert result["status"] == STATUS_BLOCKED
        assert "NO_CACHED_TRADE_EVIDENCE" in result["failure_reasons"]
        assert "CACHED_TRADE_PRESCREEN_FAILED" in result["failure_reasons"]
        assert report["summary"][
            "cached_wallets_without_local_trade_evidence"
        ] == 1
        assert report["acquisition_plan"]["wallets_queued"] == 0
    engine.dispose()
