from backend.app import models
from backend.app.database.base import Base


def test_paper_trading_models_are_exported():
    assert models.PaperAccount is not None
    assert models.PaperPosition is not None
    assert models.PaperOrder is not None


def test_paper_trading_tables_registered():
    table_names = set(
        Base.metadata.tables.keys()
    )

    assert "paper_accounts" in table_names
    assert "paper_positions" in table_names
    assert "paper_orders" in table_names


def test_paper_position_account_foreign_key():
    table = Base.metadata.tables[
        "paper_positions"
    ]

    foreign_key = next(
        iter(
            table.c.account_id.foreign_keys
        )
    )

    assert (
        foreign_key.target_fullname
        == "paper_accounts.id"
    )


def test_paper_order_foreign_keys():
    table = Base.metadata.tables[
        "paper_orders"
    ]

    account_foreign_key = next(
        iter(
            table.c.account_id.foreign_keys
        )
    )

    position_foreign_key = next(
        iter(
            table.c.position_id.foreign_keys
        )
    )

    assert (
        account_foreign_key.target_fullname
        == "paper_accounts.id"
    )

    assert (
        position_foreign_key.target_fullname
        == "paper_positions.id"
    )


def test_position_has_unique_account_token():
    table = Base.metadata.tables[
        "paper_positions"
    ]

    constraint_names = {
        constraint.name
        for constraint in table.constraints
    }

    assert (
        "uq_paper_positions_account_token"
        in constraint_names
    ) 