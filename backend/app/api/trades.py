from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.app.services.network_engine import build_wallet_network
from backend.app.services.early_buyer_engine import calculate_early_buyer_score
from backend.app.services.influence_engine import calculate_wallet_influence

from backend.app.services.discovery_engine import (
    discover_full_from_wallet, 
    discover_import_and_score_wallets_from_token,
    discover_wallets_from_token_onchain,
    get_traded_tokens_by_wallet,
    get_wallets_by_token,
) 
from backend.app.services.discovery_engine import (
    discover_wallets_from_token_onchain,
    get_traded_tokens_by_wallet,
    get_wallets_by_token,
) 
from backend.app.services.discovery_engine import (
    get_traded_tokens_by_wallet,
    get_wallets_by_token,
) 
from backend.app.services.discovery_engine import get_traded_tokens_by_wallet 
from backend.app.schemas.ranking import WalletRankingResponse 
from backend.app.database.session import get_db
from backend.app.models.trade import Trade
from backend.app.schemas.analytics import WalletAnalyticsResponse
from backend.app.schemas.portfolio import WalletPortfolioResponse
from backend.app.schemas.roi import WalletRoiResponse
from backend.app.schemas.smart_score import SmartScoreResponse
from backend.app.schemas.trade import TradeResponse, TradeStatsResponse
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

@router.get("/wallet/{wallet_address}", response_model=list[TradeResponse])
def get_trades_by_wallet(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .order_by(Trade.created_at.desc())
        .all()
    ) 

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


@router.get(
    "/smart-score/{wallet_address}",
    response_model=SmartScoreResponse,
)
def get_wallet_smart_score(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return calculate_smart_score(db, wallet_address)


@router.get("/ranking", response_model=WalletRankingResponse)
def get_wallet_ranking(db: Session = Depends(get_db)):
    return get_ranked_wallets(db)

@router.get("/discovery/tokens/{wallet_address}")
def discover_tokens_from_wallet(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return get_traded_tokens_by_wallet(db, wallet_address)  

@router.get("/discovery/wallets/{token_mint}")
def discover_wallets_from_token(
    token_mint: str,
    db: Session = Depends(get_db),
):
    return get_wallets_by_token(db, token_mint)  

@router.get("/discovery/onchain/wallets/{token_mint}")
def discover_wallets_from_token_onchain_endpoint(token_mint: str):
    return discover_wallets_from_token_onchain(token_mint) 

@router.post("/discovery/onchain/score/{token_mint}")
def discover_import_and_score_wallets_endpoint(
    token_mint: str,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    return discover_import_and_score_wallets_from_token(
        db=db,
        token_mint=token_mint,
        limit=limit,
    ) 

@router.post("/discovery/full/{wallet_address}")
def discover_full_pipeline(
    wallet_address: str,
    max_tokens: int = 5,
    max_wallets_per_token: int = 5,
    db: Session = Depends(get_db),
):
    return discover_full_from_wallet(
        db=db,
        wallet_address=wallet_address,
        max_tokens=max_tokens,
        max_wallets_per_token=max_wallets_per_token,
    ) 

@router.get("/network/{wallet_address}")
def get_wallet_network(
    wallet_address: str,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    return build_wallet_network(
        db=db,
        wallet_address=wallet_address,
        limit=limit,
    ) 
@router.get("/early-buyer/{wallet_address}")
def get_early_buyer_score(
    wallet_address: str,
    early_rank_threshold: int = 10,
    db: Session = Depends(get_db),
):
    return calculate_early_buyer_score(
        db=db,
        wallet_address=wallet_address,
        early_rank_threshold=early_rank_threshold,
    ) 

@router.get("/influence/{wallet_address}")
def get_wallet_influence(
    wallet_address: str,
    max_followers: int = 20,
    db: Session = Depends(get_db),
):
    return calculate_wallet_influence(
        db=db,
        wallet_address=wallet_address,
        max_followers=max_followers,
    ) 