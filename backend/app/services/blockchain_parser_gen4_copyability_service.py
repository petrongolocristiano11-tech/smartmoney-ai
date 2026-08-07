from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.constants import (
    GEN4_MANDATORY_EXCLUDED_PRICE_MINTS,
    SOL_MINT,
)
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4CopyabilityPosition,
    CanonicalParserGen4CopyabilityWorkerState,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.models.gen4_forward_shadow import CanonicalParserGen4ForwardCampaign
from backend.app.services.jupiter_swap_client import (
    JupiterOrderResult,
    JupiterSwapClient,
    sanitize_jupiter_payload,
)
from backend.app.services.live_trading_errors import JupiterSwapError


GEN4_COPYABILITY_POLICY_VERSION = "canonical-parser-gen4-realtime-copyability/1"
GEN4_COPYABILITY_START_CONFIRMATION = "START_GEN4_REALTIME_COPYABILITY"
GEN4_COPYABILITY_STOP_CONFIRMATION = "STOP_GEN4_REALTIME_COPYABILITY"
GEN4_COPYABILITY_PROCESS_CONFIRMATION = "PROCESS_GEN4_COPYABILITY_QUEUE"
GEN4_COPYABILITY_WEBHOOK_CONFIRMATION = "CONFIGURE_GEN4_COPYABILITY_WEBHOOK"
GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION = "START_GEN4_QUALIFIED_CANDIDATE_COPYABILITY"

CAMPAIGN_ROLE_PRIMARY = "PRIMARY_FORWARD"
CAMPAIGN_ROLE_CANDIDATE = "QUALIFIED_CANDIDATE"
SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

SOURCE_WEBHOOK = "WEBHOOK"
SOURCE_RECOVERY = "RECOVERY_ONLY"

RECEIPT_RECEIVED = "RECEIVED"
RECEIPT_PROCESSING = "PROCESSING"
RECEIPT_PROCESSED = "PROCESSED"
RECEIPT_IGNORED = "IGNORED"
RECEIPT_FAILED = "FAILED"
RECEIPT_EXCLUDED_RECOVERY = "EXCLUDED_RECOVERY"

POSITION_OPEN = "OPEN"
POSITION_OPEN_PARTIAL = "OPEN_PARTIAL"
POSITION_CLOSED = "CLOSED"
POSITION_REJECTED = "REJECTED"

LAMPORTS_PER_SOL = 1_000_000_000


class CanonicalParserGen4CopyabilityError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ParsedRawSignal:
    signature: str
    slot: int | None
    block_time: datetime | None
    wallet_address: str
    side: str
    token_mint: str
    token_decimals: int
    token_delta_raw: int
    token_pre_raw: int
    sol_equivalent_delta_lamports: int | None
    wallet_effective_price_sol: float | None
    sell_fraction: float | None
    evidence: dict[str, Any]


@dataclass(frozen=True)
class QuoteSnapshot:
    requested_at: datetime
    received_at: datetime
    latency_ms: int
    result: JupiterOrderResult
    sanitized: dict[str, Any]


@dataclass(frozen=True)
class ProcessSummary:
    receipts_processed: int = 0
    quotes_requested: int = 0
    entries_opened: int = 0
    entries_rejected: int = 0
    exits_applied: int = 0
    positions_closed: int = 0
    receipts_ignored: int = 0
    failures: int = 0

    def merge(self, other: "ProcessSummary") -> "ProcessSummary":
        return ProcessSummary(
            receipts_processed=self.receipts_processed + other.receipts_processed,
            quotes_requested=self.quotes_requested + other.quotes_requested,
            entries_opened=self.entries_opened + other.entries_opened,
            entries_rejected=self.entries_rejected + other.entries_rejected,
            exits_applied=self.exits_applied + other.exits_applied,
            positions_closed=self.positions_closed + other.positions_closed,
            receipts_ignored=self.receipts_ignored + other.receipts_ignored,
            failures=self.failures + other.failures,
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None, *, fallback: datetime | None = None) -> datetime:
    if value is None:
        value = fallback or _utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return _aware(value)
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _safe_message(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * max(0.0, min(percentile, 1.0))
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _policy_snapshot() -> dict[str, Any]:
    snapshot = {
        "policy_version": GEN4_COPYABILITY_POLICY_VERSION,
        "minimum_observation_days": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MIN_OBSERVATION_DAYS", 21)
        ),
        "minimum_closed_trades": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MIN_CLOSED_TRADES", 30)
        ),
        "proof_closed_trades": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_PROOF_CLOSED_TRADES", 100)
        ),
        "simulated_input_lamports": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_SIMULATED_INPUT_LAMPORTS", 10_000_000)
        ),
        "slippage_bps": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_SLIPPAGE_BPS", 300)
        ),
        "max_signal_age_ms": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_SIGNAL_AGE_MS", 20_000)
        ),
        "max_quote_latency_ms": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_QUOTE_LATENCY_MS", 5_000)
        ),
        "max_price_impact_bps": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PRICE_IMPACT_BPS", 500)
        ),
        "max_price_deterioration_bps": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PRICE_DETERIORATION_BPS", 1_000)
        ),
        "estimated_network_fee_lamports": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_ESTIMATED_NETWORK_FEE_LAMPORTS", 100_000)
        ),
        "max_processing_attempts": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PROCESSING_ATTEMPTS", 3)
        ),
        "minimum_webhook_coverage_percent": float(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MIN_WEBHOOK_COVERAGE_PERCENT", 95.0)
        ),
        "minimum_profit_factor": float(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MIN_PROFIT_FACTOR", 1.2)
        ),
        "maximum_drawdown_percent": float(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_DRAWDOWN_PERCENT", 20.0)
        ),
        "quote_taker_configured": bool(
            str(getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_QUOTE_TAKER", "") or "").strip()
        ),
        "entry_base_mint": SOL_MINT,
        "entry_base_asset": "SOL",
        "webhook_type": "raw",
        "webhook_confirmation": "confirmed",
        "recovery_events_excluded": True,
        "mirrored_wallet_exit": True,
        "partial_exit_allocation": "PRO_RATA",
        "live_execution": False,
        "paper_execution": False,
        "automatic_live_activation": False,
    }
    return snapshot


def _safety(*, campaign_role: str = CAMPAIGN_ROLE_PRIMARY) -> dict[str, Any]:
    return {
        "scope": "GEN4_REALTIME_COPYABILITY_SHADOW",
        "wallets": (
            "FROZEN_FORWARD_CAMPAIGN_ONLY"
            if campaign_role == CAMPAIGN_ROLE_PRIMARY
            else "RIGIDLY_VERIFIED_QUALIFIED_CANDIDATE_SET"
        ),
        "helius_webhook": "RAW_CONFIRMED",
        "jupiter": "QUOTE_AND_UNSIGNED_BUILD_ONLY",
        "signer_access": False,
        "signed_transactions": 0,
        "submitted_transactions": 0,
        "paper_orders_created": 0,
        "live_orders_created": 0,
        "recovery_events_counted_as_realtime": False,
        "automatic_live_activation": False,
    }


def _active_forward_campaign(db: Session) -> CanonicalParserGen4ForwardCampaign:
    row = db.scalar(
        select(CanonicalParserGen4ForwardCampaign)
        .where(CanonicalParserGen4ForwardCampaign.status == "ACTIVE")
        .order_by(desc(CanonicalParserGen4ForwardCampaign.anchor_at))
        .limit(1)
    )
    if row is None:
        raise CanonicalParserGen4CopyabilityError(
            "Nessuna campagna Gen4 forward attiva.",
            code="GEN4_COPYABILITY_FORWARD_CAMPAIGN_REQUIRED",
            status_code=409,
        )
    return row


def _active_copyability_campaigns(
    db: Session,
) -> list[CanonicalParserGen4CopyabilityCampaign]:
    return list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityCampaign)
            .where(CanonicalParserGen4CopyabilityCampaign.status == "ACTIVE")
            .order_by(
                CanonicalParserGen4CopyabilityCampaign.started_at.asc(),
                CanonicalParserGen4CopyabilityCampaign.id.asc(),
            )
        )
    )


def _campaign_by_id(
    db: Session,
    campaign_id: str,
    *,
    active_required: bool = False,
) -> CanonicalParserGen4CopyabilityCampaign:
    row = db.scalar(
        select(CanonicalParserGen4CopyabilityCampaign).where(
            CanonicalParserGen4CopyabilityCampaign.campaign_id == str(campaign_id).strip()
        )
    )
    if row is None:
        raise CanonicalParserGen4CopyabilityError(
            "Campagna Gen4 copyability non trovata.",
            code="GEN4_COPYABILITY_CAMPAIGN_NOT_FOUND",
            status_code=404,
        )
    if active_required and row.status != "ACTIVE":
        raise CanonicalParserGen4CopyabilityError(
            "La campagna Gen4 copyability non è attiva.",
            code="GEN4_COPYABILITY_CAMPAIGN_NOT_ACTIVE",
            status_code=409,
        )
    return row


def _primary_copyability_campaign(
    db: Session,
    *,
    required: bool = True,
) -> CanonicalParserGen4CopyabilityCampaign | None:
    row = db.scalar(
        select(CanonicalParserGen4CopyabilityCampaign)
        .where(
            CanonicalParserGen4CopyabilityCampaign.status == "ACTIVE",
            CanonicalParserGen4CopyabilityCampaign.campaign_role == CAMPAIGN_ROLE_PRIMARY,
        )
        .order_by(CanonicalParserGen4CopyabilityCampaign.id.asc())
        .limit(1)
    )
    if row is None and required:
        raise CanonicalParserGen4CopyabilityError(
            "Nessuna campagna Gen4 copyability primaria attiva.",
            code="GEN4_COPYABILITY_PRIMARY_CAMPAIGN_REQUIRED",
            status_code=409,
        )
    return row


def _normalize_candidate_wallets(wallets: Iterable[str]) -> list[str]:
    normalized = sorted({str(wallet or "").strip() for wallet in wallets if str(wallet or "").strip()})
    if not normalized or len(normalized) > 20:
        raise CanonicalParserGen4CopyabilityError(
            "Servono da 1 a 20 wallet candidati univoci.",
            code="GEN4_QUALIFIED_CANDIDATE_WALLET_COUNT_INVALID",
        )
    invalid = [wallet for wallet in normalized if SOLANA_ADDRESS_RE.fullmatch(wallet) is None]
    if invalid:
        raise CanonicalParserGen4CopyabilityError(
            "Uno o più wallet candidati non hanno un formato Solana valido.",
            code="GEN4_QUALIFIED_CANDIDATE_WALLET_INVALID",
        )
    return normalized


