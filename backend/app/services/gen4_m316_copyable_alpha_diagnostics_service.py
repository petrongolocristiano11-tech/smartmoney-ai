from __future__ import annotations

import math
from functools import lru_cache
from datetime import datetime, timezone
from typing import Any

from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
    validate_policy as validate_legacy_m74_m78_policy,
)

M316_VERSION = "canonical-parser-gen4-m316-copyable-alpha-diagnostics/1"
M316_SCOPE = "M316_COPYABLE_ALPHA_DIAGNOSTICS_SHADOW_DISARMED"
M316_SHADOW_FILTER_ARMED = False

M314_VERSION = "m314-candidate-forward-roundtrip-shadow/1"
M314_SCOPE = "M314_CANDIDATE_ROUNDTRIP"
M314_EVIDENCE_KEY = "m314_candidate_roundtrip"
M314_FRESH_ANCHOR_UTC = "2026-09-12T17:26:36.307629+00:00"

MINIMUM_TOTAL_CLOSED_FOR_SPLIT = 20
TRAIN_FRACTION = 0.60
MINIMUM_TRAIN_FILTERED_TRADES = 8
MINIMUM_VALIDATION_FILTERED_TRADES = 5
MINIMUM_PROFIT_FACTOR = 1.30
MAXIMUM_DRAWDOWN_PERCENT = 15.0

DETERIORATION_CAPS_BPS = (250.0, 500.0, 750.0, 1000.0)
IMPACT_CAPS_BPS = (50.0, 100.0, 250.0, 500.0)
LATENCY_CAPS_MS = (500, 1000, 2500, 5000)


class M316CopyableAlphaDiagnosticsError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M316CopyableAlphaDiagnosticsError(message)


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


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _state(row: Any) -> dict[str, Any] | None:
    evidence = dict(_get(row, "evidence", {}) or {})
    state = evidence.get(M314_EVIDENCE_KEY)
    if not isinstance(state, dict):
        return None
    if str(state.get("version") or "") != M314_VERSION:
        return None
    if str(state.get("scope") or "") != M314_SCOPE:
        return None
    return dict(state)


@lru_cache(maxsize=1)
def _starting_capital_lamports() -> int:
    policy = validate_legacy_m74_m78_policy()
    value = float(policy["starting_capital_sol"])
    _require(math.isfinite(value) and value > 0, "M316 starting capital invalido.")
    return int(round(value * 1_000_000_000))


def m316_closed_trade_metrics(states: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [
        dict(state)
        for state in states
        if str(state.get("status") or "") == "CLOSED"
        and state.get("pnl_lamports") is not None
        and state.get("exit_copyable") is True
        and int(state.get("remaining_token_raw") or 0) == 0
    ]
    closed.sort(
        key=lambda state: (
            str(state.get("closed_at") or ""),
            str(state.get("position_id") or ""),
        )
    )
    pnl = [int(state.get("pnl_lamports") or 0) for state in closed]
    gross_profit = sum(value for value in pnl if value > 0)
    gross_loss = abs(sum(value for value in pnl if value < 0))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (999.0 if gross_profit > 0 else 0.0)
    )
    net = sum(pnl)
    best = max(pnl) if pnl else None
    net_without_best = net - best if best is not None else None

    equity = _starting_capital_lamports()
    peak = equity
    maximum_drawdown = 0.0
    maximum_losing_streak = 0
    losing_streak = 0
    wins = 0
    for value in pnl:
        equity += value
        if value > 0:
            wins += 1
            losing_streak = 0
        elif value < 0:
            losing_streak += 1
            maximum_losing_streak = max(maximum_losing_streak, losing_streak)
        else:
            losing_streak = 0
        peak = max(peak, equity)
        drawdown = ((peak - equity) / peak * 100.0) if peak > 0 else 100.0
        maximum_drawdown = max(maximum_drawdown, drawdown)

    return {
        "closed_trade_count": len(closed),
        "net_pnl_lamports": net,
        "net_pnl_sol": net / 1_000_000_000,
        "gross_profit_lamports": gross_profit,
        "gross_loss_lamports": gross_loss,
        "profit_factor": round(profit_factor, 9),
        "best_trade_lamports": best,
        "net_without_best_trade_lamports": net_without_best,
        "maximum_realized_equity_drawdown_percent": round(maximum_drawdown, 9),
        "maximum_losing_closed_streak": maximum_losing_streak,
        "win_rate_percent": round((100.0 * wins / len(closed)) if closed else 0.0, 9),
        "starting_capital_lamports": _starting_capital_lamports(),
        "ending_equity_lamports": equity,
    }


def _entry_features_complete(state: dict[str, Any]) -> bool:
    return (
        _finite(state.get("entry_price_deterioration_bps")) is not None
        and _finite(state.get("entry_price_impact_bps")) is not None
        and state.get("entry_quote_latency_ms") is not None
        and state.get("entry_transaction_built") is True
    )


