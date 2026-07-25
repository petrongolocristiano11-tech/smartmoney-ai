from __future__ import annotations

import copy
import hashlib
import inspect
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from threading import RLock
from typing import Any, Callable

from backend.app.models.blockchain_integrity import RawBlockchainEvent
from backend.app.services.trade_engine import build_trade, normalize_swap
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    canonicalize_payload,
    sanitize_technical_metadata,
)


_PARSER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,79}$")
_PARSER_VERSION_PATTERN = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$"
)
_ARTIFACT_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,79}$")


class ParserRegistryError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 422,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class NormalizedArtifactPayload:
    artifact_type: str
    schema_version: str
    payload: dict | list
    metadata: dict[str, Any] | None = None


ParserCallable = Callable[[RawBlockchainEvent], list[NormalizedArtifactPayload]]


@dataclass(frozen=True, slots=True)
class ParserDefinition:
    name: str
    version: str
    description: str
    supported_providers: frozenset[str]
    supported_event_types: frozenset[str]
    output_schema_version: str
    parse: ParserCallable
    deterministic: bool = True
    performs_external_requests: bool = False
    writes_trades: bool = False
    enabled: bool = True
    implementation_hash: str = ""

    def supports(self, event: RawBlockchainEvent) -> bool:
        return (
            event.provider.lower() in self.supported_providers
            and event.event_type.upper() in self.supported_event_types
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "supported_providers": sorted(self.supported_providers),
            "supported_event_types": sorted(self.supported_event_types),
            "output_schema_version": self.output_schema_version,
            "deterministic": self.deterministic,
            "performs_external_requests": self.performs_external_requests,
            "writes_trades": self.writes_trades,
            "enabled": self.enabled,
            "implementation_hash": self.implementation_hash,
        }


class ParserRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], ParserDefinition] = {}
        self._lock = RLock()

    @staticmethod
    def _normalize_definition(
        definition: ParserDefinition,
    ) -> ParserDefinition:
        name = str(definition.name or "").strip().lower()
        version = str(definition.version or "").strip()
        if not _PARSER_NAME_PATTERN.fullmatch(name):
            raise ParserRegistryError(
                "Nome parser non valido.",
                code="PARSER_NAME_INVALID",
            )
        if not _PARSER_VERSION_PATTERN.fullmatch(version):
            raise ParserRegistryError(
                "Versione parser non valida; usare SemVer.",
                code="PARSER_VERSION_INVALID",
            )
        providers = frozenset(
            str(provider).strip().lower()
            for provider in definition.supported_providers
            if str(provider).strip()
        )
        event_types = frozenset(
            str(event_type).strip().upper()
            for event_type in definition.supported_event_types
            if str(event_type).strip()
        )
        if not providers or not event_types:
            raise ParserRegistryError(
                "Il parser deve dichiarare provider ed event type supportati.",
                code="PARSER_COMPATIBILITY_EMPTY",
            )
        if definition.performs_external_requests:
            raise ParserRegistryError(
                "I parser del replay controllato non possono fare richieste esterne.",
                code="PARSER_NETWORK_FORBIDDEN",
            )
        if definition.writes_trades:
            raise ParserRegistryError(
                "I parser M4 non possono scrivere Trade.",
                code="PARSER_TRADE_WRITES_FORBIDDEN",
            )
        if not callable(definition.parse):
            raise ParserRegistryError(
                "Implementazione parser non invocabile.",
                code="PARSER_IMPLEMENTATION_INVALID",
            )

        manifest = {
            "name": name,
            "version": version,
            "description": str(definition.description or "").strip(),
            "supported_providers": sorted(providers),
            "supported_event_types": sorted(event_types),
            "output_schema_version": str(
                definition.output_schema_version or ""
            ).strip(),
            "deterministic": bool(definition.deterministic),
            "performs_external_requests": False,
            "writes_trades": False,
            "source": inspect.getsource(definition.parse),
        }
        implementation_hash = hashlib.sha256(
            canonicalize_payload(manifest).encode("utf-8")
        ).hexdigest()
        return ParserDefinition(
            name=name,
            version=version,
            description=manifest["description"],
            supported_providers=providers,
            supported_event_types=event_types,
            output_schema_version=manifest["output_schema_version"],
            parse=definition.parse,
            deterministic=bool(definition.deterministic),
            performs_external_requests=False,
            writes_trades=False,
            enabled=bool(definition.enabled),
            implementation_hash=implementation_hash,
        )

    def register(self, definition: ParserDefinition) -> ParserDefinition:
        normalized = self._normalize_definition(definition)
        key = (normalized.name, normalized.version)
        with self._lock:
            if key in self._definitions:
                raise ParserRegistryError(
                    "Parser e versione già registrati.",
                    code="PARSER_VERSION_ALREADY_REGISTERED",
                    status_code=409,
                )
            self._definitions[key] = normalized
        return normalized

    def get(self, name: str, version: str) -> ParserDefinition:
        key = (
            str(name or "").strip().lower(),
            str(version or "").strip(),
        )
        definition = self._definitions.get(key)
        if definition is None:
            raise ParserRegistryError(
                "Parser o versione non registrati.",
                code="PARSER_NOT_FOUND",
                status_code=404,
            )
        if not definition.enabled:
            raise ParserRegistryError(
                "Parser registrato ma disabilitato.",
                code="PARSER_DISABLED",
                status_code=409,
            )
        return definition

    def list(self) -> list[ParserDefinition]:
        return [
            self._definitions[key]
            for key in sorted(self._definitions)
        ]

    def manifest_hash(self) -> str:
        manifest = [definition.as_dict() for definition in self.list()]
        return hashlib.sha256(
            canonicalize_payload(manifest).encode("utf-8")
        ).hexdigest()


