from backend.app.services.roi_engine import calculate_wallet_roi


def calculate_wallet_win_rate(db, wallet_address: str):
    roi_data = calculate_wallet_roi(db, wallet_address)

    valid_positions = [
        position
        for position in roi_data["positions"]
        if position["roi_reliable"]
    ]

    winning_positions = [
        position
        for position in valid_positions
        if position["profit_loss_sol"] > 0
    ]

    losing_positions = [
        position
        for position in valid_positions
        if position["profit_loss_sol"] < 0
    ]

    total_valid = len(valid_positions)

    if total_valid > 0:
        win_rate = (len(winning_positions) / total_valid) * 100
    else:
        win_rate = 0

    return {
        "wallet": wallet_address,
        "valid_positions": total_valid,
        "winning_positions": len(winning_positions),
        "losing_positions": len(losing_positions),
        "win_rate_percent": round(win_rate, 2),
    } 