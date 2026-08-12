from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.gen4_forward_feed import (
    CanonicalParserGen4ForwardFeedRun,
    CanonicalParserGen4ForwardFeedState,
)
from backend.app.models.gen4_forward_shadow import CanonicalParserGen4ForwardCampaign
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.services.blockchain_parser_gen4_forward_shadow_service import (
    GEN4_FORWARD_CYCLE_CONFIRMATION,
    run_gen4_forward_cycle,
)
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    record_gen4_copyability_recovery_events,
)
from backend.app.services.discovery_hydration_service import save_wallet_history_transactions
from backend.app.services.helius import HeliusRequestError, get_wallet_history
from backend.app.services.wallet_activity_service import ensure_aware


GEN4_FORWARD_FEED_POLICY_VERSION = "canonical-parser-gen4-forward-feed/1"
GEN4_FORWARD_FEED_CONFIGURE_CONFIRMATION = "CONFIGURE_GEN4_FORWARD_FEED"
GEN4_FORWARD_FEED_POLL_CONFIRMATION = "RUN_GEN4_FORWARD_FEED_POLL"

STATUS_COMPLETED = "COMPLETED"
STATUS_NOOP = "NOOP"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED_LOCKED = "SKIPPED_LOCKED"
STATUS_SKIPPED_BUDGET = "SKIPPED_BUDGET"


class CanonicalParserGen4ForwardFeedError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    return ensure_aware(value) or _utc_now()


def _safe_error(error: object) -> str:
    text = str(error or "Errore non specificato.")
    if "api-key=" in text.lower():
        return "Errore Helius. Dettagli sensibili rimossi."
    return text[:500]


def _transaction_time(item: dict[str, Any]) -> datetime | None:
    raw = item.get("timestamp")
    if raw is None:
        raw = item.get("blockTime")
    if raw is None:
        raw = item.get("block_time")
    try:
        timestamp = float(raw)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _safety(helius_requests: int = 0) -> dict[str, Any]:
    return {
        "scope": "GEN4_FORWARD_SOURCE_ACQUISITION_AND_SHADOW_CYCLE",
        "helius_requests": max(0, int(helius_requests)),
        "jupiter_requests": 0,
        "paper_orders_created": 0,
        "paper_positions_created": 0,
        "live_orders_created": 0,
        "transactions_built": 0,
        "transactions_signed": 0,
        "transactions_sent": 0,
        "wallets_mutated": False,
        "campaign_wallets_mutated": False,
        "historical_backfill_before_anchor_allowed": False,
        "paper_execution_connected": False,
        "live_execution_connected": False,
    }


def _active_campaign(db: Session) -> CanonicalParserGen4ForwardCampaign:
    campaign = db.scalar(
        select(CanonicalParserGen4ForwardCampaign)
        .where(CanonicalParserGen4ForwardCampaign.status == "ACTIVE")
        .order_by(desc(CanonicalParserGen4ForwardCampaign.started_at))
        .limit(1)
    )
    if campaign is None:
        raise CanonicalParserGen4ForwardFeedError(
            "Nessuna campagna Gen4 forward attiva.",
            code="GEN4_FORWARD_FEED_ACTIVE_CAMPAIGN_REQUIRED",
            status_code=409,
        )
    return campaign


def _state_for_campaign(
    db: Session,
    campaign: CanonicalParserGen4ForwardCampaign,
    *,
    create: bool,
    now: datetime | None = None,
) -> CanonicalParserGen4ForwardFeedState | None:
    state = db.scalar(
        select(CanonicalParserGen4ForwardFeedState).where(
            CanonicalParserGen4ForwardFeedState.campaign_db_id == campaign.id
        )
    )
    if state is not None or not create:
        return state

    observed = _aware(now)
    state = CanonicalParserGen4ForwardFeedState(
        state_id=str(uuid4()),
        campaign_db_id=campaign.id,
        enabled=bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED", False)
        ),
        interval_seconds=int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_INTERVAL_SECONDS", 120)
        ),
        max_requests_per_run=int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_MAX_REQUESTS_PER_RUN", 4)
        ),
        page_size=int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_PAGE_SIZE", 100)
        ),
        overlap_seconds=int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_OVERLAP_SECONDS", 90)
        ),
        feed_started_at=observed,
        next_poll_at=observed,
        technical_metadata={
            "policy_version": GEN4_FORWARD_FEED_POLICY_VERSION,
            "created_from": "active_campaign",
        },
    )
    db.add(state)
    db.flush()
    return state


