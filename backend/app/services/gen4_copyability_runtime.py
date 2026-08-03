from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from backend.app.core.config import settings
from backend.app.workers.gen4_copyability_worker import Gen4CopyabilityWorker


logger = logging.getLogger("smartmoney.embedded_gen4_copyability")


class EmbeddedGen4CopyabilityRuntime:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._worker: Gen4CopyabilityWorker | None = None

    @property
    def enabled(self) -> bool:
        return bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED", False)
            and getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_AUTOSTART", False)
        )

    @property
    def running(self) -> bool:
        return bool(self._task is not None and not self._task.done())

    async def start(self) -> bool:
        if not self.enabled:
            logger.info("embedded_gen4_copyability_disabled")
            return False
        if self.running:
            return False
        self._worker = Gen4CopyabilityWorker()
        self._task = asyncio.create_task(
            self._worker.run(),
            name="embedded-gen4-copyability-worker",
        )
        logger.info("embedded_gen4_copyability_started")
        return True

    async def stop(self) -> bool:
        if self._task is None:
            return False
        if self._worker is not None:
            self._worker.request_stop()
        self._task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await self._task
        self._task = None
        self._worker = None
        logger.info("embedded_gen4_copyability_stopped")
        return True


gen4_copyability_runtime = EmbeddedGen4CopyabilityRuntime()
