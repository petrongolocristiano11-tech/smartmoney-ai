from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Callable

from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    canonical_sha256,
)
from backend.app.services.helius import get_wallet_history
from backend.app.services.trade_engine import analyze_swap, normalize_swap


M66_HELIUS_DISCOVERY_VERSION = (
    "canonical-parser-gen4-controlled-helius-discovery/1"
)
M66_HELIUS_SCOPE = "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY"
M66_HELIUS_CACHE_SCOPE = "M66_CONTROLLED_HELIUS_REQUEST_CACHE"
M66_HELIUS_CONFIRMATION = "SPEND_MAX_9000_HELIUS_CREDITS_FOR_M66_DISCOVERY_TRANCHE"
M66_DEFAULT_SEED_WALLET = (
    "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
)

M66_ENHANCED_CREDITS_PER_REQUEST = 100
M66_MAX_SEED_TOKEN_REQUESTS = 15
M66_MAX_CANDIDATE_HISTORY_REQUESTS = 74
M66_MAX_ENHANCED_REQUESTS = 90
M66_MAX_ENHANCED_CREDITS = 9_000
M66_DEFAULT_SEED_TOKEN_REQUESTS = 15
M66_DEFAULT_CANDIDATE_HISTORY_REQUESTS = 70
M66_DEFAULT_PLANNED_REQUESTS = 86
M66_DEFAULT_PLANNED_CREDITS = 8_600
M66_MIN_PROVIDER_INTERVAL_SECONDS = 0.15

_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_EXCLUDED_MINTS = frozenset(
    {
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD8wV8wH5Lg8pJwNYBzH4Y",
    }
)


class M66ControlledHeliusDiscoveryError(RuntimeError):
    pass


HistoryFetcher = Callable[..., list[dict[str, Any]]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M66ControlledHeliusDiscoveryError(message)


def _valid_address(value: Any) -> bool:
    return bool(_SOLANA_ADDRESS.fullmatch(str(value or "").strip()))


def _finite(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _timestamp(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, result)


def _iso_now(now: datetime | None = None) -> str:
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc).isoformat()


def _without_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "integrity"}


def build_controlled_helius_plan(
    *,
    seed_wallet: str = M66_DEFAULT_SEED_WALLET,
    maximum_seed_tokens: int = M66_MAX_SEED_TOKEN_REQUESTS,
    maximum_candidate_wallets: int = M66_MAX_CANDIDATE_HISTORY_REQUESTS,
) -> dict[str, Any]:
    normalized_seed = str(seed_wallet or "").strip()
    _require(_valid_address(normalized_seed), "Seed wallet Solana non valido.")
    seed_tokens = max(
        1,
        min(int(maximum_seed_tokens), M66_MAX_SEED_TOKEN_REQUESTS),
    )
    candidates = max(
        1,
        min(
            int(maximum_candidate_wallets),
            M66_MAX_CANDIDATE_HISTORY_REQUESTS,
        ),
    )
    request_cap = 1 + seed_tokens + candidates
    credit_cap = request_cap * M66_ENHANCED_CREDITS_PER_REQUEST
    _require(
        request_cap <= M66_MAX_ENHANCED_REQUESTS,
        "Budget richieste Helius M66 oltre il limite hard.",
    )
    _require(
        credit_cap <= M66_MAX_ENHANCED_CREDITS,
        "Budget crediti Helius M66 oltre il limite hard.",
    )
    plan: dict[str, Any] = {
        "scope": "M66_CONTROLLED_HELIUS_DISCOVERY_PLAN",
        "discovery_version": M66_HELIUS_DISCOVERY_VERSION,
        "budget_profile": "EXPANDED_MANUAL_TRANCHE_9000",
        "seed_wallet": normalized_seed,
        "maximum_seed_tokens": seed_tokens,
        "maximum_candidate_wallets": candidates,
        "enhanced_request_cap": request_cap,
        "enhanced_credit_cap": credit_cap,
        "credits_per_request": M66_ENHANCED_CREDITS_PER_REQUEST,
        "request_breakdown": {
            "seed_wallet_history": 1,
            "token_histories": seed_tokens,
            "candidate_wallet_histories": candidates,
        },
        "execution": {
            "explicit_confirmation_required": M66_HELIUS_CONFIRMATION,
            "automatic_enhanced_api": False,
            "maximum_retries": 0,
            "discovery_cron_reactivation": False,
            "legacy_forward_feed_reactivation": False,
            "primary_campaign_reactivation": False,
            "backend_post": False,
            "candidate_database_writes": False,
            "raw_capture_writes": False,
            "credit_guard_required": True,
        },
    }
    plan["integrity"] = {
        "plan_payload_sha256": canonical_sha256(plan),
    }
    return plan


