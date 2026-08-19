from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4CopyabilityPosition,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    M64_EXPECTED_PARSER_VERSION,
    M64_EXPECTED_POLICY_VERSION,
    canonical_sha256,
)
from backend.app.services.gen4_copyability_aware_discovery_service import (
    M66_DEFAULT_POLICY,
    build_cached_discovery_snapshot,
)


M67_M70_VERSION = "canonical-parser-gen4-zero-helius-pre-micro-live/1"
M67_M70_SCOPE = "M67_M70_ZERO_HELIUS_PRE_MICRO_LIVE_FOUNDATION_READ_ONLY"
M67_M70_SNAPSHOT_SCOPE = "M67_ZERO_HELIUS_UNIFIED_LOCAL_EVIDENCE_SNAPSHOT"
M67_M70_RPC_SCOPE = "M67_ZERO_HELIUS_PUBLIC_RPC_EVIDENCE"
M67_M70_RUN_CONFIRMATION = "RUN_M67_M70_ZERO_HELIUS_READ_ONLY"
M67_M70_CACHE_SCHEMA = "SMARTMONEY_M67_ZERO_HELIUS_PUBLIC_RPC_CACHE_V1"

STATUS_QUALIFIED = "ECONOMICALLY_QUALIFIED_PENDING_SHORT_CANARY"
STATUS_NEEDS_HISTORY = "NEEDS_MORE_PUBLIC_RPC_HISTORY"
STATUS_INACTIVE = "INACTIVE_OR_LOW_ACTIVITY"
STATUS_RESEARCH = "RESEARCH_ONLY"
STATUS_NO_EVIDENCE = "NO_POSITION_LEVEL_EVIDENCE"

_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

M67_M70_DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": M67_M70_VERSION,
    "wallet_inventory_limit": 500,
    "activity_lookback_days": 30,
    "recent_activity_days": 7,
    "signature_page_limit": 100,
    "minimum_recent_transactions": 6,
    "minimum_recent_active_days": 3,
    "maximum_deep_wallets": 3,
    "maximum_signatures_per_deep_wallet": 150,
    "public_rpc_request_cap": 600,
    "public_rpc_maximum_attempts": 4,
    "public_rpc_throttle_seconds": 0.65,
    "starting_capital_sol": 1.0,
    "fixed_buy_size_sol": 0.05,
    "slippage_bps": 100,
    "fee_bps": 10,
    "copy_delay_seconds": 8,
    "delay_penalty_bps_per_minute": 25.0,
    "effective_market_friction_bps": 103.3333,
    "maximum_open_positions": 5,
    "minimum_closed_trades": 100,
    "minimum_recent_closed_trades": 20,
    "minimum_history_span_days": 30.0,
    "minimum_profit_factor": 1.30,
    "minimum_recent_profit_factor": 1.10,
    "minimum_win_rate_percent": 30.0,
    "maximum_drawdown_percent": 15.0,
    "maximum_recent_drawdown_percent": 15.0,
    "minimum_unique_tokens": 10,
    "maximum_token_concentration_percent": 25.0,
    "minimum_stability_windows": 5,
    "minimum_positive_stability_windows": 4,
    "minimum_worst_stability_profit_factor": 0.80,
    "stability_window_size": 20,
    "require_positive_net_without_best_trade": True,
    "consensus_window_seconds": 180,
    "consensus_minimum_independent_wallets": 2,
    "consensus_maximum_wallets": 3,
    "consensus_maximum_token_exposure_sol": 0.10,
    "canary_minimum_observation_hours": 24.0,
    "canary_minimum_entry_attempts": 20,
    "canary_minimum_closed_trades": 10,
    "canary_minimum_webhook_coverage_percent": 95.0,
    "canary_minimum_unsigned_build_coverage_percent": 100.0,
    "canary_maximum_entry_reject_rate_percent": 20.0,
    "canary_maximum_p95_end_to_quote_ms": 5000.0,
    "canary_maximum_p95_price_impact_bps": 500.0,
    "canary_maximum_p95_price_deterioration_bps": 1000.0,
}


class M67M70ZeroHeliusError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return _aware(value)
    try:
        return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _iso(value: datetime | None) -> str | None:
    aware_value = _aware(value)
    return aware_value.isoformat() if aware_value is not None else None


