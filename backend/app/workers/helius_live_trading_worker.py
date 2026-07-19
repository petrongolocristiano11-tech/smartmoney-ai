import asyncio
import hashlib
import json
import logging
import os
import random
import signal
import socket
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
from uuid import uuid4

from websockets.asyncio.client import (
    ClientConnection,
    connect,
)

from backend.app.core.config import (
    settings,
)
from backend.app.core.logging_config import (
    configure_logging,
)
from backend.app.database.session import (
    SessionLocal,
    engine,
)
from backend.app.models.live_trading_policy import (
    LiveTradingPolicy,
)
from backend.app.services.live_trading_policy_service import (
    get_or_create_live_policy,
)
from backend.app.services.live_trading_stream_processor import (
    LiveStreamProcessResult,
    process_live_signature,
)
from backend.app.services.live_trading_worker_state import (
    acquire_worker_lease,
    heartbeat_worker,
    release_worker_lease,
    utc_now,
)


configure_logging()

logger = logging.getLogger(
    "smartmoney.live_worker"
)


SUBSCRIPTION_REQUEST_START = 1000


class WorkerLeaseLost(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class PolicySnapshot:
    mode: str
    enabled: bool
    blocked_reason: str | None
    wallets: tuple[str, ...]
    fingerprint: str


@dataclass
class RuntimeMetrics:
    reconnect_count: int = 0
    signatures_received: int = 0
    signatures_processed: int = 0
    signatures_failed: int = 0
    signatures_dropped: int = 0
    last_signature: str | None = None
    last_message_at: datetime | None = None
    last_trade_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


def build_worker_id() -> str:
    railway_replica = str(
        os.getenv(
            "RAILWAY_REPLICA_ID",
            "",
        )
    ).strip()

    identity = (
        railway_replica
        or (
            f"{socket.gethostname()}:"
            f"{os.getpid()}"
        )
    )

    return (
        f"{identity}:"
        f"{uuid4().hex[:12]}"
    )


def get_helius_websocket_url() -> str:
    return (
        "wss://mainnet.helius-rpc.com/"
        f"?api-key={settings.HELIUS_API_KEY}"
    )


def normalize_wallets(
    wallets,
) -> tuple[str, ...]:
    normalized = {
        str(wallet).strip()
        for wallet in (
            wallets or []
        )
        if str(wallet).strip()
    }

    return tuple(
        sorted(normalized)
    )


def build_policy_fingerprint(
    *,
    mode: str,
    stream_enabled: bool,
    kill_switch: bool,
    wallets: tuple[str, ...],
    updated_at,
) -> str:
    material = json.dumps(
        {
            "mode": mode,
            "stream_enabled":
                stream_enabled,
            "kill_switch":
                kill_switch,
            "wallets":
                wallets,
            "updated_at":
                str(
                    updated_at or ""
                ),
        },
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    return hashlib.sha256(
        material.encode(
            "utf-8"
        )
    ).hexdigest()


def build_logs_subscription_request(
    request_id: int,
    wallet_address: str,
) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "logsSubscribe",
        "params": [
            {
                "mentions": [
                    wallet_address
                ],
            },
            {
                "commitment":
                    "confirmed",
            },
        ],
    }


def parse_logs_notification(
    message: dict,
    subscription_wallets: dict[
        int,
        str,
    ],
) -> tuple[
    str,
    str,
] | None:
    if (
        message.get("method")
        != "logsNotification"
    ):
        return None

    params = message.get(
        "params"
    )

    if not isinstance(
        params,
        dict,
    ):
        return None

    subscription_id = params.get(
        "subscription"
    )

    try:
        subscription_id = int(
            subscription_id
        )

    except (
        TypeError,
        ValueError,
    ):
        return None

    wallet = subscription_wallets.get(
        subscription_id
    )

    if not wallet:
        return None

    value = (
        params.get("result", {})
        .get("value", {})
    )

    if not isinstance(
        value,
        dict,
    ):
        return None

    if value.get("err") is not None:
        return None

    signature = str(
        value.get("signature")
        or ""
    ).strip()

    if not signature:
        return None

    return signature, wallet


def load_policy_snapshot() -> PolicySnapshot:
    db = SessionLocal()

    try:
        policy = get_or_create_live_policy(
            db
        )

        wallets = normalize_wallets(
            policy.source_wallets
        )

        mode = str(
            policy.mode
            or "DISABLED"
        ).upper()

        blocked_reason: (
            str | None
        ) = None

        enabled = bool(
            mode in {
                "DRY_RUN",
                "LIVE",
            }
            and (
                policy
                .stream_execution_enabled
            )
            and not policy.kill_switch
            and wallets
        )

        if mode == "DISABLED":
            blocked_reason = (
                "LIVE_TRADING_DISABLED"
            )

        elif policy.kill_switch:
            blocked_reason = (
                "KILL_SWITCH_ACTIVE"
            )

        elif not (
            policy
            .stream_execution_enabled
        ):
            blocked_reason = (
                "STREAM_EXECUTION_DISABLED"
            )

        elif not wallets:
            blocked_reason = (
                "SOURCE_WALLETS_EMPTY"
            )

        elif not settings.JUPITER_API_KEY:
            enabled = False
            blocked_reason = (
                "JUPITER_NOT_CONFIGURED"
            )

        elif (
            mode == "LIVE"
            and not settings
            .is_live_trading_configured
        ):
            enabled = False
            blocked_reason = (
                "LIVE_EXECUTION_NOT_CONFIGURED"
            )

        fingerprint = (
            build_policy_fingerprint(
                mode=mode,
                stream_enabled=(
                    policy
                    .stream_execution_enabled
                ),
                kill_switch=(
                    policy.kill_switch
                ),
                wallets=wallets,
                updated_at=(
                    policy.updated_at
                ),
            )
        )

        return PolicySnapshot(
            mode=mode,
            enabled=enabled,
            blocked_reason=(
                blocked_reason
            ),
            wallets=wallets,
            fingerprint=fingerprint,
        )

    finally:
        db.close()


class HeliusLiveTradingWorker:
    def __init__(
        self,
        *,
        worker_id: str | None = None,
    ):
        self.worker_id = (
            worker_id
            or build_worker_id()
        )

        self.stop_event = (
            asyncio.Event()
        )

        self.metrics = (
            RuntimeMetrics()
        )

        self.current_status = (
            "STARTING"
        )

        self.current_snapshot = (
            PolicySnapshot(
                mode="DISABLED",
                enabled=False,
                blocked_reason=(
                    "WORKER_STARTING"
                ),
                wallets=(),
                fingerprint="",
            )
        )

        self.active_subscriptions = 0
        self.queue_depth = 0
        self.connection_latency_ms: (
            float | None
        ) = None

        self.connected_at: (
            datetime | None
        ) = None

        self.recent_signatures: set[
            str
        ] = set()

        self.recent_signature_order: (
            deque[str]
        ) = deque()

    async def wait_or_stop(
        self,
        seconds: float,
    ) -> bool:
        try:
            await asyncio.wait_for(
                self.stop_event.wait(),
                timeout=seconds,
            )

            return True

        except TimeoutError:
            return False

    def request_stop(
        self,
    ) -> None:
        if not self.stop_event.is_set():
            logger.info(
                "worker_stop_requested "
                "worker_id=%s",
                self.worker_id,
            )

            self.stop_event.set()

    def acquire_lease_sync(
        self,
    ) -> bool:
        db = SessionLocal()

        try:
            return acquire_worker_lease(
                db,
                worker_id=self.worker_id,
                lease_seconds=(
                    settings
                    .LIVE_STREAM_LEASE_SECONDS
                ),
            )

        finally:
            db.close()

    def publish_state_sync(
        self,
    ) -> bool:
        db = SessionLocal()

        try:
            return heartbeat_worker(
                db,
                worker_id=self.worker_id,
                lease_seconds=(
                    settings
                    .LIVE_STREAM_LEASE_SECONDS
                ),
                updates={
                    "status":
                        self.current_status,
                    "active_wallets":
                        list(
                            self
                            .current_snapshot
                            .wallets
                        ),
                    "monitored_wallets":
                        len(
                            self
                            .current_snapshot
                            .wallets
                        ),
                    "active_subscriptions":
                        self
                        .active_subscriptions,
                    "queue_depth":
                        self.queue_depth,
                    "reconnect_count":
                        self.metrics
                        .reconnect_count,
                    "signatures_received":
                        self.metrics
                        .signatures_received,
                    "signatures_processed":
                        self.metrics
                        .signatures_processed,
                    "signatures_failed":
                        self.metrics
                        .signatures_failed,
                    "signatures_dropped":
                        self.metrics
                        .signatures_dropped,
                    "last_latency_ms":
                        self
                        .connection_latency_ms,
                    "config_fingerprint":
                        self
                        .current_snapshot
                        .fingerprint,
                    "last_signature":
                        self.metrics
                        .last_signature,
                    "last_message_at":
                        self.metrics
                        .last_message_at,
                    "last_trade_at":
                        self.metrics
                        .last_trade_at,
                    "last_error_at":
                        self.metrics
                        .last_error_at,
                    "last_error_code":
                        self.metrics
                        .last_error_code,
                    "last_error_message":
                        self.metrics
                        .last_error_message,
                    "connected_at":
                        self.connected_at,
                },
            )

        finally:
            db.close()

    async def publish_state(
        self,
    ) -> None:
        renewed = await asyncio.to_thread(
            self.publish_state_sync
        )

        if not renewed:
            raise WorkerLeaseLost(
                "Lease del worker persa."
            )

    def release_lease_sync(
        self,
    ) -> bool:
        db = SessionLocal()

        try:
            return release_worker_lease(
                db,
                worker_id=self.worker_id,
            )

        finally:
            db.close()

    async def heartbeat_loop(
        self,
    ) -> None:
        while not self.stop_event.is_set():
            stopped = await self.wait_or_stop(
                settings
                .LIVE_STREAM_HEARTBEAT_SECONDS
            )

            if stopped:
                return

            await self.publish_state()

    def remember_signature(
        self,
        signature: str,
    ) -> bool:
        if (
            signature
            in self.recent_signatures
        ):
            return False

        self.recent_signatures.add(
            signature
        )

        self.recent_signature_order.append(
            signature
        )

        maximum = (
            settings
            .LIVE_STREAM_RECENT_SIGNATURES
        )

        while (
            len(
                self
                .recent_signature_order
            )
            > maximum
        ):
            old_signature = (
                self
                .recent_signature_order
                .popleft()
            )

            self.recent_signatures.discard(
                old_signature
            )

        return True

    async def subscribe_wallets(
        self,
        websocket: ClientConnection,
        wallets: tuple[str, ...],
    ) -> tuple[
        dict[int, str],
        list[dict],
    ]:
        subscription_wallets: dict[
            int,
            str,
        ] = {}

        early_messages: list[
            dict
        ] = []

        for index, wallet in enumerate(
            wallets
        ):
            request_id = (
                SUBSCRIPTION_REQUEST_START
                + index
            )

            await websocket.send(
                json.dumps(
                    build_logs_subscription_request(
                        request_id,
                        wallet,
                    )
                )
            )

            while True:
                raw_message = (
                    await asyncio.wait_for(
                        websocket.recv(),
                        timeout=(
                            settings
                            .LIVE_STREAM_SUBSCRIPTION_TIMEOUT_SECONDS
                        ),
                    )
                )

                try:
                    message = json.loads(
                        raw_message
                    )

                except (
                    TypeError,
                    json.JSONDecodeError,
                ):
                    continue

                if (
                    message.get("id")
                    == request_id
                ):
                    if message.get(
                        "error"
                    ):
                        raise RuntimeError(
                            "Helius ha rifiutato "
                            f"la sottoscrizione di "
                            f"{wallet}: "
                            f"{message['error']}"
                        )

                    try:
                        subscription_id = int(
                            message["result"]
                        )

                    except (
                        KeyError,
                        TypeError,
                        ValueError,
                    ) as exception:
                        raise RuntimeError(
                            "Risposta di "
                            "sottoscrizione Helius "
                            "non valida."
                        ) from exception

                    subscription_wallets[
                        subscription_id
                    ] = wallet

                    logger.info(
                        "wallet_subscribed "
                        "wallet=%s "
                        "subscription_id=%s",
                        wallet,
                        subscription_id,
                    )

                    break

                early_messages.append(
                    message
                )

        return (
            subscription_wallets,
            early_messages,
        )

    def handle_message(
        self,
        message: dict,
        *,
        subscription_wallets: dict[
            int,
            str,
        ],
        queue: asyncio.Queue,
    ) -> None:
        self.metrics.last_message_at = (
            utc_now()
        )

        parsed = parse_logs_notification(
            message,
            subscription_wallets,
        )

        if parsed is None:
            return

        signature, wallet = parsed

        self.metrics.signatures_received += 1
        self.metrics.last_signature = (
            signature
        )

        if not self.remember_signature(
            signature
        ):
            return

        try:
            queue.put_nowait(
                (
                    signature,
                    wallet,
                )
            )

            self.queue_depth = (
                queue.qsize()
            )

        except asyncio.QueueFull:
            self.metrics.signatures_dropped += 1

            self.metrics.last_error_at = (
                utc_now()
            )

            self.metrics.last_error_code = (
                "STREAM_QUEUE_FULL"
            )

            self.metrics.last_error_message = (
                "La coda del worker è piena; "
                "una firma è stata scartata."
            )

            logger.error(
                "stream_queue_full "
                "signature=%s wallet=%s",
                signature,
                wallet,
            )

    async def reader_loop(
        self,
        websocket: ClientConnection,
        *,
        subscription_wallets: dict[
            int,
            str,
        ],
        early_messages: list[dict],
        queue: asyncio.Queue,
    ) -> None:
        for message in early_messages:
            self.handle_message(
                message,
                subscription_wallets=(
                    subscription_wallets
                ),
                queue=queue,
            )

        async for raw_message in websocket:
            try:
                message = json.loads(
                    raw_message
                )

            except (
                TypeError,
                json.JSONDecodeError,
            ):
                continue

            self.handle_message(
                message,
                subscription_wallets=(
                    subscription_wallets
                ),
                queue=queue,
            )

        raise ConnectionError(
            "Connessione Helius chiusa."
        )

    async def consumer_loop(
        self,
        consumer_id: int,
        queue: asyncio.Queue,
    ) -> None:
        while True:
            signature, wallet = (
                await queue.get()
            )

            self.queue_depth = (
                queue.qsize()
            )

            try:
                result: (
                    LiveStreamProcessResult
                ) = await asyncio.to_thread(
                    process_live_signature,
                    signature,
                    wallet,
                )

                self.metrics.last_signature = (
                    signature
                )

                if (
                    result.outcome
                    == "ORDER"
                ):
                    self.metrics.last_trade_at = (
                        utc_now()
                    )

                    if (
                        result.order_status
                        == "FAILED"
                    ):
                        self.metrics.signatures_failed += 1

                    else:
                        self.metrics.signatures_processed += 1

                    logger.info(
                        "stream_order_processed "
                        "consumer=%s "
                        "signature=%s "
                        "wallet=%s "
                        "trade_id=%s "
                        "order_id=%s "
                        "mode=%s "
                        "status=%s",
                        consumer_id,
                        signature,
                        wallet,
                        result.trade_id,
                        result.order_id,
                        result.order_mode,
                        result.order_status,
                    )

                else:
                    self.metrics.signatures_processed += 1

                    logger.info(
                        "stream_signature_skipped "
                        "consumer=%s "
                        "signature=%s "
                        "wallet=%s "
                        "reason=%s",
                        consumer_id,
                        signature,
                        wallet,
                        result.message,
                    )

            except Exception as exception:
                self.metrics.signatures_failed += 1

                self.metrics.last_error_at = (
                    utc_now()
                )

                self.metrics.last_error_code = (
                    "SIGNATURE_PROCESSING_FAILED"
                )

                self.metrics.last_error_message = (
                    f"{type(exception).__name__}: "
                    f"{exception}"
                )[:2000]

                logger.exception(
                    "signature_processing_failed "
                    "consumer=%s "
                    "signature=%s "
                    "wallet=%s",
                    consumer_id,
                    signature,
                    wallet,
                )

            finally:
                queue.task_done()

                self.queue_depth = (
                    queue.qsize()
                )

    async def policy_watch_loop(
        self,
        expected_fingerprint: str,
    ) -> str:
        while not self.stop_event.is_set():
            stopped = await self.wait_or_stop(
                settings
                .LIVE_STREAM_POLICY_REFRESH_SECONDS
            )

            if stopped:
                return "STOP_REQUESTED"

            snapshot = (
                await asyncio.to_thread(
                    load_policy_snapshot
                )
            )

            if (
                snapshot.fingerprint
                != expected_fingerprint
            ):
                return "POLICY_CHANGED"

        return "STOP_REQUESTED"

    async def drain_queue(
        self,
        queue: asyncio.Queue,
    ) -> None:
        try:
            await asyncio.wait_for(
                queue.join(),
                timeout=10,
            )

        except TimeoutError:
            logger.warning(
                "queue_drain_timeout "
                "remaining=%s",
                queue.qsize(),
            )

    async def run_connection(
        self,
        snapshot: PolicySnapshot,
    ) -> str:
        self.current_snapshot = snapshot
        self.current_status = (
            "CONNECTING"
        )

        self.active_subscriptions = 0
        self.connection_latency_ms = None
        self.connected_at = None

        await self.publish_state()

        heartbeat_task = (
            asyncio.create_task(
                self.heartbeat_loop(),
                name="live-worker-heartbeat",
            )
        )

        queue: asyncio.Queue = (
            asyncio.Queue(
                maxsize=(
                    settings
                    .LIVE_STREAM_QUEUE_SIZE
                )
            )
        )

        consumer_tasks: list[
            asyncio.Task
        ] = []

        connection_tasks: list[
            asyncio.Task
        ] = []

        try:
            async with connect(
                get_helius_websocket_url(),
                open_timeout=(
                    settings
                    .LIVE_STREAM_OPEN_TIMEOUT_SECONDS
                ),
                ping_interval=(
                    settings
                    .LIVE_STREAM_PING_INTERVAL_SECONDS
                ),
                ping_timeout=(
                    settings
                    .LIVE_STREAM_PING_TIMEOUT_SECONDS
                ),
                close_timeout=10,
                max_size=None,
                max_queue=64,
                compression=None,
            ) as websocket:
                (
                    subscription_wallets,
                    early_messages,
                ) = await self.subscribe_wallets(
                    websocket,
                    snapshot.wallets,
                )

                self.active_subscriptions = (
                    len(
                        subscription_wallets
                    )
                )

                self.connected_at = (
                    utc_now()
                )

                self.current_status = (
                    "RUNNING"
                )

                self.metrics.last_error_code = None
                self.metrics.last_error_message = None

                await self.publish_state()

                consumer_tasks = [
                    asyncio.create_task(
                        self.consumer_loop(
                            consumer_id,
                            queue,
                        ),
                        name=(
                            "live-worker-consumer-"
                            f"{consumer_id}"
                        ),
                    )
                    for consumer_id
                    in range(
                        1,
                        (
                            settings
                            .LIVE_STREAM_CONSUMERS
                            + 1
                        ),
                    )
                ]

                reader_task = (
                    asyncio.create_task(
                        self.reader_loop(
                            websocket,
                            subscription_wallets=(
                                subscription_wallets
                            ),
                            early_messages=(
                                early_messages
                            ),
                            queue=queue,
                        ),
                        name=(
                            "live-worker-reader"
                        ),
                    )
                )

                policy_task = (
                    asyncio.create_task(
                        self.policy_watch_loop(
                            snapshot
                            .fingerprint
                        ),
                        name=(
                            "live-worker-policy-watch"
                        ),
                    )
                )

                connection_tasks = [
                    reader_task,
                    policy_task,
                    heartbeat_task,
                ]

                done, _ = (
                    await asyncio.wait(
                        connection_tasks,
                        return_when=(
                            asyncio
                            .FIRST_COMPLETED
                        ),
                    )
                )

                if self.stop_event.is_set():
                    return "STOP_REQUESTED"

                for task in done:
                    if task is policy_task:
                        return task.result()

                    task.result()

                return "CONNECTION_ENDED"

        finally:
            self.active_subscriptions = 0
            self.connection_latency_ms = None

            await self.drain_queue(
                queue
            )

            for task in (
                connection_tasks
                + consumer_tasks
                + [heartbeat_task]
            ):
                if not task.done():
                    task.cancel()

            for task in (
                connection_tasks
                + consumer_tasks
                + [heartbeat_task]
            ):
                with suppress(
                    asyncio.CancelledError,
                    Exception,
                ):
                    await task

    async def run(
        self,
    ) -> None:
        logger.info(
            "live_worker_starting "
            "worker_id=%s",
            self.worker_id,
        )

        reconnect_delay = (
            settings
            .LIVE_STREAM_RECONNECT_MIN_SECONDS
        )

        try:
            while not self.stop_event.is_set():
                acquired = (
                    await asyncio.to_thread(
                        self.acquire_lease_sync
                    )
                )

                if not acquired:
                    logger.info(
                        "live_worker_standby "
                        "worker_id=%s",
                        self.worker_id,
                    )

                    await self.wait_or_stop(
                        settings
                        .LIVE_STREAM_POLICY_REFRESH_SECONDS
                    )

                    continue

                snapshot = (
                    await asyncio.to_thread(
                        load_policy_snapshot
                    )
                )

                self.current_snapshot = (
                    snapshot
                )

                if not snapshot.enabled:
                    normal_idle_reasons = {
                        "LIVE_TRADING_DISABLED",
                        "STREAM_EXECUTION_DISABLED",
                        "SOURCE_WALLETS_EMPTY",
                        "KILL_SWITCH_ACTIVE",
                    }

                    self.current_status = (
                        "IDLE"
                        if (
                            snapshot
                            .blocked_reason
                            in normal_idle_reasons
                        )
                        else "DEGRADED"
                    )

                    self.active_subscriptions = 0
                    self.connection_latency_ms = None

                    if (
                        snapshot.blocked_reason
                        in {
                            "JUPITER_NOT_CONFIGURED",
                            "LIVE_EXECUTION_NOT_CONFIGURED",
                        }
                    ):
                        self.metrics.last_error_at = (
                            utc_now()
                        )

                        self.metrics.last_error_code = (
                            snapshot
                            .blocked_reason
                        )

                        self.metrics.last_error_message = (
                            "Il worker è bloccato "
                            "da una configurazione "
                            "incompleta."
                        )

                    else:
                        self.metrics.last_error_code = None
                        self.metrics.last_error_message = None

                    await self.publish_state()

                    await self.wait_or_stop(
                        settings
                        .LIVE_STREAM_POLICY_REFRESH_SECONDS
                    )

                    reconnect_delay = (
                        settings
                        .LIVE_STREAM_RECONNECT_MIN_SECONDS
                    )

                    continue

                try:
                    reason = (
                        await self.run_connection(
                            snapshot
                        )
                    )

                    logger.info(
                        "live_stream_cycle_ended "
                        "reason=%s",
                        reason,
                    )

                    reconnect_delay = (
                        settings
                        .LIVE_STREAM_RECONNECT_MIN_SECONDS
                    )

                except WorkerLeaseLost:
                    logger.warning(
                        "worker_lease_lost "
                        "worker_id=%s",
                        self.worker_id,
                    )

                    await self.wait_or_stop(
                        settings
                        .LIVE_STREAM_POLICY_REFRESH_SECONDS
                    )

                except Exception as exception:
                    self.metrics.reconnect_count += 1

                    self.metrics.last_error_at = (
                        utc_now()
                    )

                    self.metrics.last_error_code = (
                        "HELIUS_CONNECTION_ERROR"
                    )

                    self.metrics.last_error_message = (
                        f"{type(exception).__name__}: "
                        f"{exception}"
                    )[:2000]

                    self.current_status = (
                        "DEGRADED"
                    )

                    self.active_subscriptions = 0
                    self.connection_latency_ms = None

                    with suppress(
                        WorkerLeaseLost
                    ):
                        await self.publish_state()

                    logger.exception(
                        "helius_connection_failed "
                        "retry_seconds=%.2f",
                        reconnect_delay,
                    )

                    jitter = random.uniform(
                        0,
                        min(
                            2.0,
                            reconnect_delay
                            * 0.25,
                        ),
                    )

                    await self.wait_or_stop(
                        reconnect_delay
                        + jitter
                    )

                    reconnect_delay = min(
                        settings
                        .LIVE_STREAM_RECONNECT_MAX_SECONDS,
                        reconnect_delay * 2,
                    )

        finally:
            self.current_status = (
                "STOPPED"
            )

            with suppress(
                Exception
            ):
                await asyncio.to_thread(
                    self.release_lease_sync
                )

            engine.dispose()

            logger.info(
                "live_worker_stopped "
                "worker_id=%s",
                self.worker_id,
            )


def install_signal_handlers(
    worker: HeliusLiveTradingWorker,
) -> None:
    loop = (
        asyncio.get_running_loop()
    )

    for signal_name in (
        signal.SIGINT,
        signal.SIGTERM,
    ):
        try:
            loop.add_signal_handler(
                signal_name,
                worker.request_stop,
            )

        except (
            NotImplementedError,
            RuntimeError,
        ):
            pass


async def async_main() -> None:
    worker = (
        HeliusLiveTradingWorker()
    )

    install_signal_handlers(
        worker
    )

    await worker.run()


def main() -> None:
    asyncio.run(
        async_main()
    )


if __name__ == "__main__":
    main() 