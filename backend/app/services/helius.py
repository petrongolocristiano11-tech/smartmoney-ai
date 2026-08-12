from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from backend.app.core.config import settings
from backend.app.services.raw_blockchain_capture_service import (
    RawCaptureContext,
    capture_raw_blockchain_payload_safely,
)
from backend.app.services.helius_credit_guard_service import (
    CATEGORY_ENHANCED,
    CATEGORY_RPC,
    HeliusCreditGuardError,
    reserve_helius_credits,
)
from backend.app.services.trade_engine import normalize_swap


logger = logging.getLogger("smartmoney.helius")

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}


@dataclass(slots=True)
class HeliusRequestError(RuntimeError):
    """Errore Helius sicuro da registrare nei log.

    Il messaggio non contiene mai la API key o la query string originale.
    """

    message: str
    endpoint: str
    status_code: int | None = None
    retryable: bool = False
    attempts: int = 1
    error_code: str = "HELIUS_REQUEST_FAILED"
    continuation_signature: str | None = None

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "endpoint": self.endpoint,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "attempts": self.attempts,
            "continuation_signature": self.continuation_signature,
        }


def _safe_endpoint(url: str) -> str:
    parsed = urlsplit(str(url))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            "",
        )
    )


def _retry_delay_seconds(
    attempt_number: int,
    response: httpx.Response | None = None,
) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(
                    float(retry_after),
                    settings.HELIUS_RETRY_MAX_SECONDS,
                )
            except (TypeError, ValueError):
                pass

    exponential_delay = (
        settings.HELIUS_RETRY_BASE_SECONDS
        * (2 ** max(0, attempt_number - 1))
    )
    return min(
        exponential_delay,
        settings.HELIUS_RETRY_MAX_SECONDS,
    )


def _request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    timeout: float | None = None,
    max_retries: int | None = None,
    credit_category: str | None = None,
    estimated_credits: int = 1,
    request_origin: str = "UNSPECIFIED",
    automatic: bool = False,
) -> Any:
    safe_endpoint = _safe_endpoint(url)
    retry_count = (
        settings.HELIUS_MAX_RETRIES
        if max_retries is None
        else max(0, int(max_retries))
    )
    max_attempts = retry_count + 1
    request_timeout = (
        timeout
        if timeout is not None
        else settings.HELIUS_REQUEST_TIMEOUT_SECONDS
    )

    for attempt in range(1, max_attempts + 1):
        response: httpx.Response | None = None

        if credit_category is not None:
            try:
                reserve_helius_credits(
                    category=credit_category,
                    estimated_credits=estimated_credits,
                    origin=request_origin,
                    automatic=automatic,
                )
            except HeliusCreditGuardError as error:
                raise HeliusRequestError(
                    message=error.message,
                    endpoint=safe_endpoint,
                    retryable=False,
                    attempts=max(0, attempt - 1),
                    error_code=error.code,
                ) from None

        try:
            response = httpx.request(
                method,
                url,
                params=params,
                json=json,
                timeout=request_timeout,
            )
        except httpx.RequestError as exc:
            if attempt < max_attempts:
                delay = _retry_delay_seconds(attempt)
                logger.warning(
                    "helius_request_retry endpoint=%s attempt=%s/%s "
                    "reason=%s delay_seconds=%.2f",
                    safe_endpoint,
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    delay,
                )
                time.sleep(delay)
                continue

            raise HeliusRequestError(
                message=(
                    "Helius non raggiungibile dopo "
                    f"{attempt} tentativi."
                ),
                endpoint=safe_endpoint,
                retryable=True,
                attempts=attempt,
                error_code="HELIUS_NETWORK_ERROR",
            ) from None

        status_code = response.status_code
        if status_code >= 400:
            retryable = status_code in RETRYABLE_STATUS_CODES

            if retryable and attempt < max_attempts:
                delay = _retry_delay_seconds(attempt, response)
                logger.warning(
                    "helius_http_retry endpoint=%s status=%s "
                    "attempt=%s/%s delay_seconds=%.2f",
                    safe_endpoint,
                    status_code,
                    attempt,
                    max_attempts,
                    delay,
                )
                time.sleep(delay)
                continue

            continuation_signature: str | None = None
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = None
            if isinstance(error_payload, dict):
                raw_error = str(
                    error_payload.get("error")
                    or error_payload.get("message")
                    or ""
                )
                marker_index = raw_error.lower().find("before-signature")
                if marker_index >= 0:
                    continuation_candidates = re.findall(
                        r"\b[1-9A-HJ-NP-Za-km-z]{40,128}\b",
                        raw_error[marker_index + len("before-signature"):],
                    )
                    if continuation_candidates:
                        continuation_signature = continuation_candidates[0]

            raise HeliusRequestError(
                message=(
                    "Helius richiede una firma di continuazione per proseguire "
                    "la ricerca filtrata."
                    if continuation_signature
                    else (
                        "Helius ha risposto HTTP "
                        f"{status_code} dopo {attempt} tentativi."
                    )
                ),
                endpoint=safe_endpoint,
                status_code=status_code,
                retryable=retryable or bool(continuation_signature),
                attempts=attempt,
                error_code=(
                    "HELIUS_CONTINUATION_REQUIRED"
                    if continuation_signature
                    else (
                        "HELIUS_RETRY_EXHAUSTED"
                        if retryable
                        else "HELIUS_HTTP_ERROR"
                    )
                ),
                continuation_signature=continuation_signature,
            ) from None

        try:
            return response.json()
        except ValueError:
            if attempt < max_attempts:
                delay = _retry_delay_seconds(attempt)
                logger.warning(
                    "helius_invalid_json_retry endpoint=%s "
                    "attempt=%s/%s delay_seconds=%.2f",
                    safe_endpoint,
                    attempt,
                    max_attempts,
                    delay,
                )
                time.sleep(delay)
                continue

            raise HeliusRequestError(
                message=(
                    "Helius ha restituito una risposta JSON non valida "
                    f"dopo {attempt} tentativi."
                ),
                endpoint=safe_endpoint,
                status_code=status_code,
                retryable=True,
                attempts=attempt,
                error_code="HELIUS_INVALID_JSON",
            ) from None

    raise AssertionError("Ciclo retry Helius terminato in modo inatteso.")


