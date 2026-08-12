from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4CopyabilityWorkerState,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.models.gen4_forward_feed import CanonicalParserGen4ForwardFeedState
from backend.app.models.live_trading_policy import LiveTradingPolicy
from backend.app.models.live_trading_worker import LiveTradingWorkerState


M63_TARGET_WALLET = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
M63_CONTAINMENT_CONFIRMATION = "APPLY_M63_HELIUS_CREDIT_CONTAINMENT"
M63_CONTAINMENT_METADATA_KEY = "m63_helius_credit_containment"


class M63HeliusContainmentError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _select_target_campaign(
    campaigns: list[CanonicalParserGen4CopyabilityCampaign],
    *,
    target_wallet: str,
) -> CanonicalParserGen4CopyabilityCampaign:
    matching = [
        campaign
        for campaign in campaigns
        if target_wallet in (campaign.frozen_wallets or [])
        and campaign.status == "ACTIVE"
    ]
    if len(matching) != 1:
        raise M63HeliusContainmentError(
            "Il contenimento richiede esattamente una campagna ACTIVE contenente "
            f"il wallet target; trovate={len(matching)}."
        )
    return matching[0]


def inspect_m63_helius_credit_containment(
    db: Session,
    *,
    target_wallet: str = M63_TARGET_WALLET,
) -> dict[str, Any]:
    campaigns = list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityCampaign).order_by(
                CanonicalParserGen4CopyabilityCampaign.id
            )
        )
    )
    target = _select_target_campaign(campaigns, target_wallet=target_wallet)
    active = [campaign for campaign in campaigns if campaign.status == "ACTIVE"]
    forward_states = list(
        db.scalars(
            select(CanonicalParserGen4ForwardFeedState).order_by(
                CanonicalParserGen4ForwardFeedState.id
            )
        )
    )
    policy = db.scalar(
        select(LiveTradingPolicy).where(LiveTradingPolicy.name == "default").limit(1)
    )
    legacy_worker = db.get(LiveTradingWorkerState, 1)
    copy_worker = db.scalar(
        select(CanonicalParserGen4CopyabilityWorkerState)
        .where(
            CanonicalParserGen4CopyabilityWorkerState.state_id
            == "GEN4_COPYABILITY_GLOBAL"
        )
        .limit(1)
    )
    return {
        "target_wallet": target_wallet,
        "target_campaign_id": target.campaign_id,
        "target_campaign_role": target.campaign_role,
        "target_closed_trade_count": int(target.closed_trade_count or 0),
        "active_campaign_ids": [campaign.campaign_id for campaign in active],
        "campaigns_to_pause": [
            campaign.campaign_id for campaign in active if campaign.id != target.id
        ],
        "enabled_forward_feed_state_ids": [
            state.state_id for state in forward_states if state.enabled
        ],
        "legacy_stream_execution_enabled": (
            bool(policy.stream_execution_enabled) if policy is not None else False
        ),
        "legacy_worker_status": (
            legacy_worker.status if legacy_worker is not None else "NOT_PRESENT"
        ),
        "copyability_worker_enabled": (
            bool(copy_worker.enabled) if copy_worker is not None else None
        ),
        "history_preserved": True,
        "rows_deleted": 0,
        "helius_requests": 0,
    }


