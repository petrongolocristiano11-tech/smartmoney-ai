from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

M74_M78_VERSION = "canonical-parser-gen4-zero-helius-final-pre-micro-live/1"
M74_M78_SCOPE = "M74_M78_ZERO_HELIUS_FINAL_PRE_MICRO_LIVE_CONTROL_PLANE"
M74_M78_PREPARE_CONFIRMATION = "PREPARE_M74_M78_ZERO_HELIUS_FINAL_PRE_MICRO_LIVE"
M74_M78_EVALUATE_CONFIRMATION = "EVALUATE_M74_M78_OFFLINE_POST_DISCOVERY_EVIDENCE"
M72_SCOPE = "M72_DEFINITIVE_DISCOVERY_ROTATION_READ_ONLY"
M72_PLAN_SCOPE = "M72_CONTROLLED_NEW_WALLET_ACQUISITION_PLAN_DISARMED"
M73_SCOPE = "M73_CONTROLLED_NEW_WALLET_ACQUISITION_AND_QUALIFICATION"
M73_VERSION = "canonical-parser-gen4-controlled-new-wallet-qualification/1"
M75_EVIDENCE_SCOPE = "M75_SHORT_REALTIME_CANARY_EVIDENCE"
M75_EVIDENCE_VERSION = "canonical-parser-gen4-short-realtime-canary-evidence/1"
M76_EVIDENCE_SCOPE = "M76_WALLET_INDEPENDENCE_AND_CONSENSUS_EVIDENCE"
M76_EVIDENCE_VERSION = "canonical-parser-gen4-wallet-independence-consensus-evidence/1"
QUALIFIED = "QUALIFIED_PENDING_SHORT_CANARY"

DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": M74_M78_VERSION,
    # M74 economic admission: frozen Gen4 model already used by M67-M73.
    "starting_capital_sol": 1.0,
    "fixed_buy_size_sol": 0.05,
    "slippage_bps": 100,
    "fee_bps": 10,
    "copy_delay_seconds": 8,
    "delay_penalty_bps_per_minute": 25.0,
    "maximum_open_positions": 5,
    "minimum_closed_trades": 100,
    "minimum_history_span_days": 30.0,
    "minimum_profit_factor": 1.30,
    "minimum_recent_closed_trades": 20,
    "minimum_recent_profit_factor": 1.10,
    "minimum_win_rate_percent": 30.0,
    "maximum_drawdown_percent": 15.0,
    # M75 short real-time canary contract frozen by M67-M70.
    "canary_minimum_observation_hours": 24.0,
    "canary_minimum_entry_attempts": 20,
    "canary_minimum_closed_trades": 10,
    "canary_minimum_webhook_coverage_percent": 95.0,
    "canary_minimum_unsigned_build_coverage_percent": 100.0,
    "canary_maximum_entry_reject_rate_percent": 20.0,
    "canary_maximum_p95_end_to_quote_ms": 5000.0,
    "canary_maximum_p95_price_impact_bps": 500.0,
    "canary_maximum_p95_price_deterioration_bps": 1000.0,
    "canary_maximum_worker_failures": 0,
    "canary_maximum_policy_violations": 0,
    "canary_require_zero_open_positions": True,
    "canary_require_zero_unresolved_failures": True,
    # M76 multi-wallet / consensus.
    "minimum_independent_canary_wallets": 2,
    "consensus_window_seconds": 180,
    "consensus_minimum_independent_wallets": 2,
    "consensus_maximum_wallets": 3,
    "consensus_maximum_token_exposure_sol": 0.10,
    # M77 reuses the existing M35 micro-live canary envelope.
    "m35_maximum_total_budget_sol": 0.05,
    "m35_maximum_order_budget_sol": 0.01,
    "m35_maximum_order_count": 3,
    "m35_maximum_validity_minutes": 15,
}

class M74M78Error(RuntimeError):
    pass

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M74M78Error(message)

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