def get_helius_rpc_url() -> str:
    return "https://mainnet.helius-rpc.com/"


def _first_payload_item(payload: object) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return None


def _capture_helius_payload(
    payload: object,
    *,
    event_type: str,
    transaction_signature: str | None = None,
    observed_wallet: str | None = None,
    commitment: str | None = None,
    technical_metadata: dict[str, Any] | None = None,
) -> None:
    first_item = _first_payload_item(payload)
    inferred_signature = transaction_signature
    inferred_slot: int | None = None
    inferred_block_time: int | float | None = None

    if first_item is not None:
        if inferred_signature is None:
            raw_signature = first_item.get("signature")
            if raw_signature:
                inferred_signature = str(raw_signature)

        raw_slot = first_item.get("slot")
        if raw_slot is not None:
            try:
                inferred_slot = int(raw_slot)
            except (TypeError, ValueError):
                inferred_slot = None

        raw_block_time = (
            first_item.get("timestamp")
            if first_item.get("timestamp") is not None
            else first_item.get("blockTime")
        )
        if isinstance(raw_block_time, (int, float)):
            inferred_block_time = raw_block_time

    capture_raw_blockchain_payload_safely(
        payload,
        context=RawCaptureContext(
            provider="helius",
            event_type=event_type,
            transaction_signature=inferred_signature,
            slot=inferred_slot,
            block_time=inferred_block_time,
            observed_wallet=observed_wallet,
            commitment=commitment,
            technical_metadata=technical_metadata,
        ),
    )


def _rpc_capture_identity(
    method: str,
    params: list[Any],
) -> tuple[str | None, str | None, str | None]:
    observed_wallet: str | None = None
    transaction_signature: str | None = None
    commitment: str | None = None

    wallet_methods = {
        "getBalance",
        "getSignaturesForAddress",
        "getTokenAccountsByOwner",
        "getTokenAccountBalance",
    }
    if method in wallet_methods and params and isinstance(params[0], str):
        observed_wallet = params[0]

    if method == "getTransaction" and params and isinstance(params[0], str):
        transaction_signature = params[0]
    elif method == "getSignatureStatuses" and params:
        signatures = params[0]
        if isinstance(signatures, list) and signatures:
            transaction_signature = str(signatures[0])

    for item in params:
        if isinstance(item, dict) and item.get("commitment"):
            commitment = str(item["commitment"])
            break

    return observed_wallet, transaction_signature, commitment


def helius_rpc_call(
    method: str,
    params: list[Any] | None = None,
    *,
    request_origin: str = "MANUAL_RPC",
    automatic: bool = False,
) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }

    result = _request_json(
        "POST",
        get_helius_rpc_url(),
        params={"api-key": settings.HELIUS_API_KEY},
        json=payload,
        credit_category=CATEGORY_RPC,
        estimated_credits=(10 if method == "getProgramAccounts" else 1),
        request_origin=request_origin,
        automatic=automatic,
    )

    observed_wallet, transaction_signature, commitment = (
        _rpc_capture_identity(method, payload["params"])
    )
    _capture_helius_payload(
        result,
        event_type="RPC_RESPONSE",
        transaction_signature=transaction_signature,
        observed_wallet=observed_wallet,
        commitment=commitment,
        technical_metadata={
            "rpc_method": method,
            "endpoint": get_helius_rpc_url(),
        },
    )

    if isinstance(result, dict) and result.get("error"):
        error = result.get("error") or {}
        code = error.get("code") if isinstance(error, dict) else None
        raise HeliusRequestError(
            message=(
                "Helius RPC ha restituito un errore"
                + (f" ({code})." if code is not None else ".")
            ),
            endpoint=get_helius_rpc_url(),
            retryable=False,
            attempts=1,
            error_code="HELIUS_RPC_ERROR",
        )

    return result


