from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.models.candidate_discovery_funnel import (
    CandidateDiscoveryFunnelRun,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.services.wallet_activity_service import safe_float


FUNNEL_READY = "READY"
FUNNEL_REVIEW = "REVIEW"
FUNNEL_BLOCKED = "BLOCKED"
FUNNEL_NEEDS_LOCAL_DATA = "NEEDS_LOCAL_DATA"
FUNNEL_NEEDS_HISTORY = "NEEDS_HISTORY"

ACTION_READY_FOR_SELECTION = "READY_FOR_SELECTION"
ACTION_REVIEW_CACHED_EVIDENCE = "REVIEW_CACHED_EVIDENCE"
ACTION_DO_NOT_PROMOTE = "DO_NOT_PROMOTE"
ACTION_RUN_CONTROLLED_HYDRATION = "RUN_CONTROLLED_HYDRATION"
ACTION_QUEUE_HISTORY_BACKFILL = "QUEUE_HISTORY_BACKFILL"

MIN_LOCAL_SAMPLE = 6
MIN_UNIQUE_TOKENS = 2
MIN_SMART_SCORE = 40.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, safe_float(value)))


def _ratio_percent(value: float) -> float:
    number = safe_float(value)
    if 0 <= number <= 1:
        number *= 100
    return _clip(number)


def _local_sample(wallet: DiscoveredWallet) -> int:
    return max(
        int(wallet.quality_sample_swaps_7d or 0),
        int(wallet.meaningful_swaps_7d or 0),
        int(wallet.hydration_swaps_found or 0),
        int(wallet.swaps_7d or 0),
    )


def _score(wallet: DiscoveredWallet) -> float:
    sample = _local_sample(wallet)
    sample_score = min(100.0, (sample / 30.0) * 100.0)
    concentration_score = 100.0 - _ratio_percent(
        wallet.top_token_concentration_7d
    )
    dust_percent = _ratio_percent(wallet.dust_ratio_7d)

    score = (
        _clip(wallet.smart_score) * 0.20
        + _clip(wallet.activity_score) * 0.15
        + _clip(wallet.quality_score) * 0.25
        + _ratio_percent(wallet.size_compatibility_ratio_7d) * 0.12
        + _ratio_percent(wallet.round_trip_token_ratio_7d) * 0.10
        + _clip(wallet.buy_sell_balance_score_7d) * 0.08
        + sample_score * 0.05
        + concentration_score * 0.05
    )

    score -= min(15.0, dust_percent * 0.15)
    score -= min(10.0, int(wallet.invalid_amount_swaps_7d or 0) * 2.5)
    if int(wallet.sells_7d or 0) <= 0:
        score -= 8.0
    if str(wallet.activity_classification) == "POCO_ATTIVO":
        score -= 4.0
    if str(wallet.exitability_gate_status) == "READY":
        score += 5.0
    elif str(wallet.exitability_gate_status) == "BLOCKED":
        score -= 25.0

    return round(_clip(score), 2)


def _hard_block_reasons(wallet: DiscoveredWallet) -> list[str]:
    reasons: list[str] = []
    if str(wallet.exitability_gate_status) == "BLOCKED":
        reasons.append("FUNNEL_EXITABILITY_HARD_BLOCK")
    if str(wallet.quality_classification) in {"SOSPETTO", "NON_COPIABILE"}:
        reasons.append("FUNNEL_QUALITY_BLOCK")
    if str(wallet.activity_classification) == "INATTIVO":
        reasons.append("FUNNEL_INACTIVE_WALLET")
    if (
        _local_sample(wallet) >= 10
        and _ratio_percent(wallet.dust_ratio_7d) >= 80
    ):
        reasons.append("FUNNEL_EXCESSIVE_DUST")
    if (
        _local_sample(wallet) >= 10
        and _ratio_percent(wallet.top_token_concentration_7d) >= 95
    ):
        reasons.append("FUNNEL_EXTREME_TOKEN_CONCENTRATION")
    if (
        _has_local_data(wallet)
        and _clip(wallet.smart_score) < MIN_SMART_SCORE
    ):
        reasons.append("FUNNEL_SMART_SCORE_TOO_LOW")
    return reasons


def _has_local_data(wallet: DiscoveredWallet) -> bool:
    return bool(
        _local_sample(wallet) >= MIN_LOCAL_SAMPLE
        and int(wallet.unique_tokens_7d or 0) >= MIN_UNIQUE_TOKENS
        and int(wallet.buys_7d or 0) >= 2
        and int(wallet.sells_7d or 0) >= 1
        and str(wallet.activity_classification) != "NON_ANALIZZATO"
        and str(wallet.quality_classification) != "NON_ANALIZZATO"
    )


def _history_complete_for_target(
    wallet: DiscoveredWallet,
    target_history_days: int,
) -> bool:
    return bool(
        str(wallet.extended_history_status) == "COMPLETED"
        and safe_float(wallet.backtest_history_span_days) >= target_history_days
    )


