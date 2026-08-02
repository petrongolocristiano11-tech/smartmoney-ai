from __future__ import annotations

import asyncio
import logging
import socket
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.services.blockchain_parser_gen4_forward_feed_service import (
    GEN4_FORWARD_FEED_POLL_CONFIRMATION,
    get_gen4_forward_feed_status,
    run_gen4_forward_feed_poll,
)


logger = logging.getLogger("smartmoney.gen4_forward_feed_worker")


class Gen4ForwardFeedWorker:
    def __init__(self) -> None:
        self._stop_requested = False
        self._owner_id = f"{socket.gethostname()}-{uuid4()}"[:120]

    def request_stop(self) -> None:
        self._stop_requested = True

    async def run(self) -> None:
        while not self._stop_requested:
            delay = await asyncio.to_thread(self._iteration)
            if self._stop_requested:
                break
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                self.request_stop()
                raise

    def _iteration(self) -> float:
        fallback = float(
            getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_INTERVAL_SECONDS", 120)
        )
        if not bool(getattr(settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED", False)):
            return fallback
        with SessionLocal() as db:
            try:
                status = get_gen4_forward_feed_status(db)
                state = dict(status.get("state") or {})
                interval = max(30.0, float(state.get("interval_seconds") or fallback))
                if not bool(state.get("enabled")):
                    db.commit()
                    return interval
                next_poll_at = state.get("next_poll_at")
                if next_poll_at is not None:
                    if isinstance(next_poll_at, str):
                        next_poll_at = datetime.fromisoformat(next_poll_at.replace("Z", "+00:00"))
                    if next_poll_at.tzinfo is None:
                        next_poll_at = next_poll_at.replace(tzinfo=timezone.utc)
                    seconds_until = (next_poll_at - datetime.now(timezone.utc)).total_seconds()
                    if seconds_until > 0:
                        db.commit()
                        return min(interval, max(1.0, seconds_until))
                run_gen4_forward_feed_poll(
                    db,
                    campaign_id=str(status["campaign_id"]),
                    confirmation=GEN4_FORWARD_FEED_POLL_CONFIRMATION,
                    trigger="SCHEDULER",
                    owner_id=self._owner_id,
                )
                db.commit()
                return interval
            except Exception:
                db.rollback()
                logger.exception("gen4_forward_feed_iteration_failed")
                return max(10.0, min(fallback, 60.0))
