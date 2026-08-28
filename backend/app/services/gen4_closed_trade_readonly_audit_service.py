from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4CopyabilityPosition,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.models.gen4_forward_feed import CanonicalParserGen4ForwardFeedState
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    GEN4_COPYABILITY_POLICY_VERSION,
    GEN4_COPYABILITY_RAW_PARSER_VERSION,
    CanonicalParserGen4CopyabilityError,
    ParsedRawSignal,
    parse_raw_copyability_signal,
)


M64_AUDIT_VERSION = "gen4-closed-trade-readonly-audit/1"
M64_EXPECTED_PARSER_VERSION = "canonical-parser-gen4-raw-balance-delta/4"
M64_EXPECTED_POLICY_VERSION = "canonical-parser-gen4-realtime-copyability/1"
M64_EXPECTED_ALEMBIC_HEAD = "c8a1f3d6e942"
M64_EXPECTED_DATABASE = "smartmoney_gen4"
M64_EXPECTED_GIT_HEAD = "fe63c528e55af84a97d6deb6872e825a5a43c6b4"
M64_TARGET_CAMPAIGN_ID = "e5eaf7b6-a4e7-4182-96a2-d5f6af668e74"
M64_PRIMARY_CAMPAIGN_ID = "89026d62-1e4e-452b-b0bf-8a5e3dd373e4"
M64_DISABLED_FORWARD_FEED_STATE_ID = "d11626bf-e9ba-4305-b3a9-5c6386148e72"
M64_TARGET_WALLET = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
M64_OFFICIAL_REALTIME_TRADES = 83
M64_EXPECTED_OFFICIAL_NET_PNL_LAMPORTS = 32_319_569
M64_TARGET_RECONSTRUCTED_TRADES = 17
M64_EXPECTED_RECOVERY_RECEIPTS = 28
M64_EXPECTED_QUARANTINED_SEED_POSITIONS = 2
M64_DEFAULT_PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"
M64_LAMPORTS_PER_SOL = 1_000_000_000
M64_RECOVERY_METADATA_KEY = "m63_helius_credit_containment"
M64_RECOVERY_GAP_METADATA_KEY = "m63_public_rpc_recovery_gap"


class M64ReadonlyAuditError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    normalized = aware(value)
    return normalized.isoformat() if normalized is not None else None


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _round(value: float | int | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * max(0.0, min(float(quantile), 1.0))
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _trade_brief(trade: dict[str, Any] | None) -> dict[str, Any] | None:
    if trade is None:
        return None
    return {
        "entry_signature": trade.get("entry_signature"),
        "last_exit_signature": trade.get("last_exit_signature"),
        "token_mint": trade.get("token_mint"),
        "pnl_lamports": int(trade.get("pnl_lamports") or 0),
        "pnl_sol": _round(int(trade.get("pnl_lamports") or 0) / M64_LAMPORTS_PER_SOL, 9),
        "return_percent": _round(trade.get("return_percent"), 8),
        "closed_at": trade.get("closed_at"),
    }


def calculate_trade_metrics(
    trades: Iterable[dict[str, Any]],
    *,
    evidence_quality: str,
) -> dict[str, Any]:
    rows = sorted(
        [dict(item) for item in trades],
        key=lambda item: (
            str(item.get("closed_at") or ""),
            int(item.get("close_sequence") or 0),
            int(item.get("entry_sequence") or 0),
            str(item.get("entry_signal_at") or ""),
            str(item.get("entry_signature") or ""),
        ),
    )
    pnl_values = [int(item.get("pnl_lamports") or 0) for item in rows]
    cost_values = [int(item.get("cost_lamports") or 0) for item in rows]
    return_values = [float(item.get("return_percent") or 0.0) for item in rows]
    fee_values = [int(item.get("fee_lamports") or 0) for item in rows]
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (999.0 if gross_profit > 0 else 0.0)
    )
    net_pnl = sum(pnl_values)
    total_cost = sum(cost_values)
    cumulative = 0
    peak = 0
    maximum_drawdown = 0
    equity_curve: list[dict[str, Any]] = []
    for index, (trade, pnl) in enumerate(zip(rows, pnl_values), start=1):
        cumulative += pnl
        peak = max(peak, cumulative)
        drawdown = peak - cumulative
        maximum_drawdown = max(maximum_drawdown, drawdown)
        equity_curve.append(
            {
                "sequence": index,
                "closed_at": trade.get("closed_at"),
                "entry_signature": trade.get("entry_signature"),
                "cumulative_pnl_lamports": cumulative,
                "drawdown_lamports": drawdown,
            }
        )
    best = max(rows, key=lambda item: int(item.get("pnl_lamports") or 0)) if rows else None
    worst = min(rows, key=lambda item: int(item.get("pnl_lamports") or 0)) if rows else None
    return {
        "evidence_quality": evidence_quality,
        "closed_trade_count": len(rows),
        "winning_trades": sum(value > 0 for value in pnl_values),
        "losing_trades": sum(value < 0 for value in pnl_values),
        "breakeven_trades": sum(value == 0 for value in pnl_values),
        "gross_profit_lamports": gross_profit,
        "gross_profit_sol": _round(gross_profit / M64_LAMPORTS_PER_SOL, 9),
        "gross_loss_lamports": gross_loss,
        "gross_loss_sol": _round(gross_loss / M64_LAMPORTS_PER_SOL, 9),
        "net_pnl_lamports": net_pnl,
        "net_pnl_sol": _round(net_pnl / M64_LAMPORTS_PER_SOL, 9),
        "total_cost_lamports": total_cost,
        "net_return_percent": _round(net_pnl / total_cost * 100.0 if total_cost else 0.0, 8),
        "profit_factor": _round(profit_factor, 8),
        "win_rate_percent": _round(
            sum(value > 0 for value in pnl_values) / len(rows) * 100.0 if rows else 0.0,
            8,
        ),
        "maximum_drawdown_lamports": maximum_drawdown,
        "maximum_drawdown_sol": _round(maximum_drawdown / M64_LAMPORTS_PER_SOL, 9),
        "maximum_drawdown_percent": _round(
            maximum_drawdown / total_cost * 100.0 if total_cost else 0.0,
            8,
        ),
        "average_pnl_lamports": _round(statistics.mean(pnl_values), 4) if pnl_values else None,
        "median_pnl_lamports": _round(statistics.median(pnl_values), 4) if pnl_values else None,
        "average_return_percent": _round(statistics.mean(return_values), 8) if return_values else None,
        "median_return_percent": _round(statistics.median(return_values), 8) if return_values else None,
        "total_allocated_fees_lamports": sum(fee_values),
        "best_trade": _trade_brief(best),
        "worst_trade": _trade_brief(worst),
        "equity_curve": equity_curve,
    }


def readonly_database_url(raw_url: str) -> URL:
    normalized = str(raw_url or "").strip()
    if not normalized:
        raise M64ReadonlyAuditError("DATABASE_PUBLIC_URL assente.")
    if normalized.startswith("postgres://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgres://") :]
    elif normalized.startswith("postgresql://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql://") :]
    try:
        parsed = make_url(normalized)
    except Exception as error:  # noqa: BLE001
        raise M64ReadonlyAuditError("DATABASE_PUBLIC_URL non valida.") from error
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise M64ReadonlyAuditError("L'audit production richiede PostgreSQL psycopg.")
    query = dict(parsed.query)
    existing_options = str(query.get("options") or "").strip()
    required_option = "-c default_transaction_read_only=on"
    query["options"] = (
        f"{existing_options} {required_option}".strip()
        if required_option not in existing_options
        else existing_options
    )
    return parsed.set(
        drivername="postgresql+psycopg",
        database=M64_EXPECTED_DATABASE,
        query=query,
    )


