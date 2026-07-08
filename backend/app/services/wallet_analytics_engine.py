from backend.app.models.trade import Trade
from backend.app.services.roi_engine import calculate_wallet_roi
from backend.app.services.win_rate_engine import calculate_wallet_win_rate


def calculate_wallet_analytics(db, wallet_address: str):
    roi_data = calculate_wallet_roi(db, wallet_address)
    win_rate_data = calculate_wallet_win_rate(db, wallet_address)

    trades = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .all()
    )

    reliable_positions = [
        position
        for position in roi_data["positions"]
        if position["roi_reliable"]
    ]

    total_profit_loss_sol = sum(
        position["profit_loss_sol"]
        for position in reliable_positions
    )

    total_sol_spent = sum(
        position["total_sol_spent"]
        for position in reliable_positions
    )

    total_sol_received = sum(
        position["total_sol_received"]
        for position in reliable_positions
    )

    total_trades = len(trades)
    buy_trades = len([trade for trade in trades if trade.side == "BUY"])
    sell_trades = len([trade for trade in trades if trade.side == "SELL"])

    unique_tokens = len(
        set(
            trade.token_mint
            for trade in trades
            if trade.token_mint is not None
        )
    )

    total_sol_volume = sum(
        trade.sol_amount or 0
        for trade in trades
    )

    average_trade_size_sol = (
        total_sol_volume / total_trades
        if total_trades > 0
        else 0
    )

    buy_sell_ratio = (
        buy_trades / sell_trades
        if sell_trades > 0
        else buy_trades
    )

    if total_sol_spent > 0:
        total_roi_percent = (
            total_profit_loss_sol / total_sol_spent
        ) * 100
    else:
        total_roi_percent = 0

    profit_per_token = (
        total_profit_loss_sol / unique_tokens
        if unique_tokens > 0
        else 0
    )

    if total_profit_loss_sol > 0 and win_rate_data["win_rate_percent"] >= 60:
        risk_level = "LOW"
    elif total_profit_loss_sol < 0 and win_rate_data["win_rate_percent"] < 40:
        risk_level = "HIGH"
    else:
        risk_level = "MEDIUM"

    return {
        "wallet": wallet_address,
        "tokens_analyzed": len(roi_data["positions"]),
        "reliable_positions": len(reliable_positions),
        "total_sol_spent": round(total_sol_spent, 9),
        "total_sol_received": round(total_sol_received, 9),
        "total_profit_loss_sol": round(total_profit_loss_sol, 9),
        "total_roi_percent": round(total_roi_percent, 2),
        "win_rate_percent": win_rate_data["win_rate_percent"],
        "winning_positions": win_rate_data["winning_positions"],
        "losing_positions": win_rate_data["losing_positions"],
        "total_trades": total_trades,
        "buy_trades": buy_trades,
        "sell_trades": sell_trades,
        "unique_tokens": unique_tokens,
        "total_sol_volume": round(total_sol_volume, 9),
        "average_trade_size_sol": round(average_trade_size_sol, 9),
        "buy_sell_ratio": round(buy_sell_ratio, 2),
        "profit_per_token": round(profit_per_token, 9),
        "risk_level": risk_level,
    } 