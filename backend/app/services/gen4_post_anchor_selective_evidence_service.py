from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.app.services.gen4_selective_copyability_gate_service import (
    FASTPATH_SELECTIVE_SCOPE,
    _end_to_quote_ms,
    classify_buy_attempt,
    evaluate_selective_copyability_gate,
)
from backend.app.services.gen4_promoted_selective_coverage_service import (
    evaluate_promoted_delivery_coverage,
)
from backend.app.services.gen4_selective_micro_live_readiness_service import (
    evaluate_selective_wallet,
    sign_selective_evidence,
    validate_selective_evidence,
)
from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
    validate_policy as validate_legacy_m74_m78_policy,
)

M299_VERSION = "canonical-parser-gen4-post-anchor-selective-evidence-builder/1"
M299_SCOPE = "M299_POST_ANCHOR_SELECTIVE_EVIDENCE_BUILDER_DISARMED"
M299_ACQUISITION_SCOPE = "M299_POST_ANCHOR_READONLY_ACQUISITION"
M299_ACQUISITION_VERSION = "canonical-parser-gen4-post-anchor-readonly-acquisition/1"
M299_BUILDER_ARMED = False
M299_PROMOTED_SELECTIVE_SCOPE = "PROMOTED_CANDIDATE_FASTPATH_SELECTIVE"

M297_ANCHOR_UTC = "2026-08-31T12:30:50.267406+00:00"
M297_REPORT_SHA256 = "0f1c033d7c4cc02d38e292970b3e334a5a665aee81e963bcd0727602ab7e4bf5"
M298_PRE_REPORT_SHA256 = "22be261b8af2a260cc253b7b71d50ccd876aa2894cb9d27082d968ca9d34c962"

OFFICIAL_WALLETS = {
    "OFF1_3KY83": "3kY83dXdi7efLLrP6Zer7Rs2MP7wgQakcLRHeutThQ32",
    "OFF4_Q4J6V": "Q4J6vefnKFmg5gAxGwnhthk5sewKDpnC8YNLD7Lv9ng",
    "OFF2_CWAMY": "CWAMyVxtvzzDvJX4arULju9Fkv9pvhz4gkNCfrupdsPr",
    "CFPH": "CfPHn2rGWoHQvpep71FZcwH1NsnHjLdYrq3VqeEQsZu8",
}
CHALLENGER_WALLETS = {
    "CGAZ": "CGAZ8ysbcmc6a14uYRqDJfnQvjRF4fVSZBYiTsZgRwcH",
    "89F3": "89f3DSmRiFsAZWQXCQMYPwyEUtxbVeCDP7JEjsXrbWST",
}


class M299Error(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M299Error(message)


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif value not in (None, ""):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _percentile95(values: Iterable[float]) -> float | None:
    clean = sorted(
        float(v)
        for v in values
        if isinstance(v, (int, float)) and math.isfinite(float(v))
    )
    if not clean:
        return None
    return clean[max(0, math.ceil(len(clean) * 0.95) - 1)]


def _without_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k != "integrity"}


def _accepted_signatures_after_anchor(
    wallet: str,
    events: list[Any],
    *,
    effective_anchor: datetime | None,
) -> set[str]:
    out: set[str] = set()
    for event in events:
        if str(_get(event, "wallet_address", "") or "") != wallet:
            continue
        if str(_get(event, "side", "") or "").upper() != "BUY":
            continue
        when = _aware(_get(event, "fast_received_at"))
        if when is None:
            continue
        if effective_anchor is not None and when <= effective_anchor:
            continue
        category, _ = classify_buy_attempt(event)
        if category != "ACCEPTED":
            continue
        signature = str(_get(event, "signature", "") or "")
        if signature:
            out.add(signature)
    return out


