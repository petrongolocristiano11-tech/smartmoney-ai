import asyncio

from backend.app.services.live_trading_worker_runtime import (
    EmbeddedLiveTradingWorkerRuntime,
)


class BlockingFakeWorker:
    def __init__(
        self,
    ):
        self.started = False
        self.stop_requested = False

        self._stop_event: (
            asyncio.Event | None
        ) = None

    async def run(
        self,
    ) -> None:
        self.started = True

        self._stop_event = (
            asyncio.Event()
        )

        if self.stop_requested:
            self._stop_event.set()

        await self._stop_event.wait()

    def request_stop(
        self,
    ) -> None:
        self.stop_requested = True

        if self._stop_event is not None:
            self._stop_event.set()


class ReturningFakeWorker:
    def __init__(
        self,
    ):
        self.stop_requested = False

    async def run(
        self,
    ) -> None:
        return None

    def request_stop(
        self,
    ) -> None:
        self.stop_requested = True


def test_disabled_runtime_does_not_create_worker():
    async def scenario():
        factory_called = False

        def factory():
            nonlocal factory_called

            factory_called = True

            return BlockingFakeWorker()

        runtime = (
            EmbeddedLiveTradingWorkerRuntime(
                worker_factory=factory,
                enabled=False,
                restart_seconds=0.01,
                shutdown_timeout_seconds=1,
            )
        )

        started = await runtime.start()

        assert started is False
        assert runtime.running is False
        assert factory_called is False

    asyncio.run(
        scenario()
    )


def test_runtime_starts_and_stops_worker():
    async def scenario():
        workers = []

        def factory():
            worker = BlockingFakeWorker()

            workers.append(
                worker
            )

            return worker

        runtime = (
            EmbeddedLiveTradingWorkerRuntime(
                worker_factory=factory,
                enabled=True,
                restart_seconds=0.01,
                shutdown_timeout_seconds=1,
            )
        )

        started = await runtime.start()

        assert started is True
        assert runtime.running is True

        for _ in range(20):
            if (
                workers
                and workers[0].started
            ):
                break

            await asyncio.sleep(
                0.01
            )

        assert len(workers) == 1
        assert workers[0].started is True

        stopped = await runtime.stop()

        assert stopped is True
        assert (
            workers[0].stop_requested
            is True
        )
        assert runtime.running is False

    asyncio.run(
        scenario()
    )


def test_runtime_restarts_worker_after_unexpected_exit():
    async def scenario():
        workers = []

        def factory():
            worker = ReturningFakeWorker()

            workers.append(
                worker
            )

            return worker

        runtime = (
            EmbeddedLiveTradingWorkerRuntime(
                worker_factory=factory,
                enabled=True,
                restart_seconds=0.01,
                shutdown_timeout_seconds=1,
            )
        )

        await runtime.start()

        for _ in range(50):
            if len(workers) >= 2:
                break

            await asyncio.sleep(
                0.01
            )

        assert len(workers) >= 2

        await runtime.stop()

        assert runtime.running is False

    asyncio.run(
        scenario()
    ) 