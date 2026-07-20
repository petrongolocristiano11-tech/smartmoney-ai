from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from backend.app.core.config import settings
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
) -> Any:
    safe_endpoint = _safe_endpoint(url)
    max_attempts = settings.HELIUS_MAX_RETRIES + 1
    request_timeout = (
        timeout
        if timeout is not None
        else settings.HELIUS_REQUEST_TIMEOUT_SECONDS
    )

    for attempt in range(1, max_attempts + 1):
        response: httpx.Response | None = None

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

            raise HeliusRequestError(
                message=(
                    "Helius ha risposto HTTP "
                    f"{status_code} dopo {attempt} tentativi."
                ),
                endpoint=safe_endpoint,
                status_code=status_code,
                retryable=retryable,
                attempts=attempt,
                error_code=(
                    "HELIUS_RETRY_EXHAUSTED"
                    if retryable
                    else "HELIUS_HTTP_ERROR"
                ),
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


def helius_rpc_call(
    method: str,
    params: list[Any] | None = None,
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


def get_helius_health() -> Any:
    return helius_rpc_call("getHealth")


def get_enhanced_transaction(signature: str) -> list[dict[str, Any]]:
    result = _request_json(
        "POST",
        "https://api.helius.xyz/v0/transactions/",
        params={"api-key": settings.HELIUS_API_KEY},
        json={"transactions": [signature]},
    )

    if not isinstance(result, list):
        raise HeliusRequestError(
            message="Helius Enhanced Transactions ha restituito un formato inatteso.",
            endpoint="https://api.helius.xyz/v0/transactions/",
            retryable=False,
            attempts=1,
            error_code="HELIUS_INVALID_PAYLOAD",
        )

    return result


def get_wallet_history(address: str) -> list[dict[str, Any]]:
    endpoint = (
        "https://api.helius.xyz/v0/addresses/"
        f"{address}/transactions"
    )
    result = _request_json(
        "GET",
        endpoint,
        params={"api-key": settings.HELIUS_API_KEY},
    )

    if not isinstance(result, list):
        raise HeliusRequestError(
            message="Helius Wallet History ha restituito un formato inatteso.",
            endpoint=_safe_endpoint(endpoint),
            retryable=False,
            attempts=1,
            error_code="HELIUS_INVALID_PAYLOAD",
        )

    return [item for item in result if isinstance(item, dict)]


def get_wallet_swaps(address: str) -> dict[str, Any]:
    transactions = get_wallet_history(address)

    swaps = [
        normalize_swap(transaction)
        for transaction in transactions
        if transaction.get("type") == "SWAP"
    ]

    return {
        "wallet": address,
        "swaps_found": len(swaps),
        "swaps": swaps,
    }
