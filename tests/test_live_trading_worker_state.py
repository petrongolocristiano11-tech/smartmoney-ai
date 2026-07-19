from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.live_trading_worker import (
    LiveTradingWorkerState,
)
from backend.app.services.live_trading_worker_state import (
    acquire_worker_lease,
    get_live_worker_status,
    heartbeat_worker,
    release_worker_lease,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(
        engine
    )

    session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )()

    yield session

    session.close()
    engine.dispose()


def test_only_one_worker_can_hold_active_lease(
    db,
):
    now = datetime.now(
        timezone.utc
    )

    assert acquire_worker_lease(
        db,
        worker_id="worker-a",
        lease_seconds=60,
        now=now,
    ) is True

    assert acquire_worker_lease(
        db,
        worker_id="worker-b",
        lease_seconds=60,
        now=now,
    ) is False


def test_expired_worker_lease_can_be_recovered(
    db,
):
    now = datetime.now(
        timezone.utc
    )

    assert acquire_worker_lease(
        db,
        worker_id="worker-a",
        lease_seconds=30,
        now=now,
    ) is True

    assert acquire_worker_lease(
        db,
        worker_id="worker-b",
        lease_seconds=30,
        now=(
            now
            + timedelta(
                seconds=31
            )
        ),
    ) is True

    state = db.get(
        LiveTradingWorkerState,
        1,
    )

    assert (
        state.lease_owner
        == "worker-b"
    )


def test_worker_heartbeat_and_release_are_exposed(
    db,
):
    now = datetime.now(
        timezone.utc
    )

    acquire_worker_lease(
        db,
        worker_id="worker-a",
        lease_seconds=60,
        now=now,
    )

    assert heartbeat_worker(
        db,
        worker_id="worker-a",
        lease_seconds=60,
        now=now,
        updates={
            "status": "RUNNING",
            "active_wallets": [
                "W" * 32
            ],
            "monitored_wallets": 1,
            "active_subscriptions": 1,
            "signatures_received": 5,
        },
    ) is True

    payload = get_live_worker_status(
        db,
        now=now,
        offline_after_seconds=120,
    )

    assert payload["online"] is True
    assert payload["status"] == "RUNNING"

    assert (
        payload["signatures_received"]
        == 5
    )

    assert release_worker_lease(
        db,
        worker_id="worker-a",
        now=now,
    ) is True

    payload = get_live_worker_status(
        db,
        now=now,
    )

    assert payload["status"] == "STOPPED"
    assert payload["lease_active"] is False 