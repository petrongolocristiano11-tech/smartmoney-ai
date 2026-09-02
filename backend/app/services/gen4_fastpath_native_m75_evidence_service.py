from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4FastpathSelectivePosition,
    CanonicalParserGen4FastpathShadowEvent,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
    evaluate_m75_canary,
    sign_canary_evidence,
    validate_policy,
)

FASTPATH_NATIVE_M75_BRIDGE_VERSION = "m282-fastpath-native-m75-evidence-bridge/1"
FASTPATH_NATIVE_M75_BRIDGE_SCOPE = "M282_FASTPATH_NATIVE_M75_EVIDENCE_BRIDGE_DISARMED"
FASTPATH_SELECTIVE_SCOPE = "OFFICIAL_FASTPATH_SELECTIVE"
FASTPATH_NATIVE_M75_FORMAL_ARMED = False
WEBHOOK_SOURCE = "WEBHOOK"

_POLICY_REJECTION_CODES = {
    "PRICE_ALREADY_MOVED",
    "QUOTE_TOO_SLOW",
    "NO_EXECUTABLE_OUTPUT",
    "PRICE_IMPACT_TOO_HIGH",
    "UNSIGNED_TRANSACTION_NOT_BUILT",
}


def _aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(value: Any) -> str | None:
    dt = _aware(value)
    return dt.isoformat() if dt is not None else None


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _campaign_formal_m74(campaign: Any) -> bool:
    selection = _dict(_get(campaign, "selection_snapshot", {}))
    return selection.get("formal_m74_pass") is True


def _campaign_id(campaign: Any) -> str:
    return str(_get(campaign, "campaign_id", "") or "")


