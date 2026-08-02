from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.gen4_forward_shadow import (
    CanonicalParserGen4ForwardCampaign,
    CanonicalParserGen4ForwardCycle,
    CanonicalParserGen4ForwardDecision,
)
from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
from backend.app.models.trade import Trade
from backend.app.models.wallet_edge import WalletEdge
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
from backend.app.services.blockchain_parser_gen4_profitability_service import (
    _actor,
    _components,
    _load_trades,
    _note,
    _policy_snapshot,
    _price,
    _price_ratio,
    _proxy_qualified_wallets,
    _round,
    _valid_price_points,
)

GEN4_FORWARD_SCOPE = "GEN4_STRICT_FORWARD_SHADOW"
GEN4_FORWARD_POLICY_VERSION = "canonical-parser-gen4-strict-forward-shadow/1"
GEN4_FORWARD_START_CONFIRMATION = "START_GEN4_STRICT_FORWARD_SHADOW"
GEN4_FORWARD_CYCLE_CONFIRMATION = "RUN_GEN4_STRICT_FORWARD_CYCLE"
GEN4_FORWARD_STOP_CONFIRMATION = "STOP_GEN4_STRICT_FORWARD_SHADOW"

LANE_STRICT_FORWARD = "STRICT_GEN4_FORWARD"
LANE_PROXY_FORWARD = "SIGNAL_ONLY_FORWARD"
LANE_BASELINE_FORWARD = "SIMPLE_COPY_FORWARD_BASELINE"

STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
VERDICT_COLLECTING = "COLLECTING"
VERDICT_NOT_EVALUABLE = "NOT_EVALUABLE"
VERDICT_NEGATIVE = "NEGATIVE_EVIDENCE"
VERDICT_PROMISING = "PROMISING_NOT_PROVEN"
VERDICT_PROFITABLE = "PROFITABLE_EVIDENCE"


class CanonicalParserGen4ForwardShadowError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ForwardPricePoint:
    trade_id: int
    signature: str
    wallet_address: str
    token_mint: str
    side: str
    occurred_at: datetime
    available_at: datetime
    price_sol: float
    ingestion_lag_seconds: float


@dataclass(frozen=True)
class ForwardSignal:
    lane: str
    token_mint: str
    signal_at: datetime
    signal_observed_at: datetime
    decision_at: datetime
    contributing_wallets: tuple[str, ...]
    independent_cluster_count: int
    source_trade_ids: tuple[int, ...]
    source_signatures: tuple[str, ...]
    signal_hash: str
    evidence: dict[str, Any]
    waiting_safety: bool = False
    rejection_reason: str | None = None


@dataclass(frozen=True)
class ForwardOutcome:
    signal: ForwardSignal
    status: str
    entry_at: datetime | None
    exit_at: datetime | None
    entry_price_sol: float | None
    exit_price_sol: float | None
    order_size_sol: float
    pnl_sol: float | None
    return_percent: float | None
    exit_reason: str | None
    rejection_reason: str | None
    evidence: dict[str, Any]
    portfolio_accepted: bool = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return _utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _forward_safety_contract() -> dict[str, Any]:
    return {
        "scope": GEN4_FORWARD_SCOPE,
        "metadata_writes_only": True,
        "source_tables_read_only": [
            "trades",
            "wallet_edges",
            "token_safety_snapshots",
        ],
        "external_requests": 0,
        "helius_requests": 0,
        "jupiter_requests": 0,
        "paper_orders_created": 0,
        "paper_positions_created": 0,
        "live_orders_created": 0,
        "transactions_built": 0,
        "transactions_signed": 0,
        "transactions_sent": 0,
        "worker_started": False,
        "scheduler_started": False,
        "stream_started": False,
        "signer_connected": False,
        "live_execution_authorized": False,
    }


def _forward_policy_snapshot(settings_object: Any) -> dict[str, Any]:
    base = _policy_snapshot(settings_object)
    minimum_closed = int(
        getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_MIN_CLOSED_TRADES", 30)
    )
    proof_closed = max(
        minimum_closed,
        int(getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_PROOF_CLOSED_TRADES", 100)),
    )
    return {
        "policy_version": GEN4_FORWARD_POLICY_VERSION,
        "scope": GEN4_FORWARD_SCOPE,
        "gen4_profitability_policy": base,
        "training_days": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_TRAINING_DAYS", 14)
        ),
        "minimum_frozen_wallets": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_MIN_FROZEN_WALLETS", 2)
        ),
        "maximum_frozen_wallets": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_MAX_FROZEN_WALLETS", 20)
        ),
        "minimum_observation_days": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_MIN_OBSERVATION_DAYS", 21)
        ),
        "minimum_closed_trades": minimum_closed,
        "proof_closed_trades": proof_closed,
        "maximum_source_trades_per_cycle": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_GEN4_FORWARD_MAX_SOURCE_TRADES_PER_CYCLE",
                200000,
            )
        ),
        "maximum_ingestion_lag_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_GEN4_FORWARD_MAX_INGESTION_LAG_SECONDS",
                300,
            )
        ),
        "maximum_safety_wait_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_GEN4_FORWARD_MAX_SAFETY_WAIT_MINUTES",
                30,
            )
        ),
        "availability_clock": "trades.created_at",
        "market_clock": "trades.block_time",
        "historical_backfill_after_anchor_allowed": False,
        "closed_decision_immutability": True,
        "manual_cycle_only": True,
        "external_requests_allowed": False,
        "paper_execution_connected": False,
        "live_execution_authorized": False,
        "worker_connected": False,
        "scheduler_connected": False,
        "stream_connected": False,
        "signer_connected": False,
        "transaction_submission_connected": False,
    }


def _wallet_score(metrics: dict[str, Any]) -> float:
    return (
        float(metrics.get("closed_positions") or 0) * 3.0
        + min(float(metrics.get("return_percent") or 0.0), 500.0)
        + min(float(metrics.get("profit_factor") or 0.0), 20.0) * 10.0
        + float(metrics.get("win_rate_percent") or 0.0) * 0.5
        - float(metrics.get("max_drawdown_percent") or 0.0)
        - float(metrics.get("open_positions") or 0) * 5.0
    )