def _serialize_run(row: CanonicalParserGen4ForwardFeedRun) -> dict[str, Any]:
    return {
        "run_id": row.run_id,
        "trigger": row.trigger,
        "status": row.status,
        "owner_id": row.owner_id,
        "observed_from_at": row.observed_from_at,
        "observed_to_at": row.observed_to_at,
        "wallet_count": row.wallet_count,
        "request_budget": row.request_budget,
        "helius_requests": row.helius_requests,
        "transactions_found": row.transactions_found,
        "swaps_found": row.swaps_found,
        "trades_imported": row.trades_imported,
        "trades_updated": row.trades_updated,
        "parse_failures": row.parse_failures,
        "stale_transactions_filtered": row.stale_transactions_filtered,
        "cycle_id": row.cycle_id,
        "cycle_sequence": row.cycle_sequence,
        "cycle_status": row.cycle_status,
        "new_decisions": row.new_decisions,
        "updated_decisions": row.updated_decisions,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "details": dict(row.details or {}),
        "safety": dict(row.safety or {}),
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


def _daily_helius_requests(db: Session, campaign_id: int, observed: datetime) -> int:
    day_start = observed.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.coalesce(func.sum(CanonicalParserGen4ForwardFeedRun.helius_requests), 0)).where(
                CanonicalParserGen4ForwardFeedRun.campaign_db_id == campaign_id,
                CanonicalParserGen4ForwardFeedRun.started_at >= day_start,
            )
        )
        or 0
    )


def _webhook_gated_wallets(
    db: Session,
    *,
    campaign: CanonicalParserGen4ForwardCampaign,
    state: CanonicalParserGen4ForwardFeedState,
    wallets: list[str],
    observed: datetime,
) -> tuple[list[str] | None, dict[str, Any]]:
    """Gate expensive history calls behind fresh primary webhook receipts.

    ``None`` preserves the legacy M56-M57 polling behavior if the M58+
    real-time copyability layer is unavailable or not ACTIVE. An empty list
    means the primary real-time webhook is active but no forward wallet had
    a fresh delivery, so the scheduler must use zero Helius history calls.
    """
    primary = db.scalar(
        select(CanonicalParserGen4CopyabilityCampaign)
        .where(
            CanonicalParserGen4CopyabilityCampaign.forward_campaign_db_id == campaign.id,
            CanonicalParserGen4CopyabilityCampaign.status == "ACTIVE",
            CanonicalParserGen4CopyabilityCampaign.campaign_role == "PRIMARY_FORWARD",
        )
        .order_by(CanonicalParserGen4CopyabilityCampaign.id.asc())
        .limit(1)
    )
    if primary is None or primary.webhook_status != "ACTIVE":
        return None, {
            "acquisition_mode": "LEGACY_POLLING_FALLBACK",
            "reason": "PRIMARY_REALTIME_WEBHOOK_NOT_ACTIVE",
        }

    floor_base = state.last_success_at or state.feed_started_at or campaign.anchor_at
    receipt_floor = max(
        _aware(campaign.anchor_at),
        _aware(floor_base) - timedelta(seconds=int(state.overlap_seconds)),
    )
    rows = list(
        db.scalars(
            select(CanonicalParserGen4WebhookReceipt.wallet_address)
            .where(
                CanonicalParserGen4WebhookReceipt.campaign_db_id == primary.id,
                CanonicalParserGen4WebhookReceipt.source == "WEBHOOK",
                CanonicalParserGen4WebhookReceipt.received_at > receipt_floor,
                CanonicalParserGen4WebhookReceipt.received_at <= observed,
                CanonicalParserGen4WebhookReceipt.wallet_address.in_(wallets),
            )
            .distinct()
        ).all()
    )
    triggered_set = {str(value).strip() for value in rows if str(value or "").strip()}
    triggered = [wallet for wallet in wallets if wallet in triggered_set]
    return triggered, {
        "acquisition_mode": "WEBHOOK_GATED_RECOVERY",
        "primary_copyability_campaign_id": primary.campaign_id,
        "webhook_id": primary.webhook_id,
        "receipt_floor": receipt_floor.isoformat(),
        "triggered_wallets": triggered,
        "configured_wallet_count": len(wallets),
        "triggered_wallet_count": len(triggered),
    }


