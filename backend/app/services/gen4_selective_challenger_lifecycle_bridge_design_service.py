from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from backend.app.services.gen4_selective_challenger_promotion_service import (
    M300_SCOPE,
    M300_VERSION,
    TARGETS,
)
from backend.app.services.gen4_selective_micro_live_readiness_service import (
    validate_policy as validate_m298_policy,
)
from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
)

M301_VERSION = "canonical-parser-gen4-selective-challenger-lifecycle-bridge-design/1"
M301_SCOPE = "M301_SELECTIVE_CHALLENGER_LIFECYCLE_BRIDGE_DESIGN_DISARMED"
M301_DECISION_ENVELOPE_SCOPE = "M301_M300_PROMOTION_DECISION_ENVELOPE"
M301_DECISION_ENVELOPE_VERSION = "canonical-parser-gen4-m300-promotion-decision-envelope/1"
M301_ACTIVATION_BLUEPRINT_SCOPE = "M301_PROMOTED_SELECTIVE_ACTIVATION_BLUEPRINT"
M301_ACTIVATION_BLUEPRINT_VERSION = "canonical-parser-gen4-promoted-selective-activation-blueprint/1"

PROMOTED_SELECTIVE_SCOPE = "PROMOTED_CANDIDATE_FASTPATH_SELECTIVE"
PROMOTED_ACTIVATION_TABLE = "canonical_parser_gen4_promoted_selective_activations"
PROMOTED_POSITION_TABLE = "canonical_parser_gen4_promoted_selective_positions"
OFFICIAL_POSITION_TABLE = "canonical_parser_gen4_fastpath_selective_positions"
OFFICIAL_SELECTIVE_SCOPE = "OFFICIAL_FASTPATH_SELECTIVE"

M301_BRIDGE_IMPLEMENTED = False
M301_BRIDGE_ARMED = False
M301_AUTOMATIC_PROMOTION = False
M301_PROVIDER_MUTATION_REQUIRED = False
M301_LEGACY_ENDPOINT_REQUIRED = False

M296_REPORT_SHA256 = "914bf15250adcb319359efb022f6bbc73954db6aee09dc05381b8ce0e1bfe1f2"
M297_REPORT_SHA256 = "0f1c033d7c4cc02d38e292970b3e334a5a665aee81e963bcd0727602ab7e4bf5"
M298_REPORT_SHA256 = "22be261b8af2a260cc253b7b71d50ccd876aa2894cb9d27082d968ca9d34c962"
M299_REPORT_SHA256 = "a3a9f0cac44efd02f514ea5b0a4a2fa8525c37a9b65271fc6737ba50de3a68ea"
M300_REPORT_SHA256 = "cb439fe354717299f035877fe762088e7de2aa6fd663b4f400e6c91f329bca4d"
M297_ANCHOR_UTC = "2026-08-31T12:30:50.267406+00:00"

ACTIVATION_ACTIVE = "ACTIVE"
ACTIVATION_DRAINING = "DRAINING"
ACTIVATION_STOPPED = "STOPPED"
ACTIVATION_STATUSES = {
    ACTIVATION_ACTIVE,
    ACTIVATION_DRAINING,
    ACTIVATION_STOPPED,
}


class M301Error(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M301Error(message)


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


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _without_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k != "integrity"}


def _sha64(value: Any) -> str:
    text = str(value or "").strip().lower()
    _require(len(text) == 64 and all(c in "0123456789abcdef" for c in text), "SHA256 non valido.")
    return text


