from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

from websockets.asyncio.client import connect

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.services.gen4_fastpath_shadow_service import (
    active_fastpath_wallets,
    configured_fastpath_candidate_wallets,
    record_fastpath_candidate_notification,
    record_fastpath_notification,
    reconcile_fastpath_events,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient

logger = logging.getLogger("smartmoney.gen4_fastpath_shadow")


class EmbeddedGen4FastpathShadowRuntime:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_requested = False
        self._jupiter: JupiterSwapClient | None = None
        self._subscription_id: int | None = None
        self._connected = False
        self._messages = 0
        self._errors = 0
        self._candidate_task: asyncio.Task | None = None
        self._candidate_jupiter: JupiterSwapClient | None = None
        self._candidate_subscription_id: int | None = None
        self._candidate_connected = False
        self._candidate_messages = 0
        self._candidate_errors = 0

    @property
    def enabled(self) -> bool:
        return bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_SHADOW_ENABLED", False)
            and getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED", False)
        )

    @property
    def running(self) -> bool:
        return bool(self._task is not None and not self._task.done())

    @property
    def candidate_enabled(self) -> bool:
        return bool(
            self.enabled
            and getattr(
                settings,
                "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_WATCHLIST_ENABLED",
                False,
            )
            and configured_fastpath_candidate_wallets()
        )

    @property
    def candidate_running(self) -> bool:
        return bool(
            self._candidate_task is not None
            and not self._candidate_task.done()
        )

    @property
    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "connected": self._connected,
            "subscription_id": self._subscription_id,
            "messages": self._messages,
            "errors": self._errors,
            "commitment": "processed",
            "candidate": {
                "enabled": self.candidate_enabled,
                "running": self.candidate_running,
                "connected": self._candidate_connected,
                "subscription_id": self._candidate_subscription_id,
                "wallets": configured_fastpath_candidate_wallets(),
                "messages": self._candidate_messages,
                "errors": self._candidate_errors,
                "separate_wss_connection": True,
                "live_execution": False,
                "signer_access": False,
            },
            "live_execution": False,
            "signer_access": False,
        }

    async def start(self) -> bool:
        if not self.enabled:
            logger.info("gen4_fastpath_shadow_disabled")
            return False
        if self.running:
            return False
        self._stop_requested = False
        self._jupiter = JupiterSwapClient(persistent_http=True)
        self._task = asyncio.create_task(self._run(), name="gen4-fastpath-shadow")
        if self.candidate_enabled:
            self._candidate_jupiter = JupiterSwapClient(persistent_http=True)
            self._candidate_task = asyncio.create_task(
                self._run_candidate(),
                name="gen4-fastpath-candidate-shadow",
            )
            logger.info(
                "gen4_fastpath_candidate_shadow_started wallet_count=%s",
                len(configured_fastpath_candidate_wallets()),
            )
        logger.info("gen4_fastpath_shadow_started")
        return True

    async def stop(self) -> bool:
        self._stop_requested = True
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None
        self._connected = False
        self._subscription_id = None
        if self._candidate_task is not None:
            self._candidate_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._candidate_task
        self._candidate_task = None
        self._candidate_connected = False
        self._candidate_subscription_id = None
        if self._jupiter is not None:
            await asyncio.to_thread(self._jupiter.close)
        self._jupiter = None
        if self._candidate_jupiter is not None:
            await asyncio.to_thread(self._candidate_jupiter.close)
        self._candidate_jupiter = None
        logger.info("gen4_fastpath_shadow_stopped")
        return True

    def _wallets(self) -> list[str]:
        with SessionLocal() as db:
            return active_fastpath_wallets(db)

    def _record(self, message: dict[str, Any]) -> None:
        if self._jupiter is None:
            return
        with SessionLocal() as db:
            try:
                record_fastpath_notification(db, message=message, jupiter_client=self._jupiter)
                db.commit()
            except Exception:
                db.rollback()
                raise

    def _candidate_wallets(self) -> list[str]:
        return configured_fastpath_candidate_wallets()

    def _record_candidate(self, message: dict[str, Any]) -> None:
        if self._candidate_jupiter is None:
            return
        with SessionLocal() as db:
            try:
                record_fastpath_candidate_notification(
                    db,
                    message=message,
                    jupiter_client=self._candidate_jupiter,
                )
                db.commit()
            except Exception:
                db.rollback()
                raise

    def _reconcile(self) -> None:
        with SessionLocal() as db:
            try:
                reconcile_fastpath_events(db, limit=200)
                db.commit()
            except Exception:
                db.rollback()
                raise

    async def _handle(self, message: dict[str, Any], semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                await asyncio.to_thread(self._record, message)
            except Exception:
                self._errors += 1
                logger.exception("gen4_fastpath_shadow_event_failed")

    async def _handle_candidate(
        self,
        message: dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            try:
                await asyncio.to_thread(self._record_candidate, message)
            except Exception:
                self._candidate_errors += 1
                logger.exception("gen4_fastpath_candidate_shadow_event_failed")

    async def _run(self) -> None:
        reconnect = float(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_RECONNECT_BASE_SECONDS", 1.0)
        )
        reconnect_max = float(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_RECONNECT_MAX_SECONDS", 15.0)
        )
        refresh_seconds = int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_WALLET_REFRESH_SECONDS", 15)
        )
        semaphore = asyncio.Semaphore(
            int(getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_MAX_INFLIGHT", 4))
        )
        max_size = int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_MAX_MESSAGE_BYTES", 4_000_000)
        )
        ping_interval = int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_PING_INTERVAL_SECONDS", 30)
        )
        ping_timeout = int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_PING_TIMEOUT_SECONDS", 20)
        )

        while not self._stop_requested:
            wallets = await asyncio.to_thread(self._wallets)
            if not wallets:
                await asyncio.sleep(min(5, refresh_seconds))
                continue
            url = f"wss://mainnet.helius-rpc.com/?api-key={settings.HELIUS_API_KEY}"
            try:
                async with connect(
                    url,
                    ping_interval=ping_interval,
                    ping_timeout=ping_timeout,
                    max_size=max_size,
                    close_timeout=5,
                ) as ws:
                    self._connected = True
                    request_id = 117_004
                    await ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "method": "transactionSubscribe",
                                "params": [
                                    {
                                        "vote": False,
                                        "failed": False,
                                        "accountInclude": wallets,
                                        "tokenAccounts": "balanceChanged",
                                    },
                                    {
                                        "commitment": "processed",
                                        "encoding": "jsonParsed",
                                        "transactionDetails": "full",
                                        "showRewards": False,
                                        "maxSupportedTransactionVersion": 0,
                                    },
                                ],
                            },
                            separators=(",", ":"),
                        )
                    )
                    logger.info("gen4_fastpath_shadow_subscribe wallet_count=%s", len(wallets))
                    reconnect = float(
                        getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_RECONNECT_BASE_SECONDS", 1.0)
                    )
                    last_wallets = tuple(wallets)
                    while not self._stop_requested:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=refresh_seconds)
                        except asyncio.TimeoutError:
                            await asyncio.to_thread(self._reconcile)
                            current = tuple(await asyncio.to_thread(self._wallets))
                            if current != last_wallets:
                                logger.info("gen4_fastpath_shadow_wallet_set_changed reconnecting")
                                break
                            continue
                        message = json.loads(raw)
                        if message.get("id") == request_id and message.get("result") is not None:
                            try:
                                self._subscription_id = int(message["result"])
                            except (TypeError, ValueError):
                                self._subscription_id = None
                            logger.info("gen4_fastpath_shadow_subscribed id=%s", self._subscription_id)
                            continue
                        if message.get("method") != "transactionNotification":
                            continue
                        self._messages += 1
                        asyncio.create_task(self._handle(message, semaphore))
                        if self._messages % 10 == 0:
                            await asyncio.to_thread(self._reconcile)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._errors += 1
                logger.exception("gen4_fastpath_shadow_connection_failed")
            finally:
                self._connected = False
                self._subscription_id = None
            if not self._stop_requested:
                await asyncio.sleep(reconnect)
                reconnect = min(reconnect_max, max(0.25, reconnect * 2.0))


    async def _run_candidate(self) -> None:
        reconnect = float(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_RECONNECT_BASE_SECONDS", 1.0)
        )
        reconnect_max = float(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_RECONNECT_MAX_SECONDS", 15.0)
        )
        refresh_seconds = int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_WALLET_REFRESH_SECONDS", 15)
        )
        semaphore = asyncio.Semaphore(
            int(getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_MAX_INFLIGHT", 4))
        )
        max_size = int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_MAX_MESSAGE_BYTES", 4_000_000)
        )
        ping_interval = int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_PING_INTERVAL_SECONDS", 30)
        )
        ping_timeout = int(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_PING_TIMEOUT_SECONDS", 20)
        )

        while not self._stop_requested and self.candidate_enabled:
            wallets = await asyncio.to_thread(self._candidate_wallets)
            if not wallets:
                await asyncio.sleep(min(5, refresh_seconds))
                continue
            url = f"wss://mainnet.helius-rpc.com/?api-key={settings.HELIUS_API_KEY}"
            try:
                async with connect(
                    url,
                    ping_interval=ping_interval,
                    ping_timeout=ping_timeout,
                    max_size=max_size,
                    close_timeout=5,
                ) as ws:
                    self._candidate_connected = True
                    request_id = 117_005
                    await ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "method": "transactionSubscribe",
                                "params": [
                                    {
                                        "vote": False,
                                        "failed": False,
                                        "accountInclude": wallets,
                                        "tokenAccounts": "balanceChanged",
                                    },
                                    {
                                        "commitment": "processed",
                                        "encoding": "jsonParsed",
                                        "transactionDetails": "full",
                                        "showRewards": False,
                                        "maxSupportedTransactionVersion": 0,
                                    },
                                ],
                            },
                            separators=(",", ":"),
                        )
                    )
                    logger.info(
                        "gen4_fastpath_candidate_shadow_subscribe wallet_count=%s",
                        len(wallets),
                    )
                    reconnect = float(
                        getattr(
                            settings,
                            "CANONICAL_PARSER_GEN4_FASTPATH_RECONNECT_BASE_SECONDS",
                            1.0,
                        )
                    )
                    last_wallets = tuple(wallets)
                    while not self._stop_requested and self.candidate_enabled:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=refresh_seconds)
                        except asyncio.TimeoutError:
                            current = tuple(
                                await asyncio.to_thread(self._candidate_wallets)
                            )
                            if current != last_wallets:
                                logger.info(
                                    "gen4_fastpath_candidate_shadow_wallet_set_changed reconnecting"
                                )
                                break
                            continue
                        message = json.loads(raw)
                        if (
                            message.get("id") == request_id
                            and message.get("result") is not None
                        ):
                            try:
                                self._candidate_subscription_id = int(message["result"])
                            except (TypeError, ValueError):
                                self._candidate_subscription_id = None
                            logger.info(
                                "gen4_fastpath_candidate_shadow_subscribed id=%s",
                                self._candidate_subscription_id,
                            )
                            continue
                        if message.get("method") != "transactionNotification":
                            continue
                        self._candidate_messages += 1
                        asyncio.create_task(
                            self._handle_candidate(message, semaphore)
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._candidate_errors += 1
                logger.exception("gen4_fastpath_candidate_shadow_connection_failed")
            finally:
                self._candidate_connected = False
                self._candidate_subscription_id = None
            if not self._stop_requested and self.candidate_enabled:
                await asyncio.sleep(reconnect)
                reconnect = min(reconnect_max, max(0.25, reconnect * 2.0))


gen4_fastpath_shadow_runtime = EmbeddedGen4FastpathShadowRuntime()
