from dataclasses import dataclass
import time
from typing import Any, Callable

import httpx

from backend.app.core.config import settings
from backend.app.services.live_trading_errors import (
    JupiterSwapError,
)


@dataclass(frozen=True)
class JupiterOrderResult:
    raw: dict[str, Any]
    request_id: str
    transaction: str | None
    in_amount: int
    out_amount: int
    slippage_bps: int
    router: str | None
    price_impact_percent: float
    last_valid_block_height: str | None


@dataclass(frozen=True)
class JupiterExecuteResult:
    raw: dict[str, Any]
    success: bool
    signature: str | None
    code: int | None
    error: str | None
    input_amount: int | None
    output_amount: int | None


class JupiterSwapClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        transport: (
            httpx.BaseTransport
            | None
        ) = None,
    ):
        self.api_key = (
            api_key
            if api_key is not None
            else settings.JUPITER_API_KEY
        ).strip()

        self.base_url = (
            base_url
            if base_url is not None
            else settings.JUPITER_SWAP_API_URL
        ).rstrip("/")

        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else (
                settings
                .JUPITER_SWAP_TIMEOUT_SECONDS
            )
        )

        self.max_retries = max(
            0,
            int(
                max_retries
                if max_retries is not None
                else settings.JUPITER_SWAP_MAX_RETRIES
            ),
        )

        self.retry_base_seconds = max(
            0.0,
            float(
                retry_base_seconds
                if retry_base_seconds is not None
                else settings.JUPITER_SWAP_RETRY_BASE_SECONDS
            ),
        )

        self.retry_max_seconds = max(
            self.retry_base_seconds,
            float(
                retry_max_seconds
                if retry_max_seconds is not None
                else settings.JUPITER_SWAP_RETRY_MAX_SECONDS
            ),
        )

        self.sleep_fn = sleep_fn or time.sleep
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise JupiterSwapError(
                "JUPITER_API_KEY non configurata.",
                code="JUPITER_NOT_CONFIGURED",
                status_code=503,
            )

        return {
            "x-api-key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _parse_int(
        value: Any,
        field_name: str,
        *,
        required: bool = True,
    ) -> int | None:
        if value in (None, ""):
            if required:
                raise JupiterSwapError(
                    "Risposta Jupiter priva "
                    f"di {field_name}.",
                    code="JUPITER_INVALID_RESPONSE",
                    status_code=502,
                )

            return None

        try:
            return int(value)

        except (
            TypeError,
            ValueError,
        ) as exception:
            raise JupiterSwapError(
                "Valore Jupiter non valido "
                f"per {field_name}.",
                code="JUPITER_INVALID_RESPONSE",
                status_code=502,
            ) from exception

    @staticmethod
    def _parse_float(
        value: Any,
        default: float = 0.0,
    ) -> float:
        if value in (None, ""):
            return default

        try:
            return float(value)

        except (
            TypeError,
            ValueError,
        ):
            return default

    def _retry_delay(
        self,
        attempt_index: int,
    ) -> float:
        return min(
            self.retry_max_seconds,
            self.retry_base_seconds
            * (2 ** max(0, attempt_index)),
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> dict[str, Any]:
        maximum_attempts = (
            self.max_retries + 1
            if retryable
            else 1
        )

        retryable_statuses = {
            429,
            500,
            502,
            503,
            504,
        }

        for attempt_index in range(
            maximum_attempts
        ):
            attempt_number = attempt_index + 1
            has_next_attempt = (
                attempt_number
                < maximum_attempts
            )

            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=self._headers(),
                        params=params,
                        json=json,
                    )

            except httpx.TimeoutException as exception:
                if has_next_attempt:
                    self.sleep_fn(
                        self._retry_delay(
                            attempt_index
                        )
                    )
                    continue

                raise JupiterSwapError(
                    "Timeout durante la richiesta "
                    "a Jupiter.",
                    code="JUPITER_TIMEOUT",
                    status_code=504,
                    payload={
                        "attempts":
                            attempt_number,
                        "retryable":
                            retryable,
                    },
                ) from exception

            except httpx.HTTPError as exception:
                if has_next_attempt:
                    self.sleep_fn(
                        self._retry_delay(
                            attempt_index
                        )
                    )
                    continue

                raise JupiterSwapError(
                    "Errore di rete durante la "
                    "richiesta a Jupiter.",
                    code="JUPITER_NETWORK_ERROR",
                    status_code=502,
                    payload={
                        "attempts":
                            attempt_number,
                        "retryable":
                            retryable,
                        "error_type":
                            type(
                                exception
                            ).__name__,
                    },
                ) from exception

            if (
                retryable
                and response.status_code
                in retryable_statuses
                and has_next_attempt
            ):
                retry_after = (
                    response.headers.get(
                        "Retry-After"
                    )
                )

                delay = self._retry_delay(
                    attempt_index
                )

                if retry_after:
                    try:
                        delay = min(
                            self.retry_max_seconds,
                            max(
                                delay,
                                float(
                                    retry_after
                                ),
                            ),
                        )
                    except ValueError:
                        pass

                self.sleep_fn(delay)
                continue

            try:
                payload = response.json()

            except ValueError as exception:
                raise JupiterSwapError(
                    "Jupiter ha restituito una "
                    "risposta non JSON.",
                    code=(
                        "JUPITER_INVALID_RESPONSE"
                    ),
                    status_code=502,
                    payload={
                        "http_status":
                            response.status_code,
                        "attempts":
                            attempt_number,
                    },
                ) from exception

            if not isinstance(
                payload,
                dict,
            ):
                raise JupiterSwapError(
                    "Formato risposta Jupiter "
                    "non valido.",
                    code=(
                        "JUPITER_INVALID_RESPONSE"
                    ),
                    status_code=502,
                    payload={
                        "http_status":
                            response.status_code,
                        "attempts":
                            attempt_number,
                    },
                )

            if response.is_error:
                message = (
                    payload.get("error")
                    or payload.get(
                        "errorMessage"
                    )
                    or payload.get("message")
                    or (
                        "Jupiter HTTP "
                        f"{response.status_code}"
                    )
                )

                raise JupiterSwapError(
                    str(message),
                    code="JUPITER_HTTP_ERROR",
                    status_code=502,
                    payload={
                        "http_status":
                            response.status_code,
                        "attempts":
                            attempt_number,
                        "retryable":
                            retryable,
                        "response":
                            sanitize_jupiter_payload(
                                payload
                            ),
                    },
                )

            return payload

        raise JupiterSwapError(
            "Richiesta Jupiter terminata "
            "senza risposta.",
            code="JUPITER_REQUEST_EXHAUSTED",
            status_code=502,
        )

    def get_order(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_raw: int,
        taker: str | None,
        slippage_bps: int | None = None,
    ) -> JupiterOrderResult:
        if amount_raw <= 0:
            raise JupiterSwapError(
                "L'importo dell'ordine "
                "deve essere positivo.",
                code="INVALID_ORDER_AMOUNT",
                status_code=422,
            )

        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_raw),
        }

        if taker:
            params["taker"] = taker

        if slippage_bps is not None:
            params["slippageBps"] = str(
                slippage_bps
            )

        payload = self._request_json(
            "GET",
            "/order",
            params=params,
            retryable=True,
        )

        request_id = str(
            payload.get("requestId") or ""
        ).strip()

        if not request_id:
            raise JupiterSwapError(
                "Risposta Jupiter priva "
                "di requestId.",
                code="JUPITER_INVALID_RESPONSE",
                status_code=502,
            )

        transaction = payload.get(
            "transaction"
        )

        if transaction is not None:
            transaction = (
                str(transaction).strip()
                or None
            )

        if taker and not transaction:
            error_message = (
                payload.get("errorMessage")
                or payload.get("error")
            )

            raise JupiterSwapError(
                str(
                    error_message
                    or (
                        "Jupiter non ha restituito "
                        "una transazione da firmare."
                    )
                ),
                code="JUPITER_TRANSACTION_MISSING",
                status_code=502,
                payload=sanitize_jupiter_payload(
                    payload
                ),
            )

        last_valid_block_height = (
            payload.get(
                "lastValidBlockHeight"
            )
        )

        return JupiterOrderResult(
            raw=payload,
            request_id=request_id,
            transaction=transaction,
            in_amount=int(
                self._parse_int(
                    payload.get("inAmount"),
                    "inAmount",
                )
            ),
            out_amount=int(
                self._parse_int(
                    payload.get("outAmount"),
                    "outAmount",
                )
            ),
            slippage_bps=int(
                self._parse_int(
                    payload.get(
                        "slippageBps",
                        slippage_bps or 0,
                    ),
                    "slippageBps",
                )
            ),
            router=(
                str(
                    payload.get("router")
                ).strip()
                if payload.get("router")
                else None
            ),
            price_impact_percent=(
                self._parse_float(
                    payload.get(
                        "priceImpact",
                        payload.get(
                            "priceImpactPct"
                        ),
                    ),
                    0.0,
                )
            ),
            last_valid_block_height=(
                str(last_valid_block_height)
                if last_valid_block_height
                not in (None, "")
                else None
            ),
        )

    def execute_order(
        self,
        *,
        signed_transaction: str,
        request_id: str,
        last_valid_block_height: (
            str | int | None
        ) = None,
    ) -> JupiterExecuteResult:
        body: dict[str, Any] = {
            "signedTransaction":
                signed_transaction,
            "requestId": request_id,
        }

        if (
            last_valid_block_height
            is not None
        ):
            body[
                "lastValidBlockHeight"
            ] = str(
                last_valid_block_height
            )

        payload = self._request_json(
            "POST",
            "/execute",
            json=body,
        )

        status_value = str(
            payload.get("status") or ""
        ).strip().lower()

        code_value = payload.get("code")

        try:
            code = (
                int(code_value)
                if code_value is not None
                else None
            )

        except (
            TypeError,
            ValueError,
        ):
            code = None

        return JupiterExecuteResult(
            raw=payload,
            success=(
                status_value == "success"
                and code == 0
            ),
            signature=(
                str(
                    payload.get("signature")
                ).strip()
                if payload.get("signature")
                else None
            ),
            code=code,
            error=(
                str(payload.get("error"))
                if payload.get("error")
                else None
            ),
            input_amount=self._parse_int(
                payload.get(
                    "inputAmountResult",
                    payload.get(
                        "totalInputAmount"
                    ),
                ),
                "inputAmountResult",
                required=False,
            ),
            output_amount=self._parse_int(
                payload.get(
                    "outputAmountResult",
                    payload.get(
                        "totalOutputAmount"
                    ),
                ),
                "outputAmountResult",
                required=False,
            ),
        )


def sanitize_jupiter_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    sanitized = dict(payload)

    for key in (
        "transaction",
        "signedTransaction",
    ):
        if key in sanitized:
            sanitized[key] = "<omitted>"

    return sanitized 