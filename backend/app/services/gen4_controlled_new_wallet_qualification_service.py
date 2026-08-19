from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable


M73_VERSION = "canonical-parser-gen4-controlled-new-wallet-qualification/1"
M73_SCOPE = "M73_CONTROLLED_NEW_WALLET_ACQUISITION_AND_QUALIFICATION"
M73_RUN_CONFIRMATION = "EXECUTE_M73_DISCOVERY_TRANCHE_MAX_9000_HELIUS_CREDITS"
M66_HELIUS_CONFIRMATION = "SPEND_MAX_9000_HELIUS_CREDITS_FOR_M66_DISCOVERY_TRANCHE"
M73_MAX_HELIUS_REQUESTS = 90
M73_MAX_HELIUS_CREDITS = 9_000
M73_HELIUS_RETRIES = 0
M73_MAX_PUBLIC_RPC_REQUESTS = 5_000
M73_MAX_DEEP_CANDIDATES = 8
M73_MAX_SIGNATURES_PER_CANDIDATE = 500
M73_DEFAULT_PUBLIC_RPC_REQUESTS = 4_000
M73_DEFAULT_DEEP_CANDIDATES = 6

DISPOSITION_QUALIFIED = "QUALIFIED_PENDING_SHORT_CANARY"
DISPOSITION_OBSERVE = "OBSERVE_ONLY"
DISPOSITION_RESEARCH = "RESEARCH_ONLY"
DISPOSITION_REJECT = "REJECTED_FROM_PROMOTION"

_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_WALLET_KEYS = {
    "wallet",
    "wallet_address",
    "walletaddress",
    "candidate_wallet",
    "candidate_wallet_address",
    "candidate_address",
    "trader_wallet",
    "owner_wallet",
    "source_wallet",
}
_SCORE_KEYS = (
    "copyability_score",
    "candidate_score",
    "activity_score",
    "quality_score",
    "smart_score",
    "score",
)


class M73ControlledQualificationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M73ControlledQualificationError(message)


