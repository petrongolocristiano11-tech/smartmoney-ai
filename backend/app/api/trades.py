from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.schemas.analytics import WalletAnalyticsResponse 
from backend.app.schemas.roi import WalletRoiResponse 
from backend.app.schemas.portfolio import WalletPortfolioResponse
from backend.app.schemas.trade import TradeResponse, TradeStatsResponse 
from backend.app.schemas.trade import TradeResponse, TradeStatsResponse 
from backend.app.schemas.trade import TradeResponse 
from backend.app.database.session import get_db
from backend.app.models.trade import Trade
from backend.app.services.portfolio_engine import build_wallet_portfolio
from backend.app.services.ranking_engine import get_ranked_wallets
from backend.app.services.roi_engine import calculate_wallet_roi
from backend.app.services.smart_score_engine import calculate_smart_score
from backend.app.services.wallet_analytics_engine import calculate_wallet_analytics
from backend.app.services.win_rate_engine import calculate_wallet_win_rate

router = APIRouter(
    prefix="/trades",
    tags=["Trades"],
)


@router.get("", response_model=list[TradeResponse])
def get_trades(db: Session = Depends(get_db)):
    return db.query(Trade).all()


@router.get("/stats", response_model=TradeStatsResponse)
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


@router.get("/portfolio/{wallet_address}", response_model=WalletPortfolioResponse) 
def get_wallet_portfolio(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return build_wallet_portfolio(db, wallet_address)


@router.get("/roi/{wallet_address}", response_model=WalletRoiResponse) 
def get_wallet_roi(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return calculate_wallet_roi(db, wallet_address)


@router.get("/win-rate/{wallet_address}")
def get_wallet_win_rate(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return calculate_wallet_win_rate(db, wallet_address)


@router.get(
    "/analytics/{wallet_address}",
    response_model=WalletAnalyticsResponse,
) 
def get_wallet_analytics(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return calculate_wallet_analytics(db, wallet_address)


@router.get("/smart-score/{wallet_address}")
def get_wallet_smart_score(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return calculate_smart_score(db, wallet_address)


@router.get("/ranking")
def get_wallet_ranking(db: Session = Depends(get_db)):
    return get_ranked_wallets(db) 