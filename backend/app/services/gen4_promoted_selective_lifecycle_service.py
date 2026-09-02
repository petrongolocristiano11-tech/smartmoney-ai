from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4PromotedSelectiveActivation,
    CanonicalParserGen4PromotedSelectivePosition,
)
from backend.app.services.gen4_selective_challenger_lifecycle_bridge_design_service import (
    ACTIVATION_ACTIVE,
    ACTIVATION_DRAINING,
    ACTIVATION_STOPPED,
    M301_ACTIVATION_BLUEPRINT_SCOPE,
    M301_DECISION_ENVELOPE_SCOPE,
    PROMOTED_SELECTIVE_SCOPE,
    build_activation_blueprint,
    event_is_lifecycle_eligible,
    sign_promotion_decision_envelope,
    validate_activation_transition,
    validate_m300_decision,
    validate_operational_policy_snapshot,
    validate_promotion_decision_envelope,
)
from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
)

M307_VERSION = "canonical-parser-gen4-promoted-selective-lifecycle-bridge/1"
M307_SCOPE = "M307_PROMOTED_SELECTIVE_LIFECYCLE_BRIDGE_IMPLEMENTED_DISARMED"
M307_BRIDGE_IMPLEMENTED = True
M307_BRIDGE_ARMED = False
M307_AUTOMATIC_PROMOTION = False
M307_PREPROMOTION_BACKFILL = False
M307_LEGACY_ENDPOINT_USED = False
M307_PROVIDER_MUTATION_REQUIRED = False

M306_FORMAL_REPORT_SHA256 = "05796e4cc3d771752e10f61490d4c763288b7f3c8844db11c5c04132dec90a2b"
M299_FORMAL_ACQUISITION_REPORT_SHA256 = "b0893640854362cb28a084cc6f6ddd07b4f457299727bf627d21703114b63c19"
M306_FORMAL_TERMINAL_UTC = "2026-09-01T15:12:26.113486+00:00"

ACTIVATE_CONFIRMATION = "ACTIVATE_M307_PROMOTED_SELECTIVE_LIFECYCLE"
DRAIN_CONFIRMATION = "DRAIN_M307_PROMOTED_SELECTIVE_LIFECYCLE"
STOP_CONFIRMATION = "STOP_M307_PROMOTED_SELECTIVE_LIFECYCLE"

PROMOTED_POSITION_OPEN = "OPEN"
PROMOTED_POSITION_OPEN_PARTIAL = "OPEN_PARTIAL"
PROMOTED_POSITION_CLOSED = "CLOSED"
PROMOTED_POSITION_OPEN_STATES = {
    PROMOTED_POSITION_OPEN,
    PROMOTED_POSITION_OPEN_PARTIAL,
}


