from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.models.wallet import Wallet
from backend.app.services.discovered_wallet_service import analyze_and_apply_wallet_ranking
from backend.app.services.helius import HeliusRequestError, get_wallet_history
from backend.app.services.smart_score_engine import calculate_smart_score
from backend.app.services.trade_engine import build_trade, build_trade_data, normalize_swap
from backend.app.services.wallet_activity_service import analyze_wallet_activity


HYDRATION_STATUS_NEVER = "NEVER"
HYDRATION_STATUS_COMPLETED = "COMPLETED"
HYDRATION_STATUS_EMPTY = "EMPTY"
HYDRATION_STATUS_PARTIAL = "PARTIAL"
HYDRATION_STATUS_FAILED = "FAILED"

_ELIGIBLE_ACTIVITY_CLASSES = {
    "INATTIVO",
    "POCO_ATTIVO",
    "NON_ANALIZZATO",
}

_RUN_LOCK = Lock()


class HydrationAlreadyRunningError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_message(value: object) -> str:
    message = str(value or "Errore non specificato.")
    if "api-key=" in message.lower():
        return "Errore Helius. Dettagli sensibili rimossi."
    return message[:500]


def _apply_score(wallet: DiscoveredWallet, score: dict[str, Any]) -> None:
    analytics = score.get("dna", {}).get("analytics", {})
    wallet.smart_score = float(score.get("smart_score") or wallet.smart_score or 0)
    wallet.roi_percent = float(analytics.get("total_roi_percent") or 0)
    wallet.win_rate_percent = float(analytics.get("win_rate_percent") or 0)
    wallet.profit_loss_sol = float(analytics.get("total_profit_loss_sol") or 0)
    wallet.reliable_positions = int(analytics.get("reliable_positions") or 0)


def _upsert_wallet_sync_marker(
    db: Session,
    wallet_address: str,
    *,
    synced_at: datetime,
) -> None:
    wallet = db.query(Wallet).filter(Wallet.address == wallet_address).first()
    if wallet is None:
        wallet = Wallet(address=wallet_address, last_sync=synced_at)
        db.add(wallet)
    else:
        wallet.last_sync = synced_at


def _select_candidates(
    db: Session,
    *,
    maximum: int,
    minimum_smart_score: float,
    force: bool,
    now: datetime,
) -> tuple[list[DiscoveredWallet], int]:
    rows = (
        db.query(DiscoveredWallet)
        .filter(DiscoveredWallet.smart_score >= minimum_smart_score)
        .order_by(
            DiscoveredWallet.smart_score.desc(),
            DiscoveredWallet.ranking_score.desc(),
            DiscoveredWallet.id.asc(),
        )
        .all()
    )

    cooldown_cutoff = now - timedelta(
        hours=settings.DISCOVERY_HYDRATION_COOLDOWN_HOURS
    )
    selected: list[DiscoveredWallet] = []
    skipped_cooldown = 0

    for wallet in rows:
        if not force and wallet.activity_classification not in _ELIGIBLE_ACTIVITY_CLASSES:
            continue

        last_attempt = ensure_aware(wallet.hydration_last_attempt_at)
        if not force and last_attempt is not None and last_attempt >= cooldown_cutoff:
            skipped_cooldown += 1
            continue

        selected.append(wallet)
        if len(selected) >= maximum:
            break

    return selected, skipped_cooldown


def _save_transactions(
    db: Session,
    *,
    wallet_address: str,
    transactions: list[dict[str, Any]],
) -> dict[str, int]:
    swaps = [item for item in transactions if item.get("type") == "SWAP"]
    signatures = [
        str(item.get("signature"))
        for item in swaps
        if item.get("signature")
    ]
    existing_by_signature = {
        item.signature: item
        for item in (
            db.query(Trade)
            .filter(Trade.signature.in_(signatures))
            .all()
            if signatures
            else []
        )
    }

    imported = 0
    updated = 0
    parse_failures = 0

    for transaction in swaps:
        try:
            normalized = normalize_swap(
                transaction,
                wallet_address=wallet_address,
            )
            trade = build_trade(normalized)
            trade_data = build_trade_data(wallet_address, trade)
            signature = str(trade_data.get("signature") or "").strip()
            if not signature:
                parse_failures += 1
                continue

            existing = existing_by_signature.get(signature)
            if existing is None:
                existing = Trade(**trade_data)
                db.add(existing)
                existing_by_signature[signature] = existing
                imported += 1
            else:
                for key, value in trade_data.items():
                    setattr(existing, key, value)
                updated += 1
        except Exception:
            parse_failures += 1

    return {
        "transactions_found": len(transactions),
        "swaps_found": len(swaps),
        "trades_imported": imported,
        "trades_updated": updated,
        "parse_failures": parse_failures,
    }