def _training_snapshot(
    db: Session,
    *,
    anchor_at: datetime,
    candidate_wallets: Iterable[str] | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    base_policy = policy["gen4_profitability_policy"]
    training_start = anchor_at - timedelta(days=int(policy["training_days"]))
    trades = _load_trades(
        db,
        start_at=training_start,
        end_at=anchor_at,
        max_source_trades=int(base_policy["max_source_trades"]),
    )
    points, price_audit = _valid_price_points(trades, policy=base_policy)
    qualified, metrics_by_wallet = _proxy_qualified_wallets(
        points,
        train_start=training_start,
        train_end=anchor_at,
        policy=base_policy,
    )

    requested = {
        str(wallet).strip()
        for wallet in (candidate_wallets or [])
        if str(wallet).strip()
    }
    if requested:
        eligible = qualified & requested
        missing_requested = sorted(requested - set(metrics_by_wallet))
        rejected_requested = sorted((requested & set(metrics_by_wallet)) - qualified)
    else:
        eligible = set(qualified)
        missing_requested = []
        rejected_requested = []

    ranked = sorted(
        eligible,
        key=lambda wallet: (
            -_wallet_score(metrics_by_wallet[wallet]),
            wallet,
        ),
    )[: int(policy["maximum_frozen_wallets"])]

    edges = list(db.scalars(select(WalletEdge)))
    components = _components(
        set(ranked),
        edges,
        at=anchor_at,
        minimum_strength=float(base_policy["minimum_edge_strength"]),
    )
    component_count = len(set(components.values())) if components else len(ranked)

    selected_metrics = {
        wallet: {
            **metrics_by_wallet[wallet],
            "selection_score": _round(_wallet_score(metrics_by_wallet[wallet]), 4),
            "cluster_key": components.get(wallet),
        }
        for wallet in ranked
    }
    all_reason_counts: dict[str, int] = defaultdict(int)
    for metrics in metrics_by_wallet.values():
        for reason in metrics.get("reason_codes", []):
            all_reason_counts[str(reason)] += 1

    return {
        "anchor_at": anchor_at.isoformat(),
        "training_start_at": training_start.isoformat(),
        "training_end_at": anchor_at.isoformat(),
        "source_trade_count": len(trades),
        "accepted_price_point_count": len(points),
        "price_integrity_audit": price_audit,
        "evaluated_wallet_count": len(metrics_by_wallet),
        "qualified_wallet_count": len(qualified),
        "selected_wallet_count": len(ranked),
        "selected_wallets": ranked,
        "selected_wallet_metrics": selected_metrics,
        "independent_cluster_count": component_count,
        "requested_wallets": sorted(requested),
        "missing_requested_wallets": missing_requested,
        "rejected_requested_wallets": rejected_requested,
        "training_gate_reason_counts": dict(sorted(all_reason_counts.items())),
        "minimum_frozen_wallets": int(policy["minimum_frozen_wallets"]),
        "ready": (
            len(ranked) >= int(policy["minimum_frozen_wallets"])
            and component_count >= int(base_policy["minimum_independent_clusters"])
        ),
    }


def preview_gen4_forward_campaign(
    db: Session,
    *,
    candidate_wallets: Iterable[str] | None = None,
    anchor_at: datetime | None = None,
    settings_object: Any = settings,
) -> dict[str, Any]:
    anchor = _aware(anchor_at)
    policy = _forward_policy_snapshot(settings_object)
    training = _training_snapshot(
        db,
        anchor_at=anchor,
        candidate_wallets=candidate_wallets,
        policy=policy,
    )
    active = db.scalar(
        select(CanonicalParserGen4ForwardCampaign)
        .where(CanonicalParserGen4ForwardCampaign.status == STATUS_ACTIVE)
        .order_by(desc(CanonicalParserGen4ForwardCampaign.id))
        .limit(1)
    )
    reason_codes: list[str] = []
    if active is not None:
        reason_codes.append("ACTIVE_FORWARD_CAMPAIGN_ALREADY_EXISTS")
    if training["selected_wallet_count"] < int(policy["minimum_frozen_wallets"]):
        reason_codes.append("QUALIFIED_FROZEN_WALLETS_BELOW_MINIMUM")
    if training["independent_cluster_count"] < int(
        policy["gen4_profitability_policy"]["minimum_independent_clusters"]
    ):
        reason_codes.append("FROZEN_WALLET_CLUSTERS_BELOW_MINIMUM")
    return {
        "scope": GEN4_FORWARD_SCOPE,
        "policy_version": GEN4_FORWARD_POLICY_VERSION,
        "policy_hash": calculate_payload_hash(policy),
        "policy": policy,
        "training_snapshot": training,
        "ready": not reason_codes,
        "reason_codes": reason_codes,
        "active_campaign_id": None if active is None else active.campaign_id,
        "confirmation_required": GEN4_FORWARD_START_CONFIRMATION,
        "writes_performed": False,
        "safety": _forward_safety_contract(),
    }


def _campaign_evidence_payload(campaign: CanonicalParserGen4ForwardCampaign) -> dict[str, Any]:
    return {
        "campaign_id": campaign.campaign_id,
        "status": campaign.status,
        "verdict": campaign.verdict,
        "strict_evidence_status": campaign.strict_evidence_status,
        "policy_hash": campaign.policy_hash,
        "frozen_wallets": list(campaign.frozen_wallets or []),
        "anchor_at": _aware(campaign.anchor_at).isoformat(),
        "latest_observed_at": _aware(campaign.latest_observed_at).isoformat(),
        "counts": {
            "cycle_count": campaign.cycle_count,
            "decision_count": campaign.decision_count,
            "strict_signal_count": campaign.strict_signal_count,
            "proxy_signal_count": campaign.proxy_signal_count,
            "baseline_signal_count": campaign.baseline_signal_count,
            "strict_closed_trade_count": campaign.strict_closed_trade_count,
            "proxy_closed_trade_count": campaign.proxy_closed_trade_count,
            "baseline_closed_trade_count": campaign.baseline_closed_trade_count,
            "rejected_decision_count": campaign.rejected_decision_count,
        },
        "strict_metrics": campaign.strict_metrics,
        "proxy_metrics": campaign.proxy_metrics,
        "baseline_metrics": campaign.baseline_metrics,
        "evidence_gaps": campaign.evidence_gaps,
    }


def start_gen4_forward_campaign(
    db: Session,
    *,
    confirmation: str,
    candidate_wallets: Iterable[str] | None = None,
    anchor_at: datetime | None = None,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_ENABLED", False)):
        raise CanonicalParserGen4ForwardShadowError(
            "M52-M53 Gen4 Strict Forward Shadow è disabilitato.",
            code="GEN4_FORWARD_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != GEN4_FORWARD_START_CONFIRMATION:
        raise CanonicalParserGen4ForwardShadowError(
            f"Conferma richiesta: {GEN4_FORWARD_START_CONFIRMATION}",
            code="GEN4_FORWARD_START_CONFIRMATION_REQUIRED",
        )

    preview = preview_gen4_forward_campaign(
        db,
        candidate_wallets=candidate_wallets,
        anchor_at=anchor_at,
        settings_object=settings_object,
    )
    if not preview["ready"]:
        raise CanonicalParserGen4ForwardShadowError(
            "Campagna forward non avviabile: " + ", ".join(preview["reason_codes"]),
            code="GEN4_FORWARD_NOT_READY",
            status_code=409,
        )

    policy = preview["policy"]
    training = preview["training_snapshot"]
    anchor = datetime.fromisoformat(training["anchor_at"])
    campaign_key = calculate_payload_hash(
        {
            "scope": GEN4_FORWARD_SCOPE,
            "policy_hash": preview["policy_hash"],
            "anchor_at": anchor.isoformat(),
            "frozen_wallets": training["selected_wallets"],
        }
    )
    existing = db.scalar(
        select(CanonicalParserGen4ForwardCampaign).where(
            CanonicalParserGen4ForwardCampaign.campaign_key == campaign_key
        )
    )
    if existing is not None:
        return _serialize_campaign(db, existing) | {"idempotent_replay": True}

    minimum_complete_at = anchor + timedelta(days=int(policy["minimum_observation_days"]))
    campaign = CanonicalParserGen4ForwardCampaign(
        campaign_id=str(uuid4()),
        campaign_key=campaign_key,
        scope=GEN4_FORWARD_SCOPE,
        status=STATUS_ACTIVE,
        verdict=VERDICT_COLLECTING,
        strict_evidence_status="COLLECTING",
        policy_version=GEN4_FORWARD_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=policy,
        frozen_wallets=training["selected_wallets"],
        frozen_wallet_metrics=training["selected_wallet_metrics"],
        frozen_wallet_count=training["selected_wallet_count"],
        anchor_at=anchor,
        minimum_complete_at=minimum_complete_at,
        latest_observed_at=anchor,
        started_at=anchor,
        completed_at=None,
        minimum_observation_days=int(policy["minimum_observation_days"]),
        minimum_closed_trades=int(policy["minimum_closed_trades"]),
        proof_closed_trades=int(policy["proof_closed_trades"]),
        cycle_count=0,
        decision_count=0,
        strict_signal_count=0,
        proxy_signal_count=0,
        baseline_signal_count=0,
        strict_closed_trade_count=0,
        proxy_closed_trade_count=0,
        baseline_closed_trade_count=0,
        rejected_decision_count=0,
        strict_metrics=_empty_lane_metrics(),
        proxy_metrics=_empty_lane_metrics(),
        baseline_metrics=_empty_lane_metrics(),
        evidence_gaps=[
            "FORWARD_MINIMUM_OBSERVATION_PERIOD_NOT_REACHED",
            "STRICT_FORWARD_CLOSED_SAMPLE_BELOW_MINIMUM",
        ],
        safety=_forward_safety_contract(),
        evidence_hash="0" * 64,
        actor_label=_actor(actor_label),
        note=_note(note),
        technical_metadata={
            "training_snapshot": training,
            "point_in_time_guard": True,
            "historical_backfill_after_anchor_allowed": False,
            "external_requests": 0,
            "live_execution_authorized": False,
        },
    )
    db.add(campaign)
    try:
        db.flush()
        campaign.evidence_hash = calculate_payload_hash(_campaign_evidence_payload(campaign))
        db.flush()
    except IntegrityError as exception:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserGen4ForwardCampaign).where(
                CanonicalParserGen4ForwardCampaign.campaign_key == campaign_key
            )
        )
        if existing is not None:
            return _serialize_campaign(db, existing) | {"idempotent_replay": True}
        raise CanonicalParserGen4ForwardShadowError(
            "Impossibile persistere la campagna forward.",
            code="GEN4_FORWARD_PERSISTENCE_CONFLICT",
            status_code=409,
        ) from exception
    return _serialize_campaign(db, campaign) | {"idempotent_replay": False}


def _load_forward_trades(
    db: Session,
    *,
    anchor_at: datetime,
    observed_at: datetime,
    max_source_trades: int,
) -> list[Trade]:
    return list(
        db.scalars(
            select(Trade)
            .where(
                Trade.success.is_(True),
                Trade.block_time.isnot(None),
                Trade.created_at.isnot(None),
                Trade.block_time >= anchor_at,
                Trade.block_time <= observed_at,
                Trade.created_at >= anchor_at,
                Trade.created_at <= observed_at,
            )
            .order_by(Trade.created_at.asc(), Trade.block_time.asc(), Trade.id.asc())
            .limit(max_source_trades)
        )
    )


def _forward_price_points(
    trades: Iterable[Trade],
    *,
    policy: dict[str, Any],
) -> tuple[list[ForwardPricePoint], dict[str, Any]]:
    base_policy = policy["gen4_profitability_policy"]
    excluded = set(base_policy["excluded_price_mints"])
    max_lag = int(policy["maximum_ingestion_lag_seconds"])
    raw_by_token: dict[str, list[ForwardPricePoint]] = defaultdict(list)
    audit: dict[str, Any] = {
        "source_trade_count": 0,
        "accepted_price_point_count": 0,
        "excluded_quote_asset_count": 0,
        "invalid_amount_count": 0,
        "unsupported_side_count": 0,
        "missing_token_count": 0,
        "availability_before_block_count": 0,
        "ingestion_lag_rejected_count": 0,
        "price_discontinuity_rejected_count": 0,
        "price_discontinuity_rejected_trade_ids": [],
    }
    for trade in trades:
        audit["source_trade_count"] += 1
        token = str(trade.token_mint or "").strip()
        side = str(trade.side or "").strip().upper()
        if not token:
            audit["missing_token_count"] += 1
            continue
        if token in excluded:
            audit["excluded_quote_asset_count"] += 1
            continue
        if side not in {"BUY", "SELL"}:
            audit["unsupported_side_count"] += 1
            continue
        price = _price(trade)
        if price is None:
            audit["invalid_amount_count"] += 1
            continue
        occurred = _aware(trade.block_time)
        available = _aware(trade.created_at)
        lag = (available - occurred).total_seconds()
        if lag < -60:
            audit["availability_before_block_count"] += 1
            continue
        lag = max(0.0, lag)
        if lag > max_lag:
            audit["ingestion_lag_rejected_count"] += 1
            continue
        raw_by_token[token].append(
            ForwardPricePoint(
                trade_id=int(trade.id),
                signature=str(trade.signature),
                wallet_address=str(trade.wallet_address),
                token_mint=token,
                side=side,
                occurred_at=occurred,
                available_at=available,
                price_sol=float(price),
                ingestion_lag_seconds=lag,
            )
        )

    accepted: list[ForwardPricePoint] = []
    continuity_seconds = int(base_policy["price_continuity_window_seconds"])
    maximum_ratio = float(base_policy["maximum_price_discontinuity_ratio"])
    for token in sorted(raw_by_token):
        recent: deque[ForwardPricePoint] = deque()
        for point in sorted(
            raw_by_token[token],
            key=lambda item: (item.occurred_at, item.available_at, item.trade_id),
        ):
            cutoff = point.occurred_at - timedelta(seconds=continuity_seconds)
            while recent and recent[0].occurred_at < cutoff:
                recent.popleft()
            if recent:
                reference = median(item.price_sol for item in recent)
                if _price_ratio(point.price_sol, reference) > maximum_ratio:
                    audit["price_discontinuity_rejected_count"] += 1
                    if len(audit["price_discontinuity_rejected_trade_ids"]) < 50:
                        audit["price_discontinuity_rejected_trade_ids"].append(point.trade_id)
                    continue
            accepted.append(point)
            recent.append(point)
    accepted.sort(key=lambda item: (item.available_at, item.occurred_at, item.trade_id))
    audit["accepted_price_point_count"] = len(accepted)
    return accepted, audit


def _signal_hash(
    *,
    token_mint: str,
    source_trade_ids: Iterable[int],
    contributing_wallets: Iterable[str],
) -> str:
    return calculate_payload_hash(
        {
            "token_mint": token_mint,
            "source_trade_ids": sorted(int(item) for item in source_trade_ids),
            "contributing_wallets": sorted(str(item) for item in contributing_wallets),
        }
    )


def _build_proxy_signals(
    points: list[ForwardPricePoint],
    *,
    frozen_wallets: set[str],
    edges: list[WalletEdge],
    policy: dict[str, Any],
) -> list[ForwardSignal]:
    base_policy = policy["gen4_profitability_policy"]
    buys_by_token: dict[str, list[ForwardPricePoint]] = defaultdict(list)
    for point in points:
        if point.side == "BUY" and point.wallet_address in frozen_wallets:
            buys_by_token[point.token_mint].append(point)

    signals: list[ForwardSignal] = []
    window_seconds = int(base_policy["consensus_window_seconds"])
    minimum_wallets = int(base_policy["minimum_qualified_wallets"])
    minimum_clusters = int(base_policy["minimum_independent_clusters"])
    for token in sorted(buys_by_token):
        rows = sorted(
            buys_by_token[token],
            key=lambda item: (item.occurred_at, item.available_at, item.trade_id),
        )
        left = 0
        right = 0
        while right < len(rows):
            while (
                left <= right
                and (rows[right].occurred_at - rows[left].occurred_at).total_seconds()
                > window_seconds
            ):
                left += 1
            current = rows[left : right + 1]
            first_by_wallet: dict[str, ForwardPricePoint] = {}
            for row in current:
                first_by_wallet.setdefault(row.wallet_address, row)
            if len(first_by_wallet) < minimum_wallets:
                right += 1
                continue
            selected = sorted(
                first_by_wallet.values(),
                key=lambda item: (item.occurred_at, item.available_at, item.trade_id),
            )
            wallets = set(first_by_wallet)
            signal_at = max(item.occurred_at for item in selected)
            observed_at = max(item.available_at for item in selected)
            mapping = _components(
                wallets,
                edges,
                at=observed_at,
                minimum_strength=float(base_policy["minimum_edge_strength"]),
            )
            clusters = len(set(mapping.values()))
            if clusters < minimum_clusters:
                right += 1
                continue
            source_ids = tuple(item.trade_id for item in selected)
            source_signatures = tuple(item.signature for item in selected)
            signal_hash = _signal_hash(
                token_mint=token,
                source_trade_ids=source_ids,
                contributing_wallets=wallets,
            )
            signals.append(
                ForwardSignal(
                    lane=LANE_PROXY_FORWARD,
                    token_mint=token,
                    signal_at=signal_at,
                    signal_observed_at=observed_at,
                    decision_at=observed_at,
                    contributing_wallets=tuple(sorted(wallets)),
                    independent_cluster_count=clusters,
                    source_trade_ids=source_ids,
                    source_signatures=source_signatures,
                    signal_hash=signal_hash,
                    evidence={
                        "point_in_time_guard": True,
                        "market_clock": "block_time",
                        "availability_clock": "created_at",
                        "wallet_count": len(wallets),
                        "independent_cluster_count": clusters,
                        "maximum_source_ingestion_lag_seconds": _round(
                            max(item.ingestion_lag_seconds for item in selected), 4
                        ),
                    },
                )
            )
            next_at = signal_at + timedelta(seconds=window_seconds)
            right += 1
            while right < len(rows) and rows[right].occurred_at <= next_at:
                right += 1
            left = right
    return signals


def _build_baseline_signals(
    points: list[ForwardPricePoint],
    *,
    frozen_wallets: set[str],
) -> list[ForwardSignal]:
    signals: list[ForwardSignal] = []
    for point in points:
        if point.side != "BUY" or point.wallet_address not in frozen_wallets:
            continue
        signal_hash = _signal_hash(
            token_mint=point.token_mint,
            source_trade_ids=[point.trade_id],
            contributing_wallets=[point.wallet_address],
        )
        signals.append(
            ForwardSignal(
                lane=LANE_BASELINE_FORWARD,
                token_mint=point.token_mint,
                signal_at=point.occurred_at,
                signal_observed_at=point.available_at,
                decision_at=point.available_at,
                contributing_wallets=(point.wallet_address,),
                independent_cluster_count=1,
                source_trade_ids=(point.trade_id,),
                source_signatures=(point.signature,),
                signal_hash=signal_hash,
                evidence={
                    "point_in_time_guard": True,
                    "baseline": "FIRST_AVAILABLE_FROZEN_WALLET_BUY",
                    "source_ingestion_lag_seconds": _round(point.ingestion_lag_seconds, 4),
                },
            )
        )
    return signals


def _strict_signal(
    proxy: ForwardSignal,
    *,
    snapshot: TokenSafetySnapshot | None,
    observed_at: datetime,
    policy: dict[str, Any],
) -> ForwardSignal:
    base_policy = policy["gen4_profitability_policy"]
    maximum_wait = timedelta(minutes=int(policy["maximum_safety_wait_minutes"]))
    wait_deadline = proxy.signal_observed_at + maximum_wait
    if snapshot is None:
        waiting = observed_at < wait_deadline
        return ForwardSignal(
            **{
                **proxy.__dict__,
                "lane": LANE_STRICT_FORWARD,
                "waiting_safety": waiting,
                "rejection_reason": None if waiting else "POINT_IN_TIME_TOKEN_SAFETY_MISSING",
                "evidence": {
                    **proxy.evidence,
                    "token_safety": None,
                    "safety_wait_deadline": wait_deadline.isoformat(),
                },
            }
        )

    fetched_at = _aware(snapshot.fetched_at)
    created_at = _aware(snapshot.created_at)
    if fetched_at > observed_at or created_at > observed_at:
        return ForwardSignal(
            **{
                **proxy.__dict__,
                "lane": LANE_STRICT_FORWARD,
                "waiting_safety": observed_at < wait_deadline,
                "rejection_reason": (
                    None
                    if observed_at < wait_deadline
                    else "POINT_IN_TIME_TOKEN_SAFETY_NOT_AVAILABLE"
                ),
                "evidence": {
                    **proxy.evidence,
                    "token_safety": {
                        "fetched_at": fetched_at.isoformat(),
                        "created_at": created_at.isoformat(),
                        "available_by_observed_at": False,
                    },
                },
            }
        )
    decision_at = max(proxy.signal_observed_at, fetched_at, created_at)
    if decision_at > wait_deadline:
        return ForwardSignal(
            **{
                **proxy.__dict__,
                "lane": LANE_STRICT_FORWARD,
                "decision_at": decision_at,
                "rejection_reason": "TOKEN_SAFETY_ARRIVED_AFTER_MAXIMUM_WAIT",
                "evidence": {
                    **proxy.evidence,
                    "token_safety": {
                        "fetched_at": fetched_at.isoformat(),
                        "created_at": created_at.isoformat(),
                        "wait_deadline": wait_deadline.isoformat(),
                    },
                },
            }
        )

    reasons: list[str] = []
    age_minutes = max(0.0, (decision_at - fetched_at).total_seconds() / 60.0)
    if age_minutes > int(base_policy["token_snapshot_max_age_minutes"]):
        reasons.append("POINT_IN_TIME_TOKEN_SAFETY_EXPIRED")
    if bool(snapshot.honeypot):
        reasons.append("TOKEN_HONEYPOT")
    if bool(snapshot.mint_authority_enabled):
        reasons.append("TOKEN_MINT_AUTHORITY_ENABLED")
    if bool(snapshot.freeze_authority_enabled):
        reasons.append("TOKEN_FREEZE_AUTHORITY_ENABLED")
    if snapshot.rugged is True:
        reasons.append("TOKEN_RUGGED")
    if snapshot.rugcheck_passed is not True:
        reasons.append("TOKEN_RUGCHECK_NOT_PASSED")
    if float(snapshot.liquidity_usd or 0) < float(base_policy["minimum_token_liquidity_usd"]):
        reasons.append("TOKEN_LIQUIDITY_BELOW_MINIMUM")
    if int(snapshot.risk_score or 100) > int(base_policy["maximum_token_risk_score"]):
        reasons.append("TOKEN_RISK_SCORE_ABOVE_MAXIMUM")
    if float(snapshot.top_holder_percent or 100) > float(
        base_policy["maximum_top_holder_percent"]
    ):
        reasons.append("TOKEN_HOLDER_CONCENTRATION_ABOVE_MAXIMUM")

    return ForwardSignal(
        **{
            **proxy.__dict__,
            "lane": LANE_STRICT_FORWARD,
            "decision_at": decision_at,
            "rejection_reason": reasons[0] if reasons else None,
            "evidence": {
                **proxy.evidence,
                "token_safety": {
                    "fetched_at": fetched_at.isoformat(),
                    "created_at": created_at.isoformat(),
                    "decision_at": decision_at.isoformat(),
                    "age_minutes": _round(age_minutes, 4),
                    "liquidity_usd": _round(snapshot.liquidity_usd, 2),
                    "risk_score": int(snapshot.risk_score or 0),
                    "top_holder_percent": _round(snapshot.top_holder_percent, 4),
                    "safe": not reasons,
                    "reason_codes": reasons,
                },
            },
        }
    )


def _simulate_forward_signal(
    signal: ForwardSignal,
    *,
    token_points: list[ForwardPricePoint],
    observed_at: datetime,
    policy: dict[str, Any],
) -> ForwardOutcome:
    base = policy["gen4_profitability_policy"]
    order_size = float(base["order_size_sol"])
    if signal.waiting_safety:
        return ForwardOutcome(
            signal=signal,
            status="WAITING_SAFETY",
            entry_at=None,
            exit_at=None,
            entry_price_sol=None,
            exit_price_sol=None,
            order_size_sol=order_size,
            pnl_sol=None,
            return_percent=None,
            exit_reason=None,
            rejection_reason=None,
            evidence=signal.evidence,
        )
    if signal.rejection_reason:
        return ForwardOutcome(
            signal=signal,
            status="REJECTED",
            entry_at=None,
            exit_at=None,
            entry_price_sol=None,
            exit_price_sol=None,
            order_size_sol=order_size,
            pnl_sol=None,
            return_percent=None,
            exit_reason=None,
            rejection_reason=signal.rejection_reason,
            evidence=signal.evidence,
        )

    target_at = signal.decision_at + timedelta(seconds=int(base["copy_delay_seconds"]))
    max_entry_at = signal.decision_at + timedelta(
        seconds=int(base["maximum_execution_lag_seconds"])
    )
    entry_point = next(
        (
            point
            for point in token_points
            if point.available_at >= target_at
            and point.available_at <= max_entry_at
            and point.occurred_at >= signal.signal_at
        ),
        None,
    )
    evidence = {
        **signal.evidence,
        "signal_at": signal.signal_at.isoformat(),
        "signal_observed_at": signal.signal_observed_at.isoformat(),
        "decision_at": signal.decision_at.isoformat(),
        "entry_target_at": target_at.isoformat(),
        "maximum_entry_at": max_entry_at.isoformat(),
        "price_integrity_version": base["price_integrity_version"],
        "threshold_fill_enforced": True,
    }
    if entry_point is None:
        status = "PENDING_ENTRY" if observed_at <= max_entry_at else "EXPIRED"
        return ForwardOutcome(
            signal=signal,
            status=status,
            entry_at=None,
            exit_at=None,
            entry_price_sol=None,
            exit_price_sol=None,
            order_size_sol=order_size,
            pnl_sol=None,
            return_percent=None,
            exit_reason=None if status == "PENDING_ENTRY" else "NO_EXECUTION_PRICE",
            rejection_reason=None,
            evidence=evidence,
        )

    fee_ratio = float(base["fee_bps"]) / 10000.0
    friction_ratio = float(base["slippage_bps"]) / 10000.0
    entry_price = entry_point.price_sol * (1.0 + friction_ratio)
    quantity = order_size * max(0.0, 1.0 - fee_ratio) / entry_price
    entry_at = entry_point.available_at
    deadline = entry_at + timedelta(minutes=int(base["maximum_hold_minutes"]))
    stop_price = entry_price * (1.0 - float(base["stop_loss_percent"]) / 100.0)
    take_price = entry_price * (1.0 + float(base["take_profit_percent"]) / 100.0)
    maximum_ratio = float(base["maximum_price_discontinuity_ratio"])
    source_wallets = set(signal.contributing_wallets)

    exit_point: ForwardPricePoint | None = None
    exit_reason: str | None = None
    exit_reference_price: float | None = None
    last_before_deadline: ForwardPricePoint | None = None
    rejected_discontinuities = 0
    min_return = 0.0
    max_return = 0.0

    for point in token_points:
        if point.available_at <= entry_at:
            continue
        if point.available_at > observed_at:
            break
        if point.available_at > deadline:
            break
        if _price_ratio(point.price_sol, entry_point.price_sol) > maximum_ratio:
            rejected_discontinuities += 1
            continue
        last_before_deadline = point
        observed_return = (point.price_sol / entry_price - 1.0) * 100.0
        min_return = min(min_return, observed_return)
        max_return = max(max_return, observed_return)
        if point.price_sol <= stop_price:
            exit_point = point
            exit_reason = "STOP_LOSS"
            exit_reference_price = stop_price
            break
        if point.price_sol >= take_price:
            exit_point = point
            exit_reason = "TAKE_PROFIT"
            exit_reference_price = take_price
            break
        if point.side == "SELL" and point.wallet_address in source_wallets:
            exit_point = point
            exit_reason = "SOURCE_WALLET_SELL"
            exit_reference_price = point.price_sol
            break

    if exit_point is None and observed_at >= deadline and last_before_deadline is not None:
        exit_point = last_before_deadline
        exit_reason = "MAX_HOLD_OBSERVED_PRICE"
        exit_reference_price = last_before_deadline.price_sol

    evidence = {
        **evidence,
        "entry_source_trade_id": entry_point.trade_id,
        "entry_signature": entry_point.signature,
        "entry_source_block_at": entry_point.occurred_at.isoformat(),
        "entry_available_at": entry_point.available_at.isoformat(),
        "entry_ingestion_lag_seconds": _round(entry_point.ingestion_lag_seconds, 4),
        "deadline_at": deadline.isoformat(),
        "minimum_observed_return_percent": _round(min_return, 4),
        "maximum_observed_return_percent": _round(max_return, 4),
        "price_discontinuity_rejected_points": rejected_discontinuities,
    }
    if exit_point is None or exit_reference_price is None:
        return ForwardOutcome(
            signal=signal,
            status="OPEN",
            entry_at=entry_at,
            exit_at=None,
            entry_price_sol=_round(entry_price, 18),
            exit_price_sol=None,
            order_size_sol=order_size,
            pnl_sol=None,
            return_percent=None,
            exit_reason=None,
            rejection_reason=None,
            evidence=evidence,
        )

    exit_price = exit_reference_price * max(0.0, 1.0 - friction_ratio)
    proceeds = quantity * exit_price * max(0.0, 1.0 - fee_ratio)
    pnl = proceeds - order_size
    return_percent = pnl / order_size * 100.0 if order_size > 0 else 0.0
    evidence.update(
        {
            "exit_source_trade_id": exit_point.trade_id,
            "exit_signature": exit_point.signature,
            "exit_source_block_at": exit_point.occurred_at.isoformat(),
            "exit_available_at": exit_point.available_at.isoformat(),
            "exit_trigger_observed_price_sol": _round(exit_point.price_sol, 18),
            "exit_execution_reference_price_sol": _round(exit_reference_price, 18),
            "threshold_fill_applied": exit_reason in {"STOP_LOSS", "TAKE_PROFIT"},
        }
    )
    return ForwardOutcome(
        signal=signal,
        status="CLOSED",
        entry_at=entry_at,
        exit_at=exit_point.available_at,
        entry_price_sol=_round(entry_price, 18),
        exit_price_sol=_round(exit_price, 18),
        order_size_sol=order_size,
        pnl_sol=_round(pnl),
        return_percent=_round(return_percent, 4),
        exit_reason=exit_reason,
        rejection_reason=None,
        evidence=evidence,
    )


def _apply_portfolio(
    outcomes: list[ForwardOutcome],
    *,
    observed_at: datetime,
    policy: dict[str, Any],
) -> tuple[list[ForwardOutcome], dict[str, Any]]:
    base = policy["gen4_profitability_policy"]
    starting_capital = float(base["starting_capital_sol"])
    order_size = float(base["order_size_sol"])
    max_open = int(base["maximum_open_positions"])
    cash = starting_capital
    active: list[ForwardOutcome] = []
    active_tokens: set[str] = set()
    accepted: list[ForwardOutcome] = []
    final: list[ForwardOutcome] = []
    realized_equity = starting_capital
    peak = starting_capital
    max_drawdown = 0.0
    portfolio_rejections: dict[str, int] = defaultdict(int)

    def close_due(until: datetime) -> None:
        nonlocal cash, realized_equity, peak, max_drawdown
        due = sorted(
            [item for item in active if item.exit_at is not None and item.exit_at <= until],
            key=lambda item: item.exit_at or until,
        )
        for item in due:
            cash += order_size + float(item.pnl_sol or 0.0)
            realized_equity += float(item.pnl_sol or 0.0)
            peak = max(peak, realized_equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - realized_equity) / peak * 100.0)
            active.remove(item)
            active_tokens.discard(item.signal.token_mint)

    for outcome in sorted(
        outcomes,
        key=lambda item: (
            item.entry_at or item.signal.decision_at,
            item.signal.token_mint,
            item.signal.signal_hash,
        ),
    ):
        if outcome.entry_at is None or outcome.status in {"WAITING_SAFETY", "REJECTED", "EXPIRED", "PENDING_ENTRY"}:
            final.append(outcome)
            continue
        close_due(outcome.entry_at)
        reason: str | None = None
        if outcome.signal.token_mint in active_tokens:
            reason = "TOKEN_POSITION_ALREADY_OPEN"
        elif len(active) >= max_open:
            reason = "MAX_OPEN_POSITIONS"
        elif cash + 1e-12 < order_size:
            reason = "INSUFFICIENT_CAPITAL"
        if reason:
            portfolio_rejections[reason] += 1
            final.append(
                ForwardOutcome(
                    **{
                        **outcome.__dict__,
                        "status": "REJECTED",
                        "rejection_reason": reason,
                        "portfolio_accepted": False,
                        "evidence": {**outcome.evidence, "portfolio_rejection_reason": reason},
                    }
                )
            )
            continue
        cash -= order_size
        accepted_outcome = ForwardOutcome(
            **{**outcome.__dict__, "portfolio_accepted": True}
        )
        active.append(accepted_outcome)
        active_tokens.add(outcome.signal.token_mint)
        accepted.append(accepted_outcome)
        final.append(accepted_outcome)

    close_due(observed_at)
    closed = [item for item in accepted if item.status == "CLOSED" and item.pnl_sol is not None]
    pnls = [float(item.pnl_sol or 0.0) for item in closed]
    gross_profit = sum(max(0.0, item) for item in pnls)
    gross_loss = sum(min(0.0, item) for item in pnls)
    wins = sum(1 for item in pnls if item > 1e-12)
    losses = sum(1 for item in pnls if item < -1e-12)
    profit_factor = (
        gross_profit / abs(gross_loss)
        if gross_loss < 0
        else (999.0 if gross_profit > 0 else None)
    )
    net_pnl = sum(pnls)
    return final, {
        "signals": len(outcomes),
        "portfolio_accepted": len(accepted),
        "closed_trades": len(closed),
        "open_positions": sum(1 for item in active if item.exit_at is None),
        "winning_trades": wins,
        "losing_trades": losses,
        "breakeven_trades": len(closed) - wins - losses,
        "net_pnl_sol": _round(net_pnl),
        "total_return_percent": _round(
            net_pnl / starting_capital * 100.0 if starting_capital > 0 else 0.0,
            4,
        ),
        "win_rate_percent": _round(wins / len(closed) * 100.0 if closed else 0.0, 4),
        "profit_factor": None if profit_factor is None else _round(profit_factor, 4),
        "max_drawdown_percent": _round(max_drawdown, 4),
        "waiting_safety": sum(1 for item in final if item.status == "WAITING_SAFETY"),
        "pending_entry": sum(1 for item in final if item.status == "PENDING_ENTRY"),
        "rejected": sum(1 for item in final if item.status == "REJECTED"),
        "expired": sum(1 for item in final if item.status == "EXPIRED"),
        "portfolio_rejection_counts": dict(sorted(portfolio_rejections.items())),
    }


