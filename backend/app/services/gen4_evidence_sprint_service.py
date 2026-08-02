from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services import candidate_history_service
from backend.app.services.blockchain_parser_gen4_profitability_service import (
    preview_gen4_profitability,
)
from backend.app.services.helius import HeliusRequestError, get_wallet_history

GEN4_EVIDENCE_SPRINT_CONFIRMATION = "RUN_GEN4_EVIDENCE_SPRINT"
GEN4_EVIDENCE_SPRINT_POLICY_VERSION = (
    "canonical-parser-gen4-evidence-sprint/1"
)
SOL_MINT = "So11111111111111111111111111111111111111112"
MAX_TOTAL_HELIUS_REQUESTS = 40
REJECTED_QUALITY_CLASSIFICATIONS = frozenset({"SOSPETTO"})


class Gen4EvidenceSprintError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _transaction_time(item: dict[str, Any]) -> datetime | None:
    raw = item.get("timestamp")
    if raw is None:
        raw = item.get("blockTime")
    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return datetime.fromtimestamp(numeric, tz=timezone.utc)


def _safe_error(error: object) -> str:
    message = str(error or "Errore non specificato.")
    lowered = message.lower()
    if "api-key=" in lowered or "x-api-key" in lowered:
        return "Errore provider. Dettagli sensibili rimossi."
    return message[:500]


def _wallet_stats(db: Session, wallet_address: str) -> dict[str, Any]:
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
    oldest = _aware(oldest_at)
    newest = _aware(newest_at)
    span = 0.0
    if oldest is not None and newest is not None:
        span = max(0.0, (newest - oldest).total_seconds() / 86400.0)
    return {
        "trade_count": int(count or 0),
        "oldest_at": oldest,
        "newest_at": newest,
        "history_span_days": round(span, 6),
    }