def _validate_selection_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = dict(snapshot or {})
    required_passes = (
        "activity_gate",
        "buy_sell_parsing",
        "quality_gate",
        "observed_profitability",
        "gen4_copyability",
    )
    missing = [name for name in required_passes if str(value.get(name) or "").upper() != "PASS"]
    if missing:
        raise CanonicalParserGen4CopyabilityError(
            "Selection snapshot incompleto: " + ", ".join(missing),
            code="GEN4_QUALIFIED_CANDIDATE_SELECTION_NOT_PROVEN",
            status_code=409,
        )
    value["validated_by"] = "M61_RIGID_QUALIFIED_CANDIDATE_GATE"
    value["historical_evidence_only"] = True
    value["forward_proof_starts_at_webhook_activation"] = True
    return value


def start_gen4_copyability_campaign(
    db: Session,
    *,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    anchor_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED", False)):
        raise CanonicalParserGen4CopyabilityError(
            "La validazione real-time copyability è disabilitata.",
            code="GEN4_COPYABILITY_DISABLED",
            status_code=409,
        )
    if confirmation.strip() != GEN4_COPYABILITY_START_CONFIRMATION:
        raise CanonicalParserGen4CopyabilityError(
            f"Conferma richiesta: {GEN4_COPYABILITY_START_CONFIRMATION}",
            code="GEN4_COPYABILITY_START_CONFIRMATION_REQUIRED",
        )

    forward = _active_forward_campaign(db)
    existing = db.scalar(
        select(CanonicalParserGen4CopyabilityCampaign).where(
            CanonicalParserGen4CopyabilityCampaign.forward_campaign_db_id == forward.id,
            CanonicalParserGen4CopyabilityCampaign.campaign_role == CAMPAIGN_ROLE_PRIMARY,
        )
    )
    if existing is not None:
        if existing.status != "ACTIVE":
            raise CanonicalParserGen4CopyabilityError(
                "Esiste già una campagna copyability non attiva per questa campagna forward.",
                code="GEN4_COPYABILITY_CAMPAIGN_ALREADY_EXISTS",
                status_code=409,
            )
        _refresh_campaign_metrics(db, existing, observed_at=_aware(anchor_at))
        return _serialize_campaign(db, existing)

    observed = max(_aware(anchor_at), _aware(forward.anchor_at))
    policy = _policy_snapshot()
    minimum_days = int(policy["minimum_observation_days"])
    frozen_wallets = list(forward.frozen_wallets or [])
    candidate_key = _canonical_hash(
        {
            "campaign_role": CAMPAIGN_ROLE_PRIMARY,
            "forward_campaign_id": forward.campaign_id,
            "frozen_wallets": sorted(str(item) for item in frozen_wallets),
        }
    )
    row = CanonicalParserGen4CopyabilityCampaign(
        campaign_id=str(uuid4()),
        forward_campaign_db_id=forward.id,
        status="ACTIVE",
        campaign_role=CAMPAIGN_ROLE_PRIMARY,
        candidate_key=candidate_key,
        verdict="COLLECTING",
        policy_version=GEN4_COPYABILITY_POLICY_VERSION,
        policy_hash=_canonical_hash(policy),
        policy_snapshot=policy,
        frozen_wallets=frozen_wallets,
        selection_snapshot={
            "source": "M52_M53_FORWARD_FROZEN_WALLETS",
            "forward_campaign_id": forward.campaign_id,
        },
        anchor_at=observed,
        minimum_complete_at=observed + timedelta(days=minimum_days),
        latest_observed_at=observed,
        started_at=observed,
        completed_at=None,
        minimum_observation_days=minimum_days,
        minimum_closed_trades=int(policy["minimum_closed_trades"]),
        proof_closed_trades=int(policy["proof_closed_trades"]),
        simulated_input_lamports=int(policy["simulated_input_lamports"]),
        slippage_bps=int(policy["slippage_bps"]),
        max_signal_age_ms=int(policy["max_signal_age_ms"]),
        max_quote_latency_ms=int(policy["max_quote_latency_ms"]),
        max_price_impact_bps=int(policy["max_price_impact_bps"]),
        max_price_deterioration_bps=int(policy["max_price_deterioration_bps"]),
        estimated_network_fee_lamports=int(policy["estimated_network_fee_lamports"]),
        minimum_webhook_coverage_percent=float(policy["minimum_webhook_coverage_percent"]),
        minimum_profit_factor=float(policy["minimum_profit_factor"]),
        maximum_drawdown_percent=float(policy["maximum_drawdown_percent"]),
        webhook_id=None,
        webhook_status="NOT_CONFIGURED",
        webhook_url=None,
        webhook_configured_at=None,
        last_webhook_at=None,
        metrics={},
        evidence_gaps=["WEBHOOK_NOT_CONFIGURED"],
        safety=_safety(campaign_role=CAMPAIGN_ROLE_PRIMARY),
        actor_label=(actor_label or "SYSTEM")[:80],
        note=_safe_message(note, 500) or None,
        technical_metadata={
            "forward_campaign_id": forward.campaign_id,
            "forward_anchor_at": _aware(forward.anchor_at).isoformat(),
        },
    )
    db.add(row)
    db.flush()
    _ensure_worker_state(db)
    _refresh_campaign_metrics(db, row, observed_at=observed)
    return _serialize_campaign(db, row)



def start_gen4_qualified_candidate_campaign(
    db: Session,
    *,
    confirmation: str,
    candidate_wallets: Iterable[str],
    selection_snapshot: dict[str, Any],
    actor_label: str | None = None,
    note: str | None = None,
    anchor_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED", False)):
        raise CanonicalParserGen4CopyabilityError(
            "La validazione real-time copyability è disabilitata.",
            code="GEN4_COPYABILITY_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION:
        raise CanonicalParserGen4CopyabilityError(
            f"Conferma richiesta: {GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION}",
            code="GEN4_QUALIFIED_CANDIDATE_CONFIRMATION_REQUIRED",
        )

    primary = _primary_copyability_campaign(db)
    assert primary is not None
    forward = db.get(
        CanonicalParserGen4ForwardCampaign,
        primary.forward_campaign_db_id,
    )
    if forward is None or forward.status != "ACTIVE":
        raise CanonicalParserGen4CopyabilityError(
            "La campagna forward collegata alla copyability primaria non è attiva.",
            code="GEN4_QUALIFIED_CANDIDATE_PRIMARY_FORWARD_REQUIRED",
            status_code=409,
        )
    wallets = _normalize_candidate_wallets(candidate_wallets)
    snapshot = _validate_selection_snapshot(selection_snapshot)

    policy = _policy_snapshot()
    active_campaigns = _active_copyability_campaigns(db)

    # POST retries are idempotent by candidate wallet set while the run is ACTIVE.
    # Once a candidate run is archived, a future explicit start creates a fresh
    # immutable run (new candidate_key/anchor) instead of resurrecting old proof.
    same_active = next(
        (
            campaign
            for campaign in active_campaigns
            if campaign.campaign_role == CAMPAIGN_ROLE_CANDIDATE
            and campaign.forward_campaign_db_id == forward.id
            and sorted(str(item) for item in (campaign.frozen_wallets or [])) == wallets
        ),
        None,
    )
    if same_active is not None:
        _refresh_campaign_metrics(db, same_active, observed_at=_aware(anchor_at))
        return _serialize_campaign(db, same_active) | {"idempotent_replay": True}

    occupied_wallets = {
        str(wallet)
        for campaign in active_campaigns
        for wallet in (campaign.frozen_wallets or [])
    }
    overlap = sorted(set(wallets) & occupied_wallets)
    if overlap:
        raise CanonicalParserGen4CopyabilityError(
            "I wallet candidati non possono duplicare wallet già monitorati da campagne attive.",
            code="GEN4_QUALIFIED_CANDIDATE_OVERLAPS_ACTIVE_CAMPAIGN",
            status_code=409,
        )

    historical_candidates = list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityCampaign).where(
                CanonicalParserGen4CopyabilityCampaign.forward_campaign_db_id == forward.id,
                CanonicalParserGen4CopyabilityCampaign.campaign_role == CAMPAIGN_ROLE_CANDIDATE,
            )
        )
    )
    run_sequence = sum(
        1
        for campaign in historical_candidates
        if sorted(str(item) for item in (campaign.frozen_wallets or [])) == wallets
    )
    selection_fingerprint = _canonical_hash(
        {
            "forward_campaign_id": forward.campaign_id,
            "frozen_wallets": wallets,
            "policy_hash": _canonical_hash(policy),
            "selection_snapshot": snapshot,
        }
    )
    candidate_key = _canonical_hash(
        {
            "campaign_role": CAMPAIGN_ROLE_CANDIDATE,
            "selection_fingerprint": selection_fingerprint,
            "run_sequence": run_sequence,
        }
    )

    observed = max(_aware(anchor_at), _aware(forward.anchor_at))
    minimum_days = int(policy["minimum_observation_days"])
    row = CanonicalParserGen4CopyabilityCampaign(
        campaign_id=str(uuid4()),
        forward_campaign_db_id=forward.id,
        status="ACTIVE",
        campaign_role=CAMPAIGN_ROLE_CANDIDATE,
        candidate_key=candidate_key,
        verdict="COLLECTING",
        policy_version=GEN4_COPYABILITY_POLICY_VERSION,
        policy_hash=_canonical_hash(policy),
        policy_snapshot=policy,
        frozen_wallets=wallets,
        selection_snapshot=snapshot,
        anchor_at=observed,
        minimum_complete_at=observed + timedelta(days=minimum_days),
        latest_observed_at=observed,
        started_at=observed,
        completed_at=None,
        minimum_observation_days=minimum_days,
        minimum_closed_trades=int(policy["minimum_closed_trades"]),
        proof_closed_trades=int(policy["proof_closed_trades"]),
        simulated_input_lamports=int(policy["simulated_input_lamports"]),
        slippage_bps=int(policy["slippage_bps"]),
        max_signal_age_ms=int(policy["max_signal_age_ms"]),
        max_quote_latency_ms=int(policy["max_quote_latency_ms"]),
        max_price_impact_bps=int(policy["max_price_impact_bps"]),
        max_price_deterioration_bps=int(policy["max_price_deterioration_bps"]),
        estimated_network_fee_lamports=int(policy["estimated_network_fee_lamports"]),
        minimum_webhook_coverage_percent=float(policy["minimum_webhook_coverage_percent"]),
        minimum_profit_factor=float(policy["minimum_profit_factor"]),
        maximum_drawdown_percent=float(policy["maximum_drawdown_percent"]),
        webhook_id=None,
        webhook_status="NOT_CONFIGURED",
        webhook_url=None,
        webhook_configured_at=None,
        last_webhook_at=None,
        metrics={},
        evidence_gaps=["WEBHOOK_NOT_CONFIGURED"],
        safety=_safety(campaign_role=CAMPAIGN_ROLE_CANDIDATE),
        actor_label=(actor_label or "M61_QUALIFIED_CANDIDATE")[:80],
        note=_safe_message(note, 500) or None,
        technical_metadata={
            "forward_campaign_id": forward.campaign_id,
            "forward_anchor_at": _aware(forward.anchor_at).isoformat(),
            "primary_copyability_campaign_id": primary.campaign_id,
            "parallel_isolation": True,
            "selection_fingerprint": selection_fingerprint,
            "candidate_run_sequence": run_sequence,
            "historical_selection_evidence_not_counted_as_forward_proof": True,
        },
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exception:
        raise CanonicalParserGen4CopyabilityError(
            "Conflitto durante la creazione della campagna candidata.",
            code="GEN4_QUALIFIED_CANDIDATE_PERSISTENCE_CONFLICT",
            status_code=409,
        ) from exception
    _ensure_worker_state(db)
    _refresh_campaign_metrics(db, row, observed_at=observed)
    return _serialize_campaign(db, row) | {"idempotent_replay": False}


def stop_gen4_copyability_campaign(
    db: Session,
    *,
    campaign_id: str,
    confirmation: str,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    if confirmation.strip() != GEN4_COPYABILITY_STOP_CONFIRMATION:
        raise CanonicalParserGen4CopyabilityError(
            f"Conferma richiesta: {GEN4_COPYABILITY_STOP_CONFIRMATION}",
            code="GEN4_COPYABILITY_STOP_CONFIRMATION_REQUIRED",
        )
    campaign = _campaign_by_id(db, campaign_id, active_required=True)
    observed = _aware(observed_at)
    _refresh_campaign_metrics(db, campaign, observed_at=observed)
    campaign.status = "COMPLETED"
    campaign.completed_at = observed
    db.flush()
    return _serialize_campaign(db, campaign)


def configure_gen4_copyability_webhook(
    db: Session,
    *,
    campaign_id: str,
    confirmation: str,
    webhook_id: str,
    webhook_url: str,
    active: bool,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    if confirmation.strip() != GEN4_COPYABILITY_WEBHOOK_CONFIRMATION:
        raise CanonicalParserGen4CopyabilityError(
            f"Conferma richiesta: {GEN4_COPYABILITY_WEBHOOK_CONFIRMATION}",
            code="GEN4_COPYABILITY_WEBHOOK_CONFIRMATION_REQUIRED",
        )
    campaign = _campaign_by_id(db, campaign_id, active_required=True)
    observed = _aware(observed_at)
    realtime_receipt_count = int(
        db.scalar(
            select(func.count(CanonicalParserGen4WebhookReceipt.id)).where(
                CanonicalParserGen4WebhookReceipt.campaign_db_id == campaign.id,
                CanonicalParserGen4WebhookReceipt.source == SOURCE_WEBHOOK,
            )
        )
        or 0
    )
    first_activation = (
        active
        and campaign.webhook_configured_at is None
        and realtime_receipt_count == 0
        and campaign.closed_trade_count == 0
    )
    campaign.webhook_id = _safe_message(webhook_id, 80)
    campaign.webhook_url = _safe_message(webhook_url, 500)
    campaign.webhook_status = "ACTIVE" if active else "INACTIVE"
    campaign.webhook_configured_at = observed
    if first_activation:
        # The real-time proof clock starts only when the Helius webhook is
        # confirmed active. Time spent deploying/configuring cannot count.
        campaign.anchor_at = observed
        campaign.started_at = observed
        campaign.minimum_complete_at = observed + timedelta(
            days=campaign.minimum_observation_days
        )
    campaign.latest_observed_at = max(_aware(campaign.latest_observed_at), observed)
    db.flush()
    _refresh_campaign_metrics(db, campaign, observed_at=observed)
    return _serialize_campaign(db, campaign)


def _extract_signature(payload: dict[str, Any]) -> str:
    direct = str(payload.get("signature") or "").strip()
    if direct:
        return direct[:128]
    transaction = payload.get("transaction")
    if isinstance(transaction, dict):
        signatures = transaction.get("signatures")
        if isinstance(signatures, list) and signatures:
            value = str(signatures[0] or "").strip()
            if value:
                return value[:128]
    return ""


def _account_keys(payload: dict[str, Any]) -> list[str]:
    transaction = payload.get("transaction")
    message = transaction.get("message") if isinstance(transaction, dict) else None
    raw_keys = message.get("accountKeys") if isinstance(message, dict) else None
    keys: list[str] = []
    for item in raw_keys or []:
        if isinstance(item, dict):
            value = item.get("pubkey")
        else:
            value = item
        text = str(value or "").strip()
        if text:
            keys.append(text)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    loaded = meta.get("loadedAddresses") if isinstance(meta, dict) else None
    if isinstance(loaded, dict):
        for group in ("writable", "readonly"):
            for item in loaded.get(group) or []:
                text = str(item or "").strip()
                if text:
                    keys.append(text)
    return keys


def _token_balance_owners(payload: dict[str, Any]) -> set[str]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    owners: set[str] = set()
    for group in ("preTokenBalances", "postTokenBalances"):
        for item in meta.get(group) or []:
            if isinstance(item, dict):
                owner = str(item.get("owner") or "").strip()
                if owner:
                    owners.add(owner)
    return owners


def _matched_wallets(payload: dict[str, Any], wallets: Iterable[str]) -> list[str]:
    present = set(_account_keys(payload)) | _token_balance_owners(payload)
    return [wallet for wallet in wallets if wallet in present]



def _compact_raw_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields required for deterministic copyability replay.

    Raw Helius transactions may include large instruction/log trees. The proof
    requires signatures, account ordering and pre/post balances, not those
    unrelated fields. The full canonical hash remains in ``event_hash`` while
    this replay-complete subset protects the 500 MB Railway volume.
    """
    transaction = payload.get("transaction")
    transaction = transaction if isinstance(transaction, dict) else {}
    message = transaction.get("message")
    message = message if isinstance(message, dict) else {}
    meta = payload.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    compact_meta = {
        "err": meta.get("err"),
        "fee": meta.get("fee"),
        "preBalances": list(meta.get("preBalances") or []),
        "postBalances": list(meta.get("postBalances") or []),
        "preTokenBalances": list(meta.get("preTokenBalances") or []),
        "postTokenBalances": list(meta.get("postTokenBalances") or []),
    }
    loaded = meta.get("loadedAddresses")
    if isinstance(loaded, dict):
        compact_meta["loadedAddresses"] = {
            "writable": list(loaded.get("writable") or []),
            "readonly": list(loaded.get("readonly") or []),
        }
    return {
        "signature": _extract_signature(payload),
        "slot": payload.get("slot"),
        "blockTime": payload.get("blockTime"),
        "transaction": {
            "signatures": list(transaction.get("signatures") or []),
            "message": {
                "accountKeys": list(message.get("accountKeys") or []),
            },
        },
        "meta": compact_meta,
        "_storage": {
            "schema": "GEN4_COPYABILITY_RAW_REPLAY_SUBSET_V1",
            "full_event_hash_preserved": True,
        },
    }

def receive_gen4_copyability_webhook(
    db: Session,
    *,
    payload: Any,
    received_at: datetime | None = None,
) -> dict[str, Any]:
    campaigns = _active_copyability_campaigns(db)
    if not campaigns:
        return {
            "accepted": 0,
            "duplicates": 0,
            "ignored": 0,
            "campaigns_touched": [],
            "reason": "NO_ACTIVE_CAMPAIGN",
        }
    observed = _aware(received_at)
    events = payload if isinstance(payload, list) else [payload]
    accepted = 0
    duplicates = 0
    ignored = 0
    touched: set[str] = set()

    for item in events:
        if not isinstance(item, dict):
            ignored += 1
            continue
        signature = _extract_signature(item)
        if not signature:
            ignored += 1
            continue
        event_matched = False
        event_hash = _canonical_hash(item)
        compact_payload = _compact_raw_payload(item)
        block_time = _timestamp(item.get("blockTime"))
        slot_value = item.get("slot")
        try:
            slot = int(slot_value) if slot_value is not None else None
        except (TypeError, ValueError):
            slot = None

        for campaign in campaigns:
            wallets = [
                str(value).strip()
                for value in (campaign.frozen_wallets or [])
                if str(value).strip()
            ]
            matched = _matched_wallets(item, wallets)
            if not matched:
                continue
            event_matched = True
            touched.add(campaign.campaign_id)
            existing = db.scalar(
                select(CanonicalParserGen4WebhookReceipt).where(
                    CanonicalParserGen4WebhookReceipt.campaign_db_id == campaign.id,
                    CanonicalParserGen4WebhookReceipt.signature == signature,
                )
            )
            if existing is not None:
                existing.delivery_count += 1
                existing.last_received_at = observed
                if existing.source == SOURCE_WEBHOOK:
                    existing.raw_payload = compact_payload
                    existing.event_hash = event_hash
                else:
                    summary = dict(existing.parsed_summary or {})
                    summary["late_webhook_received_at"] = observed.isoformat()
                    summary["late_webhook_event_hash"] = event_hash
                    existing.parsed_summary = summary
                campaign.duplicate_receipt_count = max(
                    0, int(campaign.duplicate_receipt_count or 0)
                ) + 1
                duplicates += 1
                continue

            row = CanonicalParserGen4WebhookReceipt(
                receipt_id=str(uuid4()),
                campaign_db_id=campaign.id,
                signature=signature,
                event_hash=event_hash,
                source=SOURCE_WEBHOOK,
                status=RECEIPT_RECEIVED,
                auth_verified=True,
                wallet_address=matched[0],
                matched_wallets=matched,
                slot=slot,
                block_time=block_time,
                received_at=observed,
                first_received_at=observed,
                last_received_at=observed,
                delivery_count=1,
                processing_attempts=0,
                raw_payload=compact_payload,
                parsed_summary={
                    "payload_storage": "REPLAY_SUBSET_V1",
                    "campaign_role": campaign.campaign_role,
                },
            )
            try:
                with db.begin_nested():
                    db.add(row)
                    db.flush()
                campaign.receipt_count = max(0, int(campaign.receipt_count or 0)) + 1
                accepted += 1
            except IntegrityError:
                raced = db.scalar(
                    select(CanonicalParserGen4WebhookReceipt).where(
                        CanonicalParserGen4WebhookReceipt.campaign_db_id == campaign.id,
                        CanonicalParserGen4WebhookReceipt.signature == signature,
                    )
                )
                if raced is not None:
                    raced.delivery_count += 1
                    raced.last_received_at = observed
                campaign.duplicate_receipt_count = max(
                    0, int(campaign.duplicate_receipt_count or 0)
                ) + 1
                duplicates += 1

        if not event_matched:
            ignored += 1

    for campaign in campaigns:
        if campaign.campaign_id not in touched:
            continue
        campaign.last_webhook_at = observed
        campaign.latest_observed_at = max(_aware(campaign.latest_observed_at), observed)
    db.flush()
    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "ignored": ignored,
        "campaigns_touched": sorted(touched),
        "active_campaign_count": len(campaigns),
    }


def record_gen4_copyability_recovery_events(
    db: Session,
    *,
    wallet_address: str,
    transactions: list[dict[str, Any]],
    observed_at: datetime | None = None,
) -> dict[str, int]:
    campaigns = [
        campaign
        for campaign in _active_copyability_campaigns(db)
        if wallet_address in (campaign.frozen_wallets or [])
    ]
    if not campaigns:
        return {"created": 0, "existing": 0, "ignored": len(transactions)}
    observed = _aware(observed_at)
    created = 0
    existing_count = 0
    ignored = 0
    for campaign in campaigns:
        for item in transactions:
            if not isinstance(item, dict):
                ignored += 1
                continue
            signature = str(item.get("signature") or "").strip()[:128]
            if not signature:
                ignored += 1
                continue
            existing = db.scalar(
                select(CanonicalParserGen4WebhookReceipt).where(
                    CanonicalParserGen4WebhookReceipt.campaign_db_id == campaign.id,
                    CanonicalParserGen4WebhookReceipt.signature == signature,
                )
            )
            if existing is not None:
                summary = dict(existing.parsed_summary or {})
                summary["seen_by_recovery"] = True
                summary["recovery_seen_at"] = observed.isoformat()
                summary["recovery_transaction_type"] = item.get("type")
                existing.parsed_summary = summary
                existing_count += 1
                continue
            occurred = _timestamp(item.get("timestamp")) or observed
            row = CanonicalParserGen4WebhookReceipt(
                receipt_id=str(uuid4()),
                campaign_db_id=campaign.id,
                signature=signature,
                event_hash=_canonical_hash({"source": SOURCE_RECOVERY, "transaction": item}),
                source=SOURCE_RECOVERY,
                status=RECEIPT_EXCLUDED_RECOVERY,
                auth_verified=False,
                wallet_address=wallet_address,
                matched_wallets=[wallet_address],
                slot=None,
                block_time=occurred,
                received_at=observed,
                first_received_at=observed,
                last_received_at=observed,
                processed_at=observed,
                delivery_count=1,
                processing_attempts=0,
                raw_payload={},
                parsed_summary={
                    "transaction_type": item.get("type"),
                    "timestamp": item.get("timestamp"),
                    "excluded_reason": "RECOVERED_BY_120_SECOND_POLLING",
                },
            )
            db.add(row)
            db.flush()
            created += 1
    for campaign in campaigns:
        _refresh_campaign_metrics(db, campaign, observed_at=observed)
    return {"created": created, "existing": existing_count, "ignored": ignored}


def _raw_amount(item: dict[str, Any]) -> tuple[int, int]:
    amount_info = item.get("uiTokenAmount") if isinstance(item.get("uiTokenAmount"), dict) else {}
    raw = amount_info.get("amount")
    decimals = amount_info.get("decimals", 0)
    try:
        return int(raw or 0), max(0, int(decimals or 0))
    except (TypeError, ValueError):
        return 0, 0


def _wallet_token_deltas(payload: dict[str, Any], wallet: str) -> dict[str, dict[str, int]]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    aggregate: dict[str, dict[str, int]] = {}
    for phase, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for item in meta.get(phase) or []:
            if not isinstance(item, dict) or str(item.get("owner") or "").strip() != wallet:
                continue
            mint = str(item.get("mint") or "").strip()
            if not mint:
                continue
            raw, decimals = _raw_amount(item)
            state = aggregate.setdefault(mint, {"delta": 0, "pre": 0, "post": 0, "decimals": decimals})
            state["decimals"] = decimals
            if phase == "preTokenBalances":
                state["pre"] += raw
            else:
                state["post"] += raw
            state["delta"] += sign * raw
    return aggregate


def _native_delta(payload: dict[str, Any], wallet: str) -> tuple[int | None, int]:
    keys = _account_keys(payload)
    try:
        index = keys.index(wallet)
    except ValueError:
        return None, 0
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if index >= len(pre) or index >= len(post):
        return None, int(meta.get("fee") or 0)
    try:
        return int(post[index]) - int(pre[index]), int(meta.get("fee") or 0)
    except (TypeError, ValueError):
        return None, int(meta.get("fee") or 0)


def _sol_equivalent_delta(
    payload: dict[str, Any],
    wallet: str,
) -> tuple[int | None, int, int, int]:
    """Return SOL-equivalent wallet delta, native delta, WSOL delta and fee.

    Wallets may pay with native SOL or with an existing WSOL token account.
    Looking only at the system-account lamport balance would reject valid
    WSOL-routed swaps and distort the wallet's effective entry price. WSOL has
    nine decimals, so its raw token delta is already denominated in lamports.
    """
    native_delta, fee = _native_delta(payload, wallet)
    if native_delta is None:
        return None, 0, 0, fee
    wsol_state = _wallet_token_deltas(payload, wallet).get(SOL_MINT) or {}
    try:
        wsol_decimals = int(wsol_state.get("decimals") or 9)
        wsol_raw_delta = int(wsol_state.get("delta") or 0)
    except (TypeError, ValueError):
        wsol_decimals = 9
        wsol_raw_delta = 0
    if wsol_decimals == 9:
        wsol_delta_lamports = wsol_raw_delta
    elif 0 <= wsol_decimals < 9:
        wsol_delta_lamports = wsol_raw_delta * (10 ** (9 - wsol_decimals))
    else:
        wsol_delta_lamports = 0
    return (
        int(native_delta) + int(wsol_delta_lamports),
        int(native_delta),
        int(wsol_delta_lamports),
        int(fee),
    )


def parse_raw_copyability_signal(
    payload: dict[str, Any],
    *,
    frozen_wallets: Iterable[str],
) -> ParsedRawSignal:
    signature = _extract_signature(payload)
    if not signature:
        raise CanonicalParserGen4CopyabilityError(
            "Firma raw webhook assente.",
            code="GEN4_COPYABILITY_RAW_SIGNATURE_MISSING",
        )
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if meta.get("err") is not None:
        raise CanonicalParserGen4CopyabilityError(
            "Transazione raw fallita on-chain.",
            code="GEN4_COPYABILITY_RAW_TRANSACTION_FAILED",
        )
    matched = _matched_wallets(payload, frozen_wallets)
    if not matched:
        raise CanonicalParserGen4CopyabilityError(
            "Nessun wallet congelato presente nella transazione.",
            code="GEN4_COPYABILITY_RAW_WALLET_NOT_MATCHED",
        )

    candidates: list[tuple[str, str, dict[str, int]]] = []
    for wallet in matched:
        for mint, values in _wallet_token_deltas(payload, wallet).items():
            if mint in GEN4_MANDATORY_EXCLUDED_PRICE_MINTS:
                continue
            delta = int(values.get("delta") or 0)
            if delta:
                candidates.append((wallet, mint, values))
    if len(candidates) != 1:
        raise CanonicalParserGen4CopyabilityError(
            "La transazione raw non contiene un solo delta token speculativo non ambiguo.",
            code="GEN4_COPYABILITY_RAW_AMBIGUOUS_TOKEN_DELTAS",
        )

    wallet, mint, values = candidates[0]
    delta = int(values["delta"])
    side = "BUY" if delta > 0 else "SELL"
    sol_equivalent_delta, native_delta, wsol_delta, fee = _sol_equivalent_delta(
        payload,
        wallet,
    )
    if sol_equivalent_delta is None:
        raise CanonicalParserGen4CopyabilityError(
            "Delta SOL/WSOL del wallet non disponibile.",
            code="GEN4_COPYABILITY_RAW_SOL_EQUIVALENT_DELTA_UNAVAILABLE",
        )
    # This campaign deliberately proves only SOL-paired memecoin swaps. Token
    # transfers and stablecoin-routed swaps cannot be compared with a SOL quote.
    if side == "BUY" and sol_equivalent_delta >= -max(1, fee):
        raise CanonicalParserGen4CopyabilityError(
            "Il BUY non mostra una spesa SOL/WSOL verificabile.",
            code="GEN4_COPYABILITY_RAW_NOT_SOL_PAIRED_BUY",
        )
    if side == "SELL" and sol_equivalent_delta <= 0:
        raise CanonicalParserGen4CopyabilityError(
            "Il SELL non mostra un incasso SOL/WSOL verificabile.",
            code="GEN4_COPYABILITY_RAW_NOT_SOL_PAIRED_SELL",
        )

    effective_price: float | None = None
    if side == "BUY" and sol_equivalent_delta < 0 and delta > 0:
        spent = max(0, abs(sol_equivalent_delta) - max(0, fee))
        token_units = delta / (10 ** int(values["decimals"]))
        if spent > 0 and token_units > 0:
            effective_price = (spent / LAMPORTS_PER_SOL) / token_units
    sell_fraction: float | None = None
    if side == "SELL":
        pre_raw = max(0, int(values.get("pre") or 0))
        if pre_raw > 0:
            sell_fraction = min(1.0, abs(delta) / pre_raw)

    block_time = _timestamp(payload.get("blockTime"))
    slot_value = payload.get("slot")
    try:
        slot = int(slot_value) if slot_value is not None else None
    except (TypeError, ValueError):
        slot = None
    return ParsedRawSignal(
        signature=signature,
        slot=slot,
        block_time=block_time,
        wallet_address=wallet,
        side=side,
        token_mint=mint,
        token_decimals=int(values["decimals"]),
        token_delta_raw=delta,
        token_pre_raw=int(values.get("pre") or 0),
        sol_equivalent_delta_lamports=sol_equivalent_delta,
        wallet_effective_price_sol=effective_price,
        sell_fraction=sell_fraction,
        evidence={
            "matched_wallets": matched,
            "fee_lamports": fee,
            "native_delta_lamports": native_delta,
            "wsol_delta_lamports": wsol_delta,
            "sol_equivalent_delta_lamports": sol_equivalent_delta,
            "raw_token_pre": int(values.get("pre") or 0),
            "raw_token_post": int(values.get("post") or 0),
            "raw_token_delta": delta,
            "wallet_price_quality": (
                "ESTIMATED_FROM_RAW_NATIVE_BALANCE_DELTA" if effective_price is not None else "UNAVAILABLE"
            ),
        },
    )


def _quote(
    *,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    slippage_bps: int,
    client: JupiterSwapClient,
    now_fn: Any = _utc_now,
) -> QuoteSnapshot:
    requested = _aware(now_fn())
    taker = str(getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_QUOTE_TAKER", "") or "").strip() or None
    quote_and_build = getattr(client, "get_quote_and_unsigned_build", None)
    if callable(quote_and_build):
        if not taker:
            raise JupiterSwapError(
                "CANONICAL_PARSER_GEN4_COPYABILITY_QUOTE_TAKER mancante.",
                code="GEN4_COPYABILITY_QUOTE_TAKER_MISSING",
                status_code=503,
            )
        result = quote_and_build(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_raw=int(amount_raw),
            taker=taker,
            slippage_bps=int(slippage_bps),
            mode="fast",
        )
    else:
        # Dependency-injected test doubles retain the narrow get_order contract.
        result = client.get_order(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_raw=int(amount_raw),
            taker=taker,
            slippage_bps=int(slippage_bps),
        )
    received = _aware(now_fn())
    latency = max(0, int((received - requested).total_seconds() * 1000))
    sanitized = sanitize_jupiter_payload(result.raw)
    sanitized.update(
        {
            "request_id": result.request_id,
            "in_amount": result.in_amount,
            "out_amount": result.out_amount,
            "slippage_bps": result.slippage_bps,
            "router": result.router,
            "price_impact_percent": result.price_impact_percent,
            "transaction_built": bool(result.transaction),
        }
    )
    return QuoteSnapshot(
        requested_at=requested,
        received_at=received,
        latency_ms=latency,
        result=result,
        sanitized=sanitized,
    )


def _conservative_out_amount(result: JupiterOrderResult, slippage_bps: int) -> int:
    raw_threshold = (result.raw or {}).get("otherAmountThreshold")
    try:
        threshold = int(raw_threshold) if raw_threshold not in (None, "") else 0
    except (TypeError, ValueError):
        threshold = 0
    if threshold > 0:
        return min(int(result.out_amount), threshold)
    haircut = max(0, min(int(slippage_bps), 10_000))
    return max(0, int(result.out_amount) * (10_000 - haircut) // 10_000)


def _entry_deterioration_bps(
    signal: ParsedRawSignal,
    quote: JupiterOrderResult,
    *,
    slippage_bps: int,
) -> float | None:
    conservative_out = _conservative_out_amount(quote, slippage_bps)
    if signal.wallet_effective_price_sol is None or conservative_out <= 0:
        return None
    token_units = conservative_out / (10 ** signal.token_decimals)
    if token_units <= 0:
        return None
    bot_price = (quote.in_amount / LAMPORTS_PER_SOL) / token_units
    return ((bot_price / signal.wallet_effective_price_sol) - 1.0) * 10_000.0


def _chain_age_ms(signal: ParsedRawSignal, received_at: datetime) -> int | None:
    if signal.block_time is None:
        return None
    return max(0, int((_aware(received_at) - _aware(signal.block_time)).total_seconds() * 1000))


def _entry_rejection(
    campaign: CanonicalParserGen4CopyabilityCampaign,
    *,
    signal: ParsedRawSignal,
    chain_age_ms: int | None,
    quote: QuoteSnapshot,
    deterioration_bps: float | None,
) -> str | None:
    if signal.side != "BUY":
        return "NOT_A_BUY_SIGNAL"
    if chain_age_ms is None:
        return "BLOCK_TIME_UNAVAILABLE"
    if chain_age_ms > campaign.max_signal_age_ms:
        return "SIGNAL_TOO_OLD"
    if quote.latency_ms > campaign.max_quote_latency_ms:
        return "QUOTE_TOO_SLOW"
    if quote.result.out_amount <= 0:
        return "NO_EXECUTABLE_OUTPUT"
    impact_bps = max(0.0, quote.result.price_impact_percent * 100.0)
    if impact_bps > campaign.max_price_impact_bps:
        return "PRICE_IMPACT_TOO_HIGH"
    if deterioration_bps is not None and deterioration_bps > campaign.max_price_deterioration_bps:
        return "PRICE_ALREADY_MOVED"
    if not quote.result.transaction:
        return "UNSIGNED_TRANSACTION_NOT_BUILT"
    return None


def _process_buy(
    db: Session,
    *,
    campaign: CanonicalParserGen4CopyabilityCampaign,
    receipt: CanonicalParserGen4WebhookReceipt,
    signal: ParsedRawSignal,
    client: JupiterSwapClient,
    now_fn: Any,
) -> ProcessSummary:
    chain_age = _chain_age_ms(signal, receipt.received_at)
    try:
        quote = _quote(
            input_mint=SOL_MINT,
            output_mint=signal.token_mint,
            amount_raw=campaign.simulated_input_lamports,
            slippage_bps=campaign.slippage_bps,
            client=client,
            now_fn=now_fn,
        )
        conservative_out = _conservative_out_amount(quote.result, campaign.slippage_bps)
        deterioration = _entry_deterioration_bps(
            signal, quote.result, slippage_bps=campaign.slippage_bps
        )
        reason = _entry_rejection(
            campaign,
            signal=signal,
            chain_age_ms=chain_age,
            quote=quote,
            deterioration_bps=deterioration,
        )
        quote.sanitized["expected_out_amount"] = int(quote.result.out_amount)
        quote.sanitized["conservative_out_amount"] = conservative_out
        quote.sanitized["slippage_haircut_applied"] = True
        status = POSITION_REJECTED if reason else POSITION_OPEN
        position = CanonicalParserGen4CopyabilityPosition(
            position_id=str(uuid4()),
            campaign_db_id=campaign.id,
            entry_receipt_db_id=receipt.id,
            status=status,
            wallet_address=signal.wallet_address,
            token_mint=signal.token_mint,
            token_decimals=signal.token_decimals,
            entry_signature=signal.signature,
            entry_source=receipt.source,
            entry_signal_at=_aware(signal.block_time, fallback=receipt.received_at),
            entry_received_at=_aware(receipt.received_at),
            entry_quote_requested_at=quote.requested_at,
            entry_quote_received_at=quote.received_at,
            opened_at=(quote.received_at if reason is None else None),
            closed_at=(quote.received_at if reason is not None else None),
            chain_age_ms=chain_age,
            entry_quote_latency_ms=quote.latency_ms,
            entry_end_to_quote_ms=(
                max(0, int((quote.received_at - _aware(signal.block_time)).total_seconds() * 1000))
                if signal.block_time is not None
                else None
            ),
            entry_price_deterioration_bps=deterioration,
            entry_price_impact_bps=max(0.0, quote.result.price_impact_percent * 100.0),
            entry_transaction_built=bool(quote.result.transaction),
            entry_copyable=reason is None,
            entry_rejection_reason=reason,
            wallet_token_delta_raw=signal.token_delta_raw,
            wallet_sol_equivalent_delta_lamports=(
                signal.sol_equivalent_delta_lamports
            ),
            wallet_effective_price_sol=signal.wallet_effective_price_sol,
            entry_input_lamports=quote.result.in_amount,
            entry_output_token_raw=conservative_out,
            remaining_token_raw=(conservative_out if reason is None else 0),
            realized_output_lamports=0,
            allocated_entry_fee_lamports=campaign.estimated_network_fee_lamports,
            allocated_exit_fee_lamports=0,
            pnl_lamports=(
                -(quote.result.in_amount + campaign.estimated_network_fee_lamports)
                if reason is not None
                else None
            ),
            return_percent=None,
            close_reason=("ENTRY_REJECTED" if reason else None),
            exit_source=None,
            entry_quote=quote.sanitized,
            exit_quotes=[],
            evidence={"signal": signal.evidence, "safety": _safety()},
        )
        db.add(position)
        receipt.parsed_summary = {
            "side": signal.side,
            "wallet_address": signal.wallet_address,
            "token_mint": signal.token_mint,
            "chain_age_ms": chain_age,
            "quote_attempted": True,
            "quote_built": bool(quote.result.transaction),
            "quote_latency_ms": quote.latency_ms,
            "entry_copyable": reason is None,
            "entry_rejection_reason": reason,
            "position_id": position.position_id,
        }
        receipt.status = RECEIPT_PROCESSED
        receipt.processed_at = quote.received_at
        db.flush()
        return ProcessSummary(
            receipts_processed=1,
            quotes_requested=1,
            entries_opened=1 if reason is None else 0,
            entries_rejected=1 if reason is not None else 0,
        )
    except JupiterSwapError as error:
        receipt.status = RECEIPT_FAILED
        receipt.error_code = error.code
        receipt.error_message = _safe_message(error)
        receipt.processed_at = _aware(now_fn())
        summary = dict(receipt.parsed_summary or {})
        summary.update({
            "side": "BUY",
            "wallet_address": signal.wallet_address,
            "token_mint": signal.token_mint,
            "quote_attempted": True,
            "quote_built": False,
            "processing_error": error.code,
        })
        receipt.parsed_summary = summary
        return ProcessSummary(receipts_processed=1, quotes_requested=1, failures=1)


def _allocate_integer(total: int, weights: list[int]) -> list[int]:
    if total <= 0 or not weights or sum(weights) <= 0:
        return [0 for _ in weights]
    denominator = sum(weights)
    allocations = [(total * weight) // denominator for weight in weights]
    remainder = total - sum(allocations)
    for index in range(remainder):
        allocations[index % len(allocations)] += 1
    return allocations


def _process_sell(
    db: Session,
    *,
    campaign: CanonicalParserGen4CopyabilityCampaign,
    receipt: CanonicalParserGen4WebhookReceipt,
    signal: ParsedRawSignal,
    client: JupiterSwapClient,
    now_fn: Any,
) -> ProcessSummary:
    positions = list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityPosition)
            .where(
                CanonicalParserGen4CopyabilityPosition.campaign_db_id == campaign.id,
                CanonicalParserGen4CopyabilityPosition.wallet_address == signal.wallet_address,
                CanonicalParserGen4CopyabilityPosition.token_mint == signal.token_mint,
                CanonicalParserGen4CopyabilityPosition.status.in_([POSITION_OPEN, POSITION_OPEN_PARTIAL]),
                CanonicalParserGen4CopyabilityPosition.remaining_token_raw > 0,
            )
            .order_by(CanonicalParserGen4CopyabilityPosition.opened_at, CanonicalParserGen4CopyabilityPosition.id)
        )
    )
    if not positions:
        receipt.status = RECEIPT_IGNORED
        receipt.processed_at = _aware(now_fn())
        receipt.parsed_summary = {
            "side": "SELL",
            "wallet_address": signal.wallet_address,
            "token_mint": signal.token_mint,
            "ignored_reason": "NO_OPEN_COPYABILITY_POSITION",
        }
        return ProcessSummary(receipts_processed=1, receipts_ignored=1)

    fraction = signal.sell_fraction
    if fraction is None or fraction <= 0:
        receipt.status = RECEIPT_IGNORED
        receipt.processed_at = _aware(now_fn())
        receipt.parsed_summary = {
            "side": "SELL",
            "ignored_reason": "SELL_FRACTION_UNAVAILABLE",
        }
        return ProcessSummary(receipts_processed=1, receipts_ignored=1)
    remaining_weights = [int(position.remaining_token_raw) for position in positions]
    total_remaining = sum(remaining_weights)
    amount_to_sell = min(total_remaining, max(1, int(total_remaining * fraction)))

    try:
        quote = _quote(
            input_mint=signal.token_mint,
            output_mint=SOL_MINT,
            amount_raw=amount_to_sell,
            slippage_bps=campaign.slippage_bps,
            client=client,
            now_fn=now_fn,
        )
    except JupiterSwapError as error:
        receipt.status = RECEIPT_FAILED
        receipt.error_code = error.code
        receipt.error_message = _safe_message(error)
        receipt.processed_at = _aware(now_fn())
        summary = dict(receipt.parsed_summary or {})
        summary.update({
            "side": "SELL",
            "wallet_address": signal.wallet_address,
            "token_mint": signal.token_mint,
            "quote_attempted": True,
            "quote_built": False,
            "processing_error": error.code,
        })
        receipt.parsed_summary = summary
        return ProcessSummary(receipts_processed=1, quotes_requested=1, failures=1)

    conservative_out = _conservative_out_amount(quote.result, campaign.slippage_bps)
    quote.sanitized["expected_out_amount"] = int(quote.result.out_amount)
    quote.sanitized["conservative_out_amount"] = conservative_out
    quote.sanitized["slippage_haircut_applied"] = True
    impact_bps = max(0.0, quote.result.price_impact_percent * 100.0)
    chain_age = _chain_age_ms(signal, receipt.received_at)
    rejection: str | None = None
    if chain_age is None:
        rejection = "BLOCK_TIME_UNAVAILABLE"
    elif chain_age > campaign.max_signal_age_ms:
        rejection = "EXIT_SIGNAL_TOO_OLD"
    elif quote.latency_ms > campaign.max_quote_latency_ms:
        rejection = "EXIT_QUOTE_TOO_SLOW"
    elif impact_bps > campaign.max_price_impact_bps:
        rejection = "EXIT_PRICE_IMPACT_TOO_HIGH"
    elif not quote.result.transaction:
        rejection = "EXIT_UNSIGNED_TRANSACTION_NOT_BUILT"

    if rejection:
        receipt.status = RECEIPT_PROCESSED
        receipt.processed_at = quote.received_at
        receipt.parsed_summary = {
            "side": "SELL",
            "wallet_address": signal.wallet_address,
            "token_mint": signal.token_mint,
            "quote_attempted": True,
            "quote_built": bool(quote.result.transaction),
            "exit_copyable": False,
            "exit_rejection_reason": rejection,
            "quote_latency_ms": quote.latency_ms,
            "chain_age_ms": chain_age,
        }
        for position in positions:
            evidence = dict(position.evidence or {})
            rejected = list(evidence.get("rejected_exits") or [])
            rejected.append(
                {
                    "signature": signal.signature,
                    "reason": rejection,
                    "received_at": quote.received_at.isoformat(),
                    "quote": quote.sanitized,
                }
            )
            evidence["rejected_exits"] = rejected[-20:]
            position.evidence = evidence
        return ProcessSummary(receipts_processed=1, quotes_requested=1, exits_applied=0)

    sold_allocations = _allocate_integer(amount_to_sell, remaining_weights)
    out_allocations = _allocate_integer(conservative_out, sold_allocations)
    fee_allocations = _allocate_integer(campaign.estimated_network_fee_lamports, sold_allocations)
    closed = 0
    for position, sold_raw, out_lamports, fee_lamports in zip(
        positions, sold_allocations, out_allocations, fee_allocations
    ):
        if sold_raw <= 0:
            continue
        position.remaining_token_raw = max(0, int(position.remaining_token_raw) - sold_raw)
        position.realized_output_lamports += out_lamports
        position.allocated_exit_fee_lamports += fee_lamports
        position.exit_source = receipt.source
        position.last_exit_signature = signal.signature
        position.exit_quote_latency_ms = quote.latency_ms
        position.exit_price_impact_bps = impact_bps
        position.exit_transaction_built = bool(quote.result.transaction)
        position.exit_copyable = True
        quotes = list(position.exit_quotes or [])
        quotes.append(
            {
                "signature": signal.signature,
                "sell_fraction": fraction,
                "sold_token_raw": sold_raw,
                "out_lamports": out_lamports,
                "allocated_fee_lamports": fee_lamports,
                "quote": quote.sanitized,
                "quote_requested_at": quote.requested_at.isoformat(),
                "quote_received_at": quote.received_at.isoformat(),
            }
        )
        position.exit_quotes = quotes[-100:]
        dust_limit = max(1, int(position.entry_output_token_raw * 0.001))
        if position.remaining_token_raw <= dust_limit or fraction >= 0.999:
            position.remaining_token_raw = 0
            position.status = POSITION_CLOSED
            position.closed_at = quote.received_at
            position.close_reason = "MIRRORED_WALLET_EXIT"
            cost = position.entry_input_lamports + position.allocated_entry_fee_lamports
            proceeds = position.realized_output_lamports - position.allocated_exit_fee_lamports
            position.pnl_lamports = proceeds - cost
            position.return_percent = (position.pnl_lamports / cost * 100.0) if cost > 0 else None
            closed += 1
        else:
            position.status = POSITION_OPEN_PARTIAL

    receipt.status = RECEIPT_PROCESSED
    receipt.processed_at = quote.received_at
    receipt.parsed_summary = {
        "side": "SELL",
        "wallet_address": signal.wallet_address,
        "token_mint": signal.token_mint,
        "sell_fraction": fraction,
        "positions_affected": sum(1 for item in sold_allocations if item > 0),
        "positions_closed": closed,
        "quote_attempted": True,
        "quote_built": bool(quote.result.transaction),
        "quote_latency_ms": quote.latency_ms,
        "chain_age_ms": chain_age,
        "exit_copyable": True,
    }
    db.flush()
    return ProcessSummary(
        receipts_processed=1,
        quotes_requested=1,
        exits_applied=1,
        positions_closed=closed,
    )


def _ensure_worker_state(
    db: Session,
    *,
    lock: bool = False,
) -> CanonicalParserGen4CopyabilityWorkerState:
    statement = select(CanonicalParserGen4CopyabilityWorkerState).where(
        CanonicalParserGen4CopyabilityWorkerState.state_id == "GEN4_COPYABILITY_GLOBAL"
    )
    if lock:
        statement = statement.with_for_update()
    row = db.scalar(statement.limit(1))
    if row is None:
        row = CanonicalParserGen4CopyabilityWorkerState(
            state_id="GEN4_COPYABILITY_GLOBAL",
            enabled=True,
            poll_interval_seconds=max(
                1,
                min(
                    int(getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_INTERVAL_SECONDS", 1)),
                    60,
                ),
            ),
            batch_size=max(
                1,
                min(
                    int(getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_BATCH_SIZE", 20)),
                    100,
                ),
            ),
            technical_metadata={"policy_version": GEN4_COPYABILITY_POLICY_VERSION},
        )
        db.add(row)
        db.flush()
    return row


def process_gen4_copyability_queue(
    db: Session,
    *,
    confirmation: str,
    owner_id: str,
    batch_size: int | None = None,
    observed_at: datetime | None = None,
    jupiter_client: JupiterSwapClient | None = None,
    now_fn: Any = _utc_now,
) -> dict[str, Any]:
    if confirmation.strip() != GEN4_COPYABILITY_PROCESS_CONFIRMATION:
        raise CanonicalParserGen4CopyabilityError(
            f"Conferma richiesta: {GEN4_COPYABILITY_PROCESS_CONFIRMATION}",
            code="GEN4_COPYABILITY_PROCESS_CONFIRMATION_REQUIRED",
        )
    if not bool(getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED", False)):
        raise CanonicalParserGen4CopyabilityError(
            "La validazione real-time copyability è disabilitata.",
            code="GEN4_COPYABILITY_DISABLED",
            status_code=409,
        )
    campaigns = _active_copyability_campaigns(db)
    if not campaigns:
        raise CanonicalParserGen4CopyabilityError(
            "Nessuna campagna Gen4 copyability attiva.",
            code="GEN4_COPYABILITY_CAMPAIGN_REQUIRED",
            status_code=409,
        )
    campaigns_by_id = {campaign.id: campaign for campaign in campaigns}
    state = _ensure_worker_state(db, lock=True)
    observed = _aware(observed_at)
    lease_expires = _aware(state.lease_expires_at) if state.lease_expires_at else None
    if state.lease_owner and lease_expires and lease_expires > observed and state.lease_owner != owner_id:
        return {
            "status": "SKIPPED_LOCKED",
            "owner_id": state.lease_owner,
            "lease_expires_at": lease_expires.isoformat(),
            "summary": ProcessSummary().__dict__,
            "campaign_ids": [campaign.campaign_id for campaign in campaigns],
        }
    state.lease_owner = owner_id[:120]
    state.lease_expires_at = observed + timedelta(
        seconds=max(
            10,
            int(
                getattr(
                    settings,
                    "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_LEASE_SECONDS",
                    30,
                )
            ),
        )
    )
    state.last_iteration_started_at = observed
    state.total_iterations += 1
    db.flush()

    limit = max(1, min(int(batch_size or state.batch_size), 100))
    max_processing_attempts = max(
        1,
        min(
            int(
                getattr(
                    settings,
                    "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PROCESSING_ATTEMPTS",
                    3,
                )
            ),
            20,
        ),
    )
    receipts = list(
        db.scalars(
            select(CanonicalParserGen4WebhookReceipt)
            .where(
                CanonicalParserGen4WebhookReceipt.campaign_db_id.in_(
                    sorted(campaigns_by_id)
                ),
                CanonicalParserGen4WebhookReceipt.status.in_(
                    [RECEIPT_RECEIVED, RECEIPT_FAILED]
                ),
                CanonicalParserGen4WebhookReceipt.processing_attempts < max_processing_attempts,
                CanonicalParserGen4WebhookReceipt.source == SOURCE_WEBHOOK,
            )
            .order_by(
                CanonicalParserGen4WebhookReceipt.received_at,
                CanonicalParserGen4WebhookReceipt.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    client = jupiter_client or JupiterSwapClient()
    summary = ProcessSummary()
    touched_campaign_ids: set[int] = set()
    per_campaign: dict[str, ProcessSummary] = {
        campaign.campaign_id: ProcessSummary() for campaign in campaigns
    }

    for receipt in receipts:
        campaign = campaigns_by_id.get(receipt.campaign_db_id)
        if campaign is None:
            receipt.status = RECEIPT_IGNORED
            receipt.error_code = "GEN4_COPYABILITY_CAMPAIGN_NOT_ACTIVE"
            receipt.error_message = "Campagna non più attiva durante il processing."
            receipt.processed_at = _aware(now_fn())
            item_summary = ProcessSummary(receipts_processed=1, receipts_ignored=1)
            summary = summary.merge(item_summary)
            continue
        touched_campaign_ids.add(campaign.id)
        receipt.status = RECEIPT_PROCESSING
        receipt.processing_started_at = _aware(now_fn())
        receipt.processing_attempts += 1
        receipt.error_code = None
        receipt.error_message = None
        db.flush()
        try:
            with db.begin_nested():
                signal = parse_raw_copyability_signal(
                    dict(receipt.raw_payload or {}),
                    frozen_wallets=campaign.frozen_wallets or [],
                )
                receipt.wallet_address = signal.wallet_address
                queue_latency_ms = max(
                    0,
                    int(
                        (
                            _aware(receipt.processing_started_at)
                            - _aware(receipt.received_at)
                        ).total_seconds()
                        * 1000
                    ),
                )
                receipt.parsed_summary = {
                    "side": signal.side,
                    "wallet_address": signal.wallet_address,
                    "token_mint": signal.token_mint,
                    "queue_latency_ms": queue_latency_ms,
                    "quote_attempted": False,
                    "quote_built": False,
                    "campaign_role": campaign.campaign_role,
                }
                if signal.side == "BUY":
                    item_summary = _process_buy(
                        db,
                        campaign=campaign,
                        receipt=receipt,
                        signal=signal,
                        client=client,
                        now_fn=now_fn,
                    )
                else:
                    item_summary = _process_sell(
                        db,
                        campaign=campaign,
                        receipt=receipt,
                        signal=signal,
                        client=client,
                        now_fn=now_fn,
                    )
                db.flush()
        except CanonicalParserGen4CopyabilityError as error:
            receipt.status = RECEIPT_IGNORED
            receipt.error_code = error.code
            receipt.error_message = _safe_message(error)
            receipt.processed_at = _aware(now_fn())
            receipt.parsed_summary = {
                "ignored_reason": error.code,
                "campaign_role": campaign.campaign_role,
            }
            item_summary = ProcessSummary(receipts_processed=1, receipts_ignored=1)
        except Exception as error:  # noqa: BLE001
            receipt.status = RECEIPT_FAILED
            receipt.error_code = "GEN4_COPYABILITY_PROCESSING_FAILED"
            receipt.error_message = _safe_message(error)
            receipt.processed_at = _aware(now_fn())
            parsed = dict(receipt.parsed_summary or {})
            parsed["processing_error"] = receipt.error_code
            parsed["campaign_role"] = campaign.campaign_role
            receipt.parsed_summary = parsed
            item_summary = ProcessSummary(receipts_processed=1, failures=1)
        summary = summary.merge(item_summary)
        per_campaign[campaign.campaign_id] = per_campaign[campaign.campaign_id].merge(
            item_summary
        )
        db.flush()

    completed = _aware(now_fn())
    state.last_iteration_completed_at = completed
    state.last_status = "COMPLETED" if not summary.failures else "PARTIAL"
    state.last_error_code = None if not summary.failures else "GEN4_COPYABILITY_PARTIAL_FAILURE"
    state.last_error_message = (
        None if not summary.failures else "Uno o più eventi non sono stati elaborati."
    )
    state.total_receipts_processed += summary.receipts_processed
    state.total_quotes += summary.quotes_requested
    state.total_failures += summary.failures
    if summary.receipts_processed and not summary.failures:
        state.last_success_at = completed
    state.lease_owner = None
    state.lease_expires_at = None
    for campaign in campaigns:
        if campaign.id in touched_campaign_ids or not receipts:
            _refresh_campaign_metrics(db, campaign, observed_at=completed)
    db.flush()
    return {
        "status": state.last_status,
        "campaign_ids": [campaign.campaign_id for campaign in campaigns],
        "summary": summary.__dict__,
        "per_campaign": {
            campaign_id: item.__dict__ for campaign_id, item in per_campaign.items()
        },
        "worker_state": _serialize_worker_state(state),
    }


def _refresh_campaign_metrics(
    db: Session,
    campaign: CanonicalParserGen4CopyabilityCampaign,
    *,
    observed_at: datetime | None = None,
) -> None:
    observed = max(_aware(observed_at), _aware(campaign.latest_observed_at))
    receipts = list(
        db.scalars(
            select(CanonicalParserGen4WebhookReceipt).where(
                CanonicalParserGen4WebhookReceipt.campaign_db_id == campaign.id
            )
        )
    )
    positions = list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityPosition).where(
                CanonicalParserGen4CopyabilityPosition.campaign_db_id == campaign.id
            )
        )
    )
    campaign.latest_observed_at = observed
    campaign.receipt_count = len(receipts)
    campaign.duplicate_receipt_count = sum(max(0, row.delivery_count - 1) for row in receipts)
    campaign.recovery_receipt_count = sum(row.source == SOURCE_RECOVERY for row in receipts)
    campaign.processed_receipt_count = sum(row.status == RECEIPT_PROCESSED for row in receipts)
    campaign.failed_receipt_count = sum(row.status == RECEIPT_FAILED for row in receipts)
    campaign.ignored_receipt_count = sum(
        row.status in {RECEIPT_IGNORED, RECEIPT_EXCLUDED_RECOVERY} for row in receipts
    )
    campaign.buy_signal_count = sum(
        str((row.parsed_summary or {}).get("side") or "") == "BUY" for row in receipts
    )
    campaign.sell_signal_count = sum(
        str((row.parsed_summary or {}).get("side") or "") == "SELL" for row in receipts
    )
    campaign.executable_entry_count = sum(row.entry_copyable for row in positions)
    campaign.rejected_entry_count = sum(row.status == POSITION_REJECTED for row in positions)
    campaign.open_position_count = sum(row.status in {POSITION_OPEN, POSITION_OPEN_PARTIAL} for row in positions)
    closed = [
        row
        for row in positions
        if row.status == POSITION_CLOSED
        and row.entry_source == SOURCE_WEBHOOK
        and row.exit_source == SOURCE_WEBHOOK
        and row.entry_copyable
        and row.exit_copyable
        and row.pnl_lamports is not None
    ]
    campaign.closed_trade_count = len(closed)

    webhook_receipts = sum(row.source == SOURCE_WEBHOOK for row in receipts)
    recovery_receipts = sum(row.source == SOURCE_RECOVERY for row in receipts)
    reconciled_receipts = [
        row
        for row in receipts
        if row.source == SOURCE_RECOVERY
        or bool((row.parsed_summary or {}).get("seen_by_recovery"))
    ]
    reconciled_webhook_receipts = sum(
        row.source == SOURCE_WEBHOOK for row in reconciled_receipts
    )
    coverage_denominator = len(reconciled_receipts)
    coverage = (
        reconciled_webhook_receipts / coverage_denominator * 100.0
        if coverage_denominator
        else 0.0
    )
    pnl_values = [int(row.pnl_lamports or 0) for row in closed]
    cost_values = [int(row.entry_input_lamports + row.allocated_entry_fee_lamports) for row in closed]
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    net_pnl = sum(pnl_values)
    total_cost = sum(cost_values)
    net_return = (net_pnl / total_cost * 100.0) if total_cost > 0 else 0.0
    win_rate = (sum(value > 0 for value in pnl_values) / len(pnl_values) * 100.0) if pnl_values else 0.0

    cumulative = 0
    peak = 0
    maximum_drawdown_lamports = 0
    for row in sorted(closed, key=lambda item: (_aware(item.closed_at), item.id)):
        cumulative += int(row.pnl_lamports or 0)
        peak = max(peak, cumulative)
        maximum_drawdown_lamports = max(maximum_drawdown_lamports, peak - cumulative)
    maximum_drawdown_percent = (
        maximum_drawdown_lamports / total_cost * 100.0 if total_cost > 0 else 0.0
    )

    queue_latencies = [
        float((row.parsed_summary or {}).get("queue_latency_ms"))
        for row in receipts
        if (row.parsed_summary or {}).get("queue_latency_ms") is not None
    ]
    chain_ages = [float(row.chain_age_ms) for row in positions if row.chain_age_ms is not None]
    entry_quote_latencies = [
        float(row.entry_quote_latency_ms) for row in positions if row.entry_quote_latency_ms is not None
    ]
    deterioration = [
        float(row.entry_price_deterioration_bps)
        for row in positions
        if row.entry_price_deterioration_bps is not None
    ]
    quote_attempt_receipts = [
        row
        for row in receipts
        if row.source == SOURCE_WEBHOOK
        and bool((row.parsed_summary or {}).get("quote_attempted"))
    ]
    build_coverage = (
        sum(bool((row.parsed_summary or {}).get("quote_built")) for row in quote_attempt_receipts)
        / len(quote_attempt_receipts)
        * 100.0
        if quote_attempt_receipts
        else 0.0
    )
    elapsed_days = max(0.0, (observed - _aware(campaign.anchor_at)).total_seconds() / 86400.0)
    minimum_time_met = observed >= _aware(campaign.minimum_complete_at)
    minimum_trades_met = len(closed) >= campaign.minimum_closed_trades
    proof_trades_met = len(closed) >= campaign.proof_closed_trades
    profitability_met = net_return > 0 and profit_factor >= campaign.minimum_profit_factor
    drawdown_met = maximum_drawdown_percent <= campaign.maximum_drawdown_percent
    coverage_met = (
        coverage_denominator > 0
        and coverage >= campaign.minimum_webhook_coverage_percent
    )
    build_coverage_met = build_coverage >= campaign.minimum_webhook_coverage_percent
    webhook_active = campaign.webhook_status == "ACTIVE"
    quote_taker_configured = bool(campaign.policy_snapshot.get("quote_taker_configured"))
    no_unresolved_failures = campaign.failed_receipt_count == 0

    if not minimum_time_met or not minimum_trades_met:
        verdict = "COLLECTING"
    elif (
        profitability_met
        and drawdown_met
        and coverage_met
        and build_coverage_met
        and webhook_active
        and quote_taker_configured
        and no_unresolved_failures
    ):
        verdict = "PROFITABLE_EVIDENCE"
    elif net_return > 0:
        verdict = "PROMISING_NOT_PROVEN"
    else:
        verdict = "NEGATIVE_EVIDENCE"
    campaign.verdict = verdict

    gaps: list[str] = []
    if not webhook_active:
        gaps.append("WEBHOOK_NOT_ACTIVE")
    if not quote_taker_configured:
        gaps.append("QUOTE_TAKER_NOT_FROZEN_AT_CAMPAIGN_START")
    if not minimum_time_met:
        gaps.append("MINIMUM_OBSERVATION_DAYS_NOT_REACHED")
    if not minimum_trades_met:
        gaps.append("MINIMUM_CLOSED_COPYABLE_TRADES_NOT_REACHED")
    if not coverage_met:
        gaps.append("WEBHOOK_COVERAGE_BELOW_THRESHOLD")
    if not build_coverage_met:
        gaps.append("UNSIGNED_TRANSACTION_BUILD_COVERAGE_BELOW_THRESHOLD")
    if campaign.failed_receipt_count:
        gaps.append("UNRESOLVED_FAILED_RECEIPTS")
    campaign.evidence_gaps = gaps
    campaign.metrics = {
        "elapsed_days": round(elapsed_days, 6),
        "minimum_time_met": minimum_time_met,
        "minimum_trades_met": minimum_trades_met,
        "proof_trades_met": proof_trades_met,
        "closed_copyable_trades": len(closed),
        "net_pnl_lamports": net_pnl,
        "net_return_percent": round(net_return, 8),
        "profit_factor": round(profit_factor, 8),
        "win_rate_percent": round(win_rate, 8),
        "maximum_drawdown_lamports": maximum_drawdown_lamports,
        "maximum_drawdown_percent": round(maximum_drawdown_percent, 8),
        "webhook_receipts": webhook_receipts,
        "recovery_only_receipts": recovery_receipts,
        "webhook_coverage_percent": round(coverage, 8),
        "webhook_reconciliation_sample": coverage_denominator,
        "webhook_reconciled_deliveries": reconciled_webhook_receipts,
        "unsigned_transaction_build_coverage_percent": round(build_coverage, 8),
        "unsigned_transaction_build_sample": len(quote_attempt_receipts),
        "median_queue_latency_ms": statistics.median(queue_latencies) if queue_latencies else None,
        "p95_queue_latency_ms": _percentile(queue_latencies, 0.95),
        "median_chain_age_ms": statistics.median(chain_ages) if chain_ages else None,
        "p95_chain_age_ms": _percentile(chain_ages, 0.95),
        "median_entry_quote_latency_ms": (
            statistics.median(entry_quote_latencies) if entry_quote_latencies else None
        ),
        "p95_entry_quote_latency_ms": _percentile(entry_quote_latencies, 0.95),
        "median_entry_price_deterioration_bps": (
            statistics.median(deterioration) if deterioration else None
        ),
        "p95_entry_price_deterioration_bps": _percentile(deterioration, 0.95),
        "profitability_met": profitability_met,
        "drawdown_met": drawdown_met,
        "coverage_met": coverage_met,
        "build_coverage_met": build_coverage_met,
        "quote_taker_configured": quote_taker_configured,
        "webhook_active": webhook_active,
        "no_unresolved_failures": no_unresolved_failures,
        "live_gate_eligible": (
            verdict == "PROFITABLE_EVIDENCE"
            and quote_taker_configured
            and not gaps
        ),
        "automatic_live_activation": False,
    }


def _serialize_worker_state(row: CanonicalParserGen4CopyabilityWorkerState | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "state_id": row.state_id,
        "enabled": row.enabled,
        "poll_interval_seconds": row.poll_interval_seconds,
        "batch_size": row.batch_size,
        "lease_owner": row.lease_owner,
        "lease_expires_at": row.lease_expires_at,
        "last_iteration_started_at": row.last_iteration_started_at,
        "last_iteration_completed_at": row.last_iteration_completed_at,
        "last_success_at": row.last_success_at,
        "last_status": row.last_status,
        "last_error_code": row.last_error_code,
        "last_error_message": row.last_error_message,
        "total_iterations": row.total_iterations,
        "total_receipts_processed": row.total_receipts_processed,
        "total_quotes": row.total_quotes,
        "total_failures": row.total_failures,
    }


def _serialize_position(row: CanonicalParserGen4CopyabilityPosition) -> dict[str, Any]:
    return {
        "position_id": row.position_id,
        "status": row.status,
        "wallet_address": row.wallet_address,
        "token_mint": row.token_mint,
        "token_decimals": row.token_decimals,
        "entry_signature": row.entry_signature,
        "entry_source": row.entry_source,
        "entry_signal_at": row.entry_signal_at,
        "entry_received_at": row.entry_received_at,
        "entry_quote_requested_at": row.entry_quote_requested_at,
        "entry_quote_received_at": row.entry_quote_received_at,
        "opened_at": row.opened_at,
        "closed_at": row.closed_at,
        "chain_age_ms": row.chain_age_ms,
        "entry_quote_latency_ms": row.entry_quote_latency_ms,
        "entry_end_to_quote_ms": row.entry_end_to_quote_ms,
        "entry_price_deterioration_bps": row.entry_price_deterioration_bps,
        "entry_price_impact_bps": row.entry_price_impact_bps,
        "entry_transaction_built": row.entry_transaction_built,
        "entry_copyable": row.entry_copyable,
        "entry_rejection_reason": row.entry_rejection_reason,
        "entry_input_lamports": row.entry_input_lamports,
        "entry_output_token_raw": row.entry_output_token_raw,
        "remaining_token_raw": row.remaining_token_raw,
        "realized_output_lamports": row.realized_output_lamports,
        "pnl_lamports": row.pnl_lamports,
        "return_percent": row.return_percent,
        "close_reason": row.close_reason,
        "exit_source": row.exit_source,
        "last_exit_signature": row.last_exit_signature,
        "exit_quote_latency_ms": row.exit_quote_latency_ms,
        "exit_price_impact_bps": row.exit_price_impact_bps,
        "exit_transaction_built": row.exit_transaction_built,
        "exit_copyable": row.exit_copyable,
    }


def _serialize_receipt(row: CanonicalParserGen4WebhookReceipt) -> dict[str, Any]:
    return {
        "receipt_id": row.receipt_id,
        "signature": row.signature,
        "source": row.source,
        "status": row.status,
        "wallet_address": row.wallet_address,
        "matched_wallets": row.matched_wallets,
        "slot": row.slot,
        "block_time": row.block_time,
        "received_at": row.received_at,
        "delivery_count": row.delivery_count,
        "processing_attempts": row.processing_attempts,
        "processed_at": row.processed_at,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "parsed_summary": row.parsed_summary,
    }


def _serialize_campaign(
    db: Session,
    campaign: CanonicalParserGen4CopyabilityCampaign,
    *,
    recent_limit: int = 100,
) -> dict[str, Any]:
    positions = list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityPosition)
            .where(CanonicalParserGen4CopyabilityPosition.campaign_db_id == campaign.id)
            .order_by(desc(CanonicalParserGen4CopyabilityPosition.created_at))
            .limit(max(1, min(int(recent_limit), 500)))
        )
    )
    receipts = list(
        db.scalars(
            select(CanonicalParserGen4WebhookReceipt)
            .where(CanonicalParserGen4WebhookReceipt.campaign_db_id == campaign.id)
            .order_by(desc(CanonicalParserGen4WebhookReceipt.received_at))
            .limit(max(1, min(int(recent_limit), 500)))
        )
    )
    worker = db.scalar(select(CanonicalParserGen4CopyabilityWorkerState).limit(1))
    return {
        "campaign_id": campaign.campaign_id,
        "forward_campaign_db_id": campaign.forward_campaign_db_id,
        "campaign_role": campaign.campaign_role,
        "candidate_key": campaign.candidate_key,
        "status": campaign.status,
        "verdict": campaign.verdict,
        "policy_version": campaign.policy_version,
        "policy_hash": campaign.policy_hash,
        "policy_snapshot": campaign.policy_snapshot,
        "frozen_wallets": campaign.frozen_wallets,
        "selection_snapshot": campaign.selection_snapshot,
        "anchor_at": campaign.anchor_at,
        "minimum_complete_at": campaign.minimum_complete_at,
        "latest_observed_at": campaign.latest_observed_at,
        "started_at": campaign.started_at,
        "completed_at": campaign.completed_at,
        "minimum_observation_days": campaign.minimum_observation_days,
        "minimum_closed_trades": campaign.minimum_closed_trades,
        "proof_closed_trades": campaign.proof_closed_trades,
        "webhook": {
            "webhook_id": campaign.webhook_id,
            "status": campaign.webhook_status,
            "url": campaign.webhook_url,
            "configured_at": campaign.webhook_configured_at,
            "last_webhook_at": campaign.last_webhook_at,
        },
        "counts": {
            "receipt_count": campaign.receipt_count,
            "duplicate_receipt_count": campaign.duplicate_receipt_count,
            "recovery_receipt_count": campaign.recovery_receipt_count,
            "processed_receipt_count": campaign.processed_receipt_count,
            "failed_receipt_count": campaign.failed_receipt_count,
            "ignored_receipt_count": campaign.ignored_receipt_count,
            "buy_signal_count": campaign.buy_signal_count,
            "sell_signal_count": campaign.sell_signal_count,
            "executable_entry_count": campaign.executable_entry_count,
            "rejected_entry_count": campaign.rejected_entry_count,
            "open_position_count": campaign.open_position_count,
            "closed_trade_count": campaign.closed_trade_count,
        },
        "metrics": campaign.metrics,
        "evidence_gaps": campaign.evidence_gaps,
        "safety": campaign.safety,
        "worker_state": _serialize_worker_state(worker),
        "recent_positions": [_serialize_position(row) for row in positions],
        "recent_receipts": [_serialize_receipt(row) for row in receipts],
    }


def get_gen4_copyability_status(
    db: Session,
    *,
    observed_at: datetime | None = None,
    recent_limit: int = 100,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    campaigns = _active_copyability_campaigns(db)
    worker = _ensure_worker_state(db) if bool(
        getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED", False)
    ) else db.scalar(select(CanonicalParserGen4CopyabilityWorkerState).limit(1))
    for campaign in campaigns:
        _refresh_campaign_metrics(db, campaign, observed_at=observed_at)
    db.flush()

    selected: CanonicalParserGen4CopyabilityCampaign | None = None
    if campaign_id:
        selected = _campaign_by_id(db, campaign_id)
    else:
        selected = next(
            (
                campaign
                for campaign in campaigns
                if campaign.campaign_role == CAMPAIGN_ROLE_PRIMARY
            ),
            campaigns[0] if campaigns else None,
        )

    return {
        "runtime_enabled": bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED", False)
        ),
        "autostart": bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_AUTOSTART", False)
        ),
        "campaign": (
            None
            if selected is None
            else _serialize_campaign(db, selected, recent_limit=recent_limit)
        ),
        "active_campaigns": [
            _serialize_campaign(db, campaign, recent_limit=recent_limit)
            for campaign in campaigns
        ],
        "active_campaign_count": len(campaigns),
        "worker_state": _serialize_worker_state(worker),
        "safety": _safety(),
        "m61_parallel_candidate_support": True,
    }
