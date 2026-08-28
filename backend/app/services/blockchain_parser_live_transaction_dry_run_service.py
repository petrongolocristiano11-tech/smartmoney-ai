from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserIsolatedSignerProfile,
    CanonicalParserIsolatedSignerProfileEvent,
    CanonicalParserLiveTransactionDryRun,
    CanonicalParserMicroLiveCanaryPermit,
    CanonicalParserMicroLiveCanarySimulation,
)
from backend.app.models.live_platform_config import LivePlatformConfig
from backend.app.models.live_trading_policy import LiveTradingPolicy
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.solana_rpc import SolanaRpcClient

LIVE_TRANSACTION_DRY_RUN_POLICY_VERSION = (
    "canonical-parser-isolated-signer-live-transaction-dry-run/1"
)
SIGNER_PROFILE_ISSUE_PREFIX = "ISSUE_M36_ISOLATED_SIGNER_PROFILE"
SIGNER_PROFILE_REVOKE_PREFIX = "REVOKE_M36_ISOLATED_SIGNER_PROFILE"
TRANSACTION_DRY_RUN_PREFIX = "RUN_M36_LIVE_TRANSACTION_DRY_RUN"
WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"
_MONEY_QUANTUM = Decimal("0.000000001")
_PRICE_IMPACT_QUANTUM = Decimal("0.000001")
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {character: index for index, character in enumerate(_BASE58_ALPHABET)}


class CanonicalParserLiveTransactionDryRunError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    resolved = value or _utc_now()
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _actor(value: str | None) -> str:
    normalized = str(value or "MANUAL_OPERATOR").strip()
    return (normalized or "MANUAL_OPERATOR")[:80]


def _note(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = sanitize_error_message(value, max_length=500).strip()
    return normalized or None


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserLiveTransactionDryRunError(
            "Valore numerico M36 non valido.",
            code="M36_INVALID_NUMBER",
        ) from exc
    if not result.is_finite():
        raise CanonicalParserLiveTransactionDryRunError(
            "Valore numerico M36 non finito.",
            code="M36_INVALID_NUMBER",
        )
    return result


def _money(value: Any) -> str:
    return format(_decimal(value).quantize(_MONEY_QUANTUM), "f")


def _price_impact(value: Any | None) -> str | None:
    if value is None:
        return None
    return format(_decimal(value).quantize(_PRICE_IMPACT_QUANTUM), "f")


def _policy(settings_object: Any = settings) -> dict[str, Any]:
    return {
        "version": LIVE_TRANSACTION_DRY_RUN_POLICY_VERSION,
        "maximum_profile_validity_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_PROFILE_VALIDITY_MINUTES",
                60,
            )
        ),
        "maximum_transaction_bytes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_TRANSACTION_BYTES",
                1232,
            )
        ),
        "maximum_required_signers": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_REQUIRED_SIGNERS",
                1,
            )
        ),
        "maximum_programs": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_PROGRAMS",
                24,
            )
        ),
        "maximum_simulation_logs": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_MAX_SIMULATION_LOGS",
                20,
            )
        ),
        "signing_envelope_ttl_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENVELOPE_TTL_SECONDS",
                60,
            )
        ),
        "allow_address_lookup_tables": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ALLOW_ADDRESS_LOOKUP_TABLES",
                False,
            )
        ),
        "jupiter_build_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_JUPITER_BUILD_ENABLED",
                False,
            )
        ),
        "rpc_simulation_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_RPC_ENABLED",
                False,
            )
        ),
        "credential_material_permitted": False,
        "signing_permitted": False,
        "submission_permitted": False,
    }


def _base58_encode(raw: bytes) -> str:
    if not raw:
        return ""
    zero_count = 0
    for value in raw:
        if value != 0:
            break
        zero_count += 1
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _BASE58_ALPHABET[remainder] + encoded
    return ("1" * zero_count) + (encoded or ("" if zero_count else "1"))


def _base58_decode(value: str) -> bytes:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("empty base58")
    number = 0
    for character in normalized:
        try:
            digit = _BASE58_INDEX[character]
        except KeyError as exc:
            raise ValueError("invalid base58") from exc
        number = number * 58 + digit
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading = len(normalized) - len(normalized.lstrip("1"))
    return (b"\x00" * leading) + decoded


def _validate_pubkey(value: str, *, field: str) -> str:
    normalized = str(value or "").strip()
    try:
        raw = _base58_decode(normalized)
    except ValueError as exc:
        raise CanonicalParserLiveTransactionDryRunError(
            f"{field} non è un public key Solana valido.",
            code="M36_INVALID_PUBLIC_KEY",
        ) from exc
    if len(raw) != 32:
        raise CanonicalParserLiveTransactionDryRunError(
            f"{field} non è lungo 32 byte.",
            code="M36_INVALID_PUBLIC_KEY",
        )
    return normalized


def _normalize_program_ids(values: list[str], *, maximum: int) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        program_id = _validate_pubkey(value, field="Program ID")
        if program_id not in seen:
            seen.add(program_id)
            normalized.append(program_id)
    if not normalized:
        raise CanonicalParserLiveTransactionDryRunError(
            "La allowlist programmi M36 non può essere vuota.",
            code="M36_PROGRAM_ALLOWLIST_EMPTY",
        )
    if len(normalized) > maximum:
        raise CanonicalParserLiveTransactionDryRunError(
            "La allowlist programmi M36 supera il limite.",
            code="M36_PROGRAM_ALLOWLIST_LIMIT",
        )
    return sorted(normalized)


