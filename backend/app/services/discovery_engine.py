from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.trade import Trade
from backend.app.services.discovered_wallet_service import save_discovered_wallet
from backend.app.services.helius import HeliusRequestError, get_wallet_history
from backend.app.services.profile_engine import build_wallet_profile
from backend.app.services.wallet_activity_service import analyze_wallet_activity
from backend.app.services.wallet_sync_service import sync_wallet


_SECRET_PATTERNS = (
    re.compile(r"(?i)(api-key=)[^&\s'\"]+"),
    re.compile(r"(?i)(x-automation-key[=:]\s*)[^&\s'\"]+"),
)


def _redact_message(value: object) -> str:
    message = str(value)
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(r"\1REDACTED", message)
    return message[:500]


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        pass


def _issue(
    *,
    stage: str,
    error: Exception,
    wallet_address: str | None = None,
    token_mint: str | None = None,
) -> dict[str, Any]:
    if isinstance(error, HeliusRequestError):
        return {
            "stage": stage,
            "wallet": wallet_address,
            "token_mint": token_mint,
            "provider": "HELIUS",
            "error_code": error.error_code,
            "message": _redact_message(error.message),
            "status_code": error.status_code,
            "retryable": error.retryable,
            "attempts": error.attempts,
        }

    return {
        "stage": stage,
        "wallet": wallet_address,
        "token_mint": token_mint,
        "provider": None,
        "error_code": "DISCOVERY_STEP_FAILED",
        "message": _redact_message(error),
        "status_code": None,
        "retryable": False,
        "attempts": 1,
    }


def _result_status(errors: list[dict[str, Any]], *, made_progress: bool) -> str:
    if not errors:
        return "COMPLETED"
    return "PARTIAL" if made_progress else "FAILED"


def _analytics_from_score(score: dict[str, Any]) -> dict[str, Any]:
    return score.get("dna", {}).get("analytics", {})


def _sort_ranking(items: list[dict[str, Any]]) -> None:
    items.sort(
        key=lambda item: (
            bool(item.get("eligible")),
            float(item.get("ranking_score") or 0),
            float(item.get("smart_score") or 0),
        ),
        reverse=True,
    )


def _activity_breakdown(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        str(item.get("activity_classification") or "NON_ANALIZZATO")
        for item in items
    )
    return {
        "ATTIVO": counts.get("ATTIVO", 0),
        "POCO_ATTIVO": counts.get("POCO_ATTIVO", 0),
        "INATTIVO": counts.get("INATTIVO", 0),
        "IPERATTIVO": counts.get("IPERATTIVO", 0),
        "NON_ANALIZZATO": counts.get("NON_ANALIZZATO", 0),
    }


def get_traded_tokens_by_wallet(db: Session, wallet_address: str):
    rows = (
        db.query(Trade.token_mint)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.token_mint.isnot(None))
        .distinct()
        .all()
    )
    tokens = [row[0] for row in rows if row[0]]
    return {
        "wallet": wallet_address,
        "tokens_found": len(tokens),
        "tokens": tokens,
    }


def get_wallets_by_token(db: Session, token_mint: str):
    rows = (
        db.query(Trade.wallet_address)
        .filter(Trade.token_mint == token_mint)
        .distinct()
        .all()
    )
    wallets = [row[0] for row in rows if row[0]]
    return {
        "token_mint": token_mint,
        "wallets_found": len(wallets),
        "wallets": wallets,
    }


def discover_wallets_from_token_onchain(token_mint: str):
    try:
        transactions = get_wallet_history(token_mint)
    except Exception as error:
        issue = _issue(stage="TOKEN_HISTORY", error=error, token_mint=token_mint)
        return {
            "status": "FAILED",
            "token_mint": token_mint,
            "wallets_found": 0,
            "wallets": [],
            "errors": [issue],
        }

    wallets: set[str] = set()
    for transaction in transactions:
        if transaction.get("type") != "SWAP":
            continue
        fee_payer = transaction.get("feePayer")
        if fee_payer:
            wallets.add(str(fee_payer))

    return {
        "status": "COMPLETED",
        "token_mint": token_mint,
        "wallets_found": len(wallets),
        "wallets": sorted(wallets),
        "errors": [],
    }


