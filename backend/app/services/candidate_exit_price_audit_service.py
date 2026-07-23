from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.models.candidate_exit_price_audit import (
    CandidateExitPriceAuditRun,
)
from backend.app.models.candidate_position_lifecycle_audit import (
    CandidatePositionLifecycleAuditRun,
)
from backend.app.models.candidate_token_compatibility import (
    CandidateTokenCompatibility,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services.wallet_activity_service import ensure_aware, safe_float


READINESS_READY = "READY"
READINESS_PARTIAL = "PARTIAL"
READINESS_BLOCKED = "BLOCKED"
READINESS_NOT_ANALYZED = "NON_ANALIZZATO"

SCENARIO_HOURS: tuple[int | None, ...] = (
    None,
    24,
    72,
    168,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _round(value: float, digits: int = 8) -> float:
    return round(float(value or 0.0), digits)


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return ensure_aware(value)
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return ensure_aware(
            datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        )
    except ValueError:
        return None


def _source_price(trade: Trade) -> float | None:
    sol_amount = abs(safe_float(trade.sol_amount))
    token_amount = abs(safe_float(trade.token_amount))
    if sol_amount <= 0 or token_amount <= 0:
        return None
    return sol_amount / token_amount


def _latest_lifecycle_run(
    db: Session,
    wallet_address: str,
) -> CandidatePositionLifecycleAuditRun | None:
    return (
        db.query(CandidatePositionLifecycleAuditRun)
        .filter(
            CandidatePositionLifecycleAuditRun.wallet_address
            == wallet_address
        )
        .order_by(
            CandidatePositionLifecycleAuditRun.completed_at.desc(),
            CandidatePositionLifecycleAuditRun.id.desc(),
        )
        .first()
    )


def _latest_cache_rows(
    db: Session,
    tokens: set[str],
    *,
    fixed_buy_size_sol: float,
    slippage_bps: int,
) -> dict[str, CandidateTokenCompatibility]:
    if not tokens:
        return {}

    amount_raw = max(1, int(float(fixed_buy_size_sol) * 1_000_000_000))
    effective_slippage = max(0, min(int(slippage_bps), 1000))
    rows = (
        db.query(CandidateTokenCompatibility)
        .filter(CandidateTokenCompatibility.token_mint.in_(sorted(tokens)))
        .filter(
            CandidateTokenCompatibility.fixed_buy_size_lamports
            == amount_raw
        )
        .filter(
            CandidateTokenCompatibility.slippage_bps
            == effective_slippage
        )
        .order_by(
            CandidateTokenCompatibility.checked_at.desc(),
            CandidateTokenCompatibility.id.desc(),
        )
        .all()
    )

    result: dict[str, CandidateTokenCompatibility] = {}
    for row in rows:
        result.setdefault(str(row.token_mint), row)
    return result


def _trade_price_history(
    db: Session,
    wallet_address: str,
    tokens: set[str],
    *,
    through: datetime,
) -> dict[str, list[dict[str, Any]]]:
    if not tokens:
        return {}

    rows = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.success.is_(True))
        .filter(Trade.token_mint.in_(sorted(tokens)))
        .filter(Trade.block_time.isnot(None))
        .filter(Trade.block_time <= through)
        .order_by(Trade.block_time.asc(), Trade.id.asc())
        .all()
    )

    history: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        token = str(row.token_mint or "").strip()
        timestamp = ensure_aware(row.block_time)
        price = _source_price(row)
        if not token or timestamp is None or price is None:
            continue
        history.setdefault(token, []).append(
            {
                "timestamp": timestamp,
                "price_sol": price,
                "side": str(row.side or "UNKNOWN").strip().upper(),
                "signature": str(row.signature),
                "source": str(row.source or "UNKNOWN"),
            }
        )
    return history


def _latest_local_price(
    history: list[dict[str, Any]],
    *,
    target_at: datetime,
) -> dict[str, Any] | None:
    selected: dict[str, Any] | None = None
    for row in history:
        timestamp = row["timestamp"]
        if timestamp > target_at:
            break
        selected = row
    return selected


