from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.candidate_position_lifecycle_audit import (
    CandidatePositionLifecycleAuditRun,
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


def refresh_candidate_open_position_exitability(
    db: Session,
    *,
    wallet_address: str,
    lifecycle_run_id: str,
    cache_ttl_hours: int = 6,
    max_local_price_age_hours: int = 24,
    max_tokens: int = 20,
    force_refresh: bool = True,
    jupiter_client: JupiterSwapClient | None = None,
    now: datetime | None = None,
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
    fixed_buy_size_sol = safe_float(
        parameters.get("fixed_buy_size_sol")
    )
    if fixed_buy_size_sol <= 0:
        raise ValueError(
            "Lifecycle audit privo di fixed_buy_size_sol valido"
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

    compatibility: dict[str, Any]
    result_rows: list[dict[str, Any]] = []

    try:
        if selected_tokens:
            compatibility = check_candidate_jupiter_compatibility(
                db,
                selected_tokens,
                fixed_buy_size_sol=fixed_buy_size_sol,
                slippage_bps=slippage_bps,
                token_limit=len(selected_tokens),
                client=jupiter_client or JupiterSwapClient(),
                cache_ttl_hours=effective_ttl,
                force_refresh=bool(force_refresh),
                now=started_at,
            )
        else:
            compatibility = {
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

        returned_by_token: dict[str, dict[str, Any]] = {}
        for raw_item in list(compatibility.get("results") or []):
            item = dict(raw_item)
            token = str(item.get("token_mint") or "").strip()
            item["result_status"] = _result_status(item)
            if token:
                returned_by_token[token] = item
            result_rows.append(item)

        for token in selected_tokens:
            if token in returned_by_token:
                continue
            result_rows.append(
                {
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
                }
            )

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

    compatibility_status = str(
        compatibility.get("status") or "FAILED"
    )
    if compatibility_status == JUPITER_UNAVAILABLE:
        refresh_status = REFRESH_UNAVAILABLE
    elif not_selected_tokens or counts[NOT_ATTEMPTED] > 0:
        refresh_status = REFRESH_PARTIAL
    else:
        refresh_status = REFRESH_COMPLETED

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
            "force_refresh": bool(force_refresh),
            "quote_profile": "SOL_TO_TOKEN_TO_SOL_FIXED_BUY_SIZE",
        },
        "safety": {
            "diagnostic_only": True,
            "helius_requests": 0,
            "jupiter_requests": int(
                compatibility.get("requests") or 0
            ),
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
            "tokens_checked": int(
                compatibility.get("tokens_checked") or 0
            ),
            "route_found": counts[ROUTE_FOUND],
            "no_route": counts[NO_ROUTE],
            "quote_errors": counts[QUOTE_ERROR],
            "jupiter_unavailable": counts[
                JUPITER_UNAVAILABLE_RESULT
            ],
            "not_attempted": counts[NOT_ATTEMPTED],
            "requests": int(compatibility.get("requests") or 0),
            "live_checks": int(
                compatibility.get("live_checks") or 0
            ),
            "cache_hits": int(
                compatibility.get("cache_hits") or 0
            ),
            "compatibility_percent": safe_float(
                compatibility.get("compatibility_percent")
            ),
            "audit_cache_missing": int(
                audit_summary.get("cache_missing") or 0
            ),
            "audit_cache_present_percent": safe_float(
                audit_summary.get("cache_present_percent")
            ),
            "audit_current_route_percent": safe_float(
                audit_summary.get(
                    "current_route_supported_percent"
                )
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
