from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from backend.app.services.blockchain_parser_gen4_copyability_service import (
    CanonicalParserGen4CopyabilityError,
    parse_raw_copyability_signal,
)

M309_VERSION = "canonical-parser-gen4-promoted-selective-auth-delivery-coverage/1"
M309_SCOPE = "M309_PROMOTED_SELECTIVE_AUTHENTICATED_DELIVERY_COVERAGE"
M309_SOURCE = "WEBHOOK"
M309_MINIMUM_COVERAGE_PERCENT = 95.0


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_existing_raw_webhook_update(
    provider_detail: dict[str, Any],
    *,
    account_addresses: Iterable[str],
) -> dict[str, Any]:
    detail = dict(provider_detail or {})
    required = ("webhookURL", "webhookType", "authHeader", "txnStatus", "encoding")
    for key in required:
        if not str(detail.get(key) or "").strip():
            raise ValueError(f"M309_PROVIDER_DETAIL_MISSING:{key}")
    tx = [str(x) for x in (detail.get("transactionTypes") or [])]
    if "ANY" not in tx:
        raise ValueError("M309_PROVIDER_TRANSACTION_TYPES_ANY_REQUIRED")
    if str(detail.get("webhookType") or "").lower() != "raw":
        raise ValueError("M309_PROVIDER_RAW_WEBHOOK_REQUIRED")
    addresses = sorted({str(x).strip() for x in account_addresses if str(x).strip()})
    if not addresses:
        raise ValueError("M309_PROVIDER_ADDRESS_UNION_EMPTY")
    return {
        "webhookURL": detail["webhookURL"],
        "transactionTypes": tx,
        "accountAddresses": addresses,
        "webhookType": detail["webhookType"],
        "authHeader": detail["authHeader"],
        "txnStatus": detail["txnStatus"],
        "encoding": detail["encoding"],
    }


def evaluate_promoted_delivery_coverage(
    *,
    wallet: str,
    activation_id: str,
    clean_attempts: list[Any],
    delivery_receipts: list[Any],
    effective_anchor: datetime,
    terminal_at: datetime,
) -> dict[str, Any]:
    anchor = _aware(effective_anchor)
    terminal = _aware(terminal_at)
    if anchor is None or terminal is None or terminal < anchor:
        raise ValueError("M309_COVERAGE_TIME_BOUNDARY_INVALID")

    attempt_signatures = {
        str(_get(row, "signature", "") or "")
        for row in clean_attempts
        if str(_get(row, "signature", "") or "")
    }
    receipt_by_signature: dict[str, Any] = {}
    eligible_receipts: list[Any] = []
    for receipt in delivery_receipts:
        if str(_get(receipt, "wallet_address", "") or "") != wallet:
            continue
        if str(_get(receipt, "activation_id", "") or "") != activation_id:
            continue
        if str(_get(receipt, "source", "") or "") != M309_SOURCE:
            continue
        if _get(receipt, "auth_verified") is not True:
            continue
        occurred = _aware(_get(receipt, "block_time")) or _aware(_get(receipt, "received_at"))
        if occurred is None or occurred <= anchor or occurred > terminal:
            continue
        sig = str(_get(receipt, "signature", "") or "")
        if not sig:
            continue
        eligible_receipts.append(receipt)
        old = receipt_by_signature.get(sig)
        if old is None:
            receipt_by_signature[sig] = receipt
        else:
            old_at = _aware(_get(old, "received_at"))
            new_at = _aware(_get(receipt, "received_at"))
            if new_at is not None and (old_at is None or new_at < old_at):
                receipt_by_signature[sig] = receipt

    covered_signatures = sorted(attempt_signatures & set(receipt_by_signature))
    denominator = len(clean_attempts)
    coverage = 100.0 * len(covered_signatures) / denominator if denominator else 0.0

    webhook_only_buy_gaps: list[str] = []
    webhook_only_unclassified = 0
    for sig, receipt in receipt_by_signature.items():
        if sig in attempt_signatures:
            continue
        raw = _get(receipt, "raw_payload", {})
        raw = dict(raw) if isinstance(raw, dict) else {}
        try:
            signal = parse_raw_copyability_signal(raw, frozen_wallets=[wallet])
        except CanonicalParserGen4CopyabilityError:
            webhook_only_unclassified += 1
            continue
        if str(signal.side).upper() == "BUY":
            webhook_only_buy_gaps.append(sig)

    webhook_only_buy_gaps = sorted(set(webhook_only_buy_gaps))
    return {
        "scope": M309_SCOPE,
        "version": M309_VERSION,
        "numerator_auth_verified_webhook_signatures": len(covered_signatures),
        "denominator_clean_fastpath_buy_attempts": denominator,
        "webhook_coverage_percent": coverage,
        "covered_signatures": covered_signatures,
        "eligible_authenticated_receipt_count": len(eligible_receipts),
        "webhook_only_buy_gap_signatures": webhook_only_buy_gaps,
        "webhook_only_buy_gap_count": len(webhook_only_buy_gaps),
        "webhook_only_unclassified_receipt_count": webhook_only_unclassified,
        "coverage_threshold_percent": M309_MINIMUM_COVERAGE_PERCENT,
        "coverage_threshold_pass": coverage >= M309_MINIMUM_COVERAGE_PERCENT,
        "gap_technical_evidence_pass": len(webhook_only_buy_gaps) == 0,
        "wss_relabelled_as_webhook": False,
        "authenticated_secondary_delivery": True,
    }