def get_helius_health(
    *,
    request_origin: str = "MANUAL_HEALTH",
    automatic: bool = False,
) -> Any:
    return helius_rpc_call(
        "getHealth",
        request_origin=request_origin,
        automatic=automatic,
    )


def get_enhanced_transaction(
    signature: str,
    *,
    request_origin: str = "MANUAL_ENHANCED_TRANSACTION",
    automatic: bool = False,
) -> list[dict[str, Any]]:
    result = _request_json(
        "POST",
        "https://api.helius.xyz/v0/transactions/",
        params={"api-key": settings.HELIUS_API_KEY},
        json={"transactions": [signature]},
        credit_category=CATEGORY_ENHANCED,
        estimated_credits=100,
        request_origin=request_origin,
        automatic=automatic,
    )

    if not isinstance(result, list):
        raise HeliusRequestError(
            message="Helius Enhanced Transactions ha restituito un formato inatteso.",
            endpoint="https://api.helius.xyz/v0/transactions/",
            retryable=False,
            attempts=1,
            error_code="HELIUS_INVALID_PAYLOAD",
        )

    _capture_helius_payload(
        result,
        event_type="ENHANCED_TRANSACTION_RESPONSE",
        transaction_signature=signature,
        technical_metadata={
            "endpoint": "https://api.helius.xyz/v0/transactions/",
        },
    )

    return result


def get_wallet_history(
    address: str,
    *,
    limit: int = 100,
    transaction_type: str | None = None,
    gte_time: int | None = None,
    lte_time: int | None = None,
    before_signature: str | None = None,
    commitment: str = "finalized",
    token_accounts: str = "none",
    max_retries: int | None = None,
    request_origin: str = "MANUAL_WALLET_HISTORY",
    automatic: bool = False,
) -> list[dict[str, Any]]:
    endpoint = (
        "https://mainnet.helius-rpc.com/v0/addresses/"
        f"{address}/transactions"
    )
    params: dict[str, Any] = {
        "api-key": settings.HELIUS_API_KEY,
        "limit": max(1, min(int(limit), 100)),
        "commitment": commitment,
        "token-accounts": token_accounts,
        "sort-order": "desc",
    }
    if transaction_type:
        params["type"] = str(transaction_type).upper()
    if gte_time is not None:
        params["gte-time"] = int(gte_time)
    if lte_time is not None:
        params["lte-time"] = int(lte_time)
    if before_signature:
        params["before-signature"] = str(before_signature)

    result = _request_json(
        "GET",
        endpoint,
        params=params,
        max_retries=max_retries,
        credit_category=CATEGORY_ENHANCED,
        estimated_credits=100,
        request_origin=request_origin,
        automatic=automatic,
    )

    if not isinstance(result, list):
        raise HeliusRequestError(
            message="Helius Wallet History ha restituito un formato inatteso.",
            endpoint=_safe_endpoint(endpoint),
            retryable=False,
            attempts=1,
            error_code="HELIUS_INVALID_PAYLOAD",
        )

    _capture_helius_payload(
        result,
        event_type="WALLET_HISTORY_RESPONSE",
        observed_wallet=address,
        commitment=commitment,
        technical_metadata={
            "endpoint": _safe_endpoint(endpoint),
            "transaction_type": (
                str(transaction_type).upper()
                if transaction_type
                else None
            ),
            "requested_limit": params["limit"],
            "has_before_signature": bool(before_signature),
        },
    )

    return [item for item in result if isinstance(item, dict)]


def get_wallet_swaps(
    address: str,
    *,
    limit: int = 100,
    gte_time: int | None = None,
    max_retries: int | None = None,
    request_origin: str = "MANUAL_WALLET_SWAPS",
    automatic: bool = False,
) -> dict[str, Any]:
    transactions = get_wallet_history(
        address,
        limit=limit,
        transaction_type="SWAP",
        gte_time=gte_time,
        commitment="confirmed",
        token_accounts="balanceChanged",
        max_retries=max_retries,
        request_origin=request_origin,
        automatic=automatic,
    )

    swaps = [
        normalize_swap(transaction, wallet_address=address)
        for transaction in transactions
        if transaction.get("type") == "SWAP"
    ]

    return {
        "wallet": address,
        "swaps_found": len(swaps),
        "swaps": swaps,
    }
