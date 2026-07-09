from backend.app.services.wallet_analytics_engine import (
    calculate_wallet_analytics,
)


def run_wallet_backtest(db, wallet_address: str):
    analytics = calculate_wallet_analytics(
        db,
        wallet_address,
    )

    positions = analytics["reliable_positions"]

    wins = analytics["winning_positions"]
    losses = analytics["losing_positions"]

    average_profit = (
        analytics["total_profit_loss_sol"] / positions
        if positions > 0
        else 0
    )

    return {
        "wallet": wallet_address,
        "positions": positions,
        "wins": wins,
        "losses": losses,
        "win_rate": analytics["win_rate_percent"],
        "roi": analytics["total_roi_percent"],
        "profit_loss_sol": analytics["total_profit_loss_sol"],
        "average_profit_per_position": round(
            average_profit,
            6,
        ),
        "risk": analytics["risk_level"],
    } 