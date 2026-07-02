from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.app.services.portfolio_engine import build_wallet_portfolio 
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

@router.get("/stats")
def get_trade_stats(db: Session = Depends(get_db)):
    total_trades = db.query(Trade).count()
    unique_wallets = db.query(Trade.wallet_address).distinct().count()
    unique_tokens = db.query(Trade.token_mint).distinct().count()
    buy_trades = db.query(Trade).filter(Trade.side == "BUY").count()
    sell_trades = db.query(Trade).filter(Trade.side == "SELL").count()

    return {
        "total_trades": total_trades,
        "unique_wallets": unique_wallets,
        "unique_tokens": unique_tokens,
        "buy_trades": buy_trades,
        "sell_trades": sell_trades,
    } 
@router.get("/portfolio/{wallet_address}")
def get_wallet_portfolio(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return build_wallet_portfolio(db, wallet_address) 