from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.models.candidate_history_backfill import CandidateHistoryBackfillRun
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services.discovered_wallet_service import analyze_and_apply_wallet_ranking
from backend.app.services.discovery_hydration_service import (
    apply_discovered_wallet_score,
    save_wallet_history_transactions,
    upsert_wallet_sync_marker,
)
from backend.app.services.helius import HeliusRequestError, get_wallet_history
from backend.app.services.smart_score_engine import calculate_smart_score
from backend.app.services.wallet_activity_service import analyze_wallet_activity, ensure_aware


BACKFILL_STATUS_COMPLETED = "COMPLETED"
BACKFILL_STATUS_PARTIAL = "PARTIAL"
BACKFILL_STATUS_FAILED = "FAILED"
BACKFILL_STATUS_EMPTY = "EMPTY"

STOP_LOOKBACK_REACHED = "LOOKBACK_REACHED"
STOP_LAST_PAGE = "LAST_PAGE"
STOP_EMPTY_PAGE = "EMPTY_PAGE"
STOP_REQUEST_BUDGET = "REQUEST_BUDGET_EXHAUSTED"
STOP_CURSOR_REPEATED = "CURSOR_REPEATED"
STOP_CURSOR_MISSING = "CURSOR_MISSING"
STOP_FAILED = "FAILED"

_RUN_LOCK = Lock()


class CandidateHistoryAlreadyRunningError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error_message(error: object) -> str:
    message = str(error or "Errore non specificato.")
    if "api-key=" in message.lower():
        return "Errore Helius. Dettagli sensibili rimossi."
    return message[:500]


def _transaction_time(item: dict[str, Any]) -> datetime | None:
    raw_value = item.get("timestamp")
    if raw_value is None:
        raw_value = item.get("blockTime")
    if raw_value is None:
        raw_value = item.get("block_time")
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _update_wallet_backfill_fields(
    wallet: DiscoveredWallet,
    *,
    run: CandidateHistoryBackfillRun,
    success: bool,
) -> None:
    wallet.extended_history_status = run.status
    wallet.extended_history_run_id = run.run_id
    wallet.extended_history_last_attempt_at = run.started_at
    if success:
        wallet.extended_history_last_success_at = run.completed_at
    wallet.extended_history_lookback_days = run.requested_lookback_days
    wallet.extended_history_request_budget = run.request_budget
    wallet.extended_history_helius_requests = run.helius_requests
    wallet.extended_history_pages_fetched = run.pages_fetched
    wallet.extended_history_transactions_found = run.transactions_found
    wallet.extended_history_swaps_found = run.swaps_found
    wallet.extended_history_trades_imported = run.trades_imported
    wallet.extended_history_trades_updated = run.trades_updated
    wallet.extended_history_parse_failures = run.parse_failures
    wallet.extended_history_oldest_at = run.oldest_transaction_at
    wallet.extended_history_newest_at = run.newest_transaction_at
    wallet.extended_history_stop_reason = run.stop_reason
    wallet.extended_history_error_code = run.error_code
    wallet.extended_history_error_message = run.error_message
    wallet.status = "UPDATED"


def _recalculate_wallet(db: Session, wallet: DiscoveredWallet, now: datetime) -> None:
    score = calculate_smart_score(db, wallet.wallet_address)
    apply_discovered_wallet_score(wallet, score)
    activity = analyze_wallet_activity(db, wallet.wallet_address, now=now)
    analyze_and_apply_wallet_ranking(db, wallet, activity=activity)
    upsert_wallet_sync_marker(db, wallet.wallet_address, synced_at=now)