def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif value not in (None, ""):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def _without_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k != "integrity"}

def zero_safety() -> dict[str, Any]:
    return {
        "network_requests": 0,
        "public_rpc_requests": 0,
        "helius_requests": 0,
        "helius_credits": 0,
        "database_reads": 0,
        "database_writes": 0,
        "backend_posts": 0,
        "jupiter_requests": 0,
        "paper_orders": 0,
        "live_orders": 0,
        "signed_transactions": 0,
        "submitted_transactions": 0,
        "signer_access": False,
        "automatic_discovery_activation": False,
        "automatic_canary_activation": False,
        "automatic_live_activation": False,
        "micro_live_execution_authorized": False,
    }

def validate_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    p = {**DEFAULT_POLICY, **dict(policy or {})}
    _require(p.get("policy_version") == M74_M78_VERSION, "Policy M74-M78 inattesa.")
    exact = {
        "slippage_bps": 100,
        "fee_bps": 10,
        "copy_delay_seconds": 8,
        "maximum_open_positions": 5,
        "minimum_closed_trades": 100,
        "minimum_recent_closed_trades": 20,
        "canary_minimum_entry_attempts": 20,
        "canary_minimum_closed_trades": 10,
        "canary_maximum_worker_failures": 0,
        "canary_maximum_policy_violations": 0,
        "minimum_independent_canary_wallets": 2,
        "consensus_window_seconds": 180,
        "consensus_minimum_independent_wallets": 2,
        "consensus_maximum_wallets": 3,
        "m35_maximum_order_count": 3,
        "m35_maximum_validity_minutes": 15,
    }
    for key, expected in exact.items():
        _require(_integer(p.get(key)) == expected, f"Policy alterata: {key}.")
    floats = {
        "starting_capital_sol": 1.0,
        "fixed_buy_size_sol": 0.05,
        "minimum_history_span_days": 30.0,
        "delay_penalty_bps_per_minute": 25.0,
        "minimum_profit_factor": 1.30,
        "minimum_recent_profit_factor": 1.10,
        "minimum_win_rate_percent": 30.0,
        "maximum_drawdown_percent": 15.0,
        "canary_minimum_observation_hours": 24.0,
        "canary_minimum_webhook_coverage_percent": 95.0,
        "canary_minimum_unsigned_build_coverage_percent": 100.0,
        "canary_maximum_entry_reject_rate_percent": 20.0,
        "canary_maximum_p95_end_to_quote_ms": 5000.0,
        "canary_maximum_p95_price_impact_bps": 500.0,
        "canary_maximum_p95_price_deterioration_bps": 1000.0,
        "consensus_maximum_token_exposure_sol": 0.10,
        "m35_maximum_total_budget_sol": 0.05,
        "m35_maximum_order_budget_sol": 0.01,
    }
    for key, expected in floats.items():
        _require(math.isclose(_finite(p.get(key)), expected, rel_tol=0, abs_tol=1e-9), f"Policy alterata: {key}.")
    _require(p.get("canary_require_zero_open_positions") is True, "Policy alterata: canary_require_zero_open_positions.")
    _require(p.get("canary_require_zero_unresolved_failures") is True, "Policy alterata: canary_require_zero_unresolved_failures.")
    return p