def _empty_lane_metrics() -> dict[str, Any]:
    return {
        "signals": 0,
        "portfolio_accepted": 0,
        "closed_trades": 0,
        "open_positions": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "breakeven_trades": 0,
        "net_pnl_sol": 0.0,
        "total_return_percent": 0.0,
        "win_rate_percent": 0.0,
        "profit_factor": None,
        "max_drawdown_percent": 0.0,
        "waiting_safety": 0,
        "pending_entry": 0,
        "rejected": 0,
        "expired": 0,
        "portfolio_rejection_counts": {},
    }


def _decision_key(campaign_id: str, outcome: ForwardOutcome) -> str:
    return calculate_payload_hash(
        {
            "campaign_id": campaign_id,
            "lane": outcome.signal.lane,
            "signal_hash": outcome.signal.signal_hash,
        }
    )


def _outcome_payload(outcome: ForwardOutcome) -> dict[str, Any]:
    return {
        "lane": outcome.signal.lane,
        "status": outcome.status,
        "token_mint": outcome.signal.token_mint,
        "signal_at": outcome.signal.signal_at.isoformat(),
        "signal_observed_at": outcome.signal.signal_observed_at.isoformat(),
        "decision_at": outcome.signal.decision_at.isoformat(),
        "entry_at": None if outcome.entry_at is None else outcome.entry_at.isoformat(),
        "exit_at": None if outcome.exit_at is None else outcome.exit_at.isoformat(),
        "entry_price_sol": outcome.entry_price_sol,
        "exit_price_sol": outcome.exit_price_sol,
        "order_size_sol": outcome.order_size_sol,
        "pnl_sol": outcome.pnl_sol,
        "return_percent": outcome.return_percent,
        "exit_reason": outcome.exit_reason,
        "rejection_reason": outcome.rejection_reason,
        "portfolio_accepted": outcome.portfolio_accepted,
        "contributing_wallets": list(outcome.signal.contributing_wallets),
        "independent_cluster_count": outcome.signal.independent_cluster_count,
        "source_trade_ids": list(outcome.signal.source_trade_ids),
        "source_signatures": list(outcome.signal.source_signatures),
        "signal_hash": outcome.signal.signal_hash,
        "evidence": outcome.evidence,
    }


