from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from statistics import median
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserUnifiedDecisionResult,
    CanonicalParserUnifiedDecisionRun,
    CanonicalParserUnifiedDecisionWalletEvidence,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
from backend.app.models.trade import Trade
from backend.app.models.wallet_edge import WalletEdge
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)

UNIFIED_DECISION_POLICY_VERSION = "canonical-parser-unified-decision/1"
UNIFIED_DECISION_SCOPE = "SHADOW_DECISION_ONLY"
UNIFIED_DECISION_CONFIRMATION = "RUN_UNIFIED_DECISION_SHADOW_VALIDATION"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500
_MONEY_QUANTUM = Decimal("0.000000001")
_SCORE_QUANTUM = Decimal("0.0001")


class CanonicalParserUnifiedDecisionError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    resolved = value or _utc_now()
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _actor(value: str | None) -> str:
    return (
        sanitize_error_message(
            value or "LOCAL_UNIFIED_DECISION_SHADOW",
            max_length=_MAX_ACTOR_LENGTH,
        )
        or "LOCAL_UNIFIED_DECISION_SHADOW"
    )


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
    if not resolved.is_finite():
        return default
    return resolved


def _money(value: Any) -> Decimal:
    return max(Decimal("0"), _decimal(value)).quantize(_MONEY_QUANTUM, rounding=ROUND_DOWN)


def _score(value: Any) -> Decimal:
    resolved = max(Decimal("0"), min(Decimal("100"), _decimal(value)))
    return resolved.quantize(_SCORE_QUANTUM)


def _score_float(value: Any) -> float:
    return float(_score(value))


def _money_text(value: Any) -> str:
    return format(_money(value), "f")


def _score_text(value: Any) -> str:
    return format(_score(value), "f")


def _clamp(value: Any, minimum: float = 0.0, maximum: float = 100.0) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        resolved = minimum
    return max(minimum, min(maximum, resolved))


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": UNIFIED_DECISION_POLICY_VERSION,
        "scope": UNIFIED_DECISION_SCOPE,
        "lookback_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_LOOKBACK_MINUTES", 1440)
        ),
        "max_source_trades": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MAX_SOURCE_TRADES", 1000)
        ),
        "max_results": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MAX_RESULTS", 100)
        ),
        "validity_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_VALIDITY_MINUTES", 30)
        ),
        "wallet_freshness_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_WALLET_FRESHNESS_MINUTES", 1440)
        ),
        "token_freshness_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_TOKEN_FRESHNESS_MINUTES", 30)
        ),
        "minimum_qualified_wallets": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MIN_QUALIFIED_WALLETS", 2)
        ),
        "minimum_independent_clusters": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MIN_INDEPENDENT_CLUSTERS", 2)
        ),
        "minimum_approve_score": float(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MIN_APPROVE_SCORE", 72.0)
        ),
        "minimum_review_score": float(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MIN_REVIEW_SCORE", 55.0)
        ),
        "maximum_copy_latency_seconds": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MAX_COPY_LATENCY_SECONDS", 180)
        ),
        "maximum_stale_seconds": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MAX_STALE_SECONDS", 900)
        ),
        "minimum_token_liquidity_usd": float(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MIN_TOKEN_LIQUIDITY_USD", 25000.0)
        ),
        "maximum_token_risk_score": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MAX_TOKEN_RISK_SCORE", 35)
        ),
        "maximum_top_holder_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MAX_TOP_HOLDER_PERCENT", 25.0)
        ),
        "minimum_edge_strength": float(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MIN_EDGE_STRENGTH", 60.0)
        ),
        "follower_delay_seconds": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_FOLLOWER_DELAY_SECONDS", 30)
        ),
        "maximum_size_sol": _money_text(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MAX_SIZE_SOL", 0.05)
        ),
        "stop_loss_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_STOP_LOSS_PERCENT", 15.0)
        ),
        "take_profit_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_TAKE_PROFIT_PERCENT", 30.0)
        ),
        "maximum_hold_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_MAX_HOLD_MINUTES", 240)
        ),
        "wallet_requirements": {
            "discovered_wallet_eligible": True,
            "activity_eligible": True,
            "quality_eligible": True,
            "promotion_eligible": True,
            "backtest_data_sufficient": True,
            "exitability_gate_eligible": True,
        },
        "confidence_calibration_status": "BASELINE_HEURISTIC_UNCALIBRATED",
        "point_in_time_guard": True,
        "provider_cross_check": "LOCAL_EVIDENCE_ONLY",
        "counterfactual_latency_seconds": [5, 15, 30],
        "manual_run_only": True,
        "external_requests_allowed": False,
        "paper_execution_connected": False,
        "paper_order_writes": False,
        "paper_position_writes": False,
        "paper_account_writes": False,
        "permit_consumption_connected": False,
        "trade_writes": False,
        "live_execution_authorized": False,
        "worker_connected": False,
        "scheduler_connected": False,
        "stream_connected": False,
        "position_monitor_connected": False,
    }


def _safety_contract() -> dict[str, Any]:
    return {
        "scope": UNIFIED_DECISION_SCOPE,
        "read_only_source_tables": [
            "trades",
            "discovered_wallets",
            "wallet_edges",
            "token_safety_snapshots",
        ],
        "writes_only_metadata_tables": [
            "canonical_parser_unified_decision_runs",
            "canonical_parser_unified_decision_results",
            "canonical_parser_unified_decision_wallet_evidence",
        ],
        "paper_execution_connected": False,
        "permit_consumption_connected": False,
        "paper_order_writes": False,
        "paper_position_writes": False,
        "paper_account_writes": False,
        "trade_writes": False,
        "live_execution_authorized": False,
        "external_requests_allowed": False,
        "worker_start": False,
        "scheduler_start": False,
        "stream_start": False,
        "position_monitor_start": False,
    }


def _freshness_status(
    timestamps: list[datetime | None],
    *,
    evaluated_at: datetime,
    max_age_minutes: int,
) -> tuple[str, list[str], float | None]:
    reasons: list[str] = []
    if any(value is None for value in timestamps):
        return "MISSING", ["WALLET_EVIDENCE_TIMESTAMP_MISSING"], None
    aware_values = [_aware(value) for value in timestamps if value is not None]
    if any(value > evaluated_at for value in aware_values):
        return "FUTURE", ["WALLET_EVIDENCE_FROM_FUTURE"], None
    oldest = min(aware_values)
    age_minutes = max(0.0, (evaluated_at - oldest).total_seconds() / 60.0)
    if age_minutes > max_age_minutes:
        reasons.append("WALLET_EVIDENCE_EXPIRED")
        return "EXPIRED", reasons, round(age_minutes, 4)
    return "FRESH", reasons, round(age_minutes, 4)