def analyze_and_save_discovered_wallet(
    db: Session,
    *,
    wallet_address: str,
    discovered_from_token: str,
) -> dict[str, Any]:
    score = sync_wallet(db, wallet_address)
    analytics = _analytics_from_score(score)
    profile = build_wallet_profile(db=db, wallet_address=wallet_address)
    activity = analyze_wallet_activity(db, wallet_address)

    saved = save_discovered_wallet(
        db=db,
        wallet_address=wallet_address,
        discovered_from_token=discovered_from_token,
        smart_score=profile["smart_score"],
        roi_percent=analytics.get("total_roi_percent", 0),
        win_rate_percent=analytics.get("win_rate_percent", 0),
        profit_loss_sol=analytics.get("total_profit_loss_sol", 0),
        reliable_positions=analytics.get("reliable_positions", 0),
        activity=activity,
    )

    return {
        **profile,
        "wallet": wallet_address,
        "wallet_address": wallet_address,
        "ranking_score": saved.ranking_score,
        "eligible": saved.eligible,
        "eligibility_reasons": list(saved.eligibility_reasons or []),
        "last_swap_at": saved.last_swap_at,
        "swaps_24h": saved.swaps_24h,
        "swaps_7d": saved.swaps_7d,
        "buys_24h": saved.buys_24h,
        "sells_24h": saved.sells_24h,
        "buys_7d": saved.buys_7d,
        "sells_7d": saved.sells_7d,
        "volume_24h_sol": saved.volume_24h_sol,
        "volume_7d_sol": saved.volume_7d_sol,
        "active_days_7d": saved.active_days_7d,
        "average_swaps_per_active_day_7d": (
            saved.average_swaps_per_active_day_7d
        ),
        "average_minutes_between_swaps_7d": (
            saved.average_minutes_between_swaps_7d
        ),
        "activity_score": saved.activity_score,
        "activity_classification": saved.activity_classification,
        "activity_eligible": saved.activity_eligible,
        "activity_reasons": list(saved.activity_reasons or []),
        "activity_calculated_at": saved.activity_calculated_at,
    }


def discover_import_and_score_wallets_from_token(
    db: Session,
    token_mint: str,
    limit: int = 10,
):
    discovery = discover_wallets_from_token_onchain(token_mint)
    errors = list(discovery.get("errors", []))
    results: list[dict[str, Any]] = []
    failed_wallets = 0

    if discovery.get("status") != "FAILED":
        for wallet_address in discovery["wallets"][:limit]:
            try:
                results.append(
                    analyze_and_save_discovered_wallet(
                        db,
                        wallet_address=wallet_address,
                        discovered_from_token=token_mint,
                    )
                )
            except Exception as error:
                failed_wallets += 1
                _safe_rollback(db)
                errors.append(
                    _issue(
                        stage="DISCOVERED_WALLET_ANALYSIS",
                        error=error,
                        wallet_address=wallet_address,
                        token_mint=token_mint,
                    )
                )

    _sort_ranking(results)
    made_progress = bool(results) or discovery.get("status") == "COMPLETED"
    return {
        "status": _result_status(errors, made_progress=made_progress),
        "token_mint": token_mint,
        "wallets_discovered": discovery.get("wallets_found", 0),
        "wallets_analyzed": len(results),
        "wallets_eligible": sum(1 for item in results if item.get("eligible")),
        "wallets_failed": failed_wallets,
        "activity_breakdown": _activity_breakdown(results),
        "ranking": results,
        "errors": errors,
        "error_count": len(errors),
    }


