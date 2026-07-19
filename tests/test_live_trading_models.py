from backend.app import models
from backend.app.database.base import (
    Base,
)


def test_live_trading_models_are_registered_and_exported():
    assert (
        models.LiveTradingPolicy
        is not None
    )

    assert (
        models.LiveCopyOrder
        is not None
    )

    assert (
        models.LivePosition
        is not None
    )

    assert (
        models.LiveTradingEvent
        is not None
    )

    assert {
        "live_trading_policies",
        "live_copy_orders",
        "live_positions",
        "live_trading_events",
    }.issubset(
        Base.metadata.tables
    )


def test_live_position_is_unique_per_mode_generation_and_token():
    table = Base.metadata.tables[
        "live_positions"
    ]

    assert (
        (
            "uq_live_positions_"
            "mode_generation_token"
        )
        in {
            constraint.name
            for constraint
            in table.constraints
        }
    )

def test_live_trading_generation_columns_are_registered():
    policy = Base.metadata.tables[
        "live_trading_policies"
    ]

    order = Base.metadata.tables[
        "live_copy_orders"
    ]

    position = Base.metadata.tables[
        "live_positions"
    ]

    event = Base.metadata.tables[
        "live_trading_events"
    ]

    assert "dry_run_generation" in policy.c
    assert "dry_run_started_at" in policy.c
    assert "generation" in order.c
    assert "generation" in position.c
    assert "generation" in event.c