def apply_m63_helius_credit_containment(
    db: Session,
    *,
    confirmation: str,
    target_wallet: str = M63_TARGET_WALLET,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    if confirmation.strip() != M63_CONTAINMENT_CONFIRMATION:
        raise M63HeliusContainmentError(
            f"Conferma richiesta: {M63_CONTAINMENT_CONFIRMATION}"
        )

    observed = observed_at or _utc_now()
    campaigns = list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityCampaign)
            .order_by(CanonicalParserGen4CopyabilityCampaign.id)
            .with_for_update()
        )
    )
    target = _select_target_campaign(campaigns, target_wallet=target_wallet)
    target_closed_before = int(target.closed_trade_count or 0)
    forward_states = list(
        db.scalars(
            select(CanonicalParserGen4ForwardFeedState)
            .order_by(CanonicalParserGen4ForwardFeedState.id)
            .with_for_update()
        )
    )
    policy = db.scalar(
        select(LiveTradingPolicy)
        .where(LiveTradingPolicy.name == "default")
        .with_for_update()
        .limit(1)
    )
    legacy_worker = db.scalar(
        select(LiveTradingWorkerState)
        .where(LiveTradingWorkerState.id == 1)
        .with_for_update()
        .limit(1)
    )
    copy_worker = db.scalar(
        select(CanonicalParserGen4CopyabilityWorkerState)
        .where(
            CanonicalParserGen4CopyabilityWorkerState.state_id
            == "GEN4_COPYABILITY_GLOBAL"
        )
        .with_for_update()
        .limit(1)
    )
    last_target_webhook_receipt = db.scalar(
        select(CanonicalParserGen4WebhookReceipt)
        .where(
            CanonicalParserGen4WebhookReceipt.campaign_db_id == target.id,
            CanonicalParserGen4WebhookReceipt.source == "WEBHOOK",
        )
        .order_by(
            CanonicalParserGen4WebhookReceipt.received_at.desc(),
            CanonicalParserGen4WebhookReceipt.id.desc(),
        )
        .limit(1)
    )

    target_metadata = dict(target.technical_metadata or {})
    existing_snapshot = target_metadata.get(M63_CONTAINMENT_METADATA_KEY)
    if not isinstance(existing_snapshot, dict) or not existing_snapshot.get(
        "original_state"
    ):
        original_state = {
            "campaign_statuses": {
                campaign.campaign_id: campaign.status for campaign in campaigns
            },
            "forward_feed_enabled": {
                state.state_id: bool(state.enabled) for state in forward_states
            },
            "legacy_stream_execution_enabled": (
                bool(policy.stream_execution_enabled) if policy is not None else None
            ),
            "legacy_worker": (
                {
                    "status": legacy_worker.status,
                    "active_wallets": list(legacy_worker.active_wallets or []),
                    "monitored_wallets": int(legacy_worker.monitored_wallets or 0),
                    "active_subscriptions": int(
                        legacy_worker.active_subscriptions or 0
                    ),
                    "queue_depth": int(legacy_worker.queue_depth or 0),
                }
                if legacy_worker is not None
                else None
            ),
            "copyability_worker_enabled": (
                bool(copy_worker.enabled) if copy_worker is not None else None
            ),
        }
    else:
        original_state = existing_snapshot["original_state"]
    recovery_after_utc = (
        existing_snapshot.get("public_rpc_recovery_after_utc")
        if isinstance(existing_snapshot, dict)
        else None
    )
    if not recovery_after_utc and target.last_webhook_at is not None:
        recovery_after_utc = (
            last_target_webhook_receipt.block_time
            if last_target_webhook_receipt is not None
            and last_target_webhook_receipt.block_time is not None
            else target.last_webhook_at
        ).isoformat()
    recovery_after_signature = (
        existing_snapshot.get("public_rpc_recovery_after_signature")
        if isinstance(existing_snapshot, dict)
        else None
    )
    if not recovery_after_signature and last_target_webhook_receipt is not None:
        recovery_after_signature = last_target_webhook_receipt.signature

    paused_campaign_ids: list[str] = []
    for campaign in campaigns:
        if campaign.status == "ACTIVE" and campaign.id != target.id:
            metadata = dict(campaign.technical_metadata or {})
            metadata["m63_paused_at"] = observed.isoformat()
            metadata["m63_pause_reason"] = (
                "HELIUS_CREDIT_CONTAINMENT_NON_TARGET_CAMPAIGN"
            )
            campaign.technical_metadata = metadata
            campaign.status = "PAUSED"
            paused_campaign_ids.append(campaign.campaign_id)

    target_metadata[M63_CONTAINMENT_METADATA_KEY] = {
        "policy_version": "m63-helius-credit-containment/1",
        "applied_at": observed.isoformat(),
        "target_wallet": target_wallet,
        "exclusive_active_campaign": True,
        "public_rpc_recovery_after_utc": recovery_after_utc,
        "public_rpc_recovery_after_signature": recovery_after_signature,
        "original_state": original_state,
    }
    target.technical_metadata = target_metadata

    disabled_forward_state_ids: list[str] = []
    for state in forward_states:
        if state.enabled:
            disabled_forward_state_ids.append(state.state_id)
        state.enabled = False
        state.next_poll_at = None
        state.lease_owner = None
        state.lease_expires_at = None
        state.last_status = "NOOP"
        state.last_error_code = "M63_HELIUS_CREDIT_CONTAINMENT"
        state.last_error_message = "Enhanced forward recovery disabilitato."
        metadata = dict(state.technical_metadata or {})
        metadata["m63_disabled_at"] = observed.isoformat()
        state.technical_metadata = metadata

    if policy is not None:
        policy.stream_execution_enabled = False

    if legacy_worker is not None:
        legacy_worker.status = "STOPPED"
        legacy_worker.lease_owner = None
        legacy_worker.lease_expires_at = None
        legacy_worker.active_wallets = []
        legacy_worker.monitored_wallets = 0
        legacy_worker.active_subscriptions = 0
        legacy_worker.queue_depth = 0
        legacy_worker.connected_at = None
        legacy_worker.last_error_code = "M63_HELIUS_CREDIT_CONTAINMENT"
        legacy_worker.last_error_message = "Legacy Enhanced stream disabilitato."

    if copy_worker is not None:
        copy_worker.enabled = True
        copy_worker.lease_owner = None
        copy_worker.lease_expires_at = None
        metadata = dict(copy_worker.technical_metadata or {})
        metadata["m63_containment_applied_at"] = observed.isoformat()
        metadata["m63_target_campaign_id"] = target.campaign_id
        copy_worker.technical_metadata = metadata

    db.flush()
    if target.status != "ACTIVE" or int(target.closed_trade_count or 0) != target_closed_before:
        raise M63HeliusContainmentError(
            "Invariante target violata durante il contenimento."
        )

    return {
        "status": "APPLIED",
        "target_wallet": target_wallet,
        "target_campaign_id": target.campaign_id,
        "target_closed_trade_count": target_closed_before,
        "paused_campaign_ids": paused_campaign_ids,
        "disabled_forward_feed_state_ids": disabled_forward_state_ids,
        "legacy_stream_execution_enabled": False,
        "legacy_worker_status": (
            legacy_worker.status if legacy_worker is not None else "NOT_PRESENT"
        ),
        "copyability_worker_enabled": (
            bool(copy_worker.enabled) if copy_worker is not None else None
        ),
        "history_preserved": True,
        "rows_deleted": 0,
        "helius_requests": 0,
    }
