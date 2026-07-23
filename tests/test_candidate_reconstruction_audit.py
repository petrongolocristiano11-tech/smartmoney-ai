from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.candidate_reconstruction_audit import (
    CandidateReconstructionAuditRun,
)
from backend.app.models.discovered_wallet import (
    DiscoveredWallet,
)
from backend.app.models.trade import Trade
from backend.app.services.candidate_reconstruction_audit_service import (
    run_candidate_reconstruction_audit,
)


NOW = datetime(
    2026,
    7,
    23,
    12,
    0,
    tzinfo=timezone.utc,
)
WALLET = "R" * 32


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )()

    session.add(
        DiscoveredWallet(
            wallet_address=WALLET,
            smart_score=70,
            activity_classification="POCO_ATTIVO",
            quality_classification="OSSERVAZIONE",
        )
    )
    session.commit()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_trade(
    db,
    *,
    signature,
    token,
    side,
    token_amount,
    sol_amount,
    days,
    hours=0,
):
    db.add(
        Trade(
            signature=signature,
            wallet_address=WALLET,
            side=side,
            source="TEST",
            token_mint=token,
            token_amount=token_amount,
            sol_amount=sol_amount,
            success=True,
            block_time=(
                NOW
                - timedelta(
                    days=days,
                    hours=hours,
                )
            ),
        )
    )


def test_audit_builds_nine_safe_scenarios(db):
    token = "A" * 32

    add_trade(
        db,
        signature="buy-a",
        token=token,
        side="BUY",
        token_amount=100,
        sol_amount=0.05,
        days=3,
    )
    add_trade(
        db,
        signature="sell-a",
        token=token,
        side="SELL",
        token_amount=100,
        sol_amount=0.08,
        days=2,
    )
    db.commit()

    run = run_candidate_reconstruction_audit(
        db,
        wallet_address=WALLET,
        now=NOW,
    )

    assert run.status == "COMPLETED"
    assert len(run.scenario_results) == 9
    assert run.safety["helius_requests"] == 0
    assert run.safety["jupiter_requests"] == 0
    assert run.safety["live_enabled"] is False
    assert run.safety["generation_created"] is False

    assert (
        db.query(
            CandidateReconstructionAuditRun
        ).count()
        == 1
    )


def test_partial_sell_is_proportional(db):
    token = "B" * 32

    add_trade(
        db,
        signature="buy-b",
        token=token,
        side="BUY",
        token_amount=100,
        sol_amount=0.05,
        days=4,
    )
    add_trade(
        db,
        signature="partial-sell-b",
        token=token,
        side="SELL",
        token_amount=25,
        sol_amount=0.025,
        days=3,
    )
    add_trade(
        db,
        signature="final-sell-b",
        token=token,
        side="SELL",
        token_amount=75,
        sol_amount=0.09,
        days=2,
    )
    db.commit()

    run = run_candidate_reconstruction_audit(
        db,
        wallet_address=WALLET,
        now=NOW,
    )

    baseline = run.baseline_metrics

    assert baseline["partial_sell_events"] == 1
    assert baseline["completed_positions"] == 1
    assert (
        baseline["exclusion_summary"][
            "PARTIAL_SOURCE_SELL"
        ]
        == 1
    )


def test_position_limit_is_reported(db):
    tokens = [
        chr(67 + index) * 32
        for index in range(7)
    ]

    for index, token in enumerate(tokens):
        add_trade(
            db,
            signature=f"buy-{index}",
            token=token,
            side="BUY",
            token_amount=100,
            sol_amount=0.05,
            days=4,
            hours=index,
        )

    db.commit()

    run = run_candidate_reconstruction_audit(
        db,
        wallet_address=WALLET,
        now=NOW,
        baseline_starting_capital_sol=1,
        baseline_max_open_positions=5,
    )

    assert (
        run.exclusion_summary[
            "MAX_OPEN_POSITIONS_REACHED"
        ]
        == 2
    )
    assert (
        "POSITION_LIMIT_BINDING"
        in run.diagnoses
    )


def test_return_without_best_trade_is_calculated(db):
    multipliers = (1.1, 1.1, 5.0)

    for index, multiplier in enumerate(
        multipliers
    ):
        token = chr(75 + index) * 32

        add_trade(
            db,
            signature=f"buy-profit-{index}",
            token=token,
            side="BUY",
            token_amount=100,
            sol_amount=0.05,
            days=8 - index * 2,
        )
        add_trade(
            db,
            signature=f"sell-profit-{index}",
            token=token,
            side="SELL",
            token_amount=100,
            sol_amount=0.05 * multiplier,
            days=7 - index * 2,
        )

    db.commit()

    run = run_candidate_reconstruction_audit(
        db,
        wallet_address=WALLET,
        now=NOW,
    )

    baseline = run.baseline_metrics

    assert (
        baseline[
            "top_1_profit_concentration_percent"
        ]
        > 50
    )
    assert (
        baseline[
            "return_without_best_trade_percent"
        ]
        < baseline["total_return_percent"]
    )


def test_unknown_wallet_is_rejected(db):
    with pytest.raises(
        ValueError,
        match="Wallet scoperto non trovato",
    ):
        run_candidate_reconstruction_audit(
            db,
            wallet_address="Z" * 32,
            now=NOW,
        )