def _seed_tokens(
    db: Session,
    *,
    wallet_address: str,
    lookback_days: int,
    evaluated_at: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    cutoff = evaluated_at - timedelta(days=lookback_days)
    rows = list(
        db.execute(
            select(Trade.token_mint, Trade.side, func.count(Trade.id))
            .where(
                Trade.wallet_address == wallet_address,
                Trade.success.is_(True),
                Trade.block_time.isnot(None),
                Trade.block_time >= cutoff,
                Trade.block_time <= evaluated_at,
                Trade.token_mint.isnot(None),
            )
            .group_by(Trade.token_mint, Trade.side)
        )
    )
    tokens: dict[str, dict[str, Any]] = {}
    for token_mint, side, count in rows:
        token = str(token_mint or "").strip()
        normalized_side = str(side or "").strip().upper()
        if not token or token == SOL_MINT or normalized_side not in {"BUY", "SELL"}:
            continue
        entry = tokens.setdefault(
            token,
            {"token_mint": token, "buy_count": 0, "sell_count": 0, "trade_count": 0},
        )
        entry["trade_count"] += int(count or 0)
        if normalized_side == "BUY":
            entry["buy_count"] += int(count or 0)
        else:
            entry["sell_count"] += int(count or 0)
    ranked = list(tokens.values())
    ranked.sort(
        key=lambda item: (
            min(item["buy_count"], item["sell_count"]),
            item["trade_count"],
            item["sell_count"],
        ),
        reverse=True,
    )
    return ranked[:limit]


def _extract_fee_payers(
    transactions: Iterable[dict[str, Any]],
    *,
    excluded_wallets: set[str],
) -> set[str]:
    result: set[str] = set()
    for transaction in transactions:
        if str(transaction.get("type") or "").upper() != "SWAP":
            continue
        wallet = str(transaction.get("feePayer") or "").strip()
        if wallet in excluded_wallets or not 32 <= len(wallet) <= 64:
            continue
        result.add(wallet)
    return result


def _probe_metrics(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [
        timestamp
        for timestamp in (_transaction_time(item) for item in transactions)
        if timestamp is not None
    ]
    oldest = min(timestamps) if timestamps else None
    newest = max(timestamps) if timestamps else None
    span = 0.0
    if oldest is not None and newest is not None:
        span = max(0.0, (newest - oldest).total_seconds() / 86400.0)
    return {
        "transactions": len(transactions),
        "oldest_at": oldest,
        "newest_at": newest,
        "first_page_span_days": round(span, 6),
    }


def _candidate_score(candidate: dict[str, Any]) -> float:
    local_span = float(candidate["local_stats"]["history_span_days"])
    probe_span = float(candidate["probe"]["first_page_span_days"])
    shared_tokens = len(candidate["shared_tokens"])
    probe_transactions = int(candidate["probe"]["transactions"])
    completed_local_bonus = 10000.0 if local_span >= 21.0 else 0.0
    manageable_activity_bonus = min(probe_span, 45.0) * 100.0
    shared_bonus = shared_tokens * 25.0
    sample_bonus = min(probe_transactions, 100) / 10.0
    return round(
        completed_local_bonus
        + local_span * 10.0
        + manageable_activity_bonus
        + shared_bonus
        + sample_bonus,
        6,
    )


def _validate_limits(
    *,
    lookback_days: int,
    max_token_discovery_requests: int,
    max_candidate_probes: int,
    max_companions: int,
    max_backfill_requests_per_wallet: int,
    page_size: int,
) -> dict[str, int]:
    values = {
        "lookback_days": int(lookback_days),
        "max_token_discovery_requests": int(max_token_discovery_requests),
        "max_candidate_probes": int(max_candidate_probes),
        "max_companions": int(max_companions),
        "max_backfill_requests_per_wallet": int(max_backfill_requests_per_wallet),
        "page_size": int(page_size),
    }
    if not 21 <= values["lookback_days"] <= 90:
        raise Gen4EvidenceSprintError(
            "lookback_days deve essere compreso tra 21 e 90.",
            code="INVALID_LOOKBACK_DAYS",
        )
    if not 1 <= values["max_token_discovery_requests"] <= 8:
        raise Gen4EvidenceSprintError(
            "max_token_discovery_requests deve essere compreso tra 1 e 8.",
            code="INVALID_TOKEN_DISCOVERY_BUDGET",
        )
    if not 1 <= values["max_candidate_probes"] <= 12:
        raise Gen4EvidenceSprintError(
            "max_candidate_probes deve essere compreso tra 1 e 12.",
            code="INVALID_CANDIDATE_PROBE_BUDGET",
        )
    if not 1 <= values["max_companions"] <= 2:
        raise Gen4EvidenceSprintError(
            "max_companions deve essere compreso tra 1 e 2.",
            code="INVALID_MAX_COMPANIONS",
        )
    if not 1 <= values["max_backfill_requests_per_wallet"] <= 20:
        raise Gen4EvidenceSprintError(
            "max_backfill_requests_per_wallet deve essere compreso tra 1 e 20.",
            code="INVALID_BACKFILL_BUDGET",
        )
    if not 10 <= values["page_size"] <= 100:
        raise Gen4EvidenceSprintError(
            "page_size deve essere compreso tra 10 e 100.",
            code="INVALID_PAGE_SIZE",
        )
    maximum = (
        values["max_token_discovery_requests"]
        + values["max_candidate_probes"]
        + values["max_companions"]
        * values["max_backfill_requests_per_wallet"]
    )
    if maximum > MAX_TOTAL_HELIUS_REQUESTS:
        raise Gen4EvidenceSprintError(
            "Il budget Helius totale supera il limite hard di 40 richieste.",
            code="TOTAL_REQUEST_BUDGET_EXCEEDED",
        )
    values["maximum_total_helius_requests"] = maximum
    return values


def preview_gen4_evidence_sprint(
    db: Session,
    *,
    priority_wallet: str,
    lookback_days: int = 45,
    max_token_discovery_requests: int = 3,
    max_candidate_probes: int = 8,
    max_companions: int = 1,
    max_backfill_requests_per_wallet: int = 15,
    page_size: int = 100,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at) or _utc_now()
    wallet = str(priority_wallet or "").strip()
    if not 32 <= len(wallet) <= 64:
        raise Gen4EvidenceSprintError(
            "priority_wallet non valido.",
            code="INVALID_PRIORITY_WALLET",
        )
    parameters = _validate_limits(
        lookback_days=lookback_days,
        max_token_discovery_requests=max_token_discovery_requests,
        max_candidate_probes=max_candidate_probes,
        max_companions=max_companions,
        max_backfill_requests_per_wallet=max_backfill_requests_per_wallet,
        page_size=page_size,
    )
    stats = _wallet_stats(db, wallet)
    seed_tokens = _seed_tokens(
        db,
        wallet_address=wallet,
        lookback_days=parameters["lookback_days"],
        evaluated_at=now,
        limit=parameters["max_token_discovery_requests"],
    )
    return {
        "policy_version": GEN4_EVIDENCE_SPRINT_POLICY_VERSION,
        "scope": "CONTROLLED_GEN4_EVIDENCE_ACQUISITION_AND_DIAGNOSTIC",
        "evaluated_at": now,
        "confirmation_required": GEN4_EVIDENCE_SPRINT_CONFIRMATION,
        "priority_wallet": wallet,
        "priority_wallet_stats": stats,
        "seed_tokens": seed_tokens,
        "parameters": parameters,
        "safety": {
            "preview_read_only": True,
            "quality_recalculation_allowed": False,
            "promotion_changes_allowed": False,
            "discovered_wallet_creation_allowed": False,
            "force_backfill_allowed": False,
            "m31_run_connected": False,
            "paper_execution_connected": False,
            "live_execution_authorized": False,
            "worker_connected": False,
            "scheduler_connected": False,
            "signer_connected": False,
            "transaction_submission_connected": False,
        },
        "interpretation": {
            "strict_gen4": "Resta forward-only e non viene ricostruita retroattivamente.",
            "signal_only_proxy": "Può mostrare l'economia storica del consenso senza provare la profittabilità strict.",
            "simple_copy_baseline": "Confronto con copia di un singolo wallet usando le stesse assunzioni di esecuzione.",
        },
    }


def _economic_status(report: dict[str, Any]) -> str:
    proxy = report.get("proxy_metrics") or {}
    closed = int(proxy.get("closed_trades") or 0)
    minimum = int(
        (report.get("policy_snapshot") or {}).get(
            "minimum_evaluable_closed_trades", 30
        )
    )
    if closed >= minimum:
        return "PROXY_EVALUABLE_NOT_PROOF"
    if closed > 0:
        return "PROXY_SAMPLE_VISIBLE"
    windows = report.get("windows") or []
    max_qualified = max(
        (int(window.get("proxy_qualified_wallet_count") or 0) for window in windows),
        default=0,
    )
    signal_count = sum(
        int(window.get("proxy_signal_count") or 0) for window in windows
    )
    if max_qualified >= 2 and signal_count == 0:
        return "QUALIFIED_WALLETS_BUT_NO_CONSENSUS_SIGNALS"
    return "WALLET_TRAINING_GATES_NOT_MET"


def _diagnostic_summary(report: dict[str, Any]) -> dict[str, Any]:
    reason_counts: Counter[str] = Counter()
    qualified_by_window: list[dict[str, Any]] = []
    for window in report.get("windows") or []:
        evidence = window.get("evidence") or {}
        training = evidence.get("proxy_training_wallet_metrics") or {}
        qualified = []
        for wallet, metrics in training.items():
            if bool(metrics.get("qualified")):
                qualified.append(wallet)
            for reason in metrics.get("reason_codes") or []:
                reason_counts[str(reason)] += 1
        signal_audit = evidence.get("proxy_signal_audit") or {}
        qualified_by_window.append(
            {
                "sequence": window.get("sequence"),
                "train_start_at": window.get("train_start_at"),
                "train_end_at": window.get("train_end_at"),
                "test_start_at": window.get("test_start_at"),
                "test_end_at": window.get("test_end_at"),
                "qualified_wallets": sorted(qualified),
                "proxy_signal_count": int(window.get("proxy_signal_count") or 0),
                "baseline_signal_count": int(window.get("baseline_signal_count") or 0),
                "proxy_skipped_reason_counts": signal_audit.get(
                    "skipped_reason_counts", {}
                ),
            }
        )
    return {
        "economic_result_status": _economic_status(report),
        "training_gate_reason_counts": dict(sorted(reason_counts.items())),
        "windows": qualified_by_window,
    }


def run_gen4_evidence_sprint(
    db: Session,
    *,
    confirmation: str,
    priority_wallet: str,
    lookback_days: int = 45,
    max_token_discovery_requests: int = 3,
    max_candidate_probes: int = 8,
    max_companions: int = 1,
    max_backfill_requests_per_wallet: int = 15,
    page_size: int = 100,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if confirmation != GEN4_EVIDENCE_SPRINT_CONFIRMATION:
        raise Gen4EvidenceSprintError(
            "Conferma manuale non valida.",
            code="CONFIRMATION_REQUIRED",
        )
    plan = preview_gen4_evidence_sprint(
        db,
        priority_wallet=priority_wallet,
        lookback_days=lookback_days,
        max_token_discovery_requests=max_token_discovery_requests,
        max_candidate_probes=max_candidate_probes,
        max_companions=max_companions,
        max_backfill_requests_per_wallet=max_backfill_requests_per_wallet,
        page_size=page_size,
        evaluated_at=evaluated_at,
    )
    now = _aware(evaluated_at) or _utc_now()
    priority = plan["priority_wallet"]
    if float(plan["priority_wallet_stats"]["history_span_days"]) < 21.0:
        raise Gen4EvidenceSprintError(
            "Il wallet prioritario non possiede ancora 21 giorni di storico.",
            code="PRIORITY_HISTORY_INSUFFICIENT",
        )
    if not plan["seed_tokens"]:
        raise Gen4EvidenceSprintError(
            "Nessun token utile disponibile per cercare wallet compagni.",
            code="NO_SEED_TOKENS",
        )

    requests_used = 0
    discovery_results: list[dict[str, Any]] = []
    candidate_tokens: dict[str, set[str]] = defaultdict(set)
    candidate_occurrences: Counter[str] = Counter()
    excluded = {priority}
    discovered_wallet_count_before = int(
        db.scalar(select(func.count(DiscoveredWallet.id))) or 0
    )

    for token_row in plan["seed_tokens"]:
        token = token_row["token_mint"]
        try:
            transactions = get_wallet_history(
                token,
                limit=page_size,
                transaction_type="SWAP",
                gte_time=int((now - timedelta(days=lookback_days)).timestamp()),
                lte_time=int(now.timestamp()),
                commitment="confirmed",
                token_accounts="balanceChanged",
                max_retries=0,
            )
            requests_used += 1
            wallets = _extract_fee_payers(
                transactions,
                excluded_wallets=excluded,
            )
            for transaction in transactions:
                if str(transaction.get("type") or "").upper() != "SWAP":
                    continue
                wallet = str(transaction.get("feePayer") or "").strip()
                if wallet not in wallets:
                    continue
                candidate_tokens[wallet].add(token)
                candidate_occurrences[wallet] += 1
            discovery_results.append(
                {
                    "token_mint": token,
                    "status": "COMPLETED",
                    "transactions": len(transactions),
                    "wallets_found": len(wallets),
                    "error": None,
                }
            )
        except HeliusRequestError as error:
            requests_used += 1
            discovery_results.append(
                {
                    "token_mint": token,
                    "status": "FAILED",
                    "transactions": 0,
                    "wallets_found": 0,
                    "error": _safe_error(error.message),
                    "error_code": error.error_code,
                    "http_status": error.status_code,
                }
            )

    known_rows = {
        row.wallet_address: row
        for row in db.scalars(
            select(DiscoveredWallet).where(
                DiscoveredWallet.wallet_address.in_(sorted(candidate_tokens))
            )
        )
    } if candidate_tokens else {}

    preliminary = []
    for wallet, shared_tokens in candidate_tokens.items():
        row = known_rows.get(wallet)
        quality = str(
            row.quality_classification if row is not None else "NOT_REGISTERED"
        )
        if quality in REJECTED_QUALITY_CLASSIFICATIONS:
            continue
        local_stats = _wallet_stats(db, wallet)
        preliminary.append(
            {
                "wallet_address": wallet,
                "wallet_record_present": row is not None,
                "quality_classification": quality,
                "shared_tokens": sorted(shared_tokens),
                "discovery_occurrences": int(candidate_occurrences[wallet]),
                "local_stats": local_stats,
            }
        )
    preliminary.sort(
        key=lambda item: (
            len(item["shared_tokens"]),
            item["discovery_occurrences"],
            item["local_stats"]["history_span_days"],
            item["local_stats"]["trade_count"],
        ),
        reverse=True,
    )

    probed: list[dict[str, Any]] = []
    for candidate in preliminary[: plan["parameters"]["max_candidate_probes"]]:
        wallet = candidate["wallet_address"]
        try:
            transactions = get_wallet_history(
                wallet,
                limit=page_size,
                transaction_type="SWAP",
                gte_time=int((now - timedelta(days=lookback_days)).timestamp()),
                lte_time=int(now.timestamp()),
                commitment="confirmed",
                token_accounts="balanceChanged",
                max_retries=0,
            )
            requests_used += 1
            probe = _probe_metrics(transactions)
            item = {**candidate, "probe": probe, "probe_status": "COMPLETED"}
            item["score"] = _candidate_score(item)
            probed.append(item)
        except HeliusRequestError as error:
            requests_used += 1
            probed.append(
                {
                    **candidate,
                    "probe": {
                        "transactions": 0,
                        "oldest_at": None,
                        "newest_at": None,
                        "first_page_span_days": 0.0,
                    },
                    "probe_status": "FAILED",
                    "score": -1.0,
                    "error": _safe_error(error.message),
                    "error_code": error.error_code,
                    "http_status": error.status_code,
                }
            )
    probed.sort(key=lambda item: float(item.get("score") or -1.0), reverse=True)
    usable = [
        item
        for item in probed
        if item.get("probe_status") == "COMPLETED"
        and (
            float(item["local_stats"]["history_span_days"]) >= 21.0
            or float(item["probe"]["first_page_span_days"]) >= 2.0
        )
    ]
    selected = usable[: plan["parameters"]["max_companions"]]

    backfill_results: list[dict[str, Any]] = []
    for candidate in selected:
        wallet = candidate["wallet_address"]
        before = _wallet_stats(db, wallet)
        if float(before["history_span_days"]) >= 21.0:
            backfill_results.append(
                {
                    "wallet_address": wallet,
                    "status": "SKIPPED_LOCAL_HISTORY_SUFFICIENT",
                    "stop_reason": "LOCAL_HISTORY_AT_LEAST_21_DAYS",
                    "helius_requests": 0,
                    "trades_imported": 0,
                    "trades_updated": 0,
                    "before": before,
                    "after": before,
                }
            )
            continue
        try:
            run = candidate_history_service.run_extended_candidate_history(
                db,
                wallet_address=wallet,
                lookback_days=lookback_days,
                max_helius_requests=max_backfill_requests_per_wallet,
                page_size=page_size,
                force=False,
                evidence_only=True,
                now=now,
            )
            used = int(run.helius_requests or 0)
            requests_used += used
            backfill_results.append(
                {
                    "wallet_address": wallet,
                    "status": run.status,
                    "stop_reason": run.stop_reason,
                    "run_id": run.run_id,
                    "helius_requests": used,
                    "trades_imported": int(run.trades_imported or 0),
                    "trades_updated": int(run.trades_updated or 0),
                    "error_code": run.error_code,
                    "error_message": run.error_message,
                    "before": before,
                    "after": _wallet_stats(db, wallet),
                }
            )
        except (ValueError, HeliusRequestError) as error:
            backfill_results.append(
                {
                    "wallet_address": wallet,
                    "status": "FAILED",
                    "stop_reason": "FAILED",
                    "helius_requests": 0,
                    "trades_imported": 0,
                    "trades_updated": 0,
                    "error": _safe_error(error),
                    "before": before,
                    "after": _wallet_stats(db, wallet),
                }
            )

    if requests_used > int(plan["parameters"]["maximum_total_helius_requests"]):
        raise Gen4EvidenceSprintError(
            "Il consumo Helius ha superato il budget dichiarato.",
            code="REQUEST_BUDGET_INVARIANT_VIOLATED",
            status_code=500,
        )

    discovered_wallet_count_after = int(
        db.scalar(select(func.count(DiscoveredWallet.id))) or 0
    )
    if discovered_wallet_count_after != discovered_wallet_count_before:
        raise Gen4EvidenceSprintError(
            "Lo sprint evidence-only ha modificato discovered_wallets.",
            code="DISCOVERED_WALLET_COUNT_CHANGED",
            status_code=500,
        )

    profitability = preview_gen4_profitability(db, evaluated_at=now)
    diagnostic = _diagnostic_summary(profitability)
    return {
        "policy_version": GEN4_EVIDENCE_SPRINT_POLICY_VERSION,
        "scope": "CONTROLLED_GEN4_EVIDENCE_ACQUISITION_AND_DIAGNOSTIC",
        "evaluated_at": now,
        "plan": plan,
        "discovery_results": discovery_results,
        "candidate_count": len(candidate_tokens),
        "probed_candidates": probed,
        "selected_companions": selected,
        "backfill_results": backfill_results,
        "summary": {
            "helius_requests": requests_used,
            "maximum_helius_requests": int(
                plan["parameters"]["maximum_total_helius_requests"]
            ),
            "companions_selected": len(selected),
            "companions_with_21_days": sum(
                1
                for item in selected
                if float(_wallet_stats(db, item["wallet_address"])["history_span_days"])
                >= 21.0
            ),
            "trades_imported": sum(
                int(item.get("trades_imported") or 0) for item in backfill_results
            ),
            "m47_verdict": profitability.get("verdict"),
            "m47_strict_evidence_status": profitability.get(
                "strict_evidence_status"
            ),
            "proxy_closed_trades": int(
                (profitability.get("proxy_metrics") or {}).get("closed_trades")
                or 0
            ),
            "baseline_closed_trades": int(
                (profitability.get("baseline_metrics") or {}).get("closed_trades")
                or 0
            ),
            "economic_result_status": diagnostic["economic_result_status"],
        },
        "gen4_profitability": profitability,
        "diagnostic": diagnostic,
        "safety": {
            "external_requests_performed": requests_used,
            "trade_and_backfill_metadata_writes_allowed": True,
            "raw_provider_capture_may_be_written": True,
            "quality_recalculation_performed": False,
            "promotion_changes_performed": False,
            "discovered_wallet_records_created": False,
            "strict_gen4_reconstructed_retroactively": False,
            "m31_run_performed": False,
            "paper_orders_created": False,
            "live_execution_authorized": False,
            "worker_started": False,
            "scheduler_started": False,
            "signer_connected": False,
            "transaction_submitted": False,
        },
        "interpretation": {
            "strict": (
                "STRICT_GEN4 resta non ricostruibile retroattivamente: richiede "
                "evidenze point-in-time raccolte realmente prima dei segnali."
            ),
            "proxy": (
                "SIGNAL_ONLY_PROXY è il primo risultato economico storico utile, "
                "ma non costituisce prova strict né autorizzazione LIVE."
            ),
            "zero_trade": (
                "Se i trade proxy restano zero, il report diagnostico distingue "
                "gate wallet, assenza di consenso e insufficienza di uscite."
            ),
        },
    }