def _wallet_snapshot(wallet: DiscoveredWallet) -> dict[str, Any]:
    return {
        "wallet_address": wallet.wallet_address,
        "eligible": bool(wallet.eligible),
        "smart_score": round(float(wallet.smart_score or 0), 4),
        "ranking_score": round(float(wallet.ranking_score or 0), 4),
        "activity_score": round(float(wallet.activity_score or 0), 4),
        "activity_classification": wallet.activity_classification,
        "activity_eligible": bool(wallet.activity_eligible),
        "quality_score": round(float(wallet.quality_score or 0), 4),
        "quality_classification": wallet.quality_classification,
        "quality_eligible": bool(wallet.quality_eligible),
        "promotion_status": wallet.promotion_status,
        "promotion_eligible": bool(wallet.promotion_eligible),
        "latest_backtest_run_id": wallet.latest_backtest_run_id,
        "backtest_score": round(float(wallet.backtest_score or 0), 4),
        "backtest_total_return_percent": round(float(wallet.backtest_total_return_percent or 0), 4),
        "backtest_win_rate_percent": round(float(wallet.backtest_win_rate_percent or 0), 4),
        "backtest_profit_factor": None if wallet.backtest_profit_factor is None else round(float(wallet.backtest_profit_factor), 4),
        "backtest_max_drawdown_percent": round(float(wallet.backtest_max_drawdown_percent or 0), 4),
        "backtest_completed_positions": int(wallet.backtest_completed_positions or 0),
        "backtest_execution_coverage_percent": round(float(wallet.backtest_execution_coverage_percent or 0), 4),
        "backtest_jupiter_status": wallet.backtest_jupiter_status,
        "backtest_jupiter_compatibility_percent": round(float(wallet.backtest_jupiter_compatibility_percent or 0), 4),
        "backtest_data_sufficient": bool(wallet.backtest_data_sufficient),
        "backtest_data_sufficiency_score": round(float(wallet.backtest_data_sufficiency_score or 0), 4),
        "backtest_history_span_days": round(float(wallet.backtest_history_span_days or 0), 4),
        "backtest_matched_sell_ratio_percent": round(float(wallet.backtest_matched_sell_ratio_percent or 0), 4),
        "exitability_gate_status": wallet.exitability_gate_status,
        "exitability_gate_score": round(float(wallet.exitability_gate_score or 0), 4),
        "exitability_gate_eligible": bool(wallet.exitability_gate_eligible),
        "top_token_concentration_7d": round(float(wallet.top_token_concentration_7d or 0), 6),
        "buy_sell_balance_score_7d": round(float(wallet.buy_sell_balance_score_7d or 0), 4),
        "quality_sample_swaps_7d": int(wallet.quality_sample_swaps_7d or 0),
        "meaningful_swaps_7d": int(wallet.meaningful_swaps_7d or 0),
        "reliable_positions": int(wallet.reliable_positions or 0),
        "activity_calculated_at": None if wallet.activity_calculated_at is None else _aware(wallet.activity_calculated_at).isoformat(),
        "quality_calculated_at": None if wallet.quality_calculated_at is None else _aware(wallet.quality_calculated_at).isoformat(),
        "promotion_calculated_at": None if wallet.promotion_calculated_at is None else _aware(wallet.promotion_calculated_at).isoformat(),
        "exitability_gate_calculated_at": None if wallet.exitability_gate_calculated_at is None else _aware(wallet.exitability_gate_calculated_at).isoformat(),
        "eligibility_reasons": list(wallet.eligibility_reasons or []),
        "activity_reasons": list(wallet.activity_reasons or []),
        "quality_reasons": list(wallet.quality_reasons or []),
        "promotion_reasons": list(wallet.promotion_reasons or []),
        "backtest_data_sufficiency_reasons": list(wallet.backtest_data_sufficiency_reasons or []),
        "exitability_gate_reasons": list(wallet.exitability_gate_reasons or []),
    }