def _position_record(row: CanonicalParserGen4CopyabilityPosition) -> dict[str, Any]:
    entry_quote = dict(row.entry_quote or {})
    exit_quotes = [dict(item) for item in (row.exit_quotes or []) if isinstance(item, dict)]
    observed_exit_slippage = 0
    exit_slippage_complete = True
    for item in exit_quotes:
        quote = item.get("quote") if isinstance(item.get("quote"), dict) else {}
        expected = quote.get("expected_out_amount")
        conservative = quote.get("conservative_out_amount")
        try:
            observed_exit_slippage += max(0, int(expected) - int(conservative))
        except (TypeError, ValueError):
            exit_slippage_complete = False
    cost = int(row.entry_input_lamports + row.allocated_entry_fee_lamports)
    proceeds = int(row.realized_output_lamports - row.allocated_exit_fee_lamports)
    payload = {
        "position_id": row.position_id,
        "token_mint": row.token_mint,
        "token_decimals": int(row.token_decimals),
        "entry_signature": row.entry_signature,
        "last_exit_signature": row.last_exit_signature,
        "entry_source": row.entry_source,
        "exit_source": row.exit_source,
        "entry_sequence": int(row.id),
        "close_sequence": 0,
        "entry_signal_at": iso(row.entry_signal_at),
        "opened_at": iso(row.opened_at),
        "closed_at": iso(row.closed_at),
        "cost_lamports": cost,
        "proceeds_lamports": proceeds,
        "pnl_lamports": int(row.pnl_lamports or 0),
        "return_percent": _round(row.return_percent, 8),
        "entry_input_lamports": int(row.entry_input_lamports),
        "realized_output_lamports": int(row.realized_output_lamports),
        "allocated_entry_fee_lamports": int(row.allocated_entry_fee_lamports),
        "allocated_exit_fee_lamports": int(row.allocated_exit_fee_lamports),
        "fee_lamports": int(row.allocated_entry_fee_lamports + row.allocated_exit_fee_lamports),
        "entry_price_deterioration_bps": _round(row.entry_price_deterioration_bps, 8),
        "entry_price_impact_bps": _round(row.entry_price_impact_bps, 8),
        "entry_quote_latency_ms": row.entry_quote_latency_ms,
        "entry_end_to_quote_ms": row.entry_end_to_quote_ms,
        "exit_quote_latency_ms": row.exit_quote_latency_ms,
        "exit_price_impact_bps": _round(row.exit_price_impact_bps, 8),
        "observed_exit_slippage_impact_lamports": observed_exit_slippage,
        "observed_exit_slippage_complete": exit_slippage_complete,
        "entry_slippage_token_raw": (
            max(
                0,
                int(entry_quote.get("expected_out_amount"))
                - int(entry_quote.get("conservative_out_amount")),
            )
            if entry_quote.get("expected_out_amount") is not None
            and entry_quote.get("conservative_out_amount") is not None
            else None
        ),
        "entry_transaction_built": bool(row.entry_transaction_built),
        "exit_transaction_built": bool(row.exit_transaction_built),
        "close_reason": row.close_reason,
    }
    payload["evidence_sha256"] = canonical_sha256(payload)
    return payload


def _quarantined_seed_record(
    row: CanonicalParserGen4CopyabilityPosition,
) -> dict[str, Any]:
    entry_quote = dict(row.entry_quote or {})
    expected_output = entry_quote.get("expected_out_amount")
    conservative_output = entry_quote.get("conservative_out_amount")
    try:
        expected_output_raw = int(expected_output)
    except (TypeError, ValueError):
        expected_output_raw = int(row.entry_output_token_raw)
    try:
        conservative_output_raw = int(conservative_output)
    except (TypeError, ValueError):
        conservative_output_raw = int(row.entry_output_token_raw)
    payload = {
        "position_id": row.position_id,
        "entry_signature": row.entry_signature,
        "token_mint": row.token_mint,
        "token_decimals": int(row.token_decimals),
        "entry_signal_at": iso(row.entry_signal_at),
        "entry_sequence": int(row.id),
        "entry_input_lamports": int(row.entry_input_lamports),
        "entry_expected_output_token_raw": expected_output_raw,
        "entry_conservative_output_token_raw": conservative_output_raw,
        "entry_output_token_raw": int(row.entry_output_token_raw),
        "allocated_entry_fee_lamports": int(row.allocated_entry_fee_lamports),
        "entry_price_deterioration_bps": _round(row.entry_price_deterioration_bps),
        "entry_price_impact_bps": _round(row.entry_price_impact_bps),
        "entry_quote_latency_ms": row.entry_quote_latency_ms,
        "entry_end_to_quote_ms": row.entry_end_to_quote_ms,
        "entry_transaction_built": bool(row.entry_transaction_built),
        "entry_copyable": bool(row.entry_copyable),
        "close_reason": row.close_reason,
        "exit_source": row.exit_source,
        "last_exit_signature": row.last_exit_signature,
        "seed_quality": "EXACT_REALTIME_ENTRY_QUOTE_FOR_RECOVERY_EXIT_RECONSTRUCTION",
    }
    payload["evidence_sha256"] = canonical_sha256(payload)
    return payload