def realized_closed_equity_drawdown_percent(
    positions: list[Any],
    *,
    accepted_signatures: set[str],
    starting_capital_sol: float | None = None,
    position_scope: str = FASTPATH_SELECTIVE_SCOPE,
) -> dict[str, Any]:
    legacy = validate_legacy_m74_m78_policy()
    start_sol = (
        float(starting_capital_sol)
        if starting_capital_sol is not None
        else float(legacy["starting_capital_sol"])
    )
    _require(start_sol > 0, "M299 starting capital non positivo.")
    starting_lamports = int(round(start_sol * 1_000_000_000))

    closed = []
    for row in positions:
        if str(_get(row, "scope", "") or "") != str(position_scope):
            continue
        if str(_get(row, "entry_signature", "") or "") not in accepted_signatures:
            continue
        if str(_get(row, "status", "") or "") != "CLOSED":
            continue
        if not bool(_get(row, "exit_copyable", False)):
            continue
        if _integer(_get(row, "remaining_token_raw"), 0) != 0:
            continue
        closed.append(row)

    def sort_key(row: Any):
        when = (
            _aware(_get(row, "closed_at"))
            or _aware(_get(row, "opened_at"))
            or _aware(_get(row, "entry_received_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )
        return (when, str(_get(row, "position_id", "") or ""), _integer(_get(row, "id"), 0))

    closed.sort(key=sort_key)

    equity = starting_lamports
    peak = starting_lamports
    max_dd = 0.0
    trough_equity = starting_lamports
    max_losing_streak = 0
    losing_streak = 0

    for row in closed:
        pnl = _integer(_get(row, "pnl_lamports"), 0)
        equity += pnl
        if pnl < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0
        if equity > peak:
            peak = equity
        dd = ((peak - equity) / peak * 100.0) if peak > 0 else 100.0
        if dd > max_dd:
            max_dd = dd
            trough_equity = equity

    return {
        "method": "REALIZED_CLOSED_EQUITY_FROM_ACCEPTED_SELECTIVE_POSITIONS",
        "starting_capital_sol": start_sol,
        "closed_trades": len(closed),
        "ending_equity_sol": equity / 1_000_000_000,
        "peak_equity_sol": peak / 1_000_000_000,
        "trough_equity_sol_at_max_drawdown": trough_equity / 1_000_000_000,
        "maximum_drawdown_percent": round(max_dd, 9),
        "maximum_losing_closed_streak": max_losing_streak,
        "mark_to_market_claimed": False,
        "source_m74_drawdown_replaced": False,
    }


def build_official_wallet_evidence(
    *,
    wallet: str,
    events: list[Any],
    positions: list[Any],
    receipts: list[Any],
    campaign: Any,
    anchor_utc: datetime,
    terminal_at: datetime,
) -> dict[str, Any]:
    anchor = _aware(anchor_utc)
    terminal = _aware(terminal_at)
    _require(anchor is not None, "M299 official anchor mancante.")
    _require(terminal is not None, "M299 terminal mancante.")
    _require(terminal >= anchor, "M299 terminal precedente all'anchor.")

    gate = evaluate_selective_copyability_gate(
        wallet=wallet,
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=campaign,
        terminal_at=terminal,
        anchor_utc=anchor,
    )
    clean = dict(gate.get("clean_window") or {})
    economics = dict(gate.get("economics") or {})

    effective_anchor = _aware(clean.get("effective_anchor_utc")) or anchor
    accepted_signatures = _accepted_signatures_after_anchor(
        wallet,
        events,
        effective_anchor=effective_anchor,
    )
    dd = realized_closed_equity_drawdown_percent(
        positions,
        accepted_signatures=accepted_signatures,
    )

    attempts = _integer(clean.get("attempts"), 0)
    accepted = _integer(clean.get("accepted"), 0)
    market = _integer(clean.get("market_protective_rejects"), 0)
    liquidity = _integer(clean.get("liquidity_protective_rejects"), 0)
    technical = _integer(clean.get("technical_failures"), 0)
    protective = market + liquidity
    unmapped = max(0, attempts - accepted - protective - technical)

    accepted_policy_violations = list(clean.get("accepted_policy_violations") or [])
    exit_policy_violations = list(clean.get("exit_policy_violations") or [])
    exit_failures = _integer(clean.get("exit_failures"), 0)

    unresolved = (
        technical
        + unmapped
        + len(accepted_policy_violations)
        + len(exit_policy_violations)
        + exit_failures
    )

    row = {
        "wallet_address": wallet,
        "observation_hours": _finite(clean.get("observation_hours"), 0.0),
        "entry_attempts": attempts,
        "accepted_attempts": accepted,
        "protective_rejects": protective,
        "technical_failures": technical,
        "unmapped_attempts": unmapped,
        "closed_trades": _integer(economics.get("closed_trades"), 0),
        "webhook_coverage_percent": _finite(clean.get("webhook_coverage_percent"), 0.0),
        "accepted_unsigned_build_coverage_percent": _finite(
            clean.get("accepted_unsigned_build_coverage_percent"), 0.0
        ),
        "accepted_p95_end_to_quote_ms": clean.get("p95_accepted_end_to_quote_ms"),
        "accepted_p95_price_deterioration_bps": clean.get(
            "p95_accepted_price_deterioration_bps"
        ),
        "accepted_p95_price_impact_bps": clean.get("p95_accepted_price_impact_bps"),
        "accepted_policy_violations": len(accepted_policy_violations),
        "exit_policy_violations": len(exit_policy_violations),
        "exit_failures": exit_failures,
        "open_positions": _integer(clean.get("open_positions"), 0),
        "unresolved_failures": unresolved,
        "net_pnl_sol": _finite(economics.get("net_pnl_sol"), 0.0),
        "profit_factor": _finite(economics.get("profit_factor"), 0.0),
        "maximum_drawdown_percent": dd["maximum_drawdown_percent"],
        "m299_metadata": {
            "m297_anchor_utc": anchor.isoformat(),
            "effective_clean_anchor_utc": effective_anchor.isoformat(),
            "technical_reset_applied": effective_anchor > anchor,
            "market_protective_rejects": market,
            "liquidity_protective_rejects": liquidity,
            "accepted_signature_count": len(accepted_signatures),
            "m291_diagnostic_selective_pass_without_m74": bool(
                gate.get("diagnostic_selective_pass_without_m74")
            ),
            "m291_formal_selective_pass": False,
            "m291_formal_m74_admitted": bool(gate.get("formal_m74_admitted")),
            "drawdown": dd,
            "source_m74_used_as_admission_gate": False,
        },
    }

    # This validates the exact shape expected by M298 without claiming a formal pass.
    individual = evaluate_selective_wallet(
        wallet,
        row,
        source_m74_audit={"passed": None, "failed_checks": []},
    )
    return {
        "wallet_evidence": row,
        "m298_individual_evaluation": individual,
        "m291_gate_snapshot": gate,
    }



def build_promoted_wallet_evidence(
    *,
    wallet: str,
    events: list[Any],
    positions: list[Any],
    activation: Any,
    terminal_at: datetime,
    delivery_receipts: list[Any] | None = None,
) -> dict[str, Any]:
    anchor = _aware(_get(activation, "activation_anchor_at"))
    terminal = _aware(terminal_at)
    _require(anchor is not None, "M299 promoted activation anchor mancante.")
    _require(terminal is not None and terminal >= anchor, "M299 promoted terminal invalido.")

    activation_id = str(_get(activation, "activation_id", "") or "")
    policy = dict(_get(activation, "policy_snapshot", {}) or {})
    _require(activation_id, "M299 promoted activation_id mancante.")

    post_anchor: list[dict[str, Any]] = []
    for event in events:
        if str(_get(event, "wallet_address", "") or "") != wallet:
            continue
        if str(_get(event, "side", "") or "").upper() != "BUY":
            continue
        when = _aware(_get(event, "fast_received_at"))
        if when is None or when <= anchor or when > terminal:
            continue
        category, code = classify_buy_attempt(event)
        post_anchor.append(
            {
                "event": event,
                "timestamp": when,
                "category": category,
                "code": code,
                "signature": str(_get(event, "signature", "") or ""),
            }
        )
    post_anchor.sort(key=lambda row: (row["timestamp"], row["signature"]))

    technical_all = [
        row for row in post_anchor if row["category"] == "TECHNICAL_FAILURE"
    ]
    last_technical = (
        max(row["timestamp"] for row in technical_all)
        if technical_all else None
    )
    effective_anchor = max(
        value for value in (anchor, last_technical) if value is not None
    )
    clean = [row for row in post_anchor if row["timestamp"] > effective_anchor]
    accepted = [row for row in clean if row["category"] == "ACCEPTED"]
    market = [
        row for row in clean if row["category"] == "MARKET_PROTECTIVE_REJECT"
    ]
    liquidity = [
        row for row in clean if row["category"] == "LIQUIDITY_PROTECTIVE_REJECT"
    ]
    technical = [
        row for row in clean if row["category"] == "TECHNICAL_FAILURE"
    ]
    unmapped = [
        row for row in clean
        if row["category"] not in {
            "ACCEPTED",
            "MARKET_PROTECTIVE_REJECT",
            "LIQUIDITY_PROTECTIVE_REJECT",
            "TECHNICAL_FAILURE",
        }
    ]

    coverage = evaluate_promoted_delivery_coverage(
        wallet=wallet,
        activation_id=activation_id,
        clean_attempts=[row["event"] for row in clean],
        delivery_receipts=list(delivery_receipts or []),
        effective_anchor=effective_anchor,
        terminal_at=terminal,
    )
    delivery_gap_technical_count = int(coverage["webhook_only_buy_gap_count"])

    accepted_signatures = {
        row["signature"] for row in accepted if row["signature"]
    }
    accepted_end: list[float] = []
    accepted_det: list[float] = []
    accepted_impact: list[float] = []
    accepted_policy_violations = 0
    for row in accepted:
        event = row["event"]
        end = _end_to_quote_ms(event, None, policy)
        det = _finite(
            _get(event, "fast_price_deterioration_bps"),
            float("nan"),
        )
        impact = _finite(
            _get(event, "fast_price_impact_bps"),
            float("nan"),
        )
        built = bool(_get(event, "fast_transaction_built", False))
        lifecycle = dict(
            dict(_get(event, "evidence", {}) or {}).get(
                "promoted_selective_lifecycle"
            )
            or {}
        )
        complete = (
            end is not None
            and math.isfinite(float(end))
            and math.isfinite(det)
            and math.isfinite(impact)
            and built
        )
        violation = lifecycle.get("policy_violation") is True or not complete
        if violation:
            accepted_policy_violations += 1
        if not complete:
            continue
        accepted_end.append(float(end))
        accepted_det.append(det)
        accepted_impact.append(impact)

    relevant_positions = [
        position
        for position in positions
        if str(_get(position, "wallet_address", "") or "") == wallet
        and str(_get(position, "activation_id", "") or "") == activation_id
        and str(_get(position, "entry_signature", "") or "") in accepted_signatures
        and (_aware(_get(position, "entry_received_at")) or anchor) > effective_anchor
    ]
    closed_positions = [
        position
        for position in relevant_positions
        if str(_get(position, "status", "") or "") == "CLOSED"
        and _get(position, "pnl_lamports") is not None
        and bool(_get(position, "exit_copyable", False))
    ]
    pnl_lamports = [int(_get(position, "pnl_lamports", 0) or 0) for position in closed_positions]
    gross_profit = sum(value for value in pnl_lamports if value > 0)
    gross_loss = abs(sum(value for value in pnl_lamports if value < 0))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (999.0 if gross_profit > 0 else 0.0)
    )
    net_pnl_sol = sum(pnl_lamports) / 1_000_000_000
    dd = realized_closed_equity_drawdown_percent(
        relevant_positions,
        accepted_signatures=accepted_signatures,
        position_scope=M299_PROMOTED_SELECTIVE_SCOPE,
    )

    exit_failures = 0
    exit_policy_violations = 0
    policy_exit_codes = {
        "EXIT_QUOTE_TOO_SLOW",
        "EXIT_NO_EXECUTABLE_OUTPUT",
        "EXIT_PRICE_IMPACT_TOO_HIGH",
        "EXIT_UNSIGNED_TRANSACTION_NOT_BUILT",
    }
    for position in relevant_positions:
        failures = list(
            dict(_get(position, "evidence", {}) or {}).get("exit_failures") or []
        )
        exit_failures += len(failures)
        exit_policy_violations += sum(
            str(item.get("code") or "") in policy_exit_codes
            for item in failures
            if isinstance(item, dict)
        )

    attempts = len(clean)
    accepted_count = len(accepted)
    protective = len(market) + len(liquidity)
    open_positions = sum(
        str(_get(position, "status", "") or "") in {"OPEN", "OPEN_PARTIAL"}
        and int(_get(position, "remaining_token_raw", 0) or 0) > 0
        for position in relevant_positions
    )
    unresolved = (
        len(technical)
        + delivery_gap_technical_count
        + len(unmapped)
        + accepted_policy_violations
        + exit_policy_violations
        + exit_failures
    )
    unsigned_pct = (
        100.0
        * sum(bool(_get(row["event"], "fast_transaction_built", False)) for row in accepted)
        / accepted_count
        if accepted_count else 0.0
    )
    observation_hours = max(
        0.0, (terminal - effective_anchor).total_seconds() / 3600.0
    )

    evidence_row = {
        "wallet_address": wallet,
        "observation_hours": observation_hours,
        "entry_attempts": attempts,
        "accepted_attempts": accepted_count,
        "protective_rejects": protective,
        "technical_failures": len(technical),
        "unmapped_attempts": len(unmapped),
        "closed_trades": len(closed_positions),
        # M309 preserves WSS as the primary fastpath and uses independently
        # authenticated raw-webhook receipts only as secondary delivery evidence.
        "webhook_coverage_percent": float(coverage["webhook_coverage_percent"]),
        "accepted_unsigned_build_coverage_percent": unsigned_pct,
        "accepted_p95_end_to_quote_ms": _percentile95(accepted_end),
        "accepted_p95_price_deterioration_bps": _percentile95(accepted_det),
        "accepted_p95_price_impact_bps": _percentile95(accepted_impact),
        "accepted_policy_violations": accepted_policy_violations,
        "exit_policy_violations": exit_policy_violations,
        "exit_failures": exit_failures,
        "open_positions": open_positions,
        "unresolved_failures": unresolved,
        "net_pnl_sol": net_pnl_sol,
        "profit_factor": profit_factor,
        "maximum_drawdown_percent": dd["maximum_drawdown_percent"],
        "m299_metadata": {
            "lane": "PROMOTED_CANDIDATE_FASTPATH_SELECTIVE",
            "activation_id": activation_id,
            "activation_anchor_utc": anchor.isoformat(),
            "effective_clean_anchor_utc": effective_anchor.isoformat(),
            "technical_reset_applied": effective_anchor > anchor,
            "prepromotion_backfill": False,
            "accepted_signature_count": len(accepted_signatures),
            "drawdown": dd,
            "delivery_coverage_contract": {
                "candidate_runtime": "PROCESSED_WSS",
                "secondary_delivery": "AUTHENTICATED_RAW_WEBHOOK",
                "independent_webhook_coverage_available": bool(delivery_receipts),
                "webhook_coverage_percent_claimed": float(coverage["webhook_coverage_percent"]),
                "coverage_numerator": int(coverage["numerator_auth_verified_webhook_signatures"]),
                "coverage_denominator": int(coverage["denominator_clean_fastpath_buy_attempts"]),
                "webhook_only_buy_gap_count": delivery_gap_technical_count,
                "webhook_only_buy_gap_signatures": list(coverage["webhook_only_buy_gap_signatures"]),
                "no_wss_as_webhook_relabeling": True,
                "preactivation_backfill": False,
            },
            "source_m74_used_as_admission_gate": False,
        },
    }
    individual = evaluate_selective_wallet(
        wallet,
        evidence_row,
        source_m74_audit={"passed": None, "failed_checks": []},
    )
    if not delivery_receipts:
        coverage_blocker = "INDEPENDENT_WEBHOOK_OR_EQUIVALENT_DELIVERY_COVERAGE_NOT_YET_PROVEN"
    elif delivery_gap_technical_count:
        coverage_blocker = "WEBHOOK_ONLY_BUY_GAP_TECHNICAL_EVIDENCE"
    elif individual["checks"]["webhook_coverage"] is not True:
        coverage_blocker = "AUTHENTICATED_WEBHOOK_COVERAGE_BELOW_M298_THRESHOLD"
    else:
        coverage_blocker = None
    return {
        "wallet_evidence": evidence_row,
        "m298_individual_evaluation": individual,
        "delivery_coverage": coverage,
        "coverage_blocker": coverage_blocker,
        "full_lifecycle_claimed": True,
        "prepromotion_backfill": False,
    }

def build_challenger_progress(
    *,
    wallet: str,
    events: list[Any],
    anchor_utc: datetime,
    terminal_at: datetime,
) -> dict[str, Any]:
    anchor = _aware(anchor_utc)
    terminal = _aware(terminal_at)
    _require(anchor is not None and terminal is not None, "M299 challenger time boundary invalido.")

    rows = []
    for event in events:
        if str(_get(event, "wallet_address", "") or "") != wallet:
            continue
        if str(_get(event, "side", "") or "").upper() != "BUY":
            continue
        when = _aware(_get(event, "fast_received_at"))
        if when is None or when <= anchor or when > terminal:
            continue
        category, code = classify_buy_attempt(event)
        rows.append((when, event, category, code))
    rows.sort(key=lambda x: x[0])

    accepted = [x for x in rows if x[2] == "ACCEPTED"]
    market = [x for x in rows if x[2] == "MARKET_PROTECTIVE_REJECT"]
    liquidity = [x for x in rows if x[2] == "LIQUIDITY_PROTECTIVE_REJECT"]
    technical = [x for x in rows if x[2] == "TECHNICAL_FAILURE"]
    unmapped = [
        x for x in rows
        if x[2] not in {
            "ACCEPTED",
            "MARKET_PROTECTIVE_REJECT",
            "LIQUIDITY_PROTECTIVE_REJECT",
            "TECHNICAL_FAILURE",
        }
    ]

    times = [x[0] for x in rows]
    observation_hours = (
        max(0.0, (max(times) - min(times)).total_seconds() / 3600.0)
        if len(times) >= 2 else 0.0
    )
    end_ms = [
        _finite(_get(x[1], "fast_end_to_quote_ms"), float("nan"))
        for x in accepted
    ]
    det = [
        _finite(_get(x[1], "fast_price_deterioration_bps"), float("nan"))
        for x in accepted
    ]
    impact = [
        _finite(_get(x[1], "fast_price_impact_bps"), float("nan"))
        for x in accepted
    ]
    unsigned_pct = (
        100.0
        * sum(bool(_get(x[1], "fast_transaction_built", False)) for x in accepted)
        / len(accepted)
        if accepted else 0.0
    )

    return {
        "wallet_address": wallet,
        "scope": "CANDIDATE",
        "anchor_utc": anchor.isoformat(),
        "observation_hours": round(observation_hours, 6),
        "entry_attempts": len(rows),
        "accepted_attempts": len(accepted),
        "protective_rejects": len(market) + len(liquidity),
        "market_protective_rejects": len(market),
        "liquidity_protective_rejects": len(liquidity),
        "technical_failures": len(technical),
        "unmapped_attempts": len(unmapped),
        "accepted_unsigned_build_coverage_percent": round(unsigned_pct, 6),
        "accepted_p95_end_to_quote_ms": _percentile95(end_ms),
        "accepted_p95_price_deterioration_bps": _percentile95(det),
        "accepted_p95_price_impact_bps": _percentile95(impact),
        "selective_evidence_eligible": False,
        "full_lifecycle_claimed": False,
        "closed_trades_claimed": False,
        "profit_factor_claimed": False,
        "drawdown_claimed": False,
        "promotion_required_before_m298_wallet_evidence": True,
        "reason": "CANDIDATE_ENTRY_ONLY_NO_SELECTIVE_POSITION_LIFECYCLE",
    }


def build_acquisition_report(
    *,
    official_results: dict[str, dict[str, Any]],
    challenger_results: dict[str, dict[str, Any]],
    acquired_at: datetime,
    acquisition_safety: dict[str, Any],
) -> dict[str, Any]:
    acquired = _aware(acquired_at)
    _require(acquired is not None, "M299 acquired_at invalido.")

    safety = dict(acquisition_safety or {})
    _require(
        str(safety.get("database_transaction") or "")
        == "REPEATABLE_READ_READ_ONLY",
        "M299 acquisition DB transaction non read-only.",
    )
    _require(_integer(safety.get("database_writes"), -1) == 0, "M299 acquisition contiene DB writes.")
    _require(_integer(safety.get("backend_mutations"), -1) == 0, "M299 acquisition contiene backend mutations.")
    _require(_integer(safety.get("helius_calls"), -1) == 0, "M299 acquisition contiene Helius calls.")
    _require(_integer(safety.get("birdeye_cu"), -1) == 0, "M299 acquisition contiene Birdeye CU.")
    _require(_integer(safety.get("jupiter_requests"), -1) == 0, "M299 acquisition contiene Jupiter requests.")
    _require(safety.get("live") is False, "M299 acquisition LIVE non disarmato.")
    _require(safety.get("signer") is False, "M299 acquisition signer non disarmato.")
    _require(_integer(safety.get("paper_orders"), -1) == 0, "M299 acquisition paper orders presenti.")

    payload: dict[str, Any] = {
        "scope": M299_ACQUISITION_SCOPE,
        "version": M299_ACQUISITION_VERSION,
        "m299_builder_version": M299_VERSION,
        "m297_anchor_utc": M297_ANCHOR_UTC,
        "m297_report_sha256": M297_REPORT_SHA256,
        "m298_pre_report_sha256": M298_PRE_REPORT_SHA256,
        "acquired_at_utc": acquired.isoformat(),
        "official_results": dict(official_results or {}),
        "challenger_results": dict(challenger_results or {}),
        "acquisition_safety": safety,
        "formal_claims": {
            "m74_pass_invented": False,
            "legacy_m75_pass_claimed": False,
            "challenger_full_lifecycle_claimed": False,
            "micro_live_authorized": False,
        },
    }
    payload["integrity"] = {"report_payload_sha256": canonical_sha256(payload)}
    return payload


def validate_acquisition_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("scope") == M299_ACQUISITION_SCOPE, "M299 acquisition scope inatteso.")
    _require(report.get("version") == M299_ACQUISITION_VERSION, "M299 acquisition version inattesa.")
    _require(report.get("m297_anchor_utc") == M297_ANCHOR_UTC, "M299 anchor lineage inattesa.")
    _require(report.get("m297_report_sha256") == M297_REPORT_SHA256, "M299 M297 lineage SHA inatteso.")
    _require(report.get("m298_pre_report_sha256") == M298_PRE_REPORT_SHA256, "M299 M298 lineage SHA inatteso.")
    integrity = dict(report.get("integrity") or {})
    expected = str(integrity.get("report_payload_sha256") or "")
    _require(
        len(expected) == 64
        and expected == canonical_sha256(_without_integrity(report)),
        "M299 acquisition integrity SHA non valido.",
    )
    safety = dict(report.get("acquisition_safety") or {})
    _require(
        str(safety.get("database_transaction") or "")
        == "REPEATABLE_READ_READ_ONLY",
        "M299 acquisition DB safety invalida.",
    )
    _require(_integer(safety.get("database_writes"), -1) == 0, "M299 acquisition DB writes non zero.")
    return report


def sign_m298_evidence_from_acquisition(
    acquisition_report: dict[str, Any],
) -> dict[str, Any]:
    validate_acquisition_report(acquisition_report)

    wallet_evidence: dict[str, dict[str, Any]] = {}
    for label, result in dict(acquisition_report.get("official_results") or {}).items():
        row = dict(result.get("wallet_evidence") or {})
        wallet = str(row.get("wallet_address") or "")
        _require(wallet, f"M299 official evidence senza wallet: {label}.")
        wallet_evidence[wallet] = row

    _require(bool(wallet_evidence), "M299 nessuna official evidence da firmare.")
    acquisition_sha = str(
        dict(acquisition_report.get("integrity") or {}).get("report_payload_sha256")
        or ""
    )
    signed = sign_selective_evidence(
        wallet_evidence,
        anchor_utc=M297_ANCHOR_UTC,
        lineage={
            "m299_acquisition_report_sha256": acquisition_sha,
            "m299_acquisition_scope": M299_ACQUISITION_SCOPE,
            "m299_acquisition_version": M299_ACQUISITION_VERSION,
            "m299_transform_network_requests": 0,
            "m299_transform_database_reads": 0,
            "m299_transform_database_writes": 0,
            "m299_acquisition_was_networked_read_only": True,
            "m299_acquisition_safety": dict(
                acquisition_report.get("acquisition_safety") or {}
            ),
            "m297_report_sha256": M297_REPORT_SHA256,
            "m298_pre_report_sha256": M298_PRE_REPORT_SHA256,
        },
    )
    validate_selective_evidence(signed)
    return signed


def preparation_report() -> dict[str, Any]:
    legacy = validate_legacy_m74_m78_policy()
    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M299_SCOPE,
        "version": M299_VERSION,
        "state": "IMPLEMENTED_DISARMED_AWAITING_POST_ANCHOR_CHECKPOINT",
        "m297_lineage": {
            "anchor_utc": M297_ANCHOR_UTC,
            "report_sha256": M297_REPORT_SHA256,
        },
        "m298_lineage": {
            "report_sha256": M298_PRE_REPORT_SHA256,
        },
        "official_wallets": OFFICIAL_WALLETS,
        "challenger_wallets": CHALLENGER_WALLETS,
        "drawdown_contract": {
            "method": "REALIZED_CLOSED_EQUITY_FROM_ACCEPTED_SELECTIVE_POSITIONS",
            "starting_capital_sol": float(legacy["starting_capital_sol"]),
            "mark_to_market_claimed": False,
            "source_m74_drawdown_replaced": False,
            "qualification_requires_zero_open_positions_via_m298": True,
        },
        "provenance_contract": {
            "phase_1": "NETWORKED_READONLY_ACQUISITION_REPORT",
            "phase_2": "ZERO_NETWORK_M298_EVIDENCE_TRANSFORM",
            "linked_by_sha256": True,
            "database_reads_never_reported_as_zero_in_acquisition_phase": True,
        },
        "challenger_contract": {
            "entry_only": True,
            "m298_wallet_evidence_eligible": False,
            "promotion_required": True,
        },
        "safety": {
            "builder_armed": False,
            "automatic_collection": False,
            "automatic_promotion": False,
            "automatic_live_activation": False,
            "micro_live_execution_authorized": False,
            "m74_changed": False,
            "m75_changed": False,
            "pam_changed": False,
        },
    }
    payload["integrity"] = {"report_payload_sha256": canonical_sha256(payload)}
    return payload
