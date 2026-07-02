from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.models.trade import Trade

router = APIRouter(
    prefix="/trades",
    tags=["Trades"],
)


@router.get("")
def get_trades(db: Session = Depends(get_db)):
    return db.query(Trade).all() 
@router.post("/test")
def create_test_trade(db: Session = Depends(get_db)):
    trade = Trade(
        signature="test_signature",
        wallet_address="TEST_WALLET",
        side="BUY",
        source="TEST",
        token_mint="TEST_TOKEN",
        token_amount=100,
        sol_amount=1.5,
        fee=0.000005,
        success=True,
    )

    db.add(trade)
    db.commit()
    db.refresh(trade)

    return trade 
    