def load_official_snapshot(database_public_url: str) -> dict[str, Any]:
    url = readonly_database_url(database_public_url)
    engine = create_engine(url, future=True, pool_pre_ping=True)
    connection = None
    transaction = None
    try:
        connection = engine.connect()
        transaction = connection.begin()
        connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        database_name = str(connection.execute(text("SELECT current_database()" )).scalar_one())
        read_only = str(connection.execute(text("SHOW transaction_read_only")).scalar_one()).lower()
        alembic_head = str(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        )
        if database_name != M64_EXPECTED_DATABASE:
            raise M64ReadonlyAuditError(
                f"Database inatteso: {database_name}; atteso={M64_EXPECTED_DATABASE}."
            )
        if read_only != "on":
            raise M64ReadonlyAuditError("La transazione database non e read-only.")
        if alembic_head != M64_EXPECTED_ALEMBIC_HEAD:
            raise M64ReadonlyAuditError(
                f"Alembic head inattesa: {alembic_head}; attesa={M64_EXPECTED_ALEMBIC_HEAD}."
            )
        with Session(bind=connection, autoflush=False, expire_on_commit=False) as db:
            campaigns = list(
                db.scalars(
                    select(CanonicalParserGen4CopyabilityCampaign).order_by(
                        CanonicalParserGen4CopyabilityCampaign.id
                    )
                )
            )
            campaign = next(
                (
                    item
                    for item in campaigns
                    if item.campaign_id == M64_TARGET_CAMPAIGN_ID
                ),
                None,
            )
            if campaign is None:
                raise M64ReadonlyAuditError("Campagna candidata M64 non trovata.")
            active_campaign_ids = [
                item.campaign_id for item in campaigns if item.status == "ACTIVE"
            ]
            if active_campaign_ids != [M64_TARGET_CAMPAIGN_ID]:
                raise M64ReadonlyAuditError(
                    "La campagna candidata non e l'unica campagna ACTIVE."
                )
            primary_campaign = next(
                (
                    item
                    for item in campaigns
                    if item.campaign_id == M64_PRIMARY_CAMPAIGN_ID
                ),
                None,
            )
            if primary_campaign is None or primary_campaign.status != "PAUSED":
                raise M64ReadonlyAuditError(
                    "La campagna primaria M63 non risulta PAUSED."
                )
            forward_feed = db.scalar(
                select(CanonicalParserGen4ForwardFeedState).where(
                    CanonicalParserGen4ForwardFeedState.state_id
                    == M64_DISABLED_FORWARD_FEED_STATE_ID
                )
            )
            if forward_feed is None or bool(forward_feed.enabled):
                raise M64ReadonlyAuditError(
                    "Il vecchio forward feed M63 non risulta DISABLED."
                )
            if campaign.campaign_role != "QUALIFIED_CANDIDATE":
                raise M64ReadonlyAuditError("La campagna target non e QUALIFIED_CANDIDATE.")
            if campaign.status != "ACTIVE":
                raise M64ReadonlyAuditError("La campagna candidata non e ACTIVE.")
            if list(campaign.frozen_wallets or []) != [M64_TARGET_WALLET]:
                raise M64ReadonlyAuditError("Il wallet congelato della campagna e inatteso.")
            if campaign.policy_version != M64_EXPECTED_POLICY_VERSION:
                raise M64ReadonlyAuditError("Versione policy Gen4 inattesa.")
            positions = list(
                db.scalars(
                    select(CanonicalParserGen4CopyabilityPosition)
                    .where(
                        CanonicalParserGen4CopyabilityPosition.campaign_db_id
                        == campaign.id
                    )
                    .order_by(
                        CanonicalParserGen4CopyabilityPosition.closed_at,
                        CanonicalParserGen4CopyabilityPosition.id,
                    )
                )
            )
            receipts = list(
                db.scalars(
                    select(CanonicalParserGen4WebhookReceipt)
                    .where(
                        CanonicalParserGen4WebhookReceipt.campaign_db_id
                        == campaign.id
                    )
                    .order_by(
                        CanonicalParserGen4WebhookReceipt.received_at,
                        CanonicalParserGen4WebhookReceipt.id,
                    )
                )
            )
            closed = [
                item
                for item in positions
                if item.status == "CLOSED"
                and item.entry_source == "WEBHOOK"
                and item.exit_source == "WEBHOOK"
                and item.entry_copyable
                and item.exit_copyable
                and item.pnl_lamports is not None
            ]
            quarantined_seed_positions = [
                item
                for item in positions
                if item.status == "CLOSED"
                and item.entry_source == "WEBHOOK"
                and item.exit_source == "RECOVERY_ONLY"
                and item.entry_copyable
                and not item.exit_copyable
                and item.pnl_lamports is None
                and item.close_reason == "RECOVERY_GAP_QUARANTINE"
            ]
            if int(campaign.closed_trade_count or 0) != M64_OFFICIAL_REALTIME_TRADES:
                raise M64ReadonlyAuditError(
                    "Il contatore ufficiale non e 83; audit interrotto senza scritture."
                )
            if len(closed) != M64_OFFICIAL_REALTIME_TRADES:
                raise M64ReadonlyAuditError(
                    "Le posizioni ufficiali chiuse non coincidono con il contatore 83."
                )
            if (
                len(quarantined_seed_positions)
                != M64_EXPECTED_QUARANTINED_SEED_POSITIONS
            ):
                raise M64ReadonlyAuditError(
                    "Le posizioni seed RECOVERY_GAP_QUARANTINE non coincidono "
                    "con la baseline M63."
                )
            open_positions = [
                item for item in positions if item.status in {"OPEN", "OPEN_PARTIAL"}
            ]
            if open_positions:
                raise M64ReadonlyAuditError(
                    "Esistono posizioni copyability ufficiali aperte; continuita M64 non provata."
                )
            recovery_receipt_count = sum(
                item.source == "RECOVERY_ONLY" for item in receipts
            )
            if recovery_receipt_count != M64_EXPECTED_RECOVERY_RECEIPTS:
                raise M64ReadonlyAuditError(
                    "Conteggio RECOVERY_ONLY inatteso; baseline M63 non congelata."
                )
            metadata = dict(campaign.technical_metadata or {})
            containment = metadata.get(M64_RECOVERY_METADATA_KEY)
            containment = dict(containment) if isinstance(containment, dict) else {}
            boundary_utc = containment.get("public_rpc_recovery_after_utc")
            boundary_signature = str(
                containment.get("public_rpc_recovery_after_signature") or ""
            ).strip()
            latest_webhook = next(
                (item for item in reversed(receipts) if item.source == "WEBHOOK"),
                None,
            )
            if not boundary_utc and latest_webhook is not None:
                boundary_utc = iso(latest_webhook.block_time or latest_webhook.received_at)
            if not boundary_signature and latest_webhook is not None:
                boundary_signature = latest_webhook.signature
            if not boundary_utc or not boundary_signature:
                raise M64ReadonlyAuditError("Confine pubblico M63 incompleto.")
            try:
                boundary = aware(datetime.fromisoformat(str(boundary_utc)))
            except (TypeError, ValueError) as error:
                raise M64ReadonlyAuditError("Confine pubblico M63 non valido.") from error
            official_trades = [_position_record(item) for item in closed]
            official_metrics = calculate_trade_metrics(
                official_trades,
                evidence_quality="EXACT_PRODUCTION_READ_ONLY",
            )
            if (
                int(official_metrics["net_pnl_lamports"])
                != M64_EXPECTED_OFFICIAL_NET_PNL_LAMPORTS
            ):
                raise M64ReadonlyAuditError(
                    "PnL ufficiale 83 inatteso; baseline candidata modificata."
                )
            stored_metrics = dict(campaign.metrics or {})
            if int(stored_metrics.get("closed_copyable_trades") or 0) != (
                M64_OFFICIAL_REALTIME_TRADES
            ):
                raise M64ReadonlyAuditError(
                    "Conteggio metriche Gen4 salvate inatteso."
                )
            if int(stored_metrics.get("net_pnl_lamports") or 0) != int(
                official_metrics["net_pnl_lamports"]
            ):
                raise M64ReadonlyAuditError(
                    "PnL ricalcolato non coincide con le metriche Gen4 salvate."
                )
            for metric_name in (
                "net_return_percent",
                "profit_factor",
                "win_rate_percent",
                "maximum_drawdown_percent",
            ):
                stored_value = stored_metrics.get(metric_name)
                recalculated_value = official_metrics.get(metric_name)
                if stored_value is None or recalculated_value is None or abs(
                    float(stored_value) - float(recalculated_value)
                ) > 0.000001:
                    raise M64ReadonlyAuditError(
                        f"Metrica Gen4 salvata non riprodotta: {metric_name}."
                    )
            if int(stored_metrics.get("maximum_drawdown_lamports") or 0) != int(
                official_metrics["maximum_drawdown_lamports"]
            ):
                raise M64ReadonlyAuditError(
                    "Drawdown Gen4 salvato non riprodotto con ordine production."
                )
            rejected_positions = [item for item in positions if item.status == "REJECTED"]
            executable_entry_count = int(campaign.executable_entry_count or 0)
            rejected_entry_count = int(campaign.rejected_entry_count or 0)
            admission_denominator = executable_entry_count + rejected_entry_count
            if rejected_entry_count != len(rejected_positions):
                raise M64ReadonlyAuditError(
                    "Contatore entrate respinte non coerente con le posizioni."
                )
            if executable_entry_count != 85 or rejected_entry_count != 9:
                raise M64ReadonlyAuditError(
                    "Contatori entrate Gen4 inattesi; baseline 83 modificata."
                )
            report = {
                "database": {
                    "database_name": database_name,
                    "transaction_read_only": read_only,
                    "alembic_head": alembic_head,
                },
                "campaign": {
                    "campaign_id": campaign.campaign_id,
                    "campaign_role": campaign.campaign_role,
                    "status": campaign.status,
                    "wallet": M64_TARGET_WALLET,
                    "policy_version": campaign.policy_version,
                    "policy_hash": campaign.policy_hash,
                    "policy_snapshot": dict(campaign.policy_snapshot or {}),
                    "simulated_input_lamports": int(campaign.simulated_input_lamports),
                    "slippage_bps": int(campaign.slippage_bps),
                    "estimated_network_fee_lamports": int(
                        campaign.estimated_network_fee_lamports
                    ),
                    "max_signal_age_ms": int(campaign.max_signal_age_ms),
                    "max_quote_latency_ms": int(campaign.max_quote_latency_ms),
                    "max_price_impact_bps": int(campaign.max_price_impact_bps),
                    "max_price_deterioration_bps": int(
                        campaign.max_price_deterioration_bps
                    ),
                    "minimum_profit_factor": float(campaign.minimum_profit_factor),
                    "maximum_drawdown_percent": float(
                        campaign.maximum_drawdown_percent
                    ),
                    "official_closed_trade_count": int(campaign.closed_trade_count),
                    "recovery_receipt_count": recovery_receipt_count,
                    "quarantined_seed_position_count": len(
                        quarantined_seed_positions
                    ),
                    "open_position_count_observed": len(open_positions),
                    "executable_entry_count_observed": executable_entry_count,
                    "rejected_entry_count_observed": rejected_entry_count,
                    "official_admission_attempt_count": admission_denominator,
                    "official_entry_reject_rate_percent": _round(
                        rejected_entry_count / admission_denominator * 100.0
                        if admission_denominator
                        else 0.0,
                        8,
                    ),
                    "stored_metrics": stored_metrics,
                    "stored_evidence_gaps": list(campaign.evidence_gaps or []),
                },
                "boundary": {
                    "after_utc": iso(boundary),
                    "after_signature": boundary_signature,
                    "source": "M63_FROZEN_METADATA",
                },
                "containment": {
                    "active_campaign_ids": active_campaign_ids,
                    "primary_campaign_id": M64_PRIMARY_CAMPAIGN_ID,
                    "primary_campaign_status": primary_campaign.status,
                    "forward_feed_state_id": M64_DISABLED_FORWARD_FEED_STATE_ID,
                    "forward_feed_enabled": bool(forward_feed.enabled),
                    "public_rpc_recovery_completed_at": containment.get(
                        "public_rpc_recovery_completed_at"
                    ),
                    "public_rpc_recovery_signature_count": containment.get(
                        "public_rpc_recovery_signature_count"
                    ),
                    "public_rpc_recovery_counts_as_realtime_proof": False,
                    "recovery_gap_quarantine": metadata.get(
                        M64_RECOVERY_GAP_METADATA_KEY
                    ),
                },
                "official_trades": official_trades,
                "quarantined_seed_positions": [
                    _quarantined_seed_record(item)
                    for item in quarantined_seed_positions
                ],
                "official_metrics": official_metrics,
            }
            report["snapshot_sha256"] = canonical_sha256(report)
            return report
    finally:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        if connection is not None:
            connection.close()
        engine.dispose()


