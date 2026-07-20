import asyncio

from backend.app.services.live_position_monitor_runtime import (
    EmbeddedPositionMonitorRuntime,
)


class BlockingWorker:
    def __init__(self):
        self.started = False
        self.stop_requested = False
        self._stop_event: asyncio.Event | None = None

    async def run(self) -> None:
        self.started = True
        self._stop_event = asyncio.Event()
        if self.stop_requested:
            self._stop_event.set()
        await self._stop_event.wait()

    def request_stop(self) -> None:
        self.stop_requested = True
        if self._stop_event is not None:
            self._stop_event.set()


class ReturningWorker:
    async def run(self) -> None:
        return None

    def request_stop(self) -> None:
        return None


def test_disabled_position_monitor_runtime_does_not_start():
    async def scenario():
        called = False

        def factory():
            nonlocal called
            called = True
            return BlockingWorker()

        runtime = EmbeddedPositionMonitorRuntime(
            worker_factory=factory,
            enabled=False,
            restart_seconds=0.01,
            shutdown_timeout_seconds=1,
        )
        assert await runtime.start() is False
        assert runtime.running is False
        assert called is False

    asyncio.run(scenario())


def test_position_monitor_runtime_starts_and_stops():
    async def scenario():
        workers = []

        def factory():
            worker = BlockingWorker()
            workers.append(worker)
            return worker

        runtime = EmbeddedPositionMonitorRuntime(
            worker_factory=factory,
            enabled=True,
            restart_seconds=0.01,
            shutdown_timeout_seconds=1,
        )
        assert await runtime.start() is True
        for _ in range(50):
            if workers and workers[0].started:
                break
            await asyncio.sleep(0.01)
        assert workers and workers[0].started is True
        assert await runtime.stop() is True
        assert workers[0].stop_requested is True
        assert runtime.running is False

    asyncio.run(scenario())


def test_position_monitor_runtime_restarts_after_unexpected_exit():
    async def scenario():
        workers = []

        def factory():
            worker = ReturningWorker()
            workers.append(worker)
            return worker

        runtime = EmbeddedPositionMonitorRuntime(
            worker_factory=factory,
            enabled=True,
            restart_seconds=0.01,
            shutdown_timeout_seconds=1,
        )
        await runtime.start()
        for _ in range(50):
            if len(workers) >= 2:
                break
            await asyncio.sleep(0.01)
        assert len(workers) >= 2
        await runtime.stop()
        assert runtime.running is False

    asyncio.run(scenario())