def _cache_evidence(
    row: CandidateTokenCompatibility | None,
    *,
    target_at: datetime,
    audit_at: datetime,
) -> dict[str, Any]:
    if row is None:
        return {
            "present": False,
            "status": "CACHE_MISSING",
            "compatible": False,
            "buy_quote": False,
            "sell_quote": False,
            "checked_at": None,
            "expires_at": None,
            "valid_at_target": False,
            "valid_at_audit": False,
            "round_trip_value_sol": None,
            "round_trip_return_percent": None,
        }

    checked_at = ensure_aware(row.checked_at)
    expires_at = ensure_aware(row.expires_at)
    valid_at_target = bool(
        checked_at
        and expires_at
        and checked_at <= target_at < expires_at
    )
    valid_at_audit = bool(
        checked_at
        and expires_at
        and checked_at <= audit_at < expires_at
    )
    round_trip_value_sol = (
        float(row.sell_out_amount_raw) / 1_000_000_000
        if row.sell_out_amount_raw is not None
        else None
    )
    input_sol = float(row.fixed_buy_size_lamports) / 1_000_000_000
    round_trip_return = (
        (round_trip_value_sol - input_sol) / input_sol * 100.0
        if round_trip_value_sol is not None and input_sol > 0
        else None
    )

    if not bool(row.compatible) or not bool(row.sell_quote):
        cache_status = str(row.status or "CACHE_UNQUOTABLE")
    elif valid_at_audit:
        cache_status = "CACHE_CURRENT_COMPATIBLE"
    else:
        cache_status = "CACHE_EXPIRED_COMPATIBLE"

    return {
        "present": True,
        "status": cache_status,
        "compatible": bool(row.compatible),
        "buy_quote": bool(row.buy_quote),
        "sell_quote": bool(row.sell_quote),
        "checked_at": checked_at.isoformat() if checked_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "valid_at_target": valid_at_target,
        "valid_at_audit": valid_at_audit,
        "round_trip_value_sol": (
            _round(round_trip_value_sol) if round_trip_value_sol is not None else None
        ),
        "round_trip_return_percent": (
            _round(round_trip_return, 4) if round_trip_return is not None else None
        ),
    }


def _evidence_status(
    *,
    local_available: bool,
    local_fresh: bool,
    cache: dict[str, Any],
) -> str:
    if not local_available:
        return "NO_LOCAL_PRICE"
    if not local_fresh:
        return "STALE_LOCAL_PRICE"
    if (
        cache["compatible"]
        and cache["sell_quote"]
        and cache["valid_at_target"]
    ):
        return "TEMPORALLY_EXECUTABLE"
    if (
        cache["compatible"]
        and cache["sell_quote"]
        and cache["valid_at_audit"]
    ):
        return "CURRENT_ROUTE_ONLY"
    if not cache["present"]:
        return "LOCAL_PRICE_ONLY_CACHE_MISSING"
    if not cache["compatible"] or not cache["sell_quote"]:
        return "LOCAL_PRICE_ONLY_CACHE_UNQUOTABLE"
    return "LOCAL_PRICE_ONLY_CACHE_EXPIRED"


def _readiness(
    *,
    positions: int,
    local_percent: float,
    current_route_percent: float,
    cache_present_percent: float,
) -> tuple[str, float]:
    if positions <= 0:
        return READINESS_READY, 100.0

    score = (
        local_percent * 0.45
        + current_route_percent * 0.35
        + cache_present_percent * 0.20
    )
    score = max(0.0, min(100.0, score))
    if score >= 80.0:
        return READINESS_READY, _round(score, 4)
    if score >= 50.0:
        return READINESS_PARTIAL, _round(score, 4)
    return READINESS_BLOCKED, _round(score, 4)


def _diagnoses(summary: dict[str, Any]) -> list[str]:
    diagnoses: list[str] = []
    positions = int(summary.get("positions_analyzed", 0))
    if positions <= 0:
        return ["NO_OPEN_POSITIONS_REQUIRING_EXIT"]

    if safe_float(summary.get("local_observable_percent")) < 80.0:
        diagnoses.append("LOCAL_PRICE_COVERAGE_LOW")
    if safe_float(summary.get("current_route_supported_percent")) < 80.0:
        diagnoses.append("CURRENT_CACHED_ROUTE_COVERAGE_LOW")
    if safe_float(summary.get("temporal_execution_percent")) < 80.0:
        diagnoses.append("TEMPORAL_EXECUTION_EVIDENCE_LOW")
    if int(summary.get("cache_missing", 0)) == positions:
        diagnoses.append("ALL_OPEN_POSITIONS_MISSING_CACHE")
    elif int(summary.get("cache_missing", 0)) > 0:
        diagnoses.append("SOME_OPEN_POSITIONS_MISSING_CACHE")
    if int(summary.get("stale_local_prices", 0)) > 0:
        diagnoses.append("STALE_LOCAL_PRICES_PRESENT")
    if int(summary.get("future_only_prices_rejected", 0)) > 0:
        diagnoses.append("FUTURE_PRICES_REJECTED_TO_PREVENT_LOOKAHEAD")
    return diagnoses


