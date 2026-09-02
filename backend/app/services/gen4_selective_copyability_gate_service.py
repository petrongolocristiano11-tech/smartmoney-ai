from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import validate_policy

SELECTIVE_GATE_VERSION = "m291-selective-copyability-qualification-gate/1"
SELECTIVE_GATE_SCOPE = "M291_SELECTIVE_COPYABILITY_QUALIFICATION_GATE_DISARMED"
SELECTIVE_GATE_FORMAL_ARMED = False

MARKET_PROTECTIVE_REJECTIONS = frozenset({
    "PRICE_ALREADY_MOVED",
    "PRICE_IMPACT_TOO_HIGH",
})
LIQUIDITY_PROTECTIVE_REJECTIONS = frozenset({
    "NO_EXECUTABLE_OUTPUT",
})
TECHNICAL_REJECTIONS = frozenset({
    "QUOTE_TOO_SLOW",
    "UNSIGNED_TRANSACTION_NOT_BUILT",
})
FASTPATH_SELECTIVE_SCOPE = "OFFICIAL_FASTPATH_SELECTIVE"
WEBHOOK_SOURCE = "WEBHOOK"


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _campaign_formal_m74(campaign: Any) -> bool:
    selection = _dict(_get(campaign, "selection_snapshot", {}))
    return selection.get("formal_m74_pass") is True


