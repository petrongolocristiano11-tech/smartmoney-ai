from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol

from backend.app.core.config import settings
from backend.app.workers.live_position_monitor_worker import LivePositionMonitorWorker


logger = logging.getLogger("smartmoney.embedded_position_monitor")


class WorkerProtocol(Protocol):
    async def run(self) -> None: ...
    def request_stop(self) -> None: ...


WorkerFactory = Callable[[], WorkerProtocol]


class EmbeddedPositionMonitorRuntime:
    def __init__(
        self,
        *,
        worker_factory: WorkerFactory | None = None,
        enabled: bool | None = None,
        restart_seconds: float | None = None,
        shutdown_timeout_seconds: float | None = None,
    ) -> None:
        self._worker_factory = worker_factory or LivePositionMonitorWorker
        self._enabled_override = enabled
        self._restart_seconds_override = restart_seconds
        self._shutdown_timeout_override = shutdown_timeout_seconds
        self._supervisor_task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._current_worker: WorkerProtocol | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled_override if self._enabled_override is not None else settings.RUN_LIVE_POSITION_MONITOR

    @property
    def restart_seconds(self) -> float:
        return self._restart_seconds_override if self._restart_seconds_override is not None else settings.LIVE_POSITION_MONITOR_RESTART_SECONDS

    @property
    def shutdown_timeout_seconds(self) -> float:
        return self._shutdown_timeout_override if self._shutdown_timeout_override is not None else settings.LIVE_POSITION_MONITOR_SHUTDOWN_TIMEOUT_SECONDS

    @property
    def running(self) -> bool:
        return bool(self._supervisor_task is not None and not self._supervisor_task.done())

    async def start(self) -> bool:
        if not self.enabled:
            logger.info("embedded_position_monitor_disabled")
            return False
        if self.running:
            return False
        self._stop_event = asyncio.Event()
        self._supervisor_task = asyncio.create_task(
            self._supervisor_loop(),
            name="embedded-position-monitor-supervisor",
        )
        logger.info("embedded_position_monitor_started")
        return True

    async def stop(self) -> bool:
        task = self._supervisor_task
        if task is None:
            return False
        if self._stop_event is not None:
            self._stop_event.set()
        if self._current_worker is not None:
            with suppress(Exception):
                self._current_worker.request_stop()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.shutdown_timeout_seconds)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        finally:
            self._supervisor_task = None
            self._stop_event = None
            self._current_worker = None
        logger.info("embedded_position_monitor_stopped")
        return True

    async def _supervisor_loop(self) -> None:
        stop_event = self._stop_event
        if stop_event is None:
            raise RuntimeError("Stop event monitor non inizializzato.")
        while not stop_event.is_set():
            worker: WorkerProtocol | None = None
            try:
                worker = self._worker_factory()
                self._current_worker = worker
                await worker.run()
            except asyncio.CancelledError:
                if worker is not None:
                    with suppress(Exception):
                        worker.request_stop()
                raise
            except Exception:
                logger.exception("embedded_position_monitor_crashed")
            finally:
                if self._current_worker is worker:
                    self._current_worker = None
            if stop_event.is_set():
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.restart_seconds)
            except TimeoutError:
                continue


live_position_monitor_runtime = EmbeddedPositionMonitorRuntime()