def _campaign_db_id(campaign: Any) -> int | None:
    value = _get(campaign, "id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _receipt_by_signature(receipts: Iterable[Any]) -> dict[str, Any]:
    by_sig: dict[str, Any] = {}
    for row in receipts:
        if str(_get(row, "source", "") or "") != WEBHOOK_SOURCE:
            continue
        if _get(row, "auth_verified") is not True:
            continue
        sig = str(_get(row, "signature", "") or "")
        if not sig:
            continue
        current = by_sig.get(sig)
        if current is None:
            by_sig[sig] = row
            continue
        old = _aware(_get(current, "received_at"))
        new = _aware(_get(row, "received_at"))
        if new is not None and (old is None or new < old):
            by_sig[sig] = row
    return by_sig


def _end_to_quote_ms(event: Any, receipt: Any | None, policy: dict[str, Any]) -> float:
    quote_at = _aware(_get(event, "fast_quote_received_at"))
    block_at = _aware(_get(receipt, "block_time")) if receipt is not None else None
    if quote_at is not None and block_at is not None:
        return max(0.0, (quote_at - block_at).total_seconds() * 1000.0)
    stored = _get(event, "fast_end_to_quote_ms")
    if stored is not None:
        try:
            return max(0.0, float(stored))
        except (TypeError, ValueError):
            pass
    received = _aware(_get(event, "fast_received_at"))
    if quote_at is not None and received is not None:
        return max(0.0, (quote_at - received).total_seconds() * 1000.0)
    prequote = _get(event, "fast_prequote_ms")
    quote_latency = _get(event, "fast_quote_latency_ms")
    if prequote is not None and quote_latency is not None:
        try:
            return max(0.0, float(prequote) + float(quote_latency))
        except (TypeError, ValueError):
            pass
    # Missing timing must never look fast in the M75 percentile calculation.
    return float(policy["canary_maximum_p95_end_to_quote_ms"]) + 1.0


def _metric_or_fail(value: Any, limit: float) -> float:
    if value is None:
        return float(limit) + 1.0
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(limit) + 1.0
    return result


def _entry_worker_failure_codes(event: Any) -> list[str]:
    codes: list[str] = []
    parse_error = str(_get(event, "parse_error_code", "") or "").strip()
    quote_error = str(_get(event, "quote_error_code", "") or "").strip()
    if parse_error:
        codes.append(f"PARSE:{parse_error}")
    if quote_error:
        codes.append(f"QUOTE:{quote_error}")
    reason = str(_get(event, "fast_provisional_rejection_reason", "") or "").strip()
    if reason and reason not in _POLICY_REJECTION_CODES and reason != "NOT_A_BUY_SIGNAL":
        codes.append(f"UNMAPPED_REJECTION:{reason}")
    if str(_get(event, "side", "") or "").upper() == "BUY":
        if _get(event, "fast_quote_received_at") is None and not quote_error:
            codes.append("INCOMPLETE_BUY_QUOTE_EVIDENCE")
    return sorted(set(codes))


def _entry_policy_violation(event: Any, receipt: Any | None) -> bool:
    if not bool(_get(event, "fast_provisional_copyable", False)):
        return False
    snapshot = _dict(_get(event, "policy_snapshot", {}))
    max_quote = float(snapshot.get("max_quote_latency_ms", 5000))
    max_impact = float(snapshot.get("max_price_impact_bps", 500))
    max_det = float(snapshot.get("max_price_deterioration_bps", 1000))
    max_age = float(snapshot.get("max_signal_age_ms", 20000))
    quote_latency = _get(event, "fast_quote_latency_ms")
    impact = _get(event, "fast_price_impact_bps")
    deterioration = _get(event, "fast_price_deterioration_bps")
    if quote_latency is None or float(quote_latency) > max_quote:
        return True
    if impact is None or float(impact) > max_impact:
        return True
    if deterioration is None or float(deterioration) > max_det:
        return True
    if not bool(_get(event, "fast_transaction_built", False)):
        return True
    quote_at = _aware(_get(event, "fast_quote_received_at"))
    block_at = _aware(_get(receipt, "block_time")) if receipt is not None else None
    if quote_at is not None and block_at is not None:
        if (quote_at - block_at).total_seconds() * 1000.0 > max_age:
            return True
    return False


def _exit_failure_rows(position: Any) -> list[dict[str, Any]]:
    evidence = _dict(_get(position, "evidence", {}))
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in list(evidence.get("exit_failures") or []):
        if not isinstance(raw, dict):
            continue
        sig = str(raw.get("signature") or "")
        code = str(raw.get("code") or "UNKNOWN")
        key = (sig, code)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "event_type": "WORKER_FAILURE",
                "timestamp_utc": _iso(raw.get("observed_at")) or _iso(_get(position, "closed_at")) or _iso(_get(position, "opened_at")),
                "worker_failure": True,
                "policy_violation": False,
                "failure_code": f"EXIT:{code}",
                "signature": sig or None,
            }
        )
    return out


def _exit_policy_violation(position: Any, campaign: Any) -> bool:
    if str(_get(position, "status", "") or "") != "CLOSED":
        return False
    if not bool(_get(position, "exit_copyable", False)):
        return True
    if not bool(_get(position, "exit_transaction_built", False)):
        return True
    latency = _get(position, "exit_quote_latency_ms")
    impact = _get(position, "exit_price_impact_bps")
    max_quote = float(_get(campaign, "max_quote_latency_ms", 5000) or 5000)
    max_impact = float(_get(campaign, "max_price_impact_bps", 500) or 500)
    if latency is None or float(latency) > max_quote:
        return True
    if impact is None or float(impact) > max_impact:
        return True
    return False


