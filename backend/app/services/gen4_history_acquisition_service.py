from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services import candidate_history_service
from backend.app.services.blockchain_parser_gen4_profitability_service import (
    preview_gen4_profitability,
)

GEN4_HISTORY_ACQUISITION_CONFIRMATION = "RUN_GEN4_HISTORY_ACQUISITION"
GEN4_HISTORY_ACQUISITION_POLICY_VERSION = (
    "canonical-parser-gen4-controlled-history-acquisition/2"
)
AUTO_ALLOWED_QUALITY_CLASSIFICATIONS = frozenset({"COPIABILE", "OSSERVAZIONE"})
EXPLICIT_RESEARCH_REJECTED_CLASSIFICATIONS = frozenset({"SOSPETTO"})
MAX_TOTAL_HELIUS_REQUESTS = 50


class Gen4HistoryAcquisitionError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_wallets(values: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in values or ():
        wallet = str(raw or "").strip()
        if not wallet:
            continue
        if not 32 <= len(wallet) <= 64:
            raise Gen4HistoryAcquisitionError(
                f"Wallet non valido: {wallet[:12]}...",
                code="INVALID_WALLET_ADDRESS",
            )
        if wallet not in normalized:
            normalized.append(wallet)
    return normalized


def _validate_limits(
    *,
    lookback_days: int,
    max_wallets: int,
    max_helius_requests_per_wallet: int,
    page_size: int,
) -> tuple[int, int, int, int]:
    effective_lookback = int(lookback_days)
    effective_max_wallets = int(max_wallets)
    effective_requests = int(max_helius_requests_per_wallet)
    effective_page_size = int(page_size)

    if not 21 <= effective_lookback <= 90:
        raise Gen4HistoryAcquisitionError(
            "lookback_days deve essere compreso tra 21 e 90.",
            code="INVALID_LOOKBACK_DAYS",
        )
    if not 1 <= effective_max_wallets <= 5:
        raise Gen4HistoryAcquisitionError(
            "max_wallets deve essere compreso tra 1 e 5.",
            code="INVALID_MAX_WALLETS",
        )
    if not 1 <= effective_requests <= 20:
        raise Gen4HistoryAcquisitionError(
            "max_helius_requests_per_wallet deve essere compreso tra 1 e 20.",
            code="INVALID_REQUEST_BUDGET",
        )
    if not 10 <= effective_page_size <= 100:
        raise Gen4HistoryAcquisitionError(
            "page_size deve essere compreso tra 10 e 100.",
            code="INVALID_PAGE_SIZE",
        )
    if effective_max_wallets * effective_requests > MAX_TOTAL_HELIUS_REQUESTS:
        raise Gen4HistoryAcquisitionError(
            "Il budget totale Helius supera il limite hard di 50 richieste.",
            code="TOTAL_REQUEST_BUDGET_EXCEEDED",
        )

    return (
        effective_lookback,
        effective_max_wallets,
        effective_requests,
        effective_page_size,
    )


def _trade_stats(db: Session, wallet_address: str) -> dict[str, Any]:
    count, oldest_at, newest_at = db.execute(
        select(
            func.count(Trade.id),
            func.min(Trade.block_time),
            func.max(Trade.block_time),
        ).where(
            Trade.wallet_address == wallet_address,
            Trade.success.is_(True),
            Trade.block_time.isnot(None),
        )
    ).one()

    span_days = 0.0
    if oldest_at is not None and newest_at is not None:
        span_days = max(
            0.0,
            (newest_at - oldest_at).total_seconds() / 86400.0,
        )

    return {
        "trade_count": int(count or 0),
        "oldest_at": oldest_at,
        "newest_at": newest_at,
        "history_span_days": round(span_days, 6),
    }


def _auto_candidates(db: Session) -> list[DiscoveredWallet]:
    quality_priority = {
        "COPIABILE": 2,
        "OSSERVAZIONE": 1,
    }
    rows = list(
        db.scalars(
            select(DiscoveredWallet).where(
                DiscoveredWallet.quality_classification.in_(
                    sorted(AUTO_ALLOWED_QUALITY_CLASSIFICATIONS)
                )
            )
        )
    )
    rows.sort(
        key=lambda wallet: (
            quality_priority.get(str(wallet.quality_classification), 0),
            float(wallet.quality_score or 0.0),
            float(wallet.ranking_score or 0.0),
            float(wallet.smart_score or 0.0),
            int(wallet.reliable_positions or 0),
            -int(wallet.id or 0),
        ),
        reverse=True,
    )
    return rows


def _research_candidates(db: Session) -> list[DiscoveredWallet]:
    trade_count = func.count(Trade.id).label("trade_count")
    rows = list(
        db.execute(
            select(DiscoveredWallet, trade_count)
            .join(
                Trade,
                Trade.wallet_address == DiscoveredWallet.wallet_address,
            )
            .where(
                Trade.success.is_(True),
                DiscoveredWallet.quality_classification.notin_(
                    sorted(EXPLICIT_RESEARCH_REJECTED_CLASSIFICATIONS)
                ),
            )
            .group_by(DiscoveredWallet.id)
        )
    )
    rows.sort(
        key=lambda item: (
            int(item[1] or 0),
            float(item[0].backtest_history_span_days or 0.0),
            int(item[0].reliable_positions or 0),
            float(item[0].quality_score or 0.0),
            float(item[0].ranking_score or 0.0),
            -int(item[0].id or 0),
        ),
        reverse=True,
    )
    return [item[0] for item in rows]


def _wallet_plan_row(
    db: Session,
    wallet_address: str,
    wallet: DiscoveredWallet | None,
    *,
    selection_reason: str,
) -> dict[str, Any]:
    stats = _trade_stats(db, wallet_address)
    if wallet is None:
        return {
            "wallet_address": wallet_address,
            "selection_reason": selection_reason,
            "evidence_only": True,
            "wallet_record_present": False,
            "quality_classification": "NOT_REGISTERED",
            "quality_eligible": False,
            "quality_score": 0.0,
            "ranking_score": 0.0,
            "smart_score": 0.0,
            "promotion_status": "NOT_REGISTERED",
            "promotion_eligible": False,
            "extended_history_status": "EXTERNAL_EVIDENCE_ONLY",
            "extended_history_lookback_days": 0,
            "extended_history_stop_reason": None,
            **stats,
        }

    return {
        "wallet_address": wallet.wallet_address,
        "selection_reason": selection_reason,
        "evidence_only": True,
        "wallet_record_present": True,
        "quality_classification": wallet.quality_classification,
        "quality_eligible": bool(wallet.quality_eligible),
        "quality_score": float(wallet.quality_score or 0.0),
        "ranking_score": float(wallet.ranking_score or 0.0),
        "smart_score": float(wallet.smart_score or 0.0),
        "promotion_status": wallet.promotion_status,
        "promotion_eligible": bool(wallet.promotion_eligible),
        "extended_history_status": wallet.extended_history_status,
        "extended_history_lookback_days": int(
            wallet.extended_history_lookback_days or 0
        ),
        "extended_history_stop_reason": wallet.extended_history_stop_reason,
        **stats,
    }


def preview_gen4_history_acquisition(
    db: Session,
    *,
    wallet_addresses: Iterable[str] | None = None,
    lookback_days: int = 45,
    max_wallets: int = 2,
    max_helius_requests_per_wallet: int = 10,
    page_size: int = 100,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    (
        effective_lookback,
        effective_max_wallets,
        effective_requests,
        effective_page_size,
    ) = _validate_limits(
        lookback_days=lookback_days,
        max_wallets=max_wallets,
        max_helius_requests_per_wallet=max_helius_requests_per_wallet,
        page_size=page_size,
    )
    requested_wallets = _normalize_wallets(wallet_addresses)

    eligible_rows = _auto_candidates(db)
    research_rows = _research_candidates(db)
    selected: list[tuple[str, DiscoveredWallet | None, str]] = []
    rejected: list[dict[str, str]] = []

    for wallet_address in requested_wallets:
        row = db.scalar(
            select(DiscoveredWallet).where(
                DiscoveredWallet.wallet_address == wallet_address
            )
        )
        if row is None:
            selected.append(
                (
                    wallet_address,
                    None,
                    "EXPLICIT_EXTERNAL_EVIDENCE_ONLY",
                )
            )
            continue
        quality = str(row.quality_classification or "NON_ANALIZZATO")
        if quality in EXPLICIT_RESEARCH_REJECTED_CLASSIFICATIONS:
            rejected.append(
                {
                    "wallet_address": wallet_address,
                    "reason": "SUSPICIOUS_WALLET_REJECTED",
                }
            )
            continue
        reason = (
            "EXPLICIT_ELIGIBLE_WALLET"
            if quality in AUTO_ALLOWED_QUALITY_CLASSIFICATIONS
            else "EXPLICIT_RESEARCH_EVIDENCE_ONLY"
        )
        selected.append((wallet_address, row, reason))

    def append_candidates(rows: list[DiscoveredWallet], reason: str) -> None:
        selected_addresses = {item[0] for item in selected}
        for row in rows:
            if len(selected) >= effective_max_wallets:
                break
            if row.wallet_address in selected_addresses:
                continue
            selected.append((row.wallet_address, row, reason))
            selected_addresses.add(row.wallet_address)

    append_candidates(eligible_rows, "AUTO_ELIGIBLE_WALLET")
    append_candidates(research_rows, "AUTO_RESEARCH_EXISTING_EVIDENCE")

    selected = selected[:effective_max_wallets]
    plan_rows = [
        _wallet_plan_row(
            db,
            wallet_address,
            row,
            selection_reason=reason,
        )
        for wallet_address, row, reason in selected
    ]

    return {
        "policy_version": GEN4_HISTORY_ACQUISITION_POLICY_VERSION,
        "scope": "CONTROLLED_HISTORICAL_DATA_ACQUISITION_ONLY",
        "evaluated_at": evaluated_at or _utc_now(),
        "confirmation_required": GEN4_HISTORY_ACQUISITION_CONFIRMATION,
        "parameters": {
            "lookback_days": effective_lookback,
            "max_wallets": effective_max_wallets,
            "max_helius_requests_per_wallet": effective_requests,
            "page_size": effective_page_size,
            "maximum_total_helius_requests": (
                effective_max_wallets * effective_requests
            ),
        },
        "selected_wallet_count": len(plan_rows),
        "selected_wallets": plan_rows,
        "rejected_requested_wallets": rejected,
        "safety": {
            "preview_read_only": True,
            "force_backfill_allowed": False,
            "automatic_quality_classifications": sorted(
                AUTO_ALLOWED_QUALITY_CLASSIFICATIONS
            ),
            "explicit_research_rejected_classifications": sorted(
                EXPLICIT_RESEARCH_REJECTED_CLASSIFICATIONS
            ),
            "research_evidence_only": True,
            "explicit_external_wallet_evidence_only": True,
            "external_wallet_record_creation_allowed": False,
            "quality_gate_bypassed_for_copying": False,
            "promotion_changes_allowed": False,
            "m31_run_connected": False,
            "paper_execution_connected": False,
            "live_execution_authorized": False,
            "worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
            "signer_connected": False,
            "transaction_submission_connected": False,
        },
        "evidence_note": (
            "Il backfill può alimentare SIGNAL_ONLY_PROXY e SIMPLE_COPY_BASELINE. "
            "Non può ricreare retroattivamente snapshot token o backtest point-in-time; "
            "la prova STRICT_GEN4 richiede raccolta forward senza look-ahead."
        ),
    }


def run_gen4_history_acquisition(
    db: Session,
    *,
    confirmation: str,
    wallet_addresses: Iterable[str] | None = None,
    lookback_days: int = 45,
    max_wallets: int = 2,
    max_helius_requests_per_wallet: int = 10,
    page_size: int = 100,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if confirmation != GEN4_HISTORY_ACQUISITION_CONFIRMATION:
        raise Gen4HistoryAcquisitionError(
            "Conferma manuale non valida.",
            code="CONFIRMATION_REQUIRED",
        )

    plan = preview_gen4_history_acquisition(
        db,
        wallet_addresses=wallet_addresses,
        lookback_days=lookback_days,
        max_wallets=max_wallets,
        max_helius_requests_per_wallet=max_helius_requests_per_wallet,
        page_size=page_size,
        evaluated_at=evaluated_at,
    )
    if not plan["selected_wallets"]:
        rejection_summary = ", ".join(
            f"{item['wallet_address']}:{item['reason']}"
            for item in plan["rejected_requested_wallets"]
        )
        message = "Nessun wallet disponibile per acquisizione evidence-only."
        if rejection_summary:
            message += f" Richieste rifiutate: {rejection_summary}."
        raise Gen4HistoryAcquisitionError(
            message,
            code="NO_EVIDENCE_WALLETS",
        )

    results: list[dict[str, Any]] = []
    total_requests = 0
    total_imported = 0
    total_updated = 0
    total_parse_failures = 0

    for planned in plan["selected_wallets"]:
        wallet_address = planned["wallet_address"]
        wallet_before = db.scalar(
            select(DiscoveredWallet).where(
                DiscoveredWallet.wallet_address == wallet_address
            )
        )
        wallet_record_present_before = wallet_before is not None
        protected_before = (
            {
                "quality_classification": wallet_before.quality_classification,
                "quality_eligible": bool(wallet_before.quality_eligible),
                "promotion_status": wallet_before.promotion_status,
                "promotion_eligible": bool(wallet_before.promotion_eligible),
            }
            if wallet_before is not None
            else None
        )
        stats_before = _trade_stats(db, wallet_address)

        try:
            run = candidate_history_service.run_extended_candidate_history(
                db,
                wallet_address=wallet_address,
                lookback_days=plan["parameters"]["lookback_days"],
                max_helius_requests=plan["parameters"][
                    "max_helius_requests_per_wallet"
                ],
                page_size=plan["parameters"]["page_size"],
                force=False,
                evidence_only=True,
                now=evaluated_at,
            )
            result_status = run.status
            stop_reason = run.stop_reason
            error_code = run.error_code
            error_message = run.error_message
            helius_requests = int(run.helius_requests or 0)
            imported = int(run.trades_imported or 0)
            updated = int(run.trades_updated or 0)
            parse_failures = int(run.parse_failures or 0)
            run_id = run.run_id
        except ValueError as error:
            message = str(error)
            if "già stato completato" in message:
                result_status = "SKIPPED_ALREADY_COMPLETE"
                stop_reason = "ALREADY_COMPLETE_FOR_LOOKBACK"
                error_code = None
                error_message = None
            else:
                result_status = "SKIPPED_POLICY"
                stop_reason = "POLICY_REJECTED"
                error_code = "POLICY_REJECTED"
                error_message = message[:500]
            helius_requests = 0
            imported = 0
            updated = 0
            parse_failures = 0
            run_id = None

        wallet_after = db.scalar(
            select(DiscoveredWallet).where(
                DiscoveredWallet.wallet_address == wallet_address
            )
        )
        if not wallet_record_present_before and wallet_after is not None:
            raise Gen4HistoryAcquisitionError(
                "Il backfill evidence-only ha creato un record discovered_wallets "
                "non autorizzato.",
                code="EXTERNAL_WALLET_RECORD_CREATED",
                status_code=500,
            )
        if wallet_record_present_before and wallet_after is None:
            raise Gen4HistoryAcquisitionError(
                "Il record discovered_wallets esistente non è più disponibile.",
                code="DISCOVERED_WALLET_RECORD_MISSING",
                status_code=500,
            )
        if wallet_after is not None and protected_before is not None:
            protected_after = {
                "quality_classification": wallet_after.quality_classification,
                "quality_eligible": bool(wallet_after.quality_eligible),
                "promotion_status": wallet_after.promotion_status,
                "promotion_eligible": bool(wallet_after.promotion_eligible),
            }
            if protected_after != protected_before:
                wallet_after.quality_classification = protected_before[
                    "quality_classification"
                ]
                wallet_after.quality_eligible = protected_before["quality_eligible"]
                wallet_after.promotion_status = protected_before["promotion_status"]
                wallet_after.promotion_eligible = protected_before[
                    "promotion_eligible"
                ]
                db.commit()
                raise Gen4HistoryAcquisitionError(
                    "Il backfill ha tentato di modificare campi qualità/promozione; "
                    "i valori originari sono stati ripristinati.",
                    code="PROTECTED_WALLET_FIELDS_CHANGED",
                    status_code=500,
                )

        stats_after = _trade_stats(db, wallet_address)
        total_requests += helius_requests
        total_imported += imported
        total_updated += updated
        total_parse_failures += parse_failures
        results.append(
            {
                "wallet_address": wallet_address,
                "run_id": run_id,
                "status": result_status,
                "stop_reason": stop_reason,
                "error_code": error_code,
                "error_message": error_message,
                "helius_requests": helius_requests,
                "trades_imported": imported,
                "trades_updated": updated,
                "parse_failures": parse_failures,
                "before": stats_before,
                "after": stats_after,
                "protected_fields_unchanged": True,
                "wallet_record_present_before": wallet_record_present_before,
                "wallet_record_present_after": wallet_after is not None,
                "discovered_wallet_record_created": (
                    not wallet_record_present_before and wallet_after is not None
                ),
            }
        )

    if total_requests > plan["parameters"]["maximum_total_helius_requests"]:
        raise Gen4HistoryAcquisitionError(
            "Il conteggio Helius ha superato il budget pianificato.",
            code="REQUEST_BUDGET_INVARIANT_BROKEN",
            status_code=500,
        )

    profitability = preview_gen4_profitability(
        db,
        evaluated_at=evaluated_at or _utc_now(),
    )

    return {
        "policy_version": GEN4_HISTORY_ACQUISITION_POLICY_VERSION,
        "scope": "CONTROLLED_HISTORICAL_DATA_ACQUISITION_ONLY",
        "completed_at": _utc_now(),
        "plan": plan,
        "wallet_results": results,
        "summary": {
            "wallets_attempted": len(results),
            "helius_requests": total_requests,
            "trades_imported": total_imported,
            "trades_updated": total_updated,
            "parse_failures": total_parse_failures,
        },
        "gen4_profitability_after_acquisition": profitability,
        "safety": {
            "force_used": False,
            "evidence_only_used": True,
            "quality_recalculation_executed": False,
            "quality_or_promotion_fields_changed": False,
            "external_discovered_wallet_records_created": 0,
            "m31_run_executed": False,
            "paper_orders_created": 0,
            "live_orders_created": 0,
            "transactions_built": 0,
            "transactions_signed": 0,
            "transactions_sent": 0,
            "live_execution_authorized": False,
            "worker_started": False,
            "scheduler_started": False,
            "stream_started": False,
            "signer_connected": False,
        },
    }