def validate_m300_decision(decision: dict[str, Any]) -> dict[str, Any]:
    d = dict(decision or {})
    _require(d.get("scope") == M300_SCOPE, "M301 M300 scope inatteso.")
    _require(d.get("version") == M300_VERSION, "M301 M300 version inattesa.")
    wallet = str(d.get("wallet") or "")
    _require(wallet in TARGETS.values(), "M301 wallet non approvato da M300.")
    _require(d.get("promotion_eligible") is True, "M301 richiede M300 promotion_eligible=true.")
    _require(d.get("promotion_armed") is False, "M301 rifiuta M300 armato.")
    _require(d.get("promotion_executed") is False, "M301 rifiuta promotion già eseguita.")

    legacy = dict(d.get("legacy_endpoint") or {})
    _require(legacy.get("compatible") is False, "M301 legacy endpoint non deve essere compatibile.")
    _require(legacy.get("gen4_copyability_pass_invented") is False, "M301 falso Gen4 PASS rilevato.")
    _require(legacy.get("must_not_be_called_from_m300") is True, "M301 legacy boundary assente.")

    lifecycle = dict(d.get("future_selective_lifecycle_bridge") or {})
    _require(lifecycle.get("required") is True, "M301 bridge non richiesto dal decision package.")
    _require(lifecycle.get("implemented_by_m300_pre") is False, "M301 M300 dichiara bridge già implementato.")
    _require(lifecycle.get("candidate_fastpath_entry_evidence_backfilled") is False, "M301 backfill candidato vietato.")
    _require(lifecycle.get("full_lifecycle_proof_starts_at_promotion_activation") is True, "M301 anchor lifecycle invalido.")

    claims = dict(d.get("formal_claims") or {})
    for key in (
        "m74_pass_claimed",
        "legacy_m75_pass_claimed",
        "gen4_copyability_pass_claimed",
        "m298_pass_claimed",
        "micro_live_ready_claimed",
    ):
        _require(claims.get(key) is False, f"M301 formal claim vietato: {key}.")

    safety = dict(d.get("safety") or {})
    _require(_integer(safety.get("database_writes"), -1) == 0, "M301 M300 DB writes non zero.")
    _require(_integer(safety.get("backend_mutations"), -1) == 0, "M301 M300 backend mutations non zero.")
    _require(safety.get("railway_variable_set") is False, "M301 M300 Railway mutation.")
    _require(_integer(safety.get("provider_mutations"), -1) == 0, "M301 M300 provider mutation.")
    _require(safety.get("live_execution") is False, "M301 M300 LIVE non disarmato.")
    _require(safety.get("signer_access") is False, "M301 M300 signer non disarmato.")
    _require(_integer(safety.get("submitted_transactions"), -1) == 0, "M301 M300 submission non zero.")
    _require(_integer(safety.get("paper_orders"), -1) == 0, "M301 M300 paper non zero.")
    return d


