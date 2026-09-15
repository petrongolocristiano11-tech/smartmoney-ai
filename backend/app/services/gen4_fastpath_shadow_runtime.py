from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from websockets.asyncio.client import connect

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.services.gen4_fastpath_shadow_service import (
    M314_CANDIDATE_EXIT_RECOVERY_TICK_SECONDS,
    active_fastpath_wallets,
    configured_fastpath_candidate_wallets,
    fastpath_notification_wallet_hint,
    recover_candidate_roundtrip_exits,
    record_fastpath_candidate_notification,
    record_candidate_order_diagnostic,
    load_pending_candidate_order_diagnostics,
    record_fastpath_notification,
    reconcile_fastpath_events,
    reconcile_m319_candidate_edge_instrumentation,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.gen4_promoted_exit_recovery_service import (
    PROMOTED_EXIT_RECOVERY_TICK_SECONDS,
    recover_promoted_selective_exits,
)

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
        self._candidate_slot_clock_subscription_id: int | None = None
        self._candidate_slot_clock: dict[int, dict[str, Any]] = {}
        self._candidate_slot_clock_updates = 0
        self._candidate_slot_clock_hits = 0
        self._candidate_slot_clock_misses = 0
        self._candidate_wallet_locks: dict[str, asyncio.Lock] = {}
        self._candidate_fallback_lock = asyncio.Lock()
        self._official_wallet_locks: dict[str, asyncio.Lock] = {}
        self._official_fallback_lock = asyncio.Lock()
        self._reconcile_task: asyncio.Task | None = None
        self._promoted_exit_recovery_task: asyncio.Task | None = None
        self._promoted_exit_recovery_runs = 0
        self._promoted_exit_recovery_groups = 0
        self._promoted_exit_recovery_errors = 0
        self._candidate_exit_recovery_task: asyncio.Task | None = None
        self._candidate_exit_recovery_runs = 0
        self._candidate_exit_recovery_groups = 0
        self._candidate_exit_recovery_errors = 0
        self._candidate_order_diagnostic_task: asyncio.Task | None = None
        self._candidate_order_diagnostic_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._candidate_order_diagnostic_enqueued = 0
        self._candidate_order_diagnostic_completed = 0
        self._candidate_order_diagnostic_failed = 0
        self._candidate_order_diagnostic_recovered_pending = 0

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
                "slot_clock_subscription_id": self._candidate_slot_clock_subscription_id,
                "slot_clock_updates": self._candidate_slot_clock_updates,
                "slot_clock_hits": self._candidate_slot_clock_hits,
                "slot_clock_misses": self._candidate_slot_clock_misses,
                "slot_clock_cache_size": len(self._candidate_slot_clock),
                "slot_clock_source": "HELIUS_SLOTS_UPDATES_SERVER_TIMESTAMP",
                "slot_clock_true_chain_block_time": False,
                "separate_wss_connection": False,
                "live_execution": False,
                "signer_access": False,
            },
            "promoted_exit_recovery": {
                "running": bool(
                    self._promoted_exit_recovery_task is not None
                    and not self._promoted_exit_recovery_task.done()
                ),
                "runs": self._promoted_exit_recovery_runs,
                "recovered_groups": self._promoted_exit_recovery_groups,
                "errors": self._promoted_exit_recovery_errors,
                "live_execution": False,
                "signer_access": False,
                "transaction_submission": False,
            },
            "candidate_exit_recovery": {
                "running": bool(
                    self._candidate_exit_recovery_task is not None
                    and not self._candidate_exit_recovery_task.done()
                ),
                "runs": self._candidate_exit_recovery_runs,
                "recovered_groups": self._candidate_exit_recovery_groups,
                "errors": self._candidate_exit_recovery_errors,
                "live_execution": False,
                "paper_execution": False,
                "signer_access": False,
                "transaction_submission": False,
                "backfill": False,
            },
            "candidate_order_diagnostic": {
                "running": bool(
                    self._candidate_order_diagnostic_task is not None
                    and not self._candidate_order_diagnostic_task.done()
                ),
                "queue_size": (
                    self._candidate_order_diagnostic_queue.qsize()
                    if self._candidate_order_diagnostic_queue is not None
                    else 0
                ),
                "enqueued": self._candidate_order_diagnostic_enqueued,
                "completed": self._candidate_order_diagnostic_completed,
                "failed": self._candidate_order_diagnostic_failed,
                "recovered_pending": self._candidate_order_diagnostic_recovered_pending,
                "critical_path": False,
                "low_priority": True,
                "live_execution": False,
                "signer_access": False,
                "transaction_submission": False,
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
        self._jupiter = JupiterSwapClient(persistent_http=True, shared_rate_limit=True)
        self._task = asyncio.create_task(self._run(), name="gen4-fastpath-shadow")
        self._promoted_exit_recovery_task = asyncio.create_task(
            self._run_promoted_exit_recovery(),
            name="gen4-promoted-exit-recovery-shadow",
        )
        if self.candidate_enabled:
            self._candidate_jupiter = JupiterSwapClient(persistent_http=True, shared_rate_limit=True)
            self._candidate_task = asyncio.create_task(
                self._run_candidate(),
                name="gen4-fastpath-candidate-shadow",
            )
            self._candidate_exit_recovery_task = asyncio.create_task(
                self._run_candidate_exit_recovery(),
                name="gen4-m314-candidate-exit-recovery-shadow",
            )
            self._candidate_order_diagnostic_queue = asyncio.Queue(maxsize=256)
            recovered_pending = await asyncio.to_thread(
                self._load_pending_candidate_order_diagnostics
            )
            for request in recovered_pending:
                self._candidate_order_diagnostic_queue.put_nowait(
                    dict(request)
                )
                self._candidate_order_diagnostic_enqueued += 1
                self._candidate_order_diagnostic_recovered_pending += 1
            self._candidate_order_diagnostic_task = asyncio.create_task(
                self._run_candidate_order_diagnostics(),
                name="gen4-candidate-order-diagnostic-shadow",
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
        self._candidate_slot_clock_subscription_id = None
        self._candidate_slot_clock.clear()
        if self._reconcile_task is not None:
            self._reconcile_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._reconcile_task
        self._reconcile_task = None
        if self._promoted_exit_recovery_task is not None:
            self._promoted_exit_recovery_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._promoted_exit_recovery_task
        self._promoted_exit_recovery_task = None
        if self._candidate_exit_recovery_task is not None:
            self._candidate_exit_recovery_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._candidate_exit_recovery_task
        self._candidate_exit_recovery_task = None
        if self._candidate_order_diagnostic_task is not None:
            self._candidate_order_diagnostic_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._candidate_order_diagnostic_task
        self._candidate_order_diagnostic_task = None
        self._candidate_order_diagnostic_queue = None
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

    def _record(self, message: dict[str, Any], received_at: datetime) -> None:
        if self._jupiter is None:
            return
        with SessionLocal() as db:
            try:
                record_fastpath_notification(
                    db,
                    message=message,
                    jupiter_client=self._jupiter,
                    received_at=received_at,
                )
                db.commit()
            except Exception:
                db.rollback()
                raise

    def _candidate_wallets(self) -> list[str]:
        return configured_fastpath_candidate_wallets()

    @staticmethod
    def _candidate_source_slot(message: dict[str, Any]) -> int | None:
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        result = params.get("result") if isinstance(params.get("result"), dict) else {}
        try:
            return int(result.get("slot")) if result.get("slot") is not None else None
        except (TypeError, ValueError):
            return None

    def _candidate_slot_clock_for_message(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any] | None:
        slot = self._candidate_source_slot(message)
        if slot is None:
            self._candidate_slot_clock_misses += 1
            return None
        clock = self._candidate_slot_clock.get(slot)
        if clock is None:
            self._candidate_slot_clock_misses += 1
            return None
        self._candidate_slot_clock_hits += 1
        return dict(clock)

    def _record_candidate_slot_update(
        self,
        message: dict[str, Any],
        received_at: datetime,
    ) -> None:
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        result = params.get("result") if isinstance(params.get("result"), dict) else {}
        try:
            slot = int(result.get("slot"))
            timestamp_ms = int(result.get("timestamp"))
        except (TypeError, ValueError):
            return
        update_type = str(result.get("type") or "")
        candidate = {
            "slot": slot,
            "server_timestamp_ms": timestamp_ms,
            "type": update_type,
            "local_received_at_utc": received_at.isoformat(),
        }
        current = self._candidate_slot_clock.get(slot)
        should_replace = current is None
        if current is not None:
            current_type = str(current.get("type") or "")
            try:
                current_ts = int(current.get("server_timestamp_ms"))
            except (TypeError, ValueError):
                current_ts = timestamp_ms
            if update_type == "firstShredReceived" and current_type != "firstShredReceived":
                should_replace = True
            elif current_type != "firstShredReceived" and timestamp_ms < current_ts:
                should_replace = True
            elif update_type == current_type and timestamp_ms < current_ts:
                should_replace = True
        if should_replace:
            self._candidate_slot_clock[slot] = candidate
        self._candidate_slot_clock_updates += 1
        if len(self._candidate_slot_clock) > 512:
            for stale_slot in sorted(self._candidate_slot_clock)[:-384]:
                self._candidate_slot_clock.pop(stale_slot, None)

    def _record_candidate(
        self,
        message: dict[str, Any],
        received_at: datetime,
    ) -> dict[str, Any]:
        if self._candidate_jupiter is None:
            return {"status": "CANDIDATE_JUPITER_UNAVAILABLE"}
        provider_slot_clock = (
            dict(message.get("_m319_provider_slot_clock"))
            if isinstance(message.get("_m319_provider_slot_clock"), dict)
            else None
        )
        with SessionLocal() as db:
            try:
                result = record_fastpath_candidate_notification(
                    db,
                    message=message,
                    jupiter_client=self._candidate_jupiter,
                    received_at=received_at,
                    provider_slot_clock=provider_slot_clock,
                )
                db.commit()
                return dict(result or {})
            except Exception:
                db.rollback()
                raise

    def _load_pending_candidate_order_diagnostics(
        self,
    ) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            return load_pending_candidate_order_diagnostics(
                db,
                limit=256,
            )

    def _record_candidate_order_diagnostic(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        if self._candidate_jupiter is None:
            return {"status": "DIAGNOSTIC_JUPITER_UNAVAILABLE"}
        with SessionLocal() as db:
            try:
                result = record_candidate_order_diagnostic(
                    db,
                    request=request,
                    jupiter_client=self._candidate_jupiter,
                )
                db.commit()
                return dict(result or {})
            except Exception:
                db.rollback()
                raise

    async def _run_candidate_order_diagnostics(self) -> None:
        while not self._stop_requested and self.candidate_enabled:
            queue = self._candidate_order_diagnostic_queue
            if queue is None:
                await asyncio.sleep(0.05)
                continue
            request = await queue.get()
            try:
                result = await asyncio.to_thread(
                    self._record_candidate_order_diagnostic,
                    dict(request),
                )
                if str(result.get("status") or "") == "DIAGNOSTIC_COMPLETE":
                    self._candidate_order_diagnostic_completed += 1
                else:
                    self._candidate_order_diagnostic_failed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self._candidate_order_diagnostic_failed += 1
                logger.exception("gen4_candidate_order_diagnostic_failed")
            finally:
                queue.task_done()

    async def _enqueue_candidate_order_diagnostic(
        self,
        request: dict[str, Any] | None,
    ) -> None:
        if not isinstance(request, dict):
            return
        queue = self._candidate_order_diagnostic_queue
        if queue is None:
            return
        await queue.put(dict(request))
        self._candidate_order_diagnostic_enqueued += 1

    def _recover_candidate_exits(self) -> dict[str, Any]:
        if self._candidate_jupiter is None:
            return {"recovered_groups": 0}
        with SessionLocal() as db:
            try:
                result = recover_candidate_roundtrip_exits(
                    db,
                    jupiter_client=self._candidate_jupiter,
                )
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

    async def _run_candidate_exit_recovery(self) -> None:
        while not self._stop_requested and self.candidate_enabled:
            try:
                result = await asyncio.to_thread(self._recover_candidate_exits)
                self._candidate_exit_recovery_runs += 1
                self._candidate_exit_recovery_groups += int(
                    result.get("recovered_groups") or 0
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._candidate_exit_recovery_errors += 1
                logger.exception("gen4_m314_candidate_exit_recovery_failed")
            await asyncio.sleep(M314_CANDIDATE_EXIT_RECOVERY_TICK_SECONDS)

    def _recover_promoted_exits(self) -> dict[str, Any]:
        if self._jupiter is None:
            return {"recovered_groups": 0}
        with SessionLocal() as db:
            try:
                result = recover_promoted_selective_exits(
                    db,
                    jupiter_client=self._jupiter,
                )
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

    async def _run_promoted_exit_recovery(self) -> None:
        while not self._stop_requested:
            try:
                result = await asyncio.to_thread(self._recover_promoted_exits)
                self._promoted_exit_recovery_runs += 1
                self._promoted_exit_recovery_groups += int(
                    result.get("recovered_groups") or 0
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._promoted_exit_recovery_errors += 1
                logger.exception("gen4_promoted_exit_recovery_failed")
            await asyncio.sleep(PROMOTED_EXIT_RECOVERY_TICK_SECONDS)

    def _reconcile(self) -> None:
        with SessionLocal() as db:
            try:
                reconcile_fastpath_events(db, limit=200)
                reconcile_m319_candidate_edge_instrumentation(db, limit=200)
                db.commit()
            except Exception:
                db.rollback()
                raise

    async def _reconcile_background(self) -> None:
        try:
            await asyncio.to_thread(self._reconcile)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._errors += 1
            logger.exception("gen4_fastpath_shadow_reconcile_failed")

    def _schedule_reconcile(self) -> None:
        if self._reconcile_task is not None and not self._reconcile_task.done():
            return
        self._reconcile_task = asyncio.create_task(
            self._reconcile_background(),
            name="gen4-fastpath-reconcile",
        )

    async def _handle(
        self,
        message: dict[str, Any],
        semaphore: asyncio.Semaphore,
        received_at: datetime,
        wallet_hint: str | None,
    ) -> None:
        lock = (
            self._official_wallet_locks.setdefault(wallet_hint, asyncio.Lock())
            if wallet_hint
            else self._official_fallback_lock
        )
        # Per-wallet ordering is required by the M138 shadow position lifecycle.
        # The global semaphore still allows different wallets to quote concurrently.
        async with lock:
            async with semaphore:
                try:
                    await asyncio.to_thread(self._record, message, received_at)
                except Exception:
                    self._errors += 1
                    logger.exception("gen4_fastpath_shadow_event_failed")

    async def _handle_candidate(
        self,
        message: dict[str, Any],
        semaphore: asyncio.Semaphore,
        received_at: datetime,
    ) -> None:
        provider_slot_clock = self._candidate_slot_clock_for_message(message)
        record_message = message
        if provider_slot_clock is not None:
            record_message = {
                **message,
                "_m319_provider_slot_clock": provider_slot_clock,
            }
        wallets = configured_fastpath_candidate_wallets()
        wallet_hint = fastpath_notification_wallet_hint(message, wallets)
        if wallet_hint is None:
            lock = self._candidate_fallback_lock
        else:
            lock = self._candidate_wallet_locks.setdefault(wallet_hint, asyncio.Lock())

        record_result: dict[str, Any] | None = None
        async with lock:
            async with semaphore:
                try:
                    record_result = await asyncio.to_thread(
                        self._record_candidate,
                        record_message,
                        received_at,
                    )
                except Exception:
                    self._candidate_errors += 1
                    logger.exception("gen4_fastpath_candidate_shadow_event_failed")

        if isinstance(record_result, dict):
            await self._enqueue_candidate_order_diagnostic(
                record_result.get("deferred_order_diagnostic")
            )

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
                                        "maxSupportedTransactionVersion": 1,
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
                            self._schedule_reconcile()
                            current = tuple(await asyncio.to_thread(self._wallets))
                            if current != last_wallets:
                                logger.info("gen4_fastpath_shadow_wallet_set_changed reconnecting")
                                break
                            continue
                        received_at = datetime.now(timezone.utc)
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
                        wallet_hint = fastpath_notification_wallet_hint(
                            message, list(last_wallets)
                        )
                        asyncio.create_task(
                            self._handle(
                                message,
                                semaphore,
                                received_at,
                                wallet_hint,
                            )
                        )
                        if self._messages % 10 == 0:
                            self._schedule_reconcile()
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
                    slot_clock_request_id = 319_018
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
                                        "maxSupportedTransactionVersion": 1,
                                    },
                                ],
                            },
                            separators=(",", ":"),
                        )
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": slot_clock_request_id,
                                "method": "slotsUpdatesSubscribe",
                                "params": [],
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
                    next_wallet_refresh = (
                        asyncio.get_running_loop().time() + float(refresh_seconds)
                    )
                    while not self._stop_requested and self.candidate_enabled:
                        now_monotonic = asyncio.get_running_loop().time()
                        if now_monotonic >= next_wallet_refresh:
                            current = tuple(
                                await asyncio.to_thread(self._candidate_wallets)
                            )
                            if current != last_wallets:
                                logger.info(
                                    "gen4_fastpath_candidate_shadow_wallet_set_changed reconnecting"
                                )
                                break
                            next_wallet_refresh = (
                                asyncio.get_running_loop().time()
                                + float(refresh_seconds)
                            )
                        recv_timeout = max(
                            0.1,
                            min(
                                float(refresh_seconds),
                                next_wallet_refresh - asyncio.get_running_loop().time(),
                            ),
                        )
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                        except asyncio.TimeoutError:
                            current = tuple(
                                await asyncio.to_thread(self._candidate_wallets)
                            )
                            if current != last_wallets:
                                logger.info(
                                    "gen4_fastpath_candidate_shadow_wallet_set_changed reconnecting"
                                )
                                break
                            next_wallet_refresh = (
                                asyncio.get_running_loop().time()
                                + float(refresh_seconds)
                            )
                            continue
                        received_at = datetime.now(timezone.utc)
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
                        if (
                            message.get("id") == slot_clock_request_id
                            and message.get("result") is not None
                        ):
                            try:
                                self._candidate_slot_clock_subscription_id = int(
                                    message["result"]
                                )
                            except (TypeError, ValueError):
                                self._candidate_slot_clock_subscription_id = None
                            logger.info(
                                "gen4_fastpath_candidate_slot_clock_subscribed id=%s",
                                self._candidate_slot_clock_subscription_id,
                            )
                            continue
                        if message.get("method") == "slotsUpdatesNotification":
                            self._record_candidate_slot_update(message, received_at)
                            continue
                        if message.get("method") != "transactionNotification":
                            continue
                        self._candidate_messages += 1
                        asyncio.create_task(
                            self._handle_candidate(
                                message,
                                semaphore,
                                received_at,
                            )
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                self._candidate_errors += 1
                logger.exception("gen4_fastpath_candidate_shadow_connection_failed")
            finally:
                self._candidate_connected = False
                self._candidate_subscription_id = None
                self._candidate_slot_clock_subscription_id = None
            if not self._stop_requested and self.candidate_enabled:
                await asyncio.sleep(reconnect)
                reconnect = min(reconnect_max, max(0.25, reconnect * 2.0))


gen4_fastpath_shadow_runtime = EmbeddedGen4FastpathShadowRuntime()
