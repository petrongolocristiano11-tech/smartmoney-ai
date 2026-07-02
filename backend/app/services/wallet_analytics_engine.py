from backend.app.services.roi_engine import calculate_wallet_roi
from backend.app.services.win_rate_engine import calculate_wallet_win_rate


def calculate_wallet_analytics(db, wallet_address: str):
    roi_data = calculate_wallet_roi(db, wallet_address)
    win_rate_data = calculate_wallet_win_rate(db, wallet_address)

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

    if total_sol_spent > 0:
        total_roi_percent = (
            total_profit_loss_sol / total_sol_spent
        ) * 100
    else:
        total_roi_percent = 0

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
    } 