def sign_promotion_decision_envelope(
    m300_decision: dict[str, Any],
    *,
    acquisition_report_sha256: str,
    evaluated_at: datetime | str,
) -> dict[str, Any]:
    d = validate_m300_decision(m300_decision)
    observed = _aware(evaluated_at)
    _require(observed is not None, "M301 decision evaluated_at invalido.")
    acquisition_sha = _sha64(acquisition_report_sha256)

    payload: dict[str, Any] = {
        "scope": M301_DECISION_ENVELOPE_SCOPE,
        "version": M301_DECISION_ENVELOPE_VERSION,
        "wallet": str(d["wallet"]),
        "evaluated_at_utc": observed.isoformat(),
        "m300_decision": d,
        "lineage": {
            "m296_report_sha256": M296_REPORT_SHA256,
            "m297_anchor_utc": M297_ANCHOR_UTC,
            "m297_report_sha256": M297_REPORT_SHA256,
            "m298_report_sha256": M298_REPORT_SHA256,
            "m299_report_sha256": M299_REPORT_SHA256,
            "m300_report_sha256": M300_REPORT_SHA256,
            "m300_acquisition_report_sha256": acquisition_sha,
        },
        "formal_claims": {
            "m74_pass_claimed": False,
            "legacy_m75_pass_claimed": False,
            "gen4_copyability_pass_claimed": False,
            "m298_pass_claimed": False,
            "micro_live_ready_claimed": False,
        },
        "safety": {
            "promotion_armed": False,
            "bridge_implemented": False,
            "bridge_armed": False,
            "database_writes": 0,
            "backend_mutations": 0,
            "railway_variable_set": False,
            "provider_mutations": 0,
            "live": False,
            "signer": False,
            "submission": False,
            "paper_orders": 0,
        },
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload


def validate_promotion_decision_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    e = dict(envelope or {})
    _require(e.get("scope") == M301_DECISION_ENVELOPE_SCOPE, "M301 decision envelope scope inatteso.")
    _require(e.get("version") == M301_DECISION_ENVELOPE_VERSION, "M301 decision envelope version inattesa.")
    validate_m300_decision(dict(e.get("m300_decision") or {}))
    _require(_aware(e.get("evaluated_at_utc")) is not None, "M301 decision envelope time invalido.")
    lineage = dict(e.get("lineage") or {})
    _sha64(lineage.get("m300_acquisition_report_sha256"))
    _require(lineage.get("m297_anchor_utc") == M297_ANCHOR_UTC, "M301 anchor lineage inattesa.")
    _require(lineage.get("m300_report_sha256") == M300_REPORT_SHA256, "M301 M300 report lineage inattesa.")

    integrity = dict(e.get("integrity") or {})
    expected = str(integrity.get("payload_sha256") or "")
    _require(
        len(expected) == 64 and expected == canonical_sha256(_without_integrity(e)),
        "M301 decision envelope hash non valido.",
    )
    safety = dict(e.get("safety") or {})
    _require(safety.get("promotion_armed") is False, "M301 envelope promotion armata.")
    _require(safety.get("bridge_implemented") is False, "M301 envelope bridge implementato.")
    _require(safety.get("bridge_armed") is False, "M301 envelope bridge armato.")
    return e


def validate_operational_policy_snapshot(policy: dict[str, Any]) -> dict[str, Any]:
    p = dict(policy or {})
    required = (
        "simulated_input_lamports",
        "slippage_bps",
        "max_quote_latency_ms",
        "max_price_impact_bps",
        "max_price_deterioration_bps",
        "estimated_network_fee_lamports",
    )
    missing = [k for k in required if k not in p]
    _require(not missing, "M301 operational policy incompleta: " + ",".join(missing))

    m298 = validate_m298_policy()

    _require(_integer(p.get("simulated_input_lamports"), 0) > 0, "M301 input lamports non positivo.")
    _require(1 <= _integer(p.get("slippage_bps"), 0) <= 10_000, "M301 slippage invalido.")
    _require(
        0 <= _integer(p.get("estimated_network_fee_lamports"), -1),
        "M301 estimated fee invalida.",
    )

    latency = _integer(p.get("max_quote_latency_ms"), 10**9)
    impact = _finite(p.get("max_price_impact_bps"))
    deterioration = _finite(p.get("max_price_deterioration_bps"))
    _require(
        latency <= int(m298["maximum_accepted_p95_end_to_quote_ms"]),
        "M301 policy latency più permissiva di M298.",
    )
    _require(
        impact is not None and impact <= float(m298["maximum_accepted_p95_price_impact_bps"]),
        "M301 policy impact più permissiva di M298.",
    )
    _require(
        deterioration is not None
        and deterioration <= float(m298["maximum_accepted_p95_price_deterioration_bps"]),
        "M301 policy deterioration più permissiva di M298.",
    )
    _require(p.get("live_execution") is False, "M301 operational policy LIVE non false.")
    _require(p.get("paper_execution") is False, "M301 operational policy PAPER non false.")
    _require(p.get("automatic_live_activation") is False, "M301 auto-live non false.")
    return p


def build_activation_blueprint(
    decision_envelope: dict[str, Any],
    *,
    operational_policy_snapshot: dict[str, Any],
    operational_policy_source_sha256: str,
    activation_at: datetime | str,
) -> dict[str, Any]:
    envelope = validate_promotion_decision_envelope(decision_envelope)
    policy = validate_operational_policy_snapshot(operational_policy_snapshot)
    policy_source_sha = _sha64(operational_policy_source_sha256)

    activated = _aware(activation_at)
    evaluated = _aware(envelope.get("evaluated_at_utc"))
    m297_anchor = _aware(M297_ANCHOR_UTC)
    _require(activated is not None and evaluated is not None and m297_anchor is not None, "M301 activation time invalido.")
    _require(activated >= evaluated, "M301 activation precedente alla decision.")
    _require(activated > m297_anchor, "M301 activation deve essere post M297 anchor.")

    wallet = str(envelope.get("wallet") or "")
    frozen_policy = {
        "policy_source": "ACTIVE_OPERATIONAL_COPYABILITY_POLICY_AT_ACTIVATION",
        "policy_source_sha256": policy_source_sha,
        "simulated_input_lamports": int(policy["simulated_input_lamports"]),
        "slippage_bps": int(policy["slippage_bps"]),
        "max_quote_latency_ms": int(policy["max_quote_latency_ms"]),
        "max_price_impact_bps": float(policy["max_price_impact_bps"]),
        "max_price_deterioration_bps": float(policy["max_price_deterioration_bps"]),
        "estimated_network_fee_lamports": int(policy["estimated_network_fee_lamports"]),
        "live_execution": False,
        "paper_execution": False,
        "automatic_live_activation": False,
    }
    frozen_policy["policy_hash"] = canonical_sha256(frozen_policy)

    payload: dict[str, Any] = {
        "scope": M301_ACTIVATION_BLUEPRINT_SCOPE,
        "version": M301_ACTIVATION_BLUEPRINT_VERSION,
        "wallet": wallet,
        "activation_anchor_utc": activated.isoformat(),
        "initial_status": ACTIVATION_ACTIVE,
        "decision_envelope_sha256": str(
            dict(envelope.get("integrity") or {}).get("payload_sha256") or ""
        ),
        "frozen_operational_policy": frozen_policy,
        "runtime_route": {
            "input_runtime": "EXISTING_SEPARATE_CANDIDATE_WSS",
            "candidate_watchlist_membership_required": True,
            "helius_provider_union_change_required": False,
            "legacy_start_qualified_candidate_required": False,
            "official_campaign_required": False,
            "pre_activation_event_backfill": False,
            "buy_after_anchor_can_create_promoted_position": True,
            "sell_after_anchor_can_update_promoted_open_positions": True,
            "candidate_event_observation_scope_remains_unchanged": True,
        },
        "database_route": {
            "activation_table": PROMOTED_ACTIVATION_TABLE,
            "position_table": PROMOTED_POSITION_TABLE,
            "official_position_table_unchanged": True,
            "official_position_table": OFFICIAL_POSITION_TABLE,
            "official_scope_unchanged": OFFICIAL_SELECTIVE_SCOPE,
            "promoted_scope": PROMOTED_SELECTIVE_SCOPE,
            "foreign_key_strategy": "POSITION_ACTIVATION_ID_TO_PROMOTED_ACTIVATION",
            "campaign_id_required": False,
        },
        "lifecycle": {
            "full_lifecycle_proof_starts_at_activation_anchor": True,
            "prepromotion_backfill": False,
            "entry_policy_matches_frozen_operational_policy": True,
            "exit_policy_uses_same_frozen_slippage_latency_impact_and_fee": True,
            "partial_exit_allocation": "PRO_RATA",
            "dust_close_fraction": 0.001,
            "close_reason": "MIRRORED_WALLET_EXIT",
            "m299_requires_future_promoted_adapter": True,
            "m298_qualification_not_satisfied_by_activation": True,
            "m298_observation_hours_still_required": 24.0,
            "m298_entry_attempts_still_required": 20,
            "m298_closed_trades_still_required": 10,
        },
        "activation_state_machine": {
            "states": [ACTIVATION_ACTIVE, ACTIVATION_DRAINING, ACTIVATION_STOPPED],
            "ACTIVE": {
                "allow_new_buy_entries": True,
                "allow_sell_lifecycle": True,
            },
            "DRAINING": {
                "allow_new_buy_entries": False,
                "allow_sell_lifecycle": True,
                "purpose": "CLOSE_EXISTING_POSITIONS_WITHOUT_NEW_RISK",
            },
            "STOPPED": {
                "allow_new_buy_entries": False,
                "allow_sell_lifecycle": False,
                "requires_zero_open_positions": True,
            },
        },
        "formal_claims": {
            "m74_pass_claimed": False,
            "legacy_m75_pass_claimed": False,
            "gen4_copyability_pass_claimed": False,
            "m298_pass_claimed": False,
            "micro_live_ready_claimed": False,
            "micro_live_execution_authorized": False,
        },
        "safety": {
            "design_only": True,
            "bridge_implemented": False,
            "bridge_armed": False,
            "automatic_promotion": False,
            "database_writes": 0,
            "backend_mutations": 0,
            "railway_variable_set": False,
            "provider_mutations": 0,
            "helius_calls": 0,
            "birdeye_cu": 0,
            "jupiter_requests": 0,
            "live": False,
            "signer": False,
            "submission": False,
            "paper_orders": 0,
            "commit": False,
            "push": False,
            "deploy": False,
        },
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload


def validate_activation_transition(
    current_status: str,
    next_status: str,
    *,
    open_positions: int,
) -> dict[str, Any]:
    current = str(current_status or "").upper()
    nxt = str(next_status or "").upper()
    _require(current in ACTIVATION_STATUSES, "M301 current activation status invalido.")
    _require(nxt in ACTIVATION_STATUSES, "M301 next activation status invalido.")
    _require(open_positions >= 0, "M301 open positions negativo.")

    allowed = False
    reason = "TRANSITION_NOT_ALLOWED"
    if current == nxt:
        allowed = True
        reason = "IDEMPOTENT"
    elif current == ACTIVATION_ACTIVE and nxt == ACTIVATION_DRAINING:
        allowed = True
        reason = "DRAIN_NEW_ENTRIES_STOPPED_SELLS_CONTINUE"
    elif current == ACTIVATION_DRAINING and nxt == ACTIVATION_STOPPED:
        allowed = open_positions == 0
        reason = (
            "ZERO_OPEN_POSITIONS"
            if allowed else "OPEN_POSITIONS_MUST_REACH_ZERO_BEFORE_STOP"
        )

    return {
        "current_status": current,
        "next_status": nxt,
        "open_positions": int(open_positions),
        "allowed": allowed,
        "reason": reason,
        "automatic_transition": False,
    }


def event_is_lifecycle_eligible(
    activation_blueprint: dict[str, Any],
    *,
    event_received_at: datetime | str,
    side: str,
    activation_status: str,
) -> dict[str, Any]:
    blueprint = dict(activation_blueprint or {})
    _require(
        blueprint.get("scope") == M301_ACTIVATION_BLUEPRINT_SCOPE,
        "M301 activation blueprint scope inatteso.",
    )
    event_at = _aware(event_received_at)
    anchor = _aware(blueprint.get("activation_anchor_utc"))
    _require(event_at is not None and anchor is not None, "M301 event/anchor time invalido.")
    status = str(activation_status or "").upper()
    _require(status in ACTIVATION_STATUSES, "M301 activation status invalido.")
    normalized_side = str(side or "").upper()
    _require(normalized_side in {"BUY", "SELL"}, "M301 lifecycle side invalido.")

    post_anchor = event_at > anchor
    if not post_anchor:
        allowed = False
        reason = "PRE_ACTIVATION_EVENT_NO_BACKFILL"
    elif status == ACTIVATION_ACTIVE:
        allowed = True
        reason = "ACTIVE_POST_ANCHOR"
    elif status == ACTIVATION_DRAINING and normalized_side == "SELL":
        allowed = True
        reason = "DRAINING_SELL_ONLY"
    elif status == ACTIVATION_DRAINING:
        allowed = False
        reason = "DRAINING_NEW_BUY_BLOCKED"
    else:
        allowed = False
        reason = "STOPPED"

    return {
        "post_activation_anchor": post_anchor,
        "side": normalized_side,
        "activation_status": status,
        "lifecycle_allowed": allowed,
        "reason": reason,
        "prepromotion_backfill": False,
    }


def database_blueprint() -> dict[str, Any]:
    return {
        "activation_table": {
            "name": PROMOTED_ACTIVATION_TABLE,
            "purpose": "IMMUTABLE_PROMOTION_LINEAGE_AND_STATE",
            "columns_required": [
                "id",
                "activation_id",
                "wallet_address",
                "status",
                "activation_anchor_at",
                "decision_envelope_sha256",
                "policy_hash",
                "policy_snapshot",
                "evidence",
                "created_at",
                "updated_at",
                "draining_at",
                "stopped_at",
            ],
            "constraints_required": [
                "status IN ('ACTIVE','DRAINING','STOPPED')",
                "activation_anchor_at IS NOT NULL",
                "decision_envelope_sha256 LENGTH 64",
                "policy_hash LENGTH 64",
            ],
            "indexes_required": [
                "UNIQUE activation_id",
                "PARTIAL UNIQUE wallet_address WHERE status IN ('ACTIVE','DRAINING')",
            ],
        },
        "position_table": {
            "name": PROMOTED_POSITION_TABLE,
            "purpose": "PROMOTED_CHALLENGER_FULL_LIFECYCLE_ONLY",
            "scope_exact": PROMOTED_SELECTIVE_SCOPE,
            "mirrors_official_economic_columns": True,
            "foreign_key": "activation_db_id -> promoted_selective_activations.id ON DELETE CASCADE",
            "unique_constraints": [
                "position_id",
                "wallet_address + entry_signature",
                "entry_fast_event_id",
            ],
            "required_lineage": [
                "activation_db_id",
                "activation_id",
                "entry_fast_event_id",
                "entry_received_at > activation_anchor_at",
            ],
        },
        "official_table": {
            "name": OFFICIAL_POSITION_TABLE,
            "scope_exact": OFFICIAL_SELECTIVE_SCOPE,
            "schema_or_check_constraint_change_required": False,
            "rows_shared_with_promoted_lane": False,
        },
    }


def runtime_blueprint() -> dict[str, Any]:
    return {
        "candidate_recorder_hook": {
            "function": "record_fastpath_candidate_notification",
            "event_table_remains_shared": True,
            "candidate_observation_scope_remains_M117E": True,
            "lookup_active_promotion_after_signal_parse": True,
            "BUY": (
                "IF post-anchor AND activation ACTIVE AND existing candidate quote accepted, "
                "create promoted position in dedicated table using frozen activation policy."
            ),
            "SELL": (
                "IF post-anchor AND activation ACTIVE/DRAINING, quote mirrored exit and "
                "apply pro-rata only to promoted open positions for activation+wallet+token."
            ),
        },
        "no_provider_bridge": {
            "candidate_separate_wss_reused": True,
            "helius_provider_union_mutation": False,
            "legacy_copyability_campaign_creation": False,
            "legacy_start_qualified_candidate_call": False,
        },
        "isolation": {
            "official_position_table_touched": False,
            "copyability_campaign_metrics_mutated": False,
            "m75_metrics_mutated": False,
            "m75_thresholds_changed": False,
            "pam_changed": False,
            "candidate_pre_activation_events_backfilled": False,
        },
        "future_required_code_changes": [
            "NEW_ALEMBIC_MIGRATION_FOR_PROMOTED_ACTIVATION_AND_POSITION_TABLES",
            "NEW_SQLALCHEMY_MODELS_FOR_DEDICATED_TABLES",
            "CANDIDATE_RECORDER_PROMOTION_REGISTRY_LOOKUP",
            "PROMOTED_BUY_POSITION_CREATION_HELPER",
            "PROMOTED_SELL_LIFECYCLE_HELPER",
            "PROMOTED_STATUS_READ_MODEL",
            "M299_PROMOTED_LIFECYCLE_ADAPTER",
            "EXPLICIT_ACTIVATE_DRAIN_STOP_ADMIN_CONTRACT",
        ],
    }


def build_preparation_report() -> dict[str, Any]:
    db = database_blueprint()
    runtime = runtime_blueprint()
    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M301_SCOPE,
        "version": M301_VERSION,
        "state": "DESIGN_VERIFIED_DISARMED_NOT_IMPLEMENTED",
        "targets": TARGETS,
        "lineage": {
            "m296_report_sha256": M296_REPORT_SHA256,
            "m297_anchor_utc": M297_ANCHOR_UTC,
            "m297_report_sha256": M297_REPORT_SHA256,
            "m298_report_sha256": M298_REPORT_SHA256,
            "m299_report_sha256": M299_REPORT_SHA256,
            "m300_report_sha256": M300_REPORT_SHA256,
        },
        "architecture": {
            "input_runtime": "EXISTING_SEPARATE_CANDIDATE_WSS",
            "provider_change_required": False,
            "legacy_qualified_candidate_endpoint_required": False,
            "new_dedicated_activation_table": PROMOTED_ACTIVATION_TABLE,
            "new_dedicated_position_table": PROMOTED_POSITION_TABLE,
            "official_position_table_unchanged": True,
            "official_scope_constraint_unchanged": True,
            "candidate_event_scope_unchanged": True,
            "prepromotion_backfill": False,
            "full_lifecycle_proof_starts_at_activation": True,
            "state_machine": "ACTIVE->DRAINING->STOPPED",
        },
        "database_blueprint": db,
        "runtime_blueprint": runtime,
        "readiness_boundary": {
            "promotion_eligibility_is_not_m298_pass": True,
            "activation_is_not_m298_pass": True,
            "activation_is_not_micro_live_readiness": True,
            "m298_post_activation_24h_required": True,
            "m298_post_activation_20_attempts_required": True,
            "m298_post_activation_10_closed_required": True,
            "minimum_independent_wallets_remains_2": True,
        },
        "safety": {
            "design_only": True,
            "bridge_implemented": False,
            "bridge_armed": False,
            "automatic_promotion": False,
            "database_reads": 0,
            "database_writes": 0,
            "backend_calls": 0,
            "railway_variable_set": False,
            "provider_mutations": 0,
            "helius_calls": 0,
            "birdeye_cu": 0,
            "jupiter_requests": 0,
            "commit": False,
            "push": False,
            "deploy": False,
            "live": False,
            "signer": False,
            "submission": False,
            "paper_orders": 0,
            "m74_changed": False,
            "m75_changed": False,
            "pam_changed": False,
        },
    }
    payload["integrity"] = {"report_payload_sha256": canonical_sha256(payload)}
    return payload


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    r = dict(report or {})
    _require(r.get("evaluation") == "PASS", "M301 report non PASS.")
    _require(r.get("scope") == M301_SCOPE, "M301 report scope inatteso.")
    _require(r.get("version") == M301_VERSION, "M301 report version inattesa.")
    integrity = dict(r.get("integrity") or {})
    expected = str(integrity.get("report_payload_sha256") or "")
    _require(
        len(expected) == 64 and expected == canonical_sha256(_without_integrity(r)),
        "M301 report hash non valido.",
    )
    safety = dict(r.get("safety") or {})
    _require(safety.get("design_only") is True, "M301 non design-only.")
    _require(safety.get("bridge_implemented") is False, "M301 bridge implementato.")
    _require(safety.get("bridge_armed") is False, "M301 bridge armato.")
    _require(safety.get("automatic_promotion") is False, "M301 auto promotion attiva.")
    for key in (
        "database_reads",
        "database_writes",
        "backend_calls",
        "provider_mutations",
        "helius_calls",
        "birdeye_cu",
        "jupiter_requests",
        "paper_orders",
    ):
        _require(_integer(safety.get(key), -1) == 0, f"M301 safety violata: {key}.")
    for key in ("commit", "push", "deploy", "live", "signer", "submission"):
        _require(safety.get(key) is False, f"M301 safety violata: {key}.")
    return r