def validate_m72_bundle(report: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("evaluation") == "PASS", "Report M72 non PASS.")
    _require(report.get("scope") == M72_SCOPE, "Scope M72 inatteso.")
    _require(plan.get("scope") == M72_PLAN_SCOPE, "Scope piano M72 inatteso.")
    _require(plan.get("state") == "PREPARED_DISARMED", "Piano M72 non disarmato.")
    _require(plan.get("execution_authorized") is False, "Piano M72 gia autorizzato.")
    _require(plan.get("execution_performed") is False, "Piano M72 gia eseguito.")
    decision = dict(report.get("decision") or {})
    _require(decision.get("new_wallet_discovery_required") is True, "M72 non richiede nuova discovery.")
    provider = dict(plan.get("provider") or {})
    _require(_integer(provider.get("maximum_requests")) == 6, "M72 cap richieste inatteso.")
    _require(_integer(provider.get("credit_cap")) == 600, "M72 cap crediti inatteso.")
    _require(_integer(provider.get("retries")) == 0, "M72 retry inatteso.")
    plan_hash = str(dict(plan.get("integrity") or {}).get("plan_payload_sha256") or "")
    _require(len(plan_hash) == 64 and plan_hash == canonical_sha256(_without_integrity(plan)), "Hash piano M72 non valido.")
    embedded = dict(report.get("controlled_acquisition_plan") or {})
    embedded_hash = str(dict(embedded.get("integrity") or {}).get("plan_payload_sha256") or "")
    _require(embedded_hash == plan_hash, "Report/piano M72 non appartengono allo stesso run.")
    return {"plan_payload_sha256": plan_hash, "rotation_summary": dict(report.get("rotation_summary") or {})}