def _persist_webhook_idle_run(
    db: Session,
    *,
    campaign: CanonicalParserGen4ForwardCampaign,
    state: CanonicalParserGen4ForwardFeedState,
    owner_id: str,
    trigger: str,
    observed: datetime,
    gate_details: dict[str, Any],
) -> CanonicalParserGen4ForwardFeedRun:
    # Preserve the original M56-M57 cycle cadence while removing the idle
    # provider call. This keeps forward decision time progression unchanged.
    cycle_result = run_gen4_forward_cycle(
        db,
        campaign_id=campaign.campaign_id,
        confirmation=GEN4_FORWARD_CYCLE_CONFIRMATION,
        observed_at=observed,
    )
    cycle = dict(cycle_result.get("cycle") or {})
    row = CanonicalParserGen4ForwardFeedRun(
        run_id=str(uuid4()),
        state_db_id=state.id,
        campaign_db_id=campaign.id,
        trigger=trigger,
        status=STATUS_NOOP,
        owner_id=owner_id,
        observed_from_at=observed,
        observed_to_at=observed,
        wallet_count=0,
        request_budget=0,
        helius_requests=0,
        transactions_found=0,
        swaps_found=0,
        trades_imported=0,
        trades_updated=0,
        parse_failures=0,
        stale_transactions_filtered=0,
        cycle_id=cycle.get("cycle_id"),
        cycle_sequence=cycle.get("sequence"),
        cycle_status=cycle.get("status"),
        new_decisions=int(cycle.get("new_decision_count") or 0),
        updated_decisions=int(cycle.get("updated_decision_count") or 0),
        error_code=None,
        error_message=None,
        details={
            **gate_details,
            "provider_call_skipped": True,
            "provider_call_reason": "NO_NEW_PRIMARY_WEBHOOK_RECEIPT",
            "copyability_recovery": {
                "created": 0,
                "existing": 0,
                "ignored": 0,
                "counted_as_realtime": False,
            },
        },
        safety=_safety(0),
        started_at=state.last_poll_started_at or observed,
        completed_at=observed,
    )
    db.add(row)
    state.total_runs += 1
    state.successful_runs += 1
    state.last_status = STATUS_NOOP
    state.last_error_code = None
    state.last_error_message = None
    state.last_poll_completed_at = observed
    state.last_success_at = observed
    state.next_poll_at = observed + timedelta(seconds=state.interval_seconds)
    _release_lease(state)
    db.flush()
    return row


