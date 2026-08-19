from __future__ import annotations

from backend.app.services.gen4_fast_discovery_qualification_service import (
    M81_DISCOVERY_CREDIT_CAP_TOTAL,
    M81_DISCOVERY_REQUEST_CAP_TOTAL,
    M81_REQUIRED_QUALIFIED,
    M81_RPC_WORKERS,
    M81_SEEDS,
    build_final_report,
    merge_discovery_candidates,
    pass2_eligible,
    pass3_eligible,
    rank_results,
    select_pass2,
    stage_result_needs_retry,
    validate_final_report,
    validate_lineage,
)


def _m66() -> dict:
    return {
        "scope": "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY",
        "candidate_results": [
            {"wallet_address": "A" * 32},
            {"wallet_address": "B" * 32},
        ],
    }


def _m79() -> dict:
    return {
        "scope": "M79_PAID_CANDIDATE_ZERO_HELIUS_ECONOMIC_TRIAGE",
        "evaluation": "PASS",
        "pass1_ranked": [{"wallet_address": "C" * 32}],
    }


def _m80() -> dict:
    return {
        "scope": "M80_TARGETED_FOUR_WALLET_ZERO_HELIUS_DEEP_QUALIFICATION",
        "evaluation": "PASS",
        "candidate_results": [{"wallet_address": "D" * 32}],
    }


def _lane(wallet: str, score: float, closed: int = 12) -> dict:
    return {
        "scope": "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY",
        "candidate_results": [
            {
                "wallet_address": wallet,
                "status": "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST",
                "prescreen_score": score,
                "sample": {
                    "causal_closed_cycles_observed": closed,
                    "unique_tokens": 20,
                    "median_swap_sol": 0.5,
                },
                "discovery_evidence": {},
            }
        ],
    }


def _result(wallet: str, *, pf: float, net: float, dd: float, closed: int, score: float, recent_pf: float = 1.2, history_complete: bool = False, disposition: str = "OBSERVE_ONLY") -> dict:
    return {
        "wallet_address": wallet,
        "profit_factor": pf,
        "net_pnl_sol": net,
        "maximum_drawdown_percent": dd,
        "closed_trade_count": closed,
        "economic_score": score,
        "recent_profit_factor": recent_pf,
        "win_rate_percent": 40.0,
        "prescreen_score": 90.0,
        "history_complete": history_complete,
        "disposition": disposition,
    }


def test_budget_and_parallel_contract_are_hard_bounded() -> None:
    assert M81_DISCOVERY_REQUEST_CAP_TOTAL == 86
    assert M81_DISCOVERY_CREDIT_CAP_TOTAL == 8600
    assert M81_RPC_WORKERS == 3
    assert M81_REQUIRED_QUALIFIED == 2
    assert len(M81_SEEDS) == 2


def test_lineage_excludes_old_candidates_and_seeds() -> None:
    known = validate_lineage(_m66(), _m79(), _m80())
    assert "A" * 32 in known
    assert "C" * 32 in known
    assert "D" * 32 in known
    assert set(M81_SEEDS).issubset(known)


def test_discovery_merge_deduplicates_and_excludes_lineage() -> None:
    excluded = {"X" * 32}
    reports = [_lane("X" * 32, 99), _lane("Y" * 32, 90), _lane("Y" * 32, 95)]
    rows = merge_discovery_candidates(reports, excluded)
    assert [row["wallet_address"] for row in rows] == ["Y" * 32]
    assert rows[0]["prescreen_score"] == 95


def test_economic_rank_beats_prescreen_score() -> None:
    strong = _result("S" * 32, pf=1.8, net=0.2, dd=8, closed=45, score=80)
    weak = _result("W" * 32, pf=0.8, net=-0.1, dd=30, closed=60, score=20)
    weak["prescreen_score"] = 100
    assert rank_results([weak, strong])[0]["wallet_address"] == "S" * 32


def test_pass2_rejects_obvious_loser_and_selects_promising() -> None:
    strong = _result("S" * 32, pf=1.3, net=0.05, dd=12, closed=12, score=60)
    weak = _result("W" * 32, pf=0.5, net=-0.2, dd=40, closed=20, score=10)
    assert pass2_eligible(strong) is True
    assert pass2_eligible(weak) is False
    assert select_pass2([weak, strong]) == ["S" * 32]