def evaluate_candidate(
    wallet: DiscoveredWallet,
    *,
    target_history_days: int = 30,
) -> dict:
    score = _score(wallet)
    hard_block_reasons = _hard_block_reasons(wallet)
    if hard_block_reasons:
        return {
            "status": FUNNEL_BLOCKED,
            "score": score,
            "action": ACTION_DO_NOT_PROMOTE,
            "reasons": hard_block_reasons,
            "history_candidate": False,
            "recommended_history_budget": 0,
        }

    if str(wallet.exitability_gate_status) == "READY":
        return {
            "status": FUNNEL_READY,
            "score": score,
            "action": ACTION_READY_FOR_SELECTION,
            "reasons": ["FUNNEL_EXITABILITY_READY"],
            "history_candidate": False,
            "recommended_history_budget": 0,
        }

    if str(wallet.exitability_gate_status) == "REVIEW":
        return {
            "status": FUNNEL_REVIEW,
            "score": score,
            "action": ACTION_REVIEW_CACHED_EVIDENCE,
            "reasons": ["FUNNEL_EXITABILITY_REVIEW"],
            "history_candidate": False,
            "recommended_history_budget": 0,
        }

    if not _has_local_data(wallet):
        reasons = ["FUNNEL_LOCAL_SAMPLE_INSUFFICIENT"]
        if str(wallet.hydration_status) in {"NEVER", "EMPTY", "FAILED"}:
            reasons.append("FUNNEL_CONTROLLED_HYDRATION_REQUIRED")
        if int(wallet.sells_7d or 0) <= 0:
            reasons.append("FUNNEL_NO_LOCAL_SELL_SAMPLE")
        return {
            "status": FUNNEL_NEEDS_LOCAL_DATA,
            "score": score,
            "action": ACTION_RUN_CONTROLLED_HYDRATION,
            "reasons": reasons,
            "history_candidate": False,
            "recommended_history_budget": 0,
        }

    if bool(wallet.backtest_data_sufficient):
        return {
            "status": FUNNEL_REVIEW,
            "score": score,
            "action": ACTION_REVIEW_CACHED_EVIDENCE,
            "reasons": ["FUNNEL_CACHED_AUDIT_PIPELINE_REQUIRED"],
            "history_candidate": False,
            "recommended_history_budget": 0,
        }

    if _history_complete_for_target(wallet, target_history_days):
        return {
            "status": FUNNEL_REVIEW,
            "score": score,
            "action": ACTION_REVIEW_CACHED_EVIDENCE,
            "reasons": ["FUNNEL_HISTORY_COMPLETE_BUT_BACKTEST_INSUFFICIENT"],
            "history_candidate": False,
            "recommended_history_budget": 0,
        }

    current_span = safe_float(wallet.backtest_history_span_days)
    gap_days = max(0.0, float(target_history_days) - current_span)
    recommended_budget = max(1, min(5, int(ceil(gap_days / 7.0))))
    if str(wallet.extended_history_status) in {"NEVER", "EMPTY"}:
        recommended_budget = max(2, recommended_budget)

    return {
        "status": FUNNEL_NEEDS_HISTORY,
        "score": score,
        "action": ACTION_QUEUE_HISTORY_BACKFILL,
        "reasons": [
            "FUNNEL_PROMISING_LOCAL_SAMPLE",
            "FUNNEL_HISTORY_REQUIRED",
        ],
        "history_candidate": True,
        "recommended_history_budget": recommended_budget,
    }


def _allocate_history_budget(
    candidates: list[dict],
    *,
    total_budget: int,
    max_wallets: int,
) -> list[dict]:
    selected = sorted(
        candidates,
        key=lambda row: (
            -safe_float(row["score"]),
            -safe_float(row["smart_score"]),
            str(row["wallet_address"]),
        ),
    )[:max_wallets]

    remaining = max(0, int(total_budget))
    allocations = {str(row["wallet_address"]): 0 for row in selected}

    for row in selected:
        if remaining <= 0:
            break
        address = str(row["wallet_address"])
        allocations[address] += 1
        remaining -= 1

    while remaining > 0:
        changed = False
        for row in selected:
            if remaining <= 0:
                break
            address = str(row["wallet_address"])
            recommended = int(row["recommended_history_budget"] or 0)
            if allocations[address] >= recommended:
                continue
            allocations[address] += 1
            remaining -= 1
            changed = True
        if not changed:
            break

    queue: list[dict] = []
    for index, row in enumerate(selected, start=1):
        address = str(row["wallet_address"])
        allocated = allocations[address]
        if allocated <= 0:
            continue
        queue.append({
            "priority": index,
            "wallet_address": address,
            "funnel_score": row["score"],
            "smart_score": row["smart_score"],
            "quality_score": row["quality_score"],
            "current_history_span_days": row["current_history_span_days"],
            "recommended_requests": row["recommended_history_budget"],
            "allocated_requests": allocated,
            "action": ACTION_QUEUE_HISTORY_BACKFILL,
            "manual_only": True,
            "reasons": row["reasons"],
        })
    return queue