def _passes_spec(state: dict[str, Any], spec: dict[str, Any]) -> bool:
    if not _entry_features_complete(state):
        return False
    deterioration = float(state["entry_price_deterioration_bps"])
    impact = float(state["entry_price_impact_bps"])
    latency = int(state["entry_quote_latency_ms"])
    return (
        deterioration <= float(spec["max_entry_price_deterioration_bps"])
        and impact <= float(spec["max_entry_price_impact_bps"])
        and latency <= int(spec["max_entry_quote_latency_ms"])
    )


def _metric_pass(metrics: dict[str, Any], *, minimum_trades: int) -> bool:
    return bool(
        int(metrics["closed_trade_count"]) >= int(minimum_trades)
        and int(metrics["net_pnl_lamports"]) > 0
        and float(metrics["profit_factor"]) >= MINIMUM_PROFIT_FACTOR
        and metrics.get("net_without_best_trade_lamports") is not None
        and int(metrics["net_without_best_trade_lamports"]) > 0
        and float(metrics["maximum_realized_equity_drawdown_percent"])
        <= MAXIMUM_DRAWDOWN_PERCENT
    )


def _states_for_wallet(
    wallet: str,
    events: list[Any],
    *,
    terminal: datetime,
) -> list[dict[str, Any]]:
    anchor = _aware(M314_FRESH_ANCHOR_UTC)
    _require(anchor is not None, "M316 M314 anchor invalido.")
    out: list[dict[str, Any]] = []
    for row in events:
        state = _state(row)
        if state is None or str(state.get("wallet_address") or "") != str(wallet):
            continue
        if state.get("strict_forward_only") is not True or state.get("backfill") is not False:
            continue
        entered = _aware(state.get("entry_received_at"))
        if entered is None or entered <= anchor or entered > terminal:
            continue
        out.append(state)
    out.sort(
        key=lambda state: (
            str(state.get("entry_received_at") or ""),
            str(state.get("position_id") or ""),
        )
    )
    return out


def _closed_states(states: list[dict[str, Any]], *, terminal: datetime) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for state in states:
        closed_at = _aware(state.get("closed_at"))
        if (
            str(state.get("status") or "") == "CLOSED"
            and state.get("pnl_lamports") is not None
            and state.get("exit_copyable") is True
            and int(state.get("remaining_token_raw") or 0) == 0
            and closed_at is not None
            and closed_at <= terminal
        ):
            out.append(state)
    out.sort(
        key=lambda state: (
            str(state.get("closed_at") or ""),
            str(state.get("position_id") or ""),
        )
    )
    return out


@lru_cache(maxsize=1)
def _candidate_specs() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "max_entry_price_deterioration_bps": deterioration,
            "max_entry_price_impact_bps": impact,
            "max_entry_quote_latency_ms": latency,
        }
        for deterioration in DETERIORATION_CAPS_BPS
        for impact in IMPACT_CAPS_BPS
        for latency in LATENCY_CAPS_MS
    )