def _upsert_decisions(
    db: Session,
    *,
    campaign: CanonicalParserGen4ForwardCampaign,
    sequence: int,
    outcomes: list[ForwardOutcome],
) -> tuple[int, int]:
    existing = {
        row.decision_key: row
        for row in db.scalars(
            select(CanonicalParserGen4ForwardDecision).where(
                CanonicalParserGen4ForwardDecision.campaign_db_id == campaign.id
            )
        )
    }
    new_count = 0
    updated_count = 0
    for outcome in outcomes:
        key = _decision_key(campaign.campaign_id, outcome)
        payload = _outcome_payload(outcome)
        evidence_hash = calculate_payload_hash(payload)
        row = existing.get(key)
        if row is None:
            row = CanonicalParserGen4ForwardDecision(
                decision_id=str(uuid4()),
                decision_key=key,
                campaign_db_id=campaign.id,
                lane=outcome.signal.lane,
                status=outcome.status,
                token_mint=outcome.signal.token_mint,
                signal_at=outcome.signal.signal_at,
                signal_observed_at=outcome.signal.signal_observed_at,
                decision_at=outcome.signal.decision_at,
                entry_at=outcome.entry_at,
                exit_at=outcome.exit_at,
                entry_price_sol=outcome.entry_price_sol,
                exit_price_sol=outcome.exit_price_sol,
                order_size_sol=outcome.order_size_sol,
                pnl_sol=outcome.pnl_sol,
                return_percent=outcome.return_percent,
                exit_reason=outcome.exit_reason,
                rejection_reason=outcome.rejection_reason,
                portfolio_accepted=outcome.portfolio_accepted,
                wallet_count=len(outcome.signal.contributing_wallets),
                independent_cluster_count=outcome.signal.independent_cluster_count,
                contributing_wallets=list(outcome.signal.contributing_wallets),
                source_trade_ids=list(outcome.signal.source_trade_ids),
                source_signatures=list(outcome.signal.source_signatures),
                signal_hash=outcome.signal.signal_hash,
                evidence=outcome.evidence,
                evidence_hash=evidence_hash,
                first_seen_cycle_sequence=sequence,
                last_updated_cycle_sequence=sequence,
            )
            db.add(row)
            new_count += 1
            continue
        if row.status == "CLOSED" and row.evidence_hash != evidence_hash:
            raise CanonicalParserGen4ForwardShadowError(
                "Decisione forward chiusa non modificabile.",
                code="GEN4_FORWARD_CLOSED_DECISION_IMMUTABILITY_VIOLATION",
                status_code=409,
            )
        if row.evidence_hash == evidence_hash:
            continue
        row.status = outcome.status
        row.signal_at = outcome.signal.signal_at
        row.signal_observed_at = outcome.signal.signal_observed_at
        row.decision_at = outcome.signal.decision_at
        row.entry_at = outcome.entry_at
        row.exit_at = outcome.exit_at
        row.entry_price_sol = outcome.entry_price_sol
        row.exit_price_sol = outcome.exit_price_sol
        row.pnl_sol = outcome.pnl_sol
        row.return_percent = outcome.return_percent
        row.exit_reason = outcome.exit_reason
        row.rejection_reason = outcome.rejection_reason
        row.portfolio_accepted = outcome.portfolio_accepted
        row.evidence = outcome.evidence
        row.evidence_hash = evidence_hash
        row.last_updated_cycle_sequence = sequence
        updated_count += 1
    db.flush()
    return new_count, updated_count


