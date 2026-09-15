from dataclasses import dataclass
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import httpx

from backend.app.core.config import settings
from backend.app.services.live_trading_errors import (
    JupiterSwapError,
)


_JUPITER_RATE_LIMIT_FALLBACK_RPS = 10
_JUPITER_RATE_LIMIT_HEADROOM_RATIO = 0.80
_JUPITER_RATE_LIMIT_RESET_EPSILON_SECONDS = 0.05


class _SharedJupiterRateLimitCoordinator:
    """Process-wide pacing for the shared Jupiter general API bucket.

    Official and candidate fast-path clients run in the same process and use the
    same API key / organisation quota.  The coordinator therefore serializes
    request *starts* across client instances, preserves headroom below the
    observed RPS limit, and honors the gateway reset timestamp after a 429.
    It never applies to /execute because execute has a dedicated bucket and is
    not retryable in this client.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_request_at = 0.0
        self._blocked_until = 0.0
        self._observed_limit = _JUPITER_RATE_LIMIT_FALLBACK_RPS
        self._critical_waiters = 0

    def _target_rps_locked(self) -> int:
        return max(
            1,
            int(
                self._observed_limit
                * _JUPITER_RATE_LIMIT_HEADROOM_RATIO
            ),
        )

    def acquire(self, *, priority: str = "normal") -> None:
        normalized_priority = str(priority or "normal").strip().lower()
        if normalized_priority not in {"normal", "critical", "diagnostic"}:
            raise ValueError("JUPITER_RATE_LIMIT_PRIORITY_INVALID")

        critical_registered = False
        if normalized_priority == "critical":
            with self._lock:
                self._critical_waiters += 1
                critical_registered = True

        try:
            while True:
                with self._lock:
                    now = time.monotonic()
                    ready_at = max(
                        self._next_request_at,
                        self._blocked_until,
                    )
                    if (
                        normalized_priority == "diagnostic"
                        and self._critical_waiters > 0
                    ):
                        interval = 1.0 / float(
                            self._target_rps_locked()
                        )
                        delay = max(
                            0.005,
                            min(
                                0.050,
                                max(0.0, ready_at - now)
                                or (interval / 4.0),
                            ),
                        )
                    elif ready_at <= now:
                        interval = 1.0 / float(
                            self._target_rps_locked()
                        )
                        self._next_request_at = now + interval
                        if critical_registered:
                            self._critical_waiters = max(
                                0,
                                self._critical_waiters - 1,
                            )
                            critical_registered = False
                        return
                    else:
                        delay = max(0.0, ready_at - now)
                time.sleep(delay)
        finally:
            if critical_registered:
                with self._lock:
                    self._critical_waiters = max(
                        0,
                        self._critical_waiters - 1,
                    )

    def observe(self, headers: Any) -> None:
        current = _parse_nonnegative_int_header(
            headers,
            "x-ratelimit-current",
        )
        remaining = _parse_nonnegative_int_header(
            headers,
            "x-ratelimit-remaining",
        )
        if current is None or remaining is None:
            return
        observed_limit = current + remaining
        if observed_limit <= 0:
            return
        with self._lock:
            self._observed_limit = observed_limit

    def block_until_reset(self, headers: Any) -> float:
        reset_value = _header_value(
            headers,
            "x-ratelimit-reset",
        )
        delay = 0.0
        if reset_value:
            try:
                delay = max(
                    0.0,
                    float(reset_value)
                    - time.time()
                    + _JUPITER_RATE_LIMIT_RESET_EPSILON_SECONDS,
                )
            except (TypeError, ValueError):
                delay = 0.0
        with self._lock:
            if delay > 0.0:
                self._blocked_until = max(
                    self._blocked_until,
                    time.monotonic() + delay,
                )
        return delay


def _header_value(headers: Any, name: str) -> str | None:
    try:
        value = headers.get(name)
    except AttributeError:
        return None
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _parse_nonnegative_int_header(
    headers: Any,
    name: str,
) -> int | None:
    value = _header_value(headers, name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _sanitized_rate_limit_headers(
    headers: Any,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in (
        "x-ratelimit-current",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "retry-after",
    ):
        value = _header_value(headers, name)
        if value is not None:
            result[name] = value
    return result


_SHARED_JUPITER_RATE_LIMIT_COORDINATOR = (
    _SharedJupiterRateLimitCoordinator()
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
    request_timing: dict[str, Any] | None = None


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
        persistent_http: bool = False,
        shared_rate_limit: bool = False,
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
        self.persistent_http = bool(persistent_http)
        self.shared_rate_limit = bool(shared_rate_limit)
        self._persistent_client = (
            httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            )
            if self.persistent_http
            else None
        )

    def close(self) -> None:
        if self._persistent_client is not None:
            self._persistent_client.close()
            self._persistent_client = None

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
        timing_sink: dict[str, Any] | None = None,
        request_priority: str = "normal",
    ) -> dict[str, Any]:
        normalized_request_priority = str(
            request_priority or "normal"
        ).strip().lower()
        if normalized_request_priority not in {
            "normal",
            "critical",
            "diagnostic",
        }:
            raise JupiterSwapError(
                "Priorità interna Jupiter non valida.",
                code="JUPITER_REQUEST_PRIORITY_INVALID",
                status_code=500,
            )

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

        timing_enabled = timing_sink is not None
        request_started = time.perf_counter() if timing_enabled else 0.0
        pacing_wait_ms = 0.0
        http_round_trip_ms = 0.0
        retry_sleep_requested_ms = 0.0
        attempts_started = 0
        status_codes: list[int] = []

        def publish_timing(
            *,
            success: bool,
            error_type: str | None = None,
            http_status: int | None = None,
        ) -> None:
            if timing_sink is None:
                return
            total_ms = max(
                0.0,
                (time.perf_counter() - request_started) * 1000.0,
            )
            timing_sink.clear()
            timing_sink.update(
                {
                    "version": "jupiter-component-timing/1",
                    "method": str(method).upper(),
                    "path": str(path),
                    "attempts": int(attempts_started),
                    "retry_count": max(0, int(attempts_started) - 1),
                    "shared_pacing_wait_ms": round(pacing_wait_ms, 3),
                    "http_round_trip_ms": round(http_round_trip_ms, 3),
                    "retry_sleep_requested_ms": round(
                        retry_sleep_requested_ms,
                        3,
                    ),
                    "endpoint_total_ms": round(total_ms, 3),
                    "status_codes": list(status_codes),
                    "final_http_status": (
                        int(http_status)
                        if http_status is not None
                        else None
                    ),
                    "success": bool(success),
                    "error_type": (
                        str(error_type)
                        if error_type
                        else None
                    ),
                    "retryable": bool(retryable),
                    "shared_rate_limit": bool(
                        retryable and self.shared_rate_limit
                    ),
                    "used_persistent_http": bool(
                        self._persistent_client is not None
                    ),
                    "observation_only": True,
                    "request_priority": normalized_request_priority,
                }
            )

        for attempt_index in range(
            maximum_attempts
        ):
            attempt_number = attempt_index + 1
            attempts_started = attempt_number
            has_next_attempt = (
                attempt_number
                < maximum_attempts
            )

            if retryable and self.shared_rate_limit:
                pacing_started = (
                    time.perf_counter()
                    if timing_enabled
                    else 0.0
                )
                if normalized_request_priority == "normal":
                    # Preserve the historical coordinator call contract exactly.
                    # Existing fakes/tests and legacy callers expose acquire()
                    # with no keyword arguments. Priority is an opt-in extension
                    # used only by the new candidate critical/diagnostic paths.
                    _SHARED_JUPITER_RATE_LIMIT_COORDINATOR.acquire()
                else:
                    _SHARED_JUPITER_RATE_LIMIT_COORDINATOR.acquire(
                        priority=normalized_request_priority,
                    )
                if timing_enabled:
                    pacing_wait_ms += max(
                        0.0,
                        (
                            time.perf_counter()
                            - pacing_started
                        )
                        * 1000.0,
                    )

            http_started = (
                time.perf_counter()
                if timing_enabled
                else 0.0
            )
            try:
                if self._persistent_client is not None:
                    response = self._persistent_client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=self._headers(),
                        params=params,
                        json=json,
                    )
                else:
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
                if timing_enabled:
                    http_round_trip_ms += max(
                        0.0,
                        (
                            time.perf_counter()
                            - http_started
                        )
                        * 1000.0,
                    )
                if has_next_attempt:
                    delay = self._retry_delay(
                        attempt_index
                    )
                    retry_sleep_requested_ms += (
                        delay * 1000.0
                    )
                    self.sleep_fn(delay)
                    continue

                publish_timing(
                    success=False,
                    error_type="TIMEOUT",
                )
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
                if timing_enabled:
                    http_round_trip_ms += max(
                        0.0,
                        (
                            time.perf_counter()
                            - http_started
                        )
                        * 1000.0,
                    )
                if has_next_attempt:
                    delay = self._retry_delay(
                        attempt_index
                    )
                    retry_sleep_requested_ms += (
                        delay * 1000.0
                    )
                    self.sleep_fn(delay)
                    continue

                publish_timing(
                    success=False,
                    error_type=type(exception).__name__,
                )
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

            if timing_enabled:
                http_round_trip_ms += max(
                    0.0,
                    (
                        time.perf_counter()
                        - http_started
                    )
                    * 1000.0,
                )
            status_codes.append(int(response.status_code))

            rate_limit_headers = (
                _sanitized_rate_limit_headers(
                    response.headers
                )
            )
            if retryable and self.shared_rate_limit:
                _SHARED_JUPITER_RATE_LIMIT_COORDINATOR.observe(
                    response.headers
                )

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
                        delay = max(
                            delay,
                            float(retry_after),
                        )
                    except ValueError:
                        pass

                if (
                    response.status_code == 429
                    and self.shared_rate_limit
                ):
                    reset_delay = (
                        _SHARED_JUPITER_RATE_LIMIT_COORDINATOR
                        .block_until_reset(
                            response.headers
                        )
                    )
                    delay = max(delay, reset_delay)

                # A gateway reset is authoritative.  Do not cap it to the
                # generic exponential-backoff ceiling; the current Swap V2
                # general bucket is per-second and this prevents blind retries
                # before the advertised reset boundary.
                retry_sleep_requested_ms += (
                    delay * 1000.0
                )
                self.sleep_fn(delay)
                continue

            try:
                payload = response.json()

            except ValueError as exception:
                publish_timing(
                    success=False,
                    error_type="INVALID_JSON",
                    http_status=response.status_code,
                )
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
                publish_timing(
                    success=False,
                    error_type="INVALID_RESPONSE_SHAPE",
                    http_status=response.status_code,
                )
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

                publish_timing(
                    success=False,
                    error_type="HTTP_ERROR",
                    http_status=response.status_code,
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
                        "rate_limit_headers":
                            rate_limit_headers,
                    },
                )

            publish_timing(
                success=True,
                http_status=response.status_code,
            )
            return payload

        publish_timing(
            success=False,
            error_type="REQUEST_EXHAUSTED",
        )
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

    @staticmethod
    def _valid_unsigned_build_instruction(
        value: Any,
    ) -> bool:
        return (
            isinstance(value, dict)
            and bool(str(value.get("programId") or "").strip())
            and bool(str(value.get("data") or "").strip())
            and isinstance(value.get("accounts"), list)
        )

    def get_quote_and_unsigned_build(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_raw: int,
        taker: str,
        slippage_bps: int | None = None,
        mode: str = "fast",
    ) -> JupiterOrderResult:
        """Quote and validate unsigned /build instructions concurrently.

        The /order price observation and the /build executable-instruction
        request are independent for this read-only copyability shadow. Running
        them concurrently preserves both evidence streams and every existing
        fail-closed validation while removing their avoidable serial latency.
        This method never signs, submits, or calls Jupiter /execute.
        """
        if amount_raw <= 0:
            raise JupiterSwapError(
                "L'importo della quotazione deve essere positivo.",
                code="INVALID_ORDER_AMOUNT",
                status_code=422,
            )

        normalized_taker = str(taker or "").strip()
        if not normalized_taker:
            raise JupiterSwapError(
                "Il taker pubblico per /build è obbligatorio.",
                code="JUPITER_BUILD_TAKER_REQUIRED",
                status_code=422,
            )

        normalized_mode = str(mode or "fast").strip().lower()
        if normalized_mode != "fast":
            raise JupiterSwapError(
                "M58-M60 consente solo Jupiter /build mode=fast.",
                code="JUPITER_BUILD_MODE_INVALID",
                status_code=422,
            )

        common_params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_raw),
        }
        if slippage_bps is not None:
            common_params["slippageBps"] = str(slippage_bps)

        build_params = dict(common_params)
        build_params["taker"] = normalized_taker
        build_params["mode"] = normalized_mode

        # Both requests are required.  /order preserves the Meta-Aggregator
        # price observation and price-impact fallback; /build preserves the
        # exact executable unsigned-instruction evidence.  They do not depend
        # on each other's response, so serial execution only adds latency.
        order_timing: dict[str, Any] = {}
        build_timing: dict[str, Any] = {}
        parallel_started = time.perf_counter()
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="jupiter-shadow",
        ) as executor:
            order_future = executor.submit(
                self._request_json,
                "GET",
                "/order",
                params=dict(common_params),
                retryable=True,
                timing_sink=order_timing,
            )
            build_future = executor.submit(
                self._request_json,
                "GET",
                "/build",
                params=build_params,
                retryable=True,
                timing_sink=build_timing,
            )
            try:
                order_payload = order_future.result()
                build_payload = build_future.result()
            except BaseException:
                order_future.cancel()
                build_future.cancel()
                raise

        parallel_wall_ms = max(
            0.0,
            (time.perf_counter() - parallel_started) * 1000.0,
        )
        component_timing = {
            "version": "jupiter-component-timing/1",
            "parallel_wall_ms": round(parallel_wall_ms, 3),
            "order": dict(order_timing),
            "build": dict(build_timing),
            "observation_only": True,
            "pacing_changed": False,
            "retry_changed": False,
            "request_concurrency_changed": False,
        }

        request_id = str(order_payload.get("requestId") or "").strip()
        if not request_id:
            raise JupiterSwapError(
                "Risposta Jupiter /order priva di requestId.",
                code="JUPITER_INVALID_RESPONSE",
                status_code=502,
            )
        if order_payload.get("transaction") not in (None, ""):
            raise JupiterSwapError(
                "Jupiter /order senza taker ha restituito una transazione inattesa.",
                code="JUPITER_UNEXPECTED_TRANSACTION",
                status_code=502,
            )
        order_in_amount = int(
            self._parse_int(order_payload.get("inAmount"), "inAmount")
        )
        order_out_amount = int(
            self._parse_int(order_payload.get("outAmount"), "outAmount")
        )
        if order_in_amount <= 0 or order_out_amount <= 0:
            raise JupiterSwapError(
                "Jupiter /order ha restituito importi non positivi.",
                code="JUPITER_ORDER_AMOUNTS_INVALID",
                status_code=502,
            )

        forbidden_artifacts = (
            "signedTransaction",
            "signature",
            "transactionSignature",
            "txid",
        )
        if any(build_payload.get(key) not in (None, "") for key in forbidden_artifacts):
            raise JupiterSwapError(
                "Jupiter /build ha restituito un artefatto firmato inatteso.",
                code="JUPITER_SIGNED_ARTIFACT_FORBIDDEN",
                status_code=502,
            )
        if not self._valid_unsigned_build_instruction(
            build_payload.get("swapInstruction")
        ):
            raise JupiterSwapError(
                "Jupiter /build privo di swapInstruction valida.",
                code="JUPITER_BUILD_INSTRUCTION_MISSING",
                status_code=502,
            )

        blockhash_metadata = build_payload.get("blockhashWithMetadata")
        if not isinstance(blockhash_metadata, dict):
            raise JupiterSwapError(
                "Jupiter /build privo di blockhashWithMetadata.",
                code="JUPITER_BUILD_BLOCKHASH_MISSING",
                status_code=502,
            )
        last_valid_block_height = int(
            self._parse_int(
                blockhash_metadata.get("lastValidBlockHeight"),
                "lastValidBlockHeight",
            )
        )
        if last_valid_block_height <= 0:
            raise JupiterSwapError(
                "Jupiter /build con lastValidBlockHeight non positivo.",
                code="JUPITER_BUILD_BLOCKHASH_INVALID",
                status_code=502,
            )

        build_in_amount = int(
            self._parse_int(build_payload.get("inAmount"), "inAmount")
        )
        build_out_amount = int(
            self._parse_int(build_payload.get("outAmount"), "outAmount")
        )
        threshold = int(
            self._parse_int(
                build_payload.get("otherAmountThreshold"),
                "otherAmountThreshold",
            )
        )
        if build_in_amount <= 0 or build_out_amount <= 0 or threshold <= 0:
            raise JupiterSwapError(
                "Jupiter /build ha restituito importi non positivi.",
                code="JUPITER_BUILD_AMOUNTS_INVALID",
                status_code=502,
            )

        resolved_slippage = int(
            self._parse_int(
                build_payload.get("slippageBps", slippage_bps or 0),
                "slippageBps",
            )
        )
        build_vs_order_out_bps = (
            ((build_out_amount / order_out_amount) - 1.0) * 10_000.0
            if order_out_amount > 0
            else 0.0
        )
        price_impact = build_payload.get(
            "priceImpact",
            build_payload.get(
                "priceImpactPct",
                order_payload.get(
                    "priceImpact",
                    order_payload.get("priceImpactPct"),
                ),
            ),
        )
        router = (
            str(build_payload.get("router") or order_payload.get("router") or "metis")
            .strip()
            or "metis"
        )

        # Persist only evidence and counts, never raw instruction bytes.
        evidence = {
            "requestId": request_id,
            "inAmount": str(build_in_amount),
            "outAmount": str(build_out_amount),
            "otherAmountThreshold": str(threshold),
            "slippageBps": resolved_slippage,
            "router": router,
            "priceImpact": price_impact,
            "quoteOnlyOutAmount": str(order_out_amount),
            "buildVsOrderOutBps": round(build_vs_order_out_bps, 4),
            "unsignedBuild": True,
            "swapInstructionValid": True,
            "setupInstructionCount": len(build_payload.get("setupInstructions") or []),
            "computeBudgetInstructionCount": len(
                build_payload.get("computeBudgetInstructions") or []
            ),
            "otherInstructionCount": len(build_payload.get("otherInstructions") or []),
            "lookupTableCount": len(
                build_payload.get("addressesByLookupTableAddress") or {}
            ),
            "endpointSequence": ["order", "build"],
            "orderHadTaker": False,
            "buildHadTaker": True,
            "executeEndpointCalled": False,
            "signedTransactionCreated": False,
            "signatureCreated": False,
            "componentTiming": component_timing,
        }

        return JupiterOrderResult(
            raw=evidence,
            request_id=request_id,
            transaction="UNSIGNED_INSTRUCTIONS_BUILT_NO_SIGNATURE",
            in_amount=build_in_amount,
            out_amount=build_out_amount,
            slippage_bps=resolved_slippage,
            router=router,
            price_impact_percent=self._parse_float(price_impact, 0.0),
            last_valid_block_height=str(last_valid_block_height),
            request_timing=component_timing,
        )


    def get_build_priority_unsigned(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_raw: int,
        taker: str,
        slippage_bps: int | None = None,
        mode: str = "fast",
    ) -> JupiterOrderResult:
        """Build-priority candidate quote with explicit order-diagnostic omission.

        This path is intended only for candidate-entry shadow validation. It
        performs the existing Jupiter /build request, preserves every unsigned
        build safety validation, never signs/submits/executes, and returns the
        executable quote fields directly from /build. The historical /order
        comparison is intentionally not collected on the critical path and is
        marked explicitly in evidence rather than silently dropped.
        """
        if amount_raw <= 0:
            raise JupiterSwapError(
                "L'importo della quotazione deve essere positivo.",
                code="INVALID_ORDER_AMOUNT",
                status_code=422,
            )

        normalized_taker = str(taker or "").strip()
        if not normalized_taker:
            raise JupiterSwapError(
                "Il taker pubblico per /build è obbligatorio.",
                code="JUPITER_BUILD_TAKER_REQUIRED",
                status_code=422,
            )

        normalized_mode = str(mode or "fast").strip().lower()
        if normalized_mode != "fast":
            raise JupiterSwapError(
                "M58-M60 consente solo Jupiter /build mode=fast.",
                code="JUPITER_BUILD_MODE_INVALID",
                status_code=422,
            )

        build_params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_raw),
            "taker": normalized_taker,
            "mode": normalized_mode,
        }
        if slippage_bps is not None:
            build_params["slippageBps"] = str(slippage_bps)

        build_timing: dict[str, Any] = {}
        build_started = time.perf_counter()
        build_payload = self._request_json(
            "GET",
            "/build",
            params=build_params,
            retryable=True,
            timing_sink=build_timing,
            request_priority="critical",
        )
        build_wall_ms = max(
            0.0,
            (time.perf_counter() - build_started) * 1000.0,
        )
        component_timing = {
            "version": "jupiter-component-timing/1",
            "parallel_wall_ms": round(build_wall_ms, 3),
            "order": None,
            "build": dict(build_timing),
            "observation_only": True,
            "pacing_changed": False,
            "retry_changed": False,
            "request_concurrency_changed": True,
            "build_priority": True,
            "order_diagnostic_available": False,
            "order_diagnostic_mode": "NOT_CALLED_ON_CANDIDATE_CRITICAL_PATH",
        }

        request_id = str(build_payload.get("requestId") or "").strip()
        if not request_id:
            raise JupiterSwapError(
                "Risposta Jupiter /build priva di requestId.",
                code="JUPITER_BUILD_REQUEST_ID_MISSING",
                status_code=502,
            )

        forbidden_artifacts = (
            "signedTransaction",
            "signature",
            "transactionSignature",
            "txid",
        )
        if any(build_payload.get(key) not in (None, "") for key in forbidden_artifacts):
            raise JupiterSwapError(
                "Jupiter /build ha restituito un artefatto firmato inatteso.",
                code="JUPITER_SIGNED_ARTIFACT_FORBIDDEN",
                status_code=502,
            )

        if not self._valid_unsigned_build_instruction(
            build_payload.get("swapInstruction")
        ):
            raise JupiterSwapError(
                "Jupiter /build privo di swapInstruction valida.",
                code="JUPITER_BUILD_INSTRUCTION_MISSING",
                status_code=502,
            )

        blockhash_metadata = build_payload.get("blockhashWithMetadata")
        if not isinstance(blockhash_metadata, dict):
            raise JupiterSwapError(
                "Jupiter /build privo di blockhashWithMetadata.",
                code="JUPITER_BUILD_BLOCKHASH_MISSING",
                status_code=502,
            )
        last_valid_block_height = int(
            self._parse_int(
                blockhash_metadata.get("lastValidBlockHeight"),
                "lastValidBlockHeight",
            )
        )
        if last_valid_block_height <= 0:
            raise JupiterSwapError(
                "Jupiter /build con lastValidBlockHeight non positivo.",
                code="JUPITER_BUILD_BLOCKHASH_INVALID",
                status_code=502,
            )

        build_in_amount = int(
            self._parse_int(build_payload.get("inAmount"), "inAmount")
        )
        build_out_amount = int(
            self._parse_int(build_payload.get("outAmount"), "outAmount")
        )
        threshold = int(
            self._parse_int(
                build_payload.get("otherAmountThreshold"),
                "otherAmountThreshold",
            )
        )
        if build_in_amount <= 0 or build_out_amount <= 0 or threshold <= 0:
            raise JupiterSwapError(
                "Jupiter /build ha restituito importi non positivi.",
                code="JUPITER_BUILD_AMOUNTS_INVALID",
                status_code=502,
            )

        resolved_slippage = int(
            self._parse_int(
                build_payload.get("slippageBps", slippage_bps or 0),
                "slippageBps",
            )
        )

        price_impact = build_payload.get(
            "priceImpact",
            build_payload.get("priceImpactPct"),
        )
        if price_impact in (None, ""):
            raise JupiterSwapError(
                "Jupiter /build privo di priceImpact.",
                code="JUPITER_BUILD_PRICE_IMPACT_MISSING",
                status_code=502,
            )

        router = str(build_payload.get("router") or "metis").strip() or "metis"

        evidence = {
            "requestId": request_id,
            "inAmount": str(build_in_amount),
            "outAmount": str(build_out_amount),
            "otherAmountThreshold": str(threshold),
            "slippageBps": resolved_slippage,
            "router": router,
            "priceImpact": price_impact,
            "quoteOnlyOutAmount": None,
            "buildVsOrderOutBps": None,
            "unsignedBuild": True,
            "swapInstructionValid": True,
            "setupInstructionCount": len(build_payload.get("setupInstructions") or []),
            "computeBudgetInstructionCount": len(
                build_payload.get("computeBudgetInstructions") or []
            ),
            "otherInstructionCount": len(build_payload.get("otherInstructions") or []),
            "lookupTableCount": len(
                build_payload.get("addressesByLookupTableAddress") or {}
            ),
            "endpointSequence": ["build"],
            "orderHadTaker": None,
            "buildHadTaker": True,
            "orderDiagnosticAvailable": False,
            "orderDiagnosticMode": "NOT_CALLED_ON_CANDIDATE_CRITICAL_PATH",
            "buildPriorityCriticalPath": True,
            "executeEndpointCalled": False,
            "signedTransactionCreated": False,
            "signatureCreated": False,
            "componentTiming": component_timing,
        }

        return JupiterOrderResult(
            raw=evidence,
            request_id=request_id,
            transaction="UNSIGNED_INSTRUCTIONS_BUILT_NO_SIGNATURE",
            in_amount=build_in_amount,
            out_amount=build_out_amount,
            slippage_bps=resolved_slippage,
            router=router,
            price_impact_percent=self._parse_float(price_impact, 0.0),
            last_valid_block_height=str(last_valid_block_height),
            request_timing=component_timing,
        )

    def get_order_diagnostic(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_raw: int,
        slippage_bps: int | None = None,
    ) -> dict[str, Any]:
        """Low-priority post-commit /order diagnostic; never part of entry gating."""
        if amount_raw <= 0:
            raise JupiterSwapError(
                "L'importo diagnostico deve essere positivo.",
                code="INVALID_ORDER_AMOUNT",
                status_code=422,
            )

        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_raw),
        }
        if slippage_bps is not None:
            params["slippageBps"] = str(slippage_bps)

        timing: dict[str, Any] = {}
        payload = self._request_json(
            "GET",
            "/order",
            params=params,
            retryable=True,
            timing_sink=timing,
            request_priority="diagnostic",
        )

        request_id = str(payload.get("requestId") or "").strip()
        if not request_id:
            raise JupiterSwapError(
                "Risposta Jupiter /order diagnostica priva di requestId.",
                code="JUPITER_DIAGNOSTIC_ORDER_REQUEST_ID_MISSING",
                status_code=502,
            )
        if payload.get("transaction") not in (None, ""):
            raise JupiterSwapError(
                "Jupiter /order diagnostico ha restituito una transazione inattesa.",
                code="JUPITER_UNEXPECTED_TRANSACTION",
                status_code=502,
            )

        in_amount = int(
            self._parse_int(payload.get("inAmount"), "inAmount")
        )
        out_amount = int(
            self._parse_int(payload.get("outAmount"), "outAmount")
        )
        if in_amount <= 0 or out_amount <= 0:
            raise JupiterSwapError(
                "Jupiter /order diagnostico ha restituito importi non positivi.",
                code="JUPITER_DIAGNOSTIC_ORDER_AMOUNTS_INVALID",
                status_code=502,
            )

        price_impact = payload.get(
            "priceImpact",
            payload.get("priceImpactPct"),
        )
        router = str(payload.get("router") or "").strip() or None

        return {
            "version": "candidate-deferred-order-diagnostic/1",
            "requestId": request_id,
            "inAmount": str(in_amount),
            "outAmount": str(out_amount),
            "router": router,
            "priceImpact": price_impact,
            "componentTiming": dict(timing),
            "criticalPath": False,
            "requestPriority": "diagnostic",
            "executeEndpointCalled": False,
            "signedTransactionCreated": False,
            "signatureCreated": False,
        }

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