def empty_helius_request_cache(*, generated_at: datetime | None = None) -> dict[str, Any]:
    cache: dict[str, Any] = {
        "scope": M66_HELIUS_CACHE_SCOPE,
        "discovery_version": M66_HELIUS_DISCOVERY_VERSION,
        "generated_at_utc": _iso_now(generated_at),
        "histories": {},
        "safety": {
            "public_onchain_data_only": True,
            "api_key_stored": False,
            "credentials_stored": False,
        },
    }
    cache["integrity"] = {
        "cache_payload_sha256": canonical_sha256(cache),
    }
    return cache


def validate_helius_request_cache(
    cache: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    if cache is None:
        return {}
    _require(isinstance(cache, dict), "Cache Helius M66 non oggetto.")
    _require(
        cache.get("scope") == M66_HELIUS_CACHE_SCOPE,
        "Scope cache Helius M66 inatteso.",
    )
    _require(
        cache.get("discovery_version") == M66_HELIUS_DISCOVERY_VERSION,
        "Versione cache Helius M66 inattesa.",
    )
    integrity = dict(cache.get("integrity") or {})
    expected_hash = str(integrity.get("cache_payload_sha256") or "")
    _require(len(expected_hash) == 64, "Hash cache Helius M66 assente.")
    _require(
        expected_hash == canonical_sha256(_without_integrity(cache)),
        "Hash cache Helius M66 non valido.",
    )
    histories = cache.get("histories")
    _require(isinstance(histories, dict), "Histories cache Helius M66 non valide.")
    validated: dict[str, list[dict[str, Any]]] = {}
    for raw_address, raw_history in histories.items():
        address = str(raw_address or "").strip()
        _require(_valid_address(address), "Indirizzo cache Helius M66 non valido.")
        _require(isinstance(raw_history, list), "History cache Helius non array.")
        _require(len(raw_history) <= 100, "History cache Helius oltre 100 righe.")
        _require(
            all(isinstance(item, dict) for item in raw_history),
            "Transazione cache Helius non oggetto.",
        )
        validated[address] = [dict(item) for item in raw_history]
    return validated


def build_helius_request_cache(
    histories: dict[str, list[dict[str, Any]]],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    normalized: dict[str, list[dict[str, Any]]] = {}
    for address in sorted(histories):
        _require(_valid_address(address), "Indirizzo output cache Helius non valido.")
        history = histories[address]
        _require(len(history) <= 100, "History output cache Helius oltre 100 righe.")
        normalized[address] = [dict(item) for item in history]
    cache = empty_helius_request_cache(generated_at=generated_at)
    cache["histories"] = normalized
    cache["integrity"] = {
        "cache_payload_sha256": canonical_sha256(_without_integrity(cache)),
    }
    return cache


def _parse_swap(transaction: dict[str, Any], wallet: str) -> dict[str, Any] | None:
    if str(transaction.get("type") or "").upper() != "SWAP":
        return None
    normalized = normalize_swap(transaction, wallet_address=wallet)
    analysis = analyze_swap(normalized)
    side = str(analysis.get("side") or "UNKNOWN").upper()
    token = str(analysis.get("token_mint") or "").strip()
    token_amount = _finite(analysis.get("token_amount"))
    sol_amount = _finite(analysis.get("sol_amount"))
    if (
        side not in {"BUY", "SELL"}
        or not _valid_address(token)
        or token in _EXCLUDED_MINTS
        or token_amount <= 0
        or sol_amount <= 0
    ):
        return None
    return {
        "signature": str(transaction.get("signature") or ""),
        "timestamp": _timestamp(transaction.get("timestamp")),
        "side": side,
        "token_mint": token,
        "token_amount": token_amount,
        "sol_amount": sol_amount,
        "parser": analysis.get("parser"),
    }


def _seed_tokens(
    transactions: list[dict[str, Any]],
    *,
    seed_wallet: str,
    limit: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    latest: dict[str, int] = {}
    for transaction in transactions:
        parsed = _parse_swap(transaction, seed_wallet)
        if parsed is None:
            continue
        token = parsed["token_mint"]
        counts[token] += 1
        latest[token] = max(latest.get(token, 0), int(parsed["timestamp"]))
    ordered = sorted(
        counts,
        key=lambda token: (-counts[token], -latest[token], token),
    )[:limit]
    return [
        {
            "token_mint": token,
            "seed_swap_occurrences": counts[token],
            "latest_seed_swap_timestamp": latest[token],
        }
        for token in ordered
    ]


def _candidate_prescreen(
    wallet: str,
    transactions: list[dict[str, Any]],
    *,
    discovery_tokens: set[str],
) -> dict[str, Any]:
    parsed_by_signature: dict[str, dict[str, Any]] = {}
    anonymous_index = 0
    for transaction in transactions:
        parsed = _parse_swap(transaction, wallet)
        if parsed is None:
            continue
        signature = parsed["signature"]
        if not signature:
            anonymous_index += 1
            signature = f"missing-signature-{anonymous_index}"
        parsed_by_signature.setdefault(signature, parsed)
    parsed = sorted(
        parsed_by_signature.values(),
        key=lambda item: (int(item["timestamp"]), item["signature"]),
    )
    buys = sum(item["side"] == "BUY" for item in parsed)
    sells = sum(item["side"] == "SELL" for item in parsed)
    amounts = [float(item["sol_amount"]) for item in parsed]
    token_counts = Counter(item["token_mint"] for item in parsed)
    active_days = {
        datetime.fromtimestamp(item["timestamp"], tz=timezone.utc).date().isoformat()
        for item in parsed
        if item["timestamp"] > 0
    }
    dust = sum(0 < amount <= 0.001 for amount in amounts)
    meaningful = sum(amount >= 0.005 for amount in amounts)
    size_compatible = sum(0.02 <= amount <= 5.0 for amount in amounts)
    count = len(parsed)
    dust_ratio = dust / count if count else 0.0
    size_ratio = size_compatible / count if count else 0.0
    top_concentration = (
        max(token_counts.values()) / count if token_counts and count else 0.0
    )
    token_sides: dict[str, set[str]] = defaultdict(set)
    inventory: dict[str, float] = defaultdict(float)
    observed_closed_cycles = 0
    orphan_sells = 0
    for item in parsed:
        token = item["token_mint"]
        token_sides[token].add(item["side"])
        amount = float(item["token_amount"])
        if item["side"] == "BUY":
            inventory[token] += amount
            continue
        before = inventory[token]
        if before <= 0:
            orphan_sells += 1
            continue
        remaining = max(0.0, before - amount)
        if remaining <= max(1e-12, before * 0.01):
            observed_closed_cycles += 1
            remaining = 0.0
        inventory[token] = remaining
    completed_pair_tokens = sum(
        {"BUY", "SELL"}.issubset(sides) for sides in token_sides.values()
    )
    reasons: list[str] = []
    if count < 4:
        reasons.append("INSUFFICIENT_SINGLE_PAGE_SWAP_SAMPLE")
    if buys == 0:
        reasons.append("NO_OBSERVED_BUYS")
    if sells == 0:
        reasons.append("NO_OBSERVED_SELLS")
    if len(token_counts) < 2:
        reasons.append("LOW_TOKEN_DIVERSITY")
    if len(active_days) < 2:
        reasons.append("INSUFFICIENT_ACTIVE_DAYS")
    if dust_ratio > 0.25:
        reasons.append("DUST_RATIO_HIGH")
    if size_ratio < 0.50:
        reasons.append("LOW_SIZE_COMPATIBILITY")
    if top_concentration > 0.85:
        reasons.append("TOKEN_CONCENTRATION_HIGH")
    if completed_pair_tokens == 0:
        reasons.append("NO_OBSERVED_BUY_SELL_TOKEN_PAIR")
    if observed_closed_cycles == 0:
        reasons.append("NO_CAUSAL_CLOSED_CYCLE_IN_PAGE")
    prescreen_passed = not reasons
    sample_component = min(count / 20.0, 1.0) * 25.0
    diversity_component = min(len(token_counts) / 5.0, 1.0) * 20.0
    active_component = min(len(active_days) / 4.0, 1.0) * 15.0
    size_component = size_ratio * 20.0
    cycle_component = min(observed_closed_cycles / 3.0, 1.0) * 20.0
    score = max(
        0.0,
        min(
            100.0,
            sample_component
            + diversity_component
            + active_component
            + size_component
            + cycle_component
            - min(25.0, dust_ratio * 50.0),
        ),
    )
    timestamps = [item["timestamp"] for item in parsed if item["timestamp"] > 0]
    return {
        "wallet_address": wallet,
        "status": (
            "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST"
            if prescreen_passed
            else "PRESCREEN_REJECTED"
        ),
        "prescreen_score": round(score, 4),
        "reasons": reasons,
        "next_action": (
            "ACQUIRE_TARGETED_HISTORY_THEN_RUN_EXACT_GEN4_GATE"
            if prescreen_passed
            else "DO_NOT_SPEND_MORE_CREDITS"
        ),
        "sample": {
            "enhanced_rows": len(transactions),
            "valid_swaps": count,
            "buys": buys,
            "sells": sells,
            "unique_tokens": len(token_counts),
            "active_days": len(active_days),
            "meaningful_swaps": meaningful,
            "dust_ratio": round(dust_ratio, 8),
            "median_swap_sol": round(median(amounts), 9) if amounts else 0.0,
            "size_compatibility_ratio": round(size_ratio, 8),
            "top_token_concentration": round(top_concentration, 8),
            "completed_pair_tokens": completed_pair_tokens,
            "causal_closed_cycles_observed": observed_closed_cycles,
            "orphan_sells": orphan_sells,
            "oldest_timestamp": min(timestamps) if timestamps else None,
            "newest_timestamp": max(timestamps) if timestamps else None,
            "discovery_token_overlap": len(set(token_counts) & discovery_tokens),
        },
        "economics": {
            "net_pnl_sol": None,
            "profit_factor": None,
            "win_rate_percent": None,
            "maximum_drawdown_percent": None,
            "status": "UNAVAILABLE_FROM_SINGLE_ENHANCED_HISTORY_PAGE",
            "historical_jupiter_quotes_invented": False,
        },
        "promotion": {
            "qualified_for_short_canary": False,
            "micro_live_preparation_authorized": False,
            "micro_live_execution_authorized": False,
        },
    }


def execute_controlled_helius_discovery(
    *,
    confirmation: str,
    seed_wallet: str = M66_DEFAULT_SEED_WALLET,
    cached_wallet_addresses: set[str] | None = None,
    maximum_seed_tokens: int = M66_MAX_SEED_TOKEN_REQUESTS,
    maximum_candidate_wallets: int = M66_MAX_CANDIDATE_HISTORY_REQUESTS,
    request_cache: dict[str, Any] | None = None,
    fetch_history: HistoryFetcher = get_wallet_history,
    executed_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(
        str(confirmation or "").strip() == M66_HELIUS_CONFIRMATION,
        f"Conferma Helius richiesta: {M66_HELIUS_CONFIRMATION}.",
    )
    plan = build_controlled_helius_plan(
        seed_wallet=seed_wallet,
        maximum_seed_tokens=maximum_seed_tokens,
        maximum_candidate_wallets=maximum_candidate_wallets,
    )
    seed = plan["seed_wallet"]
    cached_wallets = {
        str(item).strip()
        for item in (cached_wallet_addresses or set())
        if _valid_address(item)
    }
    histories = validate_helius_request_cache(request_cache)
    request_addresses: list[str] = []
    cache_hit_addresses: list[str] = []
    last_provider_request_completed_at: float | None = None

    def history(address: str, origin_suffix: str) -> list[dict[str, Any]]:
        nonlocal last_provider_request_completed_at
        if address in histories:
            cache_hit_addresses.append(address)
            return [dict(item) for item in histories[address]]
        _require(
            len(request_addresses) < int(plan["enhanced_request_cap"]),
            "Budget Helius M66 esaurito prima della richiesta.",
        )
        if last_provider_request_completed_at is not None:
            elapsed = time.monotonic() - last_provider_request_completed_at
            remaining = M66_MIN_PROVIDER_INTERVAL_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)
        result = fetch_history(
            address,
            limit=100,
            transaction_type="SWAP",
            commitment="finalized",
            token_accounts="balanceChanged",
            max_retries=0,
            request_origin=f"M66_CONTROLLED_DISCOVERY_{origin_suffix}"[:120],
            automatic=False,
            capture_response=False,
        )
        last_provider_request_completed_at = time.monotonic()
        _require(isinstance(result, list), "Payload Helius M66 non array.")
        _require(
            len(result) <= 100 and all(isinstance(item, dict) for item in result),
            "Payload Helius M66 oltre limite o non valido.",
        )
        request_addresses.append(address)
        histories[address] = [dict(item) for item in result]
        return [dict(item) for item in result]

    seed_history = history(seed, "SEED_WALLET")
    selected_tokens = _seed_tokens(
        seed_history,
        seed_wallet=seed,
        limit=int(plan["maximum_seed_tokens"]),
    )
    candidate_occurrences: Counter[str] = Counter()
    candidate_tokens: dict[str, set[str]] = defaultdict(set)
    candidate_latest: dict[str, int] = {}
    for token_row in selected_tokens:
        token = token_row["token_mint"]
        for transaction in history(token, "TOKEN_HISTORY"):
            if str(transaction.get("type") or "").upper() != "SWAP":
                continue
            wallet = str(transaction.get("feePayer") or "").strip()
            if (
                not _valid_address(wallet)
                or wallet == seed
                or wallet in cached_wallets
            ):
                continue
            candidate_occurrences[wallet] += 1
            candidate_tokens[wallet].add(token)
            candidate_latest[wallet] = max(
                candidate_latest.get(wallet, 0),
                _timestamp(transaction.get("timestamp")),
            )
    ranked_pool = sorted(
        candidate_occurrences,
        key=lambda wallet: (
            -len(candidate_tokens[wallet]),
            -candidate_occurrences[wallet],
            -candidate_latest[wallet],
            wallet,
        ),
    )
    selected_wallets = ranked_pool[: int(plan["maximum_candidate_wallets"])]
    discovery_token_set = {item["token_mint"] for item in selected_tokens}
    candidates: list[dict[str, Any]] = []
    for wallet in selected_wallets:
        result = _candidate_prescreen(
            wallet,
            history(wallet, "CANDIDATE_WALLET"),
            discovery_tokens=discovery_token_set,
        )
        result["discovery_evidence"] = {
            "token_overlap": sorted(candidate_tokens[wallet]),
            "token_history_occurrences": candidate_occurrences[wallet],
            "latest_token_history_timestamp": candidate_latest[wallet],
        }
        candidates.append(result)
    candidates.sort(
        key=lambda item: (
            item["status"] != "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST",
            -_finite(item["prescreen_score"]),
            item["wallet_address"],
        )
    )
    network_requests = len(request_addresses)
    credits_reserved = network_requests * M66_ENHANCED_CREDITS_PER_REQUEST
    completed_at = executed_at or datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "discovery": "PASS",
        "scope": M66_HELIUS_SCOPE,
        "discovery_version": M66_HELIUS_DISCOVERY_VERSION,
        "budget_profile": "EXPANDED_MANUAL_TRANCHE_9000",
        "executed_at_utc": _iso_now(completed_at),
        "seed_wallet": seed,
        "cached_inventory": {
            "wallets_available_without_helius": len(cached_wallets),
            "existing_wallets_excluded_from_new_discovery": len(cached_wallets),
        },
        "seed_tokens": selected_tokens,
        "candidate_pool": {
            "new_wallets_found_before_limit": len(ranked_pool),
            "wallets_selected_for_prescreen": len(selected_wallets),
            "wallets_prescreened": len(candidates),
        },
        "candidate_results": candidates,
        "summary": {
            "new_wallets_prescreened": len(candidates),
            "prescreen_pass_needing_full_gen4_history": sum(
                item["status"]
                == "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST"
                for item in candidates
            ),
            "prescreen_rejected": sum(
                item["status"] == "PRESCREEN_REJECTED" for item in candidates
            ),
            "qualified_for_short_canary": 0,
            "micro_live_ready": 0,
        },
        "budget": {
            "enhanced_request_cap": plan["enhanced_request_cap"],
            "enhanced_requests_executed": network_requests,
            "enhanced_credit_cap": plan["enhanced_credit_cap"],
            "enhanced_credits_reserved_maximum": credits_reserved,
            "cache_hits": len(cache_hit_addresses),
            "network_request_addresses": request_addresses,
            "cache_hit_addresses": cache_hit_addresses,
            "maximum_retries": 0,
            "provider_minimum_interval_seconds": M66_MIN_PROVIDER_INTERVAL_SECONDS,
            "automatic_enhanced_api": False,
        },
        "activation": {
            "discovery_cron_reactivation_authorized": False,
            "primary_campaign_reactivation_authorized": False,
            "legacy_forward_feed_reactivation_authorized": False,
            "short_canary_activation_authorized": False,
            "micro_live_preparation_authorized": False,
            "micro_live_execution_authorized": False,
            "automatic_live_activation": False,
            "signer_authorized": False,
        },
        "safety": {
            "explicit_manual_confirmation": True,
            "automatic_enhanced_polling": False,
            "helius_requests": network_requests,
            "helius_credits_reserved_maximum": credits_reserved,
            "candidate_database_writes": 0,
            "raw_capture_writes": 0,
            "credit_guard_reservation_writes_maximum": network_requests,
            "database_write_scope": "HELIUS_CREDIT_GUARD_RESERVATIONS_ONLY",
            "backend_posts": 0,
            "jupiter_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "official_realtime_counter_mutated": False,
            "recovery_counted_as_realtime_proof": False,
            "historical_jupiter_quotes_invented": False,
        },
    }
    report["integrity"] = {
        "plan_payload_sha256": plan["integrity"]["plan_payload_sha256"],
        "report_payload_sha256": canonical_sha256(report),
    }
    output_cache = build_helius_request_cache(histories, generated_at=completed_at)
    return report, output_cache


__all__ = [
    "M66_DEFAULT_SEED_WALLET",
    "M66_ENHANCED_CREDITS_PER_REQUEST",
    "M66_HELIUS_CACHE_SCOPE",
    "M66_HELIUS_CONFIRMATION",
    "M66_HELIUS_DISCOVERY_VERSION",
    "M66_HELIUS_SCOPE",
    "M66_MAX_ENHANCED_CREDITS",
    "M66_MAX_ENHANCED_REQUESTS",
    "M66_MIN_PROVIDER_INTERVAL_SECONDS",
    "M66ControlledHeliusDiscoveryError",
    "build_controlled_helius_plan",
    "build_helius_request_cache",
    "empty_helius_request_cache",
    "execute_controlled_helius_discovery",
    "validate_helius_request_cache",
]
