from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
    validate_policy as validate_legacy_m74_m78_policy,
)

M315_EXECUTION_REALITY_GUARD_VERSION = "canonical-parser-gen4-m315-execution-reality-promotion-guard/1"
M315_EXECUTION_REALITY_GUARD_SCOPE = "M315_EXECUTION_REALITY_PROMOTION_GUARD_DISARMED"
M315_EXECUTION_REALITY_GUARD_ARMED = False

M314_CANDIDATE_ROUNDTRIP_VERSION = "m314-candidate-forward-roundtrip-shadow/1"
M314_CANDIDATE_ROUNDTRIP_SCOPE = "M314_CANDIDATE_ROUNDTRIP"
M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY = "m314_candidate_roundtrip"
M314_FRESH_ANCHOR_UTC = "2026-09-12T17:26:36.307629+00:00"

MINIMUM_CLOSED_TRADES = 10
MINIMUM_PROFIT_FACTOR = 1.30
MAXIMUM_DRAWDOWN_PERCENT = 15.0
MAXIMUM_TECHNICAL_EXIT_FAILURES = 0


class M315ExecutionRealityGuardError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M315ExecutionRealityGuardError(message)


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


def _without_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "integrity"}


def _state(row: Any) -> dict[str, Any] | None:
    evidence = dict(_get(row, "evidence", {}) or {})
    value = evidence.get(M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY)
    if not isinstance(value, dict):
        return None
    if str(value.get("version") or "") != M314_CANDIDATE_ROUNDTRIP_VERSION:
        return None
    if str(value.get("scope") or "") != M314_CANDIDATE_ROUNDTRIP_SCOPE:
        return None
    return dict(value)


def _starting_capital_lamports() -> int:
    legacy = validate_legacy_m74_m78_policy()
    value = float(legacy["starting_capital_sol"])
    _require(math.isfinite(value) and value > 0, "M315 starting capital invalido.")
    return int(round(value * 1_000_000_000))


def _realized_equity_drawdown_percent(closed_states: list[dict[str, Any]]) -> float:
    equity = _starting_capital_lamports()
    peak = equity
    maximum = 0.0
    for state in closed_states:
        equity += int(state.get("pnl_lamports") or 0)
        peak = max(peak, equity)
        drawdown = ((peak - equity) / peak * 100.0) if peak > 0 else 100.0
        maximum = max(maximum, drawdown)
    return float(maximum)