def _receipt_map(receipts: Iterable[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in receipts:
        if str(_get(row, "source", "") or "") != WEBHOOK_SOURCE:
            continue
        if _get(row, "auth_verified") is not True:
            continue
        sig = str(_get(row, "signature", "") or "")
        if not sig:
            continue
        current = out.get(sig)
        if current is None:
            out[sig] = row
            continue
        old = _aware(_get(current, "received_at"))
        new = _aware(_get(row, "received_at"))
        if new is not None and (old is None or new < old):
            out[sig] = row
    return out


def _block_time(receipt: Any | None) -> datetime | None:
    if receipt is None:
        return None
    direct = _aware(_get(receipt, "block_time"))
    if direct is not None:
        return direct
    summary = _dict(_get(receipt, "parsed_summary", {}))
    value = summary.get("block_time")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return _aware(value)


def _end_to_quote_ms(event: Any, receipt: Any | None, policy: dict[str, Any]) -> float | None:
    quote_at = _aware(_get(event, "fast_quote_received_at"))
    block_at = _block_time(receipt)
    if quote_at is not None and block_at is not None:
        return max(0.0, (quote_at - block_at).total_seconds() * 1000.0)
    stored = _get(event, "fast_end_to_quote_ms")
    if stored is not None:
        try:
            return max(0.0, float(stored))
        except (TypeError, ValueError):
            return None
    received = _aware(_get(event, "fast_received_at"))
    if quote_at is not None and received is not None:
        return max(0.0, (quote_at - received).total_seconds() * 1000.0)
    prequote = _get(event, "fast_prequote_ms")
    quote_latency = _get(event, "fast_quote_latency_ms")
    if prequote is not None and quote_latency is not None:
        try:
            return max(0.0, float(prequote) + float(quote_latency))
        except (TypeError, ValueError):
            return None
    return None


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _percentile95(values: list[float]) -> float | None:
    clean = sorted(float(v) for v in values if _finite_float(v) is not None)
    if not clean:
        return None
    index = max(0, math.ceil(len(clean) * 0.95) - 1)
    return clean[index]


def classify_buy_attempt(event: Any) -> tuple[str, str]:
    parse_error = str(_get(event, "parse_error_code", "") or "").strip()
    quote_error = str(_get(event, "quote_error_code", "") or "").strip()
    if parse_error:
        return "TECHNICAL_FAILURE", f"PARSE:{parse_error}"
    if quote_error:
        return "TECHNICAL_FAILURE", f"QUOTE:{quote_error}"

    reason = str(_get(event, "fast_provisional_rejection_reason", "") or "").strip()
    copyable = bool(_get(event, "fast_provisional_copyable", False))
    built = bool(_get(event, "fast_transaction_built", False))

    if copyable and built and not reason:
        if _get(event, "fast_quote_received_at") is None:
            return "TECHNICAL_FAILURE", "INCOMPLETE_ACCEPTED_QUOTE_EVIDENCE"
        if _finite_float(_get(event, "fast_price_impact_bps")) is None:
            return "TECHNICAL_FAILURE", "INCOMPLETE_ACCEPTED_IMPACT_EVIDENCE"
        if _finite_float(_get(event, "fast_price_deterioration_bps")) is None:
            return "TECHNICAL_FAILURE", "INCOMPLETE_ACCEPTED_DETERIORATION_EVIDENCE"
        return "ACCEPTED", "ACCEPTED"

    if reason in MARKET_PROTECTIVE_REJECTIONS:
        return "MARKET_PROTECTIVE_REJECT", reason
    if reason in LIQUIDITY_PROTECTIVE_REJECTIONS:
        return "LIQUIDITY_PROTECTIVE_REJECT", reason
    if reason in TECHNICAL_REJECTIONS:
        return "TECHNICAL_FAILURE", reason
    if reason == "NOT_A_BUY_SIGNAL":
        return "NOT_BUY_SIGNAL", reason
    if not built and not reason:
        return "TECHNICAL_FAILURE", "UNSIGNED_TRANSACTION_NOT_BUILT"
    if reason:
        return "TECHNICAL_FAILURE", f"UNMAPPED_REJECTION:{reason}"
    return "TECHNICAL_FAILURE", "UNCLASSIFIED_BUY_ATTEMPT"


def _exit_failures(position: Any) -> list[tuple[datetime | None, str]]:
    evidence = _dict(_get(position, "evidence", {}))
    out: list[tuple[datetime | None, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in list(evidence.get("exit_failures") or []):
        if not isinstance(raw, dict):
            continue
        sig = str(raw.get("signature") or "")
        code = str(raw.get("code") or "UNKNOWN")
        key = (sig, code)
        if key in seen:
            continue
        seen.add(key)
        when = (
            _aware(raw.get("observed_at"))
            or _aware(_get(position, "closed_at"))
            or _aware(_get(position, "opened_at"))
        )
        out.append((when, f"EXIT:{code}"))
    return out


def _exit_policy_violation(position: Any, campaign: Any) -> bool:
    if str(_get(position, "status", "") or "") != "CLOSED":
        return False
    if not bool(_get(position, "exit_copyable", False)):
        return True
    if not bool(_get(position, "exit_transaction_built", False)):
        return True
    latency = _finite_float(_get(position, "exit_quote_latency_ms"))
    impact = _finite_float(_get(position, "exit_price_impact_bps"))
    max_quote = float(_get(campaign, "max_quote_latency_ms", 5000) or 5000)
    max_impact = float(_get(campaign, "max_price_impact_bps", 500) or 500)
    if latency is None or latency > max_quote:
        return True
    if impact is None or impact > max_impact:
        return True
    return False


def _economics(positions: list[Any]) -> dict[str, Any]:
    closed = [
        row
        for row in positions
        if str(_get(row, "status", "") or "") == "CLOSED"
        and bool(_get(row, "exit_copyable", False))
        and int(_get(row, "remaining_token_raw", 0) or 0) == 0
    ]
    pnls = [int(_get(row, "pnl_lamports", 0) or 0) for row in closed]
    gross_profit = sum(x for x in pnls if x > 0)
    gross_loss = -sum(x for x in pnls if x < 0)
    if gross_loss:
        profit_factor = gross_profit / gross_loss
    elif gross_profit:
        profit_factor = 999.0
    else:
        profit_factor = 0.0
    return {
        "closed_trades": len(closed),
        "net_pnl_lamports": sum(pnls),
        "net_pnl_sol": sum(pnls) / 1_000_000_000,
        "gross_profit_lamports": gross_profit,
        "gross_loss_lamports": gross_loss,
        "profit_factor": profit_factor,
        "win_rate_percent": (
            100.0 * sum(x > 0 for x in pnls) / len(pnls) if pnls else 0.0
        ),
    }


def evaluate_selective_copyability_gate(
    *,
    wallet: str,
    events: list[Any],
    positions: list[Any],
    receipts: list[Any],
    campaign: Any,
    terminal_at: datetime,
    anchor_utc: datetime | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = validate_policy(policy)
    terminal = _aware(terminal_at)
    if terminal is None:
        raise ValueError("M291_TERMINAL_AT_REQUIRED")

    receipt_by_sig = _receipt_map(receipts)
    wallet_events = [
        row for row in events
        if str(_get(row, "wallet_address", "") or "") == wallet
        and str(_get(row, "side", "") or "").upper() == "BUY"
    ]
    wallet_events.sort(
        key=lambda row: _aware(_get(row, "fast_received_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )
    wallet_positions = [
        row for row in positions
        if str(_get(row, "wallet_address", "") or "") == wallet
        and str(_get(row, "scope", "") or "") == FASTPATH_SELECTIVE_SCOPE
    ]

    classifications: list[dict[str, Any]] = []
    technical_failures: list[tuple[datetime | None, str, str | None]] = []

    for event in wallet_events:
        category, code = classify_buy_attempt(event)
        received = _aware(_get(event, "fast_received_at"))
        sig = str(_get(event, "signature", "") or "")
        classifications.append(
            {
                "event": event,
                "category": category,
                "code": code,
                "timestamp": received,
                "signature": sig,
            }
        )
        if category == "TECHNICAL_FAILURE":
            technical_failures.append((received, code, sig or None))

    for position in wallet_positions:
        for when, code in _exit_failures(position):
            technical_failures.append(
                (when, code, str(_get(position, "entry_signature", "") or "") or None)
            )

    explicit_anchor = _aware(anchor_utc)
    technical_times = [when for when, _, _ in technical_failures if when is not None]
    last_technical_at = max(technical_times) if technical_times else None

    clean_anchor_candidates = [x for x in (explicit_anchor, last_technical_at) if x is not None]
    clean_anchor = max(clean_anchor_candidates) if clean_anchor_candidates else None

    clean_attempts = []
    for row in classifications:
        when = row["timestamp"]
        if when is None:
            continue
        if clean_anchor is not None and when <= clean_anchor:
            continue
        clean_attempts.append(row)

    accepted = [row for row in clean_attempts if row["category"] == "ACCEPTED"]
    market_protective = [
        row for row in clean_attempts if row["category"] == "MARKET_PROTECTIVE_REJECT"
    ]
    liquidity_protective = [
        row for row in clean_attempts if row["category"] == "LIQUIDITY_PROTECTIVE_REJECT"
    ]
    clean_technical = [
        row for row in clean_attempts if row["category"] == "TECHNICAL_FAILURE"
    ]
    clean_unmapped = [
        row for row in clean_attempts
        if row["category"] not in {
            "ACCEPTED",
            "MARKET_PROTECTIVE_REJECT",
            "LIQUIDITY_PROTECTIVE_REJECT",
            "TECHNICAL_FAILURE",
        }
    ]

    accepted_signatures = {row["signature"] for row in accepted if row["signature"]}
    clean_positions = [
        row for row in wallet_positions
        if str(_get(row, "entry_signature", "") or "") in accepted_signatures
    ]

    accepted_end_ms: list[float] = []
    accepted_impact: list[float] = []
    accepted_deterioration: list[float] = []
    accepted_policy_violations: list[str] = []
    webhook_covered = 0

    for row in clean_attempts:
        event = row["event"]
        receipt = receipt_by_sig.get(row["signature"])
        if receipt is not None:
            webhook_covered += 1

        if row["category"] != "ACCEPTED":
            continue

        end_ms = _end_to_quote_ms(event, receipt, p)
        impact = _finite_float(_get(event, "fast_price_impact_bps"))
        deterioration = _finite_float(_get(event, "fast_price_deterioration_bps"))
        if end_ms is None or impact is None or deterioration is None:
            accepted_policy_violations.append(
                f"INCOMPLETE_ACCEPTED_EVIDENCE:{row['signature'] or 'UNKNOWN'}"
            )
            continue
        accepted_end_ms.append(end_ms)
        accepted_impact.append(impact)
        accepted_deterioration.append(deterioration)

        if end_ms > float(p["canary_maximum_p95_end_to_quote_ms"]):
            accepted_policy_violations.append(
                f"ACCEPTED_END_TO_QUOTE:{row['signature'] or 'UNKNOWN'}"
            )
        if impact > float(p["canary_maximum_p95_price_impact_bps"]):
            accepted_policy_violations.append(
                f"ACCEPTED_PRICE_IMPACT:{row['signature'] or 'UNKNOWN'}"
            )
        if deterioration > float(p["canary_maximum_p95_price_deterioration_bps"]):
            accepted_policy_violations.append(
                f"ACCEPTED_DETERIORATION:{row['signature'] or 'UNKNOWN'}"
            )
        if not bool(_get(event, "fast_transaction_built", False)):
            accepted_policy_violations.append(
                f"ACCEPTED_UNSIGNED_NOT_BUILT:{row['signature'] or 'UNKNOWN'}"
            )

    exit_policy_violations = [
        str(_get(row, "position_id", "") or _get(row, "entry_signature", "") or "UNKNOWN")
        for row in clean_positions
        if _exit_policy_violation(row, campaign)
    ]

    open_positions = sum(
        str(_get(row, "status", "") or "") in {"OPEN", "OPEN_PARTIAL"}
        and int(_get(row, "remaining_token_raw", 0) or 0) > 0
        for row in clean_positions
    )

    clean_exit_failures = []
    for row in clean_positions:
        clean_exit_failures.extend(_exit_failures(row))

    economics = _economics(clean_positions)

    clean_times = [
        row["timestamp"] for row in clean_attempts if row["timestamp"] is not None
    ]
    if clean_times:
        observation_hours = max(
            0.0, (max(clean_times) - min(clean_times)).total_seconds() / 3600.0
        )
    else:
        observation_hours = 0.0

    p95_end = _percentile95(accepted_end_ms)
    p95_impact = _percentile95(accepted_impact)
    p95_deterioration = _percentile95(accepted_deterioration)

    attempt_count = len(clean_attempts)
    accepted_count = len(accepted)
    webhook_coverage = (
        100.0 * webhook_covered / attempt_count if attempt_count else 0.0
    )
    accepted_unsigned_coverage = (
        100.0
        * sum(
            bool(_get(row["event"], "fast_transaction_built", False))
            for row in accepted
        )
        / accepted_count
        if accepted_count
        else 0.0
    )

    hard_checks = {
        "observation_span": observation_hours >= float(p["canary_minimum_observation_hours"]),
        "entry_attempts": attempt_count >= int(p["canary_minimum_entry_attempts"]),
        "closed_trades": economics["closed_trades"] >= int(p["canary_minimum_closed_trades"]),
        "webhook_coverage": webhook_coverage >= float(p["canary_minimum_webhook_coverage_percent"]),
        "accepted_unsigned_build_coverage": accepted_unsigned_coverage >= float(p["canary_minimum_unsigned_build_coverage_percent"]),
        "accepted_end_to_quote_p95": (
            p95_end is not None
            and p95_end <= float(p["canary_maximum_p95_end_to_quote_ms"])
        ),
        "accepted_price_deterioration_p95": (
            p95_deterioration is not None
            and p95_deterioration <= float(p["canary_maximum_p95_price_deterioration_bps"])
        ),
        "accepted_price_impact_p95": (
            p95_impact is not None
            and p95_impact <= float(p["canary_maximum_p95_price_impact_bps"])
        ),
        "zero_technical_failures_in_clean_window": len(clean_technical) == 0,
        "zero_unmapped_attempts": len(clean_unmapped) == 0,
        "zero_accepted_policy_violations": len(accepted_policy_violations) == 0,
        "zero_exit_policy_violations": len(exit_policy_violations) == 0,
        "zero_exit_failures": len(clean_exit_failures) == 0,
        "zero_open_positions": open_positions == 0,
    }

    # This is a mathematical positive-expectancy floor, not a replacement for M74.
    economic_floor_checks = {
        "positive_net_pnl": economics["net_pnl_lamports"] > 0,
        "profit_factor_above_one": economics["profit_factor"] > 1.0,
    }

    operational_pass = all(hard_checks.values())
    economic_floor_pass = all(economic_floor_checks.values())
    diagnostic_selective_pass_without_m74 = operational_pass and economic_floor_pass
    formal_m74 = _campaign_formal_m74(campaign)
    would_be_formal_ready_if_armed = (
        formal_m74
        and diagnostic_selective_pass_without_m74
        and SELECTIVE_GATE_FORMAL_ARMED
    )

    return {
        "scope": SELECTIVE_GATE_SCOPE,
        "version": SELECTIVE_GATE_VERSION,
        "state": "DISARMED_SHADOW_EVALUATION",
        "wallet": wallet,
        "campaign_id": str(_get(campaign, "campaign_id", "") or ""),
        "formal_m74_admitted": formal_m74,
        "formal_gate_armed": SELECTIVE_GATE_FORMAL_ARMED,
        "clean_window": {
            "explicit_anchor_utc": explicit_anchor.isoformat() if explicit_anchor else None,
            "last_technical_failure_utc": last_technical_at.isoformat() if last_technical_at else None,
            "effective_anchor_utc": clean_anchor.isoformat() if clean_anchor else None,
            "observation_hours": observation_hours,
            "attempts": attempt_count,
            "accepted": accepted_count,
            "market_protective_rejects": len(market_protective),
            "liquidity_protective_rejects": len(liquidity_protective),
            "technical_failures": len(clean_technical),
            "webhook_coverage_percent": webhook_coverage,
            "accepted_unsigned_build_coverage_percent": accepted_unsigned_coverage,
            "p95_accepted_end_to_quote_ms": p95_end,
            "p95_accepted_price_deterioration_bps": p95_deterioration,
            "p95_accepted_price_impact_bps": p95_impact,
            "open_positions": open_positions,
            "exit_failures": len(clean_exit_failures),
            "accepted_policy_violations": accepted_policy_violations,
            "exit_policy_violations": exit_policy_violations,
        },
        "economics": economics,
        "hard_checks": hard_checks,
        "economic_floor_checks": economic_floor_checks,
        "operational_pass": operational_pass,
        "economic_floor_pass": economic_floor_pass,
        "diagnostic_selective_pass_without_m74": diagnostic_selective_pass_without_m74,
        "would_be_formal_ready_if_armed": would_be_formal_ready_if_armed,
        "formal_selective_pass": False,
        "formal_selective_pass_reason": "M291_DISARMED_NO_FORMAL_CLAIM",
        "legacy_m75_changed": False,
        "m74_bypass": False,
        "protective_reject_rate_is_hard_gate": False,
        "technical_failure_policy": "RESET_CLEAN_WINDOW_AND_REQUALIFY",
        "safety": {
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
            "m74_changed": False,
            "m75_changed": False,
            "pam_changed": False,
        },
    }