def _metrics_from_rows(
    rows: list[CanonicalParserGen4ForwardDecision],
    *,
    starting_capital: float,
) -> dict[str, Any]:
    accepted = [row for row in rows if row.portfolio_accepted]
    closed = [row for row in accepted if row.status == "CLOSED" and row.pnl_sol is not None]
    pnls = [float(row.pnl_sol or 0.0) for row in closed]
    gross_profit = sum(max(0.0, item) for item in pnls)
    gross_loss = sum(min(0.0, item) for item in pnls)
    wins = sum(1 for item in pnls if item > 1e-12)
    losses = sum(1 for item in pnls if item < -1e-12)
    profit_factor = (
        gross_profit / abs(gross_loss)
        if gross_loss < 0
        else (999.0 if gross_profit > 0 else None)
    )
    equity = starting_capital
    peak = starting_capital
    max_drawdown = 0.0
    for row in sorted(closed, key=lambda item: (_aware(item.exit_at), item.id)):
        equity += float(row.pnl_sol or 0.0)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
    net_pnl = sum(pnls)
    return {
        "signals": len(rows),
        "portfolio_accepted": len(accepted),
        "closed_trades": len(closed),
        "open_positions": sum(1 for row in accepted if row.status == "OPEN"),
        "winning_trades": wins,
        "losing_trades": losses,
        "breakeven_trades": len(closed) - wins - losses,
        "net_pnl_sol": _round(net_pnl),
        "total_return_percent": _round(net_pnl / starting_capital * 100.0, 4),
        "win_rate_percent": _round(wins / len(closed) * 100.0 if closed else 0.0, 4),
        "profit_factor": None if profit_factor is None else _round(profit_factor, 4),
        "max_drawdown_percent": _round(max_drawdown, 4),
        "waiting_safety": sum(1 for row in rows if row.status == "WAITING_SAFETY"),
        "pending_entry": sum(1 for row in rows if row.status == "PENDING_ENTRY"),
        "rejected": sum(1 for row in rows if row.status == "REJECTED"),
        "expired": sum(1 for row in rows if row.status == "EXPIRED"),
    }