def get_gen4_forward_feed_status(db: Session) -> dict[str, Any]:
    campaign = _active_campaign(db)
    state = _state_for_campaign(db, campaign, create=True)
    assert state is not None
    recent = list(
        db.scalars(
            select(CanonicalParserGen4ForwardFeedRun)
            .where(CanonicalParserGen4ForwardFeedRun.campaign_db_id == campaign.id)
            .order_by(desc(CanonicalParserGen4ForwardFeedRun.started_at))
            .limit(20)
        )
    )
    now = _utc_now()
    return {
        "policy_version": GEN4_FORWARD_FEED_POLICY_VERSION,
        "runtime_enabled": bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED", False)
        ),
        "autostart_enabled": bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_AUTOSTART", False)
        ),
        "automatic_enhanced_enabled": bool(
            getattr(settings, "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED", False)
        ),
        "campaign_id": campaign.campaign_id,
        "frozen_wallets": list(campaign.frozen_wallets or []),
        "state": {
            "state_id": state.state_id,
            "enabled": state.enabled,
            "interval_seconds": state.interval_seconds,
            "max_requests_per_run": state.max_requests_per_run,
            "page_size": state.page_size,
            "overlap_seconds": state.overlap_seconds,
            "feed_started_at": state.feed_started_at,
            "last_poll_started_at": state.last_poll_started_at,
            "last_poll_completed_at": state.last_poll_completed_at,
            "last_success_at": state.last_success_at,
            "next_poll_at": state.next_poll_at,
            "lease_owner": state.lease_owner,
            "lease_expires_at": state.lease_expires_at,
            "last_status": state.last_status,
            "last_error_code": state.last_error_code,
            "last_error_message": state.last_error_message,
            "total_runs": state.total_runs,
            "successful_runs": state.successful_runs,
            "failed_runs": state.failed_runs,
            "total_helius_requests": state.total_helius_requests,
            "total_transactions_found": state.total_transactions_found,
            "total_swaps_found": state.total_swaps_found,
            "total_trades_imported": state.total_trades_imported,
            "total_trades_updated": state.total_trades_updated,
            "total_parse_failures": state.total_parse_failures,
            "total_stale_transactions_filtered": state.total_stale_transactions_filtered,
            "daily_helius_requests": _daily_helius_requests(db, campaign.id, now),
            "daily_request_cap": int(
                getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_DAILY_REQUEST_CAP", 2000)
            ),
        },
        "recent_runs": [_serialize_run(row) for row in recent],
        "safety": _safety(0),
    }