def discover_full_from_wallet(
    db: Session,
    wallet_address: str,
    max_tokens: int = 5,
    max_wallets_per_token: int = 5,
):
    errors: list[dict[str, Any]] = []
    seed_score: dict[str, Any] | None = None
    seed_trades = 0
    seed_sync_status = "COMPLETED"

    try:
        seed_score = sync_wallet(db, wallet_address)
        seed_analytics = _analytics_from_score(seed_score)
        seed_trades = int(seed_analytics.get("total_trades", 0))
        if seed_trades > 0:
            try:
                build_wallet_profile(db=db, wallet_address=wallet_address)
            except Exception as error:
                _safe_rollback(db)
                errors.append(
                    _issue(
                        stage="SEED_PROFILE",
                        error=error,
                        wallet_address=wallet_address,
                    )
                )
    except Exception as error:
        seed_sync_status = "FAILED"
        _safe_rollback(db)
        errors.append(
            _issue(stage="SEED_SYNC", error=error, wallet_address=wallet_address)
        )

    try:
        token_data = get_traded_tokens_by_wallet(db, wallet_address)
    except Exception as error:
        _safe_rollback(db)
        errors.append(
            _issue(
                stage="SEED_TOKEN_QUERY",
                error=error,
                wallet_address=wallet_address,
            )
        )
        return {
            "status": "FAILED",
            "seed_wallet": wallet_address,
            "seed_sync_status": seed_sync_status,
            "seed_trades_imported": seed_trades,
            "seed_tokens_found": 0,
            "tokens_attempted": 0,
            "tokens_processed": 0,
            "tokens_failed": 0,
            "wallets_discovered": 0,
            "wallets_analyzed": 0,
            "wallets_eligible": 0,
            "wallets_failed": 0,
            "activity_breakdown": _activity_breakdown([]),
            "ranking": [],
            "errors": errors,
            "error_count": len(errors),
        }

    tokens = token_data["tokens"][:max_tokens]
    discovered_wallets: set[str] = set()
    tokens_processed = 0
    tokens_failed = 0

    for token_mint in tokens:
        discovery = discover_wallets_from_token_onchain(token_mint)
        discovery_errors = discovery.get("errors", [])
        if discovery.get("status") == "FAILED":
            tokens_failed += 1
            errors.extend(discovery_errors)
            continue

        tokens_processed += 1
        errors.extend(discovery_errors)
        for discovered_wallet in discovery.get("wallets", [])[:max_wallets_per_token]:
            if discovered_wallet and discovered_wallet != wallet_address:
                discovered_wallets.add(discovered_wallet)

    results: list[dict[str, Any]] = []
    wallets_failed = 0
    for discovered_wallet in sorted(discovered_wallets):
        try:
            results.append(
                analyze_and_save_discovered_wallet(
                    db,
                    wallet_address=discovered_wallet,
                    discovered_from_token="MULTI_TOKEN",
                )
            )
        except Exception as error:
            wallets_failed += 1
            _safe_rollback(db)
            errors.append(
                _issue(
                    stage="DISCOVERED_WALLET_ANALYSIS",
                    error=error,
                    wallet_address=discovered_wallet,
                )
            )

    _sort_ranking(results)
    made_progress = any((seed_score is not None, tokens_processed > 0, bool(results)))
    return {
        "status": _result_status(errors, made_progress=made_progress),
        "seed_wallet": wallet_address,
        "seed_sync_status": seed_sync_status,
        "seed_trades_imported": seed_trades,
        "seed_tokens_found": token_data["tokens_found"],
        "tokens_attempted": len(tokens),
        "tokens_processed": tokens_processed,
        "tokens_failed": tokens_failed,
        "wallets_discovered": len(discovered_wallets),
        "wallets_analyzed": len(results),
        "wallets_eligible": sum(1 for item in results if item.get("eligible")),
        "wallets_failed": wallets_failed,
        "activity_breakdown": _activity_breakdown(results),
        "ranking": results,
        "errors": errors,
        "error_count": len(errors),
    }