def build_m316_wallet_alpha_diagnostics(
    *,
    wallet: str,
    events: list[Any],
    evaluated_at: datetime | str,
) -> dict[str, Any]:
    target = str(wallet or "").strip()
    _require(bool(target), "M316 wallet mancante.")
    terminal = _aware(evaluated_at)
    _require(terminal is not None, "M316 evaluated_at invalido.")

    states = _states_for_wallet(target, events, terminal=terminal)
    closed = _closed_states(states, terminal=terminal)
    baseline = m316_closed_trade_metrics(closed)
    complete_feature_count = sum(_entry_features_complete(state) for state in closed)
    unique_exit_failures = {
        (str(item.get("signature") or ""), str(item.get("code") or ""))
        for state in states
        for item in list(state.get("exit_failures") or [])
        if isinstance(item, dict)
    }
    open_position_count = sum(
        str(state.get("status") or "") in {"OPEN", "OPEN_PARTIAL"}
        and int(state.get("remaining_token_raw") or 0) > 0
        for state in states
    )

    selected_spec: dict[str, Any] | None = None
    training_metrics: dict[str, Any] | None = None
    validation_metrics: dict[str, Any] | None = None
    training_total = 0
    validation_total = 0
    validation_pass = False
    state_name = "INSUFFICIENT_CLOSED_EVIDENCE"

    if len(closed) >= MINIMUM_TOTAL_CLOSED_FOR_SPLIT:
        split_at = max(12, int(len(closed) * TRAIN_FRACTION))
        split_at = min(split_at, len(closed) - MINIMUM_VALIDATION_FILTERED_TRADES)
        training = closed[:split_at]
        validation = closed[split_at:]
        training_total = len(training)
        validation_total = len(validation)

        candidates: list[tuple[tuple[Any, ...], dict[str, Any], dict[str, Any]]] = []
        for spec in _candidate_specs():
            filtered = [row for row in training if _passes_spec(row, spec)]
            metrics = m316_closed_trade_metrics(filtered)
            if not _metric_pass(metrics, minimum_trades=MINIMUM_TRAIN_FILTERED_TRADES):
                continue
            score = (
                int(metrics["net_without_best_trade_lamports"]),
                int(metrics["net_pnl_lamports"]),
                int(metrics["closed_trade_count"]),
                -float(spec["max_entry_price_deterioration_bps"]),
                -float(spec["max_entry_price_impact_bps"]),
                -int(spec["max_entry_quote_latency_ms"]),
            )
            candidates.append((score, spec, metrics))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            _, selected_spec, training_metrics = candidates[0]
            validation_filtered = [
                row for row in validation if _passes_spec(row, selected_spec)
            ]
            validation_metrics = m316_closed_trade_metrics(validation_filtered)
            validation_economics_pass = _metric_pass(
                validation_metrics,
                minimum_trades=MINIMUM_VALIDATION_FILTERED_TRADES,
            )
            validation_pass = bool(
                validation_economics_pass
                and len(unique_exit_failures) == 0
                and open_position_count == 0
            )
            if validation_pass:
                state_name = "VALIDATED_SHADOW_FILTER_DISARMED"
            elif validation_economics_pass:
                state_name = "FILTER_ECONOMICS_VALIDATED_TECHNICAL_BLOCKER"
            else:
                state_name = "TRAINING_FILTER_FOUND_VALIDATION_NOT_PASS"
        else:
            state_name = "NO_ROBUST_TRAINING_FILTER_FOUND"

    payload: dict[str, Any] = {
        "scope": M316_SCOPE,
        "version": M316_VERSION,
        "wallet": target,
        "evaluated_at_utc": terminal.isoformat(),
        "state": state_name,
        "shadow_filter_armed": False,
        "validated_shadow_filter_pass": validation_pass,
        "selected_filter": selected_spec,
        "evidence": {
            "total_closed_trades": len(closed),
            "complete_pre_entry_feature_trades": complete_feature_count,
            "training_total_trades": training_total,
            "validation_total_trades": validation_total,
            "baseline_metrics": baseline,
            "training_filtered_metrics": training_metrics,
            "validation_filtered_metrics": validation_metrics,
            "open_position_count": open_position_count,
            "technical_exit_failure_count": len(unique_exit_failures),
        },
        "method": {
            "chronological_train_validation_split": True,
            "exact_m314_fresh_anchor_utc": M314_FRESH_ANCHOR_UTC,
            "strict_forward_only": True,
            "zero_backfill_only": True,
            "training_fraction": TRAIN_FRACTION,
            "filter_selection_uses_training_outcomes_only": True,
            "validation_outcomes_never_used_to_select_filter": True,
            "trade_filter_uses_only_pre_entry_features": True,
            "features": [
                "entry_price_deterioration_bps",
                "entry_price_impact_bps",
                "entry_quote_latency_ms",
                "entry_transaction_built",
            ],
            "candidate_grid_size": len(_candidate_specs()),
        },
        "policy": {
            "minimum_total_closed_for_split": MINIMUM_TOTAL_CLOSED_FOR_SPLIT,
            "minimum_train_filtered_trades": MINIMUM_TRAIN_FILTERED_TRADES,
            "minimum_validation_filtered_trades": MINIMUM_VALIDATION_FILTERED_TRADES,
            "minimum_profit_factor": MINIMUM_PROFIT_FACTOR,
            "maximum_drawdown_percent": MAXIMUM_DRAWDOWN_PERCENT,
            "require_positive_net": True,
            "require_positive_net_without_best_trade": True,
            "require_zero_technical_exit_failures_for_validation": True,
            "require_zero_open_positions_for_validation": True,
        },
        "safety": {
            "observation_only": True,
            "automatic_entry_filtering": False,
            "automatic_promotion": False,
            "database_writes": 0,
            "provider_mutation": False,
            "m300_changed": False,
            "m298_changed": False,
            "m307_changed": False,
            "m315_changed": False,
            "live_execution": False,
            "paper_execution": False,
            "signer_access": False,
            "backfill": False,
        },
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload


def build_m316_candidate_alpha_diagnostics(
    *,
    events: list[Any],
    evaluated_at: datetime | str,
) -> dict[str, Any]:
    terminal = _aware(evaluated_at)
    _require(terminal is not None, "M316 evaluated_at invalido.")
    wallets = sorted(
        {
            str(state.get("wallet_address") or "")
            for row in events
            for state in [_state(row)]
            if state is not None and str(state.get("wallet_address") or "")
        }
    )
    by_wallet = {
        wallet: build_m316_wallet_alpha_diagnostics(
            wallet=wallet,
            events=events,
            evaluated_at=terminal,
        )
        for wallet in wallets
    }
    validated = sorted(
        wallet
        for wallet, result in by_wallet.items()
        if result.get("validated_shadow_filter_pass") is True
    )
    payload: dict[str, Any] = {
        "scope": M316_SCOPE,
        "version": M316_VERSION,
        "evaluated_at_utc": terminal.isoformat(),
        "shadow_filter_armed": False,
        "wallet_count": len(wallets),
        "validated_shadow_filter_wallets": validated,
        "wallets": by_wallet,
        "safety": {
            "observation_only": True,
            "automatic_entry_filtering": False,
            "automatic_promotion": False,
            "database_writes": 0,
            "provider_mutation": False,
            "live_execution": False,
            "paper_execution": False,
            "signer_access": False,
            "backfill": False,
        },
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload
