from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.services.live_order_reconciliation_service import reconcile_live_orders


class FakeRpc:
    def get_signature_status(self, signature):
        return {
            "found": True,
            "confirmation_status": "finalized",
            "confirmations": None,
            "error": None,
            "slot": 123,
        }


def test_reconcile_confirms_pending_live_order():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    order = LiveCopyOrder(
        idempotency_key="r" * 64,
        source_signature="source",
        source_wallet="W" * 32,
        source_side="BUY",
        source_token_mint="T" * 32,
        mode="LIVE",
        generation=1,
        status="FILLED",
        input_mint="I" * 32,
        output_mint="O" * 32,
        requested_input_amount_raw=1,
        requested_value_sol=0.01,
        slippage_bps=20,
        transaction_signature="signature",
        reconciliation_status="PENDING",
    )
    db.add(order)
    db.commit()

    summary = reconcile_live_orders(db, rpc_client=FakeRpc())
    db.refresh(order)

    assert summary["confirmed"] == 1
    assert order.reconciliation_status == "CONFIRMED"
    assert order.confirmation_status == "finalized"
    assert order.confirmed_at is not None
    db.close()
    engine.dispose()
