from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.app.services.network_engine import build_wallet_network
from backend.app.services.early_buyer_engine import calculate_early_buyer_score
from backend.app.services.influence_engine import calculate_wallet_influence
from backend.app.schemas.conviction import WalletConvictionResponse
from backend.app.services.conviction_engine import calculate_wallet_conviction
from backend.app.schemas.prediction import WalletPredictionResponse
from backend.app.services.prediction_engine import calculate_wallet_prediction
from backend.app.schemas.signals import TokenSignalsResponse
from backend.app.services.signals_engine import get_token_signals
from backend.app.schemas.backtest import WalletBacktestResponse
from backend.app.services.backtest_engine import run_wallet_backtest
from backend.app.schemas.copy_trading import CopyTradingSimulationResponse
from backend.app.services.copy_trading_engine import simulate_copy_trading
from backend.app.services.smart_discovery_engine import smart_discovery_from_wallet

from backend.app.services.holding_time_engine import calculate_wallet_holding_time
from backend.app.services.wallet_dna_engine import calculate_wallet_dna
from backend.app.services.profile_engine import build_wallet_profile
from backend.app.services.wallet_sync_service import sync_wallet 
from backend.app.services.discovery_engine import (
    discover_full_from_wallet, 
    discover_import_and_score_wallets_from_token,
    discover_wallets_from_token_onchain,
    get_traded_tokens_by_wallet,
    get_wallets_by_token,
) 

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

@router.get(
    "/conviction/{wallet_address}",
    response_model=WalletConvictionResponse,
)
def get_wallet_conviction(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return calculate_wallet_conviction(
        db,
        wallet_address,
    )  

@router.get(
    "/prediction/{wallet_address}",
    response_model=WalletPredictionResponse,
)
def get_wallet_prediction(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return calculate_wallet_prediction(
        db,
        wallet_address,
    ) 

@router.get("/holding/{wallet_address}")
def get_wallet_holding_time(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return calculate_wallet_holding_time(db, wallet_address)


@router.get("/dna/{wallet_address}")
def get_wallet_dna(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return calculate_wallet_dna(db, wallet_address) 

@router.get("/profile/{wallet_address}")
def get_wallet_profile(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return build_wallet_profile(
        db=db,
        wallet_address=wallet_address,
    ) 

@router.post("/refresh/{wallet_address}")
def refresh_wallet(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return sync_wallet(
        db=db,
        wallet_address=wallet_address,
    ) 

@router.get(
    "/signals",
    response_model=TokenSignalsResponse,
)
def get_signals(
    min_buyers: int = 2,
    db: Session = Depends(get_db),
):
    return get_token_signals(
        db=db,
        min_buyers=min_buyers,
    ) 

@router.get(
    "/backtest/{wallet_address}",
    response_model=WalletBacktestResponse,
)
def get_wallet_backtest(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    return run_wallet_backtest(
        db,
        wallet_address,
    ) 

@router.get(
    "/copy/{wallet_address}",
    response_model=CopyTradingSimulationResponse,
)
def get_copy_trading_simulation(
    wallet_address: str,
    starting_capital: float = 10.0,
    db: Session = Depends(get_db),
):
    return simulate_copy_trading(
        db=db,
        wallet_address=wallet_address,
        starting_capital=starting_capital,
    ) 
@router.post("/discovery/smart/{wallet_address}")
def smart_discovery_pipeline(
    wallet_address: str,
    max_depth: int = 2,
    max_tokens_per_wallet: int = 5,
    max_wallets_per_token: int = 5,
    min_smart_score: float = 60,
    db: Session = Depends(get_db),
):
    return smart_discovery_from_wallet(
        db=db,
        seed_wallet=wallet_address,
        max_depth=max_depth,
        max_tokens_per_wallet=max_tokens_per_wallet,
        max_wallets_per_token=max_wallets_per_token,
        min_smart_score=min_smart_score,
    ) 