def test_pass3_only_extends_promising_incomplete_history() -> None:
    row = _result("P" * 32, pf=1.5, net=0.12, dd=10, closed=55, score=75, recent_pf=1.4, history_complete=False)
    assert pass3_eligible(row) is True
    row["history_complete"] = True
    assert pass3_eligible(row) is False


def test_two_qualified_wallets_route_directly_to_m75_but_never_authorize_live() -> None:
    q1 = _result("Q" * 32, pf=1.5, net=0.2, dd=10, closed=120, score=90, history_complete=True, disposition="QUALIFIED_PENDING_SHORT_CANARY")
    q2 = _result("R" * 32, pf=1.6, net=0.3, dd=9, closed=130, score=92, history_complete=True, disposition="QUALIFIED_PENDING_SHORT_CANARY")
    report = build_final_report(
        input_hashes={"x": "y"},
        started_at_utc="2026-08-17T00:00:00+00:00",
        completed_at_utc="2026-08-17T00:10:00+00:00",
        discovery_lanes=[],
        discovery_requests=10,
        discovery_credit_reserved_maximum=1000,
        candidates=[],
        final_results=[q1, q2],
        public_rpc_stats={"requests": 20},
        public_cache_sha256="a" * 64,
        early_stop=True,
    )
    validate_final_report(report)
    assert report["summary"]["m74_minimum_two_wallets_reached"] is True
    assert report["next_step"] == "START_M75_SHORT_REALTIME_CANARY"
    assert report["safety"]["live_orders"] == 0
    assert report["safety"]["signer_authorized"] is False
    assert report["safety"]["micro_live_execution_authorized"] is False


def test_report_rejects_helius_budget_overrun() -> None:
    report = build_final_report(
        input_hashes={},
        started_at_utc="2026-08-17T00:00:00+00:00",
        completed_at_utc="2026-08-17T00:01:00+00:00",
        discovery_lanes=[],
        discovery_requests=87,
        discovery_credit_reserved_maximum=8700,
        candidates=[],
        final_results=[],
        public_rpc_stats={},
        public_cache_sha256="b" * 64,
        early_stop=False,
    )
    try:
        validate_final_report(report)
    except Exception as error:
        assert "Cap" in str(error) or "credit" in str(error).lower()
    else:
        raise AssertionError("Budget overrun must fail")


def test_qualified_wallet_is_not_reprocessed_by_pass2() -> None:
    qualified = _result(
        "Q" * 32,
        pf=1.6,
        net=0.2,
        dd=8,
        closed=60,
        score=90,
        history_complete=True,
        disposition="QUALIFIED_PENDING_SHORT_CANARY",
    )
    assert pass2_eligible(qualified) is False
    assert select_pass2([qualified]) == []


def test_rpc_retry_result_is_explicitly_resumable() -> None:
    row = {"wallet_address": "Z" * 32, "disposition": "RPC_RETRY_REQUIRED"}
    assert stage_result_needs_retry(row) is True
    assert stage_result_needs_retry({"disposition": "RESEARCH_ONLY"}) is False


def test_report_routes_rpc_retry_to_no_helius_respend_resume() -> None:
    retry = {
        "wallet_address": "Z" * 32,
        "disposition": "RPC_RETRY_REQUIRED",
        "prescreen_score": 90.0,
    }
    report = build_final_report(
        input_hashes={"x": "y"},
        started_at_utc="2026-08-17T00:00:00+00:00",
        completed_at_utc="2026-08-17T00:10:00+00:00",
        discovery_lanes=[],
        discovery_requests=10,
        discovery_credit_reserved_maximum=1000,
        candidates=[],
        final_results=[retry],
        public_rpc_stats={"requests": 20},
        public_cache_sha256="c" * 64,
        early_stop=False,
    )
    validate_final_report(report)
    assert report["summary"]["rpc_retry_required"] == 1
    assert report["next_step"] == "RERUN_M81_PUBLIC_RPC_ONLY_NO_HELIUS_RESPEND"