def run_candidate_discovery_funnel(
    db: Session,
    *,
    limit: int = 500,
    history_request_budget: int = 10,
    max_history_wallets: int = 5,
    target_history_days: int = 30,
    now: datetime | None = None,
) -> CandidateDiscoveryFunnelRun:
    started_at = now or utc_now()
    effective_limit = max(1, min(int(limit), 500))
    effective_budget = max(0, min(int(history_request_budget), 50))
    effective_max_history_wallets = max(1, min(int(max_history_wallets), 20))
    effective_target_days = max(7, min(int(target_history_days), 90))

    wallets = (
        db.query(DiscoveredWallet)
        .order_by(
            DiscoveredWallet.ranking_score.desc(),
            DiscoveredWallet.smart_score.desc(),
        )
        .limit(effective_limit)
        .all()
    )

    counts = {
        FUNNEL_READY: 0,
        FUNNEL_REVIEW: 0,
        FUNNEL_BLOCKED: 0,
        FUNNEL_NEEDS_LOCAL_DATA: 0,
        FUNNEL_NEEDS_HISTORY: 0,
    }
    results: list[dict] = []
    history_candidates: list[dict] = []

    for wallet in wallets:
        outcome = evaluate_candidate(
            wallet,
            target_history_days=effective_target_days,
        )
        wallet.discovery_funnel_status = outcome["status"]
        wallet.discovery_funnel_score = outcome["score"]
        wallet.discovery_funnel_priority = 0
        wallet.discovery_funnel_action = outcome["action"]
        wallet.discovery_funnel_reasons = outcome["reasons"]
        wallet.discovery_funnel_history_budget = 0
        wallet.discovery_funnel_calculated_at = started_at

        row = {
            "wallet_address": wallet.wallet_address,
            **outcome,
            "smart_score": safe_float(wallet.smart_score),
            "activity_score": safe_float(wallet.activity_score),
            "quality_score": safe_float(wallet.quality_score),
            "local_sample_swaps": _local_sample(wallet),
            "current_history_span_days": safe_float(
                wallet.backtest_history_span_days
            ),
            "exitability_gate_status": str(wallet.exitability_gate_status),
        }
        counts[outcome["status"]] += 1
        results.append(row)
        if outcome["history_candidate"]:
            history_candidates.append(row)

    history_queue = _allocate_history_budget(
        history_candidates,
        total_budget=effective_budget,
        max_wallets=effective_max_history_wallets,
    )
    queue_by_wallet = {
        row["wallet_address"]: row
        for row in history_queue
    }
    wallets_by_address = {
        wallet.wallet_address: wallet
        for wallet in wallets
    }
    for address, queue_row in queue_by_wallet.items():
        wallet = wallets_by_address[address]
        wallet.discovery_funnel_priority = int(queue_row["priority"])
        wallet.discovery_funnel_history_budget = int(
            queue_row["allocated_requests"]
        )

    allocated_budget = sum(
        int(row["allocated_requests"])
        for row in history_queue
    )
    run = CandidateDiscoveryFunnelRun(
        run_id=str(uuid4()),
        status="COMPLETED",
        parameters={
            "limit": effective_limit,
            "history_request_budget": effective_budget,
            "max_history_wallets": effective_max_history_wallets,
            "target_history_days": effective_target_days,
        },
        safety={
            "cached_only": True,
            "history_backfills_started": 0,
            "helius_requests": 0,
            "jupiter_live_requests": 0,
            "live_changed": False,
            "stream_changed": False,
            "worker_changed": False,
            "generation_changed": False,
            "eligibility_changed": False,
            "promotion_status_changed": False,
        },
        summary={
            "wallets_evaluated": len(wallets),
            "wallets_ready": counts[FUNNEL_READY],
            "wallets_review": counts[FUNNEL_REVIEW],
            "wallets_blocked": counts[FUNNEL_BLOCKED],
            "wallets_needs_local_data": counts[FUNNEL_NEEDS_LOCAL_DATA],
            "wallets_needs_history": counts[FUNNEL_NEEDS_HISTORY],
            "history_queue_wallets": len(history_queue),
            "history_budget_requested": effective_budget,
            "history_budget_allocated": allocated_budget,
            "history_budget_unallocated": effective_budget - allocated_budget,
        },
        wallet_results=results,
        history_queue=history_queue,
        started_at=started_at,
        completed_at=started_at,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_latest_candidate_discovery_funnel(
    db: Session,
) -> CandidateDiscoveryFunnelRun | None:
    return (
        db.query(CandidateDiscoveryFunnelRun)
        .order_by(
            CandidateDiscoveryFunnelRun.started_at.desc(),
            CandidateDiscoveryFunnelRun.id.desc(),
        )
        .first()
    )