def build_m315_execution_reality_guard(
    *,
    wallet: str,
    events: list[Any],
    evaluated_at: datetime | str,
    anchor_utc: datetime | str = M314_FRESH_ANCHOR_UTC,
) -> dict[str, Any]:
    target = str(wallet or "").strip()
    _require(bool(target), "M315 wallet mancante.")
    anchor = _aware(anchor_utc)
    terminal = _aware(evaluated_at)
    _require(anchor is not None, "M315 M314 anchor invalido.")
    _require(terminal is not None and terminal >= anchor, "M315 evaluated_at invalido.")
    _require(anchor.isoformat() == M314_FRESH_ANCHOR_UTC, "M315 richiede exact fresh M314 anchor.")

    entries: list[tuple[Any, dict[str, Any]]] = []
    for row in events:
        state = _state(row)
        if state is None:
            continue
        if str(state.get("wallet_address") or "") != target:
            continue
        received = _aware(state.get("entry_received_at"))
        if received is None or received <= anchor or received > terminal:
            continue
        entries.append((row, state))

    entries.sort(
        key=lambda item: (
            str(item[1].get("entry_received_at") or ""),
            str(_get(item[0], "event_id", "") or ""),
        )
    )
    closed = [
        state
        for _, state in entries
        if str(state.get("status") or "") == "CLOSED"
        and state.get("pnl_lamports") is not None
        and bool(state.get("exit_copyable"))
        and int(state.get("remaining_token_raw") or 0) == 0
    ]
    closed.sort(key=lambda state: (str(state.get("closed_at") or ""), str(state.get("position_id") or "")))

    pnl_values = [int(state.get("pnl_lamports") or 0) for state in closed]
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (999.0 if gross_profit > 0 else 0.0)
    )
    net_pnl = sum(pnl_values)
    best_trade = max(pnl_values) if pnl_values else None
    net_without_best = net_pnl - best_trade if best_trade is not None else None
    drawdown = _realized_equity_drawdown_percent(closed)

    failures = [
        dict(item)
        for _, state in entries
        for item in list(state.get("exit_failures") or [])
        if isinstance(item, dict)
    ]
    unique_failures = {
        (str(item.get("signature") or ""), str(item.get("code") or ""))
        for item in failures
    }
    open_positions = sum(
        str(state.get("status") or "") in {"OPEN", "OPEN_PARTIAL"}
        and int(state.get("remaining_token_raw") or 0) > 0
        for _, state in entries
    )
    strict_forward = all(state.get("strict_forward_only") is True for _, state in entries)
    zero_backfill = all(state.get("backfill") is False for _, state in entries)

    checks = {
        "minimum_closed_trades": len(closed) >= MINIMUM_CLOSED_TRADES,
        "positive_net_pnl": net_pnl > 0,
        "minimum_profit_factor": profit_factor >= MINIMUM_PROFIT_FACTOR,
        "maximum_realized_equity_drawdown": drawdown <= MAXIMUM_DRAWDOWN_PERCENT,
        "positive_net_without_best_trade": net_without_best is not None and net_without_best > 0,
        "zero_technical_exit_failures": len(unique_failures) <= MAXIMUM_TECHNICAL_EXIT_FAILURES,
        "zero_open_positions": open_positions == 0,
        "strict_forward_only": strict_forward,
        "zero_backfill": zero_backfill,
    }
    passed = bool(entries) and all(checks.values())

    payload: dict[str, Any] = {
        "scope": M315_EXECUTION_REALITY_GUARD_SCOPE,
        "version": M315_EXECUTION_REALITY_GUARD_VERSION,
        "wallet": target,
        "m314_anchor_utc": anchor.isoformat(),
        "evaluated_at_utc": terminal.isoformat(),
        "state": "M315_EXECUTION_REALITY_PASS_DISARMED" if passed else "M315_EXECUTION_REALITY_PENDING_OR_FAIL",
        "passed": passed,
        "guard_armed": False,
        "manual_m307_prerequisite_satisfied": passed,
        "metrics": {
            "entry_count": len(entries),
            "open_position_count": open_positions,
            "closed_trade_count": len(closed),
            "net_pnl_lamports": net_pnl,
            "net_pnl_sol": net_pnl / 1_000_000_000,
            "gross_profit_lamports": gross_profit,
            "gross_loss_lamports": gross_loss,
            "profit_factor": round(profit_factor, 9),
            "maximum_realized_equity_drawdown_percent": round(drawdown, 9),
            "best_trade_lamports": best_trade,
            "net_without_best_trade_lamports": net_without_best,
            "technical_exit_failure_count": len(unique_failures),
        },
        "checks": checks,
        "policy": {
            "minimum_closed_trades": MINIMUM_CLOSED_TRADES,
            "minimum_profit_factor": MINIMUM_PROFIT_FACTOR,
            "maximum_drawdown_percent": MAXIMUM_DRAWDOWN_PERCENT,
            "maximum_technical_exit_failures": MAXIMUM_TECHNICAL_EXIT_FAILURES,
            "require_positive_net_pnl": True,
            "require_positive_net_without_best_trade": True,
            "require_zero_open_positions": True,
            "require_strict_forward_only": True,
            "require_zero_backfill": True,
        },
        "safety": {
            "observation_only": True,
            "automatic_promotion": False,
            "database_writes": 0,
            "provider_mutation": False,
            "live_execution": False,
            "paper_execution": False,
            "signer_access": False,
            "m74_changed": False,
            "m75_changed": False,
            "m298_changed": False,
            "m76_changed": False,
            "m77_changed": False,
            "pam_changed": False,
        },
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload


def validate_m315_execution_reality_guard(
    guard: dict[str, Any],
    *,
    expected_wallet: str | None = None,
) -> dict[str, Any]:
    value = dict(guard or {})
    _require(value.get("scope") == M315_EXECUTION_REALITY_GUARD_SCOPE, "M315 guard scope inatteso.")
    _require(value.get("version") == M315_EXECUTION_REALITY_GUARD_VERSION, "M315 guard version inattesa.")
    wallet = str(value.get("wallet") or "")
    _require(bool(wallet), "M315 guard wallet mancante.")
    if expected_wallet is not None:
        _require(wallet == str(expected_wallet), "M315 guard wallet mismatch.")
    _require(str(value.get("m314_anchor_utc") or "") == M314_FRESH_ANCHOR_UTC, "M315 guard M314 anchor drift.")
    _require(_aware(value.get("evaluated_at_utc")) is not None, "M315 guard evaluated_at invalido.")
    _require(value.get("guard_armed") is False, "M315 guard non deve auto-armare promotion.")
    _require(value.get("passed") is True, "M315 execution reality non PASS.")
    _require(value.get("manual_m307_prerequisite_satisfied") is True, "M315 prerequisite M307 non soddisfatto.")
    checks = dict(value.get("checks") or {})
    required_checks = {
        "minimum_closed_trades",
        "positive_net_pnl",
        "minimum_profit_factor",
        "maximum_realized_equity_drawdown",
        "positive_net_without_best_trade",
        "zero_technical_exit_failures",
        "zero_open_positions",
        "strict_forward_only",
        "zero_backfill",
    }
    _require(set(checks) == required_checks, "M315 guard checks incompleti o inattesi.")
    _require(all(checks.get(key) is True for key in required_checks), "M315 guard checks non tutti PASS.")
    safety = dict(value.get("safety") or {})
    _require(safety.get("observation_only") is True, "M315 guard non observation-only.")
    _require(safety.get("automatic_promotion") is False, "M315 guard automatic promotion non false.")
    _require(safety.get("provider_mutation") is False, "M315 guard provider mutation non false.")
    _require(safety.get("live_execution") is False, "M315 guard LIVE non false.")
    _require(safety.get("paper_execution") is False, "M315 guard PAPER non false.")
    _require(safety.get("signer_access") is False, "M315 guard signer non false.")
    integrity = dict(value.get("integrity") or {})
    expected = str(integrity.get("payload_sha256") or "")
    _require(len(expected) == 64 and expected == canonical_sha256(_without_integrity(value)), "M315 guard integrity invalida.")
    return value