def build_fastpath_native_m75_bridge(
    *,
    wallet: str,
    events: list[Any],
    positions: list[Any],
    receipts: list[Any],
    campaign: Any,
    terminal_at: datetime,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = validate_policy(policy)
    receipt_map = _receipt_by_signature(receipts)
    wallet_events = [
        row
        for row in events
        if str(_get(row, "wallet_address", "") or "") == wallet
    ]
    wallet_events.sort(key=lambda row: _aware(_get(row, "fast_received_at")) or datetime.min.replace(tzinfo=timezone.utc))
    buys = [row for row in wallet_events if str(_get(row, "side", "") or "").upper() == "BUY"]
    wallet_positions = [
        row
        for row in positions
        if str(_get(row, "wallet_address", "") or "") == wallet
        and str(_get(row, "scope", "") or "") == FASTPATH_SELECTIVE_SCOPE
    ]

    records: list[dict[str, Any]] = []
    worker_failure_codes: list[str] = []
    policy_violation_codes: list[str] = []

    for event in buys:
        sig = str(_get(event, "signature", "") or "")
        receipt = receipt_map.get(sig)
        failures = _entry_worker_failure_codes(event)
        worker_failure_codes.extend(failures)
        violation = _entry_policy_violation(event, receipt)
        if violation:
            policy_violation_codes.append(f"ENTRY:{sig or 'UNKNOWN'}")
        records.append(
            {
                "event_type": "ENTRY_ATTEMPT",
                "timestamp_utc": _iso(_get(event, "fast_received_at")),
                "signature": sig,
                "webhook_covered": receipt is not None,
                "unsigned_build_success": bool(_get(event, "fast_transaction_built", False)),
                "entry_rejected": not bool(_get(event, "fast_provisional_copyable", False)),
                "end_to_quote_ms": _end_to_quote_ms(event, receipt, p),
                "price_impact_bps": _metric_or_fail(
                    _get(event, "fast_price_impact_bps"),
                    float(p["canary_maximum_p95_price_impact_bps"]),
                ),
                "price_deterioration_bps": _metric_or_fail(
                    _get(event, "fast_price_deterioration_bps"),
                    float(p["canary_maximum_p95_price_deterioration_bps"]),
                ),
                "worker_failure": bool(failures),
                "policy_violation": violation,
                "failure_codes": failures,
                "decision_source": "FASTPATH_PROVISIONAL",
                "webhook_role": "POSTHOC_RECONCILIATION_ONLY",
            }
        )

    # Parse failures where side could not be classified must still fail M75 instead of disappearing.
    buy_ids = {id(row) for row in buys}
    for event in wallet_events:
        if id(event) in buy_ids:
            continue
        parse_error = str(_get(event, "parse_error_code", "") or "").strip()
        if not parse_error:
            continue
        code = f"PARSE:{parse_error}"
        worker_failure_codes.append(code)
        records.append(
            {
                "event_type": "WORKER_FAILURE",
                "timestamp_utc": _iso(_get(event, "fast_received_at")),
                "signature": str(_get(event, "signature", "") or ""),
                "worker_failure": True,
                "policy_violation": False,
                "failure_code": code,
            }
        )

    valid_closed = []
    for position in wallet_positions:
        exit_failures = _exit_failure_rows(position)
        records.extend(exit_failures)
        for failure in exit_failures:
            worker_failure_codes.append(str(failure.get("failure_code") or "EXIT:UNKNOWN"))
        if str(_get(position, "status", "") or "") != "CLOSED":
            continue
        if _get(position, "closed_at") is None:
            worker_failure_codes.append("CLOSED_POSITION_MISSING_TIMESTAMP")
            records.append(
                {
                    "event_type": "WORKER_FAILURE",
                    "timestamp_utc": _iso(_get(position, "opened_at")),
                    "worker_failure": True,
                    "policy_violation": False,
                    "failure_code": "CLOSED_POSITION_MISSING_TIMESTAMP",
                }
            )
            continue
        if int(_get(position, "remaining_token_raw", 0) or 0) != 0:
            policy_violation_codes.append(f"CLOSED_WITH_REMAINING:{_get(position, 'position_id', '')}")
            continue
        if not bool(_get(position, "exit_copyable", False)):
            policy_violation_codes.append(f"CLOSED_NONCOPYABLE:{_get(position, 'position_id', '')}")
            continue
        valid_closed.append(position)
        exit_violation = _exit_policy_violation(position, campaign)
        if exit_violation:
            policy_violation_codes.append(f"EXIT:{_get(position, 'position_id', '')}")
        records.append(
            {
                "event_type": "CLOSED_TRADE",
                "timestamp_utc": _iso(_get(position, "closed_at")),
                "position_id": str(_get(position, "position_id", "") or ""),
                "entry_signature": str(_get(position, "entry_signature", "") or ""),
                "pnl_lamports": int(_get(position, "pnl_lamports", 0) or 0),
                "worker_failure": False,
                "policy_violation": exit_violation,
            }
        )

    # Fail closed on duplicate codes only once for terminal unresolved count.
    unique_failures = sorted(set(code for code in worker_failure_codes if code))
    unique_violations = sorted(set(code for code in policy_violation_codes if code))
    open_count = sum(
        str(_get(row, "status", "") or "") in {"OPEN", "OPEN_PARTIAL"}
        and int(_get(row, "remaining_token_raw", 0) or 0) > 0
        for row in wallet_positions
    )
    records.append(
        {
            "event_type": "CANARY_TERMINAL_STATE",
            "timestamp_utc": _iso(terminal_at),
            "open_position_count": int(open_count),
            "unresolved_failure_count": len(unique_failures),
            "worker_failure": False,
            "policy_violation": bool(unique_violations),
            "policy_violation_codes": unique_violations,
            "terminal_source": "M282_DISARMED_SNAPSHOT",
        }
    )

    formal_m74 = _campaign_formal_m74(campaign)
    actual = evaluate_m75_canary(wallet, records, admitted=formal_m74, policy=p)
    assuming_m74 = evaluate_m75_canary(wallet, records, admitted=True, policy=p)
    signed_evidence = sign_canary_evidence({wallet: records})
    payload: dict[str, Any] = {
        "scope": FASTPATH_NATIVE_M75_BRIDGE_SCOPE,
        "version": FASTPATH_NATIVE_M75_BRIDGE_VERSION,
        "state": "DISARMED_EVIDENCE_PROJECTION",
        "wallet": wallet,
        "campaign_id": _campaign_id(campaign),
        "formal_m74_admitted": formal_m74,
        "decision_source": "PROCESSED_WSS_FASTPATH",
        "webhook_role": "POSTHOC_RECONCILIATION_ONLY",
        "entry_attempt_source": "CANONICAL_PARSER_GEN4_FASTPATH_SHADOW_EVENTS",
        "closed_lifecycle_source": "CANONICAL_PARSER_GEN4_FASTPATH_SELECTIVE_POSITIONS",
        "terminal_source": "M282_DISARMED_SNAPSHOT",
        "worker_failure_mapping": "PARSE_QUOTE_EXIT_AND_INCOMPLETE_EVIDENCE_FAIL_CLOSED",
        "policy_violation_mapping": "ACCEPTED_ENTRY_OR_EXIT_CONTRADICTING_FROZEN_OPERATIONAL_POLICY",
        "records": records,
        "signed_m75_evidence": signed_evidence,
        "evaluation_with_actual_m74": actual,
        "diagnostic_evaluation_assuming_m74_only": assuming_m74,
        "formal_m75_claimed": False,
        "formal_m75_pass": False,
        "formal_m75_pass_reason": "M282_BRIDGE_DISARMED_NO_FORMAL_CLAIM",
        "micro_live_execution_authorized": False,
        "safety": {
            "formal_bridge_armed": FASTPATH_NATIVE_M75_FORMAL_ARMED,
            "m74_bypass": False,
            "m75_thresholds_changed": False,
            "pam_changed": False,
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
        },
    }
    payload["integrity"] = {
        "report_payload_sha256": canonical_sha256(payload),
        "m75_evidence_payload_sha256": str(
            _dict(signed_evidence.get("integrity")).get("payload_sha256") or ""
        ),
    }
    return payload


def load_fastpath_native_m75_bridge(
    db: Session,
    *,
    wallet: str,
    events: list[CanonicalParserGen4FastpathShadowEvent],
    anchor_utc: datetime,
    terminal_at: datetime | None = None,
) -> dict[str, Any]:
    anchor = _aware(anchor_utc)
    if anchor is None:
        raise ValueError("M282_ANCHOR_REQUIRED")
    relevant = [
        row
        for row in events
        if str(_get(row, "wallet_address", "") or "") == wallet
        and (_aware(_get(row, "fast_received_at")) or anchor) >= anchor
    ]
    campaign_ids = sorted(
        {
            str(_get(row, "campaign_id", "") or "")
            for row in relevant
            if str(_get(row, "campaign_id", "") or "")
        }
    )
    if len(campaign_ids) != 1:
        return {
            "scope": FASTPATH_NATIVE_M75_BRIDGE_SCOPE,
            "version": FASTPATH_NATIVE_M75_BRIDGE_VERSION,
            "state": "DISARMED_NOT_EVALUABLE",
            "wallet": wallet,
            "reason": "EXACT_ONE_CAMPAIGN_REQUIRED",
            "campaign_ids": campaign_ids,
            "formal_m75_claimed": False,
            "formal_m75_pass": False,
            "micro_live_execution_authorized": False,
        }
    campaign_id = campaign_ids[0]
    campaign = db.scalar(
        select(CanonicalParserGen4CopyabilityCampaign).where(
            CanonicalParserGen4CopyabilityCampaign.campaign_id == campaign_id
        )
    )
    if campaign is None:
        return {
            "scope": FASTPATH_NATIVE_M75_BRIDGE_SCOPE,
            "version": FASTPATH_NATIVE_M75_BRIDGE_VERSION,
            "state": "DISARMED_NOT_EVALUABLE",
            "wallet": wallet,
            "reason": "CAMPAIGN_NOT_FOUND",
            "campaign_id": campaign_id,
            "formal_m75_claimed": False,
            "formal_m75_pass": False,
            "micro_live_execution_authorized": False,
        }
    buy_signatures = sorted(
        {
            str(_get(row, "signature", "") or "")
            for row in relevant
            if str(_get(row, "side", "") or "").upper() == "BUY"
            and str(_get(row, "signature", "") or "")
        }
    )
    positions: list[CanonicalParserGen4FastpathSelectivePosition] = []
    receipts: list[CanonicalParserGen4WebhookReceipt] = []
    if buy_signatures:
        positions = list(
            db.scalars(
                select(CanonicalParserGen4FastpathSelectivePosition).where(
                    CanonicalParserGen4FastpathSelectivePosition.scope == FASTPATH_SELECTIVE_SCOPE,
                    CanonicalParserGen4FastpathSelectivePosition.campaign_id == campaign_id,
                    CanonicalParserGen4FastpathSelectivePosition.wallet_address == wallet,
                    CanonicalParserGen4FastpathSelectivePosition.entry_signature.in_(buy_signatures),
                )
            )
        )
        campaign_db_id = _campaign_db_id(campaign)
        if campaign_db_id is not None:
            receipts = list(
                db.scalars(
                    select(CanonicalParserGen4WebhookReceipt).where(
                        CanonicalParserGen4WebhookReceipt.campaign_db_id == campaign_db_id,
                        CanonicalParserGen4WebhookReceipt.signature.in_(buy_signatures),
                        CanonicalParserGen4WebhookReceipt.source == WEBHOOK_SOURCE,
                    )
                )
            )
        else:
            return {
                "scope": FASTPATH_NATIVE_M75_BRIDGE_SCOPE,
                "version": FASTPATH_NATIVE_M75_BRIDGE_VERSION,
                "state": "DISARMED_NOT_EVALUABLE",
                "wallet": wallet,
                "reason": "CAMPAIGN_DB_ID_MISSING",
                "campaign_id": campaign_id,
                "formal_m75_claimed": False,
                "formal_m75_pass": False,
                "micro_live_execution_authorized": False,
            }
    return build_fastpath_native_m75_bridge(
        wallet=wallet,
        events=relevant,
        positions=positions,
        receipts=receipts,
        campaign=campaign,
        terminal_at=_aware(terminal_at) or datetime.now(timezone.utc),
    )