class M307Error(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M307Error(message)


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif value not in (None, ""):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sha64(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    _require(
        len(text) == 64 and all(ch in "0123456789abcdef" for ch in text),
        f"M307 SHA256 non valido: {label}.",
    )
    return text


def _without_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k != "integrity"}


def build_activation_package(
    *,
    m300_decision: dict[str, Any],
    m306_report_sha256: str,
    m299_acquisition_report_sha256: str,
    operational_policy_snapshot: dict[str, Any],
    operational_policy_source_sha256: str,
    candidate_watchlist_wallets: list[str],
    activation_at: datetime | str,
) -> dict[str, Any]:
    decision = validate_m300_decision(dict(m300_decision or {}))
    _require(
        decision.get("state") == "PROMOTION_ELIGIBLE_DISARMED",
        "M307 richiede M300 state=PROMOTION_ELIGIBLE_DISARMED.",
    )
    checks = dict(decision.get("checks") or {})
    _require(bool(checks) and all(value is True for value in checks.values()), "M307 M300 checks non tutti PASS.")

    m306_sha = _sha64(m306_report_sha256, label="M306 formal report")
    _require(
        m306_sha == M306_FORMAL_REPORT_SHA256,
        "M307 M306 formal report SHA inatteso.",
    )
    m299_sha = _sha64(m299_acquisition_report_sha256, label="M299 acquisition report")
    _require(
        m299_sha == M299_FORMAL_ACQUISITION_REPORT_SHA256,
        "M307 M299 acquisition report SHA inatteso.",
    )

    wallet = str(decision["wallet"])
    watchlist = sorted({str(item).strip() for item in candidate_watchlist_wallets if str(item).strip()})
    _require(wallet in watchlist, "M307 wallet non presente nella candidate watchlist al momento della preparazione.")

    policy = validate_operational_policy_snapshot(dict(operational_policy_snapshot or {}))
    policy_source_sha = _sha64(
        operational_policy_source_sha256,
        label="operational policy source",
    )
    activated = _aware(activation_at)
    _require(activated is not None, "M307 activation_at invalido.")
    formal_terminal = _aware(M306_FORMAL_TERMINAL_UTC)
    _require(formal_terminal is not None and activated >= formal_terminal, "M307 activation precedente alla formal M306 evaluation.")

    decision_envelope = sign_promotion_decision_envelope(
        decision,
        acquisition_report_sha256=m299_sha,
        evaluated_at=formal_terminal,
    )
    blueprint = build_activation_blueprint(
        decision_envelope,
        operational_policy_snapshot=policy,
        operational_policy_source_sha256=policy_source_sha,
        activation_at=activated,
    )
    _require(
        blueprint.get("scope") == M301_ACTIVATION_BLUEPRINT_SCOPE,
        "M307 activation blueprint scope inatteso.",
    )

    payload: dict[str, Any] = {
        "scope": "M307_PROMOTED_SELECTIVE_ACTIVATION_PACKAGE",
        "version": M307_VERSION,
        "wallet": wallet,
        "formal_promotion_lineage": {
            "m306_report_sha256": m306_sha,
            "m299_acquisition_report_sha256": m299_sha,
            "m306_terminal_utc": M306_FORMAL_TERMINAL_UTC,
            "m300_state": decision["state"],
            "m300_promotion_eligible": True,
        },
        "candidate_watchlist_snapshot": {
            "wallets": watchlist,
            "target_present": True,
        },
        "decision_envelope": decision_envelope,
        "activation_blueprint": blueprint,
        "safety": {
            "bridge_implemented": True,
            "bridge_armed": False,
            "automatic_promotion": False,
            "prepromotion_backfill": False,
            "legacy_endpoint_used": False,
            "provider_mutation_required": False,
            "live": False,
            "signer": False,
            "paper": False,
        },
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload


def validate_activation_package(package: dict[str, Any]) -> dict[str, Any]:
    p = dict(package or {})
    _require(
        p.get("scope") == "M307_PROMOTED_SELECTIVE_ACTIVATION_PACKAGE",
        "M307 activation package scope inatteso.",
    )
    _require(p.get("version") == M307_VERSION, "M307 activation package version inattesa.")
    wallet = str(p.get("wallet") or "")
    lineage = dict(p.get("formal_promotion_lineage") or {})
    _require(
        str(lineage.get("m306_report_sha256") or "") == M306_FORMAL_REPORT_SHA256,
        "M307 activation package M306 lineage invalida.",
    )
    _require(
        str(lineage.get("m299_acquisition_report_sha256") or "")
        == M299_FORMAL_ACQUISITION_REPORT_SHA256,
        "M307 activation package M299 lineage invalida.",
    )
    _require(lineage.get("m300_state") == "PROMOTION_ELIGIBLE_DISARMED", "M307 activation package M300 state invalido.")
    _require(lineage.get("m300_promotion_eligible") is True, "M307 activation package M300 eligibility invalida.")

    watchlist = dict(p.get("candidate_watchlist_snapshot") or {})
    _require(watchlist.get("target_present") is True, "M307 candidate watchlist proof mancante.")
    _require(wallet in [str(x) for x in watchlist.get("wallets") or []], "M307 wallet assente dalla candidate watchlist proof.")

    envelope = validate_promotion_decision_envelope(dict(p.get("decision_envelope") or {}))
    _require(str(envelope.get("wallet") or "") == wallet, "M307 decision envelope wallet mismatch.")
    blueprint = dict(p.get("activation_blueprint") or {})
    _require(blueprint.get("scope") == M301_ACTIVATION_BLUEPRINT_SCOPE, "M307 activation blueprint scope invalido.")
    _require(str(blueprint.get("wallet") or "") == wallet, "M307 activation blueprint wallet mismatch.")
    frozen = dict(blueprint.get("frozen_operational_policy") or {})
    validate_operational_policy_snapshot(
        {
            "simulated_input_lamports": frozen.get("simulated_input_lamports"),
            "slippage_bps": frozen.get("slippage_bps"),
            "max_quote_latency_ms": frozen.get("max_quote_latency_ms"),
            "max_price_impact_bps": frozen.get("max_price_impact_bps"),
            "max_price_deterioration_bps": frozen.get("max_price_deterioration_bps"),
            "estimated_network_fee_lamports": frozen.get("estimated_network_fee_lamports"),
            "live_execution": False,
            "paper_execution": False,
            "automatic_live_activation": False,
        }
    )
    _require(
        str(frozen.get("policy_hash") or "") == canonical_sha256(
            {k: v for k, v in frozen.items() if k != "policy_hash"}
        ),
        "M307 frozen policy hash invalido.",
    )

    safety = dict(p.get("safety") or {})
    _require(safety.get("bridge_implemented") is True, "M307 bridge implemented claim mancante.")
    _require(safety.get("bridge_armed") is False, "M307 bridge non disarmato.")
    _require(safety.get("automatic_promotion") is False, "M307 automatic promotion non false.")
    _require(safety.get("prepromotion_backfill") is False, "M307 backfill non false.")
    _require(safety.get("legacy_endpoint_used") is False, "M307 legacy endpoint usato.")
    _require(safety.get("provider_mutation_required") is False, "M307 provider mutation richiesta.")
    _require(safety.get("live") is False and safety.get("signer") is False and safety.get("paper") is False, "M307 safety execution non disarmata.")

    integrity = dict(p.get("integrity") or {})
    expected = str(integrity.get("payload_sha256") or "")
    _require(
        len(expected) == 64 and expected == canonical_sha256(_without_integrity(p)),
        "M307 activation package integrity invalida.",
    )
    return p


def serialize_activation(
    db: Session,
    activation: CanonicalParserGen4PromotedSelectiveActivation,
) -> dict[str, Any]:
    open_positions = int(
        db.scalar(
            select(CanonicalParserGen4PromotedSelectivePosition.id)
            .where(
                CanonicalParserGen4PromotedSelectivePosition.activation_db_id == activation.id,
                CanonicalParserGen4PromotedSelectivePosition.status.in_(list(PROMOTED_POSITION_OPEN_STATES)),
            )
            .limit(1)
        )
        is not None
    )
    if open_positions:
        open_positions = len(
            list(
                db.scalars(
                    select(CanonicalParserGen4PromotedSelectivePosition).where(
                        CanonicalParserGen4PromotedSelectivePosition.activation_db_id == activation.id,
                        CanonicalParserGen4PromotedSelectivePosition.status.in_(list(PROMOTED_POSITION_OPEN_STATES)),
                    )
                )
            )
        )
    total_positions = len(
        list(
            db.scalars(
                select(CanonicalParserGen4PromotedSelectivePosition).where(
                    CanonicalParserGen4PromotedSelectivePosition.activation_db_id == activation.id
                )
            )
        )
    )
    return {
        "activation_id": activation.activation_id,
        "wallet_address": activation.wallet_address,
        "status": activation.status,
        "activation_anchor_utc": activation.activation_anchor_at.isoformat(),
        "draining_at_utc": activation.draining_at.isoformat() if activation.draining_at else None,
        "stopped_at_utc": activation.stopped_at.isoformat() if activation.stopped_at else None,
        "decision_envelope_sha256": activation.decision_envelope_sha256,
        "formal_m306_report_sha256": activation.formal_m306_report_sha256,
        "policy_hash": activation.policy_hash,
        "open_positions": open_positions,
        "position_count": total_positions,
        "promotion_executed": True,
        "full_lifecycle_activation_started": True,
        "micro_live_ready_claimed": False,
        "live_execution_authorized": False,
    }


def activate_promoted_selective_lifecycle(
    db: Session,
    *,
    confirmation: str,
    activation_package: dict[str, Any],
) -> dict[str, Any]:
    _require(
        str(confirmation or "").strip() == ACTIVATE_CONFIRMATION,
        f"M307 activation confirmation richiesta: {ACTIVATE_CONFIRMATION}.",
    )
    package = validate_activation_package(activation_package)
    wallet = str(package["wallet"])

    existing = db.scalar(
        select(CanonicalParserGen4PromotedSelectiveActivation)
        .where(
            CanonicalParserGen4PromotedSelectiveActivation.wallet_address == wallet,
            CanonicalParserGen4PromotedSelectiveActivation.status.in_(
                [ACTIVATION_ACTIVE, ACTIVATION_DRAINING]
            ),
        )
        .order_by(CanonicalParserGen4PromotedSelectiveActivation.id.desc())
        .limit(1)
    )
    _require(existing is None, "M307 wallet ha già una promoted activation ACTIVE/DRAINING.")

    blueprint = dict(package["activation_blueprint"])
    frozen = dict(blueprint["frozen_operational_policy"])
    envelope = dict(package["decision_envelope"])
    activation = CanonicalParserGen4PromotedSelectiveActivation(
        activation_id=str(uuid4()),
        wallet_address=wallet,
        status=ACTIVATION_ACTIVE,
        activation_anchor_at=_aware(blueprint["activation_anchor_utc"]),
        decision_envelope_sha256=str(dict(envelope.get("integrity") or {}).get("payload_sha256") or ""),
        formal_m306_report_sha256=M306_FORMAL_REPORT_SHA256,
        policy_hash=str(frozen["policy_hash"]),
        policy_snapshot=frozen,
        decision_envelope=envelope,
        evidence={
            "version": M307_VERSION,
            "scope": M307_SCOPE,
            "activation_package_sha256": str(dict(package.get("integrity") or {}).get("payload_sha256") or ""),
            "activation_blueprint": blueprint,
            "formal_promotion_lineage": dict(package["formal_promotion_lineage"]),
            "candidate_watchlist_snapshot": dict(package["candidate_watchlist_snapshot"]),
            "prepromotion_backfill": False,
            "legacy_endpoint_used": False,
            "provider_mutation_required": False,
            "live_execution": False,
            "paper_execution": False,
            "signer_access": False,
        },
        draining_at=None,
        stopped_at=None,
    )
    db.add(activation)
    db.flush()
    return serialize_activation(db, activation)


def get_promoted_activation_for_event(
    db: Session,
    *,
    wallet: str,
    event_received_at: datetime | str,
    side: str,
) -> CanonicalParserGen4PromotedSelectiveActivation | None:
    activation = db.scalar(
        select(CanonicalParserGen4PromotedSelectiveActivation)
        .where(
            CanonicalParserGen4PromotedSelectiveActivation.wallet_address == str(wallet),
            CanonicalParserGen4PromotedSelectiveActivation.status.in_(
                [ACTIVATION_ACTIVE, ACTIVATION_DRAINING]
            ),
        )
        .order_by(CanonicalParserGen4PromotedSelectiveActivation.activation_anchor_at.desc())
        .limit(1)
    )
    if activation is None:
        return None
    blueprint = dict(dict(activation.evidence or {}).get("activation_blueprint") or {})
    if not blueprint:
        return None
    decision = event_is_lifecycle_eligible(
        blueprint,
        event_received_at=event_received_at,
        side=side,
        activation_status=activation.status,
    )
    return activation if decision.get("lifecycle_allowed") is True else None


def transition_promoted_selective_lifecycle(
    db: Session,
    *,
    activation_id: str,
    next_status: str,
    confirmation: str,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    activation = db.scalar(
        select(CanonicalParserGen4PromotedSelectiveActivation)
        .where(CanonicalParserGen4PromotedSelectiveActivation.activation_id == str(activation_id))
        .limit(1)
    )
    _require(activation is not None, "M307 activation non trovata.")
    target = str(next_status or "").upper()
    expected_confirmation = {
        ACTIVATION_DRAINING: DRAIN_CONFIRMATION,
        ACTIVATION_STOPPED: STOP_CONFIRMATION,
    }.get(target)
    _require(expected_confirmation is not None, "M307 transition target non supportato.")
    _require(
        str(confirmation or "").strip() == expected_confirmation,
        f"M307 transition confirmation richiesta: {expected_confirmation}.",
    )

    open_positions = len(
        list(
            db.scalars(
                select(CanonicalParserGen4PromotedSelectivePosition).where(
                    CanonicalParserGen4PromotedSelectivePosition.activation_db_id == activation.id,
                    CanonicalParserGen4PromotedSelectivePosition.status.in_(list(PROMOTED_POSITION_OPEN_STATES)),
                )
            )
        )
    )
    decision = validate_activation_transition(
        activation.status,
        target,
        open_positions=open_positions,
    )
    _require(decision.get("allowed") is True, "M307 activation transition non consentita: " + str(decision.get("reason") or ""))

    now = _aware(observed_at) or datetime.now(timezone.utc)
    activation.status = target
    if target == ACTIVATION_DRAINING:
        activation.draining_at = now
    elif target == ACTIVATION_STOPPED:
        activation.stopped_at = now
    evidence = dict(activation.evidence or {})
    transitions = list(evidence.get("state_transitions") or [])
    transitions.append(
        {
            "from": decision["current_status"],
            "to": decision["next_status"],
            "observed_at_utc": now.isoformat(),
            "open_positions": open_positions,
            "automatic": False,
        }
    )
    evidence["state_transitions"] = transitions[-50:]
    activation.evidence = evidence
    db.flush()
    return serialize_activation(db, activation)


def promoted_selective_status(
    db: Session,
    *,
    wallet: str | None = None,
) -> dict[str, Any]:
    statement = select(CanonicalParserGen4PromotedSelectiveActivation)
    if wallet:
        statement = statement.where(
            CanonicalParserGen4PromotedSelectiveActivation.wallet_address == str(wallet)
        )
    activations = list(
        db.scalars(
            statement.order_by(
                CanonicalParserGen4PromotedSelectiveActivation.activation_anchor_at.desc(),
                CanonicalParserGen4PromotedSelectiveActivation.id.desc(),
            )
        )
    )
    return {
        "scope": M307_SCOPE,
        "version": M307_VERSION,
        "bridge_implemented": True,
        "bridge_armed": False,
        "automatic_promotion": False,
        "prepromotion_backfill": False,
        "legacy_endpoint_used": False,
        "provider_mutation_required": False,
        "activations": [serialize_activation(db, row) for row in activations],
        "safety": {
            "live_execution": False,
            "signer_access": False,
            "paper_orders": 0,
            "submitted_transactions": 0,
            "micro_live_ready_claimed": False,
        },
    }