def _signed_report(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["integrity"] = {"report_payload_sha256": canonical_sha256(payload)}
    return payload

def build_preparation_report(report: dict[str, Any], plan: dict[str, Any], *, prepared_at: datetime | None = None) -> dict[str, Any]:
    p = validate_policy()
    m72 = validate_m72_bundle(report, plan)
    now = (prepared_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M74_M78_SCOPE,
        "version": M74_M78_VERSION,
        "mode": "PREPARE_ZERO_NETWORK",
        "prepared_at_utc": now.isoformat(),
        "input": {
            "m72_plan_payload_sha256": m72["plan_payload_sha256"],
            "m72_qualified_pending_short_canary": _integer(m72["rotation_summary"].get("qualified_pending_short_canary")),
            "new_wallet_discovery_required": True,
        },
        "current_state": "AWAITING_HELIUS_RENEWAL_AND_NEW_WALLET_DISCOVERY",
        "m74_candidate_admission": {
            "state": "IMPLEMENTED_AWAITING_M73_SUCCESS_REPORT",
            "source_required": "SUCCESSFUL_M73_NEW_WALLET_QUALIFICATION_REPORT",
            "economic_gate": {
                "minimum_closed_trades": p["minimum_closed_trades"],
                "minimum_profit_factor": p["minimum_profit_factor"],
                "minimum_win_rate_percent": p["minimum_win_rate_percent"],
                "maximum_drawdown_percent": p["maximum_drawdown_percent"],
                "minimum_recent_closed_trades": p["minimum_recent_closed_trades"],
                "minimum_recent_profit_factor": p["minimum_recent_profit_factor"],
            },
            "historical_jupiter_quotes_invented": False,
        },
        "m75_short_realtime_canary": {
            "state": "IMPLEMENTED_DISARMED",
            "minimum_observation_hours": p["canary_minimum_observation_hours"],
            "minimum_entry_attempts": p["canary_minimum_entry_attempts"],
            "minimum_closed_trades": p["canary_minimum_closed_trades"],
            "minimum_webhook_coverage_percent": p["canary_minimum_webhook_coverage_percent"],
            "minimum_unsigned_build_coverage_percent": p["canary_minimum_unsigned_build_coverage_percent"],
            "maximum_entry_reject_rate_percent": p["canary_maximum_entry_reject_rate_percent"],
            "maximum_p95_end_to_quote_ms": p["canary_maximum_p95_end_to_quote_ms"],
            "maximum_p95_price_impact_bps": p["canary_maximum_p95_price_impact_bps"],
            "maximum_p95_price_deterioration_bps": p["canary_maximum_p95_price_deterioration_bps"],
            "maximum_worker_failures": 0,
            "maximum_policy_violations": 0,
            "zero_open_positions_required": True,
            "zero_unresolved_failures_required": True,
            "execution_authorized": False,
        },
        "m76_multi_wallet_consensus": {
            "state": "IMPLEMENTED_DISARMED",
            "minimum_independent_wallets": p["minimum_independent_canary_wallets"],
            "manual_independence_confirmation_required": True,
            "cluster_collision_counts_as_consensus": False,
            "consensus_window_seconds": p["consensus_window_seconds"],
            "consensus_minimum_independent_wallets": p["consensus_minimum_independent_wallets"],
            "consensus_maximum_wallets": p["consensus_maximum_wallets"],
            "consensus_maximum_token_exposure_sol": p["consensus_maximum_token_exposure_sol"],
        },
        "m77_micro_live_envelope": {
            "state": "IMPLEMENTED_DISARMED_REUSES_M35",
            "maximum_total_budget_sol": p["m35_maximum_total_budget_sol"],
            "maximum_order_budget_sol": p["m35_maximum_order_budget_sol"],
            "maximum_order_count": p["m35_maximum_order_count"],
            "maximum_validity_minutes": p["m35_maximum_validity_minutes"],
            "signer_connected": False,
            "live_engine_connected": False,
            "external_requests_allowed": False,
            "execution_authorized": False,
        },
        "m78_final_transition": {
            "state": "IMPLEMENTED_AWAITING_REAL_EVIDENCE",
            "required_before_ready": [
                "M73_SUCCESSFUL_NEW_WALLET_DISCOVERY_AND_GEN4_QUALIFICATION",
                "AT_LEAST_TWO_INDEPENDENT_WALLETS_QUALIFIED",
                "SHORT_REALTIME_CANARY_PASS_FOR_AT_LEAST_TWO_INDEPENDENT_WALLETS",
                "EXPLICIT_MANUAL_INDEPENDENCE_CONFIRMATION",
                "EXPLICIT_MICRO_LIVE_AUTHORIZATION",
            ],
            "automatic_live_activation": False,
            "micro_live_ready": False,
            "micro_live_execution_authorized": False,
        },
        "post_renewal_path": [
            "RUN_CONTROLLED_NEW_WALLET_DISCOVERY",
            "QUALIFY_NEW_WALLETS_GEN4",
            "COLLECT_SHORT_REALTIME_CANARY",
            "CONFIRM_WALLET_INDEPENDENCE",
            "EVALUATE_M74_M78_OFFLINE_EVIDENCE",
            "EXPLICIT_MICRO_LIVE_AUTHORIZATION_IF_READY",
        ],
        "safety": zero_safety(),
    }
    return _signed_report(payload)

def _metrics_from_candidate(candidate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    economic = dict(candidate.get("economic_analysis") or {})
    metrics = dict(economic.get("metrics") or candidate.get("metrics") or {})
    recent = dict(economic.get("recent_metrics") or candidate.get("recent_metrics") or {})
    return metrics, recent

def evaluate_m74_candidate(candidate: dict[str, Any], *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    p = validate_policy(policy)
    metrics, recent = _metrics_from_candidate(candidate)
    economic_checks = dict((candidate.get("economic_analysis") or {}).get("checks") or {})
    checks = {
        "m73_disposition": candidate.get("disposition") == QUALIFIED,
        "m73_economic_gate_passed": (candidate.get("economic_analysis") or {}).get("economic_gate_passed") is True,
        "m73_all_economic_checks_passed": bool(economic_checks) and all(bool(value) for value in economic_checks.values()),
        "closed_sample": _integer(metrics.get("closed_trade_count", candidate.get("closed_trade_count"))) >= p["minimum_closed_trades"],
        "history_span": _finite(metrics.get("history_span_days", candidate.get("history_span_days"))) >= p["minimum_history_span_days"],
        "net_pnl": _finite(metrics.get("net_pnl_sol")) > 0,
        "profit_factor": _finite(metrics.get("profit_factor")) >= p["minimum_profit_factor"],
        "win_rate": _finite(metrics.get("win_rate_percent")) >= p["minimum_win_rate_percent"],
        "drawdown": _finite(metrics.get("maximum_drawdown_percent"), 100.0) <= p["maximum_drawdown_percent"],
        "recent_sample": _integer(recent.get("closed_trade_count")) >= p["minimum_recent_closed_trades"],
        "recent_profit_factor": _finite(recent.get("profit_factor")) >= p["minimum_recent_profit_factor"],
        "history_complete": bool(candidate.get("history_complete")),
        "zero_open_positions": _integer(candidate.get("open_positions", metrics.get("open_positions"))) == 0,
    }
    passed = all(checks.values())
    return {
        "wallet_address": str(candidate.get("wallet_address") or ""),
        "passed": passed,
        "state": "ADMITTED_TO_SHORT_CANARY" if passed else "NOT_ADMITTED",
        "checks": checks,
        "short_canary_execution_authorized": False,
        "micro_live_execution_authorized": False,
    }

def _percentile95(values: Iterable[float]) -> float:
    vals = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not vals:
        return 0.0
    index = max(0, math.ceil(len(vals) * 0.95) - 1)
    return vals[index]

def evaluate_m75_canary(wallet: str, records: list[dict[str, Any]], *, admitted: bool, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    p = validate_policy(policy)
    timestamps = [dt for dt in (_aware(r.get("timestamp_utc")) for r in records) if dt is not None]
    span_h = ((max(timestamps) - min(timestamps)).total_seconds() / 3600.0) if len(timestamps) >= 2 else 0.0
    entries = [r for r in records if str(r.get("event_type") or "").upper() == "ENTRY_ATTEMPT"]
    closes = [r for r in records if str(r.get("event_type") or "").upper() == "CLOSED_TRADE"]
    terminal = [r for r in records if str(r.get("event_type") or "").upper() == "CANARY_TERMINAL_STATE"]
    terminal_exact = len(terminal) == 1
    terminal_row = terminal[0] if terminal_exact else {}
    open_position_count = _integer(terminal_row.get("open_position_count"), -1)
    unresolved_failure_count = _integer(terminal_row.get("unresolved_failure_count"), -1)
    webhook = sum(bool(r.get("webhook_covered")) for r in entries)
    unsigned = sum(bool(r.get("unsigned_build_success")) for r in entries)
    rejected = sum(bool(r.get("entry_rejected")) for r in entries)
    worker_failures = sum(bool(r.get("worker_failure")) for r in records)
    violations = sum(bool(r.get("policy_violation")) for r in records)
    n = len(entries)
    webhook_pct = webhook / n * 100.0 if n else 0.0
    unsigned_pct = unsigned / n * 100.0 if n else 0.0
    reject_pct = rejected / n * 100.0 if n else 100.0
    p95_quote = _percentile95(_finite(r.get("end_to_quote_ms")) for r in entries)
    p95_impact = _percentile95(_finite(r.get("price_impact_bps")) for r in entries)
    p95_deterioration = _percentile95(_finite(r.get("price_deterioration_bps")) for r in entries)
    checks = {
        "m74_admitted": admitted,
        "observation_hours": span_h >= p["canary_minimum_observation_hours"],
        "entry_attempts": n >= p["canary_minimum_entry_attempts"],
        "closed_trades": len(closes) >= p["canary_minimum_closed_trades"],
        "webhook_coverage": webhook_pct >= p["canary_minimum_webhook_coverage_percent"],
        "unsigned_build_coverage": unsigned_pct >= p["canary_minimum_unsigned_build_coverage_percent"],
        "entry_reject_rate": reject_pct <= p["canary_maximum_entry_reject_rate_percent"],
        "end_to_quote_p95": p95_quote <= p["canary_maximum_p95_end_to_quote_ms"],
        "price_impact_p95": p95_impact <= p["canary_maximum_p95_price_impact_bps"],
        "price_deterioration_p95": p95_deterioration <= p["canary_maximum_p95_price_deterioration_bps"],
        "worker_failures": worker_failures <= p["canary_maximum_worker_failures"],
        "policy_violations": violations <= p["canary_maximum_policy_violations"],
        "terminal_state_exact": terminal_exact,
        "zero_open_positions": open_position_count == 0 if p["canary_require_zero_open_positions"] else True,
        "zero_unresolved_failures": unresolved_failure_count == 0 if p["canary_require_zero_unresolved_failures"] else True,
    }
    passed = all(checks.values())
    return {
        "wallet_address": wallet,
        "passed": passed,
        "state": "SHORT_CANARY_PASS" if passed else "SHORT_CANARY_PENDING_OR_FAIL",
        "metrics": {
            "observation_hours": round(span_h, 6),
            "entry_attempts": n,
            "closed_trades": len(closes),
            "webhook_coverage_percent": round(webhook_pct, 6),
            "unsigned_build_coverage_percent": round(unsigned_pct, 6),
            "entry_reject_rate_percent": round(reject_pct, 6),
            "p95_end_to_quote_ms": round(p95_quote, 6),
            "p95_price_impact_bps": round(p95_impact, 6),
            "p95_price_deterioration_bps": round(p95_deterioration, 6),
            "worker_failures": worker_failures,
            "policy_violations": violations,
            "terminal_state_count": len(terminal),
            "open_position_count": open_position_count,
            "unresolved_failure_count": unresolved_failure_count,
        },
        "checks": checks,
        "micro_live_execution_authorized": False,
    }

def evaluate_m76_independence(canary_pass_wallets: list[str], confirmations: list[dict[str, Any]], *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    p = validate_policy(policy)
    by_wallet = {str(r.get("wallet_address") or ""): r for r in confirmations}
    rows = []
    clusters: set[str] = set()
    for wallet in sorted(set(canary_pass_wallets)):
        row = dict(by_wallet.get(wallet) or {})
        confirmed = row.get("independence_confirmed") is True
        cluster = str(row.get("cluster_id") or "").strip()
        valid = confirmed and bool(cluster)
        if valid: clusters.add(cluster)
        rows.append({"wallet_address": wallet, "independence_confirmed": confirmed, "cluster_id": cluster or None, "valid": valid})
    all_confirmed = bool(rows) and all(r["valid"] for r in rows)
    distinct = len(clusters) == len(rows) if rows else False
    enough = len(rows) >= p["minimum_independent_canary_wallets"]
    passed = all_confirmed and distinct and enough
    return {
        "passed": passed,
        "state": "INDEPENDENT_MULTI_WALLET_POOL_READY" if passed else "INDEPENDENCE_PENDING_OR_FAIL",
        "wallets": rows,
        "minimum_independent_wallets": p["minimum_independent_canary_wallets"],
        "distinct_cluster_count": len(clusters),
        "cluster_collision_deduplication": True,
        "manual_confirmation_required": True,
    }

def build_m76_consensus_signals(events: list[dict[str, Any]], confirmations: list[dict[str, Any]], *, policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    p = validate_policy(policy)
    clusters = {str(r.get("wallet_address") or ""): str(r.get("cluster_id") or "") for r in confirmations if r.get("independence_confirmed") is True}
    buys = []
    for event in events:
        if str(event.get("side") or "").upper() != "BUY": continue
        wallet = str(event.get("wallet_address") or "")
        token = str(event.get("token_mint") or "")
        ts = _aware(event.get("timestamp_utc"))
        cluster = clusters.get(wallet, "")
        if wallet and token and ts and cluster:
            buys.append((token, ts, wallet, cluster, max(0.0, _finite(event.get("requested_size_sol")))))
    buys.sort(key=lambda x: (x[0], x[1], x[2]))
    signals: list[dict[str, Any]] = []
    for i, (token, start, *_rest) in enumerate(buys):
        window = [x for x in buys[i:] if x[0] == token and 0 <= (x[1] - start).total_seconds() <= p["consensus_window_seconds"]]
        chosen: dict[str, tuple] = {}
        for row in window:
            chosen.setdefault(row[3], row)
        selected = list(chosen.values())[:p["consensus_maximum_wallets"]]
        if len(selected) < p["consensus_minimum_independent_wallets"]: continue
        exposure = sum(x[4] for x in selected)
        if exposure > p["consensus_maximum_token_exposure_sol"] + 1e-12: continue
        signals.append({
            "token_mint": token,
            "window_start_utc": start.isoformat(),
            "window_seconds": p["consensus_window_seconds"],
            "independent_wallet_count": len(selected),
            "wallets": [x[2] for x in selected],
            "cluster_ids": [x[3] for x in selected],
            "requested_exposure_sol": round(exposure, 9),
            "runtime_execution_authorized": False,
        })
    unique = {canonical_sha256(s): s for s in signals}
    return list(unique.values())

def _validate_future_m73(report: dict[str, Any]) -> None:
    _require(report.get("evaluation") == "PASS", "Report M73 futuro non PASS.")
    _require(report.get("scope") == M73_SCOPE, "Scope M73 futuro inatteso.")
    _require(report.get("version") == M73_VERSION, "Versione M73 futura inattesa.")
    integrity = dict(report.get("integrity") or {})
    expected = str(integrity.get("report_payload_sha256") or "")
    _require(len(expected) == 64 and expected == canonical_sha256(_without_integrity(report)), "Hash report M73 futuro non valido.")
    safety = dict(report.get("safety") or {})
    _require(_integer(safety.get("helius_request_cap")) == 6, "M73 cap Helius inatteso.")
    _require(_integer(safety.get("helius_credit_cap")) == 600, "M73 cap crediti inatteso.")
    _require(_integer(safety.get("helius_retries")) == 0, "M73 retry inatteso.")
    _require(safety.get("automatic_enhanced_api") is False, "M73 Enhanced automatico attivo.")
    _require(safety.get("official_realtime_counter_mutated") is False, "M73 ha mutato il counter ufficiale.")
    _require(_integer(safety.get("paper_orders")) == 0, "M73 contiene ordini paper.")
    _require(_integer(safety.get("live_orders")) == 0, "M73 contiene ordini LIVE.")
    _require(safety.get("signer_authorized") is False, "M73 ha signer autorizzato.")

def _validate_evidence(payload: dict[str, Any], *, scope: str, version: str, label: str) -> None:
    _require(payload.get("scope") == scope, f"Scope {label} inatteso.")
    _require(payload.get("version") == version, f"Versione {label} inattesa.")
    integrity = dict(payload.get("integrity") or {})
    expected = str(integrity.get("payload_sha256") or "")
    _require(len(expected) == 64 and expected == canonical_sha256(_without_integrity(payload)), f"Hash {label} non valido.")

def sign_canary_evidence(wallet_records: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scope": M75_EVIDENCE_SCOPE,
        "version": M75_EVIDENCE_VERSION,
        "wallet_records": wallet_records,
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload

def sign_independence_evidence(confirmations: list[dict[str, Any]], consensus_observations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scope": M76_EVIDENCE_SCOPE,
        "version": M76_EVIDENCE_VERSION,
        "confirmations": confirmations,
        "consensus_observations": list(consensus_observations or []),
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload

def evaluate_post_discovery(
    m72_report: dict[str, Any],
    m72_plan: dict[str, Any],
    m73_report: dict[str, Any],
    canary_evidence: dict[str, Any],
    independence_evidence: dict[str, Any],
    *,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    p = validate_policy()
    validate_m72_bundle(m72_report, m72_plan)
    _validate_future_m73(m73_report)
    _validate_evidence(canary_evidence, scope=M75_EVIDENCE_SCOPE, version=M75_EVIDENCE_VERSION, label="M75")
    _validate_evidence(independence_evidence, scope=M76_EVIDENCE_SCOPE, version=M76_EVIDENCE_VERSION, label="M76")
    candidate_rows = [dict(x) for x in m73_report.get("candidate_results") or []]
    m74 = [evaluate_m74_candidate(x, policy=p) for x in candidate_rows]
    admitted = {x["wallet_address"] for x in m74 if x["passed"]}
    evidence_rows = dict(canary_evidence.get("wallet_records") or {})
    m75 = [evaluate_m75_canary(w, [dict(x) for x in evidence_rows.get(w, [])], admitted=w in admitted, policy=p) for w in sorted(admitted)]
    passed_wallets = [x["wallet_address"] for x in m75 if x["passed"]]
    confirmations = [dict(x) for x in independence_evidence.get("confirmations") or []]
    passed_set = set(passed_wallets)
    eligible_confirmations = [row for row in confirmations if str(row.get("wallet_address") or "") in passed_set]
    m76 = evaluate_m76_independence(passed_wallets, eligible_confirmations, policy=p)
    consensus_events = [dict(x) for x in independence_evidence.get("consensus_observations") or [] if str(x.get("wallet_address") or "") in passed_set]
    consensus = build_m76_consensus_signals(consensus_events, eligible_confirmations, policy=p)
    ready = len(passed_wallets) >= p["minimum_independent_canary_wallets"] and m76["passed"]
    now = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M74_M78_SCOPE,
        "version": M74_M78_VERSION,
        "mode": "EVALUATE_OFFLINE_POST_DISCOVERY_EVIDENCE",
        "evaluated_at_utc": now.isoformat(),
        "m74_candidate_admission": m74,
        "m75_short_realtime_canary": m75,
        "m76_independence": m76,
        "m76_consensus_signals": consensus,
        "m77_micro_live_envelope": {
            "maximum_total_budget_sol": p["m35_maximum_total_budget_sol"],
            "maximum_order_budget_sol": p["m35_maximum_order_budget_sol"],
            "maximum_order_count": p["m35_maximum_order_count"],
            "maximum_validity_minutes": p["m35_maximum_validity_minutes"],
            "reuses_existing_m35_governance": True,
            "signer_connected": False,
            "live_engine_connected": False,
            "execution_authorized": False,
        },
        "m78_final_transition": {
            "micro_live_ready": ready,
            "state": "READY_FOR_EXPLICIT_MICRO_LIVE_AUTHORIZATION" if ready else "NOT_READY_WAITING_REAL_EVIDENCE",
            "qualified_wallets": len(admitted),
            "short_canary_pass_wallets": len(passed_wallets),
            "independent_wallets_ready": m76["passed"],
            "automatic_live_activation": False,
            "micro_live_execution_authorized": False,
            "signer_authorized": False,
        },
        "safety": zero_safety(),
    }
    return _signed_report(payload)

def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("evaluation") == "PASS", "Report M74-M78 non PASS.")
    _require(report.get("scope") == M74_M78_SCOPE, "Scope M74-M78 inatteso.")
    _require(report.get("version") == M74_M78_VERSION, "Versione M74-M78 inattesa.")
    integrity = dict(report.get("integrity") or {})
    expected = str(integrity.get("report_payload_sha256") or "")
    _require(len(expected) == 64 and expected == canonical_sha256(_without_integrity(report)), "Hash report M74-M78 non valido.")
    safety = dict(report.get("safety") or {})
    for key in ("network_requests", "public_rpc_requests", "helius_requests", "helius_credits", "database_reads", "database_writes", "backend_posts", "jupiter_requests", "paper_orders", "live_orders", "signed_transactions", "submitted_transactions"):
        _require(_integer(safety.get(key)) == 0, f"Safety M74-M78 violata: {key}.")
    _require(safety.get("signer_access") is False, "Signer M74-M78 non disarmato.")
    _require(safety.get("micro_live_execution_authorized") is False, "M74-M78 ha autorizzato Micro Live.")
    return report