def _qualify_wallet(
    wallet: DiscoveredWallet | None,
    *,
    evaluated_at: datetime,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if wallet is None:
        snapshot = {"wallet_present": False}
        return {
            "qualification_status": "INSUFFICIENT_DATA",
            "final_score": 0.0,
            "confidence_score": 0.0,
            "freshness_status": "MISSING",
            "reason_codes": ["DISCOVERED_WALLET_NOT_FOUND"],
            "positive_factors": [],
            "snapshot": snapshot,
        }

    snapshot = _wallet_snapshot(wallet)
    freshness, freshness_reasons, age_minutes = _freshness_status(
        [
            wallet.activity_calculated_at,
            wallet.quality_calculated_at,
            wallet.promotion_calculated_at,
            wallet.exitability_gate_calculated_at,
        ],
        evaluated_at=evaluated_at,
        max_age_minutes=int(policy["wallet_freshness_minutes"]),
    )
    snapshot["freshness_age_minutes"] = age_minutes

    components = {
        "smart": _clamp(wallet.smart_score) * 0.15,
        "ranking": _clamp(wallet.ranking_score) * 0.15,
        "activity": _clamp(wallet.activity_score) * 0.10,
        "quality": _clamp(wallet.quality_score) * 0.15,
        "backtest": _clamp(wallet.backtest_score) * 0.25,
        "exitability": _clamp(wallet.exitability_gate_score) * 0.15,
        "data_sufficiency": _clamp(wallet.backtest_data_sufficiency_score) * 0.05,
    }
    final_score = round(sum(components.values()), 4)

    confidence_components = {
        "data_sufficiency": _clamp(wallet.backtest_data_sufficiency_score) * 0.25,
        "completed_positions": min(int(wallet.backtest_completed_positions or 0) / 20.0, 1.0) * 25.0,
        "history_span": min(float(wallet.backtest_history_span_days or 0) / 30.0, 1.0) * 20.0,
        "execution_coverage": _clamp(wallet.backtest_execution_coverage_percent) * 0.15,
        "matched_sells": _clamp(wallet.backtest_matched_sell_ratio_percent) * 0.15,
    }
    confidence_score = round(sum(confidence_components.values()), 4)

    reasons: set[str] = set(freshness_reasons)
    positives: set[str] = set()
    hard_reject = False
    review = False

    requirements = [
        (bool(wallet.eligible), "DISCOVERED_WALLET_NOT_ELIGIBLE"),
        (bool(wallet.activity_eligible), "WALLET_ACTIVITY_NOT_ELIGIBLE"),
        (bool(wallet.quality_eligible), "WALLET_QUALITY_NOT_ELIGIBLE"),
        (bool(wallet.promotion_eligible), "WALLET_PROMOTION_NOT_ELIGIBLE"),
        (bool(wallet.backtest_data_sufficient), "WALLET_BACKTEST_DATA_INSUFFICIENT"),
        (bool(wallet.exitability_gate_eligible), "WALLET_EXITABILITY_NOT_ELIGIBLE"),
    ]
    for passed, code in requirements:
        if passed:
            positives.add(code.replace("NOT_", "").replace("_INSUFFICIENT", "_SUFFICIENT"))
        else:
            reasons.add(code)
            hard_reject = True

    if not wallet.latest_backtest_run_id:
        reasons.add("WALLET_BACKTEST_RUN_MISSING")
        hard_reject = True
    if int(wallet.backtest_completed_positions or 0) < 3:
        reasons.add("WALLET_BACKTEST_SAMPLE_TOO_SMALL")
        review = True
    if float(wallet.backtest_history_span_days or 0) < 7:
        reasons.add("WALLET_HISTORY_SPAN_SHORT")
        review = True
    if float(wallet.backtest_execution_coverage_percent or 0) < 70:
        reasons.add("WALLET_EXECUTION_COVERAGE_LOW")
        review = True
    if float(wallet.backtest_matched_sell_ratio_percent or 0) < 70:
        reasons.add("WALLET_MATCHED_SELL_RATIO_LOW")
        review = True
    if str(wallet.backtest_jupiter_status or "").upper() not in {"COMPATIBLE", "PASSED", "READY"}:
        reasons.add("WALLET_JUPITER_COMPATIBILITY_NOT_READY")
        review = True
    if float(wallet.backtest_jupiter_compatibility_percent or 0) < 70:
        reasons.add("WALLET_JUPITER_COMPATIBILITY_LOW")
        review = True
    if float(wallet.top_token_concentration_7d or 0) >= 0.95 and float(wallet.buy_sell_balance_score_7d or 0) < 20:
        reasons.add("POTENTIAL_COPYTRADER_BAIT")
        hard_reject = True
    elif float(wallet.top_token_concentration_7d or 0) >= 0.85:
        reasons.add("WALLET_PROFIT_CONCENTRATION_RISK")
        review = True
    if str(wallet.quality_classification or "").upper() == "SOSPETTO":
        reasons.add("POTENTIAL_COPYTRADER_BAIT")
        hard_reject = True

    if freshness == "MISSING" or freshness == "FUTURE":
        status = "INSUFFICIENT_DATA"
    elif freshness == "EXPIRED":
        status = "EXPIRED"
    elif hard_reject:
        status = "REJECTED"
    elif review or final_score < 60 or confidence_score < 50:
        status = "REVIEW"
        if final_score < 60:
            reasons.add("WALLET_FINAL_SCORE_BELOW_QUALIFICATION")
        if confidence_score < 50:
            reasons.add("WALLET_CONFIDENCE_BELOW_QUALIFICATION")
    else:
        status = "QUALIFIED"
        positives.add("WALLET_UNIFIED_QUALIFICATION_PASSED")

    snapshot["score_components"] = {key: round(value, 4) for key, value in components.items()}
    snapshot["confidence_components"] = {
        key: round(value, 4) for key, value in confidence_components.items()
    }
    snapshot["non_replicable_profit_checks"] = {
        "history_span_sufficient": float(wallet.backtest_history_span_days or 0) >= 7,
        "completed_positions_sufficient": int(wallet.backtest_completed_positions or 0) >= 3,
        "execution_coverage_sufficient": float(wallet.backtest_execution_coverage_percent or 0) >= 70,
        "matched_sell_ratio_sufficient": float(wallet.backtest_matched_sell_ratio_percent or 0) >= 70,
        "jupiter_compatibility_sufficient": float(wallet.backtest_jupiter_compatibility_percent or 0) >= 70,
        "concentration_acceptable": float(wallet.top_token_concentration_7d or 0) < 0.85,
    }
    return {
        "qualification_status": status,
        "final_score": final_score,
        "confidence_score": confidence_score,
        "freshness_status": freshness,
        "reason_codes": sorted(reasons),
        "positive_factors": sorted(positives),
        "snapshot": snapshot,
    }


def _cluster_map(
    db: Session,
    addresses: list[str],
    *,
    minimum_strength: float,
) -> dict[str, str]:
    unique = sorted(set(addresses))
    if not unique:
        return {}
    graph: dict[str, set[str]] = {address: set() for address in unique}
    edges = list(
        db.scalars(
            select(WalletEdge).where(
                WalletEdge.source_wallet.in_(unique),
                WalletEdge.target_wallet.in_(unique),
                WalletEdge.strength >= minimum_strength,
            )
        )
    )
    for edge in edges:
        if edge.source_wallet in graph and edge.target_wallet in graph:
            graph[edge.source_wallet].add(edge.target_wallet)
            graph[edge.target_wallet].add(edge.source_wallet)

    mapping: dict[str, str] = {}
    visited: set[str] = set()
    for address in unique:
        if address in visited:
            continue
        stack = [address]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(sorted(graph[current] - visited))
        key = calculate_payload_hash({"wallets": sorted(component), "minimum_strength": minimum_strength})
        for item in component:
            mapping[item] = key
    return mapping


def _raw_trade_conflicts(trades: list[Trade]) -> list[str]:
    reasons: set[str] = set()
    signatures: set[str] = set()
    for trade in trades:
        if trade.signature in signatures:
            reasons.add("SOURCE_SIGNATURE_DUPLICATED")
        signatures.add(trade.signature)
        if not trade.raw_json:
            continue
        try:
            payload = json.loads(trade.raw_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            reasons.add("DATA_CONFLICT_RAW_JSON_INVALID")
            continue
        if not isinstance(payload, (dict, list)):
            reasons.add("DATA_CONFLICT_RAW_JSON_SHAPE_INVALID")
    return sorted(reasons)


def _token_assessment(
    db: Session,
    token_mint: str,
    *,
    evaluated_at: datetime,
    policy: dict[str, Any],
) -> dict[str, Any]:
    snapshot = db.scalar(
        select(TokenSafetySnapshot)
        .where(TokenSafetySnapshot.token_mint == token_mint)
        .order_by(desc(TokenSafetySnapshot.fetched_at), desc(TokenSafetySnapshot.id))
        .limit(1)
    )
    if snapshot is None:
        return {
            "status": "INSUFFICIENT_DATA",
            "score": 0.0,
            "reason_codes": ["TOKEN_SAFETY_SNAPSHOT_MISSING"],
            "positive_factors": [],
            "snapshot": None,
        }

    fetched_at = _aware(snapshot.fetched_at)
    age_minutes = (evaluated_at - fetched_at).total_seconds() / 60.0
    if fetched_at > evaluated_at:
        return {
            "status": "INSUFFICIENT_DATA",
            "score": 0.0,
            "reason_codes": ["TOKEN_SAFETY_SNAPSHOT_FROM_FUTURE"],
            "positive_factors": [],
            "snapshot": {"fetched_at": fetched_at.isoformat(), "age_minutes": round(age_minutes, 4)},
        }
    if age_minutes > int(policy["token_freshness_minutes"]):
        return {
            "status": "INSUFFICIENT_DATA",
            "score": 0.0,
            "reason_codes": ["TOKEN_SAFETY_SNAPSHOT_EXPIRED"],
            "positive_factors": [],
            "snapshot": {"fetched_at": fetched_at.isoformat(), "age_minutes": round(age_minutes, 4)},
        }

    reasons: set[str] = set()
    positives: set[str] = set()
    unsafe = False
    review = False

    if bool(snapshot.honeypot):
        reasons.add("TOKEN_HONEYPOT")
        unsafe = True
    else:
        positives.add("TOKEN_NOT_HONEYPOT")
    if bool(snapshot.mint_authority_enabled):
        reasons.add("TOKEN_MINT_AUTHORITY_ENABLED")
        unsafe = True
    else:
        positives.add("TOKEN_MINT_AUTHORITY_DISABLED")
    if bool(snapshot.freeze_authority_enabled):
        reasons.add("TOKEN_FREEZE_AUTHORITY_ENABLED")
        unsafe = True
    else:
        positives.add("TOKEN_FREEZE_AUTHORITY_DISABLED")
    if snapshot.rugged is True:
        reasons.add("TOKEN_RUGGED")
        unsafe = True
    if snapshot.rugcheck_passed is False:
        reasons.add("TOKEN_RUGCHECK_FAILED")
        unsafe = True
    elif snapshot.rugcheck_passed is None:
        reasons.add("TOKEN_RUGCHECK_UNAVAILABLE")
        review = True
    else:
        positives.add("TOKEN_RUGCHECK_PASSED")
    if float(snapshot.liquidity_usd or 0) < float(policy["minimum_token_liquidity_usd"]):
        reasons.add("TOKEN_LIQUIDITY_BELOW_MINIMUM")
        unsafe = True
    else:
        positives.add("TOKEN_LIQUIDITY_SUFFICIENT")
    if int(snapshot.risk_score or 100) > int(policy["maximum_token_risk_score"]):
        reasons.add("TOKEN_RISK_SCORE_ABOVE_MAXIMUM")
        unsafe = True
    else:
        positives.add("TOKEN_RISK_SCORE_ACCEPTABLE")
    if float(snapshot.top_holder_percent or 100) > float(policy["maximum_top_holder_percent"]):
        reasons.add("TOKEN_HOLDER_CONCENTRATION_ABOVE_MAXIMUM")
        unsafe = True
    else:
        positives.add("TOKEN_HOLDER_CONCENTRATION_ACCEPTABLE")

    raw_payload = snapshot.raw_payload if isinstance(snapshot.raw_payload, dict) else {}
    provider_errors = raw_payload.get("provider_errors") if isinstance(raw_payload, dict) else None
    if isinstance(provider_errors, dict) and provider_errors:
        reasons.add("TOKEN_PROVIDER_CROSS_CHECK_PARTIAL")
        review = True

    score = 100.0 - _clamp(snapshot.risk_score)
    if review:
        score = min(score, 69.0)
    if unsafe:
        score = min(score, 25.0)

    status = "UNSAFE" if unsafe else "REVIEW" if review else "SAFE"
    serialized = {
        "token_mint": snapshot.token_mint,
        "liquidity_usd": round(float(snapshot.liquidity_usd or 0), 2),
        "market_cap_usd": round(float(snapshot.market_cap_usd or 0), 2),
        "volume_24h_usd": round(float(snapshot.volume_24h_usd or 0), 2),
        "top_holder_percent": round(float(snapshot.top_holder_percent or 0), 4),
        "risk_score": int(snapshot.risk_score or 0),
        "honeypot": bool(snapshot.honeypot),
        "mint_authority_enabled": bool(snapshot.mint_authority_enabled),
        "freeze_authority_enabled": bool(snapshot.freeze_authority_enabled),
        "rugged": snapshot.rugged,
        "rugcheck_passed": snapshot.rugcheck_passed,
        "source": snapshot.source,
        "fetched_at": fetched_at.isoformat(),
        "age_minutes": round(max(0.0, age_minutes), 4),
        "provider_errors": provider_errors or {},
    }
    return {
        "status": status,
        "score": round(score, 4),
        "reason_codes": sorted(reasons),
        "positive_factors": sorted(positives),
        "snapshot": serialized,
    }


def _timing_assessment(
    source_event_at: datetime | None,
    *,
    evaluated_at: datetime,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if source_event_at is None:
        return {
            "status": "INSUFFICIENT_DATA",
            "latency_seconds": None,
            "reason_codes": ["SOURCE_EVENT_TIME_MISSING"],
            "positive_factors": [],
        }
    source = _aware(source_event_at)
    if source > evaluated_at:
        return {
            "status": "INSUFFICIENT_DATA",
            "latency_seconds": None,
            "reason_codes": ["SOURCE_EVENT_TIME_FROM_FUTURE"],
            "positive_factors": [],
        }
    latency = max(0.0, (evaluated_at - source).total_seconds())
    if latency <= int(policy["maximum_copy_latency_seconds"]):
        status = "COPYABLE"
        reasons: list[str] = []
        positives = ["COPY_LATENCY_WITHIN_LIMIT"]
    elif latency <= int(policy["maximum_stale_seconds"]):
        status = "LATE"
        reasons = ["COPY_LATENCY_LATE"]
        positives = []
    else:
        status = "STALE"
        reasons = ["COPY_LATENCY_STALE"]
        positives = []
    return {
        "status": status,
        "latency_seconds": round(latency, 4),
        "reason_codes": reasons,
        "positive_factors": positives,
    }


def _counterfactual_timing(
    *,
    base_latency: float | None,
    policy: dict[str, Any],
    approved_size: Decimal,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for extra in policy["counterfactual_latency_seconds"]:
        if base_latency is None:
            status = "INSUFFICIENT_DATA"
            latency = None
        else:
            latency = round(base_latency + int(extra), 4)
            if latency <= int(policy["maximum_copy_latency_seconds"]):
                status = "COPYABLE"
            elif latency <= int(policy["maximum_stale_seconds"]):
                status = "LATE"
            else:
                status = "STALE"
        rows.append(
            {
                "scenario": f"DETECTION_DELAY_PLUS_{extra}_SECONDS",
                "latency_seconds": latency,
                "timing_status": status,
                "creates_order": False,
            }
        )
    rows.append(
        {
            "scenario": "HALF_APPROVED_SIZE",
            "approved_size_sol": _money_text(approved_size / Decimal("2")),
            "creates_order": False,
        }
    )
    rows.append(
        {
            "scenario": "NO_TRADE_BASELINE",
            "approved_size_sol": "0.000000000",
            "creates_order": False,
        }
    )
    return rows


def _exit_plan(policy: dict[str, Any], *, decision: str) -> dict[str, Any]:
    return {
        "planned": decision in {"APPROVE", "REVIEW"},
        "metadata_only": True,
        "source_wallet_sell_trigger": True,
        "stop_loss_percent": float(policy["stop_loss_percent"]),
        "take_profit_percent": float(policy["take_profit_percent"]),
        "maximum_hold_minutes": int(policy["maximum_hold_minutes"]),
        "liquidity_deterioration_exit": True,
        "token_safety_deterioration_exit": True,
        "sell_route_loss_exit": True,
        "partial_exit_supported_in_future_execution": True,
        "creates_order": False,
    }


def _source_trades(
    db: Session,
    *,
    evaluated_at: datetime,
    policy: dict[str, Any],
    lookback_minutes: int,
    source_trade_ids: list[int] | None,
) -> list[Trade]:
    query = (
        select(Trade)
        .where(
            Trade.success.is_(True),
            Trade.side == "BUY",
            Trade.token_mint.isnot(None),
            Trade.block_time.isnot(None),
            Trade.block_time <= evaluated_at,
        )
        .order_by(Trade.block_time.desc(), Trade.id.desc())
    )
    if source_trade_ids:
        unique_ids = sorted(set(int(item) for item in source_trade_ids if int(item) > 0))
        query = query.where(Trade.id.in_(unique_ids))
    else:
        query = query.where(Trade.block_time >= evaluated_at - timedelta(minutes=lookback_minutes))
    query = query.limit(int(policy["max_source_trades"]))
    rows = list(db.scalars(query))
    rows.reverse()
    return rows


def _build_decisions(
    db: Session,
    *,
    policy: dict[str, Any],
    evaluated_at: datetime,
    lookback_minutes: int,
    max_results: int,
    source_trade_ids: list[int] | None,
) -> dict[str, Any]:
    trades = _source_trades(
        db,
        evaluated_at=evaluated_at,
        policy=policy,
        lookback_minutes=lookback_minutes,
        source_trade_ids=source_trade_ids,
    )
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        token = str(trade.token_mint or "").strip()
        if token:
            grouped[token].append(trade)

    token_order = sorted(
        grouped,
        key=lambda token: max(_aware(item.block_time) for item in grouped[token] if item.block_time),
        reverse=True,
    )[:max_results]

    all_addresses = sorted({str(trade.wallet_address) for token in token_order for trade in grouped[token]})
    wallet_rows = list(
        db.scalars(select(DiscoveredWallet).where(DiscoveredWallet.wallet_address.in_(all_addresses)))
    ) if all_addresses else []
    wallets = {row.wallet_address: row for row in wallet_rows}

    results: list[dict[str, Any]] = []
    globally_qualified: set[str] = set()

    for token_mint in token_order:
        token_trades = grouped[token_mint]
        wallet_trade_map: dict[str, list[Trade]] = defaultdict(list)
        for trade in token_trades:
            wallet_trade_map[str(trade.wallet_address)].append(trade)
        addresses = sorted(wallet_trade_map)
        cluster_map = _cluster_map(
            db,
            addresses,
            minimum_strength=float(policy["minimum_edge_strength"]),
        )
        earliest_by_wallet = {
            address: min(_aware(item.block_time) for item in rows if item.block_time)
            for address, rows in wallet_trade_map.items()
        }
        global_earliest = min(earliest_by_wallet.values()) if earliest_by_wallet else evaluated_at
        first_by_cluster: dict[str, datetime] = {}
        for address, event_at in earliest_by_wallet.items():
            cluster = cluster_map.get(address) or calculate_payload_hash({"wallet": address})
            first_by_cluster[cluster] = min(first_by_cluster.get(cluster, event_at), event_at)

        wallet_evidence: list[dict[str, Any]] = []
        for address in addresses:
            qualification = _qualify_wallet(
                wallets.get(address),
                evaluated_at=evaluated_at,
                policy=policy,
            )
            cluster_key = cluster_map.get(address) or calculate_payload_hash({"wallet": address})
            event_at = earliest_by_wallet[address]
            cluster_first = first_by_cluster[cluster_key]
            delay_from_cluster = max(0.0, (event_at - cluster_first).total_seconds())
            delay_from_global = max(0.0, (event_at - global_earliest).total_seconds())
            if qualification["qualification_status"] != "QUALIFIED":
                role = "UNQUALIFIED"
            elif event_at == cluster_first and delay_from_global <= int(policy["follower_delay_seconds"]):
                role = "EARLY_LEADER"
            elif event_at == cluster_first:
                role = "CONFIRMING_LEADER"
            elif delay_from_cluster <= int(policy["follower_delay_seconds"]):
                role = "FOLLOWER"
            else:
                role = "LATE_FOLLOWER"
            evidence_snapshot = {
                **qualification["snapshot"],
                "cluster_key": cluster_key,
                "role": role,
                "first_buy_at": event_at.isoformat(),
                "cluster_first_buy_at": cluster_first.isoformat(),
                "delay_from_cluster_seconds": round(delay_from_cluster, 4),
                "delay_from_global_seconds": round(delay_from_global, 4),
                "source_trade_ids": [item.id for item in wallet_trade_map[address]],
                "source_signatures": [item.signature for item in wallet_trade_map[address]],
            }
            evidence_hash = calculate_payload_hash(evidence_snapshot)
            wallet_evidence.append(
                {
                    "wallet_address": address,
                    "cluster_key": cluster_key,
                    "role": role,
                    "qualification_status": qualification["qualification_status"],
                    "final_score": qualification["final_score"],
                    "confidence_score": qualification["confidence_score"],
                    "freshness_status": qualification["freshness_status"],
                    "reason_codes": qualification["reason_codes"],
                    "positive_factors": qualification["positive_factors"],
                    "evidence_snapshot": evidence_snapshot,
                    "evidence_hash": evidence_hash,
                }
            )

        qualified = [row for row in wallet_evidence if row["qualification_status"] == "QUALIFIED"]
        globally_qualified.update(row["wallet_address"] for row in qualified)
        independent_clusters = sorted({row["cluster_key"] for row in qualified})
        followers = [row for row in qualified if row["role"] in {"FOLLOWER", "LATE_FOLLOWER"}]
        leaders = [row for row in qualified if row["role"] in {"EARLY_LEADER", "CONFIRMING_LEADER"}]
        leader_wallet = None
        if leaders:
            leader_wallet = max(
                leaders,
                key=lambda row: (row["final_score"], row["confidence_score"], row["wallet_address"]),
            )["wallet_address"]

        token = _token_assessment(
            db,
            token_mint,
            evaluated_at=evaluated_at,
            policy=policy,
        )
        source_event_at = max((_aware(item.block_time) for item in token_trades if item.block_time), default=None)
        timing = _timing_assessment(
            source_event_at,
            evaluated_at=evaluated_at,
            policy=policy,
        )
        data_conflicts = _raw_trade_conflicts(token_trades)

        if qualified:
            average_wallet_score = sum(row["final_score"] for row in qualified) / len(qualified)
            average_confidence = sum(row["confidence_score"] for row in qualified) / len(qualified)
        else:
            average_wallet_score = 0.0
            average_confidence = 0.0
        cluster_consensus = min(len(independent_clusters) / max(int(policy["minimum_independent_clusters"]), 1), 1.0) * 100.0
        copyability_score = {
            "COPYABLE": 100.0,
            "LATE": 35.0,
            "STALE": 0.0,
            "INSUFFICIENT_DATA": 0.0,
        }[timing["status"]]
        if qualified:
            volumes = [
                float(item.sol_amount or 0)
                for item in token_trades
                if item.wallet_address in {row["wallet_address"] for row in qualified}
                and float(item.sol_amount or 0) > 0
            ]
            total_volume = sum(volumes)
            concentration = max(volumes) / total_volume if total_volume > 0 else 1.0
            volume_diversity = max(0.0, min(100.0, (1.0 - concentration) * 150.0))
        else:
            volume_diversity = 0.0

        signal_score = round(
            average_wallet_score * 0.35
            + average_confidence * 0.15
            + cluster_consensus * 0.15
            + float(token["score"]) * 0.20
            + copyability_score * 0.10
            + volume_diversity * 0.05,
            4,
        )
        evidence_coverage = (
            min(len(qualified) / max(len(addresses), 1), 1.0) * 40.0
            + min(len(independent_clusters) / max(int(policy["minimum_independent_clusters"]), 1), 1.0) * 25.0
            + (20.0 if token["status"] == "SAFE" else 10.0 if token["status"] == "REVIEW" else 0.0)
            + (15.0 if timing["status"] == "COPYABLE" else 0.0)
        )
        confidence_score = round(
            max(0.0, min(100.0, average_confidence * 0.60 + evidence_coverage * 0.40) - 5.0),
            4,
        )
        uncertainty_score = round(max(0.0, 100.0 - confidence_score), 4)

        reasons: set[str] = set(data_conflicts)
        positives: set[str] = set()
        for row in wallet_evidence:
            if row["qualification_status"] != "QUALIFIED":
                reasons.update(row["reason_codes"])
        reasons.update(token["reason_codes"])
        reasons.update(timing["reason_codes"])
        positives.update(token["positive_factors"])
        positives.update(timing["positive_factors"])
        if len(qualified) >= int(policy["minimum_qualified_wallets"]):
            positives.add("MINIMUM_QUALIFIED_WALLETS_PASSED")
        else:
            reasons.add("QUALIFIED_WALLETS_BELOW_MINIMUM")
        if len(independent_clusters) >= int(policy["minimum_independent_clusters"]):
            positives.add("INDEPENDENT_CLUSTER_REQUIREMENT_PASSED")
        else:
            reasons.add("INDEPENDENT_CLUSTERS_BELOW_MINIMUM")
        if followers:
            reasons.add("FOLLOWER_WALLETS_PRESENT")
        if not leaders and qualified:
            reasons.add("INDEPENDENT_LEADER_NOT_IDENTIFIED")
        if signal_score >= float(policy["minimum_approve_score"]):
            positives.add("UNIFIED_SIGNAL_SCORE_APPROVE_RANGE")
        elif signal_score >= float(policy["minimum_review_score"]):
            positives.add("UNIFIED_SIGNAL_SCORE_REVIEW_RANGE")
        else:
            reasons.add("UNIFIED_SIGNAL_SCORE_BELOW_REVIEW")
        if confidence_score < 50:
            reasons.add("UNIFIED_CONFIDENCE_LOW")
        reasons.add("MARKET_REGIME_UNKNOWN")
        reasons.add("CONFIDENCE_CALIBRATION_PENDING")

        wallet_data_insufficient = (
            len(qualified) < int(policy["minimum_qualified_wallets"])
            and any(
                row["qualification_status"] in {"INSUFFICIENT_DATA", "EXPIRED"}
                for row in wallet_evidence
            )
        )
        insufficient = (
            bool(data_conflicts)
            or token["status"] == "INSUFFICIENT_DATA"
            or timing["status"] == "INSUFFICIENT_DATA"
            or wallet_data_insufficient
        )
        hard_reject = (
            token["status"] == "UNSAFE"
            or timing["status"] in {"LATE", "STALE"}
            or len(qualified) < int(policy["minimum_qualified_wallets"])
            or len(independent_clusters) < int(policy["minimum_independent_clusters"])
            or any("POTENTIAL_COPYTRADER_BAIT" in row["reason_codes"] for row in wallet_evidence)
        )
        if insufficient:
            decision = "INSUFFICIENT_DATA"
        elif hard_reject:
            decision = "REJECT"
        elif (
            token["status"] == "SAFE"
            and timing["status"] == "COPYABLE"
            and signal_score >= float(policy["minimum_approve_score"])
            and confidence_score >= 60
        ):
            decision = "APPROVE"
        elif signal_score >= float(policy["minimum_review_score"]):
            decision = "REVIEW"
        else:
            decision = "REJECT"

        qualified_addresses = {row["wallet_address"] for row in qualified}
        source_sizes = [
            _money(item.sol_amount)
            for item in token_trades
            if item.wallet_address in qualified_addresses and _money(item.sol_amount) > 0
        ]
        requested_size = _money(median(source_sizes)) if source_sizes else Decimal("0")
        maximum_size = _money(policy["maximum_size_sol"])
        uncertainty_factor = max(Decimal("0"), Decimal("1") - _decimal(uncertainty_score) / Decimal("100"))
        approved_size = Decimal("0")
        if decision == "APPROVE" and requested_size > 0:
            approved_size = _money(min(requested_size, maximum_size) * uncertainty_factor)
            if approved_size <= 0:
                decision = "REVIEW"
                reasons.add("UNCERTAINTY_BUDGET_REDUCED_SIZE_TO_ZERO")
        elif decision != "APPROVE":
            approved_size = Decimal("0")

        evidence_snapshot = {
            "source_action": "BUY",
            "source_trade_count": len(token_trades),
            "source_trade_ids": [item.id for item in token_trades],
            "source_signatures": [item.signature for item in token_trades],
            "source_wallets": addresses,
            "raw_wallet_count": len(addresses),
            "qualified_wallet_count": len(qualified),
            "independent_cluster_count": len(independent_clusters),
            "cluster_keys": independent_clusters,
            "leader_wallet": leader_wallet,
            "follower_wallets": [row["wallet_address"] for row in followers],
            "average_wallet_score": round(average_wallet_score, 4),
            "average_wallet_confidence": round(average_confidence, 4),
            "cluster_consensus_score": round(cluster_consensus, 4),
            "volume_diversity_score": round(volume_diversity, 4),
            "token_safety": token,
            "timing": timing,
            "provider_cross_check": {
                "mode": "LOCAL_EVIDENCE_ONLY",
                "raw_trade_conflicts": data_conflicts,
                "external_requests": 0,
            },
            "market_regime": {
                "status": "UNKNOWN",
                "reason": "MARKET_REGIME_DATA_NOT_YET_VERSIONED",
            },
            "sizing": {
                "requested_size_sol": _money_text(requested_size),
                "maximum_policy_size_sol": _money_text(maximum_size),
                "uncertainty_factor": format(uncertainty_factor.quantize(_SCORE_QUANTUM), "f"),
                "approved_size_sol": _money_text(approved_size),
                "metadata_only": True,
            },
        }
        decision_payload = {
            "token_mint": token_mint,
            "decision": decision,
            "signal_score": _score_text(signal_score),
            "confidence_score": _score_text(confidence_score),
            "uncertainty_score": _score_text(uncertainty_score),
            "requested_size_sol": _money_text(requested_size),
            "approved_size_sol": _money_text(approved_size),
            "token_safety_status": token["status"],
            "timing_status": timing["status"],
            "reason_codes": sorted(reasons),
            "positive_factors": sorted(positives),
            "evidence_snapshot": evidence_snapshot,
        }
        decision_hash = calculate_payload_hash(decision_payload)
        results.append(
            {
                "token_mint": token_mint,
                "decision": decision,
                "source_trade_ids": [item.id for item in token_trades],
                "source_signatures": [item.signature for item in token_trades],
                "source_event_at": source_event_at,
                "raw_wallet_count": len(addresses),
                "qualified_wallet_count": len(qualified),
                "independent_cluster_count": len(independent_clusters),
                "follower_wallet_count": len(followers),
                "leader_wallet": leader_wallet,
                "signal_score": signal_score,
                "confidence_score": confidence_score,
                "uncertainty_score": uncertainty_score,
                "requested_size_sol": requested_size,
                "approved_size_sol": approved_size,
                "token_safety_status": token["status"],
                "timing_status": timing["status"],
                "market_regime": "UNKNOWN",
                "confidence_calibration_status": "BASELINE_HEURISTIC_UNCALIBRATED",
                "reason_codes": sorted(reasons),
                "positive_factors": sorted(positives),
                "evidence_snapshot": evidence_snapshot,
                "exit_plan": _exit_plan(policy, decision=decision),
                "counterfactuals": _counterfactual_timing(
                    base_latency=timing["latency_seconds"],
                    policy=policy,
                    approved_size=approved_size,
                ),
                "decision_hash": decision_hash,
                "wallet_evidence": wallet_evidence,
            }
        )

    source_times = [_aware(item.block_time) for item in trades if item.block_time]
    summary = {
        "source_trade_count": len(trades),
        "source_token_count": len(grouped),
        "source_wallet_count": len({item.wallet_address for item in trades}),
        "qualified_wallet_count": len(globally_qualified),
        "result_count": len(results),
        "approve_count": sum(1 for row in results if row["decision"] == "APPROVE"),
        "review_count": sum(1 for row in results if row["decision"] == "REVIEW"),
        "reject_count": sum(1 for row in results if row["decision"] == "REJECT"),
        "insufficient_data_count": sum(1 for row in results if row["decision"] == "INSUFFICIENT_DATA"),
        "data_start_at": min(source_times) if source_times else None,
        "data_end_at": max(source_times) if source_times else None,
    }
    return {"trades": trades, "results": results, "summary": summary}


def _serialize_wallet_evidence(row: CanonicalParserUnifiedDecisionWalletEvidence) -> dict[str, Any]:
    return {
        "evidence_id": row.evidence_id,
        "sequence": row.sequence,
        "wallet_address": row.wallet_address,
        "cluster_key": row.cluster_key,
        "role": row.role,
        "qualification_status": row.qualification_status,
        "final_score": _score_text(row.final_score),
        "confidence_score": _score_text(row.confidence_score),
        "freshness_status": row.freshness_status,
        "reason_codes": row.reason_codes,
        "positive_factors": row.positive_factors,
        "evidence_snapshot": row.evidence_snapshot,
        "evidence_hash": row.evidence_hash,
    }


def _serialize_result(
    row: CanonicalParserUnifiedDecisionResult,
    *,
    wallet_evidence: list[CanonicalParserUnifiedDecisionWalletEvidence] | None = None,
) -> dict[str, Any]:
    return {
        "result_id": row.result_id,
        "sequence": row.sequence,
        "decision": row.decision,
        "token_mint": row.token_mint,
        "source_trade_ids": row.source_trade_ids,
        "source_signatures": row.source_signatures,
        "source_event_at": row.source_event_at,
        "raw_wallet_count": row.raw_wallet_count,
        "qualified_wallet_count": row.qualified_wallet_count,
        "independent_cluster_count": row.independent_cluster_count,
        "follower_wallet_count": row.follower_wallet_count,
        "leader_wallet": row.leader_wallet,
        "signal_score": _score_text(row.signal_score),
        "confidence_score": _score_text(row.confidence_score),
        "uncertainty_score": _score_text(row.uncertainty_score),
        "requested_size_sol": _money_text(row.requested_size_sol),
        "approved_size_sol": _money_text(row.approved_size_sol),
        "token_safety_status": row.token_safety_status,
        "timing_status": row.timing_status,
        "market_regime": row.market_regime,
        "confidence_calibration_status": row.confidence_calibration_status,
        "reason_codes": row.reason_codes,
        "positive_factors": row.positive_factors,
        "evidence_snapshot": row.evidence_snapshot,
        "exit_plan": row.exit_plan,
        "counterfactuals": row.counterfactuals,
        "decision_hash": row.decision_hash,
        "wallet_evidence": [
            _serialize_wallet_evidence(item) for item in (wallet_evidence or [])
        ],
    }


def _serialize_run(
    db: Session,
    run: CanonicalParserUnifiedDecisionRun,
    *,
    include_results: bool,
) -> dict[str, Any]:
    payload = {
        "run_id": run.run_id,
        "run_key": run.run_key,
        "scope": run.scope,
        "status": run.status,
        "source_trade_count": run.source_trade_count,
        "source_token_count": run.source_token_count,
        "source_wallet_count": run.source_wallet_count,
        "qualified_wallet_count": run.qualified_wallet_count,
        "result_count": run.result_count,
        "approve_count": run.approve_count,
        "review_count": run.review_count,
        "reject_count": run.reject_count,
        "insufficient_data_count": run.insufficient_data_count,
        "policy_version": run.policy_version,
        "policy_hash": run.policy_hash,
        "policy_snapshot": run.policy_snapshot,
        "parameters": run.parameters,
        "summary": run.summary,
        "safety": run.safety,
        "evidence_hash": run.evidence_hash,
        "actor_label": run.actor_label,
        "note": run.note,
        "data_start_at": run.data_start_at,
        "data_end_at": run.data_end_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "valid_until": run.valid_until,
        "technical_metadata": run.technical_metadata,
        "paper_execution_connected": False,
        "permit_consumption_connected": False,
        "live_execution_authorized": False,
    }
    if include_results:
        results = list(
            db.scalars(
                select(CanonicalParserUnifiedDecisionResult)
                .where(CanonicalParserUnifiedDecisionResult.run_db_id == run.id)
                .order_by(CanonicalParserUnifiedDecisionResult.sequence.asc())
            )
        )
        evidence_rows = list(
            db.scalars(
                select(CanonicalParserUnifiedDecisionWalletEvidence)
                .where(
                    CanonicalParserUnifiedDecisionWalletEvidence.result_db_id.in_(
                        [item.id for item in results]
                    )
                )
                .order_by(
                    CanonicalParserUnifiedDecisionWalletEvidence.result_db_id.asc(),
                    CanonicalParserUnifiedDecisionWalletEvidence.sequence.asc(),
                )
            )
        ) if results else []
        by_result: dict[int, list[CanonicalParserUnifiedDecisionWalletEvidence]] = defaultdict(list)
        for item in evidence_rows:
            by_result[item.result_db_id].append(item)
        payload["results"] = [
            _serialize_result(item, wallet_evidence=by_result[item.id]) for item in results
        ]
    return payload


def preview_unified_decision(
    db: Session,
    *,
    lookback_minutes: int | None = None,
    max_results: int | None = None,
    source_trade_ids: list[int] | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    requested_lookback = int(lookback_minutes or policy["lookback_minutes"])
    requested_results = int(max_results or policy["max_results"])
    requested_lookback = min(requested_lookback, int(policy["lookback_minutes"]))
    requested_results = min(requested_results, int(policy["max_results"]))
    built = _build_decisions(
        db,
        policy=policy,
        evaluated_at=now,
        lookback_minutes=requested_lookback,
        max_results=requested_results,
        source_trade_ids=source_trade_ids,
    )
    return {
        "enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_ENABLED", False)
        ),
        "evaluated_at": now,
        "policy_version": UNIFIED_DECISION_POLICY_VERSION,
        "policy_hash": calculate_payload_hash(policy),
        "policy_snapshot": policy,
        "parameters": {
            "lookback_minutes": requested_lookback,
            "max_results": requested_results,
            "source_trade_ids": sorted(set(source_trade_ids or [])),
        },
        "summary": built["summary"],
        "results": [
            {
                key: value
                for key, value in row.items()
                if key != "wallet_evidence"
            }
            | {"wallet_evidence": row["wallet_evidence"]}
            for row in built["results"]
        ],
        "confirmation_required": UNIFIED_DECISION_CONFIRMATION,
        "safety": _safety_contract(),
        "writes_performed": False,
    }


def run_unified_decision_shadow_validation(
    db: Session,
    *,
    confirmation: str,
    lookback_minutes: int | None = None,
    max_results: int | None = None,
    source_trade_ids: list[int] | None = None,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_ENABLED", False)
    ):
        raise CanonicalParserUnifiedDecisionError(
            "M31 Unified Decision Intelligence è disabilitato.",
            code="UNIFIED_DECISION_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != UNIFIED_DECISION_CONFIRMATION:
        raise CanonicalParserUnifiedDecisionError(
            f"Conferma richiesta: {UNIFIED_DECISION_CONFIRMATION}",
            code="UNIFIED_DECISION_CONFIRMATION_REQUIRED",
            status_code=422,
        )

    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    requested_lookback = int(lookback_minutes or policy["lookback_minutes"])
    requested_results = int(max_results or policy["max_results"])
    if requested_lookback > int(policy["lookback_minutes"]):
        raise CanonicalParserUnifiedDecisionError(
            "Lookback richiesto superiore al limite M31.",
            code="UNIFIED_DECISION_LOOKBACK_ABOVE_MAXIMUM",
        )
    if requested_results > int(policy["max_results"]):
        raise CanonicalParserUnifiedDecisionError(
            "Numero risultati richiesto superiore al limite M31.",
            code="UNIFIED_DECISION_RESULTS_ABOVE_MAXIMUM",
        )
    parameters = {
        "lookback_minutes": requested_lookback,
        "max_results": requested_results,
        "source_trade_ids": sorted(set(source_trade_ids or [])),
    }
    built = _build_decisions(
        db,
        policy=policy,
        evaluated_at=now,
        lookback_minutes=requested_lookback,
        max_results=requested_results,
        source_trade_ids=source_trade_ids,
    )
    source_fingerprint = [
        {"id": item.id, "signature": item.signature, "block_time": _aware(item.block_time).isoformat()}
        for item in built["trades"]
    ]
    result_hashes = [row["decision_hash"] for row in built["results"]]
    run_key = calculate_payload_hash(
        {
            "policy_hash": policy_hash,
            "parameters": parameters,
            "source_fingerprint": source_fingerprint,
            "result_hashes": result_hashes,
        }
    )
    existing = db.scalar(
        select(CanonicalParserUnifiedDecisionRun).where(
            CanonicalParserUnifiedDecisionRun.run_key == run_key
        )
    )
    if existing is not None:
        return _serialize_run(db, existing, include_results=True) | {"idempotent_replay": True}

    summary = built["summary"]
    evidence_hash = calculate_payload_hash(
        {
            "policy_hash": policy_hash,
            "parameters": parameters,
            "source_fingerprint": source_fingerprint,
            "result_hashes": result_hashes,
        }
    )
    completed_at = now
    run = CanonicalParserUnifiedDecisionRun(
        run_id=str(uuid4()),
        run_key=run_key,
        scope=UNIFIED_DECISION_SCOPE,
        status="COMPLETED",
        source_trade_count=summary["source_trade_count"],
        source_token_count=summary["source_token_count"],
        source_wallet_count=summary["source_wallet_count"],
        qualified_wallet_count=summary["qualified_wallet_count"],
        result_count=summary["result_count"],
        approve_count=summary["approve_count"],
        review_count=summary["review_count"],
        reject_count=summary["reject_count"],
        insufficient_data_count=summary["insufficient_data_count"],
        policy_version=UNIFIED_DECISION_POLICY_VERSION,
        policy_hash=policy_hash,
        policy_snapshot=policy,
        parameters=parameters,
        summary={key: value for key, value in summary.items() if not key.endswith("_at")},
        safety=_safety_contract(),
        evidence_hash=evidence_hash,
        actor_label=_actor(actor_label),
        note=_note(note),
        data_start_at=summary["data_start_at"],
        data_end_at=summary["data_end_at"],
        started_at=now,
        completed_at=completed_at,
        valid_until=completed_at + timedelta(minutes=int(policy["validity_minutes"])),
        technical_metadata={
            "source": "LOCAL_DATABASE_ONLY",
            "external_requests": 0,
            "confidence_calibration_status": "BASELINE_HEURISTIC_UNCALIBRATED",
            "point_in_time_guard": True,
            "paper_execution_connected": False,
            "permit_consumption_connected": False,
        },
    )
    db.add(run)
    try:
        db.flush()
        for sequence, result in enumerate(built["results"], start=1):
            result_row = CanonicalParserUnifiedDecisionResult(
                result_id=str(uuid4()),
                run_db_id=run.id,
                sequence=sequence,
                decision=result["decision"],
                token_mint=result["token_mint"],
                source_trade_ids=result["source_trade_ids"],
                source_signatures=result["source_signatures"],
                source_event_at=result["source_event_at"],
                raw_wallet_count=result["raw_wallet_count"],
                qualified_wallet_count=result["qualified_wallet_count"],
                independent_cluster_count=result["independent_cluster_count"],
                follower_wallet_count=result["follower_wallet_count"],
                leader_wallet=result["leader_wallet"],
                signal_score=_score(result["signal_score"]),
                confidence_score=_score(result["confidence_score"]),
                uncertainty_score=_score(result["uncertainty_score"]),
                requested_size_sol=_money(result["requested_size_sol"]),
                approved_size_sol=_money(result["approved_size_sol"]),
                token_safety_status=result["token_safety_status"],
                timing_status=result["timing_status"],
                market_regime=result["market_regime"],
                confidence_calibration_status=result["confidence_calibration_status"],
                reason_codes=result["reason_codes"],
                positive_factors=result["positive_factors"],
                evidence_snapshot=result["evidence_snapshot"],
                exit_plan=result["exit_plan"],
                counterfactuals=result["counterfactuals"],
                decision_hash=result["decision_hash"],
            )
            db.add(result_row)
            db.flush()
            for evidence_sequence, evidence in enumerate(result["wallet_evidence"], start=1):
                db.add(
                    CanonicalParserUnifiedDecisionWalletEvidence(
                        evidence_id=str(uuid4()),
                        result_db_id=result_row.id,
                        sequence=evidence_sequence,
                        wallet_address=evidence["wallet_address"],
                        cluster_key=evidence["cluster_key"],
                        role=evidence["role"],
                        qualification_status=evidence["qualification_status"],
                        final_score=_score(evidence["final_score"]),
                        confidence_score=_score(evidence["confidence_score"]),
                        freshness_status=evidence["freshness_status"],
                        reason_codes=evidence["reason_codes"],
                        positive_factors=evidence["positive_factors"],
                        evidence_snapshot=evidence["evidence_snapshot"],
                        evidence_hash=evidence["evidence_hash"],
                    )
                )
        db.commit()
    except IntegrityError as exception:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserUnifiedDecisionRun).where(
                CanonicalParserUnifiedDecisionRun.run_key == run_key
            )
        )
        if existing is not None:
            return _serialize_run(db, existing, include_results=True) | {"idempotent_replay": True}
        raise CanonicalParserUnifiedDecisionError(
            "Conflitto durante il salvataggio M31.",
            code="UNIFIED_DECISION_PERSISTENCE_CONFLICT",
            status_code=409,
        ) from exception
    db.refresh(run)
    return _serialize_run(db, run, include_results=True) | {"idempotent_replay": False}


def get_unified_decision_run(db: Session, run_id: str) -> dict[str, Any]:
    run = db.scalar(
        select(CanonicalParserUnifiedDecisionRun).where(
            CanonicalParserUnifiedDecisionRun.run_id == str(run_id)
        )
    )
    if run is None:
        raise CanonicalParserUnifiedDecisionError(
            "Run M31 non trovato.",
            code="UNIFIED_DECISION_RUN_NOT_FOUND",
            status_code=404,
        )
    return _serialize_run(db, run, include_results=True)


def resolve_unified_decision(
    db: Session,
    *,
    token_mint: str | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    run = db.scalar(
        select(CanonicalParserUnifiedDecisionRun)
        .where(
            CanonicalParserUnifiedDecisionRun.status == "COMPLETED",
            CanonicalParserUnifiedDecisionRun.valid_until >= now,
        )
        .order_by(desc(CanonicalParserUnifiedDecisionRun.completed_at), desc(CanonicalParserUnifiedDecisionRun.id))
        .limit(1)
    )
    if run is None:
        return {
            "resolved": False,
            "reason_codes": ["UNIFIED_DECISION_CURRENT_RUN_NOT_FOUND"],
            "paper_execution_connected": False,
            "live_execution_authorized": False,
        }
    payload = _serialize_run(db, run, include_results=True)
    if token_mint:
        matching = [row for row in payload["results"] if row["token_mint"] == token_mint]
        if not matching:
            return {
                "resolved": False,
                "run_id": run.run_id,
                "reason_codes": ["UNIFIED_DECISION_TOKEN_NOT_FOUND"],
                "paper_execution_connected": False,
                "live_execution_authorized": False,
            }
        payload["results"] = matching
        payload["result_count"] = len(matching)
    return payload | {"resolved": True}


def get_unified_decision_status(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    latest = db.scalar(
        select(CanonicalParserUnifiedDecisionRun)
        .order_by(desc(CanonicalParserUnifiedDecisionRun.completed_at), desc(CanonicalParserUnifiedDecisionRun.id))
        .limit(1)
    )
    counts = Counter(
        db.scalars(select(CanonicalParserUnifiedDecisionResult.decision)).all()
    )
    return {
        "enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_UNIFIED_DECISION_ENABLED", False)
        ),
        "policy_version": UNIFIED_DECISION_POLICY_VERSION,
        "policy_hash": calculate_payload_hash(_policy_snapshot(settings_object)),
        "scope": UNIFIED_DECISION_SCOPE,
        "run_count": int(db.scalar(select(func.count(CanonicalParserUnifiedDecisionRun.id))) or 0),
        "decision_counts": {
            "APPROVE": counts["APPROVE"],
            "REVIEW": counts["REVIEW"],
            "REJECT": counts["REJECT"],
            "INSUFFICIENT_DATA": counts["INSUFFICIENT_DATA"],
        },
        "latest_run": None if latest is None else _serialize_run(db, latest, include_results=False),
        "latest_run_current": bool(latest and _aware(latest.valid_until) >= now),
        "confirmation_required": UNIFIED_DECISION_CONFIRMATION,
        "safety": _safety_contract(),
    }