def _finite(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _integer(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M67M70ZeroHeliusError(message)


def _without(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    resolved = {**M67_M70_DEFAULT_POLICY, **dict(policy or {})}
    _require(
        resolved.get("policy_version") == M67_M70_VERSION,
        "Versione policy M67-M70 inattesa.",
    )
    _require(
        math.isclose(_finite(resolved["starting_capital_sol"]), 1.0, abs_tol=1e-12),
        "Capitale Gen4 diverso da 1 SOL.",
    )
    _require(
        math.isclose(_finite(resolved["fixed_buy_size_sol"]), 0.05, abs_tol=1e-12),
        "Size Gen4 diversa da 0.05 SOL.",
    )
    _require(_integer(resolved["slippage_bps"]) == 100, "Slippage Gen4 inatteso.")
    _require(_integer(resolved["fee_bps"]) == 10, "Commissione Gen4 inattesa.")
    _require(_integer(resolved["copy_delay_seconds"]) == 8, "Delay Gen4 inatteso.")
    _require(
        math.isclose(
            _finite(resolved["delay_penalty_bps_per_minute"]),
            25.0,
            abs_tol=1e-12,
        ),
        "Penalita delay Gen4 inattesa.",
    )
    expected_friction = _finite(resolved["slippage_bps"]) + (
        _finite(resolved["copy_delay_seconds"]) / 60.0
        * _finite(resolved["delay_penalty_bps_per_minute"])
    )
    _require(
        math.isclose(
            expected_friction,
            _finite(resolved["effective_market_friction_bps"]),
            abs_tol=1e-4,
        ),
        "Friction Gen4 incoerente.",
    )
    _require(
        1 <= _integer(resolved["maximum_deep_wallets"]) <= 3,
        "Numero wallet deep fuori contratto.",
    )
    _require(
        30 <= _integer(resolved["public_rpc_request_cap"]) <= 2000,
        "Cap RPC pubblico fuori contratto.",
    )
    return resolved


def validate_external_m64_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(
        report.get("scope") == "M64_GEN4_83_PLUS_RECONSTRUCTED_CLOSED_TRADES_READ_ONLY",
        "Scope report M64 inatteso.",
    )
    integrity = dict(report.get("integrity") or {})
    expected = str(integrity.get("report_payload_sha256") or "")
    _require(len(expected) == 64, "Hash interno report M64 assente.")
    _require(
        expected == canonical_sha256(_without(report, "integrity")),
        "Hash interno report M64 non valido.",
    )
    campaign = dict(report.get("campaign") or {})
    samples = dict(report.get("samples") or {})
    official = dict(samples.get("official_realtime") or {})
    reconstructed = dict(samples.get("reconstructed") or {})
    combined = dict(samples.get("combined_equivalent") or {})
    wallet = str(campaign.get("wallet") or "")
    _require(bool(_SOLANA_ADDRESS.fullmatch(wallet)), "Wallet M64 non valido.")
    _require(_integer(official.get("closed_trade_count")) == 83, "M64 ufficiali != 83.")
    _require(
        _integer(reconstructed.get("closed_trade_count")) == 17,
        "M64 ricostruiti != 17.",
    )
    _require(
        _integer(combined.get("closed_trade_count")) == 100,
        "M64 equivalente != 100.",
    )
    safety = dict(report.get("safety") or {})
    for key in (
        "helius_requests",
        "database_writes",
        "backend_posts",
        "paper_orders",
        "live_orders",
        "signed_transactions",
        "submitted_transactions",
    ):
        _require(_integer(safety.get(key)) == 0, f"Safety M64 violata: {key}.")
    _require(safety.get("official_counter_mutated") is False, "M64 ha mutato gli 83.")
    _require(
        safety.get("recovery_counted_as_realtime_proof") is False,
        "M64 conta recovery come prova realtime.",
    )
    return {
        "wallet_address": wallet,
        "report_payload_sha256": expected,
        "official": official,
        "reconstructed": reconstructed,
        "combined": combined,
        "verdict": dict(report.get("verdict") or {}),
    }


def validate_external_m65_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(
        report.get("scope") == "M65_GEN4_DEFINITIVE_WALLET_QUALIFICATION_GATE_READ_ONLY",
        "Scope report M65 inatteso.",
    )
    integrity = dict(report.get("integrity") or {})
    expected = str(integrity.get("gate_payload_sha256") or "")
    _require(len(expected) == 64, "Hash interno report M65 assente.")
    _require(
        expected == canonical_sha256(_without(report, "integrity")),
        "Hash interno report M65 non valido.",
    )
    candidate = dict(report.get("candidate") or {})
    wallet = str(candidate.get("wallet") or "")
    _require(bool(_SOLANA_ADDRESS.fullmatch(wallet)), "Wallet M65 non valido.")
    verdict = dict(report.get("verdict") or {})
    _require(
        verdict.get("micro_live_execution_authorized") is False,
        "M65 non puo autorizzare esecuzione Micro Live.",
    )
    safety = dict(report.get("safety") or {})
    for key in (
        "helius_requests",
        "database_writes",
        "backend_posts",
        "jupiter_requests",
        "paper_orders",
        "live_orders",
        "signed_transactions",
        "submitted_transactions",
    ):
        _require(_integer(safety.get(key)) == 0, f"Safety M65 violata: {key}.")
    return {
        "wallet_address": wallet,
        "gate_payload_sha256": expected,
        "status": str(verdict.get("status") or report.get("gate") or "UNKNOWN"),
        "recommended_state": str(candidate.get("recommended_state") or "UNKNOWN"),
        "economic_failure_reasons": sorted(
            str(item) for item in report.get("economic_failure_reasons") or []
        ),
        "analytics": dict(report.get("analytics") or {}),
    }


def _copyability_evidence(
    campaigns: Iterable[CanonicalParserGen4CopyabilityCampaign],
    positions: Iterable[CanonicalParserGen4CopyabilityPosition],
    receipt_rows: Iterable[Any],
) -> dict[str, dict[str, Any]]:
    campaign_by_id = {int(item.id): item for item in campaigns}
    receipts_by_wallet: dict[str, dict[str, int]] = defaultdict(
        lambda: {"webhook": 0, "recovery_only": 0}
    )
    for wallet, source, count in receipt_rows:
        address = str(wallet or "")
        if not address:
            continue
        if str(source) == "WEBHOOK":
            receipts_by_wallet[address]["webhook"] += _integer(count)
        elif str(source) == "RECOVERY_ONLY":
            receipts_by_wallet[address]["recovery_only"] += _integer(count)

    grouped: dict[str, list[CanonicalParserGen4CopyabilityPosition]] = defaultdict(list)
    for item in positions:
        grouped[str(item.wallet_address)].append(item)

    result: dict[str, dict[str, Any]] = {}
    for wallet, rows in grouped.items():
        exact_closed = [
            item
            for item in rows
            if item.status == "CLOSED"
            and item.entry_source == "WEBHOOK"
            and item.exit_source == "WEBHOOK"
            and item.entry_copyable
            and item.exit_copyable
            and item.pnl_lamports is not None
        ]
        recovery_closed = [
            item
            for item in rows
            if item.status == "CLOSED" and item.entry_source == "RECOVERY_ONLY"
        ]
        quarantined_closed = [
            item
            for item in rows
            if item.status == "CLOSED"
            and item.entry_source == "WEBHOOK"
            and item.exit_source == "RECOVERY_ONLY"
            and item.entry_copyable
            and not item.exit_copyable
            and item.pnl_lamports is None
            and item.close_reason == "RECOVERY_GAP_QUARANTINE"
        ]
        open_rows = [item for item in rows if item.status in {"OPEN", "OPEN_PARTIAL"}]
        pnl_values = [
            _integer(item.pnl_lamports)
            for item in exact_closed
            if item.pnl_lamports is not None
        ]
        campaign_ids = sorted({int(item.campaign_db_id) for item in rows})
        result[wallet] = {
            "evidence_class": "EXACT_PRODUCTION_COPYABILITY_DB_READ_ONLY",
            "campaign_ids": [
                str(campaign_by_id[item].campaign_id)
                for item in campaign_ids
                if item in campaign_by_id
            ],
            "official_realtime_closed_trades": len(exact_closed),
            "recovery_only_closed_trades": len(recovery_closed),
            "quarantined_seed_positions": len(quarantined_closed),
            "official_filter": (
                "CLOSED_WEBHOOK_ENTRY_AND_EXIT_COPYABLE_WITH_PNL"
            ),
            "open_positions": len(open_rows),
            "net_pnl_lamports": sum(pnl_values),
            "profit_factor": _profit_factor(pnl_values) if pnl_values else None,
            "win_rate_percent": (
                sum(item > 0 for item in pnl_values) / len(pnl_values) * 100.0
                if pnl_values
                else None
            ),
            "first_closed_at": _iso(
                min(
                    (_aware(item.closed_at) for item in exact_closed if item.closed_at is not None),
                    default=None,
                )
            ),
            "last_closed_at": _iso(
                max(
                    (_aware(item.closed_at) for item in exact_closed if item.closed_at is not None),
                    default=None,
                )
            ),
            "webhook_receipts": receipts_by_wallet[wallet]["webhook"],
            "recovery_only_receipts": receipts_by_wallet[wallet]["recovery_only"],
            "recovery_counts_as_realtime_proof": False,
        }
    return result


def _frozen_campaign_wallets(
    campaigns: Iterable[CanonicalParserGen4CopyabilityCampaign],
) -> set[str]:
    wallets: set[str] = set()
    for campaign in campaigns:
        for raw in campaign.frozen_wallets or []:
            if isinstance(raw, dict):
                value = raw.get("wallet_address") or raw.get("address") or raw.get("wallet")
            else:
                value = raw
            wallet = str(value or "").strip()
            if _SOLANA_ADDRESS.fullmatch(wallet):
                wallets.add(wallet)
    return wallets


def build_unified_local_snapshot(
    db: Session,
    *,
    m64_reports: Iterable[dict[str, Any]] = (),
    m65_reports: Iterable[dict[str, Any]] = (),
    limit: int = 500,
    now: datetime | None = None,
) -> dict[str, Any]:
    snapshot_at = _aware(now) or utc_now()
    m66_snapshot = build_cached_discovery_snapshot(
        db,
        limit=max(1, min(int(limit), 500)),
        policy=M66_DEFAULT_POLICY,
        now=snapshot_at,
    )
    candidates = [dict(item) for item in m66_snapshot.get("candidates") or []]
    campaigns = list(
        db.query(CanonicalParserGen4CopyabilityCampaign)
        .order_by(CanonicalParserGen4CopyabilityCampaign.id.asc())
        .all()
    )

    normalized_m64: dict[str, dict[str, Any]] = {}
    for report in m64_reports:
        normalized = validate_external_m64_report(dict(report))
        normalized_m64[normalized["wallet_address"]] = normalized
    normalized_m65: dict[str, dict[str, Any]] = {}
    for report in m65_reports:
        normalized = validate_external_m65_report(dict(report))
        normalized_m65[normalized["wallet_address"]] = normalized

    candidate_by_wallet = {
        str(item.get("wallet_address") or ""): item
        for item in candidates
        if _SOLANA_ADDRESS.fullmatch(str(item.get("wallet_address") or ""))
    }
    addresses = sorted(
        set(candidate_by_wallet)
        | _frozen_campaign_wallets(campaigns)
        | set(normalized_m64)
        | set(normalized_m65)
    )
    positions: list[CanonicalParserGen4CopyabilityPosition] = []
    receipt_rows: list[Any] = []
    if addresses:
        positions = list(
            db.query(CanonicalParserGen4CopyabilityPosition)
            .filter(CanonicalParserGen4CopyabilityPosition.wallet_address.in_(addresses))
            .order_by(
                CanonicalParserGen4CopyabilityPosition.wallet_address.asc(),
                CanonicalParserGen4CopyabilityPosition.entry_signal_at.asc(),
                CanonicalParserGen4CopyabilityPosition.id.asc(),
            )
            .all()
        )
        receipt_rows = list(
            db.query(
                CanonicalParserGen4WebhookReceipt.wallet_address,
                CanonicalParserGen4WebhookReceipt.source,
                func.count(CanonicalParserGen4WebhookReceipt.id),
            )
            .filter(CanonicalParserGen4WebhookReceipt.wallet_address.in_(addresses))
            .group_by(
                CanonicalParserGen4WebhookReceipt.wallet_address,
                CanonicalParserGen4WebhookReceipt.source,
            )
            .all()
        )
    copyability = _copyability_evidence(campaigns, positions, receipt_rows)

    unified: list[dict[str, Any]] = []
    for wallet in addresses:
        candidate = candidate_by_wallet.get(wallet, {})
        local = dict(candidate.get("local_trade_evidence") or {})
        backtest = dict(candidate.get("economics") or {})
        row = {
            "wallet_address": wallet,
            "cluster": dict(candidate.get("independence") or {}),
            "legacy_trade_cache": local,
            "candidate_backtest": backtest,
            "copyability_campaign": copyability.get(wallet),
            "m64_audit": normalized_m64.get(wallet),
            "m65_gate": normalized_m65.get(wallet),
            "economic_score": None,
            "economic_score_status": "NOT_AVAILABLE_UNTIL_POSITION_EVIDENCE",
        }
        unified.append(row)

    source = dict(m66_snapshot.get("source") or {})
    snapshot: dict[str, Any] = {
        "scope": M67_M70_SNAPSHOT_SCOPE,
        "version": M67_M70_VERSION,
        "snapshot_at_utc": _iso(snapshot_at),
        "source": {
            "wallet_rows_total": len(unified),
            "wallet_rows_read": len(unified),
            "m66_wallet_rows_total": _integer(source.get("wallet_rows_total")),
            "m66_wallet_rows_read": _integer(source.get("wallet_rows_read")),
            "union_only_wallet_rows": len(unified) - len(candidate_by_wallet),
            "wallet_rows_truncated": bool(source.get("wallet_rows_truncated")),
            "legacy_trade_rows_lifetime": _integer(
                source.get("cached_trade_rows_lifetime")
            ),
            "copyability_campaign_rows": len(campaigns),
            "copyability_position_rows": len(positions),
            "copyability_receipt_aggregate_rows": len(receipt_rows),
            "m64_reports": len(normalized_m64),
            "m65_reports": len(normalized_m65),
            "database_query_count": _integer(source.get("database_query_count")) + 3,
        },
        "candidates": unified,
        "contracts": {
            "official_realtime_counter": 83,
            "recovery_counts_as_realtime_proof": False,
            "historical_jupiter_quotes_invented": False,
            "parser_version": M64_EXPECTED_PARSER_VERSION,
            "copyability_policy_version": M64_EXPECTED_POLICY_VERSION,
        },
        "safety": _zero_safety(network_requests=0, public_rpc_requests=0),
    }
    snapshot["integrity"] = {
        "snapshot_payload_sha256": canonical_sha256(snapshot)
    }
    return snapshot


def validate_local_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    _require(snapshot.get("scope") == M67_M70_SNAPSHOT_SCOPE, "Scope snapshot M67 inatteso.")
    _require(snapshot.get("version") == M67_M70_VERSION, "Versione snapshot M67 inattesa.")
    integrity = dict(snapshot.get("integrity") or {})
    expected = str(integrity.get("snapshot_payload_sha256") or "")
    _require(len(expected) == 64, "Hash snapshot M67 assente.")
    _require(
        expected == canonical_sha256(_without(snapshot, "integrity")),
        "Hash snapshot M67 non valido.",
    )
    source = dict(snapshot.get("source") or {})
    candidates = [dict(item) for item in snapshot.get("candidates") or []]
    _require(
        _integer(source.get("wallet_rows_read")) == len(candidates),
        "Inventario M67 incoerente.",
    )
    _require(source.get("wallet_rows_truncated") is False, "Inventario M67 troncato.")
    seen: set[str] = set()
    for item in candidates:
        wallet = str(item.get("wallet_address") or "")
        _require(bool(_SOLANA_ADDRESS.fullmatch(wallet)), f"Wallet M67 non valido: {wallet}.")
        _require(wallet not in seen, f"Wallet M67 duplicato: {wallet}.")
        seen.add(wallet)
        _require(item.get("economic_score") is None, "Score economico inventato.")
    _validate_zero_safety(dict(snapshot.get("safety") or {}), allow_public_rpc=False)
    contracts = dict(snapshot.get("contracts") or {})
    _require(_integer(contracts.get("official_realtime_counter")) == 83, "Counter ufficiale != 83.")
    _require(
        contracts.get("recovery_counts_as_realtime_proof") is False,
        "Recovery promosso a prova realtime.",
    )
    return {
        "snapshot_payload_sha256": expected,
        "candidates": candidates,
        "wallet_count": len(candidates),
        "source": source,
    }


def _zero_safety(*, network_requests: int, public_rpc_requests: int) -> dict[str, Any]:
    return {
        "network_requests": int(network_requests),
        "public_rpc_requests": int(public_rpc_requests),
        "helius_requests": 0,
        "database_writes": 0,
        "backend_posts": 0,
        "jupiter_requests": 0,
        "paper_orders": 0,
        "live_orders": 0,
        "signed_transactions": 0,
        "submitted_transactions": 0,
        "signer_access": False,
        "discovery_cron_changed": False,
        "primary_campaign_changed": False,
        "legacy_forward_feed_changed": False,
        "automatic_live_activation": False,
        "micro_live_execution_authorized": False,
    }


def _validate_zero_safety(safety: dict[str, Any], *, allow_public_rpc: bool) -> None:
    for key in (
        "helius_requests",
        "database_writes",
        "backend_posts",
        "jupiter_requests",
        "paper_orders",
        "live_orders",
        "signed_transactions",
        "submitted_transactions",
    ):
        _require(_integer(safety.get(key)) == 0, f"Vincolo safety violato: {key}.")
    if not allow_public_rpc:
        _require(_integer(safety.get("public_rpc_requests")) == 0, "RPC pubblico inatteso.")
    _require(safety.get("signer_access") is False, "Accesso signer inatteso.")
    _require(
        safety.get("micro_live_execution_authorized") is False,
        "Micro Live non puo essere autorizzato.",
    )


def _profit_factor(values: Iterable[int | float]) -> float:
    rows = [_finite(item) for item in values]
    gross_profit = sum(max(0.0, item) for item in rows)
    gross_loss = abs(sum(min(0.0, item) for item in rows))
    if gross_loss > 0:
        return gross_profit / gross_loss
    return 999.0 if gross_profit > 0 else 0.0


def summarize_signature_activity(
    signature_rows: Iterable[dict[str, Any]],
    *,
    now: datetime,
    policy: dict[str, Any],
) -> dict[str, Any]:
    current = _aware(now) or utc_now()
    recent_cutoff = current - timedelta(days=_integer(policy["recent_activity_days"]))
    history_cutoff = current - timedelta(days=_integer(policy["activity_lookback_days"]))
    usable: list[tuple[dict[str, Any], datetime]] = []
    for row in signature_rows:
        if row.get("err") is not None:
            continue
        block_time = row.get("blockTime")
        if block_time is None:
            continue
        timestamp = datetime.fromtimestamp(_integer(block_time), tz=timezone.utc)
        if timestamp >= history_cutoff:
            usable.append((dict(row), timestamp))
    recent = [(row, timestamp) for row, timestamp in usable if timestamp >= recent_cutoff]
    active_days = len({timestamp.date().isoformat() for _, timestamp in recent})
    latest = max((timestamp for _, timestamp in usable), default=None)
    active = (
        len(recent) >= _integer(policy["minimum_recent_transactions"])
        and active_days >= _integer(policy["minimum_recent_active_days"])
    )
    return {
        "evidence_class": "PUBLIC_RPC_SIGNATURE_ACTIVITY_NOT_SWAP_CLASSIFICATION",
        "transactions_7d": len(recent),
        "transactions_30d": len(usable),
        "active_days_7d": active_days,
        "latest_transaction_at": _iso(latest),
        "activity_status": (
            "ACTIVE_CANDIDATE"
            if active
            else ("RECENT_LOW_ACTIVITY" if usable else "INACTIVE_30D")
        ),
        "deep_history_candidate": active,
        "economic_metrics_available": False,
    }


@dataclass
class _SimulatedPosition:
    token_mint: str
    quantity: float
    remaining_quantity: float
    remaining_cost_sol: float
    original_cost_sol: float
    entry_at: datetime
    entry_signature: str
    realized_proceeds_sol: float = 0.0
    realized_cost_sol: float = 0.0
    exit_signatures: list[str] = field(default_factory=list)


def _event_price_sol(event: dict[str, Any]) -> float | None:
    token_raw = abs(_integer(event.get("token_delta_raw")))
    decimals = max(0, _integer(event.get("token_decimals")))
    token_amount = token_raw / (10**decimals)
    sol_delta = _integer(event.get("sol_equivalent_delta_lamports"))
    network_fee = max(0, _integer(event.get("source_network_fee_lamports")))
    if str(event.get("side")) == "BUY":
        lamports = max(0, abs(sol_delta) - network_fee)
    else:
        lamports = max(0, sol_delta + network_fee)
    if token_amount <= 0 or lamports <= 0:
        return None
    return (lamports / 1_000_000_000.0) / token_amount


def _position_metrics(rows: Iterable[dict[str, Any]], starting_equity: float) -> dict[str, Any]:
    ordered = sorted(
        [dict(item) for item in rows],
        key=lambda item: (
            str(item.get("exit_at") or ""),
            str(item.get("entry_at") or ""),
            str(item.get("entry_signature") or ""),
        ),
    )
    values = [_finite(item.get("pnl_sol")) for item in ordered]
    equity = max(1e-9, starting_equity)
    peak = equity
    drawdown = 0.0
    for pnl in values:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            drawdown = max(drawdown, (peak - equity) / peak * 100.0)
    wins = sum(item > 1e-12 for item in values)
    losses = sum(item < -1e-12 for item in values)
    return {
        "closed_trade_count": len(values),
        "winning_trades": wins,
        "losing_trades": losses,
        "breakeven_trades": len(values) - wins - losses,
        "gross_profit_sol": round(sum(max(0.0, item) for item in values), 9),
        "gross_loss_sol": round(abs(sum(min(0.0, item) for item in values)), 9),
        "net_pnl_sol": round(sum(values), 9),
        "profit_factor": round(_profit_factor(values), 8),
        "win_rate_percent": round(wins / len(values) * 100.0, 8) if values else 0.0,
        "maximum_drawdown_percent": round(drawdown, 8),
    }


def simulate_gen4_from_public_events(
    events: Iterable[dict[str, Any]],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = validate_policy(dict(policy or {}))
    rows = sorted(
        [dict(item) for item in events],
        key=lambda item: (
            str(item.get("block_time") or ""),
            _integer(item.get("slot")),
            _integer(item.get("sequence")),
        ),
    )
    starting_capital = _finite(resolved["starting_capital_sol"])
    buy_size = _finite(resolved["fixed_buy_size_sol"])
    friction = _finite(resolved["effective_market_friction_bps"]) / 10_000.0
    fee_ratio = _finite(resolved["fee_bps"]) / 10_000.0
    maximum_open = _integer(resolved["maximum_open_positions"])
    cash = starting_capital
    positions: dict[str, _SimulatedPosition] = {}
    last_prices: dict[str, float] = {}
    closed: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    peak_equity = starting_capital
    maximum_drawdown = 0.0

    for event in rows:
        side = str(event.get("side") or "").upper()
        token = str(event.get("token_mint") or "")
        timestamp = _parse_datetime(event.get("block_time"))
        price = _event_price_sol(event)
        if side not in {"BUY", "SELL"} or not token or timestamp is None or price is None:
            counters["skipped_invalid"] += 1
            continue
        counters["valid_priced_events"] += 1
        last_prices[token] = price
        if side == "BUY":
            counters["buy_signals"] += 1
            if token in positions:
                counters["skipped_existing_position"] += 1
            elif len(positions) >= maximum_open:
                counters["skipped_max_positions"] += 1
            elif cash + 1e-12 < buy_size:
                counters["skipped_insufficient_capital"] += 1
            else:
                entry_fee = buy_size * fee_ratio
                net_input = max(0.0, buy_size - entry_fee)
                execution_price = price * (1.0 + friction)
                quantity = net_input / execution_price if execution_price > 0 else 0.0
                if quantity <= 0:
                    counters["skipped_invalid"] += 1
                else:
                    positions[token] = _SimulatedPosition(
                        token_mint=token,
                        quantity=quantity,
                        remaining_quantity=quantity,
                        remaining_cost_sol=buy_size,
                        original_cost_sol=buy_size,
                        entry_at=timestamp,
                        entry_signature=str(event.get("signature") or ""),
                    )
                    cash -= buy_size
                    counters["executed_buys"] += 1
        else:
            counters["sell_signals"] += 1
            position = positions.get(token)
            if position is None:
                counters["unmatched_sells"] += 1
            else:
                fraction = _finite(event.get("sell_fraction"), default=1.0)
                if fraction <= 0:
                    counters["skipped_invalid"] += 1
                    continue
                fraction = min(1.0, fraction)
                quantity_sold = min(
                    position.remaining_quantity,
                    max(position.remaining_quantity * fraction, 0.0),
                )
                if quantity_sold <= 0:
                    counters["skipped_invalid"] += 1
                    continue
                cost_fraction = quantity_sold / max(1e-18, position.remaining_quantity)
                allocated_cost = position.remaining_cost_sol * cost_fraction
                execution_price = price * max(0.0, 1.0 - friction)
                gross = quantity_sold * execution_price
                proceeds = gross * max(0.0, 1.0 - fee_ratio)
                cash += proceeds
                position.remaining_quantity -= quantity_sold
                position.remaining_cost_sol -= allocated_cost
                position.realized_proceeds_sol += proceeds
                position.realized_cost_sol += allocated_cost
                position.exit_signatures.append(str(event.get("signature") or ""))
                dust = position.quantity * 0.001
                if position.remaining_quantity <= dust or fraction >= 0.999:
                    if position.remaining_quantity > 0:
                        final_gross = position.remaining_quantity * execution_price
                        final_proceeds = final_gross * max(0.0, 1.0 - fee_ratio)
                        cash += final_proceeds
                        position.realized_proceeds_sol += final_proceeds
                        position.realized_cost_sol += position.remaining_cost_sol
                    pnl = position.realized_proceeds_sol - position.original_cost_sol
                    closed.append(
                        {
                            "token_mint": token,
                            "entry_at": _iso(position.entry_at),
                            "exit_at": _iso(timestamp),
                            "entry_signature": position.entry_signature,
                            "exit_signature": str(event.get("signature") or ""),
                            "exit_signatures": list(position.exit_signatures),
                            "cost_basis_sol": round(position.original_cost_sol, 9),
                            "proceeds_sol": round(position.realized_proceeds_sol, 9),
                            "pnl_sol": round(pnl, 9),
                            "return_percent": round(
                                pnl / position.original_cost_sol * 100.0,
                                8,
                            ),
                            "historical_jupiter_quote": "UNAVAILABLE_NOT_INVENTED",
                            "pricing_quality": "PUBLIC_SAME_TRANSACTION_ONCHAIN_PROXY_GEN4_COSTED",
                        }
                    )
                    del positions[token]
                    counters["completed_positions"] += 1

        equity = cash
        for token_name, position in positions.items():
            mark = last_prices.get(token_name)
            if mark is None:
                equity += position.remaining_cost_sol
            else:
                gross = position.remaining_quantity * mark * max(0.0, 1.0 - friction)
                equity += gross * max(0.0, 1.0 - fee_ratio)
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            maximum_drawdown = max(
                maximum_drawdown,
                (peak_equity - equity) / peak_equity * 100.0,
            )

    ending_equity = cash
    for token_name, position in positions.items():
        mark = last_prices.get(token_name)
        if mark is None:
            ending_equity += position.remaining_cost_sol
        else:
            gross = position.remaining_quantity * mark * max(0.0, 1.0 - friction)
            ending_equity += gross * max(0.0, 1.0 - fee_ratio)
    metrics = _position_metrics(closed, starting_capital)
    timestamps = [_parse_datetime(item.get("block_time")) for item in rows]
    timestamps = [item for item in timestamps if item is not None]
    metrics.update(
        {
            "source_events": len(rows),
            "valid_priced_events": counters["valid_priced_events"],
            "buy_signals": counters["buy_signals"],
            "sell_signals": counters["sell_signals"],
            "executed_buys": counters["executed_buys"],
            "unmatched_sells": counters["unmatched_sells"],
            "open_positions": len(positions),
            "ending_equity_sol": round(ending_equity, 9),
            "net_equity_pnl_sol": round(ending_equity - starting_capital, 9),
            "total_return_percent": round(
                (ending_equity - starting_capital) / starting_capital * 100.0,
                8,
            ),
            "maximum_drawdown_percent": round(maximum_drawdown, 8),
            "history_span_days": round(
                (max(timestamps) - min(timestamps)).total_seconds() / 86400.0,
                8,
            )
            if len(timestamps) >= 2
            else 0.0,
            "history_oldest_at": _iso(min(timestamps)) if timestamps else None,
            "history_newest_at": _iso(max(timestamps)) if timestamps else None,
            "unique_token_count": len(
                {str(item.get("token_mint") or "") for item in rows if item.get("token_mint")}
            ),
            "effective_market_friction_bps": _finite(
                resolved["effective_market_friction_bps"]
            ),
            "historical_jupiter_quotes_invented": False,
        }
    )
    return {
        "model": {
            "starting_capital_sol": starting_capital,
            "fixed_buy_size_sol": buy_size,
            "slippage_bps": _integer(resolved["slippage_bps"]),
            "fee_bps": _integer(resolved["fee_bps"]),
            "copy_delay_seconds": _integer(resolved["copy_delay_seconds"]),
            "delay_penalty_bps_per_minute": _finite(
                resolved["delay_penalty_bps_per_minute"]
            ),
            "effective_market_friction_bps": _finite(
                resolved["effective_market_friction_bps"]
            ),
            "maximum_open_positions": maximum_open,
        },
        "metrics": metrics,
        "closed_trades": closed,
        "open_positions": [
            {
                "token_mint": item.token_mint,
                "entry_signature": item.entry_signature,
                "entry_at": _iso(item.entry_at),
                "remaining_cost_sol": round(item.remaining_cost_sol, 9),
            }
            for item in positions.values()
        ],
    }


def _economic_analysis(backtest: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(backtest.get("metrics") or {})
    closed = [dict(item) for item in backtest.get("closed_trades") or []]
    recent_size = _integer(policy["minimum_recent_closed_trades"])
    recent = _position_metrics(closed[-recent_size:], _finite(policy["starting_capital_sol"]))
    token_counts = Counter(str(item.get("token_mint") or "") for item in closed)
    top_count = token_counts.most_common(1)[0][1] if token_counts else 0
    concentration = top_count / len(closed) * 100.0 if closed else 0.0
    best_pnl = max((_finite(item.get("pnl_sol")) for item in closed), default=0.0)
    size = _integer(policy["stability_window_size"])
    windows: list[dict[str, Any]] = []
    for start in range(0, len(closed), max(1, size)):
        chunk = closed[start : start + max(1, size)]
        if len(chunk) < max(1, size):
            continue
        item_metrics = _position_metrics(chunk, _finite(policy["starting_capital_sol"]))
        windows.append({"window": len(windows) + 1, **item_metrics})
    checks = {
        "closed_sample": _integer(metrics.get("closed_trade_count"))
        >= _integer(policy["minimum_closed_trades"]),
        "history_span": _finite(metrics.get("history_span_days"))
        >= _finite(policy["minimum_history_span_days"]),
        "net_pnl": _finite(metrics.get("net_pnl_sol")) > 0,
        "profit_factor": _finite(metrics.get("profit_factor"))
        >= _finite(policy["minimum_profit_factor"]),
        "win_rate": _finite(metrics.get("win_rate_percent"))
        >= _finite(policy["minimum_win_rate_percent"]),
        "drawdown": _finite(metrics.get("maximum_drawdown_percent"), default=100.0)
        <= _finite(policy["maximum_drawdown_percent"]),
        "recent_sample": _integer(recent.get("closed_trade_count"))
        >= _integer(policy["minimum_recent_closed_trades"]),
        "recent_pnl": _finite(recent.get("net_pnl_sol")) > 0,
        "recent_profit_factor": _finite(recent.get("profit_factor"))
        >= _finite(policy["minimum_recent_profit_factor"]),
        "recent_drawdown": _finite(
            recent.get("maximum_drawdown_percent"), default=100.0
        ) <= _finite(policy["maximum_recent_drawdown_percent"]),
        "unique_tokens": len(token_counts) >= _integer(policy["minimum_unique_tokens"]),
        "token_concentration": concentration
        <= _finite(policy["maximum_token_concentration_percent"]),
        "positive_without_best": (
            _finite(metrics.get("net_pnl_sol")) - best_pnl > 0
            if policy["require_positive_net_without_best_trade"]
            else True
        ),
        "stability_windows": len(windows) >= _integer(policy["minimum_stability_windows"]),
        "positive_stability_windows": sum(
            _finite(item.get("net_pnl_sol")) > 0 for item in windows
        ) >= _integer(policy["minimum_positive_stability_windows"]),
        "worst_stability_pf": min(
            (_finite(item.get("profit_factor")) for item in windows),
            default=0.0,
        ) >= _finite(policy["minimum_worst_stability_profit_factor"]),
        "zero_open_positions": _integer(metrics.get("open_positions")) == 0,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "metrics": metrics,
        "recent_metrics": recent,
        "top_token_concentration_percent": round(concentration, 8),
        "net_pnl_without_best_trade_sol": round(
            _finite(metrics.get("net_pnl_sol")) - best_pnl,
            9,
        ),
        "stability_windows": windows,
        "checks": checks,
        "failure_reasons": failed,
        "economic_gate_passed": not failed,
        "economic_score": _economic_score(metrics, recent, checks, policy),
    }


def _economic_score(
    metrics: dict[str, Any],
    recent: dict[str, Any],
    checks: dict[str, bool],
    policy: dict[str, Any],
) -> float | None:
    if _integer(metrics.get("closed_trade_count")) <= 0:
        return None
    sample = min(
        1.0,
        _integer(metrics.get("closed_trade_count"))
        / max(1, _integer(policy["minimum_closed_trades"])),
    )
    pf = min(2.0, _finite(metrics.get("profit_factor"))) / 2.0
    recent_pf = min(2.0, _finite(recent.get("profit_factor"))) / 2.0
    drawdown = max(
        0.0,
        1.0
        - _finite(metrics.get("maximum_drawdown_percent"), default=100.0)
        / max(1.0, _finite(policy["maximum_drawdown_percent"]) * 2.0),
    )
    pass_ratio = sum(checks.values()) / max(1, len(checks))
    return round(
        (sample * 25.0) + (pf * 25.0) + (recent_pf * 15.0) + (drawdown * 15.0) + (pass_ratio * 20.0),
        4,
    )


def replay_multi_wallet_consensus(
    wallet_events: dict[str, list[dict[str, Any]]],
    *,
    clusters: dict[str, str],
    policy: dict[str, Any],
) -> dict[str, Any]:
    window = _integer(policy["consensus_window_seconds"])
    buys: list[dict[str, Any]] = []
    for wallet, events in wallet_events.items():
        for event in events:
            if str(event.get("side")) != "BUY":
                continue
            timestamp = _parse_datetime(event.get("block_time"))
            token = str(event.get("token_mint") or "")
            if timestamp is None or not token:
                continue
            buys.append(
                {
                    "wallet_address": wallet,
                    "cluster_id": clusters.get(wallet, ""),
                    "token_mint": token,
                    "signal_at": _iso(timestamp),
                    "timestamp": timestamp,
                    "signature": str(event.get("signature") or ""),
                }
            )
    buys.sort(key=lambda item: (item["timestamp"], item["wallet_address"]))
    signals: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(buys):
        members = [row]
        for other in buys[index + 1 :]:
            delta = (other["timestamp"] - row["timestamp"]).total_seconds()
            if delta > window:
                break
            if other["token_mint"] == row["token_mint"]:
                members.append(other)
        unique_wallets = sorted({str(item["wallet_address"]) for item in members})
        independent_clusters = sorted(
            {str(item["cluster_id"]) for item in members if str(item["cluster_id"])}
        )
        key = (str(row["token_mint"]), str(row["signal_at"]))
        if key in seen:
            continue
        seen.add(key)
        if len(unique_wallets) < _integer(policy["consensus_minimum_independent_wallets"]):
            continue
        signals.append(
            {
                "token_mint": row["token_mint"],
                "window_started_at": row["signal_at"],
                "wallets": unique_wallets,
                "independent_clusters": independent_clusters,
                "cluster_deduplication_passed": len(independent_clusters)
                >= _integer(policy["consensus_minimum_independent_wallets"]),
                "activation_authorized": False,
            }
        )
    eligible = [item for item in signals if item["cluster_deduplication_passed"]]
    return {
        "window_seconds": window,
        "minimum_independent_wallets": _integer(
            policy["consensus_minimum_independent_wallets"]
        ),
        "maximum_wallets": _integer(policy["consensus_maximum_wallets"]),
        "maximum_token_exposure_sol": _finite(
            policy["consensus_maximum_token_exposure_sol"]
        ),
        "buy_events_replayed": len(buys),
        "candidate_signals": len(signals),
        "independent_signals": len(eligible),
        "signals": signals,
        "activation_authorized": False,
    }


def build_rpc_evidence(
    *,
    activity_rows: dict[str, dict[str, Any]],
    deep_rows: dict[str, dict[str, Any]],
    rpc_stats: dict[str, Any],
    cache: dict[str, Any],
    policy: dict[str, Any],
    collected_at: datetime | None = None,
) -> dict[str, Any]:
    resolved = validate_policy(policy)
    evidence: dict[str, Any] = {
        "scope": M67_M70_RPC_SCOPE,
        "version": M67_M70_VERSION,
        "collected_at_utc": _iso(_aware(collected_at) or utc_now()),
        "activity": activity_rows,
        "deep_history": deep_rows,
        "rpc": dict(rpc_stats),
        "cache": {
            "schema": cache.get("schema"),
            "entry_count": len(dict(cache.get("entries") or {})),
            "payload_sha256": str(
                dict(cache.get("integrity") or {}).get("payload_sha256") or ""
            ),
        },
        "policy_sha256": canonical_sha256(resolved),
        "safety": _zero_safety(
            network_requests=_integer(rpc_stats.get("requests")),
            public_rpc_requests=_integer(rpc_stats.get("requests")),
        ),
    }
    evidence["integrity"] = {"rpc_evidence_sha256": canonical_sha256(evidence)}
    return evidence


def validate_rpc_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    _require(evidence.get("scope") == M67_M70_RPC_SCOPE, "Scope RPC M67 inatteso.")
    _require(evidence.get("version") == M67_M70_VERSION, "Versione RPC M67 inattesa.")
    integrity = dict(evidence.get("integrity") or {})
    expected = str(integrity.get("rpc_evidence_sha256") or "")
    _require(len(expected) == 64, "Hash evidenza RPC M67 assente.")
    _require(
        expected == canonical_sha256(_without(evidence, "integrity")),
        "Hash evidenza RPC M67 non valido.",
    )
    safety = dict(evidence.get("safety") or {})
    _validate_zero_safety(safety, allow_public_rpc=True)
    _require(
        _integer(safety.get("network_requests"))
        == _integer(safety.get("public_rpc_requests")),
        "Rete M67 diversa dalle sole richieste RPC pubbliche.",
    )
    return {
        "rpc_evidence_sha256": expected,
        "activity": {str(key): dict(value) for key, value in dict(evidence.get("activity") or {}).items()},
        "deep_history": {str(key): dict(value) for key, value in dict(evidence.get("deep_history") or {}).items()},
        "rpc": dict(evidence.get("rpc") or {}),
    }


def evaluate_zero_helius_pre_micro_live(
    local_snapshot: dict[str, Any],
    rpc_evidence: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    local = validate_local_snapshot(local_snapshot)
    rpc = validate_rpc_evidence(rpc_evidence)
    resolved = validate_policy(dict(policy or {}))
    now = _aware(evaluated_at) or utc_now()
    results: list[dict[str, Any]] = []
    wallet_events: dict[str, list[dict[str, Any]]] = {}
    clusters: dict[str, str] = {}

    for candidate in local["candidates"]:
        wallet = str(candidate["wallet_address"])
        cluster = dict(candidate.get("cluster") or {})
        clusters[wallet] = str(cluster.get("cluster_id") or "")
        activity = dict(rpc["activity"].get(wallet) or {})
        deep = dict(rpc["deep_history"].get(wallet) or {})
        events = [dict(item) for item in deep.get("events") or []]
        wallet_events[wallet] = events
        m65 = dict(candidate.get("m65_gate") or {})
        m64 = dict(candidate.get("m64_audit") or {})
        copyability = dict(candidate.get("copyability_campaign") or {})
        backtest = dict(deep.get("backtest") or {})
        economic = _economic_analysis(backtest, resolved) if backtest else None

        if str(m65.get("status")) == "FAIL_ECONOMIC":
            status = STATUS_RESEARCH
            reason = "M65_DEFINITIVE_ECONOMIC_FAIL"
        elif economic and economic["economic_gate_passed"] and bool(deep.get("history_complete")):
            status = STATUS_QUALIFIED
            reason = "GEN4_PUBLIC_RPC_ECONOMIC_GATE_PASS"
        elif economic and not bool(deep.get("history_complete")):
            status = STATUS_NEEDS_HISTORY
            reason = "PUBLIC_RPC_POSITION_HISTORY_INCOMPLETE"
        elif economic and _integer(economic["metrics"].get("closed_trade_count")) >= _integer(
            resolved["minimum_closed_trades"]
        ):
            status = STATUS_RESEARCH
            reason = "GEN4_PUBLIC_RPC_ECONOMIC_GATE_FAIL"
        elif activity.get("deep_history_candidate"):
            status = STATUS_NEEDS_HISTORY
            reason = "ACTIVE_WALLET_REQUIRES_MORE_POSITION_HISTORY"
        elif activity:
            status = STATUS_INACTIVE
            reason = str(activity.get("activity_status") or "LOW_ACTIVITY")
        elif m64 or copyability:
            status = STATUS_RESEARCH
            reason = "LOCAL_EVIDENCE_AVAILABLE_NOT_QUALIFIED"
        else:
            status = STATUS_NO_EVIDENCE
            reason = "NO_LOCAL_OR_PUBLIC_POSITION_EVIDENCE"

        score = economic.get("economic_score") if economic else None
        results.append(
            {
                "wallet_address": wallet,
                "status": status,
                "reason": reason,
                "economic_score": score,
                "economic_score_status": (
                    "POSITION_LEVEL_GEN4_SCORE"
                    if score is not None
                    else "NOT_AVAILABLE_UNTIL_POSITION_EVIDENCE"
                ),
                "activity": activity or None,
                "economic_analysis": economic,
                "evidence_sources": {
                    "legacy_trade_cache": bool(candidate.get("legacy_trade_cache")),
                    "copyability_campaign": bool(copyability),
                    "m64_audit": bool(m64),
                    "m65_gate": bool(m65),
                    "public_rpc_deep_history": bool(deep),
                },
                "m65_gate": m65 or None,
                "m64_audit": m64 or None,
                "copyability_campaign": copyability or None,
                "cluster": cluster,
                "short_canary_required": status == STATUS_QUALIFIED,
                "micro_live_execution_authorized": False,
            }
        )

    results.sort(
        key=lambda item: (
            {STATUS_QUALIFIED: 0, STATUS_NEEDS_HISTORY: 1, STATUS_RESEARCH: 2, STATUS_INACTIVE: 3, STATUS_NO_EVIDENCE: 4}[item["status"]],
            -_finite(item.get("economic_score")),
            item["wallet_address"],
        )
    )
    selected: list[dict[str, Any]] = []
    used_clusters: set[str] = set()
    for item in results:
        if item["status"] != STATUS_QUALIFIED:
            continue
        cluster_id = str(item.get("cluster", {}).get("cluster_id") or "")
        if not cluster_id or cluster_id in used_clusters:
            continue
        if len(selected) >= _integer(resolved["consensus_maximum_wallets"]):
            break
        used_clusters.add(cluster_id)
        selected.append(
            {
                "rank": len(selected) + 1,
                "wallet_address": item["wallet_address"],
                "economic_score": item["economic_score"],
                "cluster_id": cluster_id,
                "short_canary_required": True,
                "micro_live_execution_authorized": False,
            }
        )

    selected_addresses = {item["wallet_address"] for item in selected}
    consensus = replay_multi_wallet_consensus(
        {
            wallet: events
            for wallet, events in wallet_events.items()
            if wallet in selected_addresses
        },
        clusters=clusters,
        policy=resolved,
    )
    canary_contract = {
        "state": "PREPARED_DISARMED",
        "required": True,
        "minimum_observation_hours": _finite(resolved["canary_minimum_observation_hours"]),
        "minimum_entry_attempts": _integer(resolved["canary_minimum_entry_attempts"]),
        "minimum_closed_trades": _integer(resolved["canary_minimum_closed_trades"]),
        "minimum_webhook_coverage_percent": _finite(
            resolved["canary_minimum_webhook_coverage_percent"]
        ),
        "minimum_unsigned_build_coverage_percent": _finite(
            resolved["canary_minimum_unsigned_build_coverage_percent"]
        ),
        "maximum_entry_reject_rate_percent": _finite(
            resolved["canary_maximum_entry_reject_rate_percent"]
        ),
        "maximum_p95_end_to_quote_ms": _finite(
            resolved["canary_maximum_p95_end_to_quote_ms"]
        ),
        "maximum_p95_price_impact_bps": _finite(
            resolved["canary_maximum_p95_price_impact_bps"]
        ),
        "maximum_p95_price_deterioration_bps": _finite(
            resolved["canary_maximum_p95_price_deterioration_bps"]
        ),
        "zero_open_positions_required": True,
        "zero_unresolved_failures_required": True,
        "recovery_counts_as_realtime_proof": False,
        "activation_authorized": False,
    }
    qualification_ready = len(selected) >= _integer(
        resolved["consensus_minimum_independent_wallets"]
    )
    summary = Counter(item["status"] for item in results)
    report: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M67_M70_SCOPE,
        "version": M67_M70_VERSION,
        "evaluated_at_utc": _iso(now),
        "source": {
            "local_snapshot_sha256": local["snapshot_payload_sha256"],
            "rpc_evidence_sha256": rpc["rpc_evidence_sha256"],
            "wallets_evaluated": len(results),
            "public_rpc_requests": _integer(rpc["rpc"].get("requests")),
            "public_rpc_cache_hits": _integer(rpc["rpc"].get("cache_hits")),
            "helius_requests": 0,
        },
        "policy": resolved,
        "policy_sha256": canonical_sha256(resolved),
        "summary": {
            "wallets_evaluated": len(results),
            "wallets_active_candidates": sum(
                bool((item.get("activity") or {}).get("deep_history_candidate"))
                for item in results
            ),
            "wallets_deep_analyzed": sum(
                bool(item.get("evidence_sources", {}).get("public_rpc_deep_history"))
                for item in results
            ),
            "wallets_qualified_pending_canary": summary[STATUS_QUALIFIED],
            "wallets_needing_more_public_history": summary[STATUS_NEEDS_HISTORY],
            "wallets_research_only": summary[STATUS_RESEARCH],
            "wallets_inactive_or_low_activity": summary[STATUS_INACTIVE],
            "wallets_without_position_evidence": summary[STATUS_NO_EVIDENCE],
            "selected_wallets": len(selected),
            "multi_wallet_minimum_reached": qualification_ready,
        },
        "candidate_results": results,
        "selected_wallets": selected,
        "multi_wallet_consensus": consensus,
        "short_canary_contract": canary_contract,
        "pre_micro_live_foundation": {
            "state": "PREPARED_DISARMED",
            "provider_abstraction": {
                "public_solana_rpc": "READ_ONLY_AVAILABLE",
                "helius": "INSTALLED_BUT_DISABLED_NOT_CALLED",
            },
            "risk_contract": {
                "starting_capital_sol": _finite(resolved["starting_capital_sol"]),
                "fixed_buy_size_sol": _finite(resolved["fixed_buy_size_sol"]),
                "maximum_open_positions": _integer(resolved["maximum_open_positions"]),
                "maximum_token_exposure_sol": _finite(
                    resolved["consensus_maximum_token_exposure_sol"]
                ),
                "maximum_wallets": _integer(resolved["consensus_maximum_wallets"]),
                "circuit_breaker_required": True,
                "manual_kill_switch_required": True,
            },
            "candidate_specific_configuration_ready": qualification_ready,
            "signer_authorized": False,
            "live_authorized": False,
            "automatic_activation": False,
            "next_step": (
                "COLLECT_SHORT_REALTIME_CANARY_AFTER_EXPLICIT_PROVIDER_APPROVAL"
                if qualification_ready
                else "CONTINUE_ZERO_HELIUS_PUBLIC_RPC_QUALIFICATION"
            ),
        },
        "safety": _zero_safety(
            network_requests=_integer(rpc["rpc"].get("requests")),
            public_rpc_requests=_integer(rpc["rpc"].get("requests")),
        ),
    }
    report["integrity"] = {
        "decision_input_sha256": canonical_sha256(
            {
                "local_snapshot_sha256": local["snapshot_payload_sha256"],
                "rpc_evidence_sha256": rpc["rpc_evidence_sha256"],
                "policy_sha256": report["policy_sha256"],
            }
        ),
        "report_payload_sha256": canonical_sha256(report),
    }
    return report


__all__ = [
    "M67_M70_CACHE_SCHEMA",
    "M67_M70_DEFAULT_POLICY",
    "M67_M70_RPC_SCOPE",
    "M67_M70_RUN_CONFIRMATION",
    "M67_M70_SCOPE",
    "M67_M70_SNAPSHOT_SCOPE",
    "M67_M70_VERSION",
    "M67M70ZeroHeliusError",
    "build_rpc_evidence",
    "build_unified_local_snapshot",
    "evaluate_zero_helius_pre_micro_live",
    "replay_multi_wallet_consensus",
    "simulate_gen4_from_public_events",
    "summarize_signature_activity",
    "utc_now",
    "validate_external_m64_report",
    "validate_external_m65_report",
    "validate_local_snapshot",
    "validate_policy",
    "validate_rpc_evidence",
]