def configure_gen4_forward_feed(
    db: Session,
    *,
    campaign_id: str,
    confirmation: str,
    enabled: bool,
    interval_seconds: int | None = None,
    max_requests_per_run: int | None = None,
    page_size: int | None = None,
    overlap_seconds: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if confirmation.strip() != GEN4_FORWARD_FEED_CONFIGURE_CONFIRMATION:
        raise CanonicalParserGen4ForwardFeedError(
            f"Conferma richiesta: {GEN4_FORWARD_FEED_CONFIGURE_CONFIRMATION}",
            code="GEN4_FORWARD_FEED_CONFIGURE_CONFIRMATION_REQUIRED",
        )
    campaign = _active_campaign(db)
    if campaign.campaign_id != campaign_id:
        raise CanonicalParserGen4ForwardFeedError(
            "La campagna richiesta non è la campagna attiva.",
            code="GEN4_FORWARD_FEED_CAMPAIGN_MISMATCH",
            status_code=409,
        )
    state = _state_for_campaign(db, campaign, create=True, now=now)
    assert state is not None
    state.enabled = bool(enabled)
    if interval_seconds is not None:
        state.interval_seconds = max(30, min(int(interval_seconds), 3600))
    if max_requests_per_run is not None:
        state.max_requests_per_run = max(1, min(int(max_requests_per_run), 20))
    if page_size is not None:
        state.page_size = max(10, min(int(page_size), 100))
    if overlap_seconds is not None:
        state.overlap_seconds = max(0, min(int(overlap_seconds), 300))
    observed = _aware(now)
    if state.enabled and (state.next_poll_at is None or state.next_poll_at > observed):
        state.next_poll_at = observed
    if not state.enabled:
        state.lease_owner = None
        state.lease_expires_at = None
    db.flush()
    return get_gen4_forward_feed_status(db)


def _acquire_lease(
    db: Session,
    *,
    campaign: CanonicalParserGen4ForwardCampaign,
    owner_id: str,
    observed: datetime,
) -> CanonicalParserGen4ForwardFeedState | None:
    state = db.scalar(
        select(CanonicalParserGen4ForwardFeedState)
        .where(CanonicalParserGen4ForwardFeedState.campaign_db_id == campaign.id)
        .with_for_update()
    )
    if state is None:
        state = _state_for_campaign(db, campaign, create=True, now=observed)
    assert state is not None
    lease_expires = _aware(state.lease_expires_at) if state.lease_expires_at else None
    if state.lease_owner and lease_expires and lease_expires > observed:
        return None
    lease_seconds = int(
        getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_LEASE_SECONDS", 180)
    )
    state.lease_owner = owner_id
    state.lease_expires_at = observed + timedelta(seconds=lease_seconds)
    state.last_poll_started_at = observed
    db.flush()
    return state


def _release_lease(state: CanonicalParserGen4ForwardFeedState) -> None:
    state.lease_owner = None
    state.lease_expires_at = None


def _persist_skipped_run(
    db: Session,
    *,
    campaign: CanonicalParserGen4ForwardCampaign,
    state: CanonicalParserGen4ForwardFeedState,
    owner_id: str,
    trigger: str,
    status: str,
    observed: datetime,
    error_code: str,
    error_message: str,
) -> CanonicalParserGen4ForwardFeedRun:
    row = CanonicalParserGen4ForwardFeedRun(
        run_id=str(uuid4()),
        state_db_id=state.id,
        campaign_db_id=campaign.id,
        trigger=trigger,
        status=status,
        owner_id=owner_id,
        observed_from_at=observed,
        observed_to_at=observed,
        wallet_count=len(campaign.frozen_wallets or []),
        request_budget=0,
        helius_requests=0,
        transactions_found=0,
        swaps_found=0,
        trades_imported=0,
        trades_updated=0,
        parse_failures=0,
        stale_transactions_filtered=0,
        new_decisions=0,
        updated_decisions=0,
        error_code=error_code,
        error_message=error_message,
        details={},
        safety=_safety(0),
        started_at=observed,
        completed_at=observed,
    )
    db.add(row)
    state.total_runs += 1
    state.last_status = status
    state.last_error_code = error_code
    state.last_error_message = error_message
    state.last_poll_completed_at = observed
    state.next_poll_at = observed + timedelta(seconds=state.interval_seconds)
    _release_lease(state)
    db.flush()
    return row


def run_gen4_forward_feed_poll(
    db: Session,
    *,
    campaign_id: str,
    confirmation: str,
    trigger: str = "MANUAL",
    owner_id: str | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED", False)
    ):
        raise CanonicalParserGen4ForwardFeedError(
            "Il feed Gen4 forward è disabilitato.",
            code="GEN4_FORWARD_FEED_DISABLED",
            status_code=409,
        )
    if confirmation.strip() != GEN4_FORWARD_FEED_POLL_CONFIRMATION:
        raise CanonicalParserGen4ForwardFeedError(
            f"Conferma richiesta: {GEN4_FORWARD_FEED_POLL_CONFIRMATION}",
            code="GEN4_FORWARD_FEED_POLL_CONFIRMATION_REQUIRED",
        )
    normalized_trigger = str(trigger or "MANUAL").upper()
    if normalized_trigger not in {"MANUAL", "SCHEDULER", "STARTUP"}:
        raise CanonicalParserGen4ForwardFeedError(
            "Trigger feed non valido.",
            code="GEN4_FORWARD_FEED_INVALID_TRIGGER",
        )

    campaign = _active_campaign(db)
    if campaign.campaign_id != campaign_id:
        raise CanonicalParserGen4ForwardFeedError(
            "La campagna richiesta non è la campagna attiva.",
            code="GEN4_FORWARD_FEED_CAMPAIGN_MISMATCH",
            status_code=409,
        )
    observed = max(_aware(observed_at), _aware(campaign.latest_observed_at) + timedelta(microseconds=1))
    owner = (owner_id or f"feed-{uuid4()}")[:120]
    state = _acquire_lease(db, campaign=campaign, owner_id=owner, observed=observed)
    if state is None:
        existing_state = _state_for_campaign(db, campaign, create=True, now=observed)
        assert existing_state is not None
        row = CanonicalParserGen4ForwardFeedRun(
            run_id=str(uuid4()),
            state_db_id=existing_state.id,
            campaign_db_id=campaign.id,
            trigger=normalized_trigger,
            status=STATUS_SKIPPED_LOCKED,
            owner_id=owner,
            observed_from_at=observed,
            observed_to_at=observed,
            wallet_count=len(campaign.frozen_wallets or []),
            request_budget=0,
            helius_requests=0,
            transactions_found=0,
            swaps_found=0,
            trades_imported=0,
            trades_updated=0,
            parse_failures=0,
            stale_transactions_filtered=0,
            new_decisions=0,
            updated_decisions=0,
            error_code="GEN4_FORWARD_FEED_LEASE_BUSY",
            error_message="Un altro poll Gen4 forward possiede il lease.",
            details={},
            safety=_safety(0),
            started_at=observed,
            completed_at=observed,
        )
        db.add(row)
        db.flush()
        return {"run": _serialize_run(row), "status": get_gen4_forward_feed_status(db)}

    if not state.enabled:
        row = _persist_skipped_run(
            db,
            campaign=campaign,
            state=state,
            owner_id=owner,
            trigger=normalized_trigger,
            status=STATUS_NOOP,
            observed=observed,
            error_code="GEN4_FORWARD_FEED_STATE_DISABLED",
            error_message="Il feed della campagna è disabilitato.",
        )
        return {"run": _serialize_run(row), "status": get_gen4_forward_feed_status(db)}

    daily_cap = int(
        getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_DAILY_REQUEST_CAP", 2000)
    )
    daily_used = _daily_helius_requests(db, campaign.id, observed)
    if daily_used >= daily_cap:
        row = _persist_skipped_run(
            db,
            campaign=campaign,
            state=state,
            owner_id=owner,
            trigger=normalized_trigger,
            status=STATUS_SKIPPED_BUDGET,
            observed=observed,
            error_code="GEN4_FORWARD_FEED_DAILY_REQUEST_CAP_REACHED",
            error_message="Tetto giornaliero Helius del feed raggiunto.",
        )
        return {"run": _serialize_run(row), "status": get_gen4_forward_feed_status(db)}

    max_lag_seconds = int(
        getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_MAX_INGESTION_LAG_SECONDS", 300)
    )
    source_floor = observed - timedelta(seconds=max_lag_seconds)
    if state.last_success_at is not None:
        source_floor = max(
            source_floor,
            _aware(state.last_success_at) - timedelta(seconds=state.overlap_seconds),
        )
    source_floor = max(source_floor, _aware(campaign.anchor_at), _aware(state.feed_started_at))

    wallets = [str(item) for item in (campaign.frozen_wallets or []) if str(item).strip()]
    gated_wallets, gate_details = _webhook_gated_wallets(
        db,
        campaign=campaign,
        state=state,
        wallets=wallets,
        observed=observed,
    )
    if gated_wallets == []:
        row = _persist_webhook_idle_run(
            db,
            campaign=campaign,
            state=state,
            owner_id=owner,
            trigger=normalized_trigger,
            observed=observed,
            gate_details=gate_details,
        )
        return {
            "run": _serialize_run(row),
            "status": get_gen4_forward_feed_status(db),
        }
    if not bool(
        getattr(settings, "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED", False)
    ):
        row = _persist_skipped_run(
            db,
            campaign=campaign,
            state=state,
            owner_id=owner,
            trigger=normalized_trigger,
            status=STATUS_SKIPPED_BUDGET,
            observed=observed,
            error_code="HELIUS_AUTOMATIC_ENHANCED_DISABLED",
            error_message=(
                "Recovery Enhanced automatico disabilitato; il Raw Webhook "
                "resta il feed real-time autorizzato."
            ),
        )
        return {
            "run": _serialize_run(row),
            "status": get_gen4_forward_feed_status(db),
        }
    acquisition_wallets = wallets if gated_wallets is None else gated_wallets
    request_budget = min(
        int(state.max_requests_per_run),
        max(0, daily_cap - daily_used),
    )
    requests_used = 0
    all_transactions: list[tuple[str, dict[str, Any]]] = []
    wallet_details: list[dict[str, Any]] = []
    partial_errors: list[dict[str, str]] = []

    for wallet_index, wallet in enumerate(acquisition_wallets):
        remaining_wallets = max(1, len(acquisition_wallets) - wallet_index)
        wallet_budget = max(1, (request_budget - requests_used) // remaining_wallets)
        before_signature: str | None = None
        wallet_transactions: list[dict[str, Any]] = []
        pages = 0
        try:
            while requests_used < request_budget and pages < wallet_budget:
                page = get_wallet_history(
                    wallet,
                    limit=state.page_size,
                    transaction_type="SWAP",
                    gte_time=int(source_floor.timestamp()),
                    lte_time=int(observed.timestamp()),
                    before_signature=before_signature,
                    commitment="confirmed",
                    token_accounts="balanceChanged",
                    max_retries=0,
                    request_origin="GEN4_FORWARD_RECOVERY",
                    automatic=True,
                )
                requests_used += 1
                pages += 1
                wallet_transactions.extend(page)
                if len(page) < state.page_size or not page:
                    break
                oldest = min(
                    (_transaction_time(item) for item in page if _transaction_time(item) is not None),
                    default=None,
                )
                if oldest is not None and oldest <= source_floor:
                    break
                signature = str(page[-1].get("signature") or "").strip()
                if not signature or signature == before_signature:
                    break
                before_signature = signature
        except HeliusRequestError as error:
            requests_used += max(1, int(error.attempts or 1))
            partial_errors.append(
                {
                    "wallet_address": wallet,
                    "error_code": error.error_code,
                    "error_message": _safe_error(error.message),
                }
            )
        wallet_details.append(
            {
                "wallet_address": wallet,
                "pages": pages,
                "transactions_found": len(wallet_transactions),
            }
        )
        all_transactions.extend((wallet, item) for item in wallet_transactions)
        if requests_used >= request_budget:
            break

    filtered_by_wallet: dict[str, list[dict[str, Any]]] = {
        wallet: [] for wallet in acquisition_wallets
    }
    stale_filtered = 0
    invalid_time_filtered = 0
    for wallet, item in all_transactions:
        occurred = _transaction_time(item)
        if occurred is None:
            invalid_time_filtered += 1
            continue
        if occurred < source_floor or occurred < _aware(campaign.anchor_at) or occurred > observed:
            stale_filtered += 1
            continue
        if (observed - occurred).total_seconds() > max_lag_seconds:
            stale_filtered += 1
            continue
        filtered_by_wallet.setdefault(wallet, []).append(item)

    counters = {
        "transactions_found": len(all_transactions),
        "swaps_found": 0,
        "trades_imported": 0,
        "trades_updated": 0,
        "parse_failures": 0,
        "copyability_recovery_created": 0,
        "copyability_recovery_existing": 0,
        "copyability_recovery_ignored": 0,
    }
    for wallet in acquisition_wallets:
        recovery = record_gen4_copyability_recovery_events(
            db,
            wallet_address=wallet,
            transactions=filtered_by_wallet.get(wallet, []),
            observed_at=observed,
        )
        counters["copyability_recovery_created"] += int(recovery["created"])
        counters["copyability_recovery_existing"] += int(recovery["existing"])
        counters["copyability_recovery_ignored"] += int(recovery["ignored"])
        saved = save_wallet_history_transactions(
            db,
            wallet_address=wallet,
            transactions=filtered_by_wallet.get(wallet, []),
        )
        counters["swaps_found"] += int(saved["swaps_found"])
        counters["trades_imported"] += int(saved["trades_imported"])
        counters["trades_updated"] += int(saved["trades_updated"])
        counters["parse_failures"] += int(saved["parse_failures"])
    db.flush()

    cycle_result = run_gen4_forward_cycle(
        db,
        campaign_id=campaign.campaign_id,
        confirmation=GEN4_FORWARD_CYCLE_CONFIRMATION,
        observed_at=observed,
    )
    cycle = dict(cycle_result.get("cycle") or {})
    new_decisions = int(cycle.get("new_decision_count") or 0)
    updated_decisions = int(cycle.get("updated_decision_count") or 0)
    status = STATUS_PARTIAL if partial_errors else (
        STATUS_COMPLETED
        if counters["trades_imported"] or counters["trades_updated"] or new_decisions or updated_decisions
        else STATUS_NOOP
    )

    run = CanonicalParserGen4ForwardFeedRun(
        run_id=str(uuid4()),
        state_db_id=state.id,
        campaign_db_id=campaign.id,
        trigger=normalized_trigger,
        status=status,
        owner_id=owner,
        observed_from_at=source_floor,
        observed_to_at=observed,
        wallet_count=len(acquisition_wallets),
        request_budget=request_budget,
        helius_requests=requests_used,
        transactions_found=counters["transactions_found"],
        swaps_found=counters["swaps_found"],
        trades_imported=counters["trades_imported"],
        trades_updated=counters["trades_updated"],
        parse_failures=counters["parse_failures"],
        stale_transactions_filtered=stale_filtered + invalid_time_filtered,
        cycle_id=cycle.get("cycle_id"),
        cycle_sequence=cycle.get("sequence"),
        cycle_status=cycle.get("status"),
        new_decisions=new_decisions,
        updated_decisions=updated_decisions,
        error_code=("GEN4_FORWARD_FEED_PARTIAL_HELIUS_FAILURE" if partial_errors else None),
        error_message=("Uno o più wallet non sono stati acquisiti." if partial_errors else None),
        details={
            **gate_details,
            "wallets": wallet_details,
            "partial_errors": partial_errors,
            "source_floor": source_floor.isoformat(),
            "observed_at": observed.isoformat(),
            "invalid_time_filtered": invalid_time_filtered,
            "maximum_ingestion_lag_seconds": max_lag_seconds,
            "provider_call_skipped": False,
            "copyability_recovery": {
                "created": counters["copyability_recovery_created"],
                "existing": counters["copyability_recovery_existing"],
                "ignored": counters["copyability_recovery_ignored"],
                "counted_as_realtime": False,
            },
        },
        safety=_safety(requests_used),
        started_at=state.last_poll_started_at or observed,
        completed_at=observed,
    )
    db.add(run)

    state.total_runs += 1
    state.successful_runs += 1
    state.total_helius_requests += requests_used
    state.total_transactions_found += counters["transactions_found"]
    state.total_swaps_found += counters["swaps_found"]
    state.total_trades_imported += counters["trades_imported"]
    state.total_trades_updated += counters["trades_updated"]
    state.total_parse_failures += counters["parse_failures"]
    state.total_stale_transactions_filtered += stale_filtered + invalid_time_filtered
    state.last_status = status
    state.last_error_code = run.error_code
    state.last_error_message = run.error_message
    state.last_poll_completed_at = observed
    state.last_success_at = observed
    state.next_poll_at = observed + timedelta(seconds=state.interval_seconds)
    _release_lease(state)
    db.flush()
    return {
        "run": _serialize_run(run),
        "cycle": cycle_result,
        "status": get_gen4_forward_feed_status(db),
    }
