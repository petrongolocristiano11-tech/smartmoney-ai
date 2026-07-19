import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol

from backend.app.core.config import settings
from backend.app.workers.helius_live_trading_worker import (
    HeliusLiveTradingWorker,
)


logger = logging.getLogger(
    "smartmoney.embedded_live_worker"
)


class LiveTradingWorkerProtocol(
    Protocol
):
    async def run(
        self,
    ) -> None:
        ...

    def request_stop(
        self,
    ) -> None:
        ...


WorkerFactory = Callable[
    [],
    LiveTradingWorkerProtocol,
]


class EmbeddedLiveTradingWorkerRuntime:
    """
    Gestisce il worker Helius all'interno
    del processo FastAPI.

    Il supervisor:
    - avvia il worker senza bloccare FastAPI;
    - lo riavvia se termina inaspettatamente;
    - inoltra lo shutdown dell'app;
    - forza la cancellazione se lo shutdown
      supera il timeout configurato.
    """

    def __init__(
        self,
        *,
        worker_factory: (
            WorkerFactory | None
        ) = None,
        enabled: bool | None = None,
        restart_seconds: (
            float | None
        ) = None,
        shutdown_timeout_seconds: (
            float | None
        ) = None,
    ):
        self._worker_factory = (
            worker_factory
            or HeliusLiveTradingWorker
        )

        self._enabled_override = enabled

        self._restart_seconds_override = (
            restart_seconds
        )

        self._shutdown_timeout_override = (
            shutdown_timeout_seconds
        )

        self._supervisor_task: (
            asyncio.Task | None
        ) = None

        self._stop_event: (
            asyncio.Event | None
        ) = None

        self._current_worker: (
            LiveTradingWorkerProtocol
            | None
        ) = None

    @property
    def enabled(
        self,
    ) -> bool:
        if (
            self._enabled_override
            is not None
        ):
            return self._enabled_override

        return (
            settings
            .RUN_LIVE_STREAM_WORKER
        )

    @property
    def restart_seconds(
        self,
    ) -> float:
        if (
            self
            ._restart_seconds_override
            is not None
        ):
            return (
                self
                ._restart_seconds_override
            )

        return (
            settings
            .LIVE_STREAM_EMBEDDED_RESTART_SECONDS
        )

    @property
    def shutdown_timeout_seconds(
        self,
    ) -> float:
        if (
            self
            ._shutdown_timeout_override
            is not None
        ):
            return (
                self
                ._shutdown_timeout_override
            )

        return (
            settings
            .LIVE_STREAM_SHUTDOWN_TIMEOUT_SECONDS
        )

    @property
    def running(
        self,
    ) -> bool:
        task = self._supervisor_task

        return bool(
            task is not None
            and not task.done()
        )

    async def start(
        self,
    ) -> bool:
        if not self.enabled:
            logger.info(
                "embedded_live_worker_disabled"
            )

            return False

        if self.running:
            logger.warning(
                "embedded_live_worker_"
                "already_running"
            )

            return False

        self._stop_event = (
            asyncio.Event()
        )

        self._supervisor_task = (
            asyncio.create_task(
                self._supervisor_loop(),
                name=(
                    "embedded-helius-"
                    "live-worker-supervisor"
                ),
            )
        )

        logger.info(
            "embedded_live_worker_started"
        )

        return True

    async def stop(
        self,
    ) -> bool:
        task = self._supervisor_task

        if task is None:
            return False

        if self._stop_event is not None:
            self._stop_event.set()

        worker = self._current_worker

        if worker is not None:
            with suppress(Exception):
                worker.request_stop()

        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=(
                    self
                    .shutdown_timeout_seconds
                ),
            )

        except TimeoutError:
            logger.error(
                "embedded_live_worker_"
                "shutdown_timeout "
                "timeout_seconds=%.2f",
                self
                .shutdown_timeout_seconds,
            )

            task.cancel()

            with suppress(
                asyncio.CancelledError,
                Exception,
            ):
                await task

        except Exception:
            logger.exception(
                "embedded_live_worker_"
                "shutdown_failed"
            )

        finally:
            self._current_worker = None
            self._supervisor_task = None
            self._stop_event = None

        logger.info(
            "embedded_live_worker_stopped"
        )

        return True

    async def _supervisor_loop(
        self,
    ) -> None:
        stop_event = self._stop_event

        if stop_event is None:
            raise RuntimeError(
                "Stop event del worker "
                "non inizializzato."
            )

        while not stop_event.is_set():
            worker: (
                LiveTradingWorkerProtocol
                | None
            ) = None

            try:
                worker = (
                    self._worker_factory()
                )

                self._current_worker = (
                    worker
                )

                await worker.run()

            except asyncio.CancelledError:
                if worker is not None:
                    with suppress(
                        Exception
                    ):
                        worker.request_stop()

                raise

            except Exception:
                logger.exception(
                    "embedded_live_worker_"
                    "crashed"
                )

            finally:
                if (
                    self._current_worker
                    is worker
                ):
                    self._current_worker = (
                        None
                    )

            if stop_event.is_set():
                break

            logger.error(
                "embedded_live_worker_"
                "unexpected_exit "
                "restart_seconds=%.2f",
                self.restart_seconds,
            )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=(
                        self.restart_seconds
                    ),
                )

            except TimeoutError:
                continue


live_trading_worker_runtime = (
    EmbeddedLiveTradingWorkerRuntime()
) 