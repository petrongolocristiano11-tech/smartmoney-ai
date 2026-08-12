from __future__ import annotations

import asyncio
import logging
import socket
from uuid import uuid4

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    GEN4_COPYABILITY_PROCESS_CONFIRMATION,
    GEN4_COPYABILITY_START_CONFIRMATION,
    get_gen4_copyability_status,
    process_gen4_copyability_queue,
    start_gen4_copyability_campaign,
)


logger = logging.getLogger("smartmoney.gen4_copyability_worker")


class Gen4CopyabilityWorker:
    """Persistent DB-backed shadow worker.

    It never receives a signer and never calls Jupiter execute. The worker only
    converts already persisted Helius webhook receipts into quote-time shadow
    positions. A database lease prevents duplicate queue processing when a
    deployment briefly overlaps with its replacement.
    """

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
        fallback = max(
            1.0,
            min(
                float(
                    getattr(
                        settings,
                        "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_INTERVAL_SECONDS",
                        1,
                    )
                ),
                60.0,
            ),
        )
        if not bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED", False)
        ):
            return fallback

        with SessionLocal() as db:
            try:
                status = get_gen4_copyability_status(db, recent_limit=1)
                campaigns = list(status.get("active_campaigns") or [])
                primary_campaigns = [
                    item
                    for item in campaigns
                    if item.get("campaign_role") == "PRIMARY_FORWARD"
                ]
                if not campaigns:
                    if not bool(
                        getattr(
                            settings,
                            "CANONICAL_PARSER_GEN4_COPYABILITY_AUTOSTART",
                            False,
                        )
                    ):
                        db.commit()
                        return fallback
                    start_gen4_copyability_campaign(
                        db,
                        confirmation=GEN4_COPYABILITY_START_CONFIRMATION,
                        actor_label="EMBEDDED_AUTOSTART",
                        note=(
                            "Campagna real-time copyability avviata dal runtime "
                            "embedded. Il clock probatorio verrà riallineato alla "
                            "prima configurazione webhook attiva."
                        ),
                    )
                    db.commit()
                    logger.info("gen4_copyability_campaign_autostarted")
                    return fallback

                # M63 may intentionally keep only one qualified-candidate
                # campaign active. Do not resurrect the obsolete primary
                # campaign while an exclusive candidate is collecting proof.
                if not primary_campaigns:
                    logger.info(
                        "gen4_copyability_candidate_only_runtime campaign_count=%s",
                        len(campaigns),
                    )

                worker_state = dict(status.get("worker_state") or {})
                interval = max(
                    1.0,
                    min(
                        float(worker_state.get("poll_interval_seconds") or fallback),
                        60.0,
                    ),
                )
                if worker_state.get("enabled") is False:
                    db.commit()
                    return interval

                result = process_gen4_copyability_queue(
                    db,
                    confirmation=GEN4_COPYABILITY_PROCESS_CONFIRMATION,
                    owner_id=self._owner_id,
                )
                db.commit()
                processed = int((result.get("summary") or {}).get("receipts_processed") or 0)
                return 0.05 if processed > 0 else interval
            except Exception:
                db.rollback()
                logger.exception("gen4_copyability_iteration_failed")
                return max(2.0, min(fallback * 5.0, 30.0))
