from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from backend.app.core.config import settings
from backend.app.workers.gen4_forward_feed_worker import Gen4ForwardFeedWorker


logger = logging.getLogger("smartmoney.embedded_gen4_forward_feed")


class EmbeddedGen4ForwardFeedRuntime:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._worker: Gen4ForwardFeedWorker | None = None

    @property
    def enabled(self) -> bool:
        return bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED", False)
            and getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_AUTOSTART", False)
        )

    @property
    def running(self) -> bool:
        return bool(self._task is not None and not self._task.done())

    async def start(self) -> bool:
        if not self.enabled:
            logger.info("embedded_gen4_forward_feed_disabled")
            return False
        if self.running:
            return False
        self._worker = Gen4ForwardFeedWorker()
        self._task = asyncio.create_task(
            self._worker.run(),
            name="embedded-gen4-forward-feed-worker",
        )
        logger.info("embedded_gen4_forward_feed_started")
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
        logger.info("embedded_gen4_forward_feed_stopped")
        return True


gen4_forward_feed_runtime = EmbeddedGen4ForwardFeedRuntime()
