from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.trade import Trade
from backend.app.services.discovered_wallet_service import save_discovered_wallet
from backend.app.services.helius import HeliusRequestError, get_wallet_history
from backend.app.services.profile_engine import build_wallet_profile
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
        # Non sostituisce l'errore originale con un errore di rollback.
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


def _result_status(
    errors: list[dict[str, Any]],
    *,
    made_progress: bool,
) -> str:
    if not errors:
        return "COMPLETED"
    return "PARTIAL" if made_progress else "FAILED"


def _analytics_from_score(score: dict[str, Any]) -> dict[str, Any]:
    return score.get("dna", {}).get("analytics", {})


def get_traded_tokens_by_wallet(
    db: Session,
    wallet_address: str,
):
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


def get_wallets_by_token(
    db: Session,
    token_mint: str,
):
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


def discover_wallets_from_token_onchain(
    token_mint: str,
):
    try:
        transactions = get_wallet_history(token_mint)
    except Exception as error:
        issue = _issue(
            stage="TOKEN_HISTORY",
            error=error,
            token_mint=token_mint,
        )
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


def _save_ranked_wallet(
    db: Session,
    *,
    wallet_address: str,
    discovered_from_token: str,
) -> dict[str, Any]:
    score = sync_wallet(db, wallet_address)
    analytics = _analytics_from_score(score)
    profile = build_wallet_profile(
        db=db,
        wallet_address=wallet_address,
    )

    save_discovered_wallet(
        db=db,
        wallet_address=wallet_address,
        discovered_from_token=discovered_from_token,
        smart_score=profile["smart_score"],
        roi_percent=analytics.get("total_roi_percent", 0),
        win_rate_percent=analytics.get("win_rate_percent", 0),
        profit_loss_sol=analytics.get("total_profit_loss_sol", 0),
        reliable_positions=analytics.get("reliable_positions", 0),
    )
    return profile


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
                    _save_ranked_wallet(
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
                        stage="DISCOVERED_WALLET_SYNC",
                        error=error,
                        wallet_address=wallet_address,
                        token_mint=token_mint,
                    )
                )

    results.sort(
        key=lambda item: item.get("smart_score", 0),
        reverse=True,
    )

    made_progress = bool(results) or (
        discovery.get("status") == "COMPLETED"
    )

    return {
        "status": _result_status(errors, made_progress=made_progress),
        "token_mint": token_mint,
        "wallets_discovered": discovery.get("wallets_found", 0),
        "wallets_analyzed": len(results),
        "wallets_failed": failed_wallets,
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
                build_wallet_profile(
                    db=db,
                    wallet_address=wallet_address,
                )
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
            _issue(
                stage="SEED_SYNC",
                error=error,
                wallet_address=wallet_address,
            )
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
            "wallets_failed": 0,
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

        for discovered_wallet in discovery.get("wallets", [])[
            :max_wallets_per_token
        ]:
            if discovered_wallet and discovered_wallet != wallet_address:
                discovered_wallets.add(discovered_wallet)

    results: list[dict[str, Any]] = []
    wallets_failed = 0

    for discovered_wallet in sorted(discovered_wallets):
        try:
            results.append(
                _save_ranked_wallet(
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
                    stage="DISCOVERED_WALLET_SYNC",
                    error=error,
                    wallet_address=discovered_wallet,
                )
            )

    results.sort(
        key=lambda item: item.get("smart_score", 0),
        reverse=True,
    )

    made_progress = any(
        (
            seed_score is not None,
            tokens_processed > 0,
            bool(results),
        )
    )

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
        "wallets_failed": wallets_failed,
        "ranking": results,
        "errors": errors,
        "error_count": len(errors),
    }