def _integer(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _finite(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _without_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "integrity"}


def validate_runtime_limits(
    *,
    helius_requests: int = M73_MAX_HELIUS_REQUESTS,
    helius_credits: int = M73_MAX_HELIUS_CREDITS,
    helius_retries: int = M73_HELIUS_RETRIES,
    public_rpc_requests: int = M73_MAX_PUBLIC_RPC_REQUESTS,
    deep_candidates: int = M73_MAX_DEEP_CANDIDATES,
    signatures_per_candidate: int = M73_MAX_SIGNATURES_PER_CANDIDATE,
) -> dict[str, int]:
    resolved = {
        "helius_requests": max(0, min(int(helius_requests), M73_MAX_HELIUS_REQUESTS)),
        "helius_credits": max(0, min(int(helius_credits), M73_MAX_HELIUS_CREDITS)),
        "helius_retries": max(0, min(int(helius_retries), M73_HELIUS_RETRIES)),
        "public_rpc_requests": max(
            30, min(int(public_rpc_requests), M73_MAX_PUBLIC_RPC_REQUESTS)
        ),
        "deep_candidates": max(1, min(int(deep_candidates), M73_MAX_DEEP_CANDIDATES)),
        "signatures_per_candidate": max(
            100,
            min(int(signatures_per_candidate), M73_MAX_SIGNATURES_PER_CANDIDATE),
        ),
    }
    _require(resolved["helius_requests"] <= 90, "Cap Helius M73 > 90 richieste.")
    _require(resolved["helius_credits"] <= 9_000, "Cap Helius M73 > 9000 crediti.")
    _require(resolved["helius_retries"] == 0, "M73 non consente retry Helius.")
    _require(resolved["public_rpc_requests"] <= 5_000, "Cap RPC M73 > 5000.")
    _require(resolved["deep_candidates"] <= 8, "M73 analizza al massimo 8 candidati.")
    _require(
        resolved["signatures_per_candidate"] <= 500,
        "M73 analizza al massimo 500 firme per candidato.",
    )
    return resolved


def validate_m72_authorization(
    rotation_report: dict[str, Any],
    acquisition_plan: dict[str, Any],
) -> dict[str, Any]:
    _require(
        str(rotation_report.get("evaluation") or "") == "PASS",
        "Report M72 non PASS.",
    )
    _require(
        str(rotation_report.get("scope") or "")
        == "M72_DEFINITIVE_DISCOVERY_ROTATION_READ_ONLY",
        "Scope report M72 inatteso.",
    )
    decision = dict(rotation_report.get("decision") or {})
    _require(
        decision.get("new_wallet_discovery_required") is True,
        "M72 non richiede nuova discovery.",
    )
    _require(
        decision.get("controlled_discovery_execution_authorized") is False,
        "Report M72 inatteso: discovery risultava già autorizzata.",
    )
    _require(
        str(acquisition_plan.get("state") or "") == "PREPARED_DISARMED",
        "Piano M72 non disarmato.",
    )
    _require(
        acquisition_plan.get("execution_authorized") is False
        and acquisition_plan.get("execution_performed") is False,
        "Piano M72 risulta già eseguito/autorizzato.",
    )
    provider = dict(acquisition_plan.get("provider") or {})
    _require(_integer(provider.get("maximum_requests")) == 6, "Piano M72 legacy cap != 6.")
    _require(_integer(provider.get("credit_cap")) == 600, "Piano M72 legacy crediti != 600.")
    _require(_integer(provider.get("retries")) == 0, "Piano M72 retry != 0.")
    expected = str(dict(acquisition_plan.get("integrity") or {}).get("plan_payload_sha256") or "")
    _require(
        len(expected) == 64
        and expected == canonical_sha256(_without_integrity(acquisition_plan)),
        "Hash piano M72 non valido.",
    )
    embedded = dict(rotation_report.get("controlled_acquisition_plan") or {})
    embedded_hash = str(dict(embedded.get("integrity") or {}).get("plan_payload_sha256") or "")
    _require(embedded_hash == expected, "Report M72 e piano M72 non appartengono allo stesso run.")
    return {
        "plan_payload_sha256": expected,
        "active_wallets_reviewed": _integer(
            dict(rotation_report.get("rotation_summary") or {}).get("active_wallets_reviewed")
        ),
        "legacy_m72_maximum_requests": 6,
        "legacy_m72_credit_cap": 600,
        "expanded_budget_requires_new_runtime_confirmation": True,
    }


def known_m72_wallets(rotation_report: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("wallet_rotation", "research_only_locked"):
        for item in rotation_report.get(key) or []:
            if isinstance(item, dict):
                wallet = str(item.get("wallet_address") or "")
                if _SOLANA_ADDRESS.fullmatch(wallet):
                    values.add(wallet)
    return values


def choose_seed_wallet(rotation_report: dict[str, Any]) -> str:
    rows: list[dict[str, Any]] = []
    for item in rotation_report.get("wallet_rotation") or []:
        if not isinstance(item, dict) or item.get("disposition") != "OBSERVE_ONLY":
            continue
        wallet = str(item.get("wallet_address") or "")
        if not _SOLANA_ADDRESS.fullmatch(wallet):
            continue
        transactions = max(1, _integer(item.get("transaction_count")))
        parsed = _integer(item.get("parsed_event_count"))
        rows.append(
            {
                "wallet": wallet,
                "closed": _integer(item.get("closed_trade_count")),
                "buy": _integer(item.get("buy_events")),
                "parser_yield": parsed / transactions,
            }
        )
    _require(rows, "M72 non contiene un wallet OBSERVE_ONLY utilizzabile come seed.")
    rows.sort(
        key=lambda item: (
            -item["closed"],
            -item["buy"],
            -item["parser_yield"],
            item["wallet"],
        )
    )
    return str(rows[0]["wallet"])


def _candidate_score(record: dict[str, Any]) -> float:
    for key in _SCORE_KEYS:
        if key in record:
            return _finite(record.get(key), default=0.0)
    return 0.0


def extract_m66_candidates(
    documents: Iterable[tuple[str, Any]],
    *,
    excluded_wallets: set[str],
    maximum_candidates: int = 80,
) -> list[dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}

    def visit(value: Any, *, source: str, path: str) -> None:
        if isinstance(value, dict):
            normalized = {str(key).lower(): item for key, item in value.items()}
            for key, item in normalized.items():
                if key not in _WALLET_KEYS or not isinstance(item, str):
                    continue
                wallet = item.strip()
                if not _SOLANA_ADDRESS.fullmatch(wallet) or wallet in excluded_wallets:
                    continue
                row = evidence.setdefault(
                    wallet,
                    {
                        "wallet_address": wallet,
                        "prescreen_score": 0.0,
                        "evidence_hits": 0,
                        "sources": set(),
                        "paths": set(),
                    },
                )
                row["prescreen_score"] = max(
                    _finite(row.get("prescreen_score")),
                    _candidate_score(value),
                )
                row["evidence_hits"] = _integer(row.get("evidence_hits")) + 1
                row["sources"].add(source)
                row["paths"].add(f"{path}.{key}" if path else key)
            for key, item in value.items():
                visit(item, source=source, path=f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, source=source, path=f"{path}[{index}]")

    for source, document in documents:
        visit(document, source=str(source), path="")

    rows = []
    for row in evidence.values():
        rows.append(
            {
                **{key: value for key, value in row.items() if key not in {"sources", "paths"}},
                "sources": sorted(row["sources"]),
                "paths": sorted(row["paths"])[:20],
            }
        )
    rows.sort(
        key=lambda item: (
            -_finite(item.get("prescreen_score")),
            -_integer(item.get("evidence_hits")),
            str(item.get("wallet_address")),
        )
    )
    return rows[: max(1, min(int(maximum_candidates), 80))]


def classify_deep_candidate(
    candidate: dict[str, Any],
    deep_history: dict[str, Any],
    economic_analysis: dict[str, Any] | None,
    *,
    minimum_parser_yield_percent: float = 10.0,
) -> dict[str, Any]:
    wallet = str(candidate.get("wallet_address") or deep_history.get("wallet_address") or "")
    _require(_SOLANA_ADDRESS.fullmatch(wallet) is not None, "Wallet candidato M73 non valido.")
    transactions = _integer(deep_history.get("transaction_count"))
    parsed_events = _integer(deep_history.get("parsed_event_count"))
    parser_yield = (parsed_events / transactions * 100.0) if transactions else 0.0
    backtest = dict(deep_history.get("backtest") or {})
    metrics = dict(backtest.get("metrics") or {})
    buys = _integer(metrics.get("buy_signals"))
    sells = _integer(metrics.get("sell_signals"))
    closed = _integer(metrics.get("closed_trade_count"))
    open_positions = _integer(metrics.get("open_positions"))
    history_complete = bool(deep_history.get("history_complete"))
    economic = dict(economic_analysis or {})
    gate_passed = bool(economic.get("economic_gate_passed"))

    if not history_complete:
        disposition = DISPOSITION_OBSERVE
        reason = "NEEDS_MORE_PUBLIC_RPC_HISTORY"
    elif buys == 0 and sells >= 5:
        disposition = DISPOSITION_REJECT
        reason = "COMPLETE_HISTORY_NON_COPYABLE_SELL_ONLY"
    elif transactions >= 50 and parser_yield < float(minimum_parser_yield_percent):
        disposition = DISPOSITION_REJECT
        reason = "COMPLETE_HISTORY_LOW_CANONICAL_PARSER_YIELD"
    elif closed >= 100 and gate_passed:
        disposition = DISPOSITION_QUALIFIED
        reason = "GEN4_PUBLIC_RPC_ECONOMIC_GATE_PASS"
    elif closed >= 100:
        disposition = DISPOSITION_RESEARCH
        reason = "GEN4_PUBLIC_RPC_ECONOMIC_GATE_FAIL"
    else:
        disposition = DISPOSITION_OBSERVE
        reason = "COMPLETE_HISTORY_INSUFFICIENT_CLOSED_SAMPLE"

    return {
        "wallet_address": wallet,
        "disposition": disposition,
        "reason": reason,
        "prescreen_score": _finite(candidate.get("prescreen_score")),
        "evidence_hits": _integer(candidate.get("evidence_hits")),
        "history_complete": history_complete,
        "signature_count": _integer(deep_history.get("signature_count")),
        "transaction_count": transactions,
        "parsed_event_count": parsed_events,
        "parser_yield_percent": round(parser_yield, 8),
        "buy_events": buys,
        "sell_events": sells,
        "closed_trade_count": closed,
        "open_positions": open_positions,
        "economic_analysis": economic or None,
        "short_canary_required": disposition == DISPOSITION_QUALIFIED,
        "independence_confirmation_required": disposition == DISPOSITION_QUALIFIED,
        "micro_live_execution_authorized": False,
    }


def build_m73_report(
    *,
    m72_report_sha256: str,
    m72_plan_sha256: str,
    seed_wallet: str,
    m66_files: list[dict[str, Any]],
    discovered_candidates: list[dict[str, Any]],
    evaluated_candidates: list[dict[str, Any]],
    helius_accounting: dict[str, Any],
    public_rpc_stats: dict[str, Any],
    limits: dict[str, int],
    cache_payload_sha256: str,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    counts = defaultdict(int)
    for item in evaluated_candidates:
        counts[str(item.get("disposition") or "UNKNOWN")] += 1
    qualified = [
        dict(item)
        for item in evaluated_candidates
        if item.get("disposition") == DISPOSITION_QUALIFIED
    ]
    report: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M73_SCOPE,
        "version": M73_VERSION,
        "evaluated_at_utc": (evaluated_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        ).isoformat(),
        "inputs": {
            "m72_report_sha256": m72_report_sha256,
            "m72_plan_sha256": m72_plan_sha256,
            "m66_controlled_outputs": m66_files,
            "public_rpc_cache_payload_sha256": cache_payload_sha256,
        },
        "limits": limits,
        "acquisition": {
            "seed_wallet": seed_wallet,
            "provider_lane": "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY_MANUAL_ONLY",
            "m66_confirmation": M66_HELIUS_CONFIRMATION,
            "candidate_count_before_deep_scan": len(discovered_candidates),
            "selected_for_deep_scan": len(evaluated_candidates),
            "helius_accounting": helius_accounting,
        },
        "candidate_prescreen": discovered_candidates,
        "candidate_results": evaluated_candidates,
        "summary": {
            "candidates_discovered": len(discovered_candidates),
            "candidates_deep_analyzed": len(evaluated_candidates),
            "qualified_pending_short_canary": counts[DISPOSITION_QUALIFIED],
            "observe_only": counts[DISPOSITION_OBSERVE],
            "research_only": counts[DISPOSITION_RESEARCH],
            "rejected_from_promotion": counts[DISPOSITION_REJECT],
            "independence_confirmation_pending": len(qualified),
            "short_canary_execution_authorized": False,
            "micro_live_execution_authorized": False,
        },
        "public_rpc": dict(public_rpc_stats),
        "decision": {
            "next_step": (
                "M74_SHORT_REALTIME_CANARY_PREPARATION"
                if qualified
                else "CONTINUE_CONTROLLED_ROTATION_OR_PUBLIC_RPC_HISTORY"
            ),
            "automatic_wallet_application": False,
            "short_canary_execution_authorized": False,
            "micro_live_execution_authorized": False,
            "signer_authorized": False,
        },
        "safety": {
            "helius_request_cap": M73_MAX_HELIUS_REQUESTS,
            "helius_credit_cap": M73_MAX_HELIUS_CREDITS,
            "discovery_budget_profile": "EXPANDED_MANUAL_TRANCHE_9000",
            "helius_retries": 0,
            "automatic_enhanced_api": False,
            "database_candidate_writes": 0,
            "backend_posts": 0,
            "jupiter_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signer_authorized": False,
            "recovery_counts_as_realtime_proof": False,
            "official_realtime_counter": 83,
            "official_realtime_counter_mutated": False,
        },
    }
    report["integrity"] = {"report_payload_sha256": canonical_sha256(report)}
    return report


def validate_m73_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("evaluation") == "PASS", "Report M73 non PASS.")
    _require(report.get("scope") == M73_SCOPE, "Scope M73 inatteso.")
    _require(report.get("version") == M73_VERSION, "Versione M73 inattesa.")
    expected = str(dict(report.get("integrity") or {}).get("report_payload_sha256") or "")
    _require(
        len(expected) == 64 and expected == canonical_sha256(_without_integrity(report)),
        "Hash report M73 non valido.",
    )
    safety = dict(report.get("safety") or {})
    _require(_integer(safety.get("helius_request_cap")) == 90, "Cap Helius report != 90.")
    _require(_integer(safety.get("helius_credit_cap")) == 9_000, "Cap crediti report != 9000.")
    _require(_integer(safety.get("helius_retries")) == 0, "Retry Helius report != 0.")
    _require(safety.get("automatic_enhanced_api") is False, "Enhanced automatico attivo.")
    _require(safety.get("official_realtime_counter_mutated") is False, "Counter 83 mutato.")
    _require(_integer(safety.get("paper_orders")) == 0, "Paper order creati.")
    _require(_integer(safety.get("live_orders")) == 0, "Live order creati.")
    _require(safety.get("signer_authorized") is False, "Signer autorizzato.")
    return {"report_payload_sha256": expected}


__all__ = [
    "DISPOSITION_OBSERVE",
    "DISPOSITION_QUALIFIED",
    "DISPOSITION_REJECT",
    "DISPOSITION_RESEARCH",
    "M66_HELIUS_CONFIRMATION",
    "M73ControlledQualificationError",
    "M73_MAX_DEEP_CANDIDATES",
    "M73_MAX_HELIUS_CREDITS",
    "M73_MAX_HELIUS_REQUESTS",
    "M73_MAX_PUBLIC_RPC_REQUESTS",
    "M73_MAX_SIGNATURES_PER_CANDIDATE",
    "M73_RUN_CONFIRMATION",
    "M73_SCOPE",
    "M73_VERSION",
    "build_m73_report",
    "canonical_sha256",
    "choose_seed_wallet",
    "classify_deep_candidate",
    "extract_m66_candidates",
    "known_m72_wallets",
    "validate_m72_authorization",
    "validate_m73_report",
    "validate_runtime_limits",
]