def _iso_or_none(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_raw_event_envelope(
    event: RawBlockchainEvent,
) -> list[NormalizedArtifactPayload]:
    payload = {
        "provider": event.provider,
        "chain": event.chain,
        "network": event.network,
        "event_type": event.event_type,
        "transaction_signature": event.transaction_signature,
        "slot": event.slot,
        "block_time": _iso_or_none(event.block_time),
        "observed_wallet": event.observed_wallet,
        "commitment": event.commitment,
        "raw_payload": copy.deepcopy(event.raw_payload),
        "raw_payload_hash": event.payload_hash,
    }
    return [
        NormalizedArtifactPayload(
            artifact_type="RAW_EVENT_ENVELOPE",
            schema_version="raw-event-envelope/1",
            payload=payload,
            metadata={
                "source": "raw_blockchain_events",
                "deterministic": True,
            },
        )
    ]



def _canonical_decimal_string(value: object) -> str | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _timestamp_iso(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, OverflowError, TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _transaction_items(payload: dict | list) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [copy.deepcopy(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    if isinstance(result, list):
        return [copy.deepcopy(item) for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        return [copy.deepcopy(result)]
    return [copy.deepcopy(payload)]


def parse_swap_canonical_events(
    event: RawBlockchainEvent,
) -> list[NormalizedArtifactPayload]:
    artifacts: list[NormalizedArtifactPayload] = []
    for raw_index, transaction in enumerate(_transaction_items(event.raw_payload)):
        transaction_type = str(transaction.get("type") or "").strip().upper()
        if transaction_type != "SWAP":
            continue

        normalized = normalize_swap(
            transaction,
            wallet_address=event.observed_wallet,
        )
        reconstructed = build_trade(normalized)
        signature = str(reconstructed.get("signature") or "").strip() or None
        wallet = str(reconstructed.get("wallet_address") or "").strip() or None
        side = str(reconstructed.get("side") or "UNKNOWN").strip().upper()
        if side not in {"BUY", "SELL"}:
            side = "UNKNOWN"
        token_mint = str(reconstructed.get("token_mint") or "").strip() or None
        token_amount = _canonical_decimal_string(reconstructed.get("token_amount"))
        sol_amount = _canonical_decimal_string(reconstructed.get("sol_amount"))

        flags: list[str] = []
        if not signature:
            flags.append("MISSING_SIGNATURE")
        if not wallet:
            flags.append("MISSING_WALLET")
        if side == "UNKNOWN":
            flags.append("UNKNOWN_SIDE")
        if not token_mint:
            flags.append("MISSING_TOKEN_MINT")
        if token_amount is None:
            flags.append("MISSING_TOKEN_AMOUNT")
        if sol_amount is None:
            flags.append("MISSING_SOL_AMOUNT")

        if {"MISSING_SIGNATURE", "MISSING_WALLET"} & set(flags):
            quality_status = "FAIL"
        elif flags:
            quality_status = "WARN"
        else:
            quality_status = "PASS"

        raw_item_hash = calculate_payload_hash(transaction)
        payload = {
            "canonical_type": "SWAP",
            "schema_version": "canonical-swap/1",
            "signature": signature,
            "wallet_address": wallet,
            "side": side,
            "source": str(reconstructed.get("source") or "").strip() or None,
            "token_mint": token_mint,
            "token_amount": token_amount,
            "sol_amount": sol_amount,
            "fee_lamports": transaction.get("fee"),
            "success": not bool(transaction.get("transactionError")),
            "block_time": _timestamp_iso(transaction.get("timestamp")),
            "legacy_reconstruction_parser": reconstructed.get("parser"),
            "quality_status": quality_status,
            "quality_flags": flags,
            "raw_transaction_hash": raw_item_hash,
        }
        artifacts.append(
            NormalizedArtifactPayload(
                artifact_type="CANONICAL_SWAP_EVENT",
                schema_version="canonical-swap/1",
                payload=payload,
                metadata={
                    "source": "trade_engine_shadow_adapter",
                    "raw_item_index": raw_index,
                    "raw_transaction_hash": raw_item_hash,
                    "deterministic": True,
                    "writes_trades": False,
                    "external_requests": 0,
                },
            )
        )
    return artifacts

def validate_parser_artifacts(
    definition: ParserDefinition,
    artifacts: list[NormalizedArtifactPayload],
) -> list[dict[str, Any]]:
    if not isinstance(artifacts, list):
        raise ParserRegistryError(
            "Il parser deve restituire una lista di artifact.",
            code="PARSER_OUTPUT_INVALID",
            status_code=500,
        )
    normalized: list[dict[str, Any]] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, NormalizedArtifactPayload):
            raise ParserRegistryError(
                "Artifact parser non valido.",
                code="PARSER_ARTIFACT_INVALID",
                status_code=500,
            )
        artifact_type = str(artifact.artifact_type or "").strip().upper()
        schema_version = str(artifact.schema_version or "").strip()
        if not _ARTIFACT_TYPE_PATTERN.fullmatch(artifact_type):
            raise ParserRegistryError(
                "Artifact type non valido.",
                code="PARSER_ARTIFACT_TYPE_INVALID",
                status_code=500,
            )
        if not schema_version:
            raise ParserRegistryError(
                "Schema version artifact mancante.",
                code="PARSER_ARTIFACT_SCHEMA_MISSING",
                status_code=500,
            )
        payload_hash = calculate_payload_hash(artifact.payload)
        normalized.append(
            {
                "artifact_type": artifact_type,
                "artifact_index": index,
                "schema_version": schema_version,
                "payload": copy.deepcopy(artifact.payload),
                "payload_hash": payload_hash,
                "artifact_metadata": sanitize_technical_metadata(
                    artifact.metadata
                ),
            }
        )
    return normalized


DEFAULT_PARSER_REGISTRY = ParserRegistry()
DEFAULT_PARSER_REGISTRY.register(
    ParserDefinition(
        name="raw_event_envelope",
        version="1.0.0",
        description=(
            "Normalizza deterministicamente l'envelope e il payload raw "
            "senza produrre Trade o richieste esterne."
        ),
        supported_providers=frozenset({"helius", "solana_rpc"}),
        supported_event_types=frozenset(
            {
                "WALLET_HISTORY_RESPONSE",
                "ENHANCED_TRANSACTION_RESPONSE",
                "RPC_RESPONSE",
            }
        ),
        output_schema_version="raw-event-envelope/1",
        parse=parse_raw_event_envelope,
    )
)
DEFAULT_PARSER_REGISTRY.register(
    ParserDefinition(
        name="swap_canonical_event",
        version="1.0.0",
        description=(
            "Produce eventi swap canonici deterministici usando soltanto "
            "il payload raw e il motore di ricostruzione esistente, senza "
            "scrivere Trade o fare richieste esterne."
        ),
        supported_providers=frozenset({"helius"}),
        supported_event_types=frozenset(
            {
                "WALLET_HISTORY_RESPONSE",
                "ENHANCED_TRANSACTION_RESPONSE",
            }
        ),
        output_schema_version="canonical-swap/1",
        parse=parse_swap_canonical_events,
    )
)