def _refresh_campaign_metrics(
    db: Session,
    *,
    campaign: CanonicalParserGen4ForwardCampaign,
    observed_at: datetime,
    completed: bool = False,
) -> None:
    rows = list(
        db.scalars(
            select(CanonicalParserGen4ForwardDecision).where(
                CanonicalParserGen4ForwardDecision.campaign_db_id == campaign.id
            )
        )
    )
    by_lane: dict[str, list[CanonicalParserGen4ForwardDecision]] = defaultdict(list)
    for row in rows:
        by_lane[row.lane].append(row)
    starting_capital = float(
        campaign.policy_snapshot["gen4_profitability_policy"]["starting_capital_sol"]
    )
    strict_metrics = _metrics_from_rows(
        by_lane[LANE_STRICT_FORWARD], starting_capital=starting_capital
    )
    proxy_metrics = _metrics_from_rows(
        by_lane[LANE_PROXY_FORWARD], starting_capital=starting_capital
    )
    baseline_metrics = _metrics_from_rows(
        by_lane[LANE_BASELINE_FORWARD], starting_capital=starting_capital
    )

    observation_days = max(0.0, (observed_at - _aware(campaign.anchor_at)).total_seconds() / 86400.0)
    gaps: list[str] = []
    if observation_days < campaign.minimum_observation_days:
        gaps.append("FORWARD_MINIMUM_OBSERVATION_PERIOD_NOT_REACHED")
    if strict_metrics["closed_trades"] < campaign.minimum_closed_trades:
        gaps.append("STRICT_FORWARD_CLOSED_SAMPLE_BELOW_MINIMUM")

    enough = not gaps
    if not enough:
        verdict = VERDICT_NOT_EVALUABLE if completed else VERDICT_COLLECTING
        strict_status = "INSUFFICIENT" if completed else "COLLECTING"
    else:
        strict_status = (
            "SUFFICIENT"
            if strict_metrics["closed_trades"] >= campaign.proof_closed_trades
            else "EVALUABLE"
        )
        base = campaign.policy_snapshot["gen4_profitability_policy"]
        positive = strict_metrics["total_return_percent"] > 0
        pf_ok = (
            strict_metrics["profit_factor"] is not None
            and strict_metrics["profit_factor"] >= float(base["minimum_portfolio_profit_factor"])
        )
        dd_ok = strict_metrics["max_drawdown_percent"] <= float(
            base["maximum_portfolio_drawdown_percent"]
        )
        if not positive or not pf_ok or not dd_ok:
            verdict = VERDICT_NEGATIVE
        elif strict_status == "SUFFICIENT":
            verdict = VERDICT_PROFITABLE
        else:
            verdict = VERDICT_PROMISING

    campaign.latest_observed_at = observed_at
    campaign.decision_count = len(rows)
    campaign.strict_signal_count = len(by_lane[LANE_STRICT_FORWARD])
    campaign.proxy_signal_count = len(by_lane[LANE_PROXY_FORWARD])
    campaign.baseline_signal_count = len(by_lane[LANE_BASELINE_FORWARD])
    campaign.strict_closed_trade_count = strict_metrics["closed_trades"]
    campaign.proxy_closed_trade_count = proxy_metrics["closed_trades"]
    campaign.baseline_closed_trade_count = baseline_metrics["closed_trades"]
    campaign.rejected_decision_count = sum(1 for row in rows if row.status == "REJECTED")
    campaign.strict_metrics = strict_metrics
    campaign.proxy_metrics = proxy_metrics
    campaign.baseline_metrics = baseline_metrics
    campaign.evidence_gaps = gaps
    campaign.verdict = verdict
    campaign.strict_evidence_status = strict_status
    if completed:
        campaign.status = STATUS_COMPLETED
        campaign.completed_at = observed_at
    campaign.evidence_hash = calculate_payload_hash(_campaign_evidence_payload(campaign))
    db.flush()