class PublicSolanaRpc:
    def __init__(
        self,
        url: str,
        *,
        client: Any | None = None,
        throttle_seconds: float = 0.60,
        maximum_attempts: int = 8,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        parsed = urlsplit(str(url or "").strip())
        hostname = str(parsed.hostname or "").lower()
        if parsed.scheme != "https" or not hostname:
            raise M64ReadonlyAuditError("L'RPC pubblico deve usare HTTPS.")
        if "helius" in hostname:
            raise M64ReadonlyAuditError("M64 rifiuta esplicitamente endpoint Helius.")
        if parsed.username or parsed.password:
            raise M64ReadonlyAuditError("L'RPC pubblico non deve contenere credenziali.")
        self.url = str(url).strip()
        self.public_origin = f"{parsed.scheme}://{hostname}"
        self.client = client or httpx.Client(timeout=45.0)
        self._owns_client = client is None
        self.throttle_seconds = max(0.0, float(throttle_seconds))
        self.maximum_attempts = max(1, min(int(maximum_attempts), 8))
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn
        self.last_request_at: float | None = None
        self.requests = 0
        self.retry_429 = 0
        self.retry_5xx = 0
        self.retry_network = 0

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _throttle(self) -> None:
        if self.last_request_at is None:
            return
        remaining = self.throttle_seconds - (
            self.monotonic_fn() - self.last_request_at
        )
        if remaining > 0:
            self.sleep_fn(remaining)

    def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        delay = min(8.0, 0.75 * (2 ** max(0, attempt - 1)))
        if retry_after:
            try:
                delay = max(delay, min(30.0, float(retry_after)))
            except ValueError:
                pass
        self.sleep_fn(delay)

    def call(self, method: str, params: list[Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.maximum_attempts + 1):
            self._throttle()
            self.requests += 1
            self.last_request_at = self.monotonic_fn()
            try:
                response = self.client.post(
                    self.url,
                    json={
                        "jsonrpc": "2.0",
                        "id": self.requests,
                        "method": method,
                        "params": params,
                    },
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 429:
                    self.retry_429 += 1
                    if attempt < self.maximum_attempts:
                        self._backoff(attempt, response.headers.get("Retry-After"))
                        continue
                if 500 <= response.status_code <= 599:
                    self.retry_5xx += 1
                    if attempt < self.maximum_attempts:
                        self._backoff(attempt)
                        continue
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise M64ReadonlyAuditError("Risposta JSON-RPC inattesa.")
                if body.get("error"):
                    code = (body.get("error") or {}).get("code")
                    raise M64ReadonlyAuditError(
                        f"RPC pubblico {method} fallito; code={code}."
                    )
                return body.get("result")
            except (httpx.HTTPError, ValueError, M64ReadonlyAuditError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPError):
                    self.retry_network += 1
                if attempt < self.maximum_attempts:
                    self._backoff(attempt)
                    continue
        raise M64ReadonlyAuditError(
            f"RPC pubblico non disponibile per {method}: "
            f"{type(last_error).__name__}."
        ) from None

    def stats(self) -> dict[str, Any]:
        return {
            "public_origin": self.public_origin,
            "requests": self.requests,
            "retry_429": self.retry_429,
            "retry_5xx": self.retry_5xx,
            "retry_network": self.retry_network,
            "throttle_seconds": self.throttle_seconds,
            "maximum_attempts": self.maximum_attempts,
            "helius_requests": 0,
        }


def collect_public_transactions(
    rpc: PublicSolanaRpc,
    *,
    wallet_address: str,
    after: datetime,
    after_signature: str,
    maximum_signatures: int,
) -> dict[str, Any]:
    maximum = max(1, min(int(maximum_signatures), 5000))
    boundary_epoch = int(aware(after).timestamp())  # type: ignore[union-attr]
    collected: dict[str, dict[str, Any]] = {}
    before: str | None = None
    boundary_reached = False
    while len(collected) < maximum and not boundary_reached:
        page_limit = min(1000, maximum - len(collected))
        config: dict[str, Any] = {
            "commitment": "finalized",
            "limit": page_limit,
            "until": after_signature,
        }
        if before:
            config["before"] = before
        page = rpc.call("getSignaturesForAddress", [wallet_address, config])
        if not isinstance(page, list):
            raise M64ReadonlyAuditError("Elenco firme RPC non valido.")
        if not page:
            boundary_reached = True
            break
        for item in page:
            if not isinstance(item, dict):
                continue
            signature = str(item.get("signature") or "").strip()
            block_time = item.get("blockTime")
            if block_time is not None and int(block_time) <= boundary_epoch:
                boundary_reached = True
                break
            if signature and item.get("err") is None:
                collected.setdefault(signature, dict(item))
        before = str((page[-1] or {}).get("signature") or "").strip()
        if len(page) < page_limit or not before:
            boundary_reached = True
    if len(collected) >= maximum and not boundary_reached:
        return {
            "boundary_reached": False,
            "signature_limit_reached": True,
            "signatures": [],
            "transactions": [],
            "unavailable": [],
        }
    signatures = sorted(
        collected.values(),
        key=lambda item: (
            int(item.get("blockTime") or 0),
            int(item.get("slot") or 0),
            str(item.get("signature") or ""),
        ),
    )
    transactions: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for item in signatures:
        signature = str(item.get("signature") or "")
        result = rpc.call(
            "getTransaction",
            [
                signature,
                {
                    "commitment": "finalized",
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 1,
                },
            ],
        )
        if not isinstance(result, dict):
            unavailable.append(signature)
            continue
        payload = dict(result)
        payload.setdefault("signature", signature)
        transactions.append(payload)
    return {
        "boundary_reached": boundary_reached,
        "signature_limit_reached": False,
        "signatures": signatures,
        "transactions": transactions,
        "unavailable": unavailable,
    }


def parse_public_transactions(
    transactions: Iterable[dict[str, Any]],
    *,
    wallet_address: str,
) -> dict[str, Any]:
    if GEN4_COPYABILITY_RAW_PARSER_VERSION != M64_EXPECTED_PARSER_VERSION:
        raise M64ReadonlyAuditError("Versione parser M62 inattesa.")
    if GEN4_COPYABILITY_POLICY_VERSION != M64_EXPECTED_POLICY_VERSION:
        raise M64ReadonlyAuditError("Versione policy Gen4 inattesa.")
    events: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for sequence, raw in enumerate(transactions, start=1):
        payload = dict(raw)
        transaction_hash = canonical_sha256(payload)
        signature = str(payload.get("signature") or "")
        if not signature:
            nested = payload.get("transaction") or {}
            signatures = nested.get("signatures") if isinstance(nested, dict) else []
            signature = str((signatures or [""])[0])
        evidence_rows.append(
            {
                "sequence": sequence,
                "signature": signature,
                "transaction_sha256": transaction_hash,
            }
        )
        try:
            signal = parse_raw_copyability_signal(
                payload,
                frozen_wallets=[wallet_address],
            )
            fee = int(signal.evidence.get("fee_lamports") or 0)
            event = {
                "sequence": sequence,
                "signature": signal.signature,
                "slot": signal.slot,
                "block_time": iso(signal.block_time),
                "wallet_address": signal.wallet_address,
                "side": signal.side,
                "token_mint": signal.token_mint,
                "token_decimals": signal.token_decimals,
                "token_delta_raw": signal.token_delta_raw,
                "token_pre_raw": signal.token_pre_raw,
                "sell_fraction": signal.sell_fraction,
                "sol_equivalent_delta_lamports": signal.sol_equivalent_delta_lamports,
                "source_network_fee_lamports": fee,
                "transaction_sha256": transaction_hash,
                "parser_version": signal.evidence.get("raw_parser_version"),
                "price_basis": "SAME_TRANSACTION_SOL_OR_WSOL_AND_TOKEN_DELTAS",
            }
            events.append(event)
        except CanonicalParserGen4CopyabilityError as error:
            rejected.append(
                {
                    "sequence": sequence,
                    "signature": signature,
                    "transaction_sha256": transaction_hash,
                    "error_code": error.code,
                    "parser_evidence": error.evidence,
                }
            )
    events.sort(
        key=lambda item: (
            str(item.get("block_time") or ""),
            int(item.get("slot") or 0),
            int(item.get("sequence") or 0),
        )
    )
    return {
        "events": events,
        "rejected": rejected,
        "transaction_evidence": evidence_rows,
    }


def _allocate_integer(total: int, weights: list[int]) -> list[int]:
    if total <= 0 or not weights or sum(weights) <= 0:
        return [0 for _ in weights]
    denominator = sum(weights)
    allocations = [(total * weight) // denominator for weight in weights]
    remainder = total - sum(allocations)
    for index in range(remainder):
        allocations[index % len(allocations)] += 1
    return allocations


@dataclass
class ReconstructedPosition:
    entry_signature: str
    token_mint: str
    token_decimals: int
    entry_signal_at: str | None
    entry_sequence: int
    entry_output_token_raw: int
    remaining_token_raw: int
    entry_input_lamports: int
    allocated_entry_fee_lamports: int
    entry_evidence_class: str
    realized_output_lamports: int = 0
    allocated_exit_fee_lamports: int = 0
    last_exit_signature: str | None = None
    exit_signatures: list[str] = field(default_factory=list)


@dataclass
class ReconstructionScenario:
    name: str
    slippage_bps: int
    estimated_network_fee_lamports: int
    simulated_input_lamports: int
    positions: list[ReconstructedPosition] = field(default_factory=list)
    closed: list[dict[str, Any]] = field(default_factory=list)
    ignored_sells: int = 0
    unevaluable_events: int = 0

    def seed(self, seed: dict[str, Any]) -> None:
        expected_output = int(
            seed.get("entry_expected_output_token_raw")
            or seed.get("entry_output_token_raw")
            or 0
        )
        conservative_output = int(
            seed.get("entry_conservative_output_token_raw")
            or seed.get("entry_output_token_raw")
            or 0
        )
        output = (
            expected_output
            if self.slippage_bps == 0
            else conservative_output
        )
        if output <= 0:
            self.unevaluable_events += 1
            return
        self.positions.append(
            ReconstructedPosition(
                entry_signature=str(seed["entry_signature"]),
                token_mint=str(seed["token_mint"]),
                token_decimals=int(seed["token_decimals"]),
                entry_signal_at=seed.get("entry_signal_at"),
                entry_sequence=int(seed.get("entry_sequence") or 0),
                entry_output_token_raw=output,
                remaining_token_raw=output,
                entry_input_lamports=int(seed["entry_input_lamports"]),
                allocated_entry_fee_lamports=(
                    self.estimated_network_fee_lamports
                    if self.estimated_network_fee_lamports > 0
                    else 0
                ),
                entry_evidence_class=(
                    "EXACT_REALTIME_ENTRY_QUOTE_FOR_RECOVERY_EXIT_RECONSTRUCTION"
                ),
            )
        )

    def process(self, event: dict[str, Any]) -> None:
        if event["side"] == "BUY":
            self._buy(event)
        else:
            self._sell(event)

    def _buy(self, event: dict[str, Any]) -> None:
        source_spend = max(
            0,
            abs(int(event.get("sol_equivalent_delta_lamports") or 0))
            - max(0, int(event.get("source_network_fee_lamports") or 0)),
        )
        source_tokens = int(event.get("token_delta_raw") or 0)
        if source_spend <= 0 or source_tokens <= 0:
            self.unevaluable_events += 1
            return
        expected_tokens = self.simulated_input_lamports * source_tokens // source_spend
        conservative_tokens = (
            expected_tokens * (10_000 - self.slippage_bps) // 10_000
        )
        if conservative_tokens <= 0:
            self.unevaluable_events += 1
            return
        self.positions.append(
            ReconstructedPosition(
                entry_signature=str(event["signature"]),
                token_mint=str(event["token_mint"]),
                token_decimals=int(event["token_decimals"]),
                entry_signal_at=event.get("block_time"),
                entry_sequence=int(event.get("sequence") or 0),
                entry_output_token_raw=conservative_tokens,
                remaining_token_raw=conservative_tokens,
                entry_input_lamports=self.simulated_input_lamports,
                allocated_entry_fee_lamports=self.estimated_network_fee_lamports,
                entry_evidence_class="PUBLIC_SAME_TRANSACTION_ONCHAIN_PROXY",
            )
        )

    def _sell(self, event: dict[str, Any]) -> None:
        positions = [
            item
            for item in self.positions
            if item.token_mint == event["token_mint"] and item.remaining_token_raw > 0
        ]
        if not positions:
            self.ignored_sells += 1
            return
        fraction = event.get("sell_fraction")
        if fraction is None or float(fraction) <= 0:
            self.unevaluable_events += 1
            return
        source_sold = abs(int(event.get("token_delta_raw") or 0))
        source_gross_proceeds = max(
            0,
            int(event.get("sol_equivalent_delta_lamports") or 0)
            + max(0, int(event.get("source_network_fee_lamports") or 0)),
        )
        if source_sold <= 0 or source_gross_proceeds <= 0:
            self.unevaluable_events += 1
            return
        weights = [item.remaining_token_raw for item in positions]
        total_remaining = sum(weights)
        amount_to_sell = min(
            total_remaining,
            max(1, int(total_remaining * min(1.0, float(fraction)))),
        )
        expected_out = amount_to_sell * source_gross_proceeds // source_sold
        conservative_out = expected_out * (10_000 - self.slippage_bps) // 10_000
        sold_allocations = _allocate_integer(amount_to_sell, weights)
        out_allocations = _allocate_integer(conservative_out, sold_allocations)
        fee_allocations = _allocate_integer(
            self.estimated_network_fee_lamports,
            sold_allocations,
        )
        for position, sold_raw, out_lamports, fee_lamports in zip(
            positions,
            sold_allocations,
            out_allocations,
            fee_allocations,
        ):
            if sold_raw <= 0:
                continue
            position.remaining_token_raw = max(
                0, position.remaining_token_raw - sold_raw
            )
            position.realized_output_lamports += out_lamports
            position.allocated_exit_fee_lamports += fee_lamports
            position.last_exit_signature = str(event["signature"])
            position.exit_signatures.append(str(event["signature"]))
            dust_limit = max(1, int(position.entry_output_token_raw * 0.001))
            if position.remaining_token_raw <= dust_limit or float(fraction) >= 0.999:
                position.remaining_token_raw = 0
                cost = (
                    position.entry_input_lamports
                    + position.allocated_entry_fee_lamports
                )
                proceeds = (
                    position.realized_output_lamports
                    - position.allocated_exit_fee_lamports
                )
                pnl = proceeds - cost
                trade = {
                    "model_scenario": self.name,
                    "entry_signature": position.entry_signature,
                    "last_exit_signature": position.last_exit_signature,
                    "exit_signatures": list(position.exit_signatures),
                    "token_mint": position.token_mint,
                    "token_decimals": position.token_decimals,
                    "entry_signal_at": position.entry_signal_at,
                    "closed_at": event.get("block_time"),
                    "entry_sequence": position.entry_sequence,
                    "entry_evidence_class": position.entry_evidence_class,
                    "close_sequence": int(event.get("sequence") or 0),
                    "entry_input_lamports": position.entry_input_lamports,
                    "entry_output_token_raw": position.entry_output_token_raw,
                    "realized_output_lamports": position.realized_output_lamports,
                    "allocated_entry_fee_lamports": position.allocated_entry_fee_lamports,
                    "allocated_exit_fee_lamports": position.allocated_exit_fee_lamports,
                    "fee_lamports": (
                        position.allocated_entry_fee_lamports
                        + position.allocated_exit_fee_lamports
                    ),
                    "cost_lamports": cost,
                    "proceeds_lamports": proceeds,
                    "pnl_lamports": pnl,
                    "return_percent": pnl / cost * 100.0 if cost > 0 else None,
                    "pricing_quality": (
                        "EXACT_REALTIME_ENTRY_QUOTE_PLUS_ESTIMATED_ONCHAIN_EXIT_PROXY"
                        if position.entry_evidence_class.startswith("EXACT_REALTIME")
                        else "ESTIMATED_SAME_TRANSACTION_ONCHAIN_PROXY"
                    ),
                    "historical_jupiter_quote": "UNAVAILABLE_NOT_INVENTED",
                }
                trade["evidence_sha256"] = canonical_sha256(trade)
                self.closed.append(trade)

    def open_positions(self) -> list[dict[str, Any]]:
        return [
            {
                "entry_signature": item.entry_signature,
                "token_mint": item.token_mint,
                "remaining_token_raw": item.remaining_token_raw,
                "entry_output_token_raw": item.entry_output_token_raw,
                "entry_signal_at": item.entry_signal_at,
            }
            for item in self.positions
            if item.remaining_token_raw > 0
        ]


def reconstruct_closed_trades(
    events: Iterable[dict[str, Any]],
    *,
    policy: dict[str, Any],
    target_closed_trades: int = M64_TARGET_RECONSTRUCTED_TRADES,
    seed_positions: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    simulated_input = int(policy["simulated_input_lamports"])
    slippage_bps = int(policy["slippage_bps"])
    fee_lamports = int(policy["estimated_network_fee_lamports"])
    scenarios = {
        "net_policy": ReconstructionScenario(
            "net_policy", slippage_bps, fee_lamports, simulated_input
        ),
        "no_slippage": ReconstructionScenario(
            "no_slippage", 0, fee_lamports, simulated_input
        ),
        "no_fees": ReconstructionScenario(
            "no_fees", slippage_bps, 0, simulated_input
        ),
        "no_costs": ReconstructionScenario("no_costs", 0, 0, simulated_input),
    }
    seeds = sorted(
        [dict(item) for item in (seed_positions or [])],
        key=lambda item: (
            str(item.get("entry_signal_at") or ""),
            int(item.get("entry_sequence") or 0),
            str(item.get("entry_signature") or ""),
        ),
    )
    seed_signatures = [str(item.get("entry_signature") or "") for item in seeds]
    if any(not item for item in seed_signatures) or len(seed_signatures) != len(
        set(seed_signatures)
    ):
        raise M64ReadonlyAuditError("Seed di ricostruzione duplicati o incompleti.")
    for seed in seeds:
        for scenario in scenarios.values():
            scenario.seed(seed)
    ordered = sorted(
        [dict(item) for item in events],
        key=lambda item: (
            str(item.get("block_time") or ""),
            int(item.get("slot") or 0),
            int(item.get("sequence") or 0),
        ),
    )
    for event in ordered:
        for scenario in scenarios.values():
            scenario.process(event)
    target = max(0, int(target_closed_trades))
    selected = scenarios["net_policy"].closed[:target]
    comparison = {
        name: {item["entry_signature"]: item for item in scenario.closed}
        for name, scenario in scenarios.items()
    }

    def enrich(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched_rows: list[dict[str, Any]] = []
        for item in items:
            trade = dict(item)
            # The scenario-level hash covers the trade before cost-impact
            # enrichment.  It must not become an input to the final hash: the
            # verifier defines evidence_sha256 as the canonical digest of all
            # other final trade fields.
            trade.pop("evidence_sha256", None)
            signature = str(item["entry_signature"])
            no_slippage = comparison["no_slippage"].get(signature)
            no_fees = comparison["no_fees"].get(signature)
            no_costs = comparison["no_costs"].get(signature)
            net = int(item["pnl_lamports"])
            slippage_impact = (
                int(no_slippage["pnl_lamports"]) - net if no_slippage else None
            )
            fee_impact = int(no_fees["pnl_lamports"]) - net if no_fees else None
            total_impact = int(no_costs["pnl_lamports"]) - net if no_costs else None
            interaction = (
                total_impact - slippage_impact - fee_impact
                if total_impact is not None
                and slippage_impact is not None
                and fee_impact is not None
                else None
            )
            trade["cost_impact"] = {
                "slippage_impact_lamports": slippage_impact,
                "fee_impact_lamports": fee_impact,
                "total_cost_impact_lamports": total_impact,
                "interaction_lamports": interaction,
                "method": "FOUR_SCENARIO_SAME_TRANSACTION_PROXY",
            }
            trade["evidence_sha256"] = canonical_sha256(trade)
            enriched_rows.append(trade)
        return enriched_rows

    all_closed = scenarios["net_policy"].closed
    complete_close_batch = list(selected)
    cutoff_key: tuple[str, int, str] | None = None
    if selected:
        cutoff = selected[-1]
        cutoff_key = (
            str(cutoff.get("closed_at") or ""),
            int(cutoff.get("close_sequence") or 0),
            str(cutoff.get("last_exit_signature") or ""),
        )
        for item in all_closed[len(selected) :]:
            item_key = (
                str(item.get("closed_at") or ""),
                int(item.get("close_sequence") or 0),
                str(item.get("last_exit_signature") or ""),
            )
            if item_key != cutoff_key:
                break
            complete_close_batch.append(item)
    enriched = enrich(selected)
    enriched_complete_batch = enrich(complete_close_batch)
    supplemental_batch = enriched_complete_batch[len(enriched) :]
    return {
        "target_closed_trades": target,
        "target_reached": len(enriched) == target,
        "all_reconstructed_closed_trade_count": len(all_closed),
        "selected_closed_trade_count": len(enriched),
        "selected_trades": enriched,
        "complete_close_batch_trade_count": len(enriched_complete_batch),
        "complete_close_batch_trades": enriched_complete_batch,
        "supplemental_cutoff_batch_trade_count": len(supplemental_batch),
        "supplemental_cutoff_batch_trades": supplemental_batch,
        "target_cut_through_close_batch": bool(supplemental_batch),
        "target_cutoff_close_key": (
            {
                "closed_at": cutoff_key[0],
                "close_sequence": cutoff_key[1],
                "last_exit_signature": cutoff_key[2],
            }
            if cutoff_key is not None
            else None
        ),
        "open_positions_at_end": scenarios["net_policy"].open_positions(),
        "ignored_sell_events": scenarios["net_policy"].ignored_sells,
        "unevaluable_price_events": scenarios["net_policy"].unevaluable_events,
        "modeled_buy_events": sum(item["side"] == "BUY" for item in ordered),
        "modeled_sell_events": sum(item["side"] == "SELL" for item in ordered),
        "seeded_open_position_count": len(seeds),
        "seeded_open_position_signatures": seed_signatures,
        "historical_entry_admission": {
            "status": "NOT_RECONSTRUCTIBLE_WITHOUT_HISTORICAL_JUPITER_QUOTES",
            "entry_reject_rate_percent": None,
            "quote_latency_ms": None,
            "price_impact_bps": None,
            "price_deterioration_bps": None,
            "price_already_moved_count": None,
            "unsigned_build_coverage_percent": None,
        },
    }


def build_audit_report(
    *,
    official_snapshot: dict[str, Any],
    public_result: dict[str, Any],
    parser_result: dict[str, Any],
    reconstruction: dict[str, Any],
    rpc_stats: dict[str, Any],
    started_at: datetime,
    completed_at: datetime,
    raw_evidence_sha256: str,
) -> dict[str, Any]:
    official_trades = list(official_snapshot["official_trades"])
    reconstructed_trades = list(reconstruction["selected_trades"])
    complete_close_batch_trades = list(
        reconstruction.get("complete_close_batch_trades")
        or reconstructed_trades
    )
    combined_trades = official_trades + reconstructed_trades
    combined_complete_close_batch_trades = (
        official_trades + complete_close_batch_trades
    )
    official_metrics = calculate_trade_metrics(
        official_trades,
        evidence_quality="EXACT_PRODUCTION_READ_ONLY",
    )
    reconstructed_metrics = calculate_trade_metrics(
        reconstructed_trades,
        evidence_quality="ESTIMATED_SAME_TRANSACTION_ONCHAIN_PROXY",
    )
    combined_metrics = calculate_trade_metrics(
        combined_trades,
        evidence_quality="MIXED_83_EXACT_PLUS_RECONSTRUCTED_PROXY",
    )
    reconstructed_complete_batch_metrics = calculate_trade_metrics(
        complete_close_batch_trades,
        evidence_quality="ESTIMATED_COMPLETE_CUTOFF_CLOSE_BATCH_SENSITIVITY",
    )
    combined_complete_batch_metrics = calculate_trade_metrics(
        combined_complete_close_batch_trades,
        evidence_quality="MIXED_83_EXACT_PLUS_COMPLETE_CLOSE_BATCH_SENSITIVITY",
    )
    official_attempts = int(
        official_snapshot["campaign"].get("official_admission_attempt_count") or 0
    )
    official_rejects = int(
        official_snapshot["campaign"].get("rejected_entry_count_observed") or 0
    )
    unknown_entries = int(reconstruction.get("modeled_buy_events") or 0)
    combined_attempts = official_attempts + unknown_entries
    reject_bounds = {
        "exact_percent": None,
        "reason": "HISTORICAL_JUPITER_ENTRY_ADMISSION_UNAVAILABLE",
        "lower_bound_percent": _round(
            official_rejects / combined_attempts * 100.0 if combined_attempts else 0.0,
            8,
        ),
        "upper_bound_percent": _round(
            (official_rejects + unknown_entries) / combined_attempts * 100.0
            if combined_attempts
            else 0.0,
            8,
        ),
    }
    reconstructed_n = len(reconstructed_trades)
    history_complete = bool(public_result.get("boundary_reached")) and not bool(
        public_result.get("signature_limit_reached")
    ) and not list(public_result.get("unavailable") or [])
    report: dict[str, Any] = {
        "audit": "PASS",
        "scope": "M64_GEN4_83_PLUS_RECONSTRUCTED_CLOSED_TRADES_READ_ONLY",
        "audit_version": M64_AUDIT_VERSION,
        "started_at_utc": iso(started_at),
        "completed_at_utc": iso(completed_at),
        "source": {
            "expected_git_head": M64_EXPECTED_GIT_HEAD,
            "expected_alembic_head": M64_EXPECTED_ALEMBIC_HEAD,
            "parser_version": GEN4_COPYABILITY_RAW_PARSER_VERSION,
            "policy_version": GEN4_COPYABILITY_POLICY_VERSION,
            "raw_evidence_sha256": raw_evidence_sha256,
        },
        "safety": {
            "helius_requests": 0,
            "database_writes": 0,
            "backend_posts": 0,
            "railway_mutations": 0,
            "jupiter_historical_quote_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "signer_access": False,
            "official_counter_mutated": False,
            "recovery_counted_as_realtime_proof": False,
        },
        "database": official_snapshot["database"],
        "campaign": official_snapshot["campaign"],
        "boundary": official_snapshot["boundary"],
        "containment": official_snapshot["containment"],
        "public_rpc": {
            **rpc_stats,
            "boundary_reached": bool(public_result.get("boundary_reached")),
            "signature_limit_reached": bool(
                public_result.get("signature_limit_reached")
            ),
            "signatures_found": len(public_result.get("signatures") or []),
            "transactions_fetched": len(public_result.get("transactions") or []),
            "transactions_unavailable": list(public_result.get("unavailable") or []),
            "history_complete": history_complete,
        },
        "parser": {
            "parsed_event_count": len(parser_result["events"]),
            "rejected_transaction_count": len(parser_result["rejected"]),
            "raw_parser_reject_rate_percent": _round(
                len(parser_result["rejected"])
                / max(
                    1,
                    len(parser_result["events"]) + len(parser_result["rejected"]),
                )
                * 100.0,
                8,
            ),
            "rejections": parser_result["rejected"],
        },
        "samples": {
            "official_realtime": {
                "closed_trade_count": M64_OFFICIAL_REALTIME_TRADES,
                "evidence_class": "OFFICIAL_REALTIME",
                "metrics": official_metrics,
                "trades": official_trades,
                "entry_reject_rate_percent": official_snapshot["campaign"].get(
                    "official_entry_reject_rate_percent"
                ),
            },
            "reconstructed": {
                "closed_trade_count": reconstructed_n,
                "target_closed_trade_count": M64_TARGET_RECONSTRUCTED_TRADES,
                "target_reached": bool(reconstruction["target_reached"]),
                "evidence_class": "RECOVERY_ANALYTIC_ONLY_NOT_REALTIME_PROOF",
                "metrics": reconstructed_metrics,
                "trades": reconstructed_trades,
                "open_positions_at_end": reconstruction["open_positions_at_end"],
                "historical_entry_admission": reconstruction[
                    "historical_entry_admission"
                ],
                "seeded_open_position_count": reconstruction.get(
                    "seeded_open_position_count", 0
                ),
            },
            "combined_equivalent": {
                "closed_trade_count": M64_OFFICIAL_REALTIME_TRADES + reconstructed_n,
                "target_100_reached": reconstructed_n == M64_TARGET_RECONSTRUCTED_TRADES,
                "evidence_class": "ANALYTIC_EQUIVALENT_NOT_OFFICIAL_REALTIME_PROOF",
                "metrics": combined_metrics,
                "entry_reject_rate_bounds": reject_bounds,
            },
            "cutoff_complete_batch_sensitivity": {
                "closed_trade_count": M64_OFFICIAL_REALTIME_TRADES
                + len(complete_close_batch_trades),
                "reconstructed_closed_trade_count": len(
                    complete_close_batch_trades
                ),
                "target_cut_through_close_batch": bool(
                    reconstruction.get("target_cut_through_close_batch")
                ),
                "supplemental_cutoff_batch_trade_count": int(
                    reconstruction.get("supplemental_cutoff_batch_trade_count")
                    or 0
                ),
                "evidence_class": (
                    "ANALYTIC_CUTOFF_BATCH_SENSITIVITY_NOT_REALTIME_PROOF"
                ),
                "reconstructed_metrics": reconstructed_complete_batch_metrics,
                "combined_metrics": combined_complete_batch_metrics,
                "supplemental_trades": list(
                    reconstruction.get("supplemental_cutoff_batch_trades") or []
                ),
            },
        },
        "reconstruction": {
            key: value
            for key, value in reconstruction.items()
            if key
            not in {
                "selected_trades",
                "complete_close_batch_trades",
                "supplemental_cutoff_batch_trades",
            }
        },
        "evidence_quality": {
            "official_83": "EXACT_PRODUCTION_READ_ONLY",
            "raw_signatures_and_transactions": (
                "COMPLETE_PUBLIC_FINALIZED" if history_complete else "INCOMPLETE"
            ),
            "round_trip_pairing": "DETERMINISTIC_NO_LOOKAHEAD_GEN4_PRO_RATA",
            "reconstructed_prices": "ESTIMATED_SAME_TRANSACTION_ONCHAIN_PROXY",
            "quarantined_seed_entries": (
                "EXACT_REALTIME_ENTRY_QUOTE_FOR_RECOVERY_EXIT_RECONSTRUCTION"
            ),
            "fees": "EXACT_FROZEN_POLICY_PARAMETER",
            "slippage": "EXACT_FROZEN_BPS_APPLIED_TO_PROXY",
            "historical_jupiter_quotes": "UNAVAILABLE_NOT_INVENTED",
            "historical_quote_latency": "UNAVAILABLE",
            "historical_price_impact": "UNAVAILABLE",
            "historical_price_already_moved": "UNAVAILABLE",
        },
        "verdict": {
            "audit_history_complete": history_complete,
            "seventeen_round_trips_found": reconstructed_n
            == M64_TARGET_RECONSTRUCTED_TRADES,
            "combined_equivalent_sample": M64_OFFICIAL_REALTIME_TRADES
            + reconstructed_n,
            "target_cut_through_close_batch": bool(
                reconstruction.get("target_cut_through_close_batch")
            ),
            "official_realtime_counter_remains": M64_OFFICIAL_REALTIME_TRADES,
            "micro_live_gate_auto_authorized": False,
            "reason": (
                "ANALYTIC_SAMPLE_100_AVAILABLE_WITH_HISTORICAL_QUOTE_GAPS"
                if reconstructed_n == M64_TARGET_RECONSTRUCTED_TRADES
                and history_complete
                else "FEWER_THAN_17_COMPLETE_ROUND_TRIPS_OR_INCOMPLETE_HISTORY"
            ),
        },
    }
    report["integrity"] = {
        "report_payload_sha256": canonical_sha256(report),
        "full_signatures_preserved": True,
        "raw_transaction_hashes_preserved": True,
    }
    return report


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