def run_extended_candidate_history(
    db: Session,
    *,
    wallet_address: str,
    lookback_days: int = 30,
    max_helius_requests: int = 5,
    page_size: int = 100,
    force: bool = False,
    now: datetime | None = None,
) -> CandidateHistoryBackfillRun:
    if not _RUN_LOCK.acquire(blocking=False):
        raise CandidateHistoryAlreadyRunningError(
            "Un backfill storico candidato è già in esecuzione."
        )

    run_id = str(uuid4())
    started_at = ensure_aware(now) or utc_now()
    try:
        wallet = (
            db.query(DiscoveredWallet)
            .filter(DiscoveredWallet.wallet_address == wallet_address)
            .first()
        )
        if wallet is None:
            raise ValueError("Wallet scoperto non trovato")
        allowed_history_quality_classifications = {
            "COPIABILE",
            "OSSERVAZIONE",
        }
        if (
            not force
            and wallet.quality_classification
            not in allowed_history_quality_classifications
        ):
            raise ValueError(
                "Lo storico esteso è consentito solo ai wallet COPIABILE."
            )

        effective_lookback = max(7, min(int(lookback_days), 90))
        effective_budget = max(1, min(int(max_helius_requests), 20))
        effective_page_size = max(10, min(int(page_size), 100))
        cutoff = started_at - timedelta(days=effective_lookback)

        run = CandidateHistoryBackfillRun(
            run_id=run_id,
            wallet_address=wallet_address,
            status=BACKFILL_STATUS_PARTIAL,
            stop_reason=STOP_REQUEST_BUDGET,
            requested_lookback_days=effective_lookback,
            page_size=effective_page_size,
            request_budget=effective_budget,
            parameters={
                "lookback_days": effective_lookback,
                "max_helius_requests": effective_budget,
                "page_size": effective_page_size,
                "transaction_type": "SWAP",
                "token_accounts": "balanceChanged",
                "pagination": "before-signature",
                "force": force,
            },
            safety={
                "manual_only": True,
                "live_enabled": False,
                "live_armed": False,
                "stream_started": False,
                "worker_started": False,
                "wallets_applied": False,
                "generation_created": False,
                "generation_reset": False,
                "transactions_signed": False,
                "transactions_submitted": False,
                "retry_attempts_enabled": False,
            },
            started_at=started_at,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        before_signature: str | None = None
        seen_page_cursors: set[str] = set()
        seen_signatures: set[str] = set()
        oldest_at: datetime | None = None
        newest_at: datetime | None = None
        stop_reason = STOP_REQUEST_BUDGET

        for _ in range(effective_budget):
            run.helius_requests += 1
            run.next_before_signature = before_signature
            db.commit()
            try:
                page = get_wallet_history(
                    wallet_address,
                    limit=effective_page_size,
                    transaction_type="SWAP",
                    gte_time=int(cutoff.timestamp()),
                    lte_time=int(started_at.timestamp()),
                    before_signature=before_signature,
                    commitment="confirmed",
                    token_accounts="balanceChanged",
                    max_retries=0,
                )
            except HeliusRequestError as error:
                continuation = str(error.continuation_signature or "").strip()
                if continuation:
                    if continuation in seen_page_cursors:
                        stop_reason = STOP_CURSOR_REPEATED
                        break
                    seen_page_cursors.add(continuation)
                    before_signature = continuation
                    run.next_before_signature = continuation
                    run.stop_reason = "FILTER_CONTINUATION"
                    db.commit()
                    continue
                raise

            if not page:
                stop_reason = (
                    STOP_EMPTY_PAGE if run.transactions_found == 0 else STOP_LAST_PAGE
                )
                db.commit()
                break

            run.pages_fetched += 1
            unique_page: list[dict[str, Any]] = []
            for item in page:
                signature = str(item.get("signature") or "").strip()
                if signature and signature in seen_signatures:
                    run.duplicate_transactions += 1
                    continue
                if signature:
                    seen_signatures.add(signature)
                unique_page.append(item)

                timestamp = _transaction_time(item)
                if timestamp is not None:
                    oldest_at = timestamp if oldest_at is None else min(oldest_at, timestamp)
                    newest_at = timestamp if newest_at is None else max(newest_at, timestamp)

            counters = save_wallet_history_transactions(
                db,
                wallet_address=wallet_address,
                transactions=unique_page,
            )
            run.transactions_found += counters["transactions_found"]
            run.swaps_found += counters["swaps_found"]
            run.trades_imported += counters["trades_imported"]
            run.trades_updated += counters["trades_updated"]
            run.parse_failures += counters["parse_failures"]
            db.commit()
            db.refresh(run)

            last_signature = str(page[-1].get("signature") or "").strip()
            page_oldest = min(
                (time for time in (_transaction_time(item) for item in page) if time),
                default=None,
            )
            if page_oldest is not None and page_oldest <= cutoff:
                stop_reason = STOP_LOOKBACK_REACHED
                before_signature = last_signature or before_signature
                break
            if not last_signature:
                stop_reason = STOP_CURSOR_MISSING
                break
            if last_signature in seen_page_cursors:
                stop_reason = STOP_CURSOR_REPEATED
                break

            seen_page_cursors.add(last_signature)
            before_signature = last_signature
        else:
            stop_reason = STOP_REQUEST_BUDGET

        run.oldest_transaction_at = oldest_at
        run.newest_transaction_at = newest_at
        run.next_before_signature = before_signature
        run.stop_reason = stop_reason
        if run.transactions_found == 0:
            run.status = BACKFILL_STATUS_EMPTY
        elif stop_reason == STOP_REQUEST_BUDGET:
            run.status = BACKFILL_STATUS_PARTIAL
        elif run.parse_failures > 0:
            run.status = BACKFILL_STATUS_PARTIAL
        else:
            run.status = BACKFILL_STATUS_COMPLETED
        run.completed_at = utc_now()

        _recalculate_wallet(db, wallet, started_at)
        _update_wallet_backfill_fields(
            wallet,
            run=run,
            success=True,
        )
        db.commit()
        db.refresh(run)
        db.refresh(wallet)
        return run

    except Exception as error:
        db.rollback()
        if isinstance(error, (ValueError, CandidateHistoryAlreadyRunningError)):
            raise

        completed_at = utc_now()
        wallet = (
            db.query(DiscoveredWallet)
            .filter(DiscoveredWallet.wallet_address == wallet_address)
            .first()
        )
        error_code = (
            error.error_code
            if isinstance(error, HeliusRequestError)
            else "EXTENDED_HISTORY_FAILED"
        )
        error_message = (
            error.message
            if isinstance(error, HeliusRequestError)
            else _safe_error_message(error)
        )
        run = (
            db.query(CandidateHistoryBackfillRun)
            .filter(CandidateHistoryBackfillRun.run_id == run_id)
            .first()
        )
        if run is None:
            run = CandidateHistoryBackfillRun(
                run_id=run_id,
                wallet_address=wallet_address,
                requested_lookback_days=max(7, min(int(lookback_days), 90)),
                page_size=max(10, min(int(page_size), 100)),
                request_budget=max(1, min(int(max_helius_requests), 20)),
                parameters={"force": force},
                safety={
                    "manual_only": True,
                    "live_enabled": False,
                    "stream_started": False,
                    "worker_started": False,
                    "wallets_applied": False,
                    "generation_created": False,
                    "generation_reset": False,
                    "transactions_signed": False,
                    "transactions_submitted": False,
                },
                started_at=started_at,
            )
            db.add(run)
        run.status = (
            BACKFILL_STATUS_PARTIAL
            if int(run.transactions_found or 0) > 0
            else BACKFILL_STATUS_FAILED
        )
        run.stop_reason = STOP_FAILED
        run.error_code = error_code
        run.error_message = _safe_error_message(error_message)
        run.completed_at = completed_at
        if wallet is not None:
            _update_wallet_backfill_fields(
                wallet,
                run=run,
                success=run.status == BACKFILL_STATUS_PARTIAL,
            )
        db.commit()
        db.refresh(run)
        return run
    finally:
        _RUN_LOCK.release()

def get_latest_extended_candidate_history(
    db: Session,
    wallet_address: str,
) -> CandidateHistoryBackfillRun | None:
    return (
        db.query(CandidateHistoryBackfillRun)
        .filter(CandidateHistoryBackfillRun.wallet_address == wallet_address)
        .order_by(
            CandidateHistoryBackfillRun.completed_at.desc(),
            CandidateHistoryBackfillRun.id.desc(),
        )
        .first()
    )
