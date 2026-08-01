from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from backend.app.models.candidate_position_lifecycle_audit import (
    CandidatePositionLifecycleAuditRun,
)
from backend.app.models.candidate_token_compatibility import (
    CandidateTokenCompatibility,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.services.candidate_exit_price_audit_service import (
    run_candidate_exit_price_audit,
)
from backend.app.services.candidate_jupiter_compatibility_service import (
    JUPITER_UNAVAILABLE,
    check_candidate_jupiter_compatibility,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.wallet_activity_service import ensure_aware, safe_float


REFRESH_COMPLETED = "COMPLETED"
REFRESH_PARTIAL = "PARTIAL"
REFRESH_UNAVAILABLE = "UNAVAILABLE"

ROUTE_FOUND = "ROUTE_FOUND"
NO_ROUTE = "NO_ROUTE"
QUOTE_ERROR = "QUOTE_ERROR"
JUPITER_UNAVAILABLE_RESULT = "JUPITER_UNAVAILABLE"
NOT_ATTEMPTED = "NOT_ATTEMPTED"

_TRANSIENT_ERROR_CODES = {
    "JUPITER_HTTP_ERROR",
    "JUPITER_NETWORK_ERROR",
    "JUPITER_TIMEOUT",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_lifecycle_run(
    db: Session,
    *,
    wallet_address: str,
    lifecycle_run_id: str,
) -> CandidatePositionLifecycleAuditRun:
    run_id = str(lifecycle_run_id or "").strip()
    if not run_id:
        raise ValueError(
            "Lifecycle run_id obbligatorio per il refresh exitability"
        )

    lifecycle = (
        db.query(CandidatePositionLifecycleAuditRun)
        .filter(
            CandidatePositionLifecycleAuditRun.wallet_address
            == wallet_address
        )
        .filter(CandidatePositionLifecycleAuditRun.run_id == run_id)
        .first()
    )
    if lifecycle is None:
        raise ValueError(
            "Lifecycle audit richiesto non trovato per il wallet selezionato"
        )
    if str(lifecycle.status or "").strip().upper() != "COMPLETED":
        raise ValueError("Lifecycle audit sorgente non completato")
    return lifecycle


def _position_tokens(position_details: list[dict[str, Any]]) -> list[str]:
    tokens: list[str] = []
    for row in position_details:
        token = str(row.get("token_mint") or "").strip()
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _result_status(item: dict[str, Any]) -> str:
    if bool(item.get("compatible")) and bool(item.get("sell_quote")):
        return ROUTE_FOUND

    error_code = str(item.get("error_code") or "").strip()
    if error_code == "JUPITER_NOT_CONFIGURED":
        return JUPITER_UNAVAILABLE_RESULT
    if error_code:
        return QUOTE_ERROR
    return NO_ROUTE


def _profile_cache_rows(
    db: Session,
    *,
    tokens: list[str],
    fixed_buy_size_lamports: int,
    slippage_bps: int,
) -> dict[str, CandidateTokenCompatibility]:
    if not tokens:
        return {}

    rows = (
        db.query(CandidateTokenCompatibility)
        .filter(CandidateTokenCompatibility.token_mint.in_(tokens))
        .filter(
            CandidateTokenCompatibility.fixed_buy_size_lamports
            == fixed_buy_size_lamports
        )
        .filter(CandidateTokenCompatibility.slippage_bps == slippage_bps)
        .all()
    )
    return {str(row.token_mint): row for row in rows}


def _is_current_compatible_cache(
    row: CandidateTokenCompatibility | None,
    *,
    now: datetime,
) -> bool:
    if row is None:
        return False
    expires_at = ensure_aware(row.expires_at)
    return bool(
        row.compatible
        and row.buy_quote
        and row.sell_quote
        and expires_at
        and expires_at > now
    )


def _cache_result(row: CandidateTokenCompatibility) -> dict[str, Any]:
    checked_at = ensure_aware(row.checked_at)
    expires_at = ensure_aware(row.expires_at)
    item = {
        "token_mint": str(row.token_mint),
        "buy_quote": bool(row.buy_quote),
        "sell_quote": bool(row.sell_quote),
        "compatible": bool(row.compatible),
        "buy_out_amount_raw": row.buy_out_amount_raw,
        "sell_out_amount_raw": row.sell_out_amount_raw,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "source": "CACHE",
        "checked_at": checked_at.isoformat() if checked_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    item["result_status"] = _result_status(item)
    return item


def _is_transient_quote_error(item: dict[str, Any]) -> bool:
    code = str(item.get("error_code") or "").strip().upper()
    message = str(item.get("error_message") or "").strip().lower()
    if code not in _TRANSIENT_ERROR_CODES:
        return False
    if code in {"JUPITER_NETWORK_ERROR", "JUPITER_TIMEOUT"}:
        return True
    return "too many requests" in message or "429" in message


def _empty_compatibility() -> dict[str, Any]:
    return {
        "checked": True,
        "status": "PASSED",
        "tokens_checked": 0,
        "tokens_compatible": 0,
        "requests": 0,
        "cache_hits": 0,
        "live_checks": 0,
        "compatibility_percent": 100.0,
        "results": [],
    }


def refresh_candidate_open_position_exitability(
    db: Session,
    *,
    wallet_address: str,
    lifecycle_run_id: str,
    cache_ttl_hours: int = 6,
    max_local_price_age_hours: int = 24,
    max_tokens: int = 20,
    force_refresh: bool = False,
    jupiter_client: JupiterSwapClient | None = None,
    now: datetime | None = None,
    transient_retry_count: int = 1,
    transient_retry_delay_seconds: float = 1.5,
    sleep_fn: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    started_at = ensure_aware(now) or utc_now()
    normalized_wallet = str(wallet_address or "").strip()

    wallet = (
        db.query(DiscoveredWallet)
        .filter(DiscoveredWallet.wallet_address == normalized_wallet)
        .first()
    )
    if wallet is None:
        raise ValueError("Wallet scoperto non trovato")

    lifecycle = _resolve_lifecycle_run(
        db,
        wallet_address=normalized_wallet,
        lifecycle_run_id=lifecycle_run_id,
    )
    position_details = [
        dict(row) for row in list(lifecycle.position_details or [])
    ]
    source_open_positions = int(
        (lifecycle.baseline_metrics or {}).get(
            "open_positions",
            len(position_details),
        )
        or 0
    )
    if source_open_positions != len(position_details):
        raise ValueError(
            "Lifecycle audit incompleto: "
            f"{source_open_positions} posizioni aperte ma "
            f"{len(position_details)} dettagli disponibili"
        )

    all_tokens = _position_tokens(position_details)
    effective_max_tokens = max(1, min(int(max_tokens), 50))
    selected_tokens = all_tokens[:effective_max_tokens]
    not_selected_tokens = all_tokens[effective_max_tokens:]

    parameters = dict(lifecycle.parameters or {})
    fixed_buy_size_sol = safe_float(parameters.get("fixed_buy_size_sol"))
    if fixed_buy_size_sol <= 0:
        raise ValueError(
            "Lifecycle audit privo di fixed_buy_size_sol valido"
        )
    fixed_buy_size_lamports = max(
        1,
        int(float(fixed_buy_size_sol) * 1_000_000_000),
    )
    slippage_bps = max(
        0,
        min(int(parameters.get("slippage_bps") or 100), 1000),
    )
    effective_ttl = max(1, min(int(cache_ttl_hours), 24))
    effective_local_age = max(
        1,
        min(int(max_local_price_age_hours), 720),
    )
    retry_budget = max(0, min(int(transient_retry_count), 2))
    retry_delay = max(
        0.0,
        min(float(transient_retry_delay_seconds), 5.0),
    )
    effective_sleep = sleep_fn or time.sleep

    cache_rows = _profile_cache_rows(
        db,
        tokens=selected_tokens,
        fixed_buy_size_lamports=fixed_buy_size_lamports,
        slippage_bps=slippage_bps,
    )
    reusable_tokens = [
        token
        for token in selected_tokens
        if _is_current_compatible_cache(
            cache_rows.get(token),
            now=started_at,
        )
    ]
    live_tokens = [
        token for token in selected_tokens if token not in reusable_tokens
    ]

    result_by_token: dict[str, dict[str, Any]] = {
        token: _cache_result(cache_rows[token])
        for token in reusable_tokens
    }
    aggregate_requests = 0
    aggregate_live_checks = 0
    aggregate_cache_hits = len(reusable_tokens)
    retry_attempts = 0
    transient_errors_seen = 0
    unavailable = False

    client = jupiter_client or JupiterSwapClient(
        max_retries=2,
        retry_base_seconds=1.0,
        retry_max_seconds=4.0,
    )

    try:
        compatibility = _empty_compatibility()
        pending_tokens = list(live_tokens)

        for attempt_index in range(retry_budget + 1):
            if not pending_tokens:
                break
            if attempt_index > 0:
                retry_attempts += 1
                effective_sleep(retry_delay * attempt_index)

            compatibility = check_candidate_jupiter_compatibility(
                db,
                pending_tokens,
                fixed_buy_size_sol=fixed_buy_size_sol,
                slippage_bps=slippage_bps,
                token_limit=len(pending_tokens),
                client=client,
                cache_ttl_hours=effective_ttl,
                force_refresh=True,
                now=started_at,
            )
            aggregate_requests += int(compatibility.get("requests") or 0)
            aggregate_live_checks += int(
                compatibility.get("live_checks") or 0
            )
            aggregate_cache_hits += int(
                compatibility.get("cache_hits") or 0
            )
            if str(compatibility.get("status") or "") == JUPITER_UNAVAILABLE:
                unavailable = True

            returned_tokens: set[str] = set()
            transient_tokens: list[str] = []
            for raw_item in list(compatibility.get("results") or []):
                item = dict(raw_item)
                token = str(item.get("token_mint") or "").strip()
                if not token:
                    continue
                returned_tokens.add(token)
                item["result_status"] = _result_status(item)
                item["retry_attempt"] = attempt_index
                result_by_token[token] = item
                if _is_transient_quote_error(item):
                    transient_errors_seen += 1
                    transient_tokens.append(token)

            for token in pending_tokens:
                if token in returned_tokens:
                    continue
                result_by_token[token] = {
                    "token_mint": token,
                    "result_status": NOT_ATTEMPTED,
                    "buy_quote": False,
                    "sell_quote": False,
                    "compatible": False,
                    "error_code": "JUPITER_CHECK_NOT_ATTEMPTED",
                    "error_message": (
                        "Controllo non eseguito dopo indisponibilita Jupiter"
                    ),
                    "source": "NONE",
                    "checked_at": None,
                    "expires_at": None,
                    "retry_attempt": attempt_index,
                }

            pending_tokens = transient_tokens

        result_rows = [
            result_by_token.get(
                token,
                {
                    "token_mint": token,
                    "result_status": NOT_ATTEMPTED,
                    "buy_quote": False,
                    "sell_quote": False,
                    "compatible": False,
                    "error_code": "JUPITER_CHECK_NOT_ATTEMPTED",
                    "error_message": "Controllo Jupiter non eseguito",
                    "source": "NONE",
                    "checked_at": None,
                    "expires_at": None,
                    "retry_attempt": 0,
                },
            )
            for token in selected_tokens
        ]

        exit_price_audit = run_candidate_exit_price_audit(
            db,
            wallet_address=normalized_wallet,
            max_local_price_age_hours=effective_local_age,
            lifecycle_run_id=lifecycle.run_id,
            now=started_at,
        )
    except Exception:
        db.rollback()
        raise

    counts = {
        ROUTE_FOUND: 0,
        NO_ROUTE: 0,
        QUOTE_ERROR: 0,
        JUPITER_UNAVAILABLE_RESULT: 0,
        NOT_ATTEMPTED: 0,
    }
    for row in result_rows:
        status = str(row.get("result_status") or NOT_ATTEMPTED)
        counts[status] = counts.get(status, 0) + 1

    if unavailable:
        refresh_status = REFRESH_UNAVAILABLE
    elif (
        not_selected_tokens
        or counts[NOT_ATTEMPTED] > 0
        or counts[QUOTE_ERROR] > 0
    ):
        refresh_status = REFRESH_PARTIAL
    else:
        refresh_status = REFRESH_COMPLETED

    checked_count = len(result_rows)
    compatible_count = counts[ROUTE_FOUND]
    compatibility_percent = (
        compatible_count / checked_count * 100.0 if checked_count else 100.0
    )
    completed_at = utc_now()
    audit_summary = dict(exit_price_audit.summary or {})

    return {
        "wallet_address": normalized_wallet,
        "lifecycle_run_id": lifecycle.run_id,
        "status": refresh_status,
        "parameters": {
            "fixed_buy_size_sol": fixed_buy_size_sol,
            "slippage_bps": slippage_bps,
            "cache_ttl_hours": effective_ttl,
            "max_local_price_age_hours": effective_local_age,
            "max_tokens": effective_max_tokens,
            "force_refresh_requested": bool(force_refresh),
            "refresh_policy": "REUSE_CURRENT_COMPATIBLE_RETRY_FAILURES",
            "transient_retry_count": retry_budget,
            "transient_retry_delay_seconds": retry_delay,
            "quote_profile": "SOL_TO_TOKEN_TO_SOL_FIXED_BUY_SIZE",
        },
        "safety": {
            "diagnostic_only": True,
            "helius_requests": 0,
            "jupiter_requests": aggregate_requests,
            "current_compatible_cache_preserved": True,
            "transactions_signed": False,
            "transactions_submitted": False,
            "live_enabled": False,
            "stream_changed": False,
            "worker_started": False,
            "wallets_applied": False,
            "generation_reset": False,
            "generation_created": False,
        },
        "summary": {
            "source_open_positions": source_open_positions,
            "position_details": len(position_details),
            "unique_open_position_tokens": len(all_tokens),
            "tokens_selected": len(selected_tokens),
            "tokens_not_selected": len(not_selected_tokens),
            "tokens_checked": checked_count,
            "route_found": counts[ROUTE_FOUND],
            "no_route": counts[NO_ROUTE],
            "quote_errors": counts[QUOTE_ERROR],
            "jupiter_unavailable": counts[JUPITER_UNAVAILABLE_RESULT],
            "not_attempted": counts[NOT_ATTEMPTED],
            "requests": aggregate_requests,
            "live_checks": aggregate_live_checks,
            "cache_hits": aggregate_cache_hits,
            "reused_current_routes": len(reusable_tokens),
            "tokens_retried": len(live_tokens),
            "retry_attempts": retry_attempts,
            "transient_errors_seen": transient_errors_seen,
            "compatibility_percent": round(compatibility_percent, 4),
            "audit_cache_missing": int(
                audit_summary.get("cache_missing") or 0
            ),
            "audit_cache_present_percent": safe_float(
                audit_summary.get("cache_present_percent")
            ),
            "audit_current_route_percent": safe_float(
                audit_summary.get("current_route_supported_percent")
            ),
            "audit_positions_analyzed": int(
                audit_summary.get("positions_analyzed") or 0
            ),
        },
        "results": result_rows,
        "exit_price_audit": exit_price_audit,
        "started_at": started_at,
        "completed_at": completed_at,
    }
