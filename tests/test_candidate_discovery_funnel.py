from types import SimpleNamespace

from backend.app.services.candidate_discovery_funnel_service import (
    _allocate_history_budget,
    evaluate_candidate,
)


def wallet(**overrides):
    data = {
        "wallet_address": "W" * 44,
        "smart_score": 75,
        "ranking_score": 80,
        "activity_score": 75,
        "activity_classification": "ATTIVO",
        "quality_score": 78,
        "quality_classification": "COPIABILE",
        "quality_sample_swaps_7d": 20,
        "meaningful_swaps_7d": 18,
        "hydration_swaps_found": 20,
        "swaps_7d": 20,
        "unique_tokens_7d": 6,
        "buys_7d": 11,
        "sells_7d": 9,
        "size_compatibility_ratio_7d": 0.8,
        "round_trip_token_ratio_7d": 0.6,
        "buy_sell_balance_score_7d": 90,
        "top_token_concentration_7d": 0.3,
        "dust_ratio_7d": 0.05,
        "invalid_amount_swaps_7d": 0,
        "hydration_status": "COMPLETED",
        "extended_history_status": "NEVER",
        "backtest_history_span_days": 7,
        "backtest_data_sufficient": False,
        "exitability_gate_status": "NON_ANALIZZATO",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_ready_gate_is_ready_for_selection():
    result = evaluate_candidate(
        wallet(exitability_gate_status="READY")
    )
    assert result["status"] == "READY"
    assert result["action"] == "READY_FOR_SELECTION"
    assert result["history_candidate"] is False


def test_hard_exitability_block_stays_blocked():
    result = evaluate_candidate(
        wallet(exitability_gate_status="BLOCKED")
    )
    assert result["status"] == "BLOCKED"
    assert result["action"] == "DO_NOT_PROMOTE"
    assert "FUNNEL_EXITABILITY_HARD_BLOCK" in result["reasons"]


def test_promotion_gate_reason_blocks_history_queue():
    result = evaluate_candidate(
        wallet(
            promotion_reasons=[
                "QUALITY_NOT_COPYABLE",
            ],
        )
    )

    assert result["status"] == "BLOCKED"
    assert result["action"] == "DO_NOT_PROMOTE"
    assert result["history_candidate"] is False
    assert (
        "FUNNEL_PROMOTION_GATE_QUALITY_NOT_COPYABLE"
        in result["reasons"]
    )


def test_low_promotion_score_blocks_history_queue():
    result = evaluate_candidate(
        wallet(
            promotion_reasons=[
                "SMART_SCORE_BELOW_PROMOTION_MINIMUM",
            ],
        )
    )

    assert result["status"] == "BLOCKED"
    assert result["history_candidate"] is False


def test_rejected_promotion_status_is_terminal():
    result = evaluate_candidate(
        wallet(
            promotion_status="BOCCIATO",
        )
    )

    assert result["status"] == "BLOCKED"
    assert (
        "FUNNEL_PROMOTION_STATUS_REJECTED"
        in result["reasons"]
    )


def test_exit_price_block_is_terminal():
    result = evaluate_candidate(
        wallet(
            exit_price_coverage_status="BLOCKED",
        )
    )

    assert result["status"] == "BLOCKED"
    assert result["history_candidate"] is False
    assert (
        "FUNNEL_EXIT_PRICE_AUDIT_BLOCK"
        in result["reasons"]
    )


def test_missing_local_sample_requests_controlled_hydration():
    result = evaluate_candidate(
        wallet(
            quality_classification="NON_ANALIZZATO",
            quality_sample_swaps_7d=0,
            meaningful_swaps_7d=0,
            hydration_swaps_found=0,
            swaps_7d=0,
            unique_tokens_7d=0,
            buys_7d=0,
            sells_7d=0,
            hydration_status="NEVER",
        )
    )
    assert result["status"] == "NEEDS_LOCAL_DATA"
    assert result["action"] == "RUN_CONTROLLED_HYDRATION"


def test_promising_local_sample_enters_history_queue():
    result = evaluate_candidate(
        wallet(backtest_history_span_days=8),
        target_history_days=30,
    )
    assert result["status"] == "NEEDS_HISTORY"
    assert result["history_candidate"] is True
    assert result["recommended_history_budget"] >= 2


def test_complete_but_insufficient_history_requires_review_not_more_budget():
    result = evaluate_candidate(
        wallet(
            extended_history_status="COMPLETED",
            backtest_history_span_days=30,
            backtest_data_sufficient=False,
        ),
        target_history_days=30,
    )
    assert result["status"] == "REVIEW"
    assert result["history_candidate"] is False


def test_last_page_marks_history_as_exhausted_below_target():
    result = evaluate_candidate(
        wallet(
            extended_history_status="COMPLETED",
            extended_history_stop_reason="LAST_PAGE",
            extended_history_lookback_days=30,
            backtest_history_span_days=29.4,
            backtest_data_sufficient=False,
        ),
        target_history_days=30,
    )

    assert result["status"] == "REVIEW"
    assert result["action"] == "REVIEW_CACHED_EVIDENCE"
    assert result["history_candidate"] is False
    assert result["recommended_history_budget"] == 0
    assert result["reasons"] == [
        "FUNNEL_HISTORY_COMPLETE_BUT_BACKTEST_INSUFFICIENT"
    ]


def test_reached_lookback_marks_history_complete_below_exact_span():
    result = evaluate_candidate(
        wallet(
            extended_history_status="COMPLETED",
            extended_history_stop_reason="LOOKBACK_REACHED",
            extended_history_lookback_days=30,
            backtest_history_span_days=29.4,
            backtest_data_sufficient=False,
        ),
        target_history_days=30,
    )

    assert result["status"] == "REVIEW"
    assert result["history_candidate"] is False
    assert result["recommended_history_budget"] == 0


def test_budget_is_diversified_before_extra_requests():
    candidates = [
        {
            "wallet_address": "A",
            "score": 90,
            "smart_score": 90,
            "quality_score": 90,
            "current_history_span_days": 5,
            "recommended_history_budget": 5,
            "reasons": ["A"],
        },
        {
            "wallet_address": "B",
            "score": 80,
            "smart_score": 80,
            "quality_score": 80,
            "current_history_span_days": 5,
            "recommended_history_budget": 5,
            "reasons": ["B"],
        },
        {
            "wallet_address": "C",
            "score": 70,
            "smart_score": 70,
            "quality_score": 70,
            "current_history_span_days": 5,
            "recommended_history_budget": 5,
            "reasons": ["C"],
        },
    ]
    queue = _allocate_history_budget(
        candidates,
        total_budget=3,
        max_wallets=3,
    )
    assert [row["allocated_requests"] for row in queue] == [1, 1, 1]
    assert [row["priority"] for row in queue] == [1, 2, 3]



def test_unhydrated_wallet_requires_local_data_instead_of_terminal_block():
    result = evaluate_candidate(
        wallet(
            activity_classification="INATTIVO",
            quality_classification="NON_COPIABILE",
            quality_sample_swaps_7d=0,
            meaningful_swaps_7d=0,
            hydration_swaps_found=0,
            swaps_7d=0,
            unique_tokens_7d=0,
            buys_7d=0,
            sells_7d=0,
            hydration_status="NEVER",
        )
    )

    assert result["status"] == "NEEDS_LOCAL_DATA"
    assert result["action"] == "RUN_CONTROLLED_HYDRATION"
    assert result["history_candidate"] is False
    assert result["recommended_history_budget"] == 0
    assert (
        "FUNNEL_CONTROLLED_HYDRATION_REQUIRED"
        in result["reasons"]
    )


def test_inactive_wallet_with_local_evidence_remains_terminal():
    result = evaluate_candidate(
        wallet(
            activity_classification="INATTIVO",
        )
    )

    assert result["status"] == "BLOCKED"
    assert result["action"] == "DO_NOT_PROMOTE"
    assert result["history_candidate"] is False
    assert (
        "FUNNEL_INACTIVE_WALLET"
        in result["reasons"]
    )


def test_terminal_promotion_reason_blocks_even_without_local_data():
    result = evaluate_candidate(
        wallet(
            promotion_reasons=[
                "QUALITY_NOT_COPYABLE",
            ],
            activity_classification="INATTIVO",
            quality_classification="NON_COPIABILE",
            quality_sample_swaps_7d=0,
            meaningful_swaps_7d=0,
            hydration_swaps_found=0,
            swaps_7d=0,
            unique_tokens_7d=0,
            buys_7d=0,
            sells_7d=0,
            hydration_status="NEVER",
        )
    )

    assert result["status"] == "BLOCKED"
    assert result["action"] == "DO_NOT_PROMOTE"
    assert result["history_candidate"] is False
    assert (
        "FUNNEL_PROMOTION_GATE_QUALITY_NOT_COPYABLE"
        in result["reasons"]
    )