def _read_shortvec(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    cursor = offset
    for _ in range(3):
        if cursor >= len(data):
            raise ValueError("shortvec truncated")
        byte = data[cursor]
        cursor += 1
        result |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return result, cursor
        shift += 7
    raise ValueError("shortvec too long")


def _take(data: bytes, offset: int, length: int) -> tuple[bytes, int]:
    if length < 0 or offset < 0 or offset + length > len(data):
        raise ValueError("transaction truncated")
    return data[offset : offset + length], offset + length


def _inspect_v1_solana_transaction(raw: bytes) -> dict[str, Any]:
    cursor = 1
    header_raw, cursor = _take(raw, cursor, 3)
    num_required_signatures = header_raw[0]
    num_readonly_signed = header_raw[1]
    num_readonly_unsigned = header_raw[2]

    if num_required_signatures < 1 or num_required_signatures > 12:
        raise ValueError("invalid v1 signer count")
    if num_readonly_signed >= num_required_signatures:
        raise ValueError("invalid v1 readonly signed count")

    config_mask_raw, cursor = _take(raw, cursor, 4)
    config_mask = int.from_bytes(config_mask_raw, "little")
    if config_mask & ~0x1F:
        raise ValueError("unsupported v1 transaction config")
    priority_bits = config_mask & 0x03
    if priority_bits not in (0, 0x03):
        raise ValueError("invalid v1 priority fee mask")

    blockhash_raw, cursor = _take(raw, cursor, 32)
    instruction_count_raw, cursor = _take(raw, cursor, 1)
    account_count_raw, cursor = _take(raw, cursor, 1)
    instruction_count = instruction_count_raw[0]
    account_count = account_count_raw[0]

    if instruction_count > 64:
        raise ValueError("too many v1 instructions")
    if account_count < 1 or account_count > 64:
        raise ValueError("invalid v1 account count")
    if account_count < num_required_signatures + num_readonly_unsigned:
        raise ValueError("invalid v1 readonly unsigned count")

    account_bytes, cursor = _take(raw, cursor, account_count * 32)
    account_keys = [
        _base58_encode(account_bytes[index : index + 32])
        for index in range(0, len(account_bytes), 32)
    ]
    if len(set(account_keys)) != len(account_keys):
        raise ValueError("duplicate v1 account keys")

    transaction_config: dict[str, Any] = {
        "mask": config_mask,
        "priority_fee_lamports": None,
        "compute_unit_limit": None,
        "loaded_accounts_data_size_limit": None,
        "heap_size": None,
    }
    if priority_bits == 0x03:
        value_raw, cursor = _take(raw, cursor, 8)
        transaction_config["priority_fee_lamports"] = int.from_bytes(
            value_raw, "little"
        )
    if config_mask & (1 << 2):
        value_raw, cursor = _take(raw, cursor, 4)
        transaction_config["compute_unit_limit"] = int.from_bytes(
            value_raw, "little"
        )
    if config_mask & (1 << 3):
        value_raw, cursor = _take(raw, cursor, 4)
        transaction_config["loaded_accounts_data_size_limit"] = int.from_bytes(
            value_raw, "little"
        )
    if config_mask & (1 << 4):
        value_raw, cursor = _take(raw, cursor, 4)
        heap_size = int.from_bytes(value_raw, "little")
        if heap_size < 32 * 1024 or heap_size > 256 * 1024:
            raise ValueError("invalid v1 heap size")
        if heap_size % 1024 != 0:
            raise ValueError("unaligned v1 heap size")
        transaction_config["heap_size"] = heap_size

    instruction_headers: list[tuple[int, int, int]] = []
    for _ in range(instruction_count):
        header, cursor = _take(raw, cursor, 4)
        instruction_headers.append(
            (
                header[0],
                header[1],
                int.from_bytes(header[2:4], "little"),
            )
        )

    instructions: list[dict[str, Any]] = []
    program_ids: list[str] = []
    for sequence, (program_index, account_index_count, data_length) in enumerate(
        instruction_headers, start=1
    ):
        if program_index >= account_count:
            raise ValueError("invalid v1 program index")
        account_indexes_raw, cursor = _take(
            raw, cursor, account_index_count
        )
        if any(index >= account_count for index in account_indexes_raw):
            raise ValueError("invalid v1 instruction account index")
        _, cursor = _take(raw, cursor, data_length)
        program_id = account_keys[program_index]
        instructions.append(
            {
                "sequence": sequence,
                "program_id_index": program_index,
                "program_id": program_id,
                "account_indexes": list(account_indexes_raw),
                "data_length": data_length,
            }
        )
        if program_id not in program_ids:
            program_ids.append(program_id)

    signature_offset = cursor
    signatures_raw, cursor = _take(
        raw, cursor, num_required_signatures * 64
    )
    if cursor != len(raw):
        raise ValueError("unexpected v1 trailing bytes")
    signatures = [
        signatures_raw[index : index + 64]
        for index in range(0, len(signatures_raw), 64)
    ]

    writable_accounts: list[str] = []
    signed_writable_end = num_required_signatures - num_readonly_signed
    unsigned_writable_end = account_count - num_readonly_unsigned
    for index, account in enumerate(account_keys):
        is_writable = index < signed_writable_end or (
            num_required_signatures <= index < unsigned_writable_end
        )
        if is_writable:
            writable_accounts.append(account)

    message_bytes = raw[:signature_offset]
    return {
        "transaction_format": "V1",
        "transaction_size_bytes": len(raw),
        "signature_slot_count": num_required_signatures,
        "all_signature_slots_zero": all(
            signature == (b"\x00" * 64) for signature in signatures
        ),
        "required_signer_count": num_required_signatures,
        "required_signers": account_keys[:num_required_signatures],
        "static_account_count": account_count,
        "static_account_keys": account_keys,
        "writable_accounts": writable_accounts,
        "instruction_count": instruction_count,
        "instructions": instructions,
        "program_ids": sorted(program_ids),
        "unresolved_program_indexes": [],
        "address_lookup_count": 0,
        "address_table_lookups": [],
        "recent_blockhash": _base58_encode(blockhash_raw),
        "transaction_config": transaction_config,
        "transaction_hash": hashlib.sha256(raw).hexdigest(),
        "message_hash": hashlib.sha256(message_bytes).hexdigest(),
        "account_keys_hash": calculate_payload_hash(account_keys),
    }


def inspect_unsigned_solana_transaction(transaction_base64: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(transaction_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CanonicalParserLiveTransactionDryRunError(
            "Transazione M36 non codificata correttamente in base64.",
            code="M36_TRANSACTION_BASE64_INVALID",
        ) from exc
    if not raw:
        raise CanonicalParserLiveTransactionDryRunError(
            "Transazione M36 vuota.", code="M36_TRANSACTION_EMPTY"
        )
    try:
        if raw[0] == 0x81:
            return _inspect_v1_solana_transaction(raw)
        signature_count, cursor = _read_shortvec(raw, 0)
        signatures_raw, cursor = _take(raw, cursor, signature_count * 64)
        message_offset = cursor
        if cursor >= len(raw):
            raise ValueError("message missing")
        first = raw[cursor]
        if first & 0x80:
            version = first & 0x7F
            if version != 0:
                raise ValueError("unsupported version")
            transaction_format = "V0"
            cursor += 1
            if cursor + 3 > len(raw):
                raise ValueError("header missing")
            num_required_signatures = raw[cursor]
            num_readonly_signed = raw[cursor + 1]
            num_readonly_unsigned = raw[cursor + 2]
            cursor += 3
        else:
            transaction_format = "LEGACY"
            if cursor + 3 > len(raw):
                raise ValueError("header missing")
            num_required_signatures = raw[cursor]
            num_readonly_signed = raw[cursor + 1]
            num_readonly_unsigned = raw[cursor + 2]
            cursor += 3
        account_count, cursor = _read_shortvec(raw, cursor)
        if account_count < 1:
            raise ValueError("account keys missing")
        account_bytes, cursor = _take(raw, cursor, account_count * 32)
        account_keys = [
            _base58_encode(account_bytes[index : index + 32])
            for index in range(0, len(account_bytes), 32)
        ]
        blockhash_raw, cursor = _take(raw, cursor, 32)
        instruction_count, cursor = _read_shortvec(raw, cursor)
        instructions: list[dict[str, Any]] = []
        for sequence in range(1, instruction_count + 1):
            program_raw, cursor = _take(raw, cursor, 1)
            program_index = program_raw[0]
            account_index_count, cursor = _read_shortvec(raw, cursor)
            account_indexes_raw, cursor = _take(raw, cursor, account_index_count)
            data_length, cursor = _read_shortvec(raw, cursor)
            _, cursor = _take(raw, cursor, data_length)
            instructions.append(
                {
                    "sequence": sequence,
                    "program_id_index": program_index,
                    "account_indexes": list(account_indexes_raw),
                    "data_length": data_length,
                }
            )
        lookups: list[dict[str, Any]] = []
        if transaction_format == "V0":
            lookup_count, cursor = _read_shortvec(raw, cursor)
            for sequence in range(1, lookup_count + 1):
                key_raw, cursor = _take(raw, cursor, 32)
                writable_count, cursor = _read_shortvec(raw, cursor)
                writable_raw, cursor = _take(raw, cursor, writable_count)
                readonly_count, cursor = _read_shortvec(raw, cursor)
                readonly_raw, cursor = _take(raw, cursor, readonly_count)
                lookups.append(
                    {
                        "sequence": sequence,
                        "table_account": _base58_encode(key_raw),
                        "writable_indexes": list(writable_raw),
                        "readonly_indexes": list(readonly_raw),
                    }
                )
        if cursor != len(raw):
            raise ValueError("unexpected trailing bytes")
        if signature_count != num_required_signatures:
            raise ValueError("signature count mismatch")
        if num_required_signatures < 1 or num_required_signatures > account_count:
            raise ValueError("invalid signer count")
        if num_readonly_signed > num_required_signatures:
            raise ValueError("invalid readonly signed count")
        unsigned_count = account_count - num_required_signatures
        if num_readonly_unsigned > unsigned_count:
            raise ValueError("invalid readonly unsigned count")
        unresolved_program_indexes: list[int] = []
        program_ids: list[str] = []
        for instruction in instructions:
            index = instruction["program_id_index"]
            if index >= account_count:
                unresolved_program_indexes.append(index)
                continue
            program_id = account_keys[index]
            instruction["program_id"] = program_id
            if program_id not in program_ids:
                program_ids.append(program_id)
        writable_accounts: list[str] = []
        signed_writable_end = num_required_signatures - num_readonly_signed
        unsigned_writable_end = account_count - num_readonly_unsigned
        for index, account in enumerate(account_keys):
            is_writable = index < signed_writable_end or (
                num_required_signatures <= index < unsigned_writable_end
            )
            if is_writable:
                writable_accounts.append(account)
        signatures = [
            signatures_raw[index : index + 64]
            for index in range(0, len(signatures_raw), 64)
        ]
        message_bytes = raw[message_offset:]
        return {
            "transaction_format": transaction_format,
            "transaction_size_bytes": len(raw),
            "signature_slot_count": signature_count,
            "all_signature_slots_zero": all(
                signature == (b"\x00" * 64) for signature in signatures
            ),
            "required_signer_count": num_required_signatures,
            "required_signers": account_keys[:num_required_signatures],
            "static_account_count": account_count,
            "static_account_keys": account_keys,
            "writable_accounts": writable_accounts,
            "instruction_count": instruction_count,
            "instructions": instructions,
            "program_ids": sorted(program_ids),
            "unresolved_program_indexes": sorted(set(unresolved_program_indexes)),
            "address_lookup_count": len(lookups),
            "address_table_lookups": lookups,
            "recent_blockhash": _base58_encode(blockhash_raw),
            "transaction_hash": hashlib.sha256(raw).hexdigest(),
            "message_hash": hashlib.sha256(message_bytes).hexdigest(),
            "account_keys_hash": calculate_payload_hash(account_keys),
        }
    except CanonicalParserLiveTransactionDryRunError:
        raise
    except (IndexError, TypeError, ValueError) as exc:
        raise CanonicalParserLiveTransactionDryRunError(
            "Transazione Solana M36 non interpretabile.",
            code="M36_TRANSACTION_INVALID",
        ) from exc


def _live_policy_snapshot(row: LiveTradingPolicy) -> dict[str, Any]:
    return {
        "id": row.id,
        "mode": row.mode,
        "kill_switch": bool(row.kill_switch),
        "stream_execution_enabled": bool(row.stream_execution_enabled),
        "buy_enabled": bool(row.buy_enabled),
        "sell_enabled": bool(row.sell_enabled),
        "max_order_size_sol": str(row.max_order_size_sol),
        "max_daily_buy_sol": str(row.max_daily_buy_sol),
        "max_daily_loss_sol": str(row.max_daily_loss_sol),
        "max_total_exposure_sol": str(row.max_total_exposure_sol),
    }


def _platform_snapshot(row: LivePlatformConfig) -> dict[str, Any]:
    return {
        "id": row.id,
        "live_armed_until": (
            None
            if row.live_armed_until is None
            else _aware(row.live_armed_until).isoformat()
        ),
        "token_safety_enabled": bool(row.token_safety_enabled),
        "token_safety_fail_closed": bool(row.token_safety_fail_closed),
        "max_token_risk_score": int(row.max_token_risk_score),
        "max_top_holder_percent": str(row.max_top_holder_percent),
    }


def _safe_live_control_state(
    db: Session,
    *,
    now: datetime,
    settings_object: Any = settings,
) -> tuple[LiveTradingPolicy, LivePlatformConfig]:
    live_policy = db.scalar(
        select(LiveTradingPolicy).order_by(LiveTradingPolicy.id.asc()).limit(1)
    )
    platform = db.scalar(
        select(LivePlatformConfig).order_by(LivePlatformConfig.id.asc()).limit(1)
    )
    reasons: list[str] = []
    if live_policy is None:
        reasons.append("LIVE_POLICY_MISSING")
    if platform is None:
        reasons.append("LIVE_PLATFORM_CONFIG_MISSING")
    if live_policy is not None:
        if live_policy.mode == "LIVE":
            reasons.append("LIVE_MODE_ACTIVE")
        if not live_policy.kill_switch:
            reasons.append("KILL_SWITCH_NOT_ENGAGED")
        if live_policy.stream_execution_enabled:
            reasons.append("STREAM_EXECUTION_ENABLED")
    if platform is not None:
        if platform.live_armed_until is not None and _aware(platform.live_armed_until) > now:
            reasons.append("LIVE_PLATFORM_ARMED")
        if not platform.token_safety_enabled:
            reasons.append("TOKEN_SAFETY_DISABLED")
        if not platform.token_safety_fail_closed:
            reasons.append("TOKEN_SAFETY_NOT_FAIL_CLOSED")
    if bool(getattr(settings_object, "RUN_LIVE_STREAM_WORKER", False)):
        reasons.append("LIVE_STREAM_WORKER_ENABLED")
    if bool(getattr(settings_object, "RUN_LIVE_POSITION_MONITOR", False)):
        reasons.append("LIVE_POSITION_MONITOR_ENABLED")
    if reasons:
        raise CanonicalParserLiveTransactionDryRunError(
            "Stato LIVE non sicuro per M36.",
            code="M36_LIVE_CONTROL_STATE_UNSAFE",
            status_code=409,
        )
    assert live_policy is not None and platform is not None
    return live_policy, platform


def _serialize_profile(
    row: CanonicalParserIsolatedSignerProfile,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _aware(now)
    resolved_status = row.status
    if row.status == "ACTIVE" and _aware(row.expires_at) <= current:
        resolved_status = "EXPIRED"
    return {
        "profile_id": row.profile_id,
        "profile_key": row.profile_key,
        "scope": row.scope,
        "status": row.status,
        "resolved_status": resolved_status,
        "wallet_address": row.wallet_address,
        "network": row.network,
        "allowed_program_ids": row.allowed_program_ids,
        "max_transaction_bytes": row.max_transaction_bytes,
        "max_required_signers": row.max_required_signers,
        "allow_address_lookup_tables": row.allow_address_lookup_tables,
        "validity_minutes": row.validity_minutes,
        "policy_version": row.policy_version,
        "policy_hash": row.policy_hash,
        "policy_snapshot": row.policy_snapshot,
        "actor_label": row.actor_label,
        "note": row.note,
        "issued_at": row.issued_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "revocation_reason": row.revocation_reason,
        "latest_event_sequence": row.latest_event_sequence,
        "latest_event_hash": row.latest_event_hash,
        "technical_metadata": row.technical_metadata,
    }


def _serialize_dry_run(row: CanonicalParserLiveTransactionDryRun) -> dict[str, Any]:
    return {
        "dry_run_id": row.dry_run_id,
        "dry_run_key": row.dry_run_key,
        "scope": row.scope,
        "signer_profile_id": row.signer_profile_id,
        "micro_live_simulation_id": row.micro_live_simulation_id,
        "micro_live_permit_id": row.micro_live_permit_id,
        "decision_result_id": row.decision_result_id,
        "side": row.side,
        "status": row.status,
        "transaction_source": row.transaction_source,
        "transaction_format": row.transaction_format,
        "token_mint": row.token_mint,
        "input_mint": row.input_mint,
        "output_mint": row.output_mint,
        "amount_raw": str(row.amount_raw),
        "requested_budget_sol": _money(row.requested_budget_sol),
        "transaction_size_bytes": row.transaction_size_bytes,
        "signature_slot_count": row.signature_slot_count,
        "required_signer_count": row.required_signer_count,
        "static_account_count": row.static_account_count,
        "instruction_count": row.instruction_count,
        "address_lookup_count": row.address_lookup_count,
        "required_signers": row.required_signers,
        "program_ids": row.program_ids,
        "writable_accounts": row.writable_accounts,
        "transaction_hash": row.transaction_hash,
        "message_hash": row.message_hash,
        "account_keys_hash": row.account_keys_hash,
        "jupiter_request_id": row.jupiter_request_id,
        "jupiter_router": row.jupiter_router,
        "jupiter_price_impact_percent": _price_impact(
            row.jupiter_price_impact_percent
        ),
        "jupiter_slippage_bps": row.jupiter_slippage_bps,
        "rpc_simulation_status": row.rpc_simulation_status,
        "units_consumed": row.units_consumed,
        "reason_codes": row.reason_codes,
        "inspection_snapshot": row.inspection_snapshot,
        "rpc_simulation_snapshot": row.rpc_simulation_snapshot,
        "signing_envelope": row.signing_envelope,
        "signing_envelope_hash": row.signing_envelope_hash,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "prepared_at": row.prepared_at,
        "envelope_expires_at": row.envelope_expires_at,
    }


def _append_profile_event(
    db: Session,
    profile: CanonicalParserIsolatedSignerProfile,
    *,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime,
) -> CanonicalParserIsolatedSignerProfileEvent:
    sequence = int(profile.latest_event_sequence or 0) + 1
    event_payload = {
        "profile_id": profile.profile_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat(),
        "payload": payload,
        "previous_event_hash": profile.latest_event_hash,
    }
    event_hash = calculate_payload_hash(event_payload)
    event = CanonicalParserIsolatedSignerProfileEvent(
        event_id=str(uuid4()),
        profile_db_id=profile.id,
        sequence=sequence,
        event_type=event_type,
        event_payload=event_payload,
        previous_event_hash=profile.latest_event_hash,
        event_hash=event_hash,
        occurred_at=occurred_at,
    )
    db.add(event)
    profile.latest_event_sequence = sequence
    profile.latest_event_hash = event_hash
    return event


def preview_isolated_signer_profile(
    db: Session,
    *,
    wallet_address: str,
    validity_minutes: int,
    allowed_program_ids: list[str],
    max_transaction_bytes: int,
    max_required_signers: int,
    allow_address_lookup_tables: bool,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy(settings_object)
    wallet = _validate_pubkey(wallet_address, field="Wallet signer")
    programs = _normalize_program_ids(
        allowed_program_ids, maximum=policy["maximum_programs"]
    )
    if validity_minutes < 1 or validity_minutes > policy["maximum_profile_validity_minutes"]:
        raise CanonicalParserLiveTransactionDryRunError(
            "Validità profilo signer M36 oltre limite.",
            code="M36_PROFILE_VALIDITY_LIMIT",
            status_code=409,
        )
    if max_transaction_bytes < 1 or max_transaction_bytes > policy["maximum_transaction_bytes"]:
        raise CanonicalParserLiveTransactionDryRunError(
            "Dimensione massima transazione M36 oltre limite.",
            code="M36_PROFILE_TRANSACTION_LIMIT",
            status_code=409,
        )
    if max_required_signers < 1 or max_required_signers > policy["maximum_required_signers"]:
        raise CanonicalParserLiveTransactionDryRunError(
            "Numero firmatari M36 oltre limite.",
            code="M36_PROFILE_SIGNER_LIMIT",
            status_code=409,
        )
    if allow_address_lookup_tables and not policy["allow_address_lookup_tables"]:
        raise CanonicalParserLiveTransactionDryRunError(
            "Address lookup table non consentite dalla policy M36.",
            code="M36_ADDRESS_LOOKUP_TABLES_DISABLED",
            status_code=409,
        )
    live_policy, platform = _safe_live_control_state(
        db, now=now, settings_object=settings_object
    )
    snapshot = {
        "wallet_address": wallet,
        "network": "mainnet-beta",
        "allowed_program_ids": programs,
        "max_transaction_bytes": max_transaction_bytes,
        "max_required_signers": max_required_signers,
        "allow_address_lookup_tables": bool(allow_address_lookup_tables),
        "validity_minutes": validity_minutes,
        "live_policy_snapshot": _live_policy_snapshot(live_policy),
        "live_platform_snapshot": _platform_snapshot(platform),
        "policy": policy,
    }
    profile_key = calculate_payload_hash(snapshot)
    existing = db.scalar(
        select(CanonicalParserIsolatedSignerProfile).where(
            CanonicalParserIsolatedSignerProfile.profile_key == profile_key
        )
    )
    return {
        "status": "READY",
        "ready": True,
        "profile_key": profile_key,
        "existing_profile": None if existing is None else _serialize_profile(existing, now=now),
        "snapshot": snapshot,
        "policy": policy,
        "confirmation": f"{SIGNER_PROFILE_ISSUE_PREFIX}:{profile_key}",
        "safety": {
            "public_key_only": True,
            "credential_material_loaded": False,
            "signer_connected": False,
            "signing_authorized": False,
            "submission_authorized": False,
        },
    }


def issue_isolated_signer_profile(
    db: Session,
    *,
    wallet_address: str,
    validity_minutes: int,
    allowed_program_ids: list[str],
    max_transaction_bytes: int,
    max_required_signers: int,
    allow_address_lookup_tables: bool,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENABLED",
            False,
        )
    ):
        raise CanonicalParserLiveTransactionDryRunError(
            "M36 è disabilitata.", code="M36_DISABLED", status_code=409
        )
    now = _aware(issued_at)
    preview = preview_isolated_signer_profile(
        db,
        wallet_address=wallet_address,
        validity_minutes=validity_minutes,
        allowed_program_ids=allowed_program_ids,
        max_transaction_bytes=max_transaction_bytes,
        max_required_signers=max_required_signers,
        allow_address_lookup_tables=allow_address_lookup_tables,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_profile"] is not None:
        return preview["existing_profile"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserLiveTransactionDryRunError(
            "Conferma profilo signer M36 non valida.",
            code="M36_PROFILE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    profile_id = str(uuid4())
    event_payload = {
        "profile_id": profile_id,
        "event_type": "ISSUED",
        "issued_at": now.isoformat(),
        "profile_key": preview["profile_key"],
        "actor_label": _actor(actor_label),
    }
    first_hash = calculate_payload_hash(event_payload)
    snapshot = preview["snapshot"]
    policy = preview["policy"]
    row = CanonicalParserIsolatedSignerProfile(
        profile_id=profile_id,
        profile_key=preview["profile_key"],
        scope="M36_ISOLATED_SIGNER_DRY_RUN_ONLY",
        status="ACTIVE",
        wallet_address=snapshot["wallet_address"],
        network="mainnet-beta",
        allowed_program_ids=snapshot["allowed_program_ids"],
        max_transaction_bytes=snapshot["max_transaction_bytes"],
        max_required_signers=snapshot["max_required_signers"],
        allow_address_lookup_tables=snapshot["allow_address_lookup_tables"],
        validity_minutes=validity_minutes,
        policy_version=policy["version"],
        policy_hash=calculate_payload_hash(policy),
        policy_snapshot=policy,
        actor_label=_actor(actor_label),
        note=_note(note),
        issued_at=now,
        expires_at=now + timedelta(minutes=validity_minutes),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash=first_hash,
        technical_metadata={
            "live_policy_snapshot": snapshot["live_policy_snapshot"],
            "live_platform_snapshot": snapshot["live_platform_snapshot"],
            "credential_fields_present": False,
        },
    )
    db.add(row)
    db.flush()
    db.add(
        CanonicalParserIsolatedSignerProfileEvent(
            event_id=str(uuid4()),
            profile_db_id=row.id,
            sequence=1,
            event_type="ISSUED",
            event_payload=event_payload,
            previous_event_hash=None,
            event_hash=first_hash,
            occurred_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserIsolatedSignerProfile).where(
                CanonicalParserIsolatedSignerProfile.profile_key == preview["profile_key"]
            )
        )
        if duplicate is not None:
            return _serialize_profile(duplicate, now=now)
        raise CanonicalParserLiveTransactionDryRunError(
            "Conflitto profilo signer M36.",
            code="M36_PROFILE_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(row)
    return _serialize_profile(row, now=now)


def _resolve_profile(
    db: Session,
    profile_id: str,
    *,
    now: datetime,
    lock: bool = False,
) -> CanonicalParserIsolatedSignerProfile:
    statement = select(CanonicalParserIsolatedSignerProfile).where(
        CanonicalParserIsolatedSignerProfile.profile_id == profile_id
    )
    if lock:
        statement = statement.with_for_update()
    row = db.scalar(statement)
    if row is None:
        raise CanonicalParserLiveTransactionDryRunError(
            "Profilo signer M36 non trovato.",
            code="M36_PROFILE_NOT_FOUND",
            status_code=404,
        )
    if row.status == "ACTIVE" and _aware(row.expires_at) <= now:
        row.status = "EXPIRED"
        _append_profile_event(
            db,
            row,
            event_type="EXPIRED",
            payload={"reason": "VALIDITY_ELAPSED"},
            occurred_at=now,
        )
        db.commit()
    if row.status != "ACTIVE":
        raise CanonicalParserLiveTransactionDryRunError(
            "Profilo signer M36 non attivo.",
            code="M36_PROFILE_NOT_ACTIVE",
            status_code=409,
        )
    return row


def revoke_isolated_signer_profile(
    db: Session,
    *,
    profile_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(revoked_at)
    row = db.scalar(
        select(CanonicalParserIsolatedSignerProfile)
        .where(CanonicalParserIsolatedSignerProfile.profile_id == profile_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserLiveTransactionDryRunError(
            "Profilo signer M36 non trovato.",
            code="M36_PROFILE_NOT_FOUND",
            status_code=404,
        )
    expected = f"{SIGNER_PROFILE_REVOKE_PREFIX}:{profile_id}:{row.latest_event_hash}"
    if confirmation != expected:
        raise CanonicalParserLiveTransactionDryRunError(
            "Conferma revoca profilo M36 non valida.",
            code="M36_PROFILE_REVOKE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if row.status == "REVOKED":
        return _serialize_profile(row, now=now)
    row.status = "REVOKED"
    row.revoked_at = now
    row.revocation_reason = sanitize_error_message(reason, max_length=500)
    _append_profile_event(
        db,
        row,
        event_type="REVOKED",
        payload={
            "reason": row.revocation_reason,
            "actor_label": _actor(actor_label),
        },
        occurred_at=now,
    )
    db.commit()
    db.refresh(row)
    return _serialize_profile(row, now=now)


def _resolve_ready_m35_simulation(
    db: Session,
    simulation_id: str,
    *,
    now: datetime,
) -> tuple[CanonicalParserMicroLiveCanarySimulation, CanonicalParserMicroLiveCanaryPermit]:
    simulation = db.scalar(
        select(CanonicalParserMicroLiveCanarySimulation).where(
            CanonicalParserMicroLiveCanarySimulation.simulation_id == simulation_id
        )
    )
    if simulation is None:
        raise CanonicalParserLiveTransactionDryRunError(
            "Simulazione M35 non trovata.",
            code="M36_M35_SIMULATION_NOT_FOUND",
            status_code=404,
        )
    if simulation.status != "READY":
        raise CanonicalParserLiveTransactionDryRunError(
            "Simulazione M35 non READY.",
            code="M36_M35_SIMULATION_NOT_READY",
            status_code=409,
        )
    if calculate_payload_hash(simulation.evidence_snapshot) != simulation.evidence_hash:
        raise CanonicalParserLiveTransactionDryRunError(
            "Evidenza M35 non integra.",
            code="M36_M35_EVIDENCE_DRIFT",
            status_code=409,
        )
    permit = db.get(CanonicalParserMicroLiveCanaryPermit, simulation.permit_db_id)
    if permit is None:
        raise CanonicalParserLiveTransactionDryRunError(
            "Permit M35 non trovato.",
            code="M36_M35_PERMIT_NOT_FOUND",
            status_code=404,
        )
    if permit.status in {"REVOKED", "EXPIRED"} or _aware(permit.expires_at) <= now:
        raise CanonicalParserLiveTransactionDryRunError(
            "Permit M35 non valido per M36.",
            code="M36_M35_PERMIT_NOT_ACTIVE",
            status_code=409,
        )
    return simulation, permit


def _validate_m35_and_live_state(
    db: Session,
    *,
    simulation_id: str,
    now: datetime,
    settings_object: Any,
) -> tuple[
    CanonicalParserMicroLiveCanarySimulation,
    CanonicalParserMicroLiveCanaryPermit,
    LiveTradingPolicy,
    LivePlatformConfig,
]:
    simulation, permit = _resolve_ready_m35_simulation(
        db, simulation_id, now=now
    )
    live_policy, platform = _safe_live_control_state(
        db, now=now, settings_object=settings_object
    )
    if calculate_payload_hash(_live_policy_snapshot(live_policy)) != calculate_payload_hash(
        permit.live_policy_snapshot
    ):
        raise CanonicalParserLiveTransactionDryRunError(
            "Policy LIVE variata rispetto al permit M35.",
            code="M36_LIVE_POLICY_DRIFT",
            status_code=409,
        )
    if calculate_payload_hash(_platform_snapshot(platform)) != calculate_payload_hash(
        permit.live_platform_snapshot
    ):
        raise CanonicalParserLiveTransactionDryRunError(
            "Configurazione piattaforma LIVE variata rispetto al permit M35.",
            code="M36_LIVE_PLATFORM_DRIFT",
            status_code=409,
        )
    return simulation, permit, live_policy, platform


def _expected_order_fields(
    simulation: CanonicalParserMicroLiveCanarySimulation,
    *,
    amount_raw: int | None,
) -> tuple[str, str, int]:
    if simulation.side == "BUY":
        expected_amount = int(
            (_decimal(simulation.simulated_budget_sol) * Decimal("1000000000"))
            .quantize(Decimal("1"))
        )
        if expected_amount <= 0:
            raise CanonicalParserLiveTransactionDryRunError(
                "Budget M35 non convertibile in lamport.",
                code="M36_INVALID_BUY_AMOUNT",
                status_code=409,
            )
        if amount_raw is not None and int(amount_raw) != expected_amount:
            raise CanonicalParserLiveTransactionDryRunError(
                "Importo BUY non corrisponde alla simulazione M35.",
                code="M36_BUY_AMOUNT_MISMATCH",
                status_code=409,
            )
        return WRAPPED_SOL_MINT, simulation.token_mint, expected_amount
    if amount_raw is None or int(amount_raw) <= 0:
        raise CanonicalParserLiveTransactionDryRunError(
            "Per SELL è richiesto amount_raw positivo.",
            code="M36_SELL_AMOUNT_REQUIRED",
        )
    return simulation.token_mint, WRAPPED_SOL_MINT, int(amount_raw)


def preview_jupiter_transaction_build(
    db: Session,
    *,
    signer_profile_id: str,
    micro_live_simulation_id: str,
    amount_raw: int | None,
    slippage_bps: int | None,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
    jupiter_client: JupiterSwapClient | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENABLED",
            False,
        )
    ):
        raise CanonicalParserLiveTransactionDryRunError(
            "M36 è disabilitata.", code="M36_DISABLED", status_code=409
        )
    policy = _policy(settings_object)
    if not policy["jupiter_build_enabled"]:
        raise CanonicalParserLiveTransactionDryRunError(
            "Builder Jupiter M36 disabilitato.",
            code="M36_JUPITER_BUILD_DISABLED",
            status_code=409,
        )
    now = _aware(evaluated_at)
    profile = _resolve_profile(db, signer_profile_id, now=now)
    simulation, _, live_policy, _ = _validate_m35_and_live_state(
        db,
        simulation_id=micro_live_simulation_id,
        now=now,
        settings_object=settings_object,
    )
    normalized_token = str(idempotency_token or "").strip()
    if len(normalized_token) < 8:
        raise CanonicalParserLiveTransactionDryRunError(
            "Idempotency token M36 non valido.",
            code="M36_IDEMPOTENCY_TOKEN_INVALID",
        )
    input_mint, output_mint, resolved_amount = _expected_order_fields(
        simulation, amount_raw=amount_raw
    )
    resolved_slippage = int(
        slippage_bps if slippage_bps is not None else live_policy.max_slippage_bps
    )
    if resolved_slippage > int(live_policy.max_slippage_bps):
        raise CanonicalParserLiveTransactionDryRunError(
            "Slippage Jupiter oltre la policy LIVE.",
            code="M36_SLIPPAGE_LIMIT",
            status_code=409,
        )
    client = jupiter_client or JupiterSwapClient()
    result = client.get_order(
        input_mint=input_mint,
        output_mint=output_mint,
        amount_raw=resolved_amount,
        taker=profile.wallet_address,
        slippage_bps=resolved_slippage,
    )
    if not result.transaction:
        raise CanonicalParserLiveTransactionDryRunError(
            "Jupiter non ha prodotto la transazione M36.",
            code="M36_JUPITER_TRANSACTION_MISSING",
            status_code=502,
        )
    if _decimal(result.price_impact_percent) > _decimal(
        live_policy.max_price_impact_percent
    ):
        raise CanonicalParserLiveTransactionDryRunError(
            "Price impact Jupiter oltre la policy LIVE.",
            code="M36_PRICE_IMPACT_LIMIT",
            status_code=409,
        )
    inspection = inspect_unsigned_solana_transaction(result.transaction)
    build_evidence = {
        "signer_profile_id": profile.profile_id,
        "micro_live_simulation_id": simulation.simulation_id,
        "input_mint": input_mint,
        "output_mint": output_mint,
        "amount_raw": resolved_amount,
        "slippage_bps": result.slippage_bps,
        "jupiter_request_id": result.request_id,
        "jupiter_router": result.router,
        "jupiter_price_impact_percent": str(result.price_impact_percent),
        "transaction_hash": inspection["transaction_hash"],
        "idempotency_token": normalized_token,
    }
    return {
        "status": "BUILT",
        "transaction_source": "JUPITER_ORDER",
        "unsigned_transaction_base64": result.transaction,
        "input_mint": input_mint,
        "output_mint": output_mint,
        "amount_raw": resolved_amount,
        "jupiter_request_id": result.request_id,
        "jupiter_router": result.router,
        "jupiter_price_impact_percent": result.price_impact_percent,
        "jupiter_slippage_bps": result.slippage_bps,
        "last_valid_block_height": result.last_valid_block_height,
        "inspection": inspection,
        "build_key": calculate_payload_hash(build_evidence),
        "safety": {
            "order_built_only": True,
            "credential_material_loaded": False,
            "transaction_signed": False,
            "transaction_sent": False,
        },
    }


def _structural_preview(
    db: Session,
    *,
    signer_profile_id: str,
    micro_live_simulation_id: str,
    transaction_source: str,
    unsigned_transaction_base64: str,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    jupiter_request_id: str | None,
    jupiter_router: str | None,
    jupiter_price_impact_percent: Any | None,
    jupiter_slippage_bps: int | None,
    idempotency_token: str,
    settings_object: Any,
    evaluated_at: datetime,
) -> dict[str, Any]:
    policy = _policy(settings_object)
    profile = _resolve_profile(db, signer_profile_id, now=evaluated_at)
    simulation, permit, live_policy, platform = _validate_m35_and_live_state(
        db,
        simulation_id=micro_live_simulation_id,
        now=evaluated_at,
        settings_object=settings_object,
    )
    normalized_source = str(transaction_source or "").strip().upper()
    if normalized_source not in {"JUPITER_ORDER", "PROVIDED_TRANSACTION"}:
        raise CanonicalParserLiveTransactionDryRunError(
            "Sorgente transazione M36 non valida.", code="M36_SOURCE_INVALID"
        )
    normalized_input = _validate_pubkey(input_mint, field="Input mint")
    normalized_output = _validate_pubkey(output_mint, field="Output mint")
    expected_input, expected_output, expected_amount = _expected_order_fields(
        simulation, amount_raw=amount_raw if simulation.side == "SELL" else None
    )
    reasons: list[str] = []
    if normalized_input != expected_input or normalized_output != expected_output:
        reasons.append("MINT_DIRECTION_MISMATCH")
    if simulation.side == "BUY" and int(amount_raw) != expected_amount:
        reasons.append("BUY_AMOUNT_MISMATCH")
    inspection = inspect_unsigned_solana_transaction(unsigned_transaction_base64)
    if inspection["transaction_size_bytes"] > min(
        profile.max_transaction_bytes, policy["maximum_transaction_bytes"]
    ):
        reasons.append("TRANSACTION_TOO_LARGE")
    if not inspection["all_signature_slots_zero"]:
        reasons.append("TRANSACTION_ALREADY_SIGNED")
    if inspection["required_signer_count"] > min(
        profile.max_required_signers, policy["maximum_required_signers"]
    ):
        reasons.append("REQUIRED_SIGNER_LIMIT")
    if profile.wallet_address not in inspection["required_signers"]:
        reasons.append("PROFILE_WALLET_NOT_REQUIRED_SIGNER")
    if inspection["unresolved_program_indexes"]:
        reasons.append("UNRESOLVED_PROGRAM_IDS")
    if inspection["address_lookup_count"] > 0 and not (
        profile.allow_address_lookup_tables and policy["allow_address_lookup_tables"]
    ):
        reasons.append("ADDRESS_LOOKUP_TABLES_NOT_ALLOWED")
    unexpected_programs = sorted(
        set(inspection["program_ids"]) - set(profile.allowed_program_ids)
    )
    if unexpected_programs:
        reasons.append("PROGRAM_NOT_ALLOWLISTED")
    if len(inspection["program_ids"]) > policy["maximum_programs"]:
        reasons.append("PROGRAM_COUNT_LIMIT")
    if normalized_source == "JUPITER_ORDER":
        if not str(jupiter_request_id or "").strip():
            reasons.append("JUPITER_REQUEST_ID_MISSING")
        if jupiter_slippage_bps is None:
            reasons.append("JUPITER_SLIPPAGE_MISSING")
        elif int(jupiter_slippage_bps) > int(live_policy.max_slippage_bps):
            reasons.append("JUPITER_SLIPPAGE_LIMIT")
        if jupiter_price_impact_percent is None:
            reasons.append("JUPITER_PRICE_IMPACT_MISSING")
        elif _decimal(jupiter_price_impact_percent) > _decimal(
            live_policy.max_price_impact_percent
        ):
            reasons.append("JUPITER_PRICE_IMPACT_LIMIT")
    else:
        reasons.append("TRANSACTION_PROVENANCE_UNVERIFIED")
        if simulation.token_mint not in inspection["static_account_keys"]:
            reasons.append("TOKEN_BINDING_UNVERIFIED")
    normalized_idempotency = str(idempotency_token or "").strip()
    if len(normalized_idempotency) < 8:
        raise CanonicalParserLiveTransactionDryRunError(
            "Idempotency token M36 non valido.",
            code="M36_IDEMPOTENCY_TOKEN_INVALID",
        )
    dry_run_key = calculate_payload_hash(
        {
            "signer_profile_id": profile.profile_id,
            "micro_live_simulation_id": simulation.simulation_id,
            "transaction_source": normalized_source,
            "transaction_hash": inspection["transaction_hash"],
            "input_mint": normalized_input,
            "output_mint": normalized_output,
            "amount_raw": int(amount_raw),
            "jupiter_request_id": str(jupiter_request_id or "").strip() or None,
            "jupiter_router": str(jupiter_router or "").strip() or None,
            "jupiter_price_impact_percent": _price_impact(jupiter_price_impact_percent),
            "jupiter_slippage_bps": jupiter_slippage_bps,
            "idempotency_token": normalized_idempotency,
        }
    )
    existing = db.scalar(
        select(CanonicalParserLiveTransactionDryRun).where(
            CanonicalParserLiveTransactionDryRun.dry_run_key == dry_run_key
        )
    )
    blocking = {
        "MINT_DIRECTION_MISMATCH",
        "BUY_AMOUNT_MISMATCH",
        "TRANSACTION_TOO_LARGE",
        "TRANSACTION_ALREADY_SIGNED",
        "REQUIRED_SIGNER_LIMIT",
        "PROFILE_WALLET_NOT_REQUIRED_SIGNER",
        "UNRESOLVED_PROGRAM_IDS",
        "ADDRESS_LOOKUP_TABLES_NOT_ALLOWED",
        "PROGRAM_NOT_ALLOWLISTED",
        "PROGRAM_COUNT_LIMIT",
        "JUPITER_SLIPPAGE_LIMIT",
        "JUPITER_PRICE_IMPACT_LIMIT",
    }
    missing = {
        "JUPITER_REQUEST_ID_MISSING",
        "JUPITER_SLIPPAGE_MISSING",
        "JUPITER_PRICE_IMPACT_MISSING",
        "TOKEN_BINDING_UNVERIFIED",
    }
    if any(reason in blocking for reason in reasons):
        status = "BLOCKED"
    elif any(reason in missing for reason in reasons):
        status = "INSUFFICIENT_DATA"
    elif reasons:
        status = "REVIEW"
    else:
        status = "REVIEW"
        reasons.append("RPC_SIMULATION_PENDING")
    evidence = {
        "signer_profile": {
            "profile_id": profile.profile_id,
            "profile_key": profile.profile_key,
            "status": profile.status,
            "wallet_address": profile.wallet_address,
            "network": profile.network,
            "allowed_program_ids": profile.allowed_program_ids,
            "max_transaction_bytes": profile.max_transaction_bytes,
            "max_required_signers": profile.max_required_signers,
            "allow_address_lookup_tables": profile.allow_address_lookup_tables,
            "expires_at": _aware(profile.expires_at).isoformat(),
            "policy_hash": profile.policy_hash,
        },
        "micro_live_simulation": {
            "simulation_id": simulation.simulation_id,
            "evidence_hash": simulation.evidence_hash,
            "permit_id": simulation.permit_id,
            "decision_result_id": simulation.decision_result_id,
            "side": simulation.side,
            "token_mint": simulation.token_mint,
            "simulated_budget_sol": _money(simulation.simulated_budget_sol),
        },
        "permit": {
            "permit_id": permit.permit_id,
            "status": permit.status,
            "expires_at": _aware(permit.expires_at).isoformat(),
        },
        "live_policy_snapshot": _live_policy_snapshot(live_policy),
        "live_platform_snapshot": _platform_snapshot(platform),
        "transaction_source": normalized_source,
        "input_mint": normalized_input,
        "output_mint": normalized_output,
        "amount_raw": int(amount_raw),
        "inspection": inspection,
        "jupiter": {
            "request_id": str(jupiter_request_id or "").strip() or None,
            "router": str(jupiter_router or "").strip() or None,
            "price_impact_percent": _price_impact(jupiter_price_impact_percent),
            "slippage_bps": jupiter_slippage_bps,
        },
        "reason_codes": reasons,
        "policy": policy,
        "safety": {
            "credential_material_loaded": False,
            "signer_connected": False,
            "transaction_signed": False,
            "transaction_sent": False,
            "live_execution_authorized": False,
        },
    }
    return {
        "status": status,
        "ready": False,
        "dry_run_key": dry_run_key,
        "existing_dry_run": None if existing is None else _serialize_dry_run(existing),
        "profile": profile,
        "simulation": simulation,
        "permit": permit,
        "inspection": inspection,
        "transaction_source": normalized_source,
        "input_mint": normalized_input,
        "output_mint": normalized_output,
        "amount_raw": int(amount_raw),
        "jupiter_request_id": str(jupiter_request_id or "").strip() or None,
        "jupiter_router": str(jupiter_router or "").strip() or None,
        "jupiter_price_impact_percent": _price_impact(jupiter_price_impact_percent),
        "jupiter_slippage_bps": jupiter_slippage_bps,
        "reason_codes": reasons,
        "evidence": evidence,
        "evidence_hash": calculate_payload_hash(evidence),
        "policy": policy,
        "confirmation": f"{TRANSACTION_DRY_RUN_PREFIX}:{dry_run_key}",
    }


def preview_live_transaction_dry_run(
    db: Session,
    *,
    signer_profile_id: str,
    micro_live_simulation_id: str,
    transaction_source: str,
    unsigned_transaction_base64: str,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    jupiter_request_id: str | None,
    jupiter_router: str | None,
    jupiter_price_impact_percent: Any | None,
    jupiter_slippage_bps: int | None,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    preview = _structural_preview(
        db,
        signer_profile_id=signer_profile_id,
        micro_live_simulation_id=micro_live_simulation_id,
        transaction_source=transaction_source,
        unsigned_transaction_base64=unsigned_transaction_base64,
        input_mint=input_mint,
        output_mint=output_mint,
        amount_raw=amount_raw,
        jupiter_request_id=jupiter_request_id,
        jupiter_router=jupiter_router,
        jupiter_price_impact_percent=jupiter_price_impact_percent,
        jupiter_slippage_bps=jupiter_slippage_bps,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=_aware(evaluated_at),
    )
    return {
        "status": preview["status"],
        "ready": False,
        "dry_run_key": preview["dry_run_key"],
        "existing_dry_run": preview["existing_dry_run"],
        "inspection": preview["inspection"],
        "reason_codes": preview["reason_codes"],
        "evidence_hash": preview["evidence_hash"],
        "policy": preview["policy"],
        "confirmation": preview["confirmation"],
        "safety": preview["evidence"]["safety"],
    }


def run_live_transaction_dry_run(
    db: Session,
    *,
    signer_profile_id: str,
    micro_live_simulation_id: str,
    transaction_source: str,
    unsigned_transaction_base64: str,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    jupiter_request_id: str | None,
    jupiter_router: str | None,
    jupiter_price_impact_percent: Any | None,
    jupiter_slippage_bps: int | None,
    idempotency_token: str,
    run_rpc_simulation: bool,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    prepared_at: datetime | None = None,
    rpc_client: SolanaRpcClient | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENABLED",
            False,
        )
    ):
        raise CanonicalParserLiveTransactionDryRunError(
            "M36 è disabilitata.", code="M36_DISABLED", status_code=409
        )
    now = _aware(prepared_at)
    preview = _structural_preview(
        db,
        signer_profile_id=signer_profile_id,
        micro_live_simulation_id=micro_live_simulation_id,
        transaction_source=transaction_source,
        unsigned_transaction_base64=unsigned_transaction_base64,
        input_mint=input_mint,
        output_mint=output_mint,
        amount_raw=amount_raw,
        jupiter_request_id=jupiter_request_id,
        jupiter_router=jupiter_router,
        jupiter_price_impact_percent=jupiter_price_impact_percent,
        jupiter_slippage_bps=jupiter_slippage_bps,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_dry_run"] is not None:
        return preview["existing_dry_run"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserLiveTransactionDryRunError(
            "Conferma dry-run M36 non valida.",
            code="M36_DRY_RUN_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    reasons = [
        reason for reason in preview["reason_codes"] if reason != "RPC_SIMULATION_PENDING"
    ]
    status = preview["status"]
    rpc_status = "SKIPPED"
    rpc_snapshot: dict[str, Any] = {
        "requested": bool(run_rpc_simulation),
        "enabled": preview["policy"]["rpc_simulation_enabled"],
        "success": False,
        "error": None,
        "units_consumed": None,
        "logs": [],
    }
    structurally_blocked = status in {"BLOCKED", "INSUFFICIENT_DATA"}
    if not structurally_blocked:
        if not run_rpc_simulation:
            status = "REVIEW"
            reasons.append("RPC_SIMULATION_SKIPPED")
        elif not preview["policy"]["rpc_simulation_enabled"]:
            status = "REVIEW"
            rpc_status = "UNAVAILABLE"
            reasons.append("RPC_SIMULATION_DISABLED")
        else:
            client = rpc_client or SolanaRpcClient()
            try:
                result = client.simulate_unsigned_transaction_base64(
                    unsigned_transaction_base64
                )
                rpc_snapshot = {
                    "requested": True,
                    "enabled": True,
                    "success": bool(result.get("success")),
                    "error": result.get("error"),
                    "units_consumed": result.get("units_consumed"),
                    "logs": list(result.get("logs") or [])[
                        -preview["policy"]["maximum_simulation_logs"] :
                    ],
                }
                if rpc_snapshot["success"]:
                    rpc_status = "PASSED"
                    if preview["transaction_source"] == "JUPITER_ORDER":
                        status = "READY"
                    else:
                        status = "REVIEW"
                        if "TRANSACTION_PROVENANCE_UNVERIFIED" not in reasons:
                            reasons.append("TRANSACTION_PROVENANCE_UNVERIFIED")
                else:
                    rpc_status = "FAILED"
                    status = "BLOCKED"
                    reasons.append("RPC_SIMULATION_FAILED")
            except Exception as exc:
                rpc_status = "UNAVAILABLE"
                status = "INSUFFICIENT_DATA"
                reasons.append("RPC_SIMULATION_UNAVAILABLE")
                rpc_snapshot = {
                    "requested": True,
                    "enabled": True,
                    "success": False,
                    "error": sanitize_error_message(exc, max_length=500),
                    "units_consumed": None,
                    "logs": [],
                }
    inspection = preview["inspection"]
    dry_run_id = str(uuid4())
    envelope_expires_at = now + timedelta(
        seconds=preview["policy"]["signing_envelope_ttl_seconds"]
    )
    signing_envelope = {
        "scope": "M36_EXTERNAL_SIGNER_ATTESTATION_ONLY",
        "dry_run_id": dry_run_id,
        "signer_profile_id": preview["profile"].profile_id,
        "wallet_address": preview["profile"].wallet_address,
        "network": preview["profile"].network,
        "micro_live_simulation_id": preview["simulation"].simulation_id,
        "micro_live_permit_id": preview["permit"].permit_id,
        "transaction_hash": inspection["transaction_hash"],
        "message_hash": inspection["message_hash"],
        "required_signers": inspection["required_signers"],
        "program_ids": inspection["program_ids"],
        "rpc_simulation_status": rpc_status,
        "eligible_for_external_signing": status == "READY",
        "signing_authorized_by_backend": False,
        "submission_authorized_by_backend": False,
        "issued_at": now.isoformat(),
        "expires_at": envelope_expires_at.isoformat(),
    }
    signing_envelope_hash = calculate_payload_hash(signing_envelope)
    evidence = dict(preview["evidence"])
    evidence["reason_codes"] = sorted(set(reasons))
    evidence["rpc_simulation"] = rpc_snapshot
    evidence["signing_envelope_hash"] = signing_envelope_hash
    evidence["final_status"] = status
    evidence_hash = calculate_payload_hash(evidence)
    row = CanonicalParserLiveTransactionDryRun(
        dry_run_id=dry_run_id,
        dry_run_key=preview["dry_run_key"],
        scope="M36_PRE_SIGN_DRY_RUN_ONLY",
        signer_profile_db_id=preview["profile"].id,
        signer_profile_id=preview["profile"].profile_id,
        micro_live_simulation_db_id=preview["simulation"].id,
        micro_live_simulation_id=preview["simulation"].simulation_id,
        micro_live_permit_id=preview["permit"].permit_id,
        decision_result_id=preview["simulation"].decision_result_id,
        side=preview["simulation"].side,
        status=status,
        transaction_source=preview["transaction_source"],
        transaction_format=inspection["transaction_format"],
        token_mint=preview["simulation"].token_mint,
        input_mint=preview["input_mint"],
        output_mint=preview["output_mint"],
        amount_raw=Decimal(preview["amount_raw"]),
        requested_budget_sol=_decimal(preview["simulation"].simulated_budget_sol).quantize(
            _MONEY_QUANTUM
        ),
        transaction_size_bytes=inspection["transaction_size_bytes"],
        signature_slot_count=inspection["signature_slot_count"],
        required_signer_count=inspection["required_signer_count"],
        static_account_count=inspection["static_account_count"],
        instruction_count=inspection["instruction_count"],
        address_lookup_count=inspection["address_lookup_count"],
        required_signers=inspection["required_signers"],
        program_ids=inspection["program_ids"],
        writable_accounts=inspection["writable_accounts"],
        transaction_hash=inspection["transaction_hash"],
        message_hash=inspection["message_hash"],
        account_keys_hash=inspection["account_keys_hash"],
        jupiter_request_id=preview["jupiter_request_id"],
        jupiter_router=preview["jupiter_router"],
        jupiter_price_impact_percent=(
            None
            if preview["jupiter_price_impact_percent"] is None
            else _decimal(preview["jupiter_price_impact_percent"]).quantize(
                _PRICE_IMPACT_QUANTUM
            )
        ),
        jupiter_slippage_bps=preview["jupiter_slippage_bps"],
        rpc_simulation_status=rpc_status,
        units_consumed=rpc_snapshot.get("units_consumed"),
        reason_codes=sorted(set(reasons)),
        inspection_snapshot=inspection,
        rpc_simulation_snapshot=rpc_snapshot,
        signing_envelope=signing_envelope,
        signing_envelope_hash=signing_envelope_hash,
        evidence_hash=evidence_hash,
        actor_label=_actor(actor_label),
        note=_note(note),
        prepared_at=now,
        envelope_expires_at=envelope_expires_at,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserLiveTransactionDryRun).where(
                CanonicalParserLiveTransactionDryRun.dry_run_key
                == preview["dry_run_key"]
            )
        )
        if duplicate is not None:
            return _serialize_dry_run(duplicate)
        raise CanonicalParserLiveTransactionDryRunError(
            "Conflitto dry-run M36.",
            code="M36_DRY_RUN_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(row)
    return _serialize_dry_run(row)


def get_isolated_signer_profile(db: Session, profile_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserIsolatedSignerProfile).where(
            CanonicalParserIsolatedSignerProfile.profile_id == profile_id
        )
    )
    if row is None:
        raise CanonicalParserLiveTransactionDryRunError(
            "Profilo signer M36 non trovato.",
            code="M36_PROFILE_NOT_FOUND",
            status_code=404,
        )
    payload = _serialize_profile(row)
    payload["events"] = [
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "event_hash": event.event_hash,
            "previous_event_hash": event.previous_event_hash,
            "event_payload": event.event_payload,
            "occurred_at": event.occurred_at,
        }
        for event in db.scalars(
            select(CanonicalParserIsolatedSignerProfileEvent)
            .where(CanonicalParserIsolatedSignerProfileEvent.profile_db_id == row.id)
            .order_by(CanonicalParserIsolatedSignerProfileEvent.sequence.asc())
        )
    ]
    return payload


def get_live_transaction_dry_run(db: Session, dry_run_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserLiveTransactionDryRun).where(
            CanonicalParserLiveTransactionDryRun.dry_run_id == dry_run_id
        )
    )
    if row is None:
        raise CanonicalParserLiveTransactionDryRunError(
            "Dry-run M36 non trovato.",
            code="M36_DRY_RUN_NOT_FOUND",
            status_code=404,
        )
    return _serialize_dry_run(row)


def resolve_live_transaction_dry_run(db: Session) -> dict[str, Any]:
    profile = db.scalar(
        select(CanonicalParserIsolatedSignerProfile)
        .order_by(CanonicalParserIsolatedSignerProfile.created_at.desc())
        .limit(1)
    )
    dry_run = db.scalar(
        select(CanonicalParserLiveTransactionDryRun)
        .order_by(CanonicalParserLiveTransactionDryRun.created_at.desc())
        .limit(1)
    )
    return {
        "latest_profile": None if profile is None else _serialize_profile(profile),
        "latest_dry_run": None if dry_run is None else _serialize_dry_run(dry_run),
        "resolved_status": "EMPTY" if dry_run is None else dry_run.status,
    }


def get_live_transaction_dry_run_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    return {
        "enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_LIVE_TRANSACTION_DRY_RUN_ENABLED",
                False,
            )
        ),
        "signer_profile_count": int(
            db.scalar(select(func.count(CanonicalParserIsolatedSignerProfile.id))) or 0
        ),
        "dry_run_count": int(
            db.scalar(select(func.count(CanonicalParserLiveTransactionDryRun.id))) or 0
        ),
        "policy": _policy(settings_object),
        "safety": {
            "public_key_metadata_only": True,
            "credential_material_loaded": False,
            "legacy_signer_imported": False,
            "signer_connected": False,
            "transaction_signing_available": False,
            "transaction_submission_available": False,
            "live_engine_connected": False,
            "worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
        },
    }