def run_candidate_exit_price_audit(
    db: Session,
    *,
    wallet_address: str,
    max_local_price_age_hours: int = 24,
    now: datetime | None = None,
) -> CandidateExitPriceAuditRun:
    started_at = ensure_aware(now) or utc_now()
    wallet = (
        db.query(DiscoveredWallet)
        .filter(DiscoveredWallet.wallet_address == wallet_address)
        .first()
    )
    if wallet is None:
        raise ValueError("Wallet scoperto non trovato")

    lifecycle = _latest_lifecycle_run(db, wallet_address)
    if lifecycle is None:
        raise ValueError(
            "Esegui prima il Position Lifecycle & Stale Position Audit"
        )

    effective_max_age = max(1, min(int(max_local_price_age_hours), 720))
    position_details = [dict(row) for row in list(lifecycle.position_details or [])]
    tokens = {
        str(row.get("token_mint") or "").strip()
        for row in position_details
        if str(row.get("token_mint") or "").strip()
    }

    fixed_buy_size_sol = safe_float(
        (lifecycle.parameters or {}).get("fixed_buy_size_sol")
    ) or 0.05
    slippage_bps = int(
        (lifecycle.parameters or {}).get("slippage_bps") or 100
    )
    fee_bps = int((lifecycle.parameters or {}).get("fee_bps") or 10)
    friction_bps = safe_float(
        (lifecycle.parameters or {}).get("effective_market_friction_bps")
    )

    histories = _trade_price_history(
        db,
        wallet_address,
        tokens,
        through=started_at,
    )
    cache_rows = _latest_cache_rows(
        db,
        tokens,
        fixed_buy_size_sol=fixed_buy_size_sol,
        slippage_bps=slippage_bps,
    )

    position_results: list[dict[str, Any]] = []
    scenario_buckets: dict[int | None, list[dict[str, Any]]] = {
        scenario: [] for scenario in SCENARIO_HOURS
    }

    for detail in position_details:
        token = str(detail.get("token_mint") or "").strip()
        entry_at = _parse_datetime(detail.get("entry_at")) or started_at
        remaining_quantity = max(0.0, safe_float(detail.get("remaining_quantity")))
        remaining_cost = max(
            0.0, safe_float(detail.get("remaining_cost_basis_sol"))
        )
        token_history = histories.get(token, [])
        cache_row = cache_rows.get(token)
        scenario_evidence: list[dict[str, Any]] = []

        for holding_hours in SCENARIO_HOURS:
            expiry_at = (
                entry_at + timedelta(hours=holding_hours)
                if holding_hours is not None
                else started_at
            )
            due = holding_hours is None or expiry_at <= started_at
            target_at = min(expiry_at, started_at)
            local = _latest_local_price(token_history, target_at=target_at)
            future_exists = any(row["timestamp"] > target_at for row in token_history)

            local_available = local is not None
            local_age_hours = (
                max(
                    0.0,
                    (target_at - local["timestamp"]).total_seconds() / 3600.0,
                )
                if local is not None
                else None
            )
            local_fresh = bool(
                local_available
                and local_age_hours is not None
                and local_age_hours <= effective_max_age
            )
            cache = _cache_evidence(
                cache_row,
                target_at=target_at,
                audit_at=started_at,
            )
            temporal_executable = bool(
                due
                and local_fresh
                and cache["compatible"]
                and cache["sell_quote"]
                and cache["valid_at_target"]
            )
            current_route_supported = bool(
                due
                and local_fresh
                and cache["compatible"]
                and cache["sell_quote"]
                and cache["valid_at_audit"]
            )

            observable_value = None
            observable_pnl = None
            if due and local_fresh and local is not None:
                friction_ratio = max(0.0, friction_bps) / 10_000.0
                fee_ratio = max(0, fee_bps) / 10_000.0
                gross = (
                    remaining_quantity
                    * float(local["price_sol"])
                    * max(0.0, 1.0 - friction_ratio)
                )
                observable_value = gross * max(0.0, 1.0 - fee_ratio)
                observable_pnl = observable_value - remaining_cost

            evidence = {
                "holding_period_hours": holding_hours,
                "scenario_key": (
                    "analysis_end"
                    if holding_hours is None
                    else f"max_holding_{holding_hours}h"
                ),
                "due": due,
                "target_at": target_at.isoformat(),
                "expiry_at": expiry_at.isoformat(),
                "local_price_available": local_available,
                "local_price_fresh": local_fresh,
                "local_price_sol": (
                    _round(local["price_sol"]) if local is not None else None
                ),
                "local_price_at": (
                    local["timestamp"].isoformat() if local is not None else None
                ),
                "local_price_age_hours": (
                    _round(local_age_hours, 4)
                    if local_age_hours is not None
                    else None
                ),
                "local_price_side": local.get("side") if local else None,
                "local_price_signature": local.get("signature") if local else None,
                "local_price_source": local.get("source") if local else None,
                "future_price_exists_but_rejected": bool(
                    not local_available and future_exists
                ),
                "cache": cache,
                "temporal_executable": temporal_executable,
                "current_route_supported": current_route_supported,
                "observable_value_sol": (
                    _round(observable_value)
                    if observable_value is not None
                    else None
                ),
                "observable_pnl_sol": (
                    _round(observable_pnl)
                    if observable_pnl is not None
                    else None
                ),
                "evidence_status": _evidence_status(
                    local_available=local_available,
                    local_fresh=local_fresh,
                    cache=cache,
                ),
            }
            scenario_evidence.append(evidence)
            scenario_buckets[holding_hours].append(evidence)

        position_results.append(
            {
                "token_mint": token,
                "bootstrap": bool(detail.get("bootstrap")),
                "entry_at": entry_at.isoformat(),
                "remaining_quantity": _round(remaining_quantity),
                "remaining_cost_basis_sol": _round(remaining_cost),
                "reason_still_open": detail.get("reason_still_open"),
                "last_source_activity_at": detail.get("last_source_activity_at"),
                "scenario_evidence": scenario_evidence,
            }
        )

    scenario_results: list[dict[str, Any]] = []
    for holding_hours in SCENARIO_HOURS:
        rows = scenario_buckets[holding_hours]
        due_rows = [row for row in rows if row["due"]]
        denominator = len(due_rows)
        local_valid = sum(bool(row["local_price_fresh"]) for row in due_rows)
        temporal = sum(bool(row["temporal_executable"]) for row in due_rows)
        current_route = sum(bool(row["current_route_supported"]) for row in due_rows)
        cache_present = sum(bool(row["cache"]["present"]) for row in due_rows)
        stale = sum(
            bool(row["local_price_available"] and not row["local_price_fresh"])
            for row in due_rows
        )
        missing = sum(not bool(row["local_price_available"]) for row in due_rows)
        future_rejected = sum(
            bool(row["future_price_exists_but_rejected"]) for row in due_rows
        )
        observed_values = [
            safe_float(row["observable_value_sol"])
            for row in due_rows
            if row["observable_value_sol"] is not None
        ]
        observed_pnls = [
            safe_float(row["observable_pnl_sol"])
            for row in due_rows
            if row["observable_pnl_sol"] is not None
        ]

        scenario_results.append(
            {
                "scenario_key": (
                    "analysis_end"
                    if holding_hours is None
                    else f"max_holding_{holding_hours}h"
                ),
                "holding_period_hours": holding_hours,
                "positions_total": len(rows),
                "positions_due": denominator,
                "positions_not_due": len(rows) - denominator,
                "local_price_valid": local_valid,
                "local_observable_percent": _round(
                    local_valid / denominator * 100.0 if denominator else 100.0,
                    4,
                ),
                "temporal_executable": temporal,
                "temporal_execution_percent": _round(
                    temporal / denominator * 100.0 if denominator else 100.0,
                    4,
                ),
                "current_route_supported": current_route,
                "current_route_supported_percent": _round(
                    current_route / denominator * 100.0 if denominator else 100.0,
                    4,
                ),
                "cache_present": cache_present,
                "cache_present_percent": _round(
                    cache_present / denominator * 100.0 if denominator else 100.0,
                    4,
                ),
                "stale_local_prices": stale,
                "missing_local_prices": missing,
                "future_only_prices_rejected": future_rejected,
                "observable_value_sol": _round(sum(observed_values)),
                "observable_pnl_sol": _round(sum(observed_pnls)),
                "valuation_coverage_percent": _round(
                    len(observed_values) / denominator * 100.0
                    if denominator
                    else 100.0,
                    4,
                ),
            }
        )

    baseline = scenario_results[0]
    cache_missing = sum(
        not bool(row["scenario_evidence"][0]["cache"]["present"])
        for row in position_results
    )
    cache_compatible = sum(
        bool(row["scenario_evidence"][0]["cache"]["compatible"])
        for row in position_results
    )
    summary = {
        "positions_analyzed": len(position_results),
        "readiness_basis": (
            "45% local freshness + 35% current cached route + 20% cache presence"
        ),
        "local_observable_percent": baseline["local_observable_percent"],
        "current_route_supported_percent": baseline[
            "current_route_supported_percent"
        ],
        "temporal_execution_percent": baseline["temporal_execution_percent"],
        "cache_present_percent": baseline["cache_present_percent"],
        "cache_missing": cache_missing,
        "cache_compatible": cache_compatible,
        "stale_local_prices": baseline["stale_local_prices"],
        "missing_local_prices": baseline["missing_local_prices"],
        "future_only_prices_rejected": baseline[
            "future_only_prices_rejected"
        ],
        "observable_value_sol": baseline["observable_value_sol"],
        "observable_pnl_sol": baseline["observable_pnl_sol"],
        "valuation_coverage_percent": baseline["valuation_coverage_percent"],
    }
    readiness_status, readiness_score = _readiness(
        positions=len(position_results),
        local_percent=safe_float(summary["local_observable_percent"]),
        current_route_percent=safe_float(
            summary["current_route_supported_percent"]
        ),
        cache_present_percent=safe_float(summary["cache_present_percent"]),
    )
    summary["readiness_status"] = readiness_status
    summary["readiness_score"] = readiness_score
    diagnoses = _diagnoses(summary)

    parameters = {
        "source_lifecycle_run_id": lifecycle.run_id,
        "max_local_price_age_hours": effective_max_age,
        "fixed_buy_size_sol": fixed_buy_size_sol,
        "slippage_bps": slippage_bps,
        "fee_bps": fee_bps,
        "effective_market_friction_bps": friction_bps,
        "scenario_hours": list(SCENARIO_HOURS),
        "no_lookahead": True,
        "local_price_policy": "LATEST_SOURCE_TRADE_AT_OR_BEFORE_TARGET",
        "route_policy": "EXACT_CACHED_QUOTE_PROFILE_ONLY",
    }
    safety = {
        "diagnostic_only": True,
        "cached_data_only": True,
        "promotion_gate_changed": False,
        "wallet_eligibility_changed": False,
        "discovery_metadata_updated": True,
        "helius_requests": 0,
        "jupiter_requests": 0,
        "transactions_signed": False,
        "transactions_submitted": False,
        "live_enabled": False,
        "stream_changed": False,
        "worker_started": False,
        "wallets_applied": False,
        "generation_reset": False,
        "generation_created": False,
    }
    completed_at = utc_now()

    run = CandidateExitPriceAuditRun(
        run_id=str(uuid4()),
        wallet_address=wallet_address,
        status="COMPLETED",
        readiness_status=readiness_status,
        readiness_score=int(round(readiness_score)),
        parameters=parameters,
        safety=safety,
        summary=summary,
        scenario_results=scenario_results,
        position_results=position_results,
        diagnoses=diagnoses,
        started_at=started_at,
        completed_at=completed_at,
    )

    db.add(run)
    wallet.exit_price_coverage_status = readiness_status
    wallet.exit_price_coverage_score = readiness_score
    wallet.exit_price_local_observable_percent = safe_float(
        summary["local_observable_percent"]
    )
    wallet.exit_price_current_route_percent = safe_float(
        summary["current_route_supported_percent"]
    )
    wallet.exit_price_temporal_execution_percent = safe_float(
        summary["temporal_execution_percent"]
    )
    wallet.exit_price_audit_reasons = diagnoses
    wallet.latest_exit_price_audit_run_id = run.run_id
    wallet.exit_price_audit_calculated_at = completed_at

    db.commit()
    db.refresh(run)
    return run


def get_latest_candidate_exit_price_audit(
    db: Session,
    wallet_address: str,
) -> CandidateExitPriceAuditRun | None:
    return (
        db.query(CandidateExitPriceAuditRun)
        .filter(CandidateExitPriceAuditRun.wallet_address == wallet_address)
        .order_by(
            CandidateExitPriceAuditRun.completed_at.desc(),
            CandidateExitPriceAuditRun.id.desc(),
        )
        .first()
    )