def run_gen4_forward_cycle(
    db: Session,
    *,
    campaign_id: str,
    confirmation: str,
    observed_at: datetime | None = None,
    settings_object: Any = settings,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_ENABLED", False)):
        raise CanonicalParserGen4ForwardShadowError(
            "M52-M53 Gen4 Strict Forward Shadow è disabilitato.",
            code="GEN4_FORWARD_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != GEN4_FORWARD_CYCLE_CONFIRMATION:
        raise CanonicalParserGen4ForwardShadowError(
            f"Conferma richiesta: {GEN4_FORWARD_CYCLE_CONFIRMATION}",
            code="GEN4_FORWARD_CYCLE_CONFIRMATION_REQUIRED",
        )
    campaign = db.scalar(
        select(CanonicalParserGen4ForwardCampaign).where(
            CanonicalParserGen4ForwardCampaign.campaign_id == campaign_id
        )
    )
    if campaign is None:
        raise CanonicalParserGen4ForwardShadowError(
            "Campagna forward non trovata.",
            code="GEN4_FORWARD_CAMPAIGN_NOT_FOUND",
            status_code=404,
        )
    if campaign.status != STATUS_ACTIVE:
        raise CanonicalParserGen4ForwardShadowError(
            "La campagna forward non è attiva.",
            code="GEN4_FORWARD_CAMPAIGN_NOT_ACTIVE",
            status_code=409,
        )

    observed = _aware(observed_at)
    anchor = _aware(campaign.anchor_at)
    if observed < anchor:
        raise CanonicalParserGen4ForwardShadowError(
            "Il watermark osservato precede l'anchor della campagna.",
            code="GEN4_FORWARD_OBSERVED_BEFORE_ANCHOR",
        )
    previous_observed = _aware(campaign.latest_observed_at)
    if observed < previous_observed:
        raise CanonicalParserGen4ForwardShadowError(
            "Il watermark forward non può arretrare.",
            code="GEN4_FORWARD_WATERMARK_REGRESSION",
            status_code=409,
        )

    policy = dict(campaign.policy_snapshot)
    trades = _load_forward_trades(
        db,
        anchor_at=anchor,
        observed_at=observed,
        max_source_trades=int(policy["maximum_source_trades_per_cycle"]),
    )
    points, price_audit = _forward_price_points(trades, policy=policy)
    frozen = set(str(item) for item in campaign.frozen_wallets)
    edges = list(db.scalars(select(WalletEdge)))
    proxy_signals = _build_proxy_signals(
        points,
        frozen_wallets=frozen,
        edges=edges,
        policy=policy,
    )
    baseline_signals = _build_baseline_signals(points, frozen_wallets=frozen)
    token_snapshots = {
        snapshot.token_mint: snapshot
        for snapshot in db.scalars(
            select(TokenSafetySnapshot).where(
                TokenSafetySnapshot.token_mint.in_(
                    sorted({signal.token_mint for signal in proxy_signals}) or ["__NONE__"]
                )
            )
        )
    }
    strict_signals = [
        _strict_signal(
            signal,
            snapshot=token_snapshots.get(signal.token_mint),
            observed_at=observed,
            policy=policy,
        )
        for signal in proxy_signals
    ]

    by_token: dict[str, list[ForwardPricePoint]] = defaultdict(list)
    for point in points:
        by_token[point.token_mint].append(point)
    raw_by_lane: dict[str, list[ForwardOutcome]] = {
        LANE_STRICT_FORWARD: [
            _simulate_forward_signal(
                signal,
                token_points=by_token[signal.token_mint],
                observed_at=observed,
                policy=policy,
            )
            for signal in strict_signals
        ],
        LANE_PROXY_FORWARD: [
            _simulate_forward_signal(
                signal,
                token_points=by_token[signal.token_mint],
                observed_at=observed,
                policy=policy,
            )
            for signal in proxy_signals
        ],
        LANE_BASELINE_FORWARD: [
            _simulate_forward_signal(
                signal,
                token_points=by_token[signal.token_mint],
                observed_at=observed,
                policy=policy,
            )
            for signal in baseline_signals
        ],
    }
    outcomes: list[ForwardOutcome] = []
    lane_metrics: dict[str, dict[str, Any]] = {}
    for lane in (LANE_STRICT_FORWARD, LANE_PROXY_FORWARD, LANE_BASELINE_FORWARD):
        applied, metrics = _apply_portfolio(
            raw_by_lane[lane],
            observed_at=observed,
            policy=policy,
        )
        outcomes.extend(applied)
        lane_metrics[lane] = metrics

    sequence = int(campaign.cycle_count) + 1
    new_count, updated_count = _upsert_decisions(
        db,
        campaign=campaign,
        sequence=sequence,
        outcomes=outcomes,
    )
    closed_count = sum(1 for item in outcomes if item.status == "CLOSED" and item.portfolio_accepted)
    cycle_summary = {
        "campaign_id": campaign.campaign_id,
        "sequence": sequence,
        "observed_from_at": previous_observed.isoformat(),
        "observed_to_at": observed.isoformat(),
        "source_trade_count": len(trades),
        "accepted_price_point_count": len(points),
        "price_audit": price_audit,
        "signal_counts": {
            LANE_STRICT_FORWARD: len(strict_signals),
            LANE_PROXY_FORWARD: len(proxy_signals),
            LANE_BASELINE_FORWARD: len(baseline_signals),
        },
        "lane_metrics": lane_metrics,
        "new_decision_count": new_count,
        "updated_decision_count": updated_count,
        "closed_decision_count": closed_count,
    }
    cycle_key = calculate_payload_hash(
        {
            "campaign_id": campaign.campaign_id,
            "sequence": sequence,
            "observed_to_at": observed.isoformat(),
            "summary": cycle_summary,
        }
    )
    report_hash = calculate_payload_hash(cycle_summary)
    cycle = CanonicalParserGen4ForwardCycle(
        cycle_id=str(uuid4()),
        cycle_key=cycle_key,
        campaign_db_id=campaign.id,
        sequence=sequence,
        status="NOOP" if new_count == 0 and updated_count == 0 else "COMPLETED",
        observed_from_at=previous_observed,
        observed_to_at=observed,
        source_trade_count=len(trades),
        accepted_price_point_count=len(points),
        new_decision_count=new_count,
        updated_decision_count=updated_count,
        strict_signal_count=len(strict_signals),
        proxy_signal_count=len(proxy_signals),
        baseline_signal_count=len(baseline_signals),
        closed_decision_count=closed_count,
        summary=cycle_summary,
        evidence={
            "point_in_time_guard": True,
            "market_clock": "trades.block_time",
            "availability_clock": "trades.created_at",
            "historical_backfill_after_anchor_allowed": False,
        },
        safety=_forward_safety_contract(),
        report_hash=report_hash,
        started_at=observed,
        completed_at=observed,
    )
    db.add(cycle)
    campaign.cycle_count = sequence
    _refresh_campaign_metrics(db, campaign=campaign, observed_at=observed)
    try:
        db.flush()
    except IntegrityError as exception:
        db.rollback()
        raise CanonicalParserGen4ForwardShadowError(
            "Impossibile persistere il ciclo forward.",
            code="GEN4_FORWARD_CYCLE_PERSISTENCE_CONFLICT",
            status_code=409,
        ) from exception
    return {
        "campaign": _serialize_campaign(db, campaign),
        "cycle": _serialize_cycle(cycle),
        "safety": _forward_safety_contract(),
    }


def stop_gen4_forward_campaign(
    db: Session,
    *,
    campaign_id: str,
    confirmation: str,
    observed_at: datetime | None = None,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_ENABLED", False)):
        raise CanonicalParserGen4ForwardShadowError(
            "M52-M53 Gen4 Strict Forward Shadow è disabilitato.",
            code="GEN4_FORWARD_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != GEN4_FORWARD_STOP_CONFIRMATION:
        raise CanonicalParserGen4ForwardShadowError(
            f"Conferma richiesta: {GEN4_FORWARD_STOP_CONFIRMATION}",
            code="GEN4_FORWARD_STOP_CONFIRMATION_REQUIRED",
        )
    campaign = db.scalar(
        select(CanonicalParserGen4ForwardCampaign).where(
            CanonicalParserGen4ForwardCampaign.campaign_id == campaign_id
        )
    )
    if campaign is None:
        raise CanonicalParserGen4ForwardShadowError(
            "Campagna forward non trovata.",
            code="GEN4_FORWARD_CAMPAIGN_NOT_FOUND",
            status_code=404,
        )
    if campaign.status == STATUS_COMPLETED:
        return _serialize_campaign(db, campaign) | {"idempotent_replay": True}
    observed = max(_aware(observed_at), _aware(campaign.latest_observed_at))
    campaign.actor_label = _actor(actor_label or campaign.actor_label)
    campaign.note = _note(note) or campaign.note
    _refresh_campaign_metrics(db, campaign=campaign, observed_at=observed, completed=True)
    return _serialize_campaign(db, campaign) | {"idempotent_replay": False}


def _serialize_decision(row: CanonicalParserGen4ForwardDecision) -> dict[str, Any]:
    return {
        "decision_id": row.decision_id,
        "lane": row.lane,
        "status": row.status,
        "token_mint": row.token_mint,
        "signal_at": _aware(row.signal_at).isoformat(),
        "signal_observed_at": _aware(row.signal_observed_at).isoformat(),
        "decision_at": _aware(row.decision_at).isoformat(),
        "entry_at": None if row.entry_at is None else _aware(row.entry_at).isoformat(),
        "exit_at": None if row.exit_at is None else _aware(row.exit_at).isoformat(),
        "entry_price_sol": row.entry_price_sol,
        "exit_price_sol": row.exit_price_sol,
        "order_size_sol": row.order_size_sol,
        "pnl_sol": row.pnl_sol,
        "return_percent": row.return_percent,
        "exit_reason": row.exit_reason,
        "rejection_reason": row.rejection_reason,
        "portfolio_accepted": row.portfolio_accepted,
        "wallet_count": row.wallet_count,
        "independent_cluster_count": row.independent_cluster_count,
        "contributing_wallets": row.contributing_wallets,
        "source_trade_ids": row.source_trade_ids,
        "source_signatures": row.source_signatures,
        "signal_hash": row.signal_hash,
        "evidence": row.evidence,
        "evidence_hash": row.evidence_hash,
        "first_seen_cycle_sequence": row.first_seen_cycle_sequence,
        "last_updated_cycle_sequence": row.last_updated_cycle_sequence,
    }


def _serialize_cycle(row: CanonicalParserGen4ForwardCycle) -> dict[str, Any]:
    return {
        "cycle_id": row.cycle_id,
        "sequence": row.sequence,
        "status": row.status,
        "observed_from_at": _aware(row.observed_from_at).isoformat(),
        "observed_to_at": _aware(row.observed_to_at).isoformat(),
        "source_trade_count": row.source_trade_count,
        "accepted_price_point_count": row.accepted_price_point_count,
        "new_decision_count": row.new_decision_count,
        "updated_decision_count": row.updated_decision_count,
        "strict_signal_count": row.strict_signal_count,
        "proxy_signal_count": row.proxy_signal_count,
        "baseline_signal_count": row.baseline_signal_count,
        "closed_decision_count": row.closed_decision_count,
        "summary": row.summary,
        "evidence": row.evidence,
        "safety": row.safety,
        "report_hash": row.report_hash,
        "completed_at": None if row.completed_at is None else _aware(row.completed_at).isoformat(),
    }


def _serialize_campaign(
    db: Session,
    campaign: CanonicalParserGen4ForwardCampaign,
    *,
    include_decisions: bool = True,
    decision_limit: int = 100,
) -> dict[str, Any]:
    cycles = list(
        db.scalars(
            select(CanonicalParserGen4ForwardCycle)
            .where(CanonicalParserGen4ForwardCycle.campaign_db_id == campaign.id)
            .order_by(desc(CanonicalParserGen4ForwardCycle.sequence))
            .limit(20)
        )
    )
    decisions: list[CanonicalParserGen4ForwardDecision] = []
    if include_decisions:
        decisions = list(
            db.scalars(
                select(CanonicalParserGen4ForwardDecision)
                .where(CanonicalParserGen4ForwardDecision.campaign_db_id == campaign.id)
                .order_by(desc(CanonicalParserGen4ForwardDecision.decision_at), desc(CanonicalParserGen4ForwardDecision.id))
                .limit(max(1, min(int(decision_limit), 1000)))
            )
        )
    return {
        "campaign_id": campaign.campaign_id,
        "scope": campaign.scope,
        "status": campaign.status,
        "verdict": campaign.verdict,
        "strict_evidence_status": campaign.strict_evidence_status,
        "policy_version": campaign.policy_version,
        "policy_hash": campaign.policy_hash,
        "policy_snapshot": campaign.policy_snapshot,
        "frozen_wallets": campaign.frozen_wallets,
        "frozen_wallet_metrics": campaign.frozen_wallet_metrics,
        "frozen_wallet_count": campaign.frozen_wallet_count,
        "anchor_at": _aware(campaign.anchor_at).isoformat(),
        "minimum_complete_at": _aware(campaign.minimum_complete_at).isoformat(),
        "latest_observed_at": _aware(campaign.latest_observed_at).isoformat(),
        "started_at": _aware(campaign.started_at).isoformat(),
        "completed_at": None if campaign.completed_at is None else _aware(campaign.completed_at).isoformat(),
        "minimum_observation_days": campaign.minimum_observation_days,
        "minimum_closed_trades": campaign.minimum_closed_trades,
        "proof_closed_trades": campaign.proof_closed_trades,
        "cycle_count": campaign.cycle_count,
        "decision_count": campaign.decision_count,
        "strict_signal_count": campaign.strict_signal_count,
        "proxy_signal_count": campaign.proxy_signal_count,
        "baseline_signal_count": campaign.baseline_signal_count,
        "strict_closed_trade_count": campaign.strict_closed_trade_count,
        "proxy_closed_trade_count": campaign.proxy_closed_trade_count,
        "baseline_closed_trade_count": campaign.baseline_closed_trade_count,
        "rejected_decision_count": campaign.rejected_decision_count,
        "strict_metrics": campaign.strict_metrics,
        "proxy_metrics": campaign.proxy_metrics,
        "baseline_metrics": campaign.baseline_metrics,
        "evidence_gaps": campaign.evidence_gaps,
        "safety": campaign.safety,
        "evidence_hash": campaign.evidence_hash,
        "actor_label": campaign.actor_label,
        "note": campaign.note,
        "technical_metadata": campaign.technical_metadata,
        "recent_cycles": [_serialize_cycle(row) for row in cycles],
        "recent_decisions": [_serialize_decision(row) for row in decisions],
        "confirmation_required": {
            "cycle": GEN4_FORWARD_CYCLE_CONFIRMATION,
            "stop": GEN4_FORWARD_STOP_CONFIRMATION,
        },
    }


def get_gen4_forward_campaign(
    db: Session,
    campaign_id: str,
    *,
    include_decisions: bool = True,
    decision_limit: int = 100,
) -> dict[str, Any]:
    campaign = db.scalar(
        select(CanonicalParserGen4ForwardCampaign).where(
            CanonicalParserGen4ForwardCampaign.campaign_id == campaign_id
        )
    )
    if campaign is None:
        raise CanonicalParserGen4ForwardShadowError(
            "Campagna forward non trovata.",
            code="GEN4_FORWARD_CAMPAIGN_NOT_FOUND",
            status_code=404,
        )
    return _serialize_campaign(
        db,
        campaign,
        include_decisions=include_decisions,
        decision_limit=decision_limit,
    )


def get_gen4_forward_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    latest = db.scalar(
        select(CanonicalParserGen4ForwardCampaign)
        .order_by(desc(CanonicalParserGen4ForwardCampaign.created_at), desc(CanonicalParserGen4ForwardCampaign.id))
        .limit(1)
    )
    active = db.scalar(
        select(CanonicalParserGen4ForwardCampaign)
        .where(CanonicalParserGen4ForwardCampaign.status == STATUS_ACTIVE)
        .order_by(desc(CanonicalParserGen4ForwardCampaign.id))
        .limit(1)
    )
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_GEN4_FORWARD_ENABLED", False)),
        "scope": GEN4_FORWARD_SCOPE,
        "policy_version": GEN4_FORWARD_POLICY_VERSION,
        "policy": _forward_policy_snapshot(settings_object),
        "campaign_count": int(
            db.scalar(select(func.count(CanonicalParserGen4ForwardCampaign.id))) or 0
        ),
        "cycle_count": int(db.scalar(select(func.count(CanonicalParserGen4ForwardCycle.id))) or 0),
        "decision_count": int(
            db.scalar(select(func.count(CanonicalParserGen4ForwardDecision.id))) or 0
        ),
        "active_campaign_id": None if active is None else active.campaign_id,
        "latest_campaign": None if latest is None else _serialize_campaign(
            db, latest, include_decisions=False
        ),
        "confirmation_required": {
            "start": GEN4_FORWARD_START_CONFIRMATION,
            "cycle": GEN4_FORWARD_CYCLE_CONFIRMATION,
            "stop": GEN4_FORWARD_STOP_CONFIRMATION,
        },
        "safety": _forward_safety_contract(),
    }
