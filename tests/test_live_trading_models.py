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


def test_live_position_is_unique_per_mode_and_token():
    table = Base.metadata.tables[
        "live_positions"
    ]

    assert (
        "uq_live_positions_mode_token"
        in {
            constraint.name
            for constraint
            in table.constraints
        }
    ) 