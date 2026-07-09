from backend.app.services.backtest_engine import run_wallet_backtest


def simulate_copy_trading(
    db,
    wallet_address: str,
    starting_capital: float = 10.0,
):
    backtest = run_wallet_backtest(
        db,
        wallet_address,
    )

    roi = backtest["roi"]

    final_capital = starting_capital * (1 + roi / 100)

    profit = final_capital - starting_capital

    return {
        "wallet": wallet_address,
        "starting_capital": round(starting_capital, 4),
        "final_capital": round(final_capital, 4),
        "profit": round(profit, 4),
        "roi": roi,
        "positions": backtest["positions"],
        "wins": backtest["wins"],
        "losses": backtest["losses"],
        "risk": backtest["risk"],
    } 