def save_wallet_history_transactions(
    db: Session,
    *,
    wallet_address: str,
    transactions: list[dict[str, Any]],
) -> dict[str, int]:
    """Persist parsed swap history with signature-level deduplication."""
    return _save_transactions(
        db,
        wallet_address=wallet_address,
        transactions=transactions,
    )


def apply_discovered_wallet_score(
    wallet: DiscoveredWallet,
    score: dict[str, Any],
) -> None:
    _apply_score(wallet, score)


def upsert_wallet_sync_marker(
    db: Session,
    wallet_address: str,
    *,
    synced_at: datetime,
) -> None:
    _upsert_wallet_sync_marker(db, wallet_address, synced_at=synced_at)


def _mark_failure(
    db: Session,
    *,
    wallet_id: int,
    run_id: str,
    attempted_at: datetime,
    lookback_days: int,
    error: Exception,
) -> dict[str, Any]:
    db.rollback()
    wallet = db.query(DiscoveredWallet).filter(DiscoveredWallet.id == wallet_id).one()

    if isinstance(error, HeliusRequestError):
        error_code = error.error_code
        error_message = error.message
        attempts = int(error.attempts or 1)
    else:
        error_code = "HYDRATION_FAILED"
        error_message = _safe_message(error)
        attempts = 1

    wallet.hydration_status = HYDRATION_STATUS_FAILED
    wallet.hydration_run_id = run_id
    wallet.hydration_last_attempt_at = attempted_at
    wallet.hydration_lookback_days = lookback_days
    wallet.hydration_transactions_found = 0
    wallet.hydration_swaps_found = 0
    wallet.hydration_trades_imported = 0
    wallet.hydration_trades_updated = 0
    wallet.hydration_parse_failures = 0
    wallet.hydration_helius_requests = 1
    wallet.hydration_error_code = error_code
    wallet.hydration_error_message = _safe_message(error_message)
    db.commit()

    return {
        "wallet_address": wallet.wallet_address,
        "status": HYDRATION_STATUS_FAILED,
        "helius_requests": 1,
        "helius_attempts_reported": attempts,
        "transactions_found": 0,
        "swaps_found": 0,
        "trades_imported": 0,
        "trades_updated": 0,
        "parse_failures": 0,
        "activity_classification": wallet.activity_classification,
        "activity_score": wallet.activity_score,
        "quality_classification": wallet.quality_classification,
        "quality_score": wallet.quality_score,
        "quality_eligible": wallet.quality_eligible,
        "eligible": wallet.eligible,
        "error_code": error_code,
        "error_message": _safe_message(error_message),
    }


def _hydrate_wallet(
    db: Session,
    *,
    wallet: DiscoveredWallet,
    run_id: str,
    lookback_days: int,
    transaction_limit: int,
    now: datetime,
) -> dict[str, Any]:
    wallet_id = wallet.id
    wallet_address = wallet.wallet_address
    cutoff = now - timedelta(days=lookback_days)

    try:
        transactions = get_wallet_history(
            wallet_address,
            limit=transaction_limit,
            transaction_type="SWAP",
            gte_time=int(cutoff.timestamp()),
            commitment="confirmed",
            token_accounts="balanceChanged",
            max_retries=0,
        )
        counters = _save_transactions(
            db,
            wallet_address=wallet_address,
            transactions=transactions,
        )
        db.flush()

        score = calculate_smart_score(db, wallet_address)
        wallet = db.query(DiscoveredWallet).filter(DiscoveredWallet.id == wallet_id).one()
        _apply_score(wallet, score)
        activity = analyze_wallet_activity(db, wallet_address, now=now)
        analyze_and_apply_wallet_ranking(
            db,
            wallet,
            activity=activity,
        )
        _upsert_wallet_sync_marker(db, wallet_address, synced_at=now)

        if counters["swaps_found"] == 0:
            status = HYDRATION_STATUS_EMPTY
        elif counters["parse_failures"] > 0:
            status = HYDRATION_STATUS_PARTIAL
        else:
            status = HYDRATION_STATUS_COMPLETED

        wallet.hydration_status = status
        wallet.hydration_run_id = run_id
        wallet.hydration_last_attempt_at = now
        wallet.hydration_last_success_at = now
        wallet.hydration_lookback_days = lookback_days
        wallet.hydration_transactions_found = counters["transactions_found"]
        wallet.hydration_swaps_found = counters["swaps_found"]
        wallet.hydration_trades_imported = counters["trades_imported"]
        wallet.hydration_trades_updated = counters["trades_updated"]
        wallet.hydration_parse_failures = counters["parse_failures"]
        wallet.hydration_helius_requests = 1
        wallet.hydration_error_code = None
        wallet.hydration_error_message = None
        wallet.status = "UPDATED"
        db.commit()
        db.refresh(wallet)

        return {
            "wallet_address": wallet.wallet_address,
            "status": status,
            "helius_requests": 1,
            "helius_attempts_reported": 1,
            **counters,
            "activity_classification": wallet.activity_classification,
            "activity_score": wallet.activity_score,
            "quality_classification": wallet.quality_classification,
            "quality_score": wallet.quality_score,
            "quality_eligible": wallet.quality_eligible,
            "eligible": wallet.eligible,
            "error_code": None,
            "error_message": None,
        }
    except Exception as error:
        return _mark_failure(
            db,
            wallet_id=wallet_id,
            run_id=run_id,
            attempted_at=now,
            lookback_days=lookback_days,
            error=error,
        )


def run_controlled_discovery_hydration(
    db: Session,
    *,
    max_wallets: int | None = None,
    max_helius_requests: int | None = None,
    lookback_days: int | None = None,
    transaction_limit: int | None = None,
    minimum_smart_score: float = 0.0,
    force: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not _RUN_LOCK.acquire(blocking=False):
        raise HydrationAlreadyRunningError(
            "Una Discovery Hydration è già in esecuzione."
        )

    try:
        started_at = ensure_aware(now) or utc_now()
        run_id = str(uuid4())
        requested_wallets = int(
            max_wallets or settings.DISCOVERY_HYDRATION_DEFAULT_WALLETS
        )
        requested_budget = int(max_helius_requests or requested_wallets)
        effective_wallets = max(
            1,
            min(requested_wallets, settings.DISCOVERY_HYDRATION_MAX_WALLETS_PER_RUN),
        )
        effective_budget = max(
            1,
            min(
                requested_budget,
                settings.DISCOVERY_HYDRATION_MAX_HELIUS_REQUESTS_PER_RUN,
            ),
        )
        maximum = min(effective_wallets, effective_budget)
        effective_lookback = max(
            1,
            min(
                int(lookback_days or settings.DISCOVERY_HYDRATION_LOOKBACK_DAYS),
                14,
            ),
        )
        effective_transaction_limit = max(
            1,
            min(
                int(
                    transaction_limit
                    or settings.DISCOVERY_HYDRATION_TRANSACTION_LIMIT
                ),
                100,
            ),
        )

        candidates, skipped_cooldown = _select_candidates(
            db,
            maximum=maximum,
            minimum_smart_score=float(minimum_smart_score),
            force=force,
            now=started_at,
        )

        results: list[dict[str, Any]] = []
        for wallet in candidates:
            if len(results) >= effective_budget:
                break
            results.append(
                _hydrate_wallet(
                    db,
                    wallet=wallet,
                    run_id=run_id,
                    lookback_days=effective_lookback,
                    transaction_limit=effective_transaction_limit,
                    now=started_at,
                )
            )

        counts = Counter(item["status"] for item in results)
        helius_requests = sum(int(item.get("helius_requests") or 0) for item in results)
        failed = counts[HYDRATION_STATUS_FAILED]
        completed_count = (
            counts[HYDRATION_STATUS_COMPLETED]
            + counts[HYDRATION_STATUS_EMPTY]
            + counts[HYDRATION_STATUS_PARTIAL]
        )
        if not results:
            status = "NO_CANDIDATES"
        elif failed == 0:
            status = "COMPLETED"
        elif completed_count > 0:
            status = "PARTIAL"
        else:
            status = "FAILED"

        completed_at = utc_now()
        return {
            "status": status,
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "requested_max_wallets": requested_wallets,
            "effective_max_wallets": maximum,
            "request_budget": effective_budget,
            "helius_requests": helius_requests,
            "retry_attempts_enabled": False,
            "lookback_days": effective_lookback,
            "transaction_limit_per_wallet": effective_transaction_limit,
            "minimum_smart_score": float(minimum_smart_score),
            "force": force,
            "wallets_selected": len(candidates),
            "wallets_attempted": len(results),
            "wallets_completed": counts[HYDRATION_STATUS_COMPLETED],
            "wallets_empty": counts[HYDRATION_STATUS_EMPTY],
            "wallets_partial": counts[HYDRATION_STATUS_PARTIAL],
            "wallets_failed": failed,
            "wallets_skipped_cooldown": skipped_cooldown,
            "swaps_found": sum(int(item.get("swaps_found") or 0) for item in results),
            "trades_imported": sum(
                int(item.get("trades_imported") or 0) for item in results
            ),
            "trades_updated": sum(
                int(item.get("trades_updated") or 0) for item in results
            ),
            "parse_failures": sum(
                int(item.get("parse_failures") or 0) for item in results
            ),
            "activity_breakdown": dict(
                Counter(
                    str(item.get("activity_classification") or "NON_ANALIZZATO")
                    for item in results
                )
            ),
            "quality_breakdown": dict(
                Counter(
                    str(item.get("quality_classification") or "NON_ANALIZZATO")
                    for item in results
                )
            ),
            "results": results,
            "safety": {
                "live_enabled": False,
                "live_armed": False,
                "stream_started": False,
                "worker_started": False,
                "wallets_applied": False,
                "generation_created": False,
                "generation_reset": False,
            },
        }
    finally:
        _RUN_LOCK